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

``config_runner`` and ``integrity_check`` remain injected callables — that
seam is what makes this module testable without subprocesses — but a real
run no longer needs a caller to supply them. ``run_stage`` resolves both from
the campaign itself: ``optimization.run_command`` becomes a config runner via
``runner.make_config_runner`` and ``optimization.test_command`` is executed by
``runner.run_test_command``. Until that wiring existed, every real campaign
aborted at ``verify`` (nothing executed the test command, so every relation
reconciled as "declared but not executed") or at ``screen`` (no config
runner), which made the whole kind unusable end to end while 1600+ tests
stayed green — they inject fakes at exactly the seams that were missing.
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
    model: str | None = None,
    sdk_runner: Callable | None = None,
    **_ignored,
):
    """Run one optimization-kind iteration and return an ``IterationOutcome``.

    Imports ``IterationOutcome`` lazily to avoid a circular import:
    ``iteration`` imports this module inside ``run_iteration``.

    ``sdk_runner`` is the injection seam for the ``build`` stage's single
    agent call, mirroring ``SDKDispatcher(sdk_runner=...)``. Every other
    stage is pure Python and ignores it.
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

    # PRODUCTION WIRING (closes the gap that made this kind unusable end to
    # end). `test_command` was declared in the schema and documented in the
    # guide, but nothing executed it, so `test_results` was always None,
    # every relation reconciled as "declared but not executed", and every
    # real campaign aborted at its verify stage. Tests still inject fakes —
    # the injected seam remains the contract — but a real run now resolves
    # both callables from the campaign itself.
    repo = (campaign.get("target_system") or {}).get("repo_path")

    # Resolve the stage BEFORE running the test command. On a `build`
    # iteration the mechanism does not exist yet, so running the target's
    # tests would burn a test cycle to learn something already known: the
    # declared identifiers are missing. Worse, `go test -run <pattern>` exits
    # 0 with "no tests to run" when the pattern matches nothing, so the
    # pre-build run looks like a pass at the shell level. Deciding the stage
    # first keeps that noise out of the log and out of the artifacts.
    _resolved_early = (
        stage if stage is not None else stage_for_iteration(campaign, iteration)
    )
    _stage_early = getattr(_resolved_early, "value", None) or str(_resolved_early)
    _is_build = _stage_early == Stage.BUILD.value

    if _is_build:
        from orchestrator.optimize import build as build_mod

        _factors_for_build = parse_factors(opt["factors"])
        build_mod.run_build(
            campaign, work_dir,
            iteration=iteration,
            declared_tests=build_mod.declared_native_tests(_factors_for_build),
            model=model,
            max_turns=_build_max_turns(campaign),
            sdk_runner=sdk_runner,
        )

    if not _is_build and test_results is None and opt.get("test_command") and repo:
        # Persist the raw test output next to the iteration's artifacts. A
        # verify abort ends the campaign, so this text is the only record of
        # WHY, and re-running by hand may not reproduce a timeout or an
        # ordering-dependent failure.
        raw = runner.run_test_command(
            opt["test_command"], cwd=Path(repo),
            log_path=Path(work_dir) / "runs" / f"iter-{iteration}" / "test_output.log",
        )
        test_results = runner.match_declared_tests(parse_factors(opt["factors"]), raw)
        logger.info(
            "test_command reported %d test(s); %d matched a declared "
            "native_test", len(raw), len(test_results),
        )
    if config_runner is None and opt.get("run_command") and repo:
        config_runner = runner.make_config_runner(
            opt["run_command"], cwd=Path(repo),
            metric_path=((opt.get("response") or {}).get("primary") or {}).get(
                "metric", "",
            ),
            log_dir=Path(work_dir) / "runs" / f"iter-{iteration}" / "failed_runs",
        )

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

    # ── build: the mechanism was just authored; do NOT gate on tests here ──
    #
    # The build call already ran (above, before the test command, so the
    # target's tests are not run against code that did not exist yet). This
    # stage deliberately makes no correctness judgement: `verify` is the gate,
    # and letting the stage that wrote the code also certify it would mean the
    # model grading its own work. Ending the iteration here hands the next
    # iteration to verify, which runs the real test command against the real
    # repo and aborts if anything the campaign declared is missing or failing.
    if stage_name == Stage.BUILD.value:
        _enter_phase(engine, "DESIGN", work_dir)
        _enter_phase(engine, "HUMAN_DESIGN_GATE", work_dir)
        _enter_phase(engine, "EXECUTE_ANALYZE", work_dir)
        _enter_phase(engine, "HUMAN_FINDINGS_GATE", work_dir)
        append_ledger_row(work_dir, iteration)
        return _terminal_outcome(engine, campaign, stage_name, IterationOutcome)

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
            raise OptimizationAborted(_verify_abort_message(correctness_failures))
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
    design = _build_design(factors, design_cfg, stage_name, work_dir)
    payload = matrix.matrix_payload(design, factors, run_order_seed=iteration)
    rows = matrix.expand(design, factors)

    # At refine the design spans only the REFINABLE factors, so a factor left
    # out of it contributes no level and therefore no `apply` fragment — its
    # CLI flag disappears from the command line entirely. A target that
    # (correctly) requires all of its flags then fails every single run on a
    # usage error. Observed for real: 48 of 48 refine and confirm runs died with
    # "the following arguments are required: --enable-a, --enable-b" because
    # those two factors are `choice` and refine only covers numerics.
    #
    # Hold every non-designed factor at a fixed level instead of dropping it:
    # its first declared level, which for a two-level ablation is the control
    # and for anything else is the author's stated default. That keeps the
    # command line complete and the held-fixed value auditable in runs.jsonl,
    # rather than making the target guess.
    designed = set(_design_factor_ids(factors, design_cfg, stage_name))
    held = [f for f in factors if f.id not in designed]
    if held and rows:
        import dataclasses

        fixed = {f.id: f.levels[0] for f in held if getattr(f, "levels", None)}
        if fixed:
            logger.info(
                "%s: holding %d non-designed factor(s) fixed at their first "
                "declared level so the target still receives every flag: %s",
                stage_name, len(fixed), fixed,
            )
            rows = [
                dataclasses.replace(
                    r,
                    levels={**fixed, **dict(r.levels)},
                    apply=matrix.render_apply(
                        factors, {**fixed, **dict(r.levels)},
                    ),
                )
                for r in rows
            ]
            payload = dict(payload)
            payload["held_fixed"] = dict(fixed)
            payload["rows"] = [
                {**row, "levels": {**fixed, **dict(row.get("levels") or {})}}
                for row in payload.get("rows", [])
            ]

    if stage_name == Stage.CONFIRM.value and not (
        design_cfg.get("confirm_at") or _read_confirm_at(work_dir)
    ):
        # No fitted stationary point to reproduce, so replicate the best
        # configuration actually OBSERVED rather than the geometric origin.
        # `expand` renders coded coordinates, which for a two-level screen
        # puts the origin at the midpoint of every range — a configuration
        # nobody measured. Pin the observed winner's levels instead.
        best = _best_observed(work_dir, primary)
        if best is not None:
            import dataclasses

            rows = [
                dataclasses.replace(
                    r,
                    levels=dict(best["levels"]),
                    apply=matrix.render_apply(factors, best["levels"]),
                )
                for r in rows
            ]
            payload = dict(payload)
            payload["rows"] = [
                {**row, "levels": dict(best["levels"])}
                for row in payload.get("rows", [])
            ]
            payload["confirm_source"] = "best_observed"
            logger.info(
                "confirm: no fitted stationary point; replicating the best "
                "OBSERVED configuration (%s=%.4f) rather than the origin",
                primary, best[primary],
            )
    if _enter_phase(engine, "DESIGN", work_dir):
        _preflight_design(rows, factors, opt, iter_dir)
        artifacts.write_design_matrix(iter_dir, payload)

    _enter_phase(engine, "HUMAN_DESIGN_GATE", work_dir)

    # ── EXECUTE_ANALYZE: the tokenless sweep ────────────────────────────
    if config_runner is None:
        raise OptimizationAborted(
            "run_stage has no config_runner (row -> observation dict). A real "
            "run builds one from optimization.run_command, so reaching this "
            "means the campaign declares no run_command (or "
            "target_system.repo_path is unset) and no caller injected a "
            "substitute. Add optimization.run_command — the target's benchmark "
            "invocation, without the per-factor flags, which are appended from "
            "each factor's `apply`.",
        )
    _enter_phase(engine, "EXECUTE_ANALYZE", work_dir)
    by_index = {r.row_index: r for r in rows}

    # EXECUTE in the pre-registered randomized order, not in design order.
    #
    # `matrix_payload` generates `run_order` (a seeded permutation) and records
    # it in design_matrix.json, and `expand`'s docstring tells callers to
    # consult it. Nothing did: rows went to execute_design in design order, so
    # the artifact asserted a randomization that never happened. That is a
    # provenance defect rather than a numerical one — every configuration still
    # ran and the fit is unaffected — but run-order randomization is what
    # protects a factorial design against drift confounding (a warming cache, a
    # thermally throttling machine, a background job), and an artifact claiming
    # a guarantee the run did not provide is worse than one that claims nothing.
    #
    # execute_design returns outcomes in the order it received rows, and every
    # downstream consumer keys on `row_index` (`by_index`, `_run_row`,
    # check_fidelity), so permuting the input reorders execution without
    # reordering any result.
    order = payload.get("run_order")
    exec_rows = rows
    if isinstance(order, list) and sorted(order) == list(range(len(rows))):
        exec_rows = [by_index[i] for i in order]
        logger.info(
            "%s: executing %d row(s) in the pre-registered randomized order "
            "(seed=%s)", stage_name, len(exec_rows),
            payload.get("run_order_seed"),
        )
    elif order is not None:
        logger.warning(
            "%s: design_matrix run_order is not a permutation of 0..%d; "
            "executing in design order and the artifact's randomization claim "
            "does not hold", stage_name, len(rows) - 1,
        )

    outcomes = runner.execute_design(
        exec_rows, runner=config_runner, response_spec=response_spec,
        invariants=invariants, factors=factors,
        integrity_check=integrity_check,
        on_row=lambda outcome: artifacts.append_run(
            iter_dir, _run_row(by_index[outcome.row_index], outcome),
        ),
    )

    # Restore DESIGN order before anything reads these positionally.
    # `_fitting_responses` walks `outcomes` in sequence and `fit_effects` pairs
    # value i with `design.points[i]`, so leaving them in execution order would
    # misalign every response with its design row and produce silently wrong
    # coefficients — far worse than the provenance gap that motivated
    # randomizing execution in the first place. runs.jsonl still records the
    # true execution sequence, because `on_row` fires as each row completes.
    if exec_rows is not rows:
        pos = {r.row_index: i for i, r in enumerate(rows)}
        outcomes = sorted(
            outcomes, key=lambda o: pos.get(o.row_index, len(rows)),
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

    if stage_name == Stage.CONFIRM.value:
        # Confirm does NOT fit a model. It replicates ONE configuration, so
        # there are no distinct design points to estimate effects from —
        # attempting it raises "design matrix is singular", correctly. What
        # confirm reports is whether the predicted optimum REPRODUCED: the
        # replicate mean, its spread, and the point that was run.
        return _finish_confirm(
            engine, campaign, stage_name, iteration, iter_dir, work_dir,
            rows, outcomes, ys, factors, test_results,
        )

    # The factor_ids MUST match the design's column order and width. At
    # refine, _build_design builds a central composite over only the
    # refinable factors, so passing every factor id here would misalign the
    # model matrix (verified: it raises IndexError). Derive the ids from the
    # design that was actually built.
    fitted_ids = _design_factor_ids(factors, design_cfg, stage_name)

    # Fit on the COMPLETE rows only.
    #
    # `_fitting_responses` carries NaN for any row that did not complete, and the
    # guard above deliberately exempts `infeasible`/`rejected` rows from aborting
    # — a constrained design routinely has inadmissible corners, and aborting on
    # one would make constraints unusable. But those NaNs then flowed straight
    # into fit_effects, where a SINGLE NaN turns EVERY coefficient into NaN while
    # still returning a schema-valid Fit. Verified: one NaN row changed
    # [0.1875, -0.5625, -0.0625, 0.1875] into [nan, nan, nan, nan] with no error
    # raised and no warning logged.
    #
    # The comment above already states the intended behaviour — "refit on the
    # completed rows and report the reduced resolution honestly" — but nothing
    # implemented it. This does. The excluded rows are named in the log and
    # recorded on the fit's artifact so the reduced resolution is visible rather
    # than implied.
    design_for_fit, ys_for_fit = design, ys
    dropped = [i for i, v in enumerate(ys) if v != v]
    if dropped:
        import dataclasses

        keep = [i for i, v in enumerate(ys) if v == v]
        if len(keep) < 2:
            raise OptimizationAborted(
                f"only {len(keep)} of {len(ys)} rows produced a usable "
                f"measurement, which cannot support a fit. Re-run the failed "
                f"configurations before fitting.",
            )
        design_for_fit = dataclasses.replace(
            design, points=tuple(design.points[i] for i in keep),
        )
        ys_for_fit = [ys[i] for i in keep]
        logger.warning(
            "%s: fitting on %d of %d rows; %d row(s) excluded as not complete "
            "(row_index %s). The fit's resolution is reduced accordingly — a "
            "single NaN row would otherwise NaN-poison every coefficient "
            "silently.",
            stage_name, len(keep), len(ys), len(dropped),
            [getattr(design.points[i], "label", i) or i for i in dropped],
        )

    fit = fit_effects(design_for_fit, ys_for_fit, factor_ids=fitted_ids)
    artifacts.write_effects(iter_dir, fit, factors=factors, stage=stage_name)
    if dropped:
        _write_json(iter_dir / "fit_exclusions.json", {
            "stage": stage_name,
            "planned_rows": len(ys),
            "fitted_rows": len(ys_for_fit),
            "excluded_row_indices": dropped,
            "reason": (
                "rows did not reach status 'complete' (infeasible, rejected, or "
                "unmeasured); fitting on the complete subset rather than "
                "carrying NaN into every coefficient"
            ),
        })

    behavioral = _assert_all_behavioral(behavioral_failures)
    if stage_name == Stage.REFINE.value:
        stationary = solve_stationary_point(fit, fitted_ids)
        # Hand the solved optimum forward so `confirm` replicates THAT point
        # rather than the origin. Recorded on the artifact rather than mutated
        # into the campaign dict, so the value is durable and auditable: a
        # reader of effects.json can see which coded point confirm was asked
        # to reproduce, which is the whole claim the confirm stage makes.
        if stationary:
            _write_json(iter_dir / "confirm_at.json", dict(stationary))
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


def _verify_abort_message(failures) -> str:
    """Explain a verify abort in terms of the fix it needs.

    "Relation R_X failed" is not actionable, and after a ``build`` stage it is
    expensive not to be: the agent call is already spent, so a wrong diagnosis
    costs a whole second build to rediscover. Two failure modes need OPPOSITE
    fixes and the old message conflated them:

    - NOT EXECUTED: the test command never ran that identifier. Usually the
      test was not written, or its name/path does not match the declared
      locator, or the command's ``-run``/selection filter excludes it. Note
      that ``go test -run`` with a pattern matching nothing exits 0, so the
      shell reports success while the relation is unverified.
    - FAILED: the identifier ran and the assertion did not hold. That is a
      real defect in the mechanism -- or in the relation itself, which is
      worth considering when a metamorphic direction was asserted without
      checking the algebra.
    """
    missing, failed = [], []
    for v in failures:
        detail = str(getattr(v, "detail", "") or "")
        entry = (
            f"{getattr(v, 'relation_id', '?')} "
            f"({getattr(v, 'native_test', '?')})"
        )
        (missing if "not executed" in detail else failed).append(entry)

    parts = [
        f"verify failed: {len(missing) + len(failed)} correctness relation(s) "
        f"did not hold. The apparatus is broken, so any measurement would "
        f"describe the wrong system. No design budget was spent.",
    ]
    if failed:
        parts.append(
            "\nRAN AND FAILED (" + str(len(failed)) + ") -- the assertion did "
            "not hold:\n  " + "\n  ".join(failed)
            + "\n  Fix: correct the mechanism. If you are confident the "
            "mechanism is right, re-check the relation itself -- a metamorphic "
            "direction asserted without doing the algebra fails correct code.",
        )
    if missing:
        parts.append(
            "\nNEVER EXECUTED (" + str(len(missing)) + ") -- the test command "
            "did not run this identifier, which counts as a failure because "
            "'not run' is not evidence of correctness:\n  "
            + "\n  ".join(missing)
            + "\n  Fix: confirm the test exists with EXACTLY that name, that "
            "its file path matches the declared locator, and that the test "
            "command actually selects it. Note `go test -run <pattern>` exits "
            "0 when the pattern matches nothing, so a green shell here proves "
            "nothing. Run the command by hand and check the identifier appears "
            "in its output.",
        )
    return "".join(parts)


def _build_max_turns(campaign: dict) -> int:
    """Turn ceiling for the build call.

    Honours ``max_turns.build`` when the campaign sets it, since authoring a
    mechanism in an unfamiliar repo varies enormously in how many turns it
    needs. Falls back to the module default rather than to the reflective
    kind's design/execute budgets, which are sized for a different job.
    """
    from orchestrator.optimize.build import DEFAULT_MAX_TURNS

    raw = campaign.get("max_turns")
    if isinstance(raw, dict):
        val = raw.get("build")
        if isinstance(val, int) and val > 0:
            return val
    return DEFAULT_MAX_TURNS


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
        return tuple(f.id for f in factors if is_refinable(f))
    return ids



def _preflight_design(rows, factors, opt: dict, iter_dir: Path) -> None:
    """Check the design matrix BEFORE the sweep spends anything.

    The reflective kind validates its bundle at DESIGN (``validate_design``,
    plus a whole CRITIC phase between DESIGN and the gate) precisely so a
    malformed experiment fails before execution. This path had no equivalent:
    DESIGN wrote a matrix and EXECUTE_ANALYZE immediately ran it, so every
    authoring or generation defect cost a FULL campaign to discover.

    Three live-campaign failures motivated each check below, all found this
    way rather than by any test:

      * 115 configurations executed, every one failing its manipulation
        predicate, because the predicate named an observable the target never
        emits. Detectable up front: the ``applied.*`` namespace is known
        before any run.
      * 16 of 80 refine runs rejected because axial extrapolation produced a
        NEGATIVE request cap from a factor declared ``[64, 256]``. Detectable
        up front: every planned level is in the matrix.
      * the objective named a metric the target does not emit, so every run
        parsed but scored NaN. Not fully checkable without a run, but a
        single probe run answers it -- which is what ``verify`` is for.

    Raises ``OptimizationAborted`` with the offending rows named. Failing
    here costs one design phase; failing after the sweep costs the campaign.
    """
    problems: list[str] = []

    by_id = {f.id: f for f in factors}
    for row in rows:
        for fid, level in (row.levels or {}).items():
            f = by_id.get(fid)
            if f is None or f.type != "numeric":
                continue
            lo, hi = min(f.levels), max(f.levels)
            try:
                numeric = float(level)
            except (TypeError, ValueError):
                problems.append(
                    f"row {row.row_index}: factor {fid} level {level!r} is not "
                    f"numeric, but the factor is declared type: numeric",
                )
                continue
            if not (float(lo) <= numeric <= float(hi)):
                problems.append(
                    f"row {row.row_index}: factor {fid} level {numeric} is "
                    f"outside its declared range [{lo}, {hi}] — the target is "
                    f"unlikely to accept a configuration the campaign never "
                    f"declared legal",
                )

    # A manipulation predicate can only ever pass if it names something that
    # will exist at check time. `applied.*` always will; anything else is a
    # bet on the target echoing that field back, which most targets do not.
    for f in factors:
        obs = (f.manipulation or {}).get("observable") or (
            f.manipulation or {}
        ).get("metric") or ""
        root = str(obs).split(".", 1)[0]
        if root not in ("applied", "applied_args", "applied_env"):
            logger.info(
                "factor %s asserts manipulation against %r, which requires the "
                "TARGET to emit that field. If it does not, every run of this "
                "factor fails its check — see the applied.* namespace.",
                f.id, obs,
            )

    if problems:
        raise OptimizationAborted(
            "design pre-flight found "
            f"{len(problems)} problem(s) before spending any runs:\n  "
            + "\n  ".join(problems[:12])
            + ("\n  ..." if len(problems) > 12 else ""),
        )
    logger.info(
        "design pre-flight: %d planned configuration(s), all levels within "
        "their declared ranges", len(rows),
    )


def _build_design(factors, design_cfg: dict, stage_name: str,
                  work_dir: Path | None = None):
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
        if not refinable:
            # Nothing to refine. `is_refinable` requires a NUMERIC factor with
            # MORE THAN TWO levels, because curvature cannot be estimated from
            # two points and a `choice` factor has no interior at all. The
            # previous `refinable or ids` fallback silently built a central
            # composite over EVERY factor instead, which fitted quadratic
            # terms for categorical factors — and on a live campaign two of
            # those came out exactly 0.0, making the Hessian singular, so
            # solve_stationary_point returned None, no confirm_at.json was
            # written, and `confirm` replicated the ORIGIN instead of the
            # optimum. The campaign had already observed the true optimum
            # (117.854) and then confirmed a 73.476 centre point.
            #
            # stage.decide_after_screen already routes straight to `confirm`
            # when no refinable factor survives, so reaching here means the
            # stage was forced explicitly. Say so rather than fabricating a
            # design.
            raise OptimizationAborted(
                "refine has nothing to refine: no factor is refinable "
                "(is_refinable requires type: numeric with MORE THAN two "
                "levels — curvature cannot be estimated from two points, and "
                "a choice factor has no interior). Either declare a third "
                "level on the numeric factor you want curvature for, or drop "
                "design.refine and let the stage rule go screen -> confirm.",
            )
        return central_composite(
            refinable, center_points=int(cfg.get("center_points", 4)),
        )
    if stage_name == Stage.CONFIRM.value:
        # Confirm REPLICATES one configuration — the predicted optimum —
        # rather than re-running a screen. Without this branch confirm
        # silently rebuilt the screen design, so the campaign's final stage
        # repeated stage 2 and reported COMPLETED while the guide claimed it
        # reproduced the optimum. That is the one defect here that could
        # mislead a researcher about their own result.
        #
        # The point to replicate comes from `confirm_at` (coded coordinates
        # the refine stage's stationary point, already grid-snapped by
        # decode_coded downstream). Absent that — a campaign that skipped
        # refine because nothing was refinable — replicate the origin, which
        # for a two-level screen is the centre of the declared ranges.
        cfg = design_cfg.get("confirm") or {}
        replicates = max(1, int(cfg.get("replicates", 3)))
        at = design_cfg.get("confirm_at") or _read_confirm_at(work_dir)
        coded = tuple(
            float(at[f.id]) if isinstance(at, dict) and f.id in at else 0.0
            for f in factors
        )
        from orchestrator.optimize.design import Design, DesignPoint

        # role MUST NOT be "center": `matrix._decode_level` treats that role as
        # "ignore the coded coordinates and use the midpoint of every declared
        # range", which is correct for a genuine replicated centre point and
        # catastrophic here. Labelling the fitted stationary point "center"
        # silently discarded the coordinates confirm exists to reproduce, so a
        # stationary point at coded +0.9 of [64, 256] ran level 160 (the
        # midpoint) instead of 246. The campaign then reported "the predicted
        # optimum reproduced" about a configuration the fit never predicted.
        #
        # Observed on a real campaign: confirm reported a mean 38% below a
        # corner the screen had already measured. That was diagnosed at the time
        # as the fit extrapolating badly; it was actually this — confirm never
        # ran the fitted point at all.
        #
        # "axial" routes through `decode_coded`, which interpolates and
        # grid-snaps any coded value, including 0.0 (so the no-refine case still
        # yields the origin exactly as before).
        return Design(
            points=tuple(
                DesignPoint(coded=coded, role="axial", replicate=i)
                for i in range(replicates)
            ),
            factor_ids=tuple(f.id for f in factors),
            kind="confirm",
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


def _finish_confirm(engine, campaign, stage_name, iteration, iter_dir,
                    work_dir, rows, outcomes, ys, factors, test_results):
    """Record whether the predicted optimum reproduced, then terminate.

    Deliberately writes no ``effects.json``: there is no fit here. The claim
    confirm makes is narrower and more useful — this exact configuration,
    replicated N times, produced this mean and this spread.
    """
    from statistics import mean, pstdev

    from orchestrator.iteration import (
        IterationOutcome,
        _enter_phase,
        finalize_iteration,
    )
    from orchestrator.ledger import append_ledger_row
    from orchestrator.optimize import artifacts, relations

    usable = [v for v in ys if v == v]
    levels = dict(rows[0].levels) if rows else {}
    summary = {
        "stage": stage_name,
        "iteration": iteration,
        "confirmed_at_levels": levels,
        "replicates": len(outcomes),
        "usable_replicates": len(usable),
        "mean": mean(usable) if usable else None,
        "spread": pstdev(usable) if len(usable) > 1 else 0.0,
        "observations": usable,
    }

    # Did the confirmed point actually beat everything the campaign measured?
    #
    # A fitted stationary point is an EXTRAPOLATION. When the surface is
    # mis-specified — curvature the quadratic cannot express, an optimum
    # outside the design hull, a categorical factor dragged into the fit —
    # the solved point can land below a corner the screen already measured.
    # Without this check the campaign replicates that inferior point, records
    # status CONFIRMED because the replicates agreed with each other, and
    # reports it as the optimum. "The prediction reproduced" and "this is the
    # best configuration found" are different claims, and only the second is
    # what a reader of the report wants. Recording both keeps the artifact
    # honest when they disagree.
    primary = (
        ((campaign.get("optimization") or {}).get("response") or {})
        .get("primary") or {}
    )
    metric = primary.get("metric") or ""
    maximize = (primary.get("direction") or "maximize") != "minimize"
    best = _best_observed(work_dir, metric) if metric else None
    if best is not None and summary["mean"] is not None:
        best_val = best.get(metric)
        if isinstance(best_val, (int, float)):
            confirmed_mean = summary["mean"]
            beats = (
                confirmed_mean >= best_val if maximize
                else confirmed_mean <= best_val
            )
            summary["best_observed"] = {
                "levels": dict(best.get("levels") or {}),
                metric: best_val,
            }
            summary["confirmed_is_best_observed"] = bool(beats)
            if not beats:
                gap = abs(best_val - confirmed_mean)
                pct = (gap / abs(best_val) * 100.0) if best_val else float("nan")
                summary["regression_vs_best_observed"] = {
                    "absolute": gap, "percent": pct,
                }
                logger.warning(
                    "confirm: the confirmed configuration (%s=%.6g) is WORSE "
                    "than the best configuration already observed (%.6g at "
                    "%s) — a gap of %.6g (%.2f%%). The fitted optimum is an "
                    "extrapolation; treat the observed corner as the "
                    "campaign's answer and the surface as mis-specified.",
                    metric or "response", confirmed_mean, best_val,
                    best.get("levels"), gap, pct,
                )
    _write_json(iter_dir / "confirmation.json", summary)
    _write_json(iter_dir / "findings.json", _confirm_findings(summary, iteration))
    _write_json(iter_dir / "principle_updates.json", [])
    artifacts.write_relations(
        iter_dir, relations.reconcile(factors, test_results or {}),
    )
    _enter_phase(engine, "HUMAN_FINDINGS_GATE", work_dir)
    finalize_iteration(
        work_dir=work_dir, iter_dir=iter_dir, iteration=iteration,
        campaign=campaign,
    )
    append_ledger_row(work_dir, iteration)
    return _terminal_outcome(engine, campaign, stage_name, IterationOutcome)


def _confirm_findings(summary: dict, iteration: int) -> dict:
    """A findings.schema.json-conformant record of the confirmation run."""
    n, usable = summary["replicates"], summary["usable_replicates"]
    observed = (
        f"mean={summary['mean']:.6g} over {usable}/{n} usable replicates "
        f"(spread={summary['spread']:.6g}) at levels {summary['confirmed_at_levels']}"
        if summary["mean"] is not None
        else f"no usable replicates out of {n}"
    )
    reproduced = summary["mean"] is not None and usable >= 1
    return {
        "iteration": iteration,
        "bundle_ref": f"runs/iter-{iteration}/confirmation.json",
        "experiment_valid": reproduced,
        "discrepancy_analysis": (
            "Confirmation stage: the predicted optimum was replicated and its "
            "mean and spread recorded. No effects are fitted here — a single "
            "replicated configuration has no distinct design points to "
            "estimate from."
        ),
        "arms": [{
            "arm_type": "h-main",
            "predicted": "the refine stage's solved optimum reproduces",
            "observed": observed,
            "status": "CONFIRMED" if reproduced else "REFUTED",
            "error_type": None,
            "diagnostic_note": (
                None if reproduced
                else "every replicate failed to produce a usable measurement"
            ),
            "metadata": summary,
        }],
    }


def _best_observed(work_dir, primary: str) -> dict | None:
    """The best COMPLETED configuration observed so far, by primary metric.

    Used by ``confirm`` when there is no fitted stationary point — either
    refine was skipped (nothing refinable) or its solve was singular. The
    previous behaviour replicated the ORIGIN, which was actively misleading
    on a live campaign: the screen stage had observed goodput 117.854 and
    confirm reproduced a 73.476 centre point, so the campaign found the right
    answer and reported the wrong one.

    Reproducing the best observed corner is a WEAKER claim than reproducing a
    fitted optimum — it is the best configuration tried, not an interpolated
    peak — and ``confirmation.json`` records which of the two it was. But it
    is a real measured configuration rather than an arbitrary geometric
    centre.
    """
    import json as _json

    best = None
    for path in sorted(Path(work_dir).glob("runs/iter-*/runs.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if row.get("status") != "complete":
                continue
            value = (row.get("response") or {}).get(primary)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if best is None or numeric > best[1]:
                best = (dict(row.get("levels") or {}), numeric)
    return None if best is None else {"levels": best[0], primary: best[1]}


def _read_confirm_at(work_dir) -> dict | None:
    """The most recent refine stage's solved optimum, if any.

    Read from disk rather than threaded through the campaign dict so the
    value is durable across the process boundary between iterations — each
    stage is a separate ``run_iteration`` call.
    """
    import json

    if work_dir is None:
        return None
    # Sort NUMERICALLY on the iteration index, not lexicographically on the
    # path. "iter-10" sorts BEFORE "iter-2" as a string, so a lexicographic
    # sort silently returns a stale optimum on any campaign reaching double
    # digits — verified: with confirm_at.json at both iter-2 and iter-10 it
    # picked iter-2's value. A silent wrong answer, no error.
    def _iter_index(path: Path) -> int:
        try:
            return int(path.parent.name.split("-", 1)[1])
        except (IndexError, ValueError):
            return -1

    candidates = sorted(
        Path(work_dir).glob("runs/iter-*/confirm_at.json"), key=_iter_index,
    )
    if not candidates:
        return None
    try:
        payload = json.loads(candidates[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    # Refuse a stationary point that lies outside the design hull.
    #
    # ``decide_after_refine`` already detects this and raises
    # OPTIMUM_OUTSIDE_HULL with the rationale "ranges were too narrow to
    # contain the optimum -- escalate before confirming". But Trigger is
    # documented as reported-not-acted-on, so confirm read the same solve off
    # disk and replicated it anyway: the system diagnosed the problem, wrote
    # it into findings, and then did the thing it had just warned against.
    #
    # Observed on a real campaign: the surface was monotone in both refined
    # factors (no interior optimum exists), the quadratic solve landed at
    # coded BANDCAP=+1.62 / THRESH=-2.30, and confirm reproduced 112.4997
    # while the campaign had already MEASURED 182.2159 at a corner. Returning
    # None here makes confirm fall back to the best observed configuration,
    # which is the weaker claim but the true one.
    coords = [v for v in payload.values() if isinstance(v, (int, float))]
    outside = {
        k: v for k, v in payload.items()
        if isinstance(v, (int, float)) and not (-1.0 <= float(v) <= 1.0)
    }
    if coords and outside:
        logger.warning(
            "confirm: ignoring the fitted stationary point %s — it falls "
            "outside the design hull on %s (coded coordinates must lie in "
            "[-1, 1]). Extrapolating there would confirm a configuration the "
            "design never bracketed, so confirm will replicate the best "
            "OBSERVED configuration instead. Widen those factors' ranges and "
            "re-run refine to locate a real interior optimum.",
            payload, ", ".join(sorted(outside)),
        )
        return None
    return payload


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
