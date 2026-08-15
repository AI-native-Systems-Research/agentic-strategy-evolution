"""Stage runner for ``kind: optimization`` campaigns.

Composes the pure modules in this subpackage into one Nous iteration, and
owns the phase transitions. ``run_iteration`` delegates here on its first
line when ``validate.campaign_kind`` says ``optimization``; the reflective
path below that branch is untouched.

Phase mapping is deliberately the SAME machine the reflective kind uses
(DESIGN -> HUMAN_DESIGN_GATE -> EXECUTE_ANALYZE -> HUMAN_FINDINGS_GATE ->
DONE), so ``Engine``, ``HumanGate``, ``append_ledger_row``,
``finalize_iteration`` and the ``best_found`` / ``meta_findings`` writers
are reused rather than reimplemented. What differs is what DESIGN produces
and how EXECUTE_ANALYZE runs it:

  * ``verify``  — one model call authors the mechanism + its native tests.
  * ``screen``  — DESIGN emits a design matrix with ZERO model calls.
  * ``refine``  — same, plus curvature on the surviving factors.
  * ``confirm`` — one model call interprets the fitted surface.

Three checks hard-fail regardless of gate approval, because auto-approve is
this kind's default (spec §7.1) and removing the human must not remove the
checks:

  1. Executed configs drifting from the pre-registered ``design_matrix.json``
     (``matrix.check_fidelity``) — a silently skipped cell changes the
     design's real resolution, so tolerating it would let the campaign
     overstate what it can estimate.
  2. A held-out metric reaching a fitting input.
  3. A ``correctness`` relation violation.

NOT YET WIRED — ``locked_parameters`` deviation. The spec lists it as a
fourth such check, and ``validate._validate_locked_parameters`` exists, but
it is reached only from bundle validation and this path has no
``bundle.yaml`` / ``experiment_spec`` to compare against. An earlier version
of this docstring claimed the check; it did not exist, which is worse than
omitting it, because the claim would stop the next reader from adding it.
Wiring it needs a locked-parameters-vs-executed-config comparison built for
the matrix path. Tracked as a follow-up; do not re-add the claim until the
code is there.

A ``behavioral`` relation violation is NOT in that list. A monotonicity
break is a discovery — the motivating case is a lever measured -9.5% alone
yet required for the winning compound — so it is recorded as a finding and
the stage advances.

TODO(follow-up): ``config_runner`` and ``integrity_check`` arrive as
injected callables. Production wiring to real subprocess invocations of the
campaign's build/benchmark command and ``integrity_command`` is not built
here; tests inject fakes. Keeping the seam injected is also what makes this
module testable without subprocesses at all.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from orchestrator.optimize import artifacts, matrix, relations, runner
from orchestrator.optimize.effects import fit_effects, solve_stationary_point
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.stage import (
    Stage,
    decide_after_refine,
    decide_after_screen,
    stage_for_iteration,
)

logger = logging.getLogger(__name__)


class OptimizationAborted(RuntimeError):
    """A hard-fail that must stop the campaign regardless of gate approval."""


@dataclass(frozen=True)
class StageOutcome:
    """What one optimization stage produced.

    ``decision`` is None for stages that make no next-stage choice
    (``verify`` and ``confirm``).
    """

    stage: str
    iteration: int
    n_runs: int
    n_complete: int
    n_rejected: int
    n_infeasible: int
    n_failed: int
    triggers: tuple[str, ...] = ()
    surviving: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()


def _opt_block(campaign: dict) -> dict:
    opt = campaign.get("optimization")
    if not isinstance(opt, dict):
        raise OptimizationAborted(
            "kind: optimization requires an 'optimization' block; "
            "see docs/optimization-campaign-guide.md",
        )
    return opt


def _check_correctness_relations(
    factors, test_results: dict[str, bool] | None,
) -> tuple[list, list]:
    """Reconcile declared relations against native-test results.

    Returns ``(correctness_failures, behavioral_failures)``. A declared
    relation absent from the results is a FAILURE by ``reconcile``'s own
    semantics — a typo'd ``native_test`` must never look satisfied.
    """
    verdicts = relations.reconcile(factors, test_results or {})
    return relations.classify_failures(verdicts)


def _assert_all_behavioral(behavioral_failures) -> tuple:
    """Guard the correctness/behavioral split at the call site.

    ``stage.py`` does not inspect ``RelationVerdict.kind``, so a
    correctness verdict smuggled into ``behavioral_failures`` would raise a
    behavioral trigger — which UNDER-reacts, since behavioral triggers
    advance the stage while correctness failures must abort. This is the
    seam where the contract is enforceable, so enforce it here.
    """
    for v in behavioral_failures:
        if getattr(v, "kind", None) != "behavioral":
            raise OptimizationAborted(
                f"internal error: relation {getattr(v, 'relation_id', '?')!r} has "
                f"kind={getattr(v, 'kind', None)!r} but was passed as a behavioral "
                f"failure. Wire only classify_failures()'s SECOND return value "
                f"here; correctness failures must abort the campaign instead.",
            )
    return tuple(behavioral_failures)


def _fitting_responses(outcomes, response_spec: dict, primary: str) -> list[float]:
    """Primary-metric values for the rows admissible to fitting.

    ``rejected`` rows are untrustworthy (invariant violation, above the
    physical ceiling, failed integrity check) and are excluded.
    ``infeasible`` rows are trustworthy — they say the config is
    inadmissible, which is real information about the space — but they are
    still excluded from the fit, per spec §6.4.
    """
    held_out = {str(m) for m in (response_spec.get("held_out") or [])}
    if primary in held_out:
        raise OptimizationAborted(
            f"primary metric {primary!r} is also declared held_out; the campaign "
            f"would be optimizing against its own generalization check",
        )
    values: list[float] = []
    for o in outcomes:
        if o.status != "complete":
            values.append(float("nan"))
            continue
        resp = o.response or {}
        leaked = held_out & set(resp)
        if leaked:
            raise OptimizationAborted(
                f"held-out metric(s) {sorted(leaked)} reached a fitting input for "
                f"row {o.row_index}; held-out values belong on RunOutcome.held_out",
            )
        raw = resp.get(primary)
        if raw is None:
            # Distinct from "absent": the target emitted the key with no
            # value, which a benchmark that ran but could not compute the
            # statistic will realistically do. Carry NaN so the row is
            # excluded, and let the guard below report it by row index.
            values.append(float("nan"))
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError) as exc:
            raise OptimizationAborted(
                f"row {o.row_index}: primary metric {primary!r} is "
                f"{raw!r}, which is not a number. The response metric must "
                f"be numeric for the fit; a target emitting a string or a "
                f"structure here is an instrumentation mismatch, not a "
                f"measurement.",
            ) from exc

    # Refuse to fit on NaN. A single non-complete run poisons the ENTIRE
    # fit through the normal equations — verified: one NaN among eight runs
    # makes every effect estimate and the intercept NaN. The failure is
    # silent: the artifacts stay schema-valid (jsonschema accepts NaN as
    # "number"), so a campaign would emit a confident-looking, all-NaN
    # effects.json. The spec's stance on partial failure is "degrade the
    # claim, not the data" — refit on the completed rows and report the
    # reduced resolution honestly — and emitting NaN is neither of those.
    # `infeasible` is NOT a measurement failure: the config ran, produced
    # trustworthy numbers, and violated a declared constraint. That is real
    # information about the design space (spec §6.4), and a constrained
    # design will routinely have inadmissible corners — aborting on one
    # would make constraints unusable. Those rows are excluded from the fit
    # by carrying NaN, which is the same mechanism, so distinguish them from
    # rows that genuinely failed to measure.
    unmeasured = [
        o.row_index for o, v in zip(outcomes, values)
        if v != v and o.status not in ("infeasible", "rejected")
    ]
    if unmeasured:
        raise OptimizationAborted(
            f"{len(unmeasured)} of {len(values)} runs produced no usable "
            f"measurement (row_index {unmeasured}). Fitting would "
            f"NaN-poison every coefficient while still producing "
            f"schema-valid artifacts. Re-run the failed configurations, or "
            f"refit on the completed subset and report the reduced "
            f"resolution.",
        )
    return values


def run_stage(
    campaign: dict,
    work_dir: Path,
    *,
    iteration: int,
    stage: Stage | str | None = None,
    config_runner: Callable | None = None,
    integrity_check: Callable | None = None,
    test_results: dict[str, bool] | None = None,
    auto_approve: bool = True,
    gate=None,
    **_ignored,
):
    """Run one optimization-kind iteration and return an ``IterationOutcome``.

    Imports ``IterationOutcome`` lazily to avoid a circular import:
    ``iteration`` imports this module inside ``run_iteration``.
    """
    from orchestrator.engine import Engine
    from orchestrator.gates import HumanGate
    from orchestrator.iteration import (
        IterationOutcome,
        _enter_phase,
        finalize_iteration,
    )
    from orchestrator.ledger import append_ledger_row

    opt = _opt_block(campaign)
    resolved = stage if stage is not None else stage_for_iteration(campaign, iteration)
    stage_name = getattr(resolved, "value", None) or str(resolved)

    factors = parse_factors(opt["factors"])
    response_spec = opt.get("response") or {}
    primary = ((response_spec.get("primary") or {}).get("metric")) or ""
    invariants = ((opt.get("design_space") or {}).get("invariants")) or []

    iter_dir = Path(work_dir) / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    engine = Engine(work_dir)
    gate = gate or (HumanGate(auto_response="approve") if auto_approve else HumanGate())

    # ── verify: the native property/metamorphic tests are the gate ──────
    #
    # A correctness violation aborts before any design budget is spent.
    # That is the whole point of running verify first: 60 benchmark runs
    # against a broken mechanism measure the wrong system precisely.
    correctness_failures, behavioral_failures = _check_correctness_relations(
        factors, test_results,
    )
    if stage_name == Stage.VERIFY.value:
        if _enter_phase(engine, "DESIGN", work_dir):
            artifacts.write_relations(
                iter_dir, relations.reconcile(factors, test_results or {}),
            )
        if correctness_failures:
            ids = ", ".join(str(v.relation_id) for v in correctness_failures)
            raise OptimizationAborted(
                f"correctness relation(s) failed at verify: {ids}. The apparatus is "
                f"broken, so any measurement would describe the wrong system. Fix "
                f"the mechanism (or its native tests) before spending design budget.",
            )
        _enter_phase(engine, "HUMAN_DESIGN_GATE", work_dir)
        _enter_phase(engine, "EXECUTE_ANALYZE", work_dir)
        _enter_phase(engine, "HUMAN_FINDINGS_GATE", work_dir)
        append_ledger_row(work_dir, iteration)
        return _terminal_outcome(engine, campaign, stage_name, IterationOutcome)

    if correctness_failures:
        ids = ", ".join(str(v.relation_id) for v in correctness_failures)
        raise OptimizationAborted(
            f"correctness relation(s) failed: {ids}; refusing to fit on "
            f"measurements from a broken apparatus",
        )

    # ── DESIGN: generate and pre-register the matrix. Zero model calls. ──
    design_cfg = opt.get("design") or {}

    # Rebuild deterministically rather than re-reading the artifact: the
    # generators and run-order seed are fixed inputs, so this reproduces the
    # payload just written. check_fidelity below compares the executed runs
    # against THIS payload, which is the same object that was pre-registered.
    design = _build_design(factors, design_cfg, stage_name)
    payload = matrix.matrix_payload(design, factors, run_order_seed=iteration)
    rows = matrix.expand(design, factors)
    if _enter_phase(engine, "DESIGN", work_dir):
        artifacts.write_design_matrix(iter_dir, payload)

    _enter_phase(engine, "HUMAN_DESIGN_GATE", work_dir)

    # ── EXECUTE_ANALYZE: the tokenless sweep ────────────────────────────
    if config_runner is None:
        raise OptimizationAborted(
            "run_stage needs a config_runner callable (row -> observation dict). "
            "Production wiring to the campaign's build/benchmark command is a "
            "follow-up; tests inject a fake.",
        )
    _enter_phase(engine, "EXECUTE_ANALYZE", work_dir)
    by_index = {r.row_index: r for r in rows}
    outcomes = runner.execute_design(
        rows, runner=config_runner, response_spec=response_spec,
        invariants=invariants, factors=factors,
        integrity_check=integrity_check,
        on_row=lambda outcome: artifacts.append_run(
            iter_dir, _run_row(by_index[outcome.row_index], outcome),
        ),
    )

    # Fidelity: what ran must match what was pre-registered. Hard-fails
    # even under auto-approve — the #246 discipline extended to the matrix.
    violations = matrix.check_fidelity(payload, artifacts.read_runs(iter_dir))
    if violations:
        raise OptimizationAborted(
            "executed configurations deviate from the pre-registered "
            "design_matrix.json:\n  " + "\n  ".join(violations),
        )

    ys = _fitting_responses(outcomes, response_spec, primary)
    # The factor_ids MUST match the design's column order and width. At
    # refine, _build_design builds a central composite over only the
    # refinable factors, so passing every factor id here would misalign the
    # model matrix (verified: it raises IndexError). Derive the ids from the
    # design that was actually built.
    fitted_ids = _design_factor_ids(factors, design_cfg, stage_name)
    fit = fit_effects(design, ys, factor_ids=fitted_ids)
    artifacts.write_effects(iter_dir, fit, factors=factors, stage=stage_name)

    behavioral = _assert_all_behavioral(behavioral_failures)
    if stage_name == Stage.REFINE.value:
        stationary = solve_stationary_point(fit, fitted_ids)
        fitted_factors = [f for f in factors if f.id in set(fitted_ids)]
        decision = decide_after_refine(
            fit, fitted_factors, stationary, behavioral_failures=behavioral,
        )
    else:
        decision = decide_after_screen(fit, factors, behavioral_failures=behavioral)

    # project_findings takes `decision` as a STRING (it lands in findings
    # metadata and in the discrepancy_analysis prose). Pass the rationale,
    # which is the human/AI-readable account of what the stage rule decided
    # and why — and which stage.py guarantees is never empty precisely so
    # this projection cannot produce an evidence-free finding.
    decision_summary = decision.rationale
    if decision.triggers:
        decision_summary += (
            " | triggers: " + ", ".join(t.value for t in decision.triggers)
        )
    findings = artifacts.project_findings(
        fit, factors=factors, stage=stage_name, decision=decision_summary,
        iteration=iteration, bundle_ref=f"runs/iter-{iteration}/design_matrix.json",
    )
    _write_json(iter_dir / "findings.json", findings)
    # principle_updates.json is a BARE LIST on disk (verified against real
    # campaign artifacts, and required by iteration._merge_principles, which
    # raises on a dict). project_principle_updates returns the
    # principles.schema.json wrapper {"principles": [...]}, which is the
    # shape of the merged principles.json store, not of this per-iteration
    # file — so unwrap it here.
    updates = artifacts.project_principle_updates(
        fit, factors=factors, stage=stage_name,
    )
    _write_json(
        iter_dir / "principle_updates.json",
        updates["principles"] if isinstance(updates, dict) else updates,
    )
    artifacts.write_relations(
        iter_dir, relations.reconcile(factors, test_results or {}),
    )

    _enter_phase(engine, "HUMAN_FINDINGS_GATE", work_dir)
    finalize_iteration(
        work_dir=work_dir, iter_dir=iter_dir, iteration=iteration, campaign=campaign,
    )
    append_ledger_row(work_dir, iteration)

    statuses = [o.status for o in outcomes]
    logger.info(
        "optimization stage %s (iter %d): %d rows, %d complete",
        stage_name, iteration, len(outcomes), statuses.count("complete"),
    )
    return _terminal_outcome(engine, campaign, stage_name, IterationOutcome)


def _terminal_outcome(engine, campaign: dict, stage_name: str, outcome_enum):
    """Transition to DONE and report COMPLETED on the campaign's last stage.

    run_campaign only stops on COMPLETED / ABORTED / REDESIGN, so returning
    CONTINUE from the final stage makes it call one more iteration —
    stage_for_iteration then clamps past the end of the stage list and
    returns the final stage again, re-running it indefinitely. That looks
    correct only when max_iterations happens to equal the stage count.
    """
    if _is_final_stage(campaign, stage_name):
        engine.transition("DONE")
        return outcome_enum.COMPLETED
    return outcome_enum.CONTINUE


def _is_final_stage(campaign: dict, stage_name: str) -> bool:
    """Whether ``stage_name`` is the last stage this campaign will run.

    An explicit ``optimization.stages`` list wins; otherwise ``confirm`` is
    terminal. Getting this wrong in either direction is costly: too eager
    ends the campaign a stage early, too lax means run_campaign never sees
    COMPLETED and re-runs the final stage forever (since stage_for_iteration
    clamps past the end).
    """
    stages = ((campaign.get("optimization") or {}).get("stages")) or None
    if isinstance(stages, list) and stages:
        last = stages[-1]
        return stage_name == (getattr(last, "value", None) or str(last))
    return stage_name == Stage.CONFIRM.value


def _design_factor_ids(factors, design_cfg: dict, stage_name: str) -> tuple[str, ...]:
    """The factor ids whose columns the stage's design actually contains.

    Must agree with ``_build_design``: at refine the design spans only the
    refinable factors, so fitting with every declared id would misalign the
    model matrix.
    """
    from orchestrator.optimize.factors import is_refinable

    ids = tuple(f.id for f in factors)
    if stage_name == Stage.REFINE.value:
        refinable = tuple(f.id for f in factors if is_refinable(f))
        return refinable or ids
    return ids


def _build_design(factors, design_cfg: dict, stage_name: str):
    """Design for this stage: a screen matrix, or a response surface."""
    from orchestrator.optimize.design import (
        central_composite,
        fractional_factorial,
        full_factorial,
        is_tabulated,
        with_center_points,
    )
    from orchestrator.optimize.factors import is_refinable

    ids = tuple(f.id for f in factors)
    if stage_name == Stage.REFINE.value:
        refinable = tuple(f.id for f in factors if is_refinable(f))
        cfg = design_cfg.get("refine") or {}
        return central_composite(
            refinable or ids, center_points=int(cfg.get("center_points", 4)),
        )
    cfg = design_cfg.get("screen") or {}
    resolution = int(cfg.get("resolution", 5))
    # A fractional design only exists where one is tabulated. Below that
    # factor count the FULL factorial already achieves the resolution (it
    # aliases nothing), so use it rather than failing — e.g. 3 factors at
    # resolution V is 8 runs with every 2-factor interaction estimable.
    # Task 10's validator is what rejects a request no design can satisfy;
    # this function must not fail on one a full factorial covers.
    base = (
        fractional_factorial(ids, resolution=resolution)
        if is_tabulated(len(ids), resolution)
        else full_factorial(ids)
    )
    return with_center_points(base, int(cfg.get("center_points", 4)))


def _run_row(row, outcome) -> dict:
    """One ``runs.jsonl`` row from a ConfigRow + RunOutcome pair."""
    return {
        "row_index": row.row_index,
        "levels": dict(row.levels),
        "role": row.role,
        "replicate": row.replicate,
        "status": outcome.status,
        "response": dict(outcome.response or {}),
        "held_out": dict(getattr(outcome, "held_out", {}) or {}),
        "manipulation": list(outcome.manipulation or []),
        "invariants": list(outcome.invariants or []),
        "duration_ms": int(outcome.duration_ms or 0),
        "error": outcome.error or "",
    }


def _write_json(target: Path, payload) -> Path:
    import json

    from orchestrator.util import atomic_write

    atomic_write(Path(target), json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return Path(target)
