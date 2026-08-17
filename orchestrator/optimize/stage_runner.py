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

  * ``build``   — the ONLY substantive model call in this kind: authors the
                  mechanism and its native tests (opt-in; see build.py).
                  Gate summaries and the end-of-campaign report use the
                  existing shared machinery and are not part of the epoch.
  * ``verify``  — pure Python: runs test_command, reconciles relations, and
                  compiles the experimental policy (policy.py).
  * ``screen`` / ``foldover`` / ``refine`` / ``confirm`` — spending states of
                  the compiled epoch. ZERO model calls.
  * ``report`` / ``exception`` — inline terminal states. ZERO model calls.

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

THE ANSWER IS AN ARGMAX, NOT A SOLVE (spec §3.3, ``decide.py``). Every
fitting stage writes ``runs/iter-N/recommendation.json``: the best-predicted
point of the candidate space, in REAL levels, for every factor. Two
consumers read it — ``confirm`` replicates its ``levels``, and ``refine``
holds each non-designed factor at the level the previous recommendation
named — and both used to read the refine stage's stationary point instead.
That point is still solved and still recorded (as
``recommendation.json["stationary_point"]``, which is where
``decide_after_refine``'s OPTIMUM_OUTSIDE_HULL still comes from); it just no
longer decides what runs, because the point where a quadratic's gradient
vanishes is a saddle or a minimum as readily as a maximum and is blind to
``choice`` factors entirely.

Which state runs is decided by the COMPILED POLICY, not by the iteration
index. ``verify`` compiles ``policy.json`` (+ ``policy.sha256``) once, and
from the first epoch iteration onward ``_resolve_state`` asks
``policy.current_state`` what the last recorded transition said. Every
iteration ends by appending a row to ``transitions.jsonl``, so the path a
campaign took is EVIDENCE rather than an inference from which artifact each
iteration happened to write. ``stage_for_iteration`` still exists in
``stage.py`` for the pre-epoch stages' index mapping, but no longer decides
anything inside the epoch.

OBSERVATION CONVENTIONS (units and base, recorded here so Task 9 and any
later owner of ``certified`` do not have to reverse-engineer them from
``_close_iteration``). ``observations_from_decision`` supplies the six
fit-derived keys; the five guard keys below are supplied by this module and
are the ones whose base is not self-evident:

  * ``round`` counts the state's own rounds SPENT INCLUDING THE CURRENT ONE.
    ``screen`` and ``refine`` always report ``round: 0``: neither state
    self-loops, so no compiled guard reads their value and the key exists only
    to keep the observation vocabulary complete (``step`` treats an absent key
    as unknown, which never matches — so an omitted key is not the same as a
    zero). ``confirm`` is the one self-looping state, and it is **1-based**:
    the FIRST confirm iteration reports ``round: 1``, the second ``2``, and so
    on (``_confirm_round`` = ``1 + confirm transitions already in
    transitions.jsonl``). That is what makes the compiled guard ``{"round":
    {">=": max_rounds}}`` mean "stop once ``max_rounds`` rounds have been
    SPENT", and it is what preserves today's behaviour at the default
    ``confirm_max_rounds: 1``, where a single confirm iteration ends the
    campaign. Read the two bases together as one rule: ``round`` is
    "rounds spent by THIS state, this iteration included", and 0 for a state
    that cannot loop is the vacuous case of it.
  * ``budget_remaining`` is a raw **RUN COUNT** — benchmark configurations
    still affordable — NOT a number of confirm rounds. ``_budget_remaining``
    computes ``max_runs - (rows already recorded across every iter-* dir)``
    and returns ``10 ** 9`` when the campaign declares no ``design.max_runs``,
    i.e. "unbounded" rather than "exhausted": a missing cap must never route
    a campaign to ``report``.
  * ``certified`` is ``False`` everywhere in this task. Task 9 owns the
    Holm one-sided-t certification that can make it True.
  * ``correctness_failed`` is False on any path that reaches a transition at
    all — a correctness relation failure raises ``OptimizationAborted``
    upstream, before a transition is recorded. It is set explicitly so the
    guard is evaluated against a fact rather than against an absent key
    (``step`` treats a missing observation as unknown, which never matches).
  * ``nan_response`` is "any row admissible to this stage's fit carried NaN".
    Today ``_fitting_responses`` still raises on an unmeasured row before the
    observation can be recorded; Task 11 is what routes it to ``exception``
    instead.

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

from orchestrator.optimize import artifacts, certificate, decide, matrix, relations, runner
from orchestrator.optimize import policy as policy_mod
from orchestrator.optimize.effects import fit_effects, solve_stationary_point
from orchestrator.optimize.factors import is_refinable, parse_factors
from orchestrator.optimize.stage import (
    Stage,
    decide_after_refine,
    decide_after_screen,
    observations_from_decision,
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


def _read_mechanism_hash(work_dir: Path) -> str:
    p = Path(work_dir) / "mechanism.sha256"
    return p.read_text().strip() if p.exists() else ""


def _epoch_index(work_dir: Path) -> int:
    return 1 + len(list(Path(work_dir).glob("epoch_end*.json")))


def _compile_and_write_policy(campaign: dict, work_dir: Path) -> dict:
    """Compile, structurally check, and persist the epoch's policy."""
    pol = policy_mod.compile_policy(
        campaign, mechanism_patch_hash=_read_mechanism_hash(work_dir),
        epoch=_epoch_index(work_dir),
    )
    errs = policy_mod.check_policy(pol)
    if errs:
        raise OptimizationAborted(
            "compiled policy is structurally invalid:\n  " + "\n  ".join(errs),
        )
    policy_mod.write_policy(work_dir, pol)
    return pol


def _load_or_compile_policy(campaign: dict, work_dir: Path) -> dict:
    """The epoch's policy, compiled lazily if verify has not written one.

    A real campaign always compiles at ``verify``; the lazy branch exists so a
    unit test that jumps straight to ``stage="screen"`` still has a policy to
    interpret. Once a policy IS on disk, its recorded hash is checked: a
    pre-registered policy that changed inside an epoch is not a
    pre-registration, so an edit hard-fails rather than being interpreted.
    """
    pol = policy_mod.read_policy(work_dir)
    if pol is None:
        return _compile_and_write_policy(campaign, work_dir)
    recorded = Path(work_dir) / "policy.sha256"
    if recorded.exists() and recorded.read_text().strip() != policy_mod.policy_hash(pol):
        raise OptimizationAborted(
            "policy.json was edited after compilation (hash mismatch with "
            "policy.sha256); a pre-registered policy cannot change inside an "
            "epoch",
        )
    return pol


def _resolve_state(campaign: dict, work_dir: Path, iteration: int,
                   stage) -> tuple[str, dict | None]:
    """Which state this iteration runs, and the policy (None before compile).

    An explicit ``stage`` (tests) wins. Pre-epoch stages are index-driven;
    from the first epoch iteration onward the state is whatever the last
    recorded transition says (spec §3.2), which is what replaces
    ``stage_for_iteration``'s index clamp — the clamp re-ran the final stage
    forever whenever ``max_iterations`` exceeded the stage count.
    """
    pre = policy_mod.pre_epoch_stages(campaign)
    if stage is not None:
        name = getattr(stage, "value", None) or str(stage)
        pol = None if name in pre else _load_or_compile_policy(campaign, work_dir)
        return name, pol
    if iteration <= len(pre):
        return pre[iteration - 1], None
    pol = _load_or_compile_policy(campaign, work_dir)
    return policy_mod.current_state(pol, work_dir), pol


def _budget_remaining(pol: dict, work_dir: Path) -> int:
    """Benchmark runs still affordable — a RUN COUNT, not a round count.

    ``10 ** 9`` means "no declared cap", which must read as unbounded: a
    campaign that never declared ``design.max_runs`` must not be routed to
    ``report`` for having exhausted a budget it does not have.
    """
    cap = (pol.get("budget") or {}).get("max_runs")
    if not cap:
        return 10 ** 9
    spent = sum(
        len(artifacts.read_runs(d))
        for d in (Path(work_dir) / "runs").glob("iter-*")
    )
    return int(cap) - spent


def _confirm_round(work_dir: Path) -> int:
    """Confirm rounds SPENT INCLUDING this one — so the first confirm is 1.

    The count is ``1 + (confirm transitions already recorded)``, which is what
    makes the compiled guard ``{"round": {">=": max_rounds}}`` mean "stop once
    ``max_rounds`` rounds have been spent". Off by one in the other direction
    (a 0-based count) would let a campaign whose registered ``max_rounds`` is 1
    run confirm TWICE — and would change today's behaviour, where one confirm
    iteration ends the campaign.
    """
    return 1 + sum(
        1 for t in policy_mod.read_transitions(work_dir) if t.get("from") == "confirm"
    )


def _close_iteration(engine, campaign, work_dir, iter_dir, iteration, state, pol,
                     observations: dict, *, recommendation_levels: dict | None):
    """Record the transition and run inline terminals. Returns IterationOutcome.

    The findings/principles writes and the HUMAN_FINDINGS_GATE ->
    finalize_iteration -> append_ledger_row sequence stay with the CALLERS
    rather than moving in here: ``_finish_confirm`` writes a different artifact
    set from the screen/refine path (``confirmation.json``, no ``effects.json``),
    and folding both into one closer would have to branch on the state to get
    that right — reintroducing, inside the shared helper, exactly the
    per-state knowledge the policy exists to hold.

    ``iter_dir`` is accepted but unused here. It is part of the signature the
    later terminal-handling tasks are written against (Task 11's
    ``epoch_end.json`` is placed relative to the iteration that ended the
    epoch), and threading it now keeps those tasks from having to touch three
    call sites to get it.
    """
    from orchestrator.iteration import IterationOutcome

    if state not in (pol.get("states") or {}):
        # Reachable only through an explicit `stage=` that the policy does not
        # register — e.g. forcing `refine` on a campaign where nothing is
        # refinable, or a stage the `stages` list omits. `step` would raise a
        # bare ValueError about a missing default transition, which describes
        # the symptom rather than the mismatch.
        raise OptimizationAborted(
            f"state {state!r} was run but the compiled policy registers only "
            f"{sorted(pol.get('states') or {})}. A state outside the policy has "
            f"no registered transition, so nothing can decide what follows it — "
            f"either the campaign's `stages` list omits it or no factor makes it "
            f"compilable (refine requires a refinable factor).",
        )
    nxt, rule = policy_mod.step(pol, state, observations)
    policy_mod.append_transition(work_dir, {
        "iteration": iteration,
        "from": state,
        "to": nxt,
        "rule": rule,
        "observations": observations,
        "policy_hash": policy_mod.policy_hash(pol),
    })
    logger.info(
        "policy: %s -> %s (%s)", state, nxt,
        rule.get("accounting") or "default transition",
    )
    if nxt == "report":
        _run_report(engine, campaign, work_dir, iteration, pol,
                    recommendation_levels=recommendation_levels)
        return IterationOutcome.COMPLETED
    if nxt == "exception":
        # Task 11 replaces this with an epoch_end.json + a new epoch.
        raise OptimizationAborted(
            f"policy routed {state} -> exception: {rule.get('when')}",
        )
    return IterationOutcome.CONTINUE


def _run_report(engine, campaign, work_dir, iteration, pol, *,
                recommendation_levels) -> None:
    """Write ``report.json`` and end the campaign at DONE.

    ALWAYS ACT (spec §3.6). A finite-budget system that cannot certify must
    still return a configuration, and the report must say which rung it came
    from so a reader can tell a certificate from a fallback without reading the
    log. The ladder, strongest first:

      1. ``certified``     — terminal discrimination ran and ``R_t <= epsilon``.
      2. ``terminal_best``  — terminal discrimination ran, bound too wide. The
                              winner is still a measured configuration compared
                              against measured rivals.
      3. ``model``          — no terminal stage ran; the fitted argmax stands,
                              with its model bound, PROVIDED nothing has
                              measured those exact levels invalid.
      4. ``measured``       — the model's answer is unusable; return the best
                              measured VALID configuration. Never the largest
                              noisy observation — ``_best_observed`` filters to
                              ``complete``, and the terminal stage is what
                              re-measures when there is budget for it.
      5. ``baseline``       — nothing above survives; return the author's
                              ``known_valid_baseline``, the one configuration
                              known to work.
      6. ``none``           — not a rung. No baseline was declared, so there is
                              genuinely nothing legal to return, and saying so
                              is better than inventing an origin.

    ``recommendation_levels`` (threaded from ``_close_iteration``) is
    deliberately NOT consulted for the top rung: rung 1/2 read
    ``confirmation.json`` off disk, so a report written on a later iteration
    than the confirm it describes — a budget-exhausted route to ``report``, or a
    resumed work_dir — still reports the terminal result rather than an empty
    one. It stays in the signature because the non-confirm callers pass it and
    because it is what makes a terminal reached straight from ``screen`` fall to
    the model rung rather than to ``measured``.

    BOTH BOUNDS, SEPARATELY (spec §3.5). ``residual_regret_model`` and
    ``residual_regret_terminal`` are distinct fields with distinct deltas
    (``delta_screen``, ``delta_terminal``) because they rest on different
    assumptions: the model bound carries the registered response class, the
    terminal bound carries nothing but the fresh measurements. Collapsing them
    into one number would advertise the assumption-light guarantee while
    delivering the model-dependent one.
    """
    primary = (((campaign.get("optimization") or {}).get("response") or {})
               .get("primary") or {})
    metric = primary.get("metric") or ""
    direction = primary.get("direction") or pol["objective"]["direction"]
    conf = _latest_confirmation(work_dir)
    rec = _read_recommendation(work_dir) or {}

    if conf and conf.get("best"):
        basis = "certified" if conf.get("certified") else "terminal_best"
        levels, value = dict(conf.get("confirmed_at_levels") or {}), conf.get("mean")
    elif rec.get("levels") and not _measured_infeasible_contains(
        work_dir, rec["levels"],
    ):
        basis, levels, value = "model", dict(rec["levels"]), rec.get("predicted")
    else:
        best = (
            _best_observed(work_dir, metric, direction=direction)
            if metric else None
        )
        if best:
            basis, levels, value = "measured", dict(best["levels"]), best.get(metric)
        elif pol.get("known_valid_baseline"):
            basis, levels, value = "baseline", dict(pol["known_valid_baseline"]), None
        else:
            basis, levels, value = "none", {}, None

    trans = policy_mod.read_transitions(work_dir)
    _write_json(Path(work_dir) / "report.json", {
        "recommendation": {
            "levels": levels, "basis": basis,
            **({"value": value} if value is not None else {}),
        },
        "residual_regret_model": (rec.get("residual_regret_model") or {}).get("value"),
        "residual_regret_terminal": (
            conf.get("residual_regret_terminal") if conf else None
        ),
        "epsilon": conf.get("epsilon") if conf else rec.get("epsilon"),
        "delta_screen": pol["objective"]["delta_screen"],
        "delta_terminal": pol["objective"]["delta_terminal"],
        "certified": bool(conf and conf.get("certified")),
        "finalists": (conf.get("finalists") if conf else []) or [],
        "known_valid_baseline": pol.get("known_valid_baseline"),
        "path": [t["from"] for t in trans] + ([trans[-1]["to"]] if trans else []),
        "epoch": pol["epoch"],
        "policy_hash": policy_mod.policy_hash(pol),
        "iteration": iteration,
    })
    logger.info(
        "report: recommendation %s on basis %r (certified=%s); R_model=%s, "
        "R_terminal=%s at delta_s=%s / delta_t=%s",
        levels, basis, bool(conf and conf.get("certified")),
        (rec.get("residual_regret_model") or {}).get("value"),
        conf.get("residual_regret_terminal") if conf else None,
        pol["objective"]["delta_screen"], pol["objective"]["delta_terminal"],
    )
    engine.transition("DONE")


def _measured_infeasible_contains(work_dir, levels: dict) -> bool:
    """Has this exact configuration already been MEASURED inadmissible?

    The model rung of the ladder must not hand back a configuration the campaign
    watched fail. ``decide.ranked`` already excludes measured-infeasible points
    from the candidate space when it produces a recommendation, but the report
    may be reading a recommendation written EARLIER than the run that
    invalidated it — a confirm round that measured the model's argmax
    infeasible, most obviously — so the check is repeated at the point of use.

    Compares numerics with a tolerance, for the same reason
    ``matrix.check_fidelity`` does: levels round-trip through JSON, so an exact
    ``!=`` on a float would report a mismatch a representation step away and
    silently promote an infeasible configuration back onto the model rung.
    """
    import math as _math

    want = dict(levels or {})
    if not want:
        return False
    for other in _measured_infeasible(work_dir):
        if set(other) != set(want):
            continue
        same = True
        for k, v in want.items():
            o = other[k]
            if (isinstance(v, (int, float)) and isinstance(o, (int, float))
                    and not isinstance(v, bool) and not isinstance(o, bool)):
                if not _math.isclose(float(o), float(v), rel_tol=1e-9,
                                     abs_tol=1e-12):
                    same = False
                    break
            elif o != v:
                same = False
                break
        if same:
            return True
    return False


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
    #
    # Resolved ONCE: `_resolve_state` may compile and write policy.json, and
    # calling it twice would re-read (and re-hash-check) the same file for no
    # reason. `stage_name`/`pol` below are these same values.
    stage_name, pol = _resolve_state(campaign, work_dir, iteration, stage)
    _is_build = stage_name == Stage.BUILD.value

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
        # A pre-epoch stage is never terminal: the epoch has not started, so
        # there is no policy path to have reached its end.
        return IterationOutcome.CONTINUE

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
        # The apparatus is certified, so pre-register the epoch's policy: a
        # JSON document hashed BEFORE the first benchmark run is what makes
        # the path a pre-registration rather than a story told afterwards.
        pol = _compile_and_write_policy(campaign, work_dir)
        logger.info(
            "verify: compiled experimental policy %s (epoch %d)",
            policy_mod.policy_hash(pol)[:12], pol["epoch"],
        )
        _enter_phase(engine, "HUMAN_DESIGN_GATE", work_dir)
        _enter_phase(engine, "EXECUTE_ANALYZE", work_dir)
        _enter_phase(engine, "HUMAN_FINDINGS_GATE", work_dir)
        append_ledger_row(work_dir, iteration)
        return IterationOutcome.CONTINUE

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
    #
    # CONFIRM DOES NOT BUILD A CODED DESIGN AT ALL. It is the terminal
    # DISCRIMINATION state (spec §3.3; the paper's Figure 1 calls it
    # `discriminate`): a shortlist of finalists, each measured freshly, so
    # `_confirm_rows` returns rows and payload directly from real levels and
    # `design` stays None. `_build_design` is therefore never called for
    # confirm, and `fit_effects` is never reached on that path either.
    direction = (
        (response_spec.get("primary") or {}).get("direction", "maximize")
    )
    design = None
    if stage_name == Stage.CONFIRM.value:
        rows, payload = _confirm_rows(
            pol, work_dir, factors, primary, direction, iteration,
        )
    else:
        design = _build_design(factors, design_cfg, stage_name)
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
    #
    # AT REFINE, `levels[0]` is the wrong level and the failure is total.
    # Refine spans only the refinable factors, so every `choice` factor is
    # held — and `levels[0]` is an arbitrary declaration order, not a
    # measurement. Measured on `synthetic.SURFACES["choice_x_numeric"]`, whose
    # numeric optimum flips sign with the choice level: all eight refine runs
    # sat at C="off", so the whole refine stage measured the ANTI-optimal
    # branch and the quadratic it fitted described a surface the campaign had
    # no interest in.
    #
    # The screen stage already answered which level to hold: its
    # recommendation is the argmax of the screen fit over the WHOLE candidate
    # space, choice factors included. Hold at that, and fall back to
    # `levels[0]` only when no recommendation exists yet.
    #
    # Scoped to refine on purpose. Screen is the stage that PRODUCES the
    # recommendation, so at screen there is nothing but `levels[0]` to hold
    # at.
    #
    # CONFIRM IS EXCLUDED EXPLICITLY. Every finalist `_confirm_rows` builds
    # already names a level for EVERY factor — it validates that and aborts
    # otherwise — so there is nothing non-designed to hold, and merging a
    # `levels[0]` default over a finalist could only corrupt it. The
    # `_design_factor_ids` call below happens to return the full factor set at
    # confirm, which would make `held` empty anyway; relying on that
    # coincidence would leave the two facts free to drift apart, so say it.
    designed = set(_design_factor_ids(factors, design_cfg, stage_name))
    held = [f for f in factors if f.id not in designed]
    if held and rows and stage_name != Stage.CONFIRM.value:
        import dataclasses

        prev_levels = (
            (_read_recommendation(work_dir) or {}).get("levels")
            if stage_name == Stage.REFINE.value else None
        )
        fixed = {
            f.id: (
                prev_levels[f.id]
                if prev_levels and f.id in prev_levels else f.levels[0]
            )
            for f in held if getattr(f, "levels", None)
        }
        if fixed:
            logger.info(
                "%s: holding %d non-designed factor(s) fixed at %s so the "
                "target still receives every flag: %s",
                stage_name, len(fixed),
                "the previous stage's recommendation" if prev_levels
                else "their first declared level",
                fixed,
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

    if _enter_phase(engine, "DESIGN", work_dir):
        _preflight_design(rows, factors, opt, iter_dir)
        # Provenance: every matrix materialised inside the epoch cites the
        # policy that scheduled it, so a reader can check that this design was
        # produced under the policy that was pre-registered and not a later one.
        payload["policy_hash"] = policy_mod.policy_hash(pol)
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
        # Confirm does NOT fit a model. It compares a SHORTLIST of finalists on
        # fresh replicates, so there is no coded design to estimate effects
        # from — and that is the point: the terminal comparison must not rest
        # on the fitted surface (spec §3.3, paper §Design). `payload` carries
        # the finalist roster, so `_finish_confirm` groups the outcomes without
        # re-deriving who was who.
        return _finish_confirm(
            engine, campaign, stage_name, iteration, iter_dir, work_dir,
            rows, outcomes, ys, factors, test_results, pol, payload,
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
    stationary = None
    if stage_name == Stage.REFINE.value:
        # The stationary point survives as a DIAGNOSTIC, not as an answer.
        # `decide_after_refine` still reads it, because OPTIMUM_OUTSIDE_HULL is
        # a real and useful finding — "the ranges were too narrow to contain
        # the optimum" is worth reporting whether or not anything replicates
        # the point. What no longer happens is confirm reproducing it: see
        # `recommendation.json` below and the confirm branch above.
        stationary = solve_stationary_point(fit, fitted_ids)
        fitted_factors = [f for f in factors if f.id in set(fitted_ids)]
        decision = decide_after_refine(
            fit, fitted_factors, stationary, behavioral_failures=behavioral,
        )
    else:
        decision = decide_after_screen(fit, factors, behavioral_failures=behavioral)

    # ── the recommendation: x-hat = argmax over X_valid (spec §3.3) ────────
    #
    # This REPLACES "solve grad = 0 and replicate the result". Two defects the
    # solve could not avoid, both measured on the synthetic oracle:
    #
    #   * a SADDLE point is a stationary point. On `SURFACES["saddle"]` the
    #     solve returns the centre of the surface, which is the WORST place to
    #     sit along one of the two axes; the argmax returns a corner.
    #   * a CHOICE factor has no gradient, so the solve simply cannot see it.
    #     On `SURFACES["choice_x_numeric"]`, where the numeric optimum flips
    #     sign with the choice level, that loses the optimum outright.
    #
    # Configurations already MEASURED infeasible or rejected are removed from
    # the candidate space before the argmax: the campaign has direct evidence
    # those points are inadmissible, and recommending one anyway would be
    # recommending a configuration it watched fail.
    held_now = dict(payload.get("held_fixed") or {})
    excluded = _measured_infeasible(work_dir)
    # `top=None` means "no truncation", so one call gives both the shortlist
    # and the size of the space it was chosen from. Ordering stays in `decide`
    # — re-deriving the argmax here would put the tie-break and the direction
    # sign in two places.
    scored = decide.ranked(
        fit, factors, direction=direction, fitted_ids=fitted_ids,
        held_fixed=held_now, exclude_levels=excluded, top=None,
    )
    # `top_candidates` is not only a human-readable "how close was the
    # runner-up" — it is the POOL `_confirm_rows` draws the terminal shortlist
    # from, including the round-r top-up after finalists are excluded. Capping
    # it at 5 while `shortlist_size` may be larger would silently starve the
    # shortlist: measured on `SURFACES["sla"]` at shortlist 9, the confirm stage
    # could seat only 6 finalists because the pool held 5. Keep 5 as the floor
    # (the reporting purpose it has always served) and widen it to whatever the
    # registered shortlist needs, plus headroom for the candidates the terminal
    # stage will measure inadmissible and drop.
    _shortlist = int(
        ((pol.get("states") or {}).get("confirm") or {}).get("design", {})
        .get("shortlist_size", 3),
    )
    top = scored[:max(5, _shortlist * 2)]
    if not top:
        raise OptimizationAborted(
            f"{stage_name}: every candidate configuration was already measured "
            f"infeasible or rejected ({len(excluded)} such row(s)), so the "
            f"valid space is empty and no recommendation exists. Widen the "
            f"factors' declared levels or relax the constraint that rejected "
            f"them.",
        )
    rec = top[0]
    # ── how much doubt remains: R_delta(x-hat) (spec §3.5, paper eq. 2) ────
    #
    # A recommendation is not a certificate. `scored` is the WHOLE valid space,
    # which is what eq. (2)'s `max over z in X_valid` requires — computing the
    # bound over `top` (the five-row shortlist) would be silent about a sixth
    # candidate whose interval still reaches above x-hat. This reuses the one
    # enumeration above rather than calling `ranked` again: two enumerations of
    # the same space could in principle disagree, and the bound must be taken
    # over exactly the space the argmax was taken over.
    rb = certificate.model_regret_bound(
        fit, scored, rec, delta=pol["objective"]["delta_screen"],
        direction=direction,
    )
    epsilon = certificate.resolve_epsilon(pol["objective"]["epsilon"], rec.predicted)
    _write_json(iter_dir / "recommendation.json", {
        "stage": stage_name,
        "iteration": iteration,
        "levels": rec.levels,
        "coded": rec.coded,
        "predicted": rec.predicted,
        "fitted_ids": list(fitted_ids),
        "held_fixed": held_now,
        "top_candidates": [
            {"levels": c.levels, "coded": c.coded, "predicted": c.predicted}
            for c in top
        ],
        "stationary_point": stationary,
        "excluded_measured_infeasible": excluded,
        "residual_regret_model": rb.as_dict(),
        "epsilon": epsilon,
    })
    logger.info(
        "%s: recommendation %s (predicted %s=%.6g) — argmax over %d valid "
        "candidate(s), %d measured-infeasible configuration(s) excluded; "
        "residual regret R_%.3g=%s vs epsilon=%.6g (%s)",
        stage_name, rec.levels, primary or "response", rec.predicted,
        len(scored), len(excluded), rb.delta,
        "unknown" if rb.value is None else f"{rb.value:.6g}",
        epsilon, rb.method,
    )

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

    # ── the policy decides what happens next, not the iteration index ─────
    #
    # `observations_from_decision` projects the FIT-derived facts;
    # `refinable_survivors` is recomputed here rather than taken from
    # `len(decision.surviving)` because the screen -> refine guard asks how many
    # survivors carry CURVATURE (is_refinable), and a survivor set of
    # choice/2-level factors would otherwise route to a refine stage that
    # `_build_design` correctly refuses to build.
    by_fid = {f.id: f for f in factors}
    obs = observations_from_decision(
        decision, fit,
        refinable_survivors=sum(
            1 for fid in decision.surviving
            if fid in by_fid and is_refinable(by_fid[fid])
        ),
        stationary_in_hull=(
            None if stage_name != Stage.REFINE.value
            else (stationary is not None
                  and all(-1.0 <= v <= 1.0 for v in stationary.values()))
        ),
    )
    obs.update({
        "correctness_failed": False,
        # Rule 8's "any COMPLETE row whose primary metric is NaN". Scoping to
        # `complete` is load-bearing, not a nicety: `_fitting_responses` carries
        # NaN for `infeasible`/`rejected` rows too, and those are trustworthy
        # measurements of an inadmissible configuration — real information about
        # the design space (spec §6.4). A bare `any(v != v for v in ys)` routes
        # one inadmissible corner of a constrained design straight to
        # `exception`, which would make constraints unusable and would reverse
        # two existing behaviours (see
        # test_infeasible_row_does_not_nan_poison_the_fit).
        "nan_response": any(
            v != v and getattr(o, "status", None) == "complete"
            for o, v in zip(outcomes, ys)
        ),
        "budget_remaining": _budget_remaining(pol, work_dir),
        # No compiled guard reads `round` at screen or refine — neither state
        # self-loops, so there are no rounds to count. Reported as 0 (rather
        # than omitted) because `step` treats an absent key as unknown, and
        # "unknown" is a different fact from "zero" for any guard a later task
        # registers here.
        "round": 0,
        "certified": False,
        # The certificate, in the closed observation vocabulary, so a compiled
        # guard can read `residual_regret <= epsilon` without any code being
        # generated. `None` when there is no pure-error estimate, and `step`
        # treats a None observation as UNKNOWN rather than as a match — which
        # is the behaviour a certificate needs: a bound that could not be
        # computed must never satisfy a guard that would certify on it.
        #
        # `certified` stays False here regardless: screen and refine never
        # certify. Only confirm's terminal discrimination does (Task 9), on the
        # assumption-light terminal bound, and spec §3.5 forbids collapsing the
        # two deltas into one number.
        "residual_regret": rb.value,
        "epsilon": epsilon,
    })
    return _close_iteration(
        engine, campaign, work_dir, iter_dir, iteration, stage_name, pol, obs,
        recommendation_levels=None,
    )


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


# `_terminal_outcome` / `_is_final_stage` lived here until the compiled policy
# replaced them. Both answered "is this stage the last one?" from the campaign's
# `stages` LIST — an index question — and both are now answered by
# `policy.step`: a state is terminal when the interpreter routes to `report` or
# `exception`, which is a fact about the observations rather than about a list
# position. Keeping them as unreachable helpers would leave two definitions of
# finality in one module, and the index one is the wrong one.


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


def _confirm_rows(pol: dict, work_dir: Path, factors, primary: str,
                  direction: str, iteration: int) -> tuple[list, dict]:
    """The confirm state's rows: a SHORTLIST of finalists x fresh replicates.

    This is the paper's terminal discrimination (Figure 1 names the state
    ``discriminate``; ``confirm`` is this branch's older name for it, and the
    behaviour here is the paper's). Screening produces a shortlist
    ``S subset of X_valid``; every member of ``S`` is then measured freshly and
    they are compared with each other, so the final comparison does not rest on
    the fitted response at all. The remaining global claim is only that
    screening did not exclude the true optimum — hence spec §3.5's
    ``Pr(wrong global decision) <= delta_s + delta_t``, two risks kept apart.

    WHAT THIS REPLACES, and why it is not just "more replicates". Until now
    confirm resolved ONE target — the latest ``recommendation.json``, i.e. the
    argmax of the FITTED surface — and replicated it. Tight agreement between
    those replicates was reported as CONFIRMED, but the replicates only ever
    measured how repeatable one configuration is; whether it was the best
    configuration remained a claim about the model. Measuring several finalists
    against each other is what makes the terminal claim model-free, and it is
    also what lets a finalist the model liked be REJECTED on measurement (see
    ``_finish_confirm``'s exclusion rule and ``SURFACES["sla"]``, where the
    fitted argmax is infeasible and only a measurement can say so).

    FINALIST SELECTION. Round 1, dedup'd by levels, in this priority and
    stopping at ``shortlist_size``:

      1. the latest ``recommendation.json``'s ``levels`` — the model's answer,
         which the shortlist exists to put on trial rather than to trust;
      2. the best measured VALID configuration (``_best_observed``, which
         filters to ``status == "complete"``) — spec §3.6 rung 3's "never
         return the largest noisy observation" needs it in the comparison, not
         only in the report;
      3. ``recommendation.json``'s ``top_candidates`` in order — the near
         misses whose intervals still reach above x-hat.

    Round r > 1 keeps the previous round's winner plus every finalist whose
    bound still exceeded epsilon: those are exactly the challengers that could
    still change the epsilon-optimal decision (paper, Figure 2), so spending
    the next round's budget anywhere else buys nothing.

    ``known_valid_baseline`` is the last resort — a campaign with no fitting
    stage behind it and nothing measured has no other legal configuration.

    NO CODED COORDINATES ANYWHERE. Every row's ``levels`` is a finalist's real
    levels and its ``apply`` is rendered from those levels by
    ``matrix.render_apply``. That retires a bug class rather than guarding
    against it: the predecessor carried the target as coded coordinates for
    ``matrix.expand`` to decode, and ``matrix._decode_level`` treats
    ``role="center"`` as "ignore the coordinates, use the midpoint of every
    declared range" — so labelling the target "center" discarded it silently.
    Observed on a real campaign: a point at coded +0.9 of [64, 256] ran level
    160 instead of 246, and the campaign reported "the predicted optimum
    reproduced" about a configuration the fit never predicted. Setting
    ``levels`` directly cannot express that bug; there is no coordinate left to
    discard.

    RUN ORDER is randomized WITHIN each replicate block (seed
    ``iteration * 1000 + i``) rather than across the whole matrix, so every
    finalist is measured once before any is measured twice. A drifting machine
    then shifts all the finalists together instead of loading the drift onto
    whichever one happened to be scheduled late — which is the confound the
    terminal comparison is least able to absorb, since it compares finalists
    directly rather than through a fitted surface.
    """
    from orchestrator.optimize.matrix import (
        ConfigRow,
        randomized_run_order,
        render_apply,
    )

    cfg = (pol["states"]["confirm"] or {})["design"]
    k = max(1, int(cfg.get("shortlist_size", 3)))
    r = max(1, int(cfg.get("replicates", 3)))
    rnd = _confirm_round(work_dir)
    finalists: list[dict] = []
    provenance: list[str] = []

    def _add(levels, why: str, *, allow_measured_invalid: bool = False) -> None:
        """Seat a finalist, unless it is a duplicate, the list is full, or the
        campaign has already MEASURED this exact configuration inadmissible.

        The measured-invalid filter lives HERE, in the one place every seeding
        path goes through, rather than in the individual branches. It was
        originally only on the round-r top-up branch, which left a live gap: a
        round r > 1 whose entire carry-over was excluded produces no finalist,
        falls through to the round-1 ladder, and that ladder re-seats
        ``recommendation.levels`` / ``top_candidates`` verbatim — so the round
        would burn its whole budget re-measuring configurations an earlier round
        had already proved inadmissible. `SURFACES["sla"]` does not exercise it
        (``B=2`` always survives there, so the carry-over is never empty), which
        is exactly why it needed finding by reading rather than by running.

        Filtering unconditionally is also strictly better on round 1: a screen
        stage with infeasible corners, or a resumed work_dir, can put
        measured-invalid rows on disk before the first confirm round, and there
        was never a reason to seat one.

        ``allow_measured_invalid`` is the ONE exemption, and only
        ``known_valid_baseline`` takes it. That rung is the author's declared
        "this configuration works", the bottom of spec §3.6's ladder, and it is
        reached only when nothing else is left — so dropping it on a contrary
        measurement would leave the campaign with nothing legal to return at
        all, which is worse than measuring it again and recording the
        contradiction. `_finish_confirm` still excludes it if it measures
        invalid, and `_run_report` still reports it as ``basis: baseline``.
        """
        if not levels:
            return
        lv = dict(levels)
        if any(lv == f for f in finalists) or len(finalists) >= k:
            return
        if not allow_measured_invalid and _measured_infeasible_contains(work_dir, lv):
            logger.info(
                "confirm round %d: not seating %s (%s) — the campaign has "
                "already MEASURED this configuration inadmissible, so a round "
                "spent re-measuring it would learn nothing.", rnd, lv, why,
            )
            return
        finalists.append(lv)
        provenance.append(why)

    if rnd > 1:
        prev = _latest_confirmation(work_dir) or {}
        eps = prev.get("epsilon")
        by_key = {f["key"]: f for f in prev.get("finalists") or []}
        winner = by_key.get(prev.get("best") or "")
        if winner:
            _add(winner.get("levels"), "previous round's best")
        for f in prev.get("finalists") or []:
            bound = (prev.get("bounds") or {}).get(f["key"])
            # `None` is UNKNOWN, not "small": a challenger whose bound could
            # not be computed has not been shown to be out of contention, so it
            # stays in the shortlist. Only a bound that was computed AND came
            # in at or below epsilon retires a finalist.
            if f.get("status") == "ok" and (
                eps is None or bound is None or bound > eps
            ):
                _add(f.get("levels"), f"round {rnd - 1} bound above epsilon")
    if not finalists:
        # The round-1 ladder, and also the recovery path for a round r > 1 whose
        # entire carry-over was excluded. Both want the same priority order, and
        # both are filtered against measured-invalid levels by `_add`.
        rec = _read_recommendation(work_dir) or {}
        _add(rec.get("levels"), f"{rec.get('stage') or 'model'} recommendation")
        best = _best_observed(work_dir, primary, direction=direction)
        if best is not None:
            _add(best["levels"], "best measured valid configuration")
        for c in rec.get("top_candidates") or []:
            _add(c.get("levels"), "model top candidate")
        if not finalists:
            _add(pol.get("known_valid_baseline"), "known_valid_baseline",
                 allow_measured_invalid=True)
    elif rnd > 1 and len(finalists) < k:
        # TOP UP a shortlist the previous round shrank.
        #
        # Retiring a finalist (its bound fell below epsilon, or a measurement
        # showed it invalid) leaves room, and re-running a two-member comparison
        # unchanged would spend the round learning nothing. Fill from the
        # model's ranked candidates; `_add` skips anything already measured
        # inadmissible, which after a round of exclusions makes this a strictly
        # better informed list than the one round 1 drew from.
        #
        # This is the mechanism `SURFACES["sla"]` needs. There the model's whole
        # top-3 violates the p99 constraint (the fit has no p99 term, so only a
        # measurement can say so); round 1 excludes all three, and round 2 draws
        # the next candidates down the ranking — which is how the campaign
        # reaches the true CONSTRAINED optimum rather than settling for the one
        # feasible corner that happened to be on the first shortlist.
        invalid = _measured_infeasible(work_dir)
        rec = _read_recommendation(work_dir) or {}
        for c in rec.get("top_candidates") or []:
            _add(c.get("levels") or {},
                 f"round {rnd} top-up from the model's ranking")
        if len(finalists) < k:
            logger.info(
                "confirm round %d: shortlist topped up to %d of a requested %d; "
                "the model's ranking offers no further candidate that has not "
                "already been measured inadmissible (%d such configuration(s)). "
                "`recommendation.json.top_candidates` is the pool, so a wider "
                "shortlist needs a wider pool.",
                rnd, len(finalists), k, len(invalid),
            )
    if not finalists:
        n_invalid = len(_measured_infeasible(work_dir))
        raise OptimizationAborted(
            f"confirm has no finalist to measure: nothing on the ladder survived "
            f"— no recommendation.json on disk, no completed run to name a best "
            f"measured configuration, and no optimization.known_valid_baseline "
            f"to fall back on. "
            + (
                f"{n_invalid} configuration(s) WERE measured inadmissible and "
                f"are therefore not re-seated; if the model's ranking holds "
                f"nothing else, the declared design space may contain no valid "
                f"configuration at all. "
                if n_invalid else ""
            )
            + "Run a fitting stage first, declare known_valid_baseline so the "
              "campaign always has one configuration it may legally return, or "
              "relax the constraint that rejected everything.",
        )

    # Every finalist must name a level for EVERY declared factor.
    # `render_apply` renders nothing for an id it is not given, so a partial
    # finalist silently drops that factor's flag from the command line — the
    # "the following arguments are required" failure, invisible in runs.jsonl
    # because the row's `levels` would simply lack the key. Every source above
    # covers every factor by construction (a recommendation's levels are
    # held_fixed + fitted; a run row records what executed; a baseline is
    # author-declared and validator-checked), so a gap here means the
    # campaign's factor set changed under a resumed work_dir.
    for lv, why in zip(finalists, provenance):
        missing = [f.id for f in factors if f.id not in lv]
        if missing:
            raise OptimizationAborted(
                f"confirm: the {why} names no level for {missing!r}, so those "
                f"factors' flags would be missing from every replicate's "
                f"command line. This happens when a campaign's factor list "
                f"changed after the recommendation was written — re-run the "
                f"fitting stage against the current factors rather than "
                f"confirming a partial configuration.",
            )

    rows: list[ConfigRow] = []
    idx = 0
    for i in range(r):
        for j in randomized_run_order(len(finalists), seed=iteration * 1000 + i):
            lv = finalists[j]
            rows.append(ConfigRow(
                row_index=idx, levels=dict(lv), role="confirm", replicate=i,
                # `finalist` rides on `apply` because ConfigRow has no field
                # for it and `runs.jsonl` records `apply` verbatim — so which
                # finalist each row measured is durable evidence rather than an
                # inference from matching level dicts after the fact.
                apply={**render_apply(factors, lv), "finalist": j},
            ))
            idx += 1
    payload = {
        "factor_ids": [f.id for f in factors],
        "kind": "shortlist_replicate",
        "resolution": None,
        "generators": [],
        "aliases": [],
        # The permutation is INSIDE each block, so the payload's top-level
        # run_order is the identity: `run_stage` executes `rows` in the order
        # this function returned them, which already carries the per-block
        # shuffle. A second permutation over the whole matrix would undo the
        # "every finalist once before any twice" property.
        "run_order": list(range(len(rows))),
        "run_order_seed": iteration,
        "round": rnd,
        "finalists": [
            {"key": f"f{j}", "levels": lv, "why": why}
            for j, (lv, why) in enumerate(zip(finalists, provenance))
        ],
        "rows": [
            {"row_index": x.row_index, "levels": dict(x.levels), "role": x.role,
             "replicate": x.replicate, "apply": x.apply}
            for x in rows
        ],
    }
    logger.info(
        "confirm round %d: %d finalist(s) x %d replicate(s) = %d fresh runs; "
        "finalists %s", rnd, len(finalists), r, len(rows),
        [{"key": f"f{j}", "why": w, "levels": lv}
         for j, (lv, w) in enumerate(zip(finalists, provenance))],
    )
    return rows, payload


def _latest_confirmation(work_dir) -> dict | None:
    """The most recent ``confirmation.json``, if any.

    Mirrors ``_read_recommendation`` — including its NUMERIC iteration sort,
    for the same reason: ``"iter-10"`` sorts before ``"iter-2"`` as a string,
    so a lexicographic walk silently returns a STALE record on any campaign
    reaching double digits. Two consumers: round r > 1's finalist carry-over,
    and ``_run_report``'s top rung.
    """
    import json

    if work_dir is None:
        return None
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return None

    def _iter_index(path: Path) -> int:
        try:
            return int(path.name.split("-", 1)[1])
        except (IndexError, ValueError):
            return -1

    for d in sorted(
        (p for p in runs.iterdir() if p.is_dir()), key=_iter_index, reverse=True,
    ):
        p = d / "confirmation.json"
        if not p.exists():
            continue
        try:
            payload = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _build_design(factors, design_cfg: dict, stage_name: str):
    """Design for this stage: a screen matrix, or a response surface.

    Takes no ``work_dir``. It used to, solely so the confirm branch could read
    the previous stage's stationary point off disk and encode it as coded
    coordinates — the indirection that let ``role="center"`` discard the point
    silently. Confirm's target is now applied to the ROWS by ``run_stage``
    (from ``recommendation.json``), so design generation is a pure function of
    the factors and the config again, which is what makes it comparable across
    stages in a test without a filesystem.
    """
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
            # solve_stationary_point returned None, no confirm target was
            # written, and `confirm` replicated the ORIGIN instead of the
            # optimum. The campaign had already observed the true optimum
            # (117.854) and then confirmed a 73.476 centre point. (Task 7
            # retired the stationary-point handoff — confirm now replicates
            # `recommendation.json` — but the reason NOT to fabricate a design
            # over non-refinable factors is unchanged: a quadratic term for a
            # categorical factor is meaningless whatever consumes it.)
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
        # Unreachable, and deliberately loud rather than silently plausible.
        #
        # Confirm is the terminal DISCRIMINATION state: `_confirm_rows` builds
        # its rows from real levels (finalists x replicates) and `run_stage`
        # never routes confirm through here. The branch that used to live at
        # this spot returned `replicates` rows at coded 0.0 for `run_stage` to
        # overwrite, and it is retired rather than left in place because a
        # design that only ever gets discarded is an invitation to consult it.
        # See `_confirm_rows`'s docstring for the `role="center"` bug class
        # that history records — the reason confirm carries no coordinates at
        # all.
        raise OptimizationAborted(
            "internal error: _build_design was called for the confirm state. "
            "Confirm builds no coded design — it measures a shortlist of "
            "finalists at real levels via _confirm_rows. A caller reaching "
            "here is reading the wrong seam.",
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
                    work_dir, rows, outcomes, ys, factors, test_results, pol,
                    payload):
    """Terminal discrimination: compare the finalists, certify or loop.

    Deliberately writes no ``effects.json``: there is no fit here, and that is
    the whole point of the state. What confirm claims is model-free — these
    ``|S|`` configurations, each measured ``replicates`` times freshly, produced
    these means, and the best of them beats the rest by at least this much with
    probability ``1 - delta_terminal``.

    MEASURED INVALIDITY TRUMPS PREDICTION. A finalist with ANY replicate that
    came back ``infeasible`` / ``rejected`` / not ``complete`` is EXCLUDED
    outright rather than averaged over its surviving replicates. The fitted
    surface has no idea a configuration is inadmissible — on
    ``SURFACES["sla"]`` the model's argmax violates the p99 constraint — so a
    single measured violation is stronger evidence than any number of
    predictions, and averaging it away would let the campaign recommend a
    configuration it watched fail. Excluding on ANY bad replicate rather than a
    majority is the conservative direction: a configuration that is admissible
    only sometimes is not admissible.

    ``pol`` is the compiled policy, threaded from ``run_stage``: confirm is the
    one state that can self-loop, so its next state is a policy decision
    (``certified`` / ``round`` / ``budget_remaining``) rather than "confirm is
    the last stage in the list", which is what the deleted index-based
    ``_is_final_stage`` assumed.

    ``paired`` is False in this task. Task 14 turns it on once
    ``workload.seeds`` puts the same seed set behind every finalist (spec §3.8),
    at which point the bound is computed on paired differences and shrinks
    substantially. Recorded in ``confirmation.json`` so a reader can tell which
    bound they are looking at rather than inferring it from the branch date.
    """
    from statistics import mean, pstdev

    from orchestrator.iteration import _enter_phase, finalize_iteration
    from orchestrator.ledger import append_ledger_row
    from orchestrator.optimize import artifacts, relations

    delta_t = pol["objective"]["delta_terminal"]
    direction = pol["objective"]["direction"]
    sign = 1.0 if direction != "minimize" else -1.0
    paired = bool(payload.get("paired"))
    fin = payload.get("finalists") or []

    by_idx = {r.row_index: r for r in rows}
    samples: dict[str, list[float]] = {f["key"]: [] for f in fin}
    status: dict[str, str] = {f["key"]: "ok" for f in fin}
    for o, y in zip(outcomes, ys):
        row = by_idx.get(o.row_index)
        if row is None:
            continue
        key = f"f{(row.apply or {}).get('finalist', 0)}"
        if key not in samples:
            continue
        if o.status != "complete" or y != y:
            status[key] = "excluded"
        else:
            samples[key].append(float(y))
    ok = {k: v for k, v in samples.items() if status[k] == "ok" and v}

    best = max(ok, key=lambda k: sign * mean(ok[k])) if ok else None
    if best is None:
        bound = certificate.RegretBound(
            None, None, delta_t, "none",
            "no finalist produced a valid measurement",
        )
    else:
        bound = certificate.terminal_regret_bound(
            ok, best, delta=delta_t, direction=direction, paired=paired,
        )
    eps = certificate.resolve_epsilon(
        pol["objective"]["epsilon"], mean(ok[best]) if best else 0.0,
    )

    # AN EXCLUSION AT CONFIRM IS EVIDENCE THAT THE delta_s PREMISE HAS FAILED,
    # SO THE GLOBAL CERTIFICATE IS UNEARNED.
    #
    # Read this carefully, because the obvious reason is the WRONG reason and a
    # maintainer reasoning from it would delete this interlock as unnecessary.
    #
    # The wrong reason: "the realized shortlist is smaller than the one the round
    # planned to compare, so the bound is over a narrowed set." That does not
    # hold. The paper scopes the terminal claim to the REALIZED shortlist — "the
    # final comparison within the realized shortlist therefore does not rely on
    # the response model" — so a bound taken over the survivors is a perfectly
    # valid WITHIN-SHORTLIST claim, even when the survivors number one. Nothing
    # about shrinkage per se invalidates `R_terminal`, and indeed this code still
    # reports that number (see below).
    #
    # The actual reason: `certified` is not a within-shortlist claim. It is the
    # GLOBAL one — epsilon-optimality over `X_valid` — and it rests on
    # `Pr(wrong global decision) <= delta_s + delta_t`, whose `delta_s` term
    # carries a premise: that screening did not exclude the true optimum, i.e.
    # that the model's candidate ranking tracks the objective well enough for the
    # top of it to contain the winner. A finalist measured INADMISSIBLE is direct
    # evidence against that premise. The fit has no constraint term at all, so
    # when the model's ranking hands the terminal stage configurations that turn
    # out invalid, the ranking is demonstrably not tracking the CONSTRAINED
    # objective — and the shortlist it produced carries no reason to contain the
    # constrained optimum. With the `delta_s` premise broken, the sum bound does
    # not hold, and `certified: True` asserts something the campaign has just
    # collected evidence against.
    #
    # Measured on `SURFACES["sla"]` at the default shortlist of 3: the model's
    # whole top-3 violates the p99 constraint, all three are excluded, and the
    # lone surviving corner would certify at R=0.0 — reporting a configuration
    # 6.1% below the true constrained optimum as CERTIFIED epsilon-optimal. The
    # within-shortlist bound of 0.0 is *correct*; it is the global label attached
    # to it that is false, and it is false precisely because the exclusions show
    # screening's ordering had failed.
    #
    # So an exclusion suppresses CERTIFICATION for this round while the policy's
    # default `confirm -> confirm` sends the campaign back with a shortlist
    # re-filled from deeper in the ranking (`_confirm_rows`'s top-up) — which is
    # how the premise gets repaired: by finding candidates that survive
    # measurement. The round cap and the budget guard still terminate it; what
    # changes is that the campaign then reports `terminal_best` — an honest
    # answer — instead of a global certificate it did not earn.
    #
    # `bounds` / `residual_regret_terminal` are deliberately UNAFFECTED. They are
    # the within-shortlist numbers, they are valid as such, and suppressing them
    # would hide the comparison that genuinely did happen.
    n_excluded = sum(1 for v in status.values() if v == "excluded")
    certified = bound.value is not None and bound.value <= eps and not n_excluded
    if n_excluded and bound.value is not None and bound.value <= eps:
        logger.info(
            "confirm: R_terminal=%.6g is at or below epsilon=%.6g over the "
            "surviving finalists, which is a valid WITHIN-SHORTLIST result and "
            "is reported as such. Not certifying globally: %d finalist(s) were "
            "measured inadmissible, which is evidence that the model's ranking "
            "is not tracking the constrained objective — so the delta_screen "
            "premise behind Pr(wrong global decision) <= delta_s + delta_t does "
            "not hold, and epsilon-optimality over X_valid is unearned. Looping "
            "to re-fill the shortlist if the registered round cap allows it.",
            bound.value, eps, n_excluded,
        )

    # Per-challenger bounds, each against the winner alone. These are what
    # round r+1 reads to decide which finalists are still in contention (a
    # bound at or below epsilon cannot change the epsilon-optimal decision), so
    # they are recorded rather than recomputed from the samples later.
    #
    # NOTE ON THE LEVEL. Each entry is computed with M=1, so it is a
    # PER-CHALLENGER bound at delta_t, not a member of the simultaneous family
    # `residual_regret_terminal` is the max of. That is the right level for a
    # "keep measuring this one?" screening decision and the wrong level for a
    # certificate — which is why the certified/uncertified verdict above reads
    # `bound.value` (the simultaneous max) and never these.
    bounds: dict[str, float | None] = {}
    for k in ok:
        if k != best:
            bounds[k] = certificate.terminal_regret_bound(
                {best: ok[best], k: ok[k]}, best,
                delta=delta_t, direction=direction, paired=paired,
            ).value

    winner_levels = next(
        (f["levels"] for f in fin if f["key"] == best), {},
    )
    summary = {
        "stage": stage_name,
        "iteration": iteration,
        "round": payload.get("round", _confirm_round(work_dir)),
        "finalists": [
            {"key": f["key"], "levels": f["levels"], "why": f.get("why"),
             "samples": samples[f["key"]],
             "mean": mean(samples[f["key"]]) if samples[f["key"]] else None,
             "n": len(samples[f["key"]]), "status": status[f["key"]]}
            for f in fin
        ],
        "best": best,
        "bounds": bounds,
        "epsilon": eps,
        "residual_regret_terminal": bound.value,
        "terminal_bound": bound.as_dict(),
        "certified": certified,
        "paired": paired,
        "delta_terminal": delta_t,
        "excluded_infeasible": [
            f["levels"] for f in fin if status[f["key"]] == "excluded"
        ],
        # Legacy fields, kept because readers of the single-point record exist
        # (the harness's recommendation fallback, the guide's worked output, and
        # `_close_iteration`'s recommendation_levels). `confirmed_at_levels` is
        # now the WINNING finalist rather than the only configuration run.
        "confirmed_at_levels": dict(winner_levels),
        "replicates": len(outcomes),
        "usable_replicates": sum(len(v) for v in ok.values()),
        "mean": mean(ok[best]) if best else None,
        "spread": pstdev(ok[best]) if best and len(ok[best]) > 1 else 0.0,
        "observations": list(ok[best]) if best else [],
    }

    # Did the winning finalist actually beat everything the campaign measured?
    #
    # A fitted argmax is an EXTRAPOLATION, and the shortlist only puts it on
    # trial against the other finalists — not against every corner the screen
    # measured. When the surface is mis-specified the winner can still land
    # below a corner from an earlier stage. "The best finalist" and "the best
    # configuration found" are different claims, and only the second is what a
    # reader of the report wants; recording both keeps the artifact honest when
    # they disagree. (The shortlist now INCLUDES `_best_observed` by
    # construction, so a disagreement here means the earlier corner was
    # measured worse this time round — real information about run-to-run
    # variation, not a bug.)
    primary_spec = (
        ((campaign.get("optimization") or {}).get("response") or {})
        .get("primary") or {}
    )
    metric = primary_spec.get("metric") or ""
    maximize = direction != "minimize"
    best_obs = (
        _best_observed(work_dir, metric, direction=direction) if metric else None
    )
    if best_obs is not None and summary["mean"] is not None:
        best_val = best_obs.get(metric)
        if isinstance(best_val, (int, float)):
            confirmed_mean = summary["mean"]
            beats = (
                confirmed_mean >= best_val if maximize
                else confirmed_mean <= best_val
            )
            summary["best_observed"] = {
                "levels": dict(best_obs.get("levels") or {}),
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
                    "confirm: the winning finalist (%s=%.6g) is WORSE than the "
                    "best configuration already observed (%.6g at %s) — a gap "
                    "of %.6g (%.2f%%). Treat the observed corner as the "
                    "campaign's answer and the surface as mis-specified.",
                    metric or "response", confirmed_mean, best_val,
                    best_obs.get("levels"), gap, pct,
                )

    _write_json(iter_dir / "confirmation.json", summary)
    # `shortlist.json` is the name spec §3.9's artifact table gives this
    # record. Written as a pointer rather than a copy so there is exactly one
    # source of truth for the finalists and their measurements.
    _write_json(iter_dir / "shortlist.json", {
        "round": summary["round"],
        "finalists": summary["finalists"],
        "best": best,
        "bounds": bounds,
        "epsilon": eps,
        "see": "confirmation.json",
    })
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

    logger.info(
        "confirm round %d: winner %s (%s) with R_%.3g=%s vs epsilon=%.6g -> %s",
        summary["round"], best, winner_levels, delta_t,
        "unknown" if bound.value is None else f"{bound.value:.6g}",
        eps, "CERTIFIED" if certified else "uncertified",
    )

    obs = {
        "correctness_failed": False,
        # No finalist produced a usable measurement, which the policy routes the
        # same way it routes a NaN fit input.
        "nan_response": not ok,
        "certified": certified,
        "round": summary["round"],
        "budget_remaining": _budget_remaining(pol, work_dir),
        # What the NEXT round would cost, in the closed observation vocabulary,
        # so a compiled guard can compare it against the remaining budget
        # without any code being generated.
        "runs_needed_confirm": len(fin) * max(
            1, int((pol["states"]["confirm"]["design"] or {}).get("replicates", 3)),
        ),
        # `residual_regret` / `epsilon` are the TERMINAL pair here, not the
        # model pair screen and refine report under the same keys. The
        # observation vocabulary is closed and deliberately does not distinguish
        # them: a guard reads "the bound this state computed against this
        # state's indifference width", and which flavour that is follows from
        # which state is being left. `report.json` keeps them apart, which is
        # where spec §3.5's "never collapsed" obligation actually bites.
        "residual_regret": bound.value,
        "epsilon": eps,
    }
    return _close_iteration(
        engine, campaign, work_dir, iter_dir, iteration, stage_name, pol, obs,
        recommendation_levels=dict(winner_levels) or None,
    )


def _confirm_findings(summary: dict, iteration: int) -> dict:
    """A findings.schema.json-conformant record of the terminal discrimination.

    THREE statuses, not two. The old record was binary — the replicates either
    reproduced or they did not — which cannot express the middle case that
    terminal discrimination creates and which is now the COMMON one: a winner
    was identified and measured, but its bound is still wider than epsilon, so
    the campaign has an answer and not a certificate. Reporting that as
    CONFIRMED would overstate the claim (the very defect spec §3.5 names by
    refusing to collapse the two deltas), and reporting it as REFUTED would
    throw away a real result.

      * CONFIRMED           — a winner AND ``R_terminal <= epsilon``.
      * PARTIALLY_CONFIRMED — a winner, bound too wide (or not computable).
      * REFUTED             — no finalist produced a valid measurement at all.
    """
    n, usable = summary["replicates"], summary["usable_replicates"]
    best, certified = summary.get("best"), bool(summary.get("certified"))
    r, eps = summary.get("residual_regret_terminal"), summary.get("epsilon")
    excluded = summary.get("excluded_infeasible") or []
    kept = [f for f in summary["finalists"] if f["status"] == "ok"]

    if best is None:
        observed = f"no finalist produced a usable measurement out of {n} runs"
    else:
        observed = (
            f"winner {best} at {summary['confirmed_at_levels']} with "
            f"mean={summary['mean']:.6g} over {len(kept)} finalist(s) and "
            f"{usable}/{n} usable fresh runs; "
            f"R_terminal="
            + ("unknown" if r is None else f"{r:.6g}")
            + f" vs epsilon={eps:.6g}"
            + (f"; {len(excluded)} finalist(s) excluded on measured invalidity"
               if excluded else "")
        )
    status = (
        "CONFIRMED" if certified
        else ("PARTIALLY_CONFIRMED" if best is not None else "REFUTED")
    )
    note = None
    if best is None:
        note = "every fresh run failed to produce a usable measurement"
    elif not certified:
        note = (
            "a winner was identified from fresh measurements but its "
            "residual-regret bound is not below epsilon, so the result is an "
            "answer and not a certificate"
            if r is not None else
            "the terminal bound was not computable (a finalist has fewer than "
            "two usable replicates), so nothing is certified — an unknown bound "
            "is not a small one"
        )
    return {
        "iteration": iteration,
        "bundle_ref": f"runs/iter-{iteration}/confirmation.json",
        "experiment_valid": best is not None,
        "discrepancy_analysis": (
            "Terminal discrimination: a shortlist of finalists was measured "
            "freshly and compared with each other, so this comparison does not "
            "rest on the fitted response surface. No effects are fitted here — "
            "there is no coded design to estimate them from. The remaining "
            "global claim is only that screening did not exclude the true "
            "optimum."
        ),
        "arms": [{
            "arm_type": "h-main",
            "predicted": (
                "the shortlist contains the optimum and fresh measurements "
                "identify it within epsilon"
            ),
            "observed": observed,
            "status": status,
            "error_type": None,
            "diagnostic_note": note,
            "metadata": summary,
        }],
    }


def _best_observed(work_dir, primary: str, *,
                   direction: str = "maximize") -> dict | None:
    """The best COMPLETED configuration observed so far, by primary metric.

    ``complete`` is load-bearing: an ``infeasible`` or ``rejected`` row is a
    trustworthy measurement of an INADMISSIBLE configuration, so it is real
    information about the space and a valid fit exclusion — but never a valid
    answer. Spec §3.6 rung 3 is "re-measure the leading measured VALID
    candidates", and this filter is what makes "valid" true of the result.

    Three consumers: ``_confirm_rows`` puts it in the shortlist (so the
    campaign's answer is never worse than something it already measured),
    ``_finish_confirm`` compares the winner against it, and ``_run_report``
    uses it as the ladder's ``measured`` rung.

    ``direction`` decides which way "best" runs. It defaults to ``maximize``
    because every pre-existing caller and test passes a maximise campaign, and
    a positional-only call site must keep working — but a minimise campaign
    that took the default would get the WORST configuration handed back as its
    fallback answer, so every production call site now passes it explicitly.
    """
    import json as _json

    sign = 1.0 if direction != "minimize" else -1.0
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
            if numeric != numeric:
                continue
            if best is None or sign * numeric > sign * best[1]:
                best = (dict(row.get("levels") or {}), numeric)
    return None if best is None else {"levels": best[0], primary: best[1]}


def _read_recommendation(work_dir) -> dict | None:
    """The most recent stage's ``recommendation.json``, if any.

    Read from disk rather than threaded through the campaign dict so the
    value is durable across the process boundary between iterations — each
    stage is a separate ``run_iteration`` call. Two consumers: ``confirm``
    replicates ``levels``, and ``refine`` holds its non-designed factors at
    the screen recommendation's levels rather than at ``levels[0]``.

    Sort NUMERICALLY on the iteration index, not lexicographically on the
    path. "iter-10" sorts BEFORE "iter-2" as a string, so a lexicographic
    sort silently returns a STALE recommendation on any campaign reaching
    double digits — verified on the predecessor of this function, which read
    ``confirm_at.json``: with a file at both iter-2 and iter-10 it picked
    iter-2's value. A silent wrong answer, no error.

    NO HULL CHECK, unlike that predecessor. It refused a stationary point
    whose coded coordinates fell outside [-1, 1], because confirm would
    otherwise have extrapolated to a configuration the design never
    bracketed (observed on a real campaign: a solve at coded BANDCAP=+1.62 /
    THRESH=-2.30, confirmed at 112.4997 while a measured corner stood at
    182.2159). ``recommendation.json`` cannot express that point: every
    candidate level comes from ``decode_coded``, which CLAMPS to the declared
    range, so a recommendation is in-hull by construction. The out-of-hull
    stationary point is still detected and reported — ``decide_after_refine``
    raises OPTIMUM_OUTSIDE_HULL from it, and it is kept in
    ``recommendation.json`` as ``stationary_point`` — it just no longer
    decides what runs.
    """
    import json

    if work_dir is None:
        return None
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return None

    def _iter_index(path: Path) -> int:
        try:
            return int(path.name.split("-", 1)[1])
        except (IndexError, ValueError):
            return -1

    for d in sorted(
        (p for p in runs.iterdir() if p.is_dir()), key=_iter_index, reverse=True,
    ):
        p = d / "recommendation.json"
        if not p.exists():
            continue
        try:
            payload = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _measured_infeasible(work_dir) -> list[dict]:
    """Level sets the campaign has already MEASURED as inadmissible.

    ``infeasible`` (a constraint or invariant said no) and ``rejected`` (the
    integrity check said no) are both direct evidence that a configuration
    cannot be recommended. They are excluded from the fit already (spec §6.4)
    — which removes their influence on the coefficients but leaves the
    candidate space free to hand one of them back as the argmax, because the
    fitted surface has no idea they are off limits. This closes that: the
    campaign never recommends a point it watched fail.
    """
    out: list[dict] = []
    runs = Path(work_dir) / "runs" if work_dir is not None else None
    if runs is None or not runs.exists():
        return out
    for d in sorted(runs.glob("iter-*")):
        for row in artifacts.read_runs(d):
            if row.get("status") in ("infeasible", "rejected") and row.get("levels"):
                out.append(dict(row["levels"]))
    return out


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
