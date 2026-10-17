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

Four checks hard-fail regardless of gate approval, because auto-approve is
this kind's default (spec §7.1) and removing the human must not remove the
checks:

  1. Executed configs drifting from the pre-registered ``design_matrix.json``
     (``matrix.check_fidelity``) — a silently skipped cell changes the
     design's real resolution, so tolerating it would let the campaign
     overstate what it can estimate.
  2. A held-out metric reaching a fitting input.
  3. A ``correctness`` relation violation.
  4. A ``locked_parameters`` deviation (#246 / F1, matrix-path form): a
     measured row whose observation, at the parameter's declared
     ``optimization.locked_observables`` path, differs from the locked value
     (or omits it). The reflective kind compares against
     ``bundle.experiment_spec.verified_parameters``; this kind has no bundle,
     so the evidence is what the target reports it ran with
     (``locked.check_row``). A lock with no declared observable cannot be
     enforced here, and ``validate_optimization_campaign`` warns naming it.

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
  * ``nan_response`` is "any row that ran to COMPLETION reported a non-numeric
    primary metric". It is checked in ``run_stage`` BEFORE ``_fitting_responses``
    is called, because that function raises on exactly these rows and an abort
    ends the campaign with no report — where the paper's rule is that the
    condition ends the EPOCH and still returns an action. The two remaining
    raises in ``_fitting_responses`` are a different failure class and stay:
    a row that never reached ``complete`` is a MEASUREMENT failure a re-run can
    repair (nothing semantic to revise), and a non-numeric-but-not-NaN value is
    an instrumentation mismatch. See ``_primary_is_nan``.

A SEMANTIC EXCEPTION ENDS THE EPOCH, NOT THE CAMPAIGN (spec §3.2, paper "the one
way back"). ``_close_iteration``'s ``exception`` branch writes
``epoch_end-<epoch>.json`` at the work_dir root, runs the report on the strongest
rung that does NOT rest on the fitted surface, and returns COMPLETED. Because
``transitions.jsonl`` rows carry ``"epoch"`` and ``policy.current_state`` reads
only this epoch's rows, a later ``nous resume <campaign.yaml>`` over the same work_dir
recompiles (``_load_or_compile_policy`` sees ``_epoch_index`` has advanced) and
starts a CLEAN epoch at ``initial`` — it does not resume at the terminal
``exception`` it just left.

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

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from orchestrator.optimize import (
    adapter_contract,
    artifacts,
    certificate,
    concurrency,
    decide,
    exclusions,
    matrix,
    relations,
    resume,
    runner,
)
from orchestrator.optimize import constraint_models as cmodels
from orchestrator.optimize import design as design_mod
from orchestrator.optimize import locked as locked_mod
from orchestrator.optimize import pareto_stage
from orchestrator.optimize import policy as policy_mod
from orchestrator.optimize.effects import (
    fit_effects,
    planned_aliases_separated,
    solve_stationary_point,
)
from orchestrator.optimize.factors import decode_coded, is_refinable, parse_factors
from orchestrator.optimize.stage import (
    Stage,
    Trigger,
    decide_after_refine,
    decide_after_screen,
    observations_from_decision,
)

logger = logging.getLogger(__name__)


class OptimizationAborted(RuntimeError):
    """A hard-fail that must stop the campaign regardless of gate approval."""


class OptimizationGateFailed(OptimizationAborted):
    """A hard gate failed: retrying the same iteration cannot legitimately pass it.

    Distinct from the parent because the campaign loop treats the two
    differently. A plain ``OptimizationAborted`` (too few usable rows, a design
    pre-flight problem) may be retried -- the next attempt reuses the rows it
    already measured. A GATE (a failed correctness relation, a moved control
    baseline, a locked-parameter deviation, drift of the mechanism / adapter
    contract / policy hash, held-out leakage, a planless build) states that the
    apparatus is not the one pre-registered, and every later measurement would
    be about the wrong system. The loop HALTS on it, regardless of
    auto-approve: before this type existed the loop logged the gate as one
    failed iteration and advanced, so a campaign whose verify gate failed went
    on to screen and refine an unverified mechanism.
    """


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


def _primary_of(response_spec) -> dict:
    """``response.primary``, or the FIRST of ``response.objectives``.

    A multi-objective campaign (spec 2026-10-15-pareto-front-design.md) has no
    ``primary``; its first objective plays that role wherever the
    single-objective machinery needs ONE metric (the stage rule's fit,
    effects.json, the NaN guard, the adapter's metric path). Every objective
    is fitted and reported by ``orchestrator.optimize.pareto``. Single-objective
    campaigns read exactly what they always read.
    """
    resp = response_spec if isinstance(response_spec, dict) else {}
    if resp.get("primary") is not None:
        return resp.get("primary") or {}
    from orchestrator.optimize.objectives import declared_objectives

    objs = declared_objectives({"response": resp})
    return dict(objs[0]) if objs else {}


def _opt_block(campaign: dict) -> dict:
    opt = campaign.get("optimization")
    if not isinstance(opt, dict):
        raise OptimizationAborted(
            "kind: optimization requires an 'optimization' block; "
            "see `nous docs guide`",
        )
    return opt


def resolve_run_timeout(opt: dict | None) -> int:
    """The wall-clock ceiling one ``run_command`` invocation runs under.

    Public because the resolution has to be identical in two places that do not
    share a code path: this module, which builds the config runner every epoch
    state measures through, and ``cli._smoke_probe_one_config``, which launches
    exactly one configuration before any epoch exists. ``--smoke`` is where an
    author first meets the ceiling, so it must be the SAME ceiling -- a probe
    that silently ran at 600 while the epoch runs at 5400 (or the reverse) would
    make the one check that exists to catch contract mismatches into a source of
    them.

    Absence resolves to ``DEFAULT_RUN_TIMEOUT_SEC``, i.e. exactly what this seam
    was hardcoded to before the field existed. That is a compatibility
    requirement rather than a preference: an epoch's ``design_matrix.json`` is a
    pre-registration, and a ceiling that moved underneath an already-registered
    design would mean the artifact no longer describes the runs it registered.

    A non-integer or non-positive value cannot reach here from a schema-valid
    campaign (``run_timeout_sec`` is ``type: integer, minimum: 1``), so one is
    treated as absent rather than raising: a run at 0 seconds fails instantly on
    every row, and turning a hand-edited campaign file into an epoch-wide abort
    at the measurement seam would attribute the failure to the wrong place.
    """
    raw = (opt or {}).get("run_timeout_sec")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return runner.DEFAULT_RUN_TIMEOUT_SEC


def resolve_test_timeout(opt: dict | None) -> int:
    """The wall-clock ceiling one ``test_command`` invocation runs under.

    ``resolve_run_timeout``'s twin, public for the same reason: ``--smoke``
    (``cli._smoke_check_optimization``) and the production gate here must run
    the suite under the SAME ceiling, or the check an author runs first would
    pass a suite the campaign then kills at verify.

    Absence resolves to ``runner.DEFAULT_TEST_TIMEOUT_SEC`` (900), the value the
    seam was hard-coded to before ``optimization.test_timeout_sec`` existed, so
    no existing campaign's gate changes. A real 13-factor campaign needed
    ~1,100s: each correctness relation for a performance knob drives the target,
    so the suite's cost is a multiple of one measurement, and a fixed ceiling
    penalised precisely the thorough campaigns the kind is built for.

    A non-integer or non-positive value is treated as absent, on
    ``resolve_run_timeout``'s convention: it cannot reach here from a
    schema-valid campaign, and a 0-second ceiling would fail every relation
    closed while blaming the tests.
    """
    raw = (opt or {}).get("test_timeout_sec")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return runner.DEFAULT_TEST_TIMEOUT_SEC


def resolve_max_parallel(opt: dict | None, *, stage_name: str,
                        measured=None) -> int:
    """The EFFECTIVE ceiling on simultaneous in-flight runs at ``stage_name``.

    ``optimization.max_parallel`` is the campaign's declared ceiling; this is the
    one place that decides where it applies, and the answer is CONFIRM ONLY.
    Everywhere else it resolves to 1 no matter what the campaign says.

    That is not conservatism about thread safety -- the measurement path is
    already race-free (``config_patch`` materialises a per-run COPY of every
    patched file precisely so rows never share mutable state). It is the
    statistics. The spending stages (``screen`` / ``foldover`` / ``refine``) fit a
    response surface over DISTINCT configurations, and co-scheduled rows contend
    for machine resources, so a row's measured response would depend on which
    other rows happened to run beside it. Contention distributed unevenly across
    a design is absorbed by the fitted coefficients as though it were a factor
    effect -- and unlike drift, which run-order randomization spreads across the
    design, a neighbour effect is not something a permutation can average away.
    On a target whose objective is where the system SATURATES, that is the
    measurement rather than noise around it.

    ``confirm`` is different in kind, not in degree. Its rows are emitted one
    complete REPLICATE BLOCK at a time, and within a block every finalist is
    measured exactly once -- so whatever contention the block creates is
    symmetric across exactly the things being compared, shifts all the finalists
    together, and cancels out of the finalist-to-finalist difference, which is
    the only quantity terminal discrimination reads. It is the same argument
    ``_confirm_rows`` makes for shuffling INSIDE a block rather than across the
    matrix; the bound is scoped to be its counterpart, and
    ``runner.execute_design`` keeps blocks a barrier so the scoping holds.

    A spending stage is NO LONGER unconditionally 1, and the paragraphs above
    are why it is not simply widened either: the confound is real, so the width
    rests on a recorded BASIS rather than on the campaign asking nicely.
    ``orchestrator.optimize.concurrency`` owns that decision and the argument for
    it. In short, a spending stage goes above 1 when the campaign declares
    ``optimization.concurrency.load_independent`` (the objective is not a
    function of machine load -- an iteration count, an output size, a simulated
    time), or when a CONTENTION FLOOR was measured at the design's most loaded
    corner and came back under the target's own serial noise floor. ``measured``
    carries that measurement's verdict. Absent both, the answer is still 1.

    CPU pinning -- which an earlier revision of this docstring named as the only
    escape hatch -- is deliberately NOT one of those bases. A disjoint cpu set
    partitions time slices and per-core L1/L2 and leaves L3, memory bandwidth,
    disk queues, page cache, NIC queues, thermal budget and the GPU shared, so
    for the throughput and tail-latency objectives these campaigns declare it
    isolates almost nothing the objective reads, while a per-row cpu set in the
    artifact would testify to an isolation the measurement never had. That is
    declined on the merits, independently of the API being Linux-only.

    Absence resolves to 1 -- exactly what every campaign authored before the
    field existed ran at. That is a compatibility REQUIREMENT rather than a
    preference: ``design_matrix.json`` is a pre-registration, and execution
    conditions that changed underneath an already-registered design would mean
    the artifact no longer describes the runs it registered.

    A non-integer or non-positive value cannot reach here from a schema-valid
    campaign (``max_parallel`` is ``type: integer, minimum: 1``), so one is
    treated as absent rather than raising -- same convention as
    ``resolve_run_timeout``, and for the same reason: turning a hand-edited
    campaign file into an epoch-wide abort at the measurement seam would
    attribute the failure to the wrong place.
    """
    return resolve_concurrency(
        opt, stage_name=stage_name, measured=measured,
    ).width


def resolve_concurrency(opt: dict | None, *, stage_name: str, measured=None):
    """``resolve_max_parallel``'s width TOGETHER WITH the reason for it.

    The width alone is not readable: ``max_parallel: 4`` in an artifact cannot
    be distinguished by a reader from the confound it is only sometimes safe
    against, so the basis travels with it onto the design matrix. Same inputs,
    same determinism; this is the richer return and ``resolve_max_parallel``
    projects it to an int for the call sites that only schedule.
    """
    return concurrency.resolve(
        opt, stage_name=stage_name, confirm_stage=Stage.CONFIRM.value,
        measured=measured,
    )


def _measure_contention_floor(opt, factors, config_runner, *, width):
    """Measure the target's contention floor at the author-named loaded corner.

    Returns a ``concurrency.Verdict``. The corner comes from
    ``optimization.concurrency.contention_probe_levels`` and is NOT defaulted to
    ``known_valid_baseline``: contention inflation grows with load, so a floor
    measured at the cheap corner certifies the loaded corners it gets wrong. See
    ``orchestrator.optimize.concurrency`` for the simulation that establishes
    this and the numbers it produced.

    Both halves of the probe execute through the SAME ``execute_design`` seam the
    epoch measures through, so the concurrency being characterised is the
    concurrency that would run. Every failure returns a ``serial`` verdict, which
    is the safe direction: an unmeasurable target and a refuted one both fall
    back to the behaviour that needs no license.
    """
    levels = concurrency.contention_probe_levels(opt)
    metric = _primary_of((opt or {}).get("response")).get("metric")
    if not levels:
        return concurrency.Verdict(
            width=1, basis=concurrency.BASIS_SERIAL, detail=(
                "optimization.concurrency.contention_probe_levels names no "
                "corner to measure at, so no floor was certified"
            ),
        )
    if not metric:
        return concurrency.Verdict(
            width=1, basis=concurrency.BASIS_SERIAL,
            detail="response.primary.metric is required to compare widths",
        )

    def _probe(w: int) -> list[float]:
        rows = [
            matrix.ConfigRow(
                row_index=i, levels=dict(levels), role="corner", replicate=0,
                apply=matrix.render_apply(factors, dict(levels)),
            )
            for i in range(max(1, w))
        ]
        outcomes = runner.execute_design(
            rows, runner=config_runner,
            response_spec=(opt or {}).get("response") or {},
            invariants=[], factors=factors, max_parallel=w,
        )
        return [o.response.get(metric) for o in outcomes]

    return concurrency.measure_contention_floor(
        _probe, width=width, metric=metric,
    )


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
    ``infeasible`` rows are trustworthy — the config ran and its primary is a
    valid measurement; it is only inadmissible to RETURN — so their primary IS
    fitted (``_PRIMARY_FIT_STATUSES``, INV-STAT15; amends spec §6.4's original
    "exclude from fitting"). Admissibility is enforced at the return points.

    THE NaN-ON-A-COMPLETE-ROW CASE NO LONGER REACHES HERE. ``run_stage`` checks
    for it before calling this function and routes it to the policy's
    ``nan_response -> exception`` branch, because that condition is SEMANTIC (the
    objective and the target's instrumentation disagree about what is measurable
    at that configuration; no re-run repairs it) and the paper's rule is that it
    ends the epoch while the campaign still returns an action. An abort here would
    end the campaign with no report at all.

    The remaining aborts are a DIFFERENT failure class each, and all THREE stay:

      * ``primary`` is also declared ``held_out`` — a campaign misconfiguration,
        caught before any measurement is interpreted;
      * a held-out metric reached a fitting input — the leak this path exists to
        refuse, one of the three checks that hard-fail under auto-approve;
      * the primary metric is a string or a structure — an instrumentation
        mismatch, not a measurement, and not a NaN (see ``_primary_is_nan``).

    A fourth bullet used to sit here — "rows that never reached ``complete``
    carry no measurement" — describing the abort the block below downgraded to a
    warning. It is gone because it had become a docstring promising a guarantee
    the code no longer makes, which is the one kind of comment rot that actively
    misleads the next reader: they would go looking for the abort and conclude
    the warning was the bug.
    """
    held_out = {str(m) for m in (response_spec.get("held_out") or [])}
    if primary in held_out:
        raise OptimizationGateFailed(
            f"primary metric {primary!r} is also declared held_out; the campaign "
            f"would be optimizing against its own generalization check",
        )
    values: list[float] = []
    fit_statuses = _PRIMARY_FIT_STATUSES
    for o in outcomes:
        if o.status not in fit_statuses:
            values.append(float("nan"))
            continue
        resp = o.response or {}
        leaked = held_out & set(resp)
        if leaked:
            raise OptimizationGateFailed(
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
        if o.status != "complete":
            # An infeasible row is fitted only when it carries a usable number:
            # its primary is a bonus measurement, never a reason to abort. A
            # missing or non-numeric value leaves it excluded, as it always was.
            try:
                v = float(raw)
            except (TypeError, ValueError):
                v = float("nan")
            values.append(v if math.isfinite(v) else float("nan"))
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
    #
    # THIS NO LONGER ABORTS, and the reason is a measured failure rather than a
    # preference. The message this raise carried named the correct behaviour
    # itself — "refit on the completed subset and report the reduced
    # resolution" — and `_fit_and_recommend` IMPLEMENTS exactly that a thousand
    # lines below: it drops the NaN rows, refits on the kept subset, enforces a
    # floor, and records the exclusions in `fit_exclusions.json`. Two guards over
    # one condition, disagreeing, and the stricter one ran first — so the refit
    # was reachable only for `infeasible`/`rejected` rows and never for a row
    # that genuinely failed to measure.
    #
    # What that cost, once, on a real campaign: 3 rows of an 18-row screen failed
    # (two wall-clock timeouts, one adapter crash). The iteration aborted and
    # discarded the 15 VALID measurements. It then retried and aborted three more
    # times, so ~14 hours of measurement produced zero usable output, the epoch
    # never reached `confirm`, and `transitions.jsonl` stayed empty because the
    # transition write lives in the iteration closer past the fit. A design of 90
    # runs would be destroyed by one bad row.
    #
    # Degrading the CLAIM rather than the DATA is the spec's stance on partial
    # failure (spec §4 D2), so the exclusion is now reported, not fatal. The floor
    # and the artifact both live at the refit site, which is the only place that
    # knows the design and can tell whether what remains is still fittable — a
    # count of NaNs here cannot answer that question.
    unmeasured = [
        o.row_index for o, v in zip(outcomes, values)
        if v != v and o.status not in ("infeasible", "rejected")
    ]
    if unmeasured:
        logger.warning(
            "%d of %d runs produced no usable measurement (row_index %s). "
            "Fitting proceeds on the complete-row subset and the exclusions are "
            "recorded in fit_exclusions.json; the fit's resolution is reduced "
            "accordingly. Re-running the failed configurations would restore it. "
            "These rows are a MEASUREMENT failure a re-run can repair, which is "
            "why they degrade the claim rather than ending the epoch — unlike a "
            "complete row reporting a non-numeric objective, which is a semantic "
            "exception and is routed to the policy before reaching here.",
            len(unmeasured), len(values), unmeasured,
        )
    return values


#: Why a row carried NaN out of ``_fitting_responses``, keyed by
#: ``RunOutcome.status``. These mean DIFFERENT things scientifically and
#: ``fit_exclusions.json`` must not merge them:
#:
#:   * ``failed`` — the row produced no measurement (crash, timeout,
#:     manipulation predicate never engaged, adapter guard). REPAIRABLE by
#:     re-running the configuration, and the region it leaves empty is a hole
#:     in the design rather than a fact about the space.
#:   * ``infeasible`` — the row RAN and produced trustworthy numbers that
#:     violated a declared constraint. Real information about the design space
#:     (spec §6.4); re-running changes nothing, and the point is genuinely
#:     outside ``X_valid``.
#:   * ``rejected`` — the row ran but its numbers are untrustworthy (invariant
#:     violation, above the physical ceiling, failed integrity check). Neither
#:     a measurement nor information about the space.
#:   * ``no_metric`` — the row reached ``complete`` but the primary metric key
#:     was present-and-null. Kept distinct from ``failed`` because the target
#:     ran successfully and only the statistic is missing, which points at the
#:     instrumentation rather than at the run.
#:
#: The split is not bookkeeping: ``failed``/``no_metric`` are the only reasons
#: whose loss can BIAS a coefficient, because they remove an ADMISSIBLE region
#: from the fit. See ``orchestrator.optimize.exclusions`` on why counting an
#: ``infeasible`` row as bias would flag every constrained campaign ever run.
EXCLUSION_REASONS: dict[str, str] = {
    "failed": "failed_to_measure",
    "infeasible": "infeasible",
    "rejected": "rejected",
    "complete": "no_metric",
}


def _exclusion_reason(outcome) -> str:
    """The ``EXCLUSION_REASONS`` label for one excluded row."""
    return EXCLUSION_REASONS.get(
        getattr(outcome, "status", "") or "", "failed_to_measure",
    )


def _screen_block_rows(work_dir: Path, screen_iter: int | None,
                       n_expected: int, indices=None) -> list[dict]:
    """The screen block's ``runs.jsonl`` rows in DESIGN-ROW order.

    Sibling of ``_screen_responses``, which reads the same file for the same
    reason and with the same ordering hazard: rows land in ``runs.jsonl`` in
    EXECUTION order (the pre-registered randomized permutation), so reading the
    file front-to-back would misalign every row with its design point. Indexed
    by ``row_index`` for that reason.

    A missing row yields an empty dict rather than raising. The caller only
    needs its ``levels`` and ``status``, and a screen row that is absent
    altogether is already routed to ``nan_response`` by ``_screen_responses``'
    flag — so this reader's job is to describe what IS there, not to re-raise a
    condition another guard owns.
    """
    if screen_iter is None:
        return [{} for _ in range(n_expected)]
    by_index: dict[int, dict] = {}
    for row in artifacts.read_runs(Path(work_dir) / "runs" / f"iter-{screen_iter}"):
        idx = row.get("row_index")
        if isinstance(idx, int):
            by_index[idx] = row
    picks = list(indices) if indices is not None else list(range(n_expected))
    return [by_index.get(i) or {} for i in picks]


def _fit_row_levels(work_dir: Path, rows, outcomes, stage_name: str,
                    screen_iter: int | None, *, n_total: int,
                    n_fold: int, prefix_indices=None) -> list[dict]:
    """Levels for every POSITION in the fit's response vector ``ys``.

    Positions, not ``row_index``, because that is what ``ys`` and
    ``design.points`` are indexed by and what the exclusion analysis and the
    identifiability floor both consume. At every state except ``foldover`` the
    two coincide (``matrix.expand`` assigns ``row_index = enumerate(points)``),
    and at ``foldover`` they emphatically do not: ``ys`` is
    ``screen_ys + fold_ys``, so position 0 is the SCREEN block's row 0 and lives
    in a previous iteration's directory. Attributing the fold block's levels to
    the screen block's exclusions would analyse the wrong contingency table and
    could flag a factor whose rows all completed.
    """
    # POSITIONAL over `rows` (design order): `row_index` equals the position
    # at every stage except refine with a held-out validation block, where
    # the block-1 reuse centres sit after it (WP-B B1/B4).
    fold = [dict(r.levels) for r in rows][:n_fold]
    fold += [{}] * (n_fold - len(fold))
    if n_total == n_fold:
        return fold
    screen = _screen_block_rows(work_dir, screen_iter, n_total - n_fold,
                                indices=prefix_indices)
    return [dict(r.get("levels") or {}) for r in screen] + fold


def _fit_exclusion_reasons(outcomes, stage_name: str, dropped, *, n_total: int,
                           n_fold: int, work_dir: Path,
                           screen_iter: int | None,
                           prefix_indices=None) -> dict[int, str]:
    """``EXCLUSION_REASONS`` label per excluded POSITION in ``ys``.

    Same positional convention as ``_fit_row_levels``, and the same reason for
    it. The screen half's status comes from its ``runs.jsonl`` row rather than
    from a ``RunOutcome``, because the outcomes this iteration holds are the
    FOLD block's — pairing them with a screen position would report one row's
    failure mode against another row's index.
    """
    by_pos: dict[int, object] = {}
    offset = 0
    if n_total != n_fold:
        offset = n_total - n_fold
        for i, row in enumerate(_screen_block_rows(work_dir, screen_iter, offset,
                                                   indices=prefix_indices)):
            by_pos[i] = row
    for i, o in enumerate(outcomes[:n_fold]):
        by_pos[offset + i] = o

    out: dict[int, str] = {}
    for i in dropped:
        src = by_pos.get(i)
        status = (
            src.get("status") if isinstance(src, dict)
            else getattr(src, "status", None)
        )
        # An ABSENT source is not a status this module knows how to label. A
        # screen row that never reached runs.jsonl at all is the
        # `_screen_responses` NaN flag's business (it routes to nan_response);
        # here it is simply a row that produced no measurement.
        out[i] = EXCLUSION_REASONS.get(status or "", "failed_to_measure")
    return out


#: Whether the fitting stages model ``response.constraints`` metrics and use
#: those models to drop CONFIDENTLY infeasible candidates from the argmax and
#: ``top_candidates`` (see ``orchestrator.optimize.constraint_models``). Not a
#: campaign knob: the spec gives the author no reason to rank candidates the
#: campaign already knows to be inadmissible. It exists so the metamorphic
#: oracle tests can run the same campaign with and without the models.
_MODEL_CONSTRAINTS = True

#: Whether confirm reserves a seat for the best SUPPORTED-FEASIBLE candidate
#: (``constraint_models.supported_feasible``; recorded as
#: ``recommendation.json["supported_feasible_candidate"]``, INV-STAT16). Not a
#: campaign knob, for the same reason as ``_MODEL_CONSTRAINTS``: it exists so the
#: metamorphic oracle tests can run one campaign with and without the seat.
_SUPPORTED_FEASIBLE_SEAT = True

#: Whether a finalist measured INFEASIBLE is a certification CAVEAT rather than a
#: veto. Off (today's rule) means any infeasible finalist withholds
#: certification (``finalist_measured_infeasible``). On means it does not
#: withhold when at least two admissible finalists remain, the simultaneous
#: terminal bound over them is within epsilon, and the model was adequate; the
#: fact is then recorded in ``certification_caveats``. Not a campaign knob: the
#: oracle evaluation that decides it runs the same campaigns both ways.
_INFEASIBLE_FINALIST_CAVEAT = False

#: How deep into the constraint-filtered ranking the refill pool reaches.
_REFILL_POOL = 256

#: Row statuses whose PRIMARY metric enters the primary fit (INV-STAT15).
#:
#: ``infeasible`` IS FITTED. An infeasible row violated a declared
#: ``response.constraints`` threshold: the configuration ran, the instrument
#: worked, and the primary it reports is a valid measurement of that
#: configuration -- it is merely inadmissible to RETURN. Excluding it (the rule
#: before constraint models existed, spec 2026-08-13 "exclude from fitting")
#: truncates the design non-randomly exactly at the constraint boundary, where
#: constrained optima live, and routinely left too few rows to fit at all.
#: Measured on the oracle (16 seeds, a bowl whose optimum sits past a noisy
#: ``A + B <= 18`` constraint): excluding aborted 4/16 campaigns with a
#: rank-deficient refine and certified 0, fitting them aborted none and
#: certified 3, with worst-case regret 0.2 vs 2.7; identical on ``sla``,
#: ``infeasible_corner_interior`` and ``bowl``.
#:
#: Admissibility is enforced where a configuration can be RETURNED, not here:
#: ``_measured_infeasible`` removes every measured-infeasible configuration
#: from the candidate space, ``_best_observed`` reads ``complete`` rows only,
#: ``_finish_confirm`` strikes an infeasible finalist, and the constraint models
#: exclude confidently-infeasible candidates.
#:
#: ``rejected`` (design-space invariant, physical ceiling, integrity check) and
#: ``failed`` (incl. a ``self_check`` violation: the measurement itself is not
#: valid) stay OUT -- those rows are not trustworthy measurements.
_PRIMARY_FIT_STATUSES = frozenset({"complete", "infeasible"})


def _fit_row_records(work_dir: Path, outcomes, stage_name: str,
                     screen_iter: int | None, *, n_total: int,
                     n_fold: int, prefix_indices=None) -> list[tuple[str, dict]]:
    """``(status, response)`` for every POSITION in the fit's response vector.

    Same positional convention as ``_fit_row_levels``: at ``foldover`` the
    first ``n_total - n_fold`` positions are the SCREEN block's rows, read back
    from its own ``runs.jsonl``. The constraint models need the infeasible rows
    the primary fit drops, so they cannot reuse ``ys``.
    """
    fold = [(str(getattr(o, "status", "") or ""), dict(getattr(o, "response", {}) or {}))
            for o in list(outcomes)[:n_fold]]
    if n_total == n_fold:
        return fold
    screen = _screen_block_rows(work_dir, screen_iter, n_total - n_fold,
                                indices=prefix_indices)
    return [(str(r.get("status") or ""), dict(r.get("response") or {}))
            for r in screen] + fold


def _constraint_models_record(models, scored_all, rec, *, delta: float,
                              applied: bool | None = None,
                              evaluated: int | None = None) -> list[dict]:
    """What the constraint models did, per constraint, for ``recommendation.json``.

    ``scored_all`` is the candidate space BEFORE the model-based exclusion, so
    ``excluded_confidently_infeasible`` counts exactly the candidates each
    constraint removed (a candidate two constraints both exclude is counted
    under each). ``at_recommendation`` gives the argmax's own verdict, so a
    recommendation that is merely UNCERTAIN on a constraint says so.

    ``scored_all`` is the ranking's own ``Scored.unfiltered``: the same set the
    exclusion was applied to -- the whole space when enumerated, the SEARCH's
    evaluated set above the cap (``candidate_space`` says which). ``applied``,
    when given, is what the ranking actually did
    (``CandidateSpace.constraint_models_applied``); when ``None`` it is derived
    from ``scored_all``, which is the same thing for an enumerated space.
    ``evaluated`` is given exactly when the space was SEARCHED (the number of
    configurations the search scored); a dropped model's ``reason`` then says
    no admissible point was FOUND among them, never that EVERY candidate is
    infeasible -- only enumeration can say that.
    """
    d = cmodels.per_constraint_delta(models, delta)
    if applied is None:
        applied = any(
            not cmodels.confidently_infeasible(models, c.coded, delta=delta)
            for c in scored_all)
    out: list[dict] = []
    for m in models:
        entry = {
            "metric": m.metric, "op": m.op, "value": m.value,
            "modelled": m.modelled, "reason": m.reason, "n_rows": m.n_rows,
            "excluded_confidently_infeasible": 0, "delta": d,
            "applied": bool(m.modelled and applied),
            "at_recommendation": None,
        }
        if m.modelled:
            entry["excluded_confidently_infeasible"] = sum(
                1 for c in scored_all
                if cmodels.bound(m, c.coded, delta=d)["verdict"] == "infeasible"
            ) if applied else 0
            entry["at_recommendation"] = cmodels.bound(m, rec.coded, delta=d)
            if not applied and evaluated is None:
                entry["reason"] = (
                    "modelled, but NOT applied: the models predict every "
                    "candidate confidently infeasible, and an empty space can only "
                    "abort -- left to measurement instead"
                )
            elif not applied:
                entry["reason"] = (
                    f"modelled, but NOT applied: no point the models admit was "
                    f"FOUND among {int(evaluated)} evaluated configurations "
                    f"(searched, not enumerated), and an empty space can only "
                    f"abort -- left to measurement instead"
                )
        out.append(entry)
    return out


def _admissible_configurations(work_dir) -> list[dict]:
    """Every distinct configuration the campaign has measured ADMISSIBLE.

    A ``complete`` row whose configuration ``_config_admissible`` accepts (no
    ``infeasible`` / ``rejected`` row anywhere): the same per-configuration
    feasibility every other selector uses. Read across every iteration on disk,
    earlier epochs included -- a measurement of the same target does not stop
    being evidence because the declared ranges moved.
    """
    runs = Path(work_dir) / "runs" if work_dir is not None else None
    if runs is None or not runs.exists():
        return []
    invalid = _measured_infeasible(work_dir)
    barred = _barred_levels(work_dir)  # read ONCE for the loop (Q3)
    seen: dict[str, dict] = {}
    for d in sorted(runs.glob("iter-*")):
        for row in artifacts.read_runs(d):
            lv = row.get("levels")
            if row.get("status") != "complete" or not lv:
                continue
            key = json.dumps(lv, sort_keys=True, default=str)
            if key not in seen and _config_admissible(work_dir, lv, invalid=invalid, barred=barred):
                seen[key] = dict(lv)
    return list(seen.values())


def _supported_feasible_record(work_dir, factors, constraints, models, scored, *,
                               delta: float, pool_size: int) -> dict:
    """``recommendation.json["supported_feasible_candidate"]``.

    ``scored`` is the ranked valid space (best first, measured-infeasible and
    confidently-infeasible candidates already removed). ``models`` is
    ``fit_constraint_models``' output -- one per declared constraint -- or empty
    when the models are switched off, in which case every constraint is treated
    as unmodelled. ``levels`` is ``None`` and ``reason`` says why when nothing
    qualifies; confirm then keeps today's shortlist.
    """
    if not models:
        models = [
            cmodels.ConstraintModel(
                str(c.get("metric") or c.get("observable") or ""), c.get("op"),
                c.get("value"), None, "constraint models disabled")
            for c in constraints
        ]
    admissible = _admissible_configurations(work_dir)
    region = cmodels.admissible_region(admissible, factors)
    unmodelled = [m.metric for m in models if not m.modelled]
    hits = cmodels.supported_feasible(scored, models, delta=delta, region=region)
    rank = {id(c): i for i, c in enumerate(scored)}
    record = {
        "levels": None, "coded": None, "predicted": None, "rank": None,
        "constraint_verdicts": [],
        "admissible_region": region if unmodelled else None,
        "n_admissible_configurations": len(admissible),
        "pool": [{"levels": c.levels, "coded": c.coded, "predicted": c.predicted}
                 for c, _ in hits[:max(1, int(pool_size))]],
    }
    if hits:
        best, verdicts = hits[0]
        record.update(levels=best.levels, coded=best.coded, predicted=best.predicted,
                      rank=rank.get(id(best)), constraint_verdicts=verdicts)
        record["reason"] = (
            "best-predicted candidate with every modelled constraint confidently "
            "feasible" + (
                f" and inside the measured-admissible region for unmodelled "
                f"{unmodelled}" if unmodelled else ""))
    elif unmodelled and not admissible:
        record["reason"] = (
            f"no configuration has been measured admissible yet, so nothing "
            f"supports feasibility under unmodelled {unmodelled}")
    else:
        record["reason"] = (
            "no valid candidate is confidently feasible under every modelled "
            "constraint" + (
                f" and inside the measured-admissible region for unmodelled "
                f"{unmodelled}" if unmodelled else ""))
    return record


def _previous_finalist_levels(work_dir) -> list[dict]:
    """Levels of every finalist an earlier confirm round already measured."""
    runs = Path(work_dir) / "runs"
    out: list[dict] = []
    for p in sorted(runs.glob("iter-*/confirmation.json")) if runs.exists() else ():
        try:
            conf = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out.extend(dict(f.get("levels") or {}) for f in conf.get("finalists") or [])
    return [lv for lv in out if lv]


def _stationary_in_hull(fit, stationary: dict | None, direction: str) -> bool:
    """Is the fitted OPTIMUM inside the declared coded hull [-1, 1]?

    This is the observation the compiled policy's ``refine`` exception guard
    reads, so it has to mean "the declared ranges contain the optimum" and
    nothing weaker. Three cases, and the middle one is why this is not a
    one-line hull test:

      * ``stationary is None`` — no curvature terms, so the surface is a plane
        and has NO interior optimum. TRUE: the argmax is at a hull boundary,
        which is inside the hull. ``decide_after_refine`` already reads this case
        as "confirm at the best observed corner"; ending the epoch on it would
        end every campaign whose refine fit happened to come out linear.

      * out of hull, but the surface CURVES THE WRONG WAY along an offending
        axis — convex where the campaign maximizes, concave where it minimizes.
        TRUE. Such a point is a minimum (or a saddle) in that direction, so
        moving toward it makes the response WORSE and it is not an optimum
        outside the ranges; the optimum is at the hull boundary the argmax
        already picks. This is the case that makes the naive geometric test
        unusable: on a monotone surface the quadratic coefficients are noise and
        the solve inverts a near-singular Hessian, so the "stationary point"
        can land absurdly far out. MEASURED, and the campaign each number comes
        from is named because the same surface gives different figures under
        different response blocks:

          - ``SURFACES["additive"]`` seed 19, default campaign: coded
            ``A=-33.7, B=+57.8``, with ``A`` convex at ``+0.0036``.
          - ``SURFACES["sla"]`` seed 5, DEFAULT (unconstrained) campaign: coded
            ``A=+6575, B=+1212``, with ``B`` convex at ``+0.0046``.
          - ``SURFACES["sla"]`` seed 5, CONSTRAINED campaign — the one
            ``test_sla_surface_never_recommends_an_invalid_point`` runs, and the
            one whose regression motivated this function: coded
            ``A=-3.20, B=+7.33``, with ``A`` convex at ``+0.128``. Note the point
            is only just out of hull here, so the magnitude of the excursion is
            NOT what identifies the artefact — the curvature sign is.

        In every one of those the offending axis is CONVEX under a maximize
        objective. The genuine case (``SURFACES["bowl_out_of_hull"]``, whose true
        peak sits at A=30 against a declared [2, 16]) solves to coded ``A=+3.4``
        with ``A`` concave at ``-1.85``. So the sign test separates the real
        semantic exception from the numerical artefact on every surface in the
        oracle, and it does so without relying on how far out the point landed.

      * out of hull AND curving the right way — FALSE. A genuine optimum outside
        the declared ranges: a defect in the factor's DEFINITION that no
        measurement inside those ranges repairs, which is what makes it the
        paper's semantic exception rather than a branch.

    Only the PURE quadratic coefficients are consulted, not the full Hessian's
    eigenvalues. A rigorous "is this a maximum" test would need the eigenvalues
    of a k x k matrix, which means an eigensolver, which means numpy — banned in
    this subpackage. The diagonal test is the right conservative direction
    anyway: it declares the epoch-ending exception only when EVERY out-of-hull
    axis independently curves toward an optimum out there, so the failure mode is
    a missed exception (the campaign confirms and reports a boundary answer,
    which is what it did before this rule existed) rather than a false one (the
    epoch ends on a surface whose ranges were fine).
    """
    if stationary is None:
        return True
    outside = [fid for fid, v in stationary.items() if not -1.0 <= v <= 1.0]
    if not outside:
        return True
    # Negative curvature is what an interior MAXIMUM needs; positive is what an
    # interior MINIMUM needs. A missing quadratic term for an offending axis
    # means the fit estimated no curvature there at all, so that axis cannot
    # carry an optimum outside the hull either.
    want_negative = direction != "minimize"
    curvature = {
        e.terms[0]: e.estimate
        for e in (getattr(fit, "quadratic", None) or ())
        if len(e.terms) == 2 and e.terms[0] == e.terms[1]
    }
    for fid in outside:
        c = curvature.get(fid)
        if c is None or (c >= 0.0 if want_negative else c <= 0.0):
            logger.info(
                "refine: the solved stationary point is outside the declared "
                "hull on %s (coded %.4g) but the fit's curvature there is %s, "
                "which is the WRONG sign for an optimum under direction %r — so "
                "this is a stationary point without being an optimum (a "
                "near-singular solve on a surface with little real curvature), "
                "not a range that fails to contain the optimum. Treating the "
                "hull as containing the optimum: the argmax is at a boundary.",
                fid, stationary[fid],
                "absent" if c is None else f"{c:+.6g}", direction,
            )
            return True
    logger.warning(
        "refine: the fitted optimum lies OUTSIDE the declared hull on %s "
        "(coded %s) and the curvature there (%s) has the sign an optimum needs "
        "under direction %r. The declared ranges do not contain the optimum, and "
        "no measurement inside them will find it.",
        outside, {fid: round(stationary[fid], 4) for fid in outside},
        {fid: round(curvature[fid], 6) for fid in outside}, direction,
    )
    return False


def _primary_is_nan(outcome, primary: str) -> bool:
    """Is this outcome's primary metric a genuine float NaN?

    Narrow on purpose. Only a value that IS a float (or int) and is not equal to
    itself counts. A missing key, ``None``, a string, or a structure are all
    different facts with different handling in ``_fitting_responses`` — an absent
    metric is an unmeasured row, a string is an instrumentation mismatch — and
    collapsing any of them into "NaN" would route a repairable failure to a
    terminal state that ends the epoch.
    """
    raw = (getattr(outcome, "response", None) or {}).get(primary)
    return isinstance(raw, float) and raw != raw


def _nan_findings(stage_name: str, iteration: int, primary: str,
                  nan_rows: list[int], n_rows: int) -> dict:
    """A minimal findings.schema.json-conformant record of a NaN exception.

    Every iteration must leave a schema-valid ``findings.json`` behind, because
    ``finalize_iteration`` and ``append_ledger_row`` read it and the ledger is
    what makes the campaign's history reconstructible. One arm, ``REFUTED``,
    because the stage's premise — that every configuration in the design yields a
    measurable response — is exactly what the run refuted; and
    ``experiment_valid: false``, because no effect was estimated at all.

    The diagnostic note NAMES the offending rows. ``validate_evidence`` rejects
    aspirational prose, and "the run produced NaN" without a row index would be
    precisely that: the row indices are what let a reader open ``runs.jsonl`` and
    see the configuration that did it.
    """
    return {
        "iteration": iteration,
        "bundle_ref": f"runs/iter-{iteration}/design_matrix.json",
        "experiment_valid": False,
        "discrepancy_analysis": (
            f"{len(nan_rows)} of {n_rows} configuration(s) in the {stage_name} "
            f"design ran to completion but reported a non-numeric "
            f"{primary!r}, so no response model was fitted and no effect was "
            f"estimated. This is a semantic exception rather than a measurement "
            f"failure: the campaign's objective and the target's instrumentation "
            f"disagree about what is measurable at those configurations, and "
            f"re-running the same epoch would re-measure the same NaN. The epoch "
            f"ends; a revision of the metric's definition (or a declared "
            f"constraint excluding the region) plus a recompilation starts the "
            f"next one."
        ),
        "arms": [{
            "arm_type": "h-main",
            "predicted": (
                f"every configuration in the {stage_name} design yields a "
                f"measurable {primary!r} the stage can fit"
            ),
            "observed": (
                f"row_index {nan_rows} reported {primary!r} as NaN with "
                f"status 'complete'"
            ),
            "status": "REFUTED",
            # `None`, not "measurement": the schema's `error_type` enum names
            # ways a PREDICTION can be wrong (direction, magnitude, regime,
            # shape_mismatch), and none of them applies to a stage that never
            # estimated an effect to be wrong about.
            "error_type": None,
            "diagnostic_note": (
                f"see runs/iter-{iteration}/runs.jsonl row_index {nan_rows} for "
                f"the exact levels; epoch_end-*.json records the guard that "
                f"ended the epoch and what a new one would need"
            ),
            "metadata": {
                "stage": stage_name,
                "primary_metric": primary,
                "nan_row_indices": nan_rows,
                "rows_planned": n_rows,
            },
        }],
    }


def _read_mechanism_hash(work_dir: Path) -> str:
    p = Path(work_dir) / "mechanism.sha256"
    return p.read_text().strip() if p.exists() else ""


#: Fallback tolerance for baseline equivalence, as a percent of the pre-build
#: control mean, used when the campaign declares neither
#: ``build_checks.baseline_tolerance_pct`` nor
#: ``response.noise_estimate_pct``. 5% is deliberately loose: this oracle
#: exists to catch a mechanism that MOVED the control, not to police
#: run-to-run noise, and a tight default would abort honest campaigns on a
#: noisy target — which teaches authors to disable the check.
DEFAULT_BASELINE_TOLERANCE_PCT = 5.0

#: Replicates of the control measured before and after the build. Three is the
#: smallest count whose mean is not one outlier away from either verdict.
DEFAULT_BASELINE_REPLICATES = 3


def _build_checks(campaign: dict) -> dict:
    raw = (_opt_block(campaign) or {}).get("build_checks")
    return raw if isinstance(raw, dict) else {}


def _mechanism_paths(campaign: dict) -> list[str] | None:
    """The drift oracle's allowlist, or None for Task 12's whole-tree hash.

    SINGLE OWNER of the resolution, because ``snapshot_mechanism`` and
    ``current_mechanism_hash`` must be handed the identical list — a scope that
    differs between the two is a comparison between two different questions,
    and every epoch iteration would read as drift.

    Only the explicit ``optimization.build_checks.mechanism_paths`` is honoured.
    The plan floated deriving paths from the factors' ``manipulation`` /
    ``relations`` when they "name paths", but the schema does not carry file
    paths there: ``manipulation`` is a predicate over observables
    (``telemetry.*`` / ``applied.*``), and ``relations[].native_test`` is a test
    IDENTIFIER for the target's own runner (``tests/x.py::test_y``, a Go
    package, a JUnit class) — which resolves to a path only for some languages,
    and names the TEST rather than the mechanism even then. A derivation that
    guessed would produce a silently wrong allowlist, which is the one failure
    mode this oracle must not have: too narrow and drift goes unnoticed. So:
    declared, or whole-tree.
    """
    raw = _build_checks(campaign).get("mechanism_paths")
    if not isinstance(raw, list):
        return None
    paths = [str(p) for p in raw if str(p).strip()]
    return paths or None


def _baseline_replicates(campaign: dict) -> int:
    raw = _build_checks(campaign).get("baseline_replicates")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return DEFAULT_BASELINE_REPLICATES


def _baseline_tolerance_pct(campaign: dict) -> float:
    """Resolved percent tolerance for ``|post_mean - pre_mean| / |pre_mean|``.

    Precedence: the campaign's explicit ``build_checks.baseline_tolerance_pct``
    beats a value derived from ``response.noise_estimate_pct``, which beats the
    module default. The derived value is ``3 x`` the declared noise: a
    difference of means smaller than three noise widths is not evidence the
    control moved, and the author already told us how noisy the target is, so
    deriving beats making them state the same fact twice.
    """
    explicit = _build_checks(campaign).get("baseline_tolerance_pct")
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        val = float(explicit)
        if val > 0:
            return val
    # A multi-objective campaign may give a MAP (metric -> pct); the baseline
    # check compares the primary role's metric (the first objective), so that
    # entry is the noise it is judged against -- not the module default.
    from orchestrator.optimize.objectives import noise_pct_for

    _opt = _opt_block(campaign) or {}
    noise = noise_pct_for(_opt, _primary_of(_opt.get("response")).get("metric") or "")
    if isinstance(noise, (int, float)) and not isinstance(noise, bool):
        derived = 3.0 * float(noise)
        if derived > 0:
            return derived
    return DEFAULT_BASELINE_TOLERANCE_PCT


def _mean(values) -> float:
    vals = [float(v) for v in values]
    return sum(vals) / len(vals) if vals else float("nan")


def _baseline_equivalent(
    pre_mean: float, post_mean: float, tolerance_pct: float,
) -> bool:
    """True when the control did NOT move beyond ``tolerance_pct``.

    RELATIVE, not absolute: a 0.4 shift is nothing on a metric of 10,000 and
    everything on a metric of 1. A NaN on either side is NOT equivalence — a
    control that failed to measure is a control that was not shown to be inert,
    and treating an unmeasurable baseline as a pass would make the oracle
    strongest exactly where the apparatus is weakest.

    ``pre_mean == 0`` falls back to an absolute comparison against the
    tolerance fraction, because the relative form is undefined there and
    dividing anyway would either raise or declare every shift infinite.
    """
    import math as _math

    if _math.isnan(pre_mean) or _math.isnan(post_mean):
        return False
    frac = tolerance_pct / 100.0
    if pre_mean == 0.0:
        return abs(post_mean) <= frac
    return abs(post_mean - pre_mean) / abs(pre_mean) <= frac


def built_factor_ids(factors, ran: set) -> set[str]:
    """Factors the build is AUTHORING: some declared correctness test did not run.

    ``ran`` is the set of declared native tests that executed against the
    pre-build tree. The single owner of this rule, shared by verify's oracle
    2(b) and ``nous validate --smoke`` so the warning an author sees before
    launching is the verdict verify will reach.
    """
    return {
        f.id for f in factors
        if any(isinstance(r, dict) and r.get("kind") == "correctness"
               and r.get("native_test") and r["native_test"] not in ran
               for r in (f.relations or ()))
    }


def _check_tests_failed_before_build(
    campaign: dict, work_dir: Path, factors, test_results: dict | None,
    *, records: dict | None = None,
) -> None:
    """Oracle 2(b): a correctness test that already passed proves nothing.

    Spec §3.7 states the requirement as "have its declared tests FAIL before the
    build and pass after, or the test proves nothing". The failure condition is
    therefore a test that PASSED pre-build — the opposite direction from every
    other test check in this module, where passing is the good outcome. A test
    green against a tree where the mechanism did not exist is green for some
    other reason, and it will stay green if the build wires the mechanism to
    nothing at all. That is the single most expensive way for a campaign to be
    wrong, because every downstream number is real, reproducible, and about the
    wrong system.

    Scoped to ``correctness`` relations. A ``behavioral`` relation may
    legitimately hold before and after (a monotonicity that the mechanism only
    sharpens), and behavioral verdicts never gate this kind anyway.

    Silent no-op when ``pre_build_tests.json`` is absent: no build stage ran, so
    there is no before-state and nothing was claimed. Absence disables the
    check, exactly as it does for the drift oracle.
    """
    path = Path(work_dir) / "pre_build_tests.json"
    if records is None and not path.exists():
        return
    if _build_checks(campaign).get("allow_preexisting_tests"):
        logger.info(
            "verify: build_checks.allow_preexisting_tests is set — not checking "
            "whether declared correctness tests already passed before the build",
        )
        return
    try:
        # The sealed, in-memory copy read before any target code ran, when
        # verify has one (gate_records.load); the file otherwise.
        pre = (records["pre_build_tests.json"] if records is not None
               else json.loads(path.read_text()))
    except (OSError, ValueError) as exc:
        raise OptimizationGateFailed(
            f"pre_build_tests.json exists but could not be read ({exc}). It is "
            f"the record of which declared tests passed BEFORE the mechanism "
            f"existed, and that question is unanswerable now that it does — "
            f"delete the work_dir and re-run the build stage rather than "
            f"proceeding without the check.",
        ) from exc
    already = set(pre.get("passed") or ())
    if not already:
        return
    # WHICH factors the build is authoring. A factor whose declared correctness
    # tests did not all exist before the build (absent from `ran`) is one whose
    # mechanism the build writes, and a pre-existing test of it that already
    # passed proves nothing about that mechanism. A factor whose tests ALL ran
    # before the build is a knob the target already had -- its relation tests
    # passing pre-build is the expected state, not evidence of a vacuous test.
    # Without this split, every campaign that tunes existing knobs ALONGSIDE a
    # built mechanism aborted at verify (found authoring a real one). When NO
    # factor has an unwritten test, the build is changing existing behaviour and
    # the strict rule applies to every factor, as before.
    built = built_factor_ids(factors, set(pre.get("ran") or ()))
    bad = sorted({
        v.native_test for v in relations.reconcile(factors, test_results or {})
        if v.kind == "correctness" and v.native_test in already
        and (not built or v.factor_id in built)
    })
    if not bad:
        return
    raise OptimizationGateFailed(
        f"native test(s) {', '.join(bad)} passed before the mechanism existed "
        f"— a test that passes without the mechanism does not test it, so it "
        f"cannot certify the apparatus every later measurement rests on. Either "
        f"strengthen the test so it fails against the pre-build tree, or set "
        f"optimization.build_checks.allow_preexisting_tests: true if the test "
        f"genuinely covers pre-existing behaviour (a backward-compatibility "
        f"relation is the legitimate case).",
    )


def _check_authored_tests_discriminate(campaign: dict, work_dir: Path, factors,
                                       iteration: int, *, records: dict | None = None
                                       ) -> None:
    """Oracle 2(d) (``test_vacuity.py``): every declared correctness test of a
    built factor must be shown to observe the mechanism, not merely the
    existence of a name. No-op when no build ran."""
    from orchestrator.optimize import test_vacuity

    pre_path = Path(work_dir) / "pre_build_tests.json"
    if records is None and not pre_path.exists():
        return
    try:
        pre = (records["pre_build_tests.json"] if records is not None
               else json.loads(pre_path.read_text()))
    except (OSError, ValueError) as exc:
        # Not "2(b) already failed": with allow_preexisting_tests 2(b) never
        # reads the file, so this is the oracle that must fail closed.
        raise OptimizationGateFailed(
            f"pre_build_tests.json is unreadable ({exc}); oracle 2(d) cannot "
            f"run. Re-run the build stage in a fresh work_dir.") from exc
    opt = _opt_block(campaign) or {}
    repo = (campaign.get("target_system") or {}).get("repo_path")
    run_tests = None
    if opt.get("test_command") and repo:
        log = Path(work_dir) / "runs" / f"iter-{iteration}" / "mutant_test_output.log"

        def run_tests(cwd: Path):
            raw = runner.run_test_command(opt["test_command"], cwd=Path(cwd),
                                          timeout=resolve_test_timeout(opt), log_path=log)
            _check_survivors(work_dir, iteration, "2(d) mutant test command")
            return runner.match_declared_tests(factors, raw), test_vacuity.read_log(raw)
    try:
        test_vacuity.check(
            campaign, work_dir, factors, repo=Path(repo) if repo else None,
            run_tests=run_tests,
            built_ids=built_factor_ids(factors, set(pre.get("ran") or ())),
            records=records)
    except ValueError as exc:
        raise OptimizationGateFailed(str(exc)) from exc


def _check_baseline_equivalence(
    campaign: dict, work_dir: Path, factors, config_runner: Callable | None,
    *, records: dict | None = None,
) -> None:
    """Oracle 2(c): ``control == known_valid_baseline`` after the build.

    The build authored a mechanism. At the mechanism's control level the target
    must behave exactly as it did before — that is what makes the control a
    control. A mechanism that moves the metric at its OFF setting has changed
    something outside its own scope (a shared code path, a default, an
    allocation), and every treatment effect the epoch then measures is
    confounded with that change while looking perfectly clean.

    Measured, not argued: the pre-build replicate values were recorded in the
    build iteration; this re-measures the SAME configuration with the SAME
    runner and compares means relatively. A hard abort, not a warning — the
    whole epoch's numbers are downstream of it, and a warning arrives after the
    runs are spent.

    When the campaign declares ``optimization.workload.seed_env``, the pre/post
    pair also shares WORKLOAD COMMON RANDOM NUMBERS (spec §3.8): post replicate
    *i* re-runs the draw pre replicate *i* used, so the tolerance is spent on
    the mechanism rather than on the workload's entropy. The artifact records
    ``paired`` either way — a reader must be able to tell which comparison
    produced the verdict.

    NOT ARMED is a distinct outcome from PASSED, and this function keeps them
    distinguishable. No file at all means the oracle was never attempted (no
    build stage, no declared baseline, no runner); ``pre_unavailable`` means it
    was attempted and the pre-build measurement could not be taken, which is a
    normal pre-build state (see the build branch) but must not read as a pass.
    Every not-armed path after a build is a HARD FAIL (``_baseline_unarmed``)
    unless ``build_checks.allow_unarmed_baseline`` waives it with a reason,
    which is recorded; the alternative is a campaign author assuming a check
    ran when nothing did.
    """
    path = Path(work_dir) / "baseline_equivalence.json"
    sealed = records.get("baseline_equivalence.json") if records is not None else None
    if (records is not None and sealed is None) or (records is None and not path.exists()):
        # A build ran but no control was even attempted: unarmed, and a gate
        # like every other unarmed path.
        if records is not None or (Path(work_dir) / "pre_build_tests.json").exists():
            _baseline_unarmed(campaign, path, {},
                              "no pre-build control measurement was attempted "
                              "(no known_valid_baseline, or no runner at build)")
        return
    try:
        rec = dict(sealed) if sealed is not None else json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OptimizationGateFailed(
            f"baseline_equivalence.json exists but could not be read ({exc}). It "
            f"holds the pre-build control measurement, which cannot be retaken "
            f"now that the mechanism is in the tree — re-run the build stage "
            f"rather than proceeding without the check.",
        ) from exc
    pre = list(rec.get("pre") or ())
    levels = dict(rec.get("levels") or {})
    unavailable = rec.get("pre_unavailable")
    if unavailable and not pre:
        # The build stage tried and could not. The pre-build measurement is gone
        # for good (the mechanism is in the tree now), so nothing can verify the
        # mechanism is inert at its control level: a GATE, not a warning (audit
        # Q8.1), unless the author waived it with a recorded reason.
        _baseline_unarmed(campaign, path, rec,
                          f"the control {levels or '<unrecorded>'} could not be "
                          f"measured before the build ({unavailable})")
        return
    if not pre or not levels:
        return
    if config_runner is None:
        _baseline_unarmed(campaign, path, rec,
                          "a pre-build control measurement exists but no "
                          "config_runner is available to re-measure it")
        return

    from orchestrator.optimize import build as build_mod

    metric = (
        _primary_of((_opt_block(campaign) or {}).get("response"))
        .get("metric") or ""
    )
    tol = float(rec.get("tolerance_pct") or _baseline_tolerance_pct(campaign))
    # WORKLOAD COMMON RANDOM NUMBERS across the build stage (spec §3.8). The
    # pre-build replicates were measured with the draws `baseline_seeds` derives
    # from the replicate index alone, so re-measuring with the same block hands
    # post replicate `i` the same draw as pre replicate `i`. That pairing is
    # what makes the tolerance a statement about the MECHANISM: `post_mean -
    # pre_mean` is then the mean of paired differences, and the workload's own
    # entropy cancels out of it instead of being charged to the build. Without
    # it, a target whose workload variance dominates its configuration effect —
    # a queue, a cache, an autoscaler, i.e. every target this kind exists for —
    # can blow a 5% hard-abort gate on noise alone, and the campaign blames the
    # mechanism for a difference the workload produced.
    #
    # The seeds are re-derived rather than read back from `rec` so a stale or
    # hand-edited artifact cannot silently steer the post measurement; the
    # recorded vector below is then a claim the derivation can be checked
    # against.
    _wl = (_opt_block(campaign) or {}).get("workload")
    seeds = build_mod.baseline_seeds(_wl, len(pre))
    # A pre-build measurement taken before this campaign declared `workload`
    # (or by an older Nous) recorded no seeds, so pairing cannot be claimed for
    # it however the campaign reads today. Degrade to the unpaired reading and
    # say so, rather than labelling a comparison that never shared a draw.
    recorded_pre = rec.get("workload_seeds")
    paired = seeds is not None and list(recorded_pre or ()) == list(seeds)
    if seeds is not None and not paired:
        logger.warning(
            "verify: the campaign declares optimization.workload.seed_env but "
            "the pre-build control measurement recorded no matching workload "
            "seeds (%r), so oracle 2(c) is an UNPAIRED comparison — the "
            "workload's own variance does not cancel out of the pre/post "
            "difference and the tolerance has to absorb it. Recorded as "
            "paired: false in baseline_equivalence.json.",
            recorded_pre,
        )
    post = build_mod.baseline_runs(
        config_runner, factors, levels, n=len(pre), metric=metric,
        workload=_wl if paired else None,
    )
    pre_mean, post_mean = _mean(pre), _mean(post)
    ok = _baseline_equivalent(pre_mean, post_mean, tol)
    record = {
        "levels": levels, "pre": pre, "post": post,
        "pre_mean": pre_mean, "post_mean": post_mean,
        "tolerance_pct": tol, "ok": ok, "paired": paired,
    }
    if paired:
        record["workload_seeds"] = seeds
        record["workload_seed_env"] = (_wl or {}).get("seed_env")
    _write_json(path, record)
    if ok:
        logger.info(
            "verify: baseline equivalence holds — control %s measured %.6g "
            "before the build and %.6g after (tolerance %.3g%%, %s)",
            levels, pre_mean, post_mean, tol,
            "paired on workload common random numbers" if paired
            else "unpaired",
        )
        return
    raise OptimizationGateFailed(
        f"build changed the baseline: control configuration {levels} moved from "
        f"{pre_mean:.6g} to {post_mean:.6g} on {metric or '<unset metric>'} "
        f"(> {tol:.3g}% tolerance, {len(pre)} replicate(s) each side, "
        f"{'paired on workload common random numbers' if paired else 'unpaired'})"
        f" — the mechanism is not inert at its control level, so every effect "
        f"this epoch would measure is confounded with whatever else the build "
        f"changed. Make the control path byte-identical to the pre-build "
        f"behaviour, or if the shift is real measurement noise on this target, "
        f"declare it: optimization.response.noise_estimate_pct (the tolerance "
        f"is 3x it) or optimization.build_checks.baseline_tolerance_pct"
        + ("" if paired else
           ", or declare optimization.workload.seed_env so the pre/post "
           "comparison shares workload draws and the workload's own variance "
           "cancels out of it")
        + ". See baseline_equivalence.json for both replicate vectors.",
    )


def _baseline_unarmed(campaign: dict, path: Path, rec: dict, why: str) -> None:
    """Oracle 2(c) could not run. Hard-fail, unless the campaign waives it with
    ``optimization.build_checks.allow_unarmed_baseline: "<reason>"``; a waiver
    is recorded in ``baseline_equivalence.json`` and in report.json's
    ``provenance.waivers``, so an unarmed oracle never reads as a passed one."""
    reason = _build_checks(campaign).get("allow_unarmed_baseline")
    if isinstance(reason, str) and reason.strip():
        logger.warning(
            "verify: ORACLE 2(c) IS NOT ARMED (%s). Waived by "
            "build_checks.allow_unarmed_baseline: %r -- nothing verifies that "
            "the mechanism is inert at its control level, and report.json says so.",
            why, reason.strip(),
        )
        _write_json(path, {**rec, "armed": False, "unarmed_because": why,
                           "waived": reason.strip()})
        return
    raise OptimizationGateFailed(
        f"oracle 2(c) is NOT ARMED: {why}. Nothing would verify that the built "
        f"mechanism is inert at its control level, and a mechanism that moves "
        f"the metric at its OFF setting confounds every effect the epoch "
        f"measures. Make the run_command able to execute the "
        f"known_valid_baseline BEFORE the build runs and start a fresh "
        f"campaign, or, if that is impossible for this target, waive the "
        f"oracle in writing: optimization.build_checks.allow_unarmed_baseline: "
        f"\"<why>\" (recorded in report.json).",
    )


def _review_build(gate, work_dir: Path, *, built: bool | None = None) -> None:
    """THE HUMAN GATE FOR A BUILT MECHANISM (audit Q10).

    After a build, and after every automatic build oracle passed, but BEFORE the
    policy is compiled and any benchmark budget is spent, a human is shown the
    authored diff and the oracle records and asked to approve. This is the
    HUMAN_DESIGN_GATE the phase machine names for this kind. Under
    ``--auto-approve`` (this kind's default) the gate answers itself; the record
    says so (``build_review.json`` ``auto: true``) and report.json lists it under
    ``provenance.waivers``, so an unreviewed mechanism never reads as reviewed.
    A reject or abort ends the campaign. Not consulted when no build ran.
    """
    wd = Path(work_dir)
    if built is False or (built is None and not (wd / "pre_build_tests.json").exists()):
        return
    files = [str(wd / n) for n in ("mechanism.patch", "build_scope.json",
                                   "authored_tests.json", "baseline_equivalence.json",
                                   "pre_build_tests.json")
             if (wd / n).exists()]
    decision, reason = gate.prompt(
        "The build authored the mechanism and its tests, and every automatic "
        "oracle passed. Approve it before the epoch spends benchmark runs?",
        artifact_path=str(wd / "mechanism.patch") if (wd / "mechanism.patch").exists() else None,
        files=files,
    )
    # A gate that cannot say whether a human answered is treated as automatic:
    # the record must not claim a review that may not have happened.
    auto = bool(getattr(gate, "is_automatic", True))
    _write_json(wd / "build_review.json", {
        "decision": decision, "reason": reason, "auto": auto, "files": files})
    if decision != "approve":
        raise OptimizationGateFailed(
            f"the built mechanism was not approved at the build review gate "
            f"({decision}{': ' + reason if reason else ''}); no policy was "
            f"compiled and no benchmark run was spent. See build_review.json.",
        )


def _reuse_enabled(opt: dict) -> bool:
    """Whether row reuse is on for this campaign. On by default.

    Opt-OUT rather than opt-in, deliberately: re-measuring rows that were
    already validly measured under the same pre-registration is never MORE
    correct, only slower, and the guards in ``resume`` refuse reuse in every
    case where it would not be sound. An author who wants the old behaviour
    (e.g. to reproduce a historical run byte-for-byte) sets
    ``optimization.reuse_measured_rows: false``.
    """
    val = opt.get("reuse_measured_rows")
    return True if val is None else bool(val)


def _enter_phase_pending(engine, work_dir: Path) -> bool:
    """True when this iteration has NOT yet passed its DESIGN phase.

    Reuse must be planned before the matrix is registered, because the carried
    -forward draws are part of the pre-registration. A resumed iteration whose
    ``design_matrix.json`` already exists is past that point: its rows are
    already registered, its own ``runs.jsonl`` already holds whatever it
    measured, and re-planning reuse would try to re-append rows that are on
    disk — which ``check_fidelity`` correctly reports as a duplicate row_index.
    """
    from orchestrator.iteration import _PHASE_INDEX
    try:
        return _PHASE_INDEX[engine.phase] <= _PHASE_INDEX["DESIGN"]
    except (KeyError, AttributeError):  # pragma: no cover - defensive
        return False


def _prior_attempt_matrix(work_dir: Path, iteration: int,
                          stage_name: str) -> dict | None:
    """The most recent EARLIER iteration's design matrix for the same stage.

    "Same stage" is checked through the matrix's own ``kind``/shape rather than
    a recorded stage name, because ``design_matrix.json`` carries no stage
    field. ``resume.carry_forward_payload`` then does the real structural
    comparison and returns ``None`` for anything that is not the same
    registration, so this only has to find a plausible candidate.
    """
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return None
    best: tuple[int, dict] | None = None
    for d in runs.glob("iter-*"):
        try:
            n = int(d.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        if n >= int(iteration):
            continue
        mpath = d / "design_matrix.json"
        if not mpath.exists():
            continue
        try:
            doc = json.loads(mpath.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if best is None or n > best[0]:
            best = (n, doc)
    return best[1] if best else None


def _rows_from_payload(rows, payload: dict):
    """``rows`` re-rendered with the payload's ``apply`` (i.e. its seeds).

    ``ConfigRow`` is frozen, so this replaces rather than mutates. Only
    ``apply`` is taken from the payload: levels/role/replicate were already
    verified identical by ``carry_forward_payload``, so taking those too would
    be a no-op that merely widened what this function could get wrong.
    """
    import dataclasses

    by_index = {}
    for row in payload.get("rows") or ():
        idx = row.get("row_index")
        if isinstance(idx, int):
            by_index[idx] = row.get("apply") or {}
    out = []
    for r in rows:
        applied = by_index.get(r.row_index)
        out.append(r if applied is None else dataclasses.replace(r, apply=dict(applied)))
    return out


def _epoch_index(work_dir: Path) -> int:
    return 1 + len(list(Path(work_dir).glob("epoch_end*.json")))


def _compile_and_write_policy(campaign: dict, work_dir: Path) -> dict:
    """Compile, structurally check, and persist the epoch's policy."""
    pol = policy_mod.compile_policy(
        campaign, mechanism_patch_hash=_read_mechanism_hash(work_dir),
        epoch=_epoch_index(work_dir),
        run_order_salt=_run_order_salt(campaign, work_dir, _epoch_index(work_dir)),
    )
    errs = policy_mod.check_policy(pol)
    if errs:
        raise OptimizationGateFailed(
            "compiled policy is structurally invalid:\n  " + "\n  ".join(errs),
        )
    try:
        policy_mod.write_policy(work_dir, pol)
    except ValueError as exc:
        # `check_policy` covers the closed observation/operator vocabulary and
        # reachability; `write_policy`'s schema check covers the shape
        # constraints neither `check_policy` nor `compile_policy` enforces
        # (`policy_version` pinned to 1, the `epsilon` `abs`/`pct` `oneOf`, the
        # delta bounds). Both are pre-registration failures of the same class,
        # so both abort the campaign the same way.
        raise OptimizationGateFailed(str(exc)) from exc
    # The exact campaign THIS epoch pre-registered, beside the policy compiled
    # from it. `campaign.yaml` is written once, at first setup, so after an
    # author revises levels and resumes into epoch 2 it describes epoch 1 -- and
    # anything decoding epoch 2's coded results against it (report.md's "what
    # to do next") would use the wrong ranges. Also a provenance record: diff
    # two epochs' files to see what the author changed between them.
    try:
        _epoch_campaign = (Path(work_dir) / f"campaign.epoch-{pol['epoch']}.yaml")
        _epoch_campaign.write_text(
            yaml.safe_dump(campaign, default_flow_style=False, sort_keys=False))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("could not record the epoch's campaign: %s", exc)
    if not _REANALYSIS.get():
        # Anchor the registration OUTSIDE the work_dir before any benchmark
        # run (#321; orchestrator/optimize/anchor.py, which states what this
        # does and does not protect against).
        from orchestrator.optimize import anchor as _anchor

        _anchor.anchor_at_compile(work_dir)
    return pol


def _run_order_salt(campaign: dict, work_dir: Path, epoch: int) -> str | None:
    """The epoch's run-order salt (#321 run-order concealment), or None.

    Recorded in ``run_order.epoch-<e>.json`` the first time the epoch compiles
    and READ BACK on every later compile of the same epoch (a resume, or
    ``nous reanalyze``'s scratch dir, which carries the file), so the policy
    hash is reproducible from the record. ``optimization.policy.run_order_salt``
    pins it (to reproduce an earlier campaign's orders);
    ``optimization.policy.run_order_concealment: false`` opts out (derivation
    1, the iteration index, recorded by the policy's absent ``run_order``
    block). Under reanalysis an
    epoch with no recorded salt was compiled before concealment existed, and
    gets None: the old derivation (the iteration index).
    """
    import secrets

    p = Path(work_dir) / f"run_order.epoch-{int(epoch)}.json"
    if p.exists():
        try:
            return str(json.loads(p.read_text())["salt"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise OptimizationGateFailed(
                f"{p.name} exists but does not record a salt ({exc}); the "
                f"epoch's run orders cannot be reproduced from it") from exc
    if _REANALYSIS.get():
        return None
    _pcfg = (_opt_block(campaign) or {}).get("policy") or {}
    if _pcfg.get("run_order_concealment") is False:
        # Declared opt-out: derivation 1, the iteration index. The declaration
        # is in the campaign, so campaign_hash in the policy covers it.
        return None
    declared = _pcfg.get("run_order_salt")
    salt = str(declared) if declared else secrets.token_hex(16)
    _write_json(p, {"epoch": int(epoch), "salt": salt,
                    "derivation": policy_mod.RUN_ORDER_DERIVATION,
                    "source": "declared" if declared else "random"})
    return salt


def _load_or_compile_policy(campaign: dict, work_dir: Path) -> dict:
    """The epoch's policy, compiled lazily if verify has not written one.

    A real campaign always compiles at ``verify``; the lazy branch exists so a
    unit test that jumps straight to ``stage="screen"`` still has a policy to
    interpret. Once a policy IS on disk, its recorded hash is checked: a
    pre-registered policy that changed inside an epoch is not a
    pre-registration, so an edit hard-fails rather than being interpreted.

    A NEWER EPOCH RECOMPILES. ``epoch_end-<e>.json`` on disk is the record that
    epoch ``e`` ended on a semantic exception, so ``_epoch_index`` has already
    moved on while ``policy.json`` still describes ``e``. That is exactly the
    paper's one way back: "an agent may then revise the mechanism or interface,
    and a new compilation starts a new epoch" — the revision happens out of
    band (a human or an agent widens a range, fixes the metric, redefines a
    factor), and the NEXT ``nous resume <campaign.yaml>`` is what has to notice. Notice it
    here, where the campaign dict and the work_dir are both in hand, and
    recompile from the revised campaign rather than interpreting the stale
    policy.

    This is not an escape from the hash check above: the check refuses a policy
    edited INSIDE an epoch, and recompiling ACROSS an epoch boundary is the
    opposite operation — a new pre-registration, freshly hashed, whose
    ``epoch`` says which execution it registers. Both artifacts are overwritten
    together (``write_policy`` writes ``policy.json`` and ``policy.sha256``), so
    the pair never disagrees. The previous epoch's own registration survives in
    ``transitions.jsonl``, whose rows carry the ``policy_hash`` they ran under —
    so "which policy scheduled this design?" stays answerable for every epoch,
    not only the current one.
    """
    pol = policy_mod.read_policy(work_dir)
    if pol is not None and int(pol.get("epoch", 1)) < _epoch_index(work_dir):
        logger.info(
            "epoch %d ended on a semantic exception (%d epoch_end record(s) on "
            "disk); recompiling the experimental policy to start epoch %d from "
            "%r. Any revision to the campaign's factors, ranges, or objective "
            "made since the exception is picked up here — that is what makes a "
            "new epoch a fresh pre-registration rather than a resumed one.",
            int(pol.get("epoch", 1)), _epoch_index(work_dir) - 1,
            _epoch_index(work_dir), pol.get("initial"),
        )
        return _compile_and_write_policy(campaign, work_dir)
    if pol is None:
        return _compile_and_write_policy(campaign, work_dir)
    # FAILS CLOSED ON A MISSING SIDECAR, and that is the whole point of this
    # block. The guard used to read `if recorded.exists() and <mismatch>`, so
    # DELETING `policy.sha256` made the condition False and SKIPPED the check
    # rather than failing it — and nothing regenerates the sidecar, because
    # `_compile_and_write_policy` only runs when `pol is None`. Verified end to
    # end: with the sidecar removed and `screen`'s default transition rewritten
    # from `confirm` to `report`, the epoch ran to completion, skipped terminal
    # discrimination entirely, wrote no `confirmation.json`, emitted
    # `report.json` with `basis: model`, and recorded the TAMPERED hash in
    # `transitions.jsonl` as though it were the registration.
    #
    # A pre-registration whose verification can be disabled by removing a file is
    # not a pre-registration; it is a file that says one existed. The absent
    # sidecar and the mismatched one are the SAME failure — this epoch's policy
    # cannot be shown to be the one it registered — so they abort with one
    # message that distinguishes the cause without softening either.
    #
    # There is no legitimate path here without a sidecar: `write_policy` writes
    # `policy.json` and `policy.sha256` together, and a fresh epoch takes the
    # `pol is None` / recompile branches above. So reaching this line with the
    # file missing means it was removed after compilation.
    recorded = Path(work_dir) / "policy.sha256"
    if not recorded.exists():
        raise OptimizationGateFailed(
            f"policy.json exists but its hash sidecar {recorded.name} does not. "
            f"`write_policy` writes the pair together, so the sidecar was removed "
            f"after compilation, and without it this epoch's policy cannot be "
            f"shown to be the one that was pre-registered — every branch it takes "
            f"is unverifiable. This is the same failure as a hash mismatch and is "
            f"refused for the same reason. Restore {recorded.name} from the "
            f"epoch's records, or end this epoch and start a new one so the "
            f"revised campaign gets a fresh, freshly-hashed pre-registration.",
        )
    if recorded.read_text().strip() != policy_mod.policy_hash(pol):
        raise OptimizationGateFailed(
            "policy.json was edited after compilation (hash mismatch with "
            "policy.sha256); a pre-registered policy cannot change inside an "
            "epoch",
        )
    # Two records of ONE commitment must agree. `mechanism.sha256` is what the
    # drift oracle compares the tree against; `compiled_from
    # .mechanism_patch_hash` is what the policy says it was compiled for. Only
    # the second is covered by the policy hash above, so re-stamping the sidecar
    # alone leaves both files individually well-formed and the pair
    # meaningless — the drift check would then certify the tree against a hash
    # this policy never registered, and the epoch's numbers would be filed
    # under a pre-registration that does not describe them. Distinct from tree
    # drift, and named as such, because the fixes differ: recompile (a new
    # epoch) versus restore the tree.
    sidecar = _read_mechanism_hash(work_dir)
    registered = str((pol.get("compiled_from") or {}).get("mechanism_patch_hash") or "")
    if sidecar and registered and sidecar != registered:
        raise OptimizationGateFailed(
            f"the policy's registered hash and the sidecar hash disagree: "
            f"policy.json was compiled for mechanism_patch_hash "
            f"{registered[:12]} but mechanism.sha256 now records "
            f"{sidecar[:12]}. This is NOT tree drift — the tree may match the "
            f"sidecar perfectly — it means the mechanism was re-snapshotted "
            f"without recompiling, so the pre-registration and the drift "
            f"oracle no longer describe the same system. A revised mechanism "
            f"is a new experiment: start a new epoch (or a fresh campaign) so "
            f"the policy is compiled against the mechanism it will measure.",
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


def _stage_reused(row: dict) -> bool:
    """A row refine FILLED from a measured screen row (WP-B B4): a copy, not
    a measurement. The one test every counter of measurements uses, so the
    screen's measurement is counted once (budget, measured means, front)."""
    return bool((row.get("reused_from") or {}).get("stage"))


def _budget_remaining(pol: dict, work_dir: Path) -> int:
    """Benchmark runs still affordable — a RUN COUNT, not a round count.

    ``10 ** 9`` means "no declared cap", which must read as unbounded: a
    campaign that never declared ``design.max_runs`` must not be routed to
    ``report`` for having exhausted a budget it does not have.
    """
    cap = (pol.get("budget") or {}).get("max_runs")
    if not cap:
        return 10 ** 9
    # A row refine filled from a measured SCREEN row (WP-B B4,
    # `reused_from.stage`) cost nothing: the screen's row is already counted.
    spent = sum(
        sum(1 for r in artifacts.read_runs(d) if not _stage_reused(r))
        for d in (Path(work_dir) / "runs").glob("iter-*")
    )
    return int(cap) - spent


def _assign_workload_seeds(rows, payload, pol, *, iteration: int, confirm: bool):
    """Give every measurement row a recorded workload seed. Spec §3.7(3), §3.8.

    Returns ``(rows, payload)`` — NEW objects both, never mutated in place: the
    caller still holds the originals and ``payload`` was already built by
    ``matrix.matrix_payload`` / ``_confirm_rows``.

    A no-op unless the campaign declares ``optimization.workload.seed_env``.
    That default is deliberate: exporting a variable a target does not read is
    harmless, but recording ``paired: True`` (below) about a comparison whose
    finalists never shared a workload draw makes the artifact claim a method
    (``bonferroni_one_sided_t_paired``) whose premise did not hold. The bound
    itself stays VALID — it is computed from the observed differences, so an
    absent cancellation just never shrinks the spread — but it is typically LESS
    efficient than the unpaired form (fewer degrees of freedom for a common term
    that was not common), and its recorded provenance is wrong. Opt-in keeps the
    label honest.

    TWO KEYING RULES, and the difference between them is the whole point.

    * At the SPENDING stages (screen / foldover / refine) the seed varies per
      ROW. Those stages fit a surface over distinct configurations, so one seed
      shared across the block would confound the entire fit with a single
      workload draw — every coefficient would carry that draw's idiosyncrasy and
      nothing in the design could separate the two.

    * At ``confirm`` the seed varies per REPLICATE, so replicate *i* of EVERY
      finalist runs the same seed. That is common random numbers: the finalists
      are compared on the same workload draws, the draw's contribution cancels
      out of the finalist-to-finalist difference, and
      ``certificate.terminal_regret_bound`` switches from Welch-combining two
      independent variances to a t on the paired differences. On a target whose
      workload variance dominates its configuration effect — a queue, a cache,
      an autoscaler, i.e. every target this kind exists for — that is the
      difference between certifying inside the run budget and not; the spec puts
      it at roughly an order of magnitude in runs.

      The pairing is POSITIONAL downstream: ``_finish_confirm`` appends each
      finalist's measurements in row order and ``terminal_regret_bound`` zips
      them, so position *i* must be replicate *i* for every finalist. It is,
      because ``_confirm_rows`` emits one complete replicate block at a time
      (the run-order shuffle is INSIDE a block) and ``run_stage`` restores
      design order before ``_finish_confirm`` reads anything positionally.

    The base for a derived seed is the ITERATION at confirm rather than the
    run-order seed, so a second confirm round measures fresh draws instead of
    re-measuring round 1's — the round exists because round 1 did not
    discriminate, and repeating its exact workload could not fix that.

    ``workload.seeds``, when declared, is taken modulo the index and used
    verbatim: a campaign that pins its seeds is reproducing a specific set of
    draws and must not have them hashed into something else.
    """
    import dataclasses

    wl = (pol or {}).get("workload") or {}
    env_name = wl.get("seed_env")
    if not env_name:
        return rows, payload
    seeds = wl.get("seeds") or None

    def _seed(i: int, base: int) -> int:
        if seeds:
            return int(seeds[i % len(seeds)])
        # 7919 is prime and much larger than any plausible row/replicate count,
        # so consecutive bases cannot collide into overlapping seed runs the way
        # a small multiplier would (base*2+i aliases base+1 at i=2).
        return (base * 7919 + i) % (2 ** 31)

    base = (policy_mod.run_order_seed(pol, iteration) if confirm
            else int(payload.get("run_order_seed", iteration)))
    out, rec = [], {}
    for r in rows:
        i = r.replicate if confirm else r.row_index
        sd = _seed(int(i or 0), base)
        env = {**((r.apply or {}).get("env") or {}), env_name: sd}
        out.append(dataclasses.replace(r, apply={**(r.apply or {}), "env": env}))
        rec[str(r.row_index)] = sd

    # The payload's rows and the ConfigRow list are separate structures built
    # from the same design, so a divergence here means the caller assembled them
    # from different row sets — and a pre-registration recording seeds the runs
    # did not carry is worse than no seeds at all. Say so rather than KeyError.
    payload_indices = {row.get("row_index") for row in payload.get("rows", [])}
    if payload_indices != {r.row_index for r in rows}:
        raise OptimizationGateFailed(
            f"workload seeding: design_matrix payload rows "
            f"{sorted(i for i in payload_indices if i is not None)} do not match "
            f"the rows about to execute {sorted(r.row_index for r in rows)}, so "
            f"the recorded seeds could not describe the runs. This is an "
            f"internal inconsistency in the stage's row assembly, not a campaign "
            f"authoring error.",
        )
    payload = dict(payload)
    payload["workload_seeds"] = rec
    payload["rows"] = [
        {**row,
         "apply": {**(row.get("apply") or {}),
                   "env": {**((row.get("apply") or {}).get("env") or {}),
                           env_name: rec[str(row["row_index"])]}}}
        for row in payload.get("rows", [])
    ]
    if confirm:
        payload["paired"] = True
    return out, payload


def _confirm_round(work_dir: Path, pol: dict | None = None) -> int:
    """Confirm rounds SPENT INCLUDING this one — so the first confirm is 1.

    The count is ``1 + (confirm transitions already recorded)``, which is what
    makes the compiled guard ``{"round": {">=": max_rounds}}`` mean "stop once
    ``max_rounds`` rounds have been spent". Off by one in the other direction
    (a 0-based count) would let a campaign whose registered ``max_rounds`` is 1
    run confirm TWICE — and would change today's behaviour, where one confirm
    iteration ends the campaign.

    SCOPED TO THE EPOCH when ``pol`` is given. ``transitions.jsonl`` is
    append-only across epochs, so a campaign that ended epoch 1 inside confirm
    and recompiled would start epoch 2 with its round cap already spent — the new
    epoch would route ``confirm -> report`` on its FIRST round and never measure
    the shortlist the recompilation was for. ``pol`` is optional because the
    legacy unit tests call this with a work_dir alone and their rows carry no
    epoch; unfiltered is the right answer there (see
    ``policy.epoch_transitions``, which reads a missing epoch as 1).
    """
    rows = (
        policy_mod.read_transitions(work_dir) if pol is None
        else policy_mod.epoch_transitions(pol, work_dir)
    )
    return 1 + sum(1 for t in rows if t.get("from") == Stage.CONFIRM.value)


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

    ``iter_dir`` is accepted and still unused, and the epoch-ending work is why
    it stays that way rather than being removed. It was threaded here for
    ``epoch_end.json``, on the assumption that file would be placed relative to
    the iteration that ended the epoch; it is not. The record is about the EPOCH,
    ``_epoch_index`` counts these files at the work_dir root to know which epoch
    the next run is, and an epoch-scoped fact buried in an iteration directory
    would make that count a directory walk. The iteration is recorded INSIDE the
    file instead, which keeps the iteration identifiable without making the
    filesystem layout carry the association. Kept in the signature because the
    callers pass it and a later terminal artifact may well be per-iteration.
    """
    from orchestrator.iteration import IterationOutcome

    if state not in (pol.get("states") or {}):
        # Reachable only through an explicit `stage=` that the policy does not
        # register — e.g. forcing `refine` on a campaign where nothing is
        # refinable, or a stage the `stages` list omits. `step` would raise a
        # bare ValueError about a missing default transition, which describes
        # the symptom rather than the mismatch.
        raise OptimizationGateFailed(
            f"state {state!r} was run but the compiled policy registers only "
            f"{sorted(pol.get('states') or {})}. A state outside the policy has "
            f"no registered transition, so nothing can decide what follows it — "
            f"either the campaign's `stages` list omits it or no factor makes it "
            f"compilable (refine requires a refinable factor).",
        )
    nxt, rule = policy_mod.step(pol, state, observations)
    policy_mod.append_transition(work_dir, {
        "iteration": iteration,
        # WHICH EPOCH this transition belongs to. `transitions.jsonl` is
        # append-only across epochs — that is the audit trail — so without this
        # field a recompiled epoch would read its predecessor's rows as its own
        # (see `policy.epoch_transitions`) and resume at the terminal
        # `exception` it was recompiled to escape.
        "epoch": pol["epoch"],
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
    if nxt == Stage.REPORT.value:
        _run_report(engine, campaign, work_dir, iteration, pol,
                    recommendation_levels=recommendation_levels)
        return IterationOutcome.COMPLETED
    if nxt == Stage.EXCEPTION.value:
        # ── the paper's orange exit: the EPOCH ends, the campaign does not ──
        #
        # An observation exposed a semantic condition the policy did not name.
        # No further measurement inside this epoch can repair it — that is what
        # makes it semantic rather than statistical — so the epoch ends here and
        # a revision plus a recompilation starts the next one
        # (`_load_or_compile_policy` picks the new epoch up from this file).
        #
        # THE CAMPAIGN STILL RETURNS AN ACTION. This used to raise, which meant
        # `run_campaign` unwound with no `report.json` at all: no recommendation,
        # no bounds, not even the baseline the author declared as known-good. The
        # paper is explicit that this is the wrong trade — "uncertainty weakens
        # the claim; it need not prevent a decision" — and the ladder in
        # `_run_report` is built precisely for the case where the strongest rungs
        # are unavailable. What the exception DOES remove is the `model` rung: the
        # fitted surface is the thing the exception just impeached (an optimum
        # outside the hull is an extrapolation from it; a NaN response means it
        # was never validly fitted), so `epoch_ended` skips it and the answer
        # falls to `measured` or `baseline` — a configuration something actually
        # ran, or the one the author certified by hand.
        #
        # `epoch_end-<e>.json` at the WORK_DIR ROOT, not inside `iter_dir`. The
        # file is about the EPOCH, and `_epoch_index` counts these files to know
        # which epoch the next run is; burying it per-iteration would make that
        # count a directory walk and would put an epoch-scoped fact in an
        # iteration-scoped place. `iteration` is recorded inside it instead, so
        # the iteration that ended the epoch is still identifiable.
        reason = f"{state}: {json.dumps(rule.get('when'), sort_keys=True)}"
        _write_json(Path(work_dir) / f"epoch_end-{pol['epoch']}.json", {
            "epoch": pol["epoch"],
            "iteration": iteration,
            "state": state,
            "rule": rule,
            "observations": observations,
            "reason": reason,
            # What a NEW epoch would need (spec §3.9: "why the epoch ended, and
            # what a new one would need"). Not prose a model wrote — the
            # observation that fired is the diagnosis, so this maps it to the
            # revision it calls for.
            "next_epoch_requires": _epoch_end_remedy(rule.get("when") or {}),
            "policy_hash": policy_mod.policy_hash(pol),
        })
        logger.warning(
            "SEMANTIC EXCEPTION at %s: %s. Epoch %d ends here — no further "
            "measurement inside it can repair a condition the policy did not "
            "name. %s Writing the report anyway on the strongest rung that does "
            "not rest on the fitted surface; a revision plus `nous resume <campaign.yaml>` "
            "starts epoch %d from %r.",
            state, reason, pol["epoch"],
            _epoch_end_remedy(rule.get("when") or {}),
            pol["epoch"] + 1, pol.get("initial"),
        )
        _run_report(engine, campaign, work_dir, iteration, pol,
                    recommendation_levels=None, epoch_ended=reason)
        return IterationOutcome.COMPLETED
    return IterationOutcome.CONTINUE


def _epoch_end_remedy(when: dict) -> str:
    """What a NEW epoch would need, given the guard that ended this one.

    Spec §3.9 asks the epoch-end record to say "why the epoch ended, and what a
    new one would need". The "why" is the guard; the "what" is a fixed mapping
    from the observation that fired to the revision it calls for, because the
    observation vocabulary is CLOSED — so this is a lookup, not a judgement, and
    it needs no model call to write.
    """
    if when.get("stationary_in_hull") is False:
        return (
            "the fitted optimum lies OUTSIDE the declared level hull, so the "
            "declared ranges do not contain it and no measurement inside them "
            "ever will: widen the offending factor's `levels` (see "
            "recommendation.json's `stationary_point` for which axis and how "
            "far) and recompile."
        )
    if when.get("nan_response") is True:
        return (
            "a configuration that RAN to completion reported a non-numeric "
            "primary metric, so the target's instrumentation and the campaign's "
            "objective disagree about what is measurable at that point: fix the "
            "metric's definition or exclude the region with a declared "
            "constraint, then recompile. Re-running the same epoch would "
            "re-measure the same NaN."
        )
    if when.get("correctness_failed") is True:
        return (
            "a correctness relation failed, so the apparatus measures the wrong "
            "system: repair the mechanism (or the relation, if the asserted "
            "algebra was wrong) and recompile."
        )
    return (
        "the policy routed to `exception` on "
        f"{json.dumps(when, sort_keys=True)}: revise the mechanism or the "
        "interface so the condition is either impossible or a named branch, "
        "then recompile."
    )


import contextvars

#: Set while run_stage serves ``nous reanalyze``: nothing is measured, and the
#: scratch work_dir has no clean tree to check.
_REANALYSIS = contextvars.ContextVar("nous_reanalysis", default=False)


def _check_survivors(work_dir, iteration, what: str) -> None:
    """Raise when a target command left processes running after it returned
    (reaper.run_in_process_group reaped them and recorded it; round 3, C2)."""
    from orchestrator.optimize import reaper

    left = reaper.take_survivors()
    if not left:
        return
    p = Path(work_dir) / "runs" / f"iter-{iteration}" / "target_survivors.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    _write_json(p, {"after": what, "survivors": left})
    raise OptimizationGateFailed(
        f"after the {what}: {len(left)} target command(s) left processes running "
        f"after they returned ({[x['cmd'][:60] for x in left[:3]]}); they were killed. "
        f"A process that outlives its command can change the measured tree or the "
        f"results after every check. See {p.name}.")


def _check_clean_tree_after(campaign, work_dir, what: str) -> None:
    """Raise when target code modified the clean tree (clean_tree.check)."""
    from orchestrator.optimize import clean_tree as _ct

    if _REANALYSIS.get() or not (Path(work_dir) / _ct.RECORD).exists():
        return
    try:
        _ct.check(Path(work_dir))
    except _ct.CleanTreeError as exc:
        raise OptimizationGateFailed(f"after the {what}: {exc}") from exc


def _run_report(engine, campaign, work_dir, iteration, pol, *,
                recommendation_levels, epoch_ended: str | None = None) -> None:
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
                              measured those exact levels invalid AND no semantic
                              exception ended the epoch (``epoch_ended``): this
                              is the one rung that rests on the fitted surface,
                              and an exception is evidence against that surface.
      4. ``measured``       — the model's answer is unusable; return the best
                              measured ADMISSIBLE configuration. Never the largest
                              noisy observation — ``_best_observed`` keeps only
                              configurations with a ``complete`` row and NO
                              infeasible/rejected row anywhere
                              (``_config_admissible``: feasibility is per
                              configuration, the same sticky rule confirm
                              applies to its finalists), and the terminal stage
                              is what re-measures when there is budget for it.
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
    # No report on measurements from a tree target code modified (round 3, A4).
    _check_clean_tree_after(campaign, work_dir, "last stage, at the terminal transition")
    primary = _primary_of((campaign.get("optimization") or {}).get("response"))
    metric = primary.get("metric") or ""
    direction = primary.get("direction") or pol["objective"]["direction"]
    conf = _latest_confirmation(work_dir)
    # THIS EPOCH's latest fitting-stage record, ``{}`` before the epoch wrote
    # one. The report describes ONE epoch: its model rung, model bound,
    # candidate space, epsilon fallback, adequacy and level facts all come from
    # this record, the same one the epoch-scoped bar (``_barred_levels``) reads.
    # Reading the latest record from ANY epoch let an epoch that ended before
    # fitting present the previous epoch's fitted pick as its answer while
    # omitting that epoch's verdict on the model; with ``{}`` such an epoch
    # falls to the measured / baseline rungs, as it should.
    _epoch_rec = (_epoch_recommendations(work_dir) or [{}])[-1]
    rec = _epoch_rec
    # ── MULTI-OBJECTIVE: the front is the answer; the ladder picks a point ──
    #
    # The latest confirm round's measured front when there is one; otherwise
    # the measured front over the fitting stages' admissible rows (rounds 0).
    # The ladder below keeps its rungs; only WHICH point each rung names
    # changes (the preferred point of the measured front, by preference).
    mo_front = None
    if pareto_stage.objectives(pol):
        mo_front = (conf or {}).get("pareto") or pareto_stage.front_record(
            pol, work_dir, rec=rec, rnd=0,
            baseline=pol.get("known_valid_baseline"),
        )
    _mo_chosen = dict(((mo_front or {}).get("preference") or {}).get("chosen") or {})

    def _mo_value(levels):
        for f in (mo_front or {}).get("front") or []:
            if _same_levels(dict(f["levels"]), dict(levels)):
                return f["mean"].get(metric)
        return None

    if mo_front is not None and conf and conf.get("pareto") and _mo_chosen:
        basis = "certified" if conf.get("certified") else "terminal_best"
        levels, value = _mo_chosen, _mo_value(_mo_chosen)
    elif mo_front is not None and conf and conf.get("pareto"):
        basis, levels, value = (
            ("baseline", dict(pol["known_valid_baseline"]), None)
            if pol.get("known_valid_baseline") else ("none", {}, None))
    elif conf and conf.get("best") and mo_front is None:
        basis = "certified" if conf.get("certified") else "terminal_best"
        levels, value = dict(conf.get("confirmed_at_levels") or {}), conf.get("mean")
    elif (
        rec.get("levels")
        # THE `model` RUNG IS UNAVAILABLE ONCE A SEMANTIC EXCEPTION ENDED THE
        # EPOCH. Every rung above rests on fresh MEASUREMENTS of the
        # configuration it returns; this one is the only rung that rests on the
        # fitted surface, and the semantic exception is evidence against that
        # surface specifically — an out-of-hull stationary point means the argmax
        # is an extrapolation past the design's own range, and a NaN response
        # means the fit's inputs were never all valid numbers. Returning the
        # model's pick anyway would be reporting the one answer the exception
        # just impeached, and labelling it `model` would tell the reader nothing
        # is wrong with it.
        #
        # Rungs 1/2 are deliberately NOT suppressed. They are measurements of a
        # shortlist against itself, they do not consult the surface, and an
        # exception raised at some LATER state (or in a later epoch over the same
        # work_dir) does not retract a terminal comparison that actually
        # happened. When the exception is confirm's own `nan_response`, there is
        # no `best` to read anyway, so those rungs fall through on their own
        # facts rather than on a special case.
        and not epoch_ended
        # WP-B B5: nor once this epoch's model was REJECTED (lack of fit, or
        # the validation prediction check). The argmax of a surface the data
        # refused is not an answer; the measured rung below is.
        and rec.get("model_adequate") is not False
        and _config_admissible(work_dir, rec["levels"])
    ):
        basis, levels, value = "model", dict(rec["levels"]), rec.get("predicted")
    elif mo_front is not None and _mo_chosen:
        basis, levels, value = "measured", _mo_chosen, _mo_value(_mo_chosen)
    else:
        best = (
            _best_observed(work_dir, metric, direction=direction)
            if metric and mo_front is None else None
        )
        if best:
            basis, levels, value = "measured", dict(best["levels"]), best.get(metric)
        elif pol.get("known_valid_baseline"):
            basis, levels, value = "baseline", dict(pol["known_valid_baseline"]), None
        else:
            basis, levels, value = "none", {}, None

    # EPOCH-SCOPED, like every other consumer of this file. `transitions.jsonl`
    # is append-only ACROSS epochs (see `policy.epoch_transitions`), so an
    # unfiltered read would splice the previous epoch's rows into THIS epoch's
    # reported `path` — a campaign whose epoch 1 ended at `exception` and
    # recompiled would report `screen -> screen -> confirm -> report`, naming a
    # state transition that never happened in the epoch the report describes.
    trans = policy_mod.epoch_transitions(pol, work_dir)
    # The registered boundary branch (policy `out_of_hull: confirm`) fired:
    # refine's optimum lies past the declared ranges, so whatever confirm
    # certified is the best configuration INSIDE them. Say so in the report,
    # with the axes, so a certificate is never read as covering more space
    # than was declared.
    boundary = next((t for t in trans if t.get("from") == "refine"
                     and ((t.get("rule") or {}).get("when") or {}).get(
                         "stationary_in_hull") is False
                     and t.get("to") != "exception"), None)
    boundary_block = None
    if boundary is not None:
        sp = (rec or {}).get("stationary_point") or {}
        boundary_block = {
            "axes": sorted(k for k, v in sp.items()
                           if isinstance(v, (int, float)) and abs(v) > 1.0),
            "certificate_scope": "declared_ranges",
        }
    # The held-out generalization check, READ only now that every decision
    # above is made, so it can inform a reader and nothing else
    # (orchestrator/optimize/held_out.py).
    from orchestrator.optimize.held_out import held_out_summary

    held_out_block = held_out_summary(
        work_dir,
        iterations={t.get("iteration") for t in trans
                    if isinstance(t.get("iteration"), int)} | {iteration},
        held_out=list(((_opt_block(campaign) or {}).get("response") or {})
                      .get("held_out") or []),
        primary=metric or "",
        recommendation=levels,
        finalists=(conf.get("finalists") if conf else []) or [],
    )
    _write_json(Path(work_dir) / "report.json", {
        "recommendation": {
            "levels": levels, "basis": basis,
            **({"value": value} if value is not None else {}),
        },
        "residual_regret_model": (rec.get("residual_regret_model") or {}).get("value"),
        # The searched caveat travels with the bound copied above it: present
        # exactly when that recommendation's candidate space was SEARCHED, so
        # report.json alone says the model bound and argmax are over the
        # evaluated set only. Absent (byte-identical) when enumerated.
        **({"candidate_space": dict(rec["candidate_space"])}
           if rec.get("candidate_space") else {}),
        # The latest fitting stage's model-adequacy facts (stage-1b N4), each
        # present only when it says something (unknown adequacy, untested
        # curvature, lost or inadmissible levels), so a report without them is
        # byte-identical. A REJECTED model is already named by
        # certification_withheld (model_inadequate).
        # Unknown AND rejected adequacy are both copied (stage-1c P4): a
        # rejected model is otherwise invisible in a report whose confirm never
        # ran (certification_withheld is then only no_terminal_discrimination).
        # EVERY adequacy/coverage fact below is read from THIS epoch's latest
        # record (_epoch_rec), the one the bar reads: mixing an earlier epoch's
        # facts into this epoch's report would describe two epochs at once.
        **({"model_adequate": None,
            "model_adequate_basis": _epoch_rec.get("model_adequate_basis")}
           if "model_adequate" in _epoch_rec and _epoch_rec["model_adequate"] is None
           else {}),
        **({"model_adequate": False} if _epoch_rec.get("model_adequate") is False else {}),
        # WHICH test rejected (WP-B B5), so report.md can say it plainly.
        **({"model_rejected_by": sorted({
            c for r in _epoch_recommendations(work_dir)
            for c in ((r.get("model_adequacy") or {}).get("this_stage") or {})
            .get("rejected_by") or []})}
           if _epoch_rec.get("model_adequate") is False
           and _epoch_rec.get("model_adequacy") else {}),
        **({k: dict(_epoch_rec[k]) for k in ("curvature_untested_levels",)
            if _epoch_rec.get(k)}),
        # The LEVEL facts the bar acts on come from THIS epoch's latest record
        # only, exactly as ``_barred_levels`` reads them -- an epoch that ends
        # before writing a recommendation must not report the previous epoch's
        # lost/inadmissible levels while its measured rung recommends them.
        **({k: dict(_epoch_rec[k]) for k in ("lost_levels", "inadmissible_levels")
            if _epoch_rec.get(k)}),
        **({k: list(_epoch_rec[k]) for k in ("all_levels_inadmissible",)
            if _epoch_rec.get(k)}),
        **({k: list(_epoch_rec[k]) for k in ("aliases_not_assessed",)
            if _epoch_rec.get(k)}),
        "residual_regret_terminal": (
            conf.get("residual_regret_terminal") if conf else None
        ),
        "epsilon": conf.get("epsilon") if conf else rec.get("epsilon"),
        "epsilon_reference": (conf.get("epsilon_reference") if conf else None),
        "delta_screen": pol["objective"]["delta_screen"],
        "delta_terminal": pol["objective"]["delta_terminal"],
        "certified": bool(conf and conf.get("certified")),
        # WHY `certified` is false, carried up from confirmation.json so the
        # report never states an unexplained boolean next to bounds that look
        # as though they should certify. Empty exactly when certified.
        "certification_withheld": (
            [] if conf and conf.get("certified")
            # A confirmation.json written before the field existed carries no
            # reasons; an uncertified report with an EMPTY list would break the
            # "empty exactly when certified" rule, so say the reason is unknown.
            else (list(conf.get("certification_withheld") or [])
                  or ["reason_not_recorded"])
            if conf else ["no_terminal_discrimination"]
        ),
        "finalists": (conf.get("finalists") if conf else []) or [],
        "known_valid_baseline": pol.get("known_valid_baseline"),
        # The declared baseline is EXEMPT from the lost/inadmissible-level bar
        # (stage-1d Q4); when the report's answer names such a level, say so.
        **({"recommendation_names_barred_level": {
                fid: levels[fid] for fid, lvs in _barred_levels(work_dir).items()
                if fid in levels and levels[fid] in lvs}}
           if levels and _names_barred_level(levels, _barred_levels(work_dir)) else {}),
        "path": [t["from"] for t in trans] + ([trans[-1]["to"]] if trans else []),
        "epoch": pol["epoch"],
        # Present ONLY when a semantic exception ended the epoch, and then it is
        # the guard that fired. A reader must be able to tell an ordinary report
        # from one written on the way out of a failed epoch without reading the
        # log, which is the same reason `basis` exists — and `epoch_end-<e>.json`
        # carries the full record next to it.
        **({"epoch_ended": epoch_ended} if epoch_ended else {}),
        **({"held_out": held_out_block} if held_out_block else {}),
        **({"pareto": mo_front} if mo_front is not None else {}),
        **({"certification_caveats": list(conf["certification_caveats"])}
           if conf and conf.get("certification_caveats") else {}),
        **({"boundary_optimum": boundary_block} if boundary_block else {}),
        # WP-A A4: WHICH region a certificate covers. Refine holds every
        # non-refinable factor (choice, two-level) at one level, and the model
        # bound and candidate space are then over that SLICE only; a
        # certificate there says nothing about the other levels (measured:
        # ridge_cubic certified C=on while the optimum has C=off).
        "certificate_scope": _certificate_scope(_epoch_rec, boundary_block),
        **({"gain_over_baseline": dict(conf["gain_over_baseline"])}
           if conf and conf.get("gain_over_baseline") else {}),
        "policy_hash": policy_mod.policy_hash(pol),
        "iteration": iteration,
        # What this report rests on (audit Q7): code version, input hashes,
        # analysis constants, waived gates; and the cross-epoch error budget.
        # See orchestrator/optimize/provenance.py.
        **_report_provenance(work_dir, pol, campaign),
    })
    logger.info(
        "report: recommendation %s on basis %r (certified=%s); R_model=%s, "
        "R_terminal=%s at delta_s=%s / delta_t=%s%s",
        levels, basis, bool(conf and conf.get("certified")),
        (rec.get("residual_regret_model") or {}).get("value"),
        conf.get("residual_regret_terminal") if conf else None,
        pol["objective"]["delta_screen"], pol["objective"]["delta_terminal"],
        f"; epoch ended by semantic exception ({epoch_ended})" if epoch_ended
        else "",
    )
    engine.transition("DONE")


def _report_provenance(work_dir, pol, campaign) -> dict:
    """``provenance`` and ``error_budget`` for report.json (provenance.py)."""
    from orchestrator.optimize import provenance as prov_mod

    _prov = prov_mod.build_provenance(
        Path(work_dir), policy_mod.policy_hash(pol), campaign=campaign)
    if not _REANALYSIS.get():
        # The anchor check is a fact about THIS work_dir's external record, so
        # a reanalysis scratch dir (which has none) does not re-derive it.
        from orchestrator.optimize import anchor as _anchor

        _v = _anchor.verify(Path(work_dir))
        _prov["anchor"] = {k: _v[k] for k in ("present", "matches", "mismatches", "where",
                                              "reanchored")}
        if _v["present"] and not _v["matches"]:
            logger.error("report: the pre-registration does NOT match its external "
                         "anchor: %s", "; ".join(_v["mismatches"]))
    return {
        "provenance": _prov,
        "error_budget": prov_mod.error_budget(Path(work_dir), pol),
    }


def _measured_infeasible_contains(work_dir, levels: dict, *,
                                  invalid: list[dict] | None = None) -> bool:
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
    want = dict(levels or {})
    if not want:
        return False
    return any(
        _same_levels(other, want)
        for other in (
            _measured_infeasible(work_dir) if invalid is None else invalid
        )
    )


def _same_levels(a: dict, b: dict) -> bool:
    """Two level dicts name the same CONFIGURATION (numerics within tolerance)."""
    import math as _math

    if set(a) != set(b):
        return False
    for k, v in b.items():
        o = a[k]
        if (isinstance(v, (int, float)) and isinstance(o, (int, float))
                and not isinstance(v, bool) and not isinstance(o, bool)):
            if not _math.isclose(float(o), float(v), rel_tol=1e-9,
                                 abs_tol=1e-12):
                return False
        elif o != v:
            return False
    return True


def _config_admissible(work_dir, levels: dict, *,
                       invalid: list[dict] | None = None,
                       barred: dict | None = None) -> bool:
    """FEASIBILITY IS A PROPERTY OF A CONFIGURATION, NOT OF A ROW.

    The ONE predicate every selector of a configuration to RETURN or to SEED
    goes through: the report ladder's ``model`` and ``measured`` rungs,
    ``_top_measured`` / ``_best_observed`` (and so the shortlist's measured
    seeds and ``_finish_confirm``'s best-observed comparison and epsilon
    reference). A configuration with ANY ``infeasible`` / ``rejected`` row
    anywhere in the campaign is inadmissible, however many of its other rows
    completed — the same sticky rule ``_finish_confirm`` applies to a finalist's
    replicates ("a configuration that is admissible only sometimes is not
    admissible").

    Judging per row was the defect: on a field campaign whose constraint metric
    straddled its bound, a finalist with two complete and three infeasible
    replicates was struck off by confirm and then returned by the report's
    ``measured`` rung on the strength of its best complete row. A row that
    merely failed to measure (timeout, crash) is NOT evidence of
    inadmissibility and does not strike the configuration off.

    ``invalid`` lets a caller that tests many configurations read
    ``_measured_infeasible`` once; ``barred`` does the same for
    ``_barred_levels`` (stage-1d Q3).
    """
    if _names_barred_level(levels, _barred_levels(work_dir) if barred is None else barred):
        return False
    return not _measured_infeasible_contains(work_dir, levels, invalid=invalid)


def _union_levels(*maps) -> dict:
    """Per-factor union of ``{factor: [levels]}`` maps, order kept."""
    out: dict = {}
    for m in maps:
        for fid, lvs in (m or {}).items():
            cur = out.setdefault(fid, [])
            for lv in lvs:
                if lv not in cur:
                    cur.append(lv)
    return out


def _epoch_recommendations(work_dir) -> list[dict]:
    """Every fitting-stage recommendation.json of this epoch, in order."""
    out = []
    for d in _this_epoch_dirs(work_dir):
        p = d / "recommendation.json"
        if p.exists():
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
    return out


def _epoch_lost_levels(work_dir) -> dict:
    """Per-factor UNION of lost_levels over the epoch's fitting stages (Q1)."""
    return _union_levels(*[r.get("lost_levels") or {}
                           for r in _epoch_recommendations(work_dir)])


def _barred_levels(work_dir) -> dict:
    """ONE RULE (stage-1c P1): the categorical levels nothing may recommend --
    lost (no retained row, incl. lost at the corners) in ANY fitting stage of
    the epoch (stage-1d Q1), and inadmissible wherever measured unless the
    factor is fully barred (``all_levels_inadmissible``; Q2: then only its
    lost levels are). ``{}`` for every campaign without them, which leaves
    every selector unchanged."""
    recs = _epoch_recommendations(work_dir)
    # EPOCH-SCOPED (stage-1d round-5 item 1): only this epoch's records. A
    # previous epoch's recommendation (``_read_recommendation`` is not
    # epoch-scoped) must not bar a level before this epoch has measured it.
    rec = recs[-1] if recs else {}
    every = set(rec.get("all_levels_inadmissible") or ())
    return _union_levels(
        {k: v for k, v in (rec.get("inadmissible_levels") or {}).items()
         if k not in every},
        *[r.get("lost_levels") or {} for r in recs + [rec]])


def _names_barred_level(levels, barred: dict) -> bool:
    return any(fid in (levels or {}) and levels[fid] in lvs
               for fid, lvs in (barred or {}).items())


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
    reanalysis: bool = False,
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

    from orchestrator.optimize import reaper as _reaper

    _reaper.take_survivors()          # none from an earlier stage count here
    _reanalysis_token = _REANALYSIS.set(bool(reanalysis))
    try:
        return _run_stage_body(
            campaign, work_dir, iteration=iteration, stage=stage,
            config_runner=config_runner, integrity_check=integrity_check,
            test_results=test_results, auto_approve=auto_approve, gate=gate,
            model=model, sdk_runner=sdk_runner, reanalysis=reanalysis, **_ignored)
    finally:
        _REANALYSIS.reset(_reanalysis_token)


def _run_stage_body(
    campaign: dict,
    work_dir: Path,
    *,
    iteration: int,
    stage=None,
    config_runner=None,
    integrity_check=None,
    test_results=None,
    auto_approve: bool = True,
    gate=None,
    model=None,
    sdk_runner=None,
    reanalysis: bool = False,
    **_ignored,
):
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

    # Resolve the stage FIRST: what the pre-epoch work below does depends on
    # which stage this is (`build` records a before-state; `verify` reads it).
    # An earlier version resolved here so it could SKIP the test command on a
    # build iteration; that is no longer the rule — see the block below, which
    # runs it deliberately, and oracle 2(b) for why the pre-build outcome is the
    # whole point.
    #
    # Resolved ONCE: `_resolve_state` may compile and write policy.json, and
    # calling it twice would re-read (and re-hash-check) the same file for no
    # reason. `stage_name`/`pol` below are these same values.
    stage_name, pol = _resolve_state(campaign, work_dir, iteration, stage)
    _is_build = stage_name == Stage.BUILD.value
    if _is_build and "plan" in (opt.get("stages") or []):
        from orchestrator.optimize.plan import PLAN_FILENAME

        if not (Path(work_dir) / PLAN_FILENAME).exists():
            # Checked before the pre-build test run and control measurement, so a
            # planless build spends nothing. Covers a resumed work_dir as well as
            # the plan stage's own abort path.
            raise OptimizationGateFailed(
                f"build will not run: this campaign declares a `plan` stage but "
                f"{PLAN_FILENAME} is absent from {work_dir}. Building without it "
                f"would author a mechanism nobody planned. Re-run the plan stage, "
                f"or seed a reviewed {PLAN_FILENAME} into the work_dir and drop "
                f"`plan` from optimization.stages.",
            )
    # Set only when the test command runs HERE; None when verdicts were injected.
    test_run: "runner.NativeTestResults | None" = None

    # THE BUILD RECORDS ARE READ ONCE, HERE, before any target code runs at
    # verify (the test command below executes agent-authored code). The oracles
    # use these sealed in-memory copies (gate_records.py).
    _gate = None
    if stage_name == Stage.VERIFY.value and not reanalysis:
        from orchestrator.optimize import build_scope as _bs
        from orchestrator.optimize import gate_records as _gr

        if _bs.build_declared(campaign) or (Path(work_dir) / "pre_build_tests.json").exists():
            try:
                _gr.require_outside_repo(work_dir, Path(repo) if repo else None)
                _gate = _gr.load(work_dir)
            except _gr.GateRecordError as exc:
                raise OptimizationGateFailed(str(exc)) from exc

    # WHERE TARGET CODE RUNS. With a build stage, every stage after it runs the
    # target's commands in the CLEAN CHECKOUT of the pre-build commit plus the
    # recorded mechanism patch (clean_tree.py) -- never in the agent's tree.
    exec_repo = Path(repo) if repo else None
    if (repo and not _is_build and stage_name != Stage.PLAN.value and not reanalysis):
        from orchestrator.optimize import clean_tree as _ct

        if _ct.active(campaign, work_dir):
            from orchestrator.optimize import gate_records as _gr2

            broken = [n for n in (_ct.RECORD, _ct.PATCH) if _gr2.check(work_dir, n) != "ok"]
            if broken:
                raise OptimizationGateFailed(
                    f"the recorded mechanism {broken} fails its seal: what the epoch "
                    f"would measure cannot be shown to be what the build produced.")
            try:
                exec_repo = _ct.ensure(Path(repo), work_dir,
                                       fresh=stage_name == Stage.VERIFY.value)
            except _ct.CleanTreeError as exc:
                raise OptimizationGateFailed(str(exc)) from exc


    if test_results is None and opt.get("test_command") and repo:
        # Runs on the BUILD iteration too, and deliberately so (oracle 2(b),
        # spec §3.7). An earlier version skipped it here on the grounds that
        # testing code which does not exist yet learns nothing — but that is
        # exactly what it learns, and the answer is load-bearing: a declared
        # correctness test that ALREADY PASSES before the mechanism exists does
        # not test the mechanism. `verify` cannot ask that question afterwards,
        # because by then the mechanism is there. The old rationale's other
        # point stands and is now handled rather than avoided: `go test -run
        # <pattern>` exits 0 with "no tests to run", so the pre-build verdicts
        # come from `match_declared_tests`' PER-TEST parse, where an identifier
        # that never ran is absent rather than passing.
        #
        # Persist the raw test output next to the iteration's artifacts. A
        # verify abort ends the campaign, so this text is the only record of
        # WHY, and re-running by hand may not reproduce a timeout or an
        # ordering-dependent failure.
        raw = runner.run_test_command(
            opt["test_command"], cwd=exec_repo,
            timeout=resolve_test_timeout(opt),
            log_path=Path(work_dir) / "runs" / f"iter-{iteration}" / "test_output.log",
        )
        # Kept beside the verdicts so a verify abort can say HOW the run ended:
        # `match_declared_tests` returns a plain dict, and an empty one reads
        # the same whether the suite was killed, crashed, or printed nothing.
        test_run = raw
        _check_survivors(work_dir, iteration, f"{stage_name} test command")
        test_results = runner.match_declared_tests(parse_factors(opt["factors"]), raw)
        logger.info(
            "test_command reported %d test(s); %d matched a declared "
            "native_test", len(raw), len(test_results),
        )
    # Resolved before the build branch, not after it: the pre-build control
    # measurement below needs the same runner the post-build one at `verify`
    # will use. Resolving only afterwards would measure `post` in production
    # while silently skipping `pre`, which turns oracle 2(c) off precisely on
    # the real campaigns it exists for.
    if config_runner is None and opt.get("run_command") and repo:
        config_runner = runner.make_config_runner(
            opt["run_command"], cwd=exec_repo,
            metric_path=_primary_of(opt.get("response")).get(
                "metric", "",
            ),
            timeout=resolve_run_timeout(opt),
            log_dir=Path(work_dir) / "runs" / f"iter-{iteration}" / "failed_runs",
        )

    if _is_build:
        from orchestrator.optimize import build as build_mod

        _factors_for_build = parse_factors(opt["factors"])
        # ── oracle 2(b), first half: what passed BEFORE the mechanism existed ──
        #
        # Recorded here and read at `verify`, because this is the only moment at
        # which the question is answerable. Both keys matter: `passed` is what
        # verify rejects, and `ran` is what distinguishes "the test existed and
        # failed" (the shape a build is supposed to have) from "the test command
        # never mentioned it", which is the fail-closed case verify already owns.
        from orchestrator.optimize import gate_records, test_vacuity

        # A build needs a repo at all (round 3, E3): say so here rather than
        # failing later with a misleading "record absent" seal error.
        if not repo:
            raise OptimizationGateFailed(
                "a build stage needs target_system.repo_path: the mechanism is "
                "authored in that repository and verified in a clean checkout of its "
                "commit.")
        # Gate records live OUTSIDE the repo and are sealed (gate_records.py).
        try:
            gate_records.require_outside_repo(work_dir, Path(repo) if repo else None)
        except gate_records.GateRecordError as exc:
            raise OptimizationGateFailed(str(exc)) from exc
        gate_records.ensure_key(work_dir)
        # The clean-checkout model (clean_tree.py): a real scope, and a committed
        # pre-build tree whose commit the mechanism patch is taken against.
        from orchestrator.optimize import build_scope as _bs0
        from orchestrator.optimize import clean_tree
        try:
            _bs0.mechanism_scope(campaign)
            _clean_base = clean_tree.require_clean_base(Path(repo)) if repo else None
            # The pre-build TREE hash, recorded before the agent can touch the
            # repository's objects: every clean tree is checked against it.
            _clean_tree_sha = clean_tree.base_tree(Path(repo), _clean_base) if repo else None
            # The ignored assets the clean tree will copy, as they are BEFORE
            # the agent runs (clean_tree.extras_digest).
            _extras_pre = clean_tree.extras_digest(
                Path(repo), list((campaign.get("target_system") or {})
                                 .get("worktree_extras") or []))
        except (_bs0.BuildScopeViolation, clean_tree.CleanTreeError) as exc:
            raise OptimizationGateFailed(str(exc)) from exc
        _write_json(Path(work_dir) / "pre_build_tests.json", {
            "passed": sorted(t for t, ok in (test_results or {}).items() if ok),
            "ran": sorted(test_results or {}),
            # WHY each failing test failed (oracle 2(d)): a failure only on a
            # missing symbol is not evidence the test observes the mechanism.
            "failure_kinds": test_vacuity.kinds_for(
                test_results or {}, test_vacuity.read_log(test_run)),
            # Whether those kinds were read from real test output (False only
            # when verdicts were injected): 2(d) accepts an unclassified
            # pre-build failure only without output.
            "output_recorded": test_vacuity.read_log(test_run) is not None,
            # True only when no test command ran here at all (the verdicts were
            # injected by a caller): review C2.
            "verdicts_injected": test_run is None,
        })
        # ── oracle 2(c), first half: the control, measured before the build ──
        #
        # Not attempted at all (file left absent) when the campaign declares no
        # baseline or no runner is available. Absence is what disables the check
        # at verify — the same convention `mechanism.sha256` uses — rather than a
        # recorded value that could never match.
        #
        # THE ATTEMPT MUST NOT BE ABLE TO KILL THE CAMPAIGN. This measurement is
        # the one place in the kind that runs the target's `run_command` against
        # a tree where the mechanism does NOT exist yet — and frequently where
        # the benchmark harness itself does not exist yet either, because `build`
        # is often what authors it. `render_apply` renders the new mechanism's
        # flag even at its control level, so a strict CLI parser exits non-zero
        # on a flag it has never heard of, and `make_config_runner` raises on a
        # harness that emits no parseable JSON. Both are NORMAL pre-build states,
        # not campaign errors. Letting either propagate aborted the campaign
        # before `run_build` — i.e. the oracle's setup destroyed the one
        # substantive model call the whole kind is built around, and authored
        # nothing. (Verified as a real A/B regression against the previous
        # commit, not a hypothetical.)
        #
        # So a failure here DEGRADES the oracle instead of failing the campaign:
        # the reason is recorded as `pre_unavailable` and `verify` says out loud
        # that 2(c) could not be armed. Recorded rather than merely logged
        # because a silently absent oracle on the one stage that authors code is
        # indistinguishable from an oracle that passed, and a campaign author
        # reading the artifacts afterwards must be able to tell those apart.
        _pre_baseline = opt.get("known_valid_baseline")
        if _pre_baseline and config_runner is not None:
            _n = _baseline_replicates(campaign)
            _metric = (
                _primary_of(opt.get("response")).get("metric") or ""
            )
            # The workload block reaches the oracle from the campaign rather
            # than from `pol` — `pol` is None at the pre-epoch stages, and
            # `compile_policy` copies `optimization.workload` through verbatim,
            # so both halves of the pre/post pair read the identical block.
            _wl = opt.get("workload")
            try:
                _pre = build_mod.baseline_runs(
                    config_runner, _factors_for_build, dict(_pre_baseline),
                    n=_n, metric=_metric, workload=_wl,
                )
            except Exception as exc:  # noqa: BLE001 — see the rationale above
                # Deliberately broad: the raiser is the TARGET's harness via an
                # injected callable, so the exception type is whatever that
                # target's failure mode produces. Narrowing to RuntimeError
                # would let the next harness's OSError/ValueError re-introduce
                # exactly the regression this guard exists to prevent.
                _reason = f"{type(exc).__name__}: {exc}"
                _write_json(Path(work_dir) / "baseline_equivalence.json", {
                    "levels": dict(_pre_baseline),
                    "pre_unavailable": _reason,
                    "tolerance_pct": _baseline_tolerance_pct(campaign),
                })
                logger.warning(
                    "build: could NOT measure the known_valid_baseline %s before "
                    "the build (%s). This is expected when the run_command or the "
                    "mechanism's flag does not exist yet — the build proceeds, but "
                    "oracle 2(c) (control must be unchanged across the build) is "
                    "NOT armed for this campaign, so nothing will check that the "
                    "mechanism is inert at its control level. To arm it, make the "
                    "run_command accept the control configuration before the build "
                    "runs. Recorded as pre_unavailable in "
                    "baseline_equivalence.json.",
                    dict(_pre_baseline), _reason,
                )
            else:
                # `workload_seeds` records the draws so verify can re-run the
                # SAME ones, and so a reader can tell a paired comparison from
                # an unpaired one without re-deriving anything. Omitted (rather
                # than written as null) when the campaign declares no
                # `workload.seed_env`, matching the artifact's existing habit of
                # letting absence mean "not applicable".
                _pre_seeds = build_mod.baseline_seeds(_wl, _n)
                _rec = {
                    "levels": dict(_pre_baseline),
                    "pre": _pre,
                    "pre_mean": _mean(_pre),
                    "tolerance_pct": _baseline_tolerance_pct(campaign),
                }
                if _pre_seeds is not None:
                    _rec["workload_seeds"] = _pre_seeds
                    _rec["workload_seed_env"] = _wl.get("seed_env")
                _write_json(Path(work_dir) / "baseline_equivalence.json", _rec)
                logger.info(
                    "build: measured the known_valid_baseline %s x%d before the "
                    "build (mean %s on %s) — verify re-measures it and hard-fails "
                    "if the mechanism moved it",
                    dict(_pre_baseline), _n, f"{_mean(_pre):.6g}",
                    _metric or "<unset>",
                )
        from orchestrator.optimize import build_scope

        # The write-scope gate: what the agent changed is the diff between the
        # tree just before and just after its call (build_scope.py).
        _scope_before = build_scope.snapshot(Path(repo), work_dir) if repo else None
        from orchestrator.optimize import isolation

        try:
            # Every process the build starts must be gone when it returns
            # (isolation.py): a survivor could act after every check.
            with isolation.track(work_dir):
                build_mod.run_build(
                    campaign, work_dir,
                    iteration=iteration,
                    declared_tests=build_mod.declared_native_tests(_factors_for_build),
                    model=model,
                    max_turns=_build_max_turns(campaign),
                    sdk_runner=sdk_runner,
                )
        except isolation.BuildSurvivors as exc:
            raise OptimizationGateFailed(str(exc)) from exc
        if repo:
            try:
                build_scope.check(campaign, Path(repo), work_dir, _scope_before,
                                  pre_ran=sorted(test_results or {}))
            except build_scope.BuildScopeViolation as exc:
                raise OptimizationGateFailed(str(exc)) from exc
        _clean_rec = None
        if repo and _clean_base:
            try:
                _clean_rec = clean_tree.capture(
                    campaign, Path(repo), work_dir, _clean_base,
                    protected=build_scope.protected_paths(
                        Path(repo), campaign, sorted(test_results or {})),
                    base_tree_sha=_clean_tree_sha, extras_pre=_extras_pre)
            except (clean_tree.CleanTreeError, build_scope.GitError) as exc:
                raise OptimizationGateFailed(str(exc)) from exc
        # Pre-register WHICH CODE the epoch will measure. `verify` compiles the
        # policy one iteration later and stamps this hash into it; every epoch
        # iteration re-checks it (below). Snapshot here rather than at verify
        # because build is the last moment at which the tree is known to be the
        # build's own output — anything that edits the target between the two
        # stages should register as drift, not be absorbed into the baseline.
        if repo:
            _paths = _mechanism_paths(campaign)
            h = build_mod.snapshot_mechanism(
                Path(repo), work_dir, allowlist=_paths,
            )
            logger.info(
                "build: recorded mechanism.patch (%s), scope: %s",
                f"sha256 {h[:12]}" if h
                else "no hash — target is not a git work tree, so the epoch "
                     "has no drift oracle",
                ", ".join(_paths) if _paths else
                "the whole working tree (declare "
                "optimization.build_checks.mechanism_paths to scope it — "
                "otherwise any file the test or run command leaves behind that "
                "git does not ignore will read as mechanism drift)",
            )
            if _clean_rec is not None:
                # The registered mechanism IS the clean patch: the policy is
                # compiled for its hash, and the epoch measures base + patch.
                (Path(work_dir) / "mechanism.sha256").write_text(
                    _clean_rec["patch_sha256"] + "\n")
        gate_records.seal(work_dir, gate_records.BUILD_RECORDS)
    elif (repo and stage_name not in policy_mod.pre_epoch_stages(campaign)
          and exec_repo == Path(repo)):
        # ── drift oracle (spec §3.7, oracle 2) ──────────────────────────────
        #
        # A measurement is only about the system that was pre-registered. The
        # policy's `mechanism_patch_hash` names that system; if the target's
        # tree no longer hashes to it, the runs this iteration is about to
        # execute would describe DIFFERENT code while being filed under the
        # same pre-registration — the design matrix would look honoured and the
        # numbers would be about something else. There is no partial-credit
        # recovery from that, so it is a hard abort, not a warning: a warning
        # in a log the campaign author reads afterwards arrives after the
        # tokens and the runs are already spent on the wrong system.
        #
        # Keyed on the FILE's presence, not on whether `build` ran: a campaign
        # may snapshot by hand (or a previous resume may have), and either way
        # the recorded hash is a commitment. Absent file → no commitment was
        # ever made (e.g. a non-git target) → nothing to check.
        #
        # Pre-epoch stages are exempt because `verify` is where the hash is
        # stamped into the policy: "drifted since compile" is not yet meaningful
        # before the compile it refers to.
        #
        # SCOPE (Task 13.5): `mechanism_paths`, when declared, narrows what
        # counts as the mechanism. It must be the same list `snapshot_mechanism`
        # used, so both come from `_mechanism_paths`. Undeclared → whole tree,
        # which is Task 12's behaviour and its known hazard: Nous runs the
        # target's `test_command`/`run_command` with the repo as cwd, so a
        # `.pytest_cache/` or `run.log` that git does not ignore lands here as
        # "the mechanism drifted". The remedy is a declared scope, named in the
        # abort message below so the author who hits the false positive is told
        # how to fix it rather than left to distrust the oracle.
        recorded = _read_mechanism_hash(work_dir)
        if recorded:
            from orchestrator.optimize import build as build_mod

            _paths = _mechanism_paths(campaign)
            # `work_dir` is passed so Nous's own outputs (this work_dir when it
            # sits inside the target, `.nous/`, `.nous-experiments/`) are
            # excluded exactly as `snapshot_mechanism` excluded them; a hash
            # recorded before that exclusion existed is still honoured.
            _ok, current = build_mod.mechanism_hash_matches(
                Path(repo), recorded, allowlist=_paths, work_dir=Path(work_dir),
            )
            if not _ok:
                _scope = (
                    f"scope: {', '.join(_paths)}" if _paths else
                    "scope: the whole working tree — if the difference is an "
                    "artifact of the test or run command (a .pytest_cache/, a "
                    "log, a coverage file) rather than a code change, that is "
                    "a FALSE POSITIVE: gitignore it, or declare "
                    "optimization.build_checks.mechanism_paths naming only the "
                    "mechanism's own files"
                )
                raise OptimizationGateFailed(
                    f"mechanism drifted since compile: the target's working "
                    f"tree no longer matches mechanism.patch; measurements "
                    f"would describe a different system "
                    f"(recorded {recorded[:12]}, now "
                    f"{current[:12] or '<no git work tree>'}; {_scope}). Either "
                    f"restore the tree to the recorded patch, or treat the "
                    f"revision as a new experiment and start a fresh campaign — "
                    f"a revised mechanism is a new pre-registration, not a "
                    f"resumed one.",
                )

    factors = parse_factors(opt["factors"])
    response_spec = opt.get("response") or {}
    primary = (_primary_of(response_spec).get("metric")) or ""
    invariants = ((opt.get("design_space") or {}).get("invariants")) or []

    iter_dir = Path(work_dir) / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    engine = Engine(work_dir)
    gate = gate or (HumanGate(auto_response="approve") if auto_approve else HumanGate())

    # ── build: the mechanism was just authored; do NOT gate on tests here ──
    #
    # The build call already ran (above — AFTER the pre-build test run and the
    # pre-build control measurement, both of which have to observe the tree as
    # it was before the mechanism existed). This stage deliberately makes no
    # correctness judgement: the pre-build verdicts are RECORDED, never gated on,
    # because `verify` is the gate, and letting the stage that wrote the code
    # also certify it would mean the model grading its own work. Ending the
    # iteration here hands the next iteration to verify, which runs the real test
    # command against the real repo and aborts if anything the campaign declared
    # is missing or failing.
    if stage_name == Stage.PLAN.value:
        # Designs the mechanism `build` will author. No measurement, no code, and
        # never terminal — the epoch has not started, so there is no policy path
        # to have reached its end. Fails CLOSED: a plan that does not parse or
        # does not satisfy `check_plan` raises rather than letting `build` proceed
        # on a specification nobody can hold it to.
        from orchestrator.optimize import plan as plan_mod

        # ONE repair attempt, then a campaign-level abort. A rejected plan used
        # to escape as an ordinary iteration failure, after which the campaign
        # loop's next index resolved to `build` -- which then authored the
        # mechanism with NO plan, a different campaign from the one declared,
        # having discarded the paid planning call. A structural rejection is
        # usually repairable by naming the failed fields; a second rejection
        # means the target description cannot support a plan, and building
        # anyway is not an answer to that.
        try:
            plan_mod.run_plan(
                campaign, work_dir,
                iteration=iteration,
                model=model,
                max_turns=_plan_max_turns(campaign),
                sdk_runner=sdk_runner,
            )
        except plan_mod.PlanRejected as first:
            logger.warning("plan: rejected (%s); retrying once with the "
                           "rejection as feedback", first)
            try:
                plan_mod.run_plan(
                    campaign, work_dir,
                    iteration=iteration,
                    model=model,
                    max_turns=_plan_max_turns(campaign),
                    sdk_runner=sdk_runner,
                    feedback=str(first),
                )
            except plan_mod.PlanRejected as second:
                raise OptimizationGateFailed(
                    f"plan stage rejected twice; build will not run without the "
                    f"plan this campaign declares. Last rejection: {second}",
                ) from second
        _enter_phase(engine, "DESIGN", work_dir)
        _enter_phase(engine, "HUMAN_DESIGN_GATE", work_dir)
        _enter_phase(engine, "EXECUTE_ANALYZE", work_dir)
        _enter_phase(engine, "HUMAN_FINDINGS_GATE", work_dir)
        append_ledger_row(work_dir, iteration)
        return IterationOutcome.CONTINUE

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
            raise OptimizationGateFailed(_verify_abort_message(
                correctness_failures, test_run=test_run, factors=factors,
            ))
        # ── oracle 2(b)/(c): the two build claims that "tests pass" cannot make ──
        #
        # Run BEFORE the policy is compiled, deliberately. A compiled policy is
        # a pre-registration; writing one and then discovering the apparatus was
        # never actually tested (2(b)) or is not the system the control
        # describes (2(c)) would leave a signed commitment to a broken
        # experiment on disk for a later resume to pick up.
        # The build's gate records must exist and be the ones written at build
        # time; "a build ran" is decided from the campaign, not from a file the
        # build agent could delete; the records were loaded and their seals
        # verified at the top of run_stage (gate_records.load).
        #
        # `nous reanalyze` (reanalyze.py) re-derives the ANALYSIS from recorded
        # rows; these gates are measurements of the target tree and were
        # decided when the campaign ran, so a reanalysis carries their records
        # instead of re-running them.
        if not reanalysis:
            _check_tests_failed_before_build(campaign, work_dir, factors, test_results,
                                             records=_gate)
            _check_authored_tests_discriminate(campaign, work_dir, factors, iteration,
                                               records=_gate)
            _check_baseline_equivalence(campaign, work_dir, factors, config_runner,
                                        records=_gate)
            _review_build(gate, work_dir, built=_gate is not None)
            if _gate is not None:
                from orchestrator.optimize import gate_records as _gr
                # Reseal only what verify itself wrote: the build-written part
                # of baseline_equivalence.json on disk must still equal the
                # sealed in-memory copy, or target code that ran at verify
                # rewrote it (round 3, B3).
                try:
                    _gr.confirm_build_part(work_dir, _gate)
                except _gr.GateRecordError as exc:
                    raise OptimizationGateFailed(str(exc)) from exc
                _gr.seal(work_dir, ("baseline_equivalence.json", *_gr.VERIFY_RECORDS))
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
        raise OptimizationGateFailed(
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
        _primary_of(response_spec).get("direction", "maximize")
    )
    design = None
    screen_design = None
    screen_iter = None
    screen_nan = False
    if stage_name == Stage.CONFIRM.value:
        rows, payload = _confirm_rows(
            pol, work_dir, factors, primary, direction, iteration,
        )
    elif stage_name == Stage.FOLDOVER.value:
        # ── the registered foldover: a real block of runs, spent to resolve
        # ── an alias the screen showed could change the answer.
        #
        # `_close_iteration` only routes here after the screen's observations
        # said `alias_consequential` AND `foldover_affordable`, so the pairs are
        # on disk in the screen's recommendation.json.
        screen_iter = _screen_iteration(work_dir, pol)
        if screen_iter is None:
            raise OptimizationAborted(
                "foldover has no screen to fold: transitions.jsonl records no "
                "transition out of `screen`, so there is no earlier block whose "
                "aliasing this state could resolve and no response vector to "
                "combine with. The state is reachable only from screen, so this "
                "means the work_dir's transition log was truncated or the state "
                "was forced with an explicit stage=.",
            )
        pairs = [
            tuple(p) for p in
            (_read_recommendation(work_dir) or {}).get("alias_consequential") or ()
        ]
        on, fold_basis = _fold_on_basis(factors, design_cfg, pairs)
        screen_design = _build_design(factors, design_cfg, Stage.SCREEN.value)
        design = _build_design(
            factors, design_cfg, stage_name, fold_on=on,
        )
        # What the two blocks TOGETHER still alias, read off the combined
        # matrix (stage-1 M3) -- never assumed from the fold rule.
        _left = design_mod.alias_pairs(design_mod.combine(screen_design, design))
        payload = matrix.matrix_payload(
            design, factors, run_order_seed=policy_mod.run_order_seed(pol, iteration))
        rows = matrix.expand(design, factors)
        # Provenance the combined fit rests on: WHICH column was negated, and
        # WHICH iteration's runs are the other half of the response vector. A
        # reader who cannot answer both cannot reproduce the effects.json this
        # iteration writes.
        payload["folded_on"] = on
        if screen_design.groups or fold_basis == "full_fallback":
            # Mixed-level screens, and the fallback on any screen: say how the
            # block was chosen and what it leaves aliased (stage-1 M3, M12).
            payload["foldover_basis"] = fold_basis
            payload["aliases_after_combination"] = [list(p) for p in _left]
            if fold_basis == "full_fallback":
                payload["unparsed_alias_pairs"] = [list(p) for p in pairs]
        payload["screen_iteration"] = screen_iter
        payload["alias_consequential"] = [list(p) for p in pairs]
        logger.info(
            "foldover: spending %d run(s) to resolve %s by negating column %s; "
            "the combined fit will be OLS over iter-%d's screen block plus this "
            "one (%d rows total)",
            len(rows), pairs or "the recorded aliasing",
            on if on is not None else "EVERY column (full foldover)",
            screen_iter, len(screen_design.points) + len(rows),
        )
    else:
        design = _build_design(factors, design_cfg, stage_name)
        _ros = policy_mod.run_order_seed(pol, iteration)
        payload = matrix.matrix_payload(design, factors, run_order_seed=_ros)
        rows = matrix.expand(design, factors)
        _n_val = sum(1 for p in design.points if p.role == "validation")
        if _n_val:
            # WP-B B1: the validation rows are their OWN BLOCK, executed after
            # every composite row in a separately seeded order. The composite's
            # rows keep exactly the run order (and, on a target with a shared
            # noise stream, exactly the measurements) they had before
            # validation points existed; a drift between the two blocks can
            # only make the prediction check reject (the conservative side).
            _n0 = len(rows) - _n_val
            payload["run_order"] = (
                matrix.randomized_run_order(_n0, _ros)
                + [_n0 + j for j in matrix.randomized_run_order(
                    _n_val, _ros * 7919 + 1)])
            from orchestrator.optimize import adequacy as _adq

            _rcfg = design_cfg.get("refine") or {}
            payload["validation"] = {
                "rule": "seeded_greedy_maximin",
                "candidates": "coded +-0.5 on every refinable axis",
                "offset": _adq.VALIDATION_OFFSET,
                "points": _n_val,
                "seed": int(_rcfg.get("validation_seed", 0)),
                "row_indices": list(range(_n0, len(rows))),
                "held_out_of_fit": True,
                "check": "joint_predictive_F_chow_1960",
                "alpha": _adq.VALIDATION_ALPHA,
                "execution": "own block, after the composite rows",
            }

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

        prev_rec = (
            (_read_recommendation(work_dir) or {})
            if stage_name == Stage.REFINE.value else {}
        )
        prev_levels = prev_rec.get("levels")
        # ── UNDER CURVATURE, the screen's argmax is the wrong source ────────
        #
        # Refine reached on the registered CURVATURE branch
        # (`policy.CURVATURE_ACCOUNTING`) comes from a screen whose lack-of-fit
        # test rejected, and its recommendation is then biased in a NAMED way
        # for exactly the factors held here: every centre row runs a choice
        # factor at the level it is pinned to (INV-STAT14 fits the level it
        # ran), so the centre-vs-corner curvature contrast is credited to that
        # level's main effect. Measured on `SURFACES["bowl_centred"]`: the
        # screen recommended C="off" (the centre rows' level) although C="on" is
        # +1.0 everywhere, refine held C at "off", and the campaign certified a
        # point 1.0 below the optimum.
        #
        # The corners are the part of the design that a level-INDEPENDENT
        # curvature does not bias: on
        # a 2-level fraction every pure quadratic column equals the intercept
        # there, and the fraction is balanced, so each held factor's marginal
        # mean over the complete CORNER rows estimates its main effect free of
        # curvature -- which is also the right criterion at the refine design's
        # centre, where every interaction with a refined factor vanishes.
        centre_confounded: dict = {}
        _held_barred = _barred_levels(work_dir)
        basis = {f.id: ("screen_recommendation"
                        if prev_levels and f.id in prev_levels else "first_level")
                 for f in held}
        if prev_rec and prev_rec.get("model_adequate") is False:
            corner_best = _corner_marginal_best(
                work_dir, prev_rec.get("iteration"), [f.id for f in held],
                primary, direction, barred=_held_barred,
            )
            if corner_best:
                logger.info(
                    "refine: the screen's model was inadequate (lack of fit), so "
                    "held factor(s) take their best CORNER marginal level, which "
                    "a level-INDEPENDENT curvature does not bias, instead of the "
                    "screen argmax: %s",
                    corner_best,
                )
                prev_levels = {**(prev_levels or {}), **corner_best}
                basis.update({fid: "corner_marginal" for fid in corner_best})
            # ── a CHOICE factor: its centre-point means, when every level has one ──
            #
            # The corner marginal is unbiased by curvature only when curvature
            # does not depend on the level. When it does -- the very case the
            # cycled centre points exist to detect (spec 2026-10-16, feature 3;
            # `curvature_under_second_level`: C=on is a bowl reading 11.1 at the
            # corners and 16 at the centre, C=off is flat at 15) -- the corners
            # make the curved level look WORSE, and refine would be spent on the
            # flat branch. The centre-point mean at each level estimates the
            # response AT REFINE'S DESIGN CENTRE under that level
            # (the point the CCD is built around) -- but ONLY when nothing else
            # moves with it (stage-1 M2):
            #   * with two or more choice factors held, the diagonal centre
            #     assignment moves their levels TOGETHER ((off,off), (on,on)),
            #     so one factor's centre mean carries the other's effect;
            #   * a held NUMERIC that refine runs away from its centre (a
            #     two-level numeric held at an edge) changes the response the
            #     centre means were measured at, through any interaction.
            # In either case the corner rule stands, and the confounding
            # factors are recorded (held_fixed_basis, centre_mean_confounded_with).
            held_choice = [f for f in held if f.type == "choice"]
            off_centre = []
            for f in held:
                if f.type == "choice":
                    continue
                lv = (prev_levels or {}).get(f.id, f.levels[0])
                try:
                    mid = decode_coded(f, 0.0)
                except (TypeError, ValueError):
                    mid = None
                if mid is None or lv != mid:
                    off_centre.append(f.id)
            confounded = ([f.id for f in held_choice[1:]] if len(held_choice) > 1
                          else []) + off_centre
            if held_choice and confounded:
                centre_confounded = {f.id: sorted(
                    [g.id for g in held_choice if g.id != f.id] + off_centre)
                    for f in held_choice}
                logger.info(
                    "refine: the centre-mean rule is NOT used for held choice "
                    "factor(s) %s -- their centre means are confounded with %s "
                    "(other held choice factors move with them in the diagonal "
                    "assignment, or a held numeric runs off-centre); the corner "
                    "rule stands.", [f.id for f in held_choice], confounded)
                centre_best = {}
            else:
                centre_best = _centre_mean_best(
                    work_dir, prev_rec.get("iteration"), held_choice,
                    primary, direction, barred=_held_barred,
                )
            if centre_best:
                logger.info(
                    "refine: every level of the held choice factor %s was measured "
                    "at the screen's centre and nothing else held moves with it, "
                    "so it is held at its best CENTRE-POINT mean (the response at "
                    "refine's design centre under that level): %s",
                    sorted(centre_best), centre_best,
                )
                prev_levels = {**(prev_levels or {}), **centre_best}
                basis.update({fid: "centre_mean" for fid in centre_best})
        fixed = {
            f.id: (
                prev_levels[f.id]
                if prev_levels and f.id in prev_levels
                # first_level fallback: the first level the bar allows (Q1)
                else next((lv for lv in f.levels
                           if lv not in _held_barred.get(f.id, ())), f.levels[0])
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
            # Where each held level came from -- recorded whenever a CHOICE
            # factor is held (the case the centre-mean rule can change), so a
            # campaign with only numeric held factors is byte-identical.
            if any(f.type == "choice" for f in held if f.id in fixed):
                payload["held_fixed_basis"] = {fid: basis[fid] for fid in fixed}
                if centre_confounded:
                    payload["centre_mean_confounded_with"] = centre_confounded
            payload["rows"] = [
                {**row, "levels": {**fixed, **dict(row.get("levels") or {})}}
                for row in payload.get("rows", [])
            ]

    # ── WP-B B4: reuse the screen's cube and centre rows (opt-in) ──────────
    # Sequential assembly with a block term (Box & Draper 2007, ch. 15):
    # refine's cube corners that the screen already measured at exactly these
    # levels are NOT re-run; the screen's matching centre rows join as extra
    # block-1 centres, so each block keeps its own centres and the block
    # (drift) effect is estimable. See `_screen_reuse` for every guard.
    stage_reuse: dict = {}
    if stage_name == Stage.REFINE.value and rows and bool(
            (design_cfg.get("refine") or {}).get("reuse_screen", False)):
        design, rows, payload, stage_reuse = _screen_reuse(
            work_dir, pol, design, rows, payload, factors)

    # ── the workload seed: last thing added to a row, before anything is written ──
    #
    # HERE, not inside `_confirm_rows` / the design branches, and not after the
    # DESIGN phase guard. The rows are final at this point (the held-fixed merge
    # above rewrites `apply` wholesale via `render_apply`, which would discard an
    # env added earlier), and the seed must be in the payload that
    # `write_design_matrix` pre-registers — a seed decided after the matrix was
    # registered is not a pre-registered seed.
    #
    # Outside the `_enter_phase` guard on purpose: that guard is False on a
    # RESUMED iteration whose design_matrix.json already exists, and the rows
    # still have to execute with their seeds. Skipping the assignment there would
    # silently run a resumed confirm round unpaired while `paired: True` sat in
    # the artifact from the first attempt.
    rows, payload = _assign_workload_seeds(
        rows, payload, pol,
        iteration=iteration, confirm=stage_name == Stage.CONFIRM.value,
    )
    if stage_reuse and "workload_seeds" in payload:
        # A reused row is the screen's measurement, under the SCREEN's
        # registered seed: record that seed, not one this stage never ran.
        _ws = dict(payload["workload_seeds"])
        for _ri, _src in stage_reuse["rows"].items():
            if _src.get("seed") is not None:
                _ws[str(_ri)] = _src["seed"]
        payload = {**payload, "workload_seeds": _ws}

    # ── row reuse across a retried iteration ─────────────────────────────────
    #
    # A failed iteration records no transition, so `current_state` still returns
    # the state it was on and THIS iteration legitimately re-registers the same
    # design. That is correct; what was wrong is that it re-MEASURED everything.
    # On a real campaign 15 valid rows were re-run four times, which was most of
    # a 14-hour campaign that produced nothing.
    #
    # WHY THE PRIOR ATTEMPT'S DRAWS ARE CARRIED FORWARD rather than the rows
    # being matched against this attempt's freshly-derived design: seeds come
    # from `run_order_seed`, which is the ITERATION, so iteration 4 row 0 and
    # iteration 5 row 0 carry DIFFERENT workload seeds. Matching on levels alone
    # would substitute one experiment's randomness for another's — a stale
    # measurement resurrected, which is worse than re-measuring. So the previous
    # attempt's registered design (seeds included) becomes this attempt's
    # pre-registration, and a row is reused only when it is a measurement of
    # exactly what this attempt registers. See `resume`'s module docstring for
    # the full validity argument and the six guards.
    #
    # NOT A STAGE DECISION. Nothing here chooses what runs next; the stage was
    # already resolved by the compiled policy above. This only changes which of
    # THIS stage's rows have to be measured again.
    # NOT AT CONFIRM, ever. Terminal discrimination's claim is that the
    # finalist comparison rests on FRESH measurements rather than on the fitted
    # surface, and a second round is spent precisely because the first did not
    # discriminate — so repeating its workload could not help (spec §3.8). Its
    # paired bound also zips replicates that must share a workload draw, which a
    # mix of reused and fresh rows would break. `carry_forward_payload` refuses
    # `shortlist_replicate` on both sides as well; this is the same rule stated
    # at the call site so a reader of the epoch's flow sees it here too.
    _reuse_plan = None
    if (_reuse_enabled(opt) and stage_name != Stage.CONFIRM.value
            and _enter_phase_pending(engine, work_dir)):
        _prior = _prior_attempt_matrix(work_dir, iteration, stage_name)
        if _prior is not None:
            _carried = resume.carry_forward_payload(_prior, payload)
            if _carried is not None:
                _carried["policy_hash"] = policy_mod.policy_hash(pol)
                _reuse_plan = resume.plan_reuse(
                    work_dir, iter_dir=iter_dir, payload=_carried,
                    policy_hash=policy_mod.policy_hash(pol),
                    epoch=int(pol.get("epoch", 1)),
                )
                if _reuse_plan.rows:
                    payload = _carried
                    # Re-derive the ConfigRow list from the carried payload so
                    # the rows that still EXECUTE carry the carried-forward
                    # seeds, not the ones this iteration would have derived.
                    rows = _rows_from_payload(rows, payload)
                    logger.info(
                        "%s: reusing %d of %d row(s) measured at iter-%s under "
                        "the same pre-registration (%.1f min of measurement "
                        "not repeated); %d row(s) still to measure",
                        stage_name, _reuse_plan.reused_count, len(payload["rows"]),
                        _reuse_plan.source_iteration,
                        _reuse_plan.saved_ms / 60000.0,
                        len(_reuse_plan.pending_indices),
                    )
                elif _reuse_plan.refused:
                    logger.info(
                        "%s: re-measuring every row — reuse refused: %s",
                        stage_name, _reuse_plan.refused,
                    )

    # Resolved OUTSIDE the DESIGN guard for the same reason the seeds are: the
    # guard is False on a resumed iteration whose design_matrix.json already
    # exists, and those rows still have to execute under a bound. Recomputing it
    # from the same campaign and the same stage name is deterministic, so a
    # resumed stage runs at the concurrency its already-written matrix records.
    # The contention-floor probe is what can lift a SPENDING stage above 1, and
    # it is a MEASUREMENT, so it runs here -- before the matrix is written, since
    # the width it licenses is part of the pre-registration. Skipped entirely
    # unless the campaign named a probe corner and asked for a width, so a
    # campaign that declares nothing pays nothing and runs exactly as before. A
    # `load_independent` declaration needs no probe at all and does not enter
    # here; `concurrency.resolve` honours it directly.
    measured = None
    if (stage_name != Stage.CONFIRM.value
            and concurrency.contention_probe_levels(opt)
            and concurrency.declared_width(opt) > 1
            and config_runner is not None):
        measured = _measure_contention_floor(
            opt, factors, config_runner,
            width=min(concurrency.declared_width(opt),
                      concurrency.cpu_ceiling()),
        )
        logger.info(
            "%s: contention floor %s -- %s", stage_name,
            "CERTIFIED" if measured.basis == concurrency.BASIS_CONTENTION_FLOOR
            else "NOT certified", measured.detail,
        )
    conc = resolve_concurrency(opt, stage_name=stage_name, measured=measured)
    max_parallel = conc.width

    if _enter_phase(engine, "DESIGN", work_dir):
        _preflight_design(rows, factors, opt, iter_dir)
        # Provenance: every matrix materialised inside the epoch cites the
        # policy that scheduled it, so a reader can check that this design was
        # produced under the policy that was pre-registered and not a later one.
        payload["policy_hash"] = policy_mod.policy_hash(pol)
        # ... and the ceiling every row of it was measured under. Recorded even
        # when the campaign declared nothing, because "the author did not choose"
        # and "the author chose 600" produce the same runs, and a reader of a
        # `failed` row whose error says "timed out after 600 seconds" should not
        # have to know which release of Nous wrote it to learn whether that
        # ceiling was intentional. Same convention as `workload_seeds`: a
        # resolved run parameter that shaped the measurement belongs on the
        # pre-registration, not only in the campaign file that may since have
        # been revised for the next epoch.
        payload["run_timeout_sec"] = resolve_run_timeout(opt)
        # ... and the CONCURRENCY those rows were measured under, recorded beside
        # `run_order` / `run_order_seed` because it is what says how to READ them.
        # A pre-registration that claims a randomized run order while executing
        # rows concurrently is asserting a guarantee it did not provide: the
        # randomization defuses a TIME trend, and co-scheduling introduces a
        # NEIGHBOUR effect that no permutation of the same rows can average away.
        # That is the same defect class as the run-order bug fixed just below --
        # an artifact recording a randomization that never happened -- and it is
        # invisible without this field, because a `run_order` permutation looks
        # identical whether it described a sequence or a schedule. The EFFECTIVE
        # value is recorded, not the declared one: `resolve_max_parallel` returns
        # 1 at every spending stage regardless of the campaign, so a screen matrix
        # saying 1 under a campaign declaring 4 is the artifact being accurate
        # about what ran rather than echoing an intention.
        payload["max_parallel"] = max_parallel
        # ... and WHY that width was allowed. The width alone is not readable:
        # `max_parallel: 4` cannot be distinguished by a reader from the
        # asymmetric-neighbour confound it is only sometimes safe against, so
        # the basis travels with it. `serial` is what every campaign authored
        # before `concurrency` existed records.
        payload["concurrency_basis"] = conc.basis
        # The evidence's width, when the basis rests on evidence. A floor
        # measured at 2 does not license 8, so a reader has to be able to check
        # the certificate covers the schedule that ran.
        if conc.certified_width is not None:
            payload["concurrency_certified_width"] = conc.certified_width
        if conc.detail:
            payload["concurrency_detail"] = conc.detail
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

    # Reused rows are appended to THIS iteration's runs.jsonl and dropped from
    # the execution list. Appending them (rather than reading them from the old
    # directory at fit time) is what keeps every existing downstream consumer
    # working unchanged: `check_fidelity` requires one run per planned row in
    # THIS iteration's log, `_best_observed` and the infeasible-region reader
    # glob `runs/iter-*/runs.jsonl`, and the fit pairs response *i* with design
    # point *i*. Each carries `reused_from`, so the log distinguishes a carried
    # measurement from a fresh one.
    _reused_rows: list[dict] = []
    if _reuse_plan is not None and _reuse_plan.rows:
        _pending = set(_reuse_plan.pending_indices)
        _reused_rows = list(_reuse_plan.rows)
        for _row in _reused_rows:
            artifacts.append_run(iter_dir, _row)
        exec_rows = [r for r in exec_rows if r.row_index in _pending]
        resume.write_manifest(iter_dir, _reuse_plan.manifest(
            iteration=iteration, epoch=int(pol.get("epoch", 1)),
            policy_hash=policy_mod.policy_hash(pol),
        ))
    elif _reuse_plan is not None:
        resume.write_manifest(iter_dir, _reuse_plan.manifest(
            iteration=iteration, epoch=int(pol.get("epoch", 1)),
            policy_hash=policy_mod.policy_hash(pol),
        ))

    if stage_reuse:
        # Appended to THIS iteration's runs.jsonl like a retry-reused row, with
        # `reused_from` naming the screen row that paid for it; never executed.
        _epoch = int(pol.get("epoch", 1))
        _already = {int(r.get("row_index", -1)) for r in _reused_rows}
        for _ri, _src in sorted(stage_reuse["rows"].items()):
            if int(_ri) in _already:
                continue        # a retry already carried this row forward
            _row = {k: v for k, v in _src["row"].items() if k != "reused_from"}
            _row["row_index"] = int(_ri)
            _row["reused_from"] = {"iteration": int(stage_reuse["from_iteration"]),
                                   "epoch": _epoch, "row_index": int(_src["row_index"]),
                                   "stage": Stage.SCREEN.value}
            artifacts.append_run(iter_dir, _row)
            _reused_rows.append(_row)
        _skip = set(int(i) for i in stage_reuse["rows"])
        exec_rows = [r for r in exec_rows if r.row_index not in _skip]
        logger.info(
            "refine: reusing %d screen row(s) from iter-%d as block 1 (cube corners "
            "+ centres); %d row(s) to measure. Block term fitted (drift check).",
            len(_skip), stage_reuse["from_iteration"], len(exec_rows))

    if max_parallel > 1:
        logger.info(
            "%s: executing replicate blocks at up to %d simultaneous run(s); "
            "blocks remain a barrier, so every finalist is measured once before "
            "any is measured twice, and contention inside a block is symmetric "
            "across exactly the finalists being compared", stage_name,
            max_parallel,
        )

    # The three target-adapter guards, armed for every measuring stage of the
    # epoch. Epoch-scoped rather than iteration-scoped, and that is the point:
    # `adapter_contract.json` lives at the work-dir root, so the contract
    # captured at `screen` is the one `refine` and `confirm` are checked
    # against. An adapter edited between two iterations of one epoch is exactly
    # the defect this closes, and an iteration-scoped fingerprint would see
    # nothing.
    adapter_guard = runner.AdapterGuard(
        work_dir, epoch=_epoch_index(work_dir), stage=stage_name,
        self_check=(response_spec.get("self_check") or []),
        constant_fields=set(response_spec.get("constant_fields") or ()),
    )

    # The fourth hard-fail: a measured row whose observation contradicts a
    # `locked_parameters` value at its declared `locked_observables` path
    # (orchestrator/optimize/locked.py). Checked in `on_row`, AFTER the row is
    # appended, so the row that exposed the deviation is on disk as evidence --
    # the same "rows already written stay" property contract drift relies on.
    # It fires on the first offending row rather than after the sweep, because
    # every further row would spend budget on an experiment nobody registered.
    def _record_row(outcome) -> None:
        artifacts.append_run(iter_dir, _run_row(by_index[outcome.row_index], outcome))
        locked_mod.check_row(campaign, outcome.response,
                             row_index=outcome.row_index, stage=stage_name)

    try:
        outcomes = runner.execute_design(
            exec_rows, runner=config_runner, response_spec=response_spec,
            invariants=invariants, factors=factors,
            integrity_check=integrity_check,
            max_parallel=max_parallel,
            adapter_guard=adapter_guard,
            on_row=_record_row,
        )
    except locked_mod.LockedParameterDeviation as exc:
        # A campaign-level abort for the same reason as contract drift below:
        # there is no row-level repair, and no surface to certify.
        raise OptimizationGateFailed(str(exc)) from exc
    except adapter_contract.AdapterContractDrift as exc:
        # Converted here so it lands on exactly the path a `policy.sha256`
        # mismatch does: a campaign-level hard abort, not a row failure and not a
        # semantic exception. A semantic exception would be wrong -- that branch
        # ends the epoch and still returns an action from the fitted surface,
        # and here the surface is fitted over rows measured by two different
        # instruments, so there is no action to certify. The rows already written
        # to runs.jsonl stay on disk (append-only), which is what lets an author
        # see which rows preceded the change.
        raise OptimizationGateFailed(str(exc)) from exc
    # The measurement batch ran target code in the clean tree: check the tree
    # right after it, so a batch that modified what it measured fails THIS
    # iteration rather than the next one (round 3, A4).
    _check_survivors(work_dir, iteration, f"{stage_name} measurement batch")
    _check_clean_tree_after(campaign, work_dir, f"{stage_name} measurement batch")

    # Restore DESIGN order before anything reads these positionally.
    # `_fitting_responses` walks `outcomes` in sequence and `fit_effects` pairs
    # value i with `design.points[i]`, so leaving them in execution order would
    # misalign every response with its design row and produce silently wrong
    # coefficients — far worse than the provenance gap that motivated
    # randomizing execution in the first place. runs.jsonl still records the
    # true execution sequence, because `on_row` fires as each row completes.
    # Reused rows re-enter the outcome list BEFORE the ordering is restored, as
    # `RunOutcome`s reconstituted from the log rows that were carried forward.
    # They have to be here, not merged later: everything downstream — the NaN
    # guard, `_fitting_responses`, `fit_effects`' positional pairing, the
    # exclusion accounting — reads `outcomes`, and a reused row that reached the
    # log but not this list would be a planned row the fit silently never saw,
    # which is the same class of defect as the NaN poisoning (spec §4 D2).
    if _reused_rows:
        outcomes = list(outcomes) + [
            _outcome_from_run_row(row) for row in _reused_rows
        ]

    if exec_rows is not rows or _reused_rows:
        pos = {r.row_index: i for i, r in enumerate(rows)}
        outcomes = sorted(
            outcomes, key=lambda o: pos.get(o.row_index, len(rows)),
        )

    # A `load_independent` declaration is an author CLAIM Nous cannot verify up
    # front without spending the runs the claim exists to save -- but the rows
    # just measured can CONTRADICT it, for free. Reported rather than aborted:
    # replicated identical rows are not guaranteed to exist in a screen design
    # (so silence is common and is not evidence of a violation), and by the time
    # these rows exist the runs are already spent, so aborting would destroy the
    # data that proves the problem instead of surfacing it for the next epoch.
    if concurrency.declared_load_independent(opt):
        contradiction = concurrency.falsify_load_independence(
            artifacts.read_runs(iter_dir),
            metric=(_primary_of(response_spec).get("metric") or ""),
        )
        if contradiction:
            logger.warning("%s: %s", stage_name, contradiction)

    # Fidelity: what ran must match what was pre-registered. Hard-fails
    # even under auto-approve — the #246 discipline extended to the matrix.
    violations = matrix.check_fidelity(payload, artifacts.read_runs(iter_dir))
    if violations:
        raise OptimizationGateFailed(
            "executed configurations deviate from the pre-registered "
            "design_matrix.json:\n  " + "\n  ".join(violations),
        )

    # ── a NaN on a COMPLETE row is a semantic exception, not a fit input ────
    #
    # BEFORE `_fitting_responses`, deliberately, and this ordering is the whole
    # fix. That function's guard raises `OptimizationAborted` on exactly these
    # rows — correctly, since fitting on them NaN-poisons every coefficient —
    # but an abort ends the CAMPAIGN with no report at all, and the paper's rule
    # is that this condition ends the EPOCH and still returns an action. Routing
    # it to the policy's registered `nan_response -> exception` branch is what
    # makes the difference; reaching `_fitting_responses` at all would already be
    # the wrong outcome, so the check cannot live inside it.
    #
    # `status == "complete"` is load-bearing and is what separates this from
    # `_fitting_responses`'s remaining raise conditions. A row the target ran to
    # completion that reports a non-numeric primary metric is a SEMANTIC defect:
    # the campaign's objective and the target's instrumentation disagree about
    # what is measurable at that point, and no re-run repairs it (the target will
    # report NaN there again). An `infeasible` / `rejected` row is the opposite —
    # a trustworthy measurement of an inadmissible configuration, real
    # information about the design space (spec §6.4) — and a row that never
    # completed at all is a MEASUREMENT failure a re-run can fix. Neither routes
    # here; both keep their existing handling (excluded from the fit by carrying
    # NaN, and `_fitting_responses`'s unmeasured guard respectively).
    #
    # Note that `float(raw) != float(raw)` is not the test used: `raw` may be the
    # string "nan" or a structure, and those are `_fitting_responses`'s
    # non-numeric raise — an instrumentation mismatch rather than a measured NaN.
    # `_primary_is_nan` accepts only a genuine float NaN.
    nan_rows = [
        o.row_index for o in outcomes
        if getattr(o, "status", None) == "complete" and (
            _primary_is_nan(o, primary)
            # Multi-objective: ANY objective NaN on a complete row (spec step 2).
            or pareto_stage.nan_on_complete(o, pareto_stage.objectives(pol)))
    ]
    if nan_rows:
        logger.warning(
            "%s: %d row(s) ran to completion but reported a non-numeric %r "
            "(row_index %s). That is a SEMANTIC exception, not a datum: the "
            "objective and the target's instrumentation disagree about what is "
            "measurable there, and no re-measurement inside this epoch repairs "
            "it. Routing to the policy's nan_response branch WITHOUT fitting — "
            "fitting on these rows would NaN-poison every coefficient while "
            "still producing schema-valid artifacts.",
            stage_name, len(nan_rows), primary, nan_rows,
        )
        _write_json(iter_dir / "findings.json", _nan_findings(
            stage_name, iteration, primary, nan_rows, len(outcomes),
        ))
        # A BARE LIST on disk, as everywhere else in this module:
        # `iteration._merge_principles` raises on a dict. Empty because a NaN
        # response supports no principle about the factors — the epoch ended
        # before any effect was estimated, and inventing a principle from an
        # unfitted stage is the aspirational-platitude failure `validate_evidence`
        # exists to reject.
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
        return _close_iteration(
            engine, campaign, work_dir, iter_dir, iteration, stage_name, pol,
            {
                "correctness_failed": False,
                "nan_response": True,
                "budget_remaining": _budget_remaining(pol, work_dir),
                # No fit ran, so there is no bound and no round to report. `step`
                # treats a missing key as unknown (never a match), and the
                # nan_response guard is registered FIRST out of every spending
                # state, so nothing else can be reached from here — but state the
                # facts that ARE known rather than leaving the row silent about
                # them.
                "round": 0,
                "certified": False,
            },
            recommendation_levels=None,
        )

    ys = _fitting_responses(outcomes, response_spec, primary)

    # ── WP-B B1: the validation block is HELD OUT of the fit ────────────────
    # It is appended last, so the fit sees exactly the composite it saw before
    # validation points existed; the held-out rows are checked against the
    # fitted model after the fit (`adequacy.prediction_check`).
    val_rows: list = []
    val_outcomes: list = []
    val_ys: list = []
    fit_blocks = (list((payload.get("stage_reuse") or {}).get("block") or [])
                  or None)
    if stage_name == Stage.REFINE.value and any(
            p.role == "validation" for p in design.points):
        _vi = [i for i, p in enumerate(design.points) if p.role == "validation"]
        _ki = [i for i, p in enumerate(design.points) if p.role != "validation"]
        _outs = list(outcomes)
        val_rows = [rows[i] for i in _vi]
        val_outcomes = [_outs[i] for i in _vi]
        val_ys = [ys[i] for i in _vi]
        import dataclasses as _dc

        design = _dc.replace(design, points=tuple(design.points[i] for i in _ki))
        rows = [rows[i] for i in _ki]
        outcomes = [_outs[i] for i in _ki]
        ys = [ys[i] for i in _ki]
        if fit_blocks:
            fit_blocks = [fit_blocks[i] for i in _ki]

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

    # ── the combined fit: screen ∪ foldover, in that order ────────────────
    #
    # This is where the spent runs BUY something. The fold block alone is just
    # another fractional design with the same aliasing; what resolves the alias
    # is the two blocks TOGETHER, because the fold's sign flip breaks the
    # defining word that made the two columns coincide. Verified on
    # `fractional_factorial("ABCD", 4)`: `alias_pairs(combine(screen, fold))` is
    # empty and all six two-factor interactions come back separately estimable,
    # where the screen alone could only estimate three.
    #
    # ORDER IS LOAD-BEARING. `combine` concatenates screen-then-fold and
    # `fit_effects` pairs response `i` with `points[i]`, so the response vector
    # must be assembled the same way round. Getting it backwards would misalign
    # every coefficient and still return a plausible-looking Fit.
    #
    # `nan_response` for the SCREEN half is checked here rather than left to the
    # per-row guard below: the combined fit rests on both blocks, and a screen
    # row that never measured means the combined design is not the design whose
    # alias structure was just reasoned about.
    fold_n = len(ys)
    # Positions of an earlier block's rows that PRECEDE this iteration's in
    # `ys` (foldover's screen block). None reads the whole block in order.
    prefix_indices = None
    if stage_name == Stage.FOLDOVER.value:
        screen_ys, screen_nan = _screen_responses(
            work_dir, screen_iter, primary, len(screen_design.points),
        )
        if screen_nan:
            logger.warning(
                "foldover: iter-%d's screen block has %d row(s) with no usable "
                "measurement, so the combined fit cannot be formed over the "
                "design whose aliasing this block was spent to resolve. Routing "
                "to the policy's nan_response branch.",
                screen_iter, sum(1 for v in screen_ys if v != v),
            )
        design = design_mod.combine(screen_design, design)
        ys = screen_ys + list(ys)
        logger.info(
            "foldover: combined fit over %d screen + %d foldover row(s); "
            "aliasing after combination: %s",
            len(screen_ys), fold_n,
            [list(p) for p in design_mod.alias_pairs(design)] or "none",
        )

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
    # THE FLOORS, AND WHY THERE ARE THREE OF THEM.
    #
    #   (a) ARITHMETIC. Fewer than two retained rows cannot support a fit at all,
    #       whatever the columns look like.
    #   (b) IDENTIFIABILITY. `len(keep) >= 2` says the normal equations have rows;
    #       it says nothing about whether any given COEFFICIENT is estimable. A
    #       factor every one of whose retained rows sits at one level has a
    #       CONSTANT column in the reduced model matrix, collinear with the
    #       intercept — `_solve_normal_equations` then raises "design matrix is
    #       singular", and the campaign dies at the fit with a message about
    #       matrix rank instead of about the factor that lost a level.
    #   (c) RANK. (b) is necessary and NOT sufficient, and this was found by
    #       MUTATION TESTING rather than by design. A subset can retain two
    #       distinct levels of every factor — so (b) passes — and still be
    #       rank-deficient for the model `fit_effects` actually builds, because
    #       that model also carries every two-factor interaction. Measured on the
    #       2^3 screen with corners 3 and 5 excluded: A, B and C each keep three
    #       levels, and the seven-term model (intercept + 3 mains + 3
    #       interactions) has rank 6 over the six surviving corners.
    #
    # (b) DROPS the factor and (c) DROPS the interaction block rather than
    # aborting. Aborting would discard every surviving coefficient to protect one
    # that was never estimable — the "throw away the 15 valid measurements"
    # behaviour this whole path exists to end. Each loss is named in
    # `fit_exclusions.json` and visible in `recommendation.json`'s `fitted_ids`,
    # so it is loud rather than silent. Aborting IS still correct when NOTHING is
    # estimable: there is then no model to fit.
    #
    # Dropping a factor also narrows the ALIAS CLASSES: `fit_effects` collapses
    # interaction columns per class over the design it is handed, so `fitted_ids`
    # is recomputed from the identifiability verdict rather than patched
    # afterwards — that function derives everything, including which interactions
    # are separately estimable, from the (design, factor_ids) pair it receives.
    import dataclasses

    design_for_fit, ys_for_fit = design, ys
    dropped = [i for i, v in enumerate(ys) if v != v]
    keep = [i for i, v in enumerate(ys) if v == v]
    # Levels per POSITION in `ys`, which is what the exclusion analysis and the
    # identifiability floor both index by. At foldover `ys` has the screen
    # block's responses prepended, so positions do not map to this iteration's
    # `row_index` — the screen half's levels are read back from its own
    # runs.jsonl. Getting this wrong would attribute the fold block's levels to
    # the screen block's exclusions and analyse the wrong table.
    levels_by_pos = _fit_row_levels(
        work_dir, rows, outcomes, stage_name, screen_iter,
        n_total=len(ys), n_fold=fold_n, prefix_indices=prefix_indices,
    )
    excluded_reasons = _fit_exclusion_reasons(
        outcomes, stage_name, dropped, n_total=len(ys), n_fold=fold_n,
        work_dir=work_dir, screen_iter=screen_iter, prefix_indices=prefix_indices,
    )
    # ── a categorical level measured ONLY at centre rows (stage-1b N3) ──────
    #
    # When every CORNER run at a level failed but a centre row at it measured,
    # that level is estimable only through the centre rows -- i.e. from the
    # centre-vs-corner contrast, which is curvature: the M1 defect, silently.
    # Its centre rows are therefore left out of the fit (reason
    # "level_lost_at_corners") and the level is LOST like any other.
    lost_at_corners: dict = {}
    if design.groups:
        from orchestrator.optimize.factors import is_categorical as _is_cat

        _dropped0 = set(dropped)
        _kept0 = [i for i in range(len(ys)) if i not in _dropped0]
        _marked: set = set()
        for f in factors:
            if not _is_cat(f) or f.id not in set(fitted_ids):
                continue
            corner_seen = {json.dumps((levels_by_pos[i] or {}).get(f.id)) for i in _kept0
                           if design.points[i].role != "center" and levels_by_pos[i]}
            hits = [i for i in _kept0 if design.points[i].role == "center"
                    and levels_by_pos[i]
                    and json.dumps(levels_by_pos[i].get(f.id)) not in corner_seen]
            if hits:
                lost_at_corners[f.id] = sorted(
                    {json.dumps(levels_by_pos[i][f.id]) for i in hits})
                lost_at_corners[f.id] = [json.loads(v) for v in lost_at_corners[f.id]]
                _marked |= set(hits)
        if _marked:
            logger.warning(
                "%s: categorical level(s) %s were measured only at CENTRE rows "
                "(every corner run at them failed); those centre rows are left out "
                "of the fit and the level(s) treated as lost, since they could be "
                "estimated only from curvature.", stage_name, lost_at_corners)
            dropped = sorted(_dropped0 | _marked)
            keep = [i for i in range(len(ys)) if i not in set(dropped)]
            for i in _marked:
                excluded_reasons[i] = "level_lost_at_corners"
    # ── INV-STAT14: fit the coordinates that RAN, not the ones planned ──────
    #
    # `design` is the pre-registered plan (what `design_matrix.json` records and
    # `check_fidelity` holds the runs to). Two of its coordinates are not what
    # ran: a clamped axial point runs at the range edge, and a choice factor's
    # centre row runs at its first level. Regressing on the plan is an
    # errors-in-variables bias -- measured on the oracle, a truly linear surface
    # on a clamped CCD failed lack of fit on every seed, and `additive` (linear,
    # with a choice factor) failed it at screen on every seed. So every fitting
    # stage (screen, foldover, refine) and the constraint models below are fitted
    # on `coded_as_run`, and `effects.json["fit_coordinates"]` records both
    # codings per fitted row. See `matrix.coded_as_run` for the choice-centre
    # decision.
    design_run, nominal_pos = matrix.coded_as_run(design, factors, levels_by_pos)
    _unrecoded = sorted(set(nominal_pos) - set(dropped))
    if _unrecoded:
        raise OptimizationAborted(
            f"{stage_name}: fitted position(s) {_unrecoded} have no recorded "
            f"level for every factor in {list(design.factor_ids)}, so the fit "
            f"cannot be coded from the levels that actually ran. That is an "
            f"inconsistency between the design and runs.jsonl, not a datum.",
        )
    design_for_fit = design_run
    # Third element: is this exclusion BIAS-RELEVANT? Only a row that was
    # admissible-but-unmeasurable leaves a hole in X_valid that can bias a
    # coefficient. An `infeasible` row is not missing information — it IS
    # information, namely that the point is outside X_valid — and a constrained
    # design has every inadmissible corner on one level of one factor by
    # construction (measured on SURFACES["sla"] before INV-STAT15 fitted them:
    # both exclusions at A=16, a perfect concentration meaning only "the p99
    # ceiling binds at high A"). Counting those as bias would flag every constrained campaign and be
    # wrong about all of them. `rejected` is grouped with `infeasible` for the
    # conservative reason the exclusions module states.
    _bias_reasons = {"failed_to_measure", "no_metric"}
    _dropped_set = set(dropped)
    balance = exclusions.analyse(
        [
            (levels_by_pos[i], i in _dropped_set,
             excluded_reasons.get(i) in _bias_reasons)
            for i in range(len(ys))
        ],
        fitted_ids,
    )
    non_identifiable_held: dict = {}
    interactions_dropped = False
    if dropped:
        if len(keep) < 2:
            raise OptimizationAborted(
                f"only {len(keep)} of {len(ys)} rows produced a usable "
                f"measurement, which cannot support a fit. Re-run the failed "
                f"configurations before fitting.",
            )
        ident = exclusions.identifiable_factors(
            [levels_by_pos[i] for i in keep], fitted_ids,
        )
        if not ident.estimable:
            raise OptimizationAborted(
                f"{len(keep)} of {len(ys)} rows were retained, but NO factor "
                f"retains two distinct levels among them "
                f"({ident.levels_retained}), so no coefficient is identifiable "
                f"and there is no model to fit. Re-run the excluded "
                f"configurations, or narrow the design to the region that "
                f"measures.",
            )
        if ident.dropped:
            logger.warning(
                "%s: factor(s) %s lost every row at all but one level "
                "(retained levels %s) and are NOT identifiable from the "
                "retained subset. Dropping them from the fitted set rather "
                "than aborting — a non-identifiable coefficient must not be "
                "estimated, and discarding the %d measurable row(s) to protect "
                "it would lose every other coefficient too. "
                "fit_exclusions.json names them and recommendation.json's "
                "fitted_ids omits them.",
                stage_name, list(ident.dropped),
                {k: list(v) for k, v in ident.levels_retained.items()
                 if k in set(ident.dropped)},
                len(keep),
            )
            fitted_ids = tuple(ident.estimable)
            # The FACTOR of each fit column (a categorical owns several).
            _owner_run = design_run.groups or design_run.factor_ids
            # A dropped factor is not "varied but unfitted": every retained row
            # sits at one level of it, so pin it there for the argmax. Reading
            # the level off the retained rows rather than off the baseline keeps
            # `held_fixed` describing what was actually measured.
            for fid in ident.dropped:
                for lv in (levels_by_pos[i] for i in keep):
                    if fid in lv:
                        non_identifiable_held[fid] = lv[fid]
                        break
            design_for_fit = dataclasses.replace(
                design_run,
                factor_ids=tuple(ident.estimable),
                points=tuple(
                    dataclasses.replace(
                        p,
                        coded=tuple(
                            c for j, c in enumerate(p.coded)
                            if _owner_run[j] in set(ident.estimable)
                        ),
                    )
                    for p in design_run.points
                ),
                **({"groups": tuple(g for g in _owner_run
                                    if g in set(ident.estimable))}
                   if design_run.groups else {}),
            )
            if design_run.groups:
                design_for_fit = dataclasses.replace(
                    design_for_fit, factor_ids=tuple(
                        c for c, g in zip(design_run.factor_ids, _owner_run)
                        if g in set(ident.estimable)))
        design_for_fit = dataclasses.replace(
            design_for_fit,
            points=tuple(design_for_fit.points[i] for i in keep),
        )
        ys_for_fit = [ys[i] for i in keep]

        logger.warning(
            "%s: fitting on %d of %d rows; %d row(s) excluded (%s). The fit's "
            "resolution is reduced accordingly — a single NaN row would "
            "otherwise NaN-poison every coefficient silently.",
            stage_name, len(keep), len(ys), len(dropped),
            ", ".join(f"pos {i}: {excluded_reasons[i]}" for i in dropped),
        )

    # ── floor (c): is the model FULL RANK on what is left? ──────────────────
    #
    # Six corners cannot support seven terms. That is arithmetic, and the
    # principled response is the one `effects.py` already takes for aliased
    # columns: FIT FEWER TERMS AND SAY SO, keeping every main effect — which is
    # what `dropped_factors`, the stage rule and the argmax all read — where
    # aborting would discard them to protect terms the surviving rows never
    # could have estimated. Two steps, most specific first:
    #
    #   1. OMIT each higher-order term whose column lies in the span of the
    #      intercept and main effects on these rows
    #      (`exclusions.non_estimable_terms`) -- unambiguous: such a term is a
    #      function of lower-order terms here, like an alias of a main effect.
    #   2. If the model is still deficient (several interactions jointly
    #      dependent, so which to drop would be arbitrary), drop the whole
    #      interaction block.
    #
    # Checked for every fit, not only one with exclusions: fitted on the coded
    # ACTUAL levels (INV-STAT14) the matrix is the one that ran, and nothing
    # guarantees a hand-built or recoded design is full rank.
    # A multi-level categorical that LOST a level (every row at it failed or
    # was excluded) keeps the contrasts its retained levels support, and the
    # lost level is excluded from the recommendation (stage-1 M5) -- as a
    # two-level choice that keeps both levels stays fitted, rather than the
    # campaign aborting on a rank-deficient model.
    lost_levels: dict = {}
    if dropped and design_for_fit.groups:
        design_for_fit, lost_levels = exclusions.lost_categorical_levels(
            design_for_fit, factors, [levels_by_pos[i] for i in keep])
        if lost_levels:
            logger.warning(
                "%s: categorical level(s) %s have no retained row; the factor(s) "
                "are fitted on their remaining levels and the lost levels are "
                "never recommended (fit_exclusions.json lost_levels).",
                stage_name, lost_levels)
    omitted_terms = exclusions.non_estimable_terms(design_for_fit)
    if omitted_terms:
        logger.warning(
            "%s: term(s) %s are not estimable from the %d fitted row(s) -- each "
            "column lies in the span of the intercept and main effects there "
            "(e.g. a quadratic of a factor with only two levels left, or an "
            "interaction over three surviving cells of a 2x2). Omitting them "
            "and recording omitted_terms in effects.json.",
            stage_name, [f"{t[0]}^2" if t[0] == t[1] else f"{t[0]}{t[1]}"
                         for t in omitted_terms],
            len(ys_for_fit),
        )
    if not exclusions.model_is_full_rank(design_for_fit, omit_terms=omitted_terms):
        if exclusions.model_is_full_rank(
            design_for_fit, include_interactions=False, omit_terms=omitted_terms,
        ):
            interactions_dropped = True
            logger.warning(
                "%s: the %d fitted row(s) cannot support the full model "
                "(intercept + main effects + two-factor interactions) — it "
                "is rank-deficient. Fitting MAIN EFFECTS ONLY and recording "
                "the reduced model, rather than aborting and discarding "
                "every main effect to protect interactions the surviving "
                "rows never could have estimated. fit_exclusions.json "
                "records interactions_dropped.",
                stage_name, len(ys_for_fit),
            )
        else:
            raise OptimizationAborted(
                f"the {len(ys_for_fit)} retained row(s) cannot support even a "
                f"main-effects-only model over {list(fitted_ids)}: the "
                f"model matrix is rank-deficient, so no coefficient is "
                f"estimable. Re-run the excluded configurations, or narrow "
                f"the design to the region that measures.",
            )

    # ── a level-correlated loss is not a widened one ────────────────────────
    #
    # A BALANCED loss costs degrees of freedom, which widens every interval —
    # honest, and already handled by the arithmetic. A loss CONCENTRATED on one
    # level of one factor moves that factor's POINT ESTIMATE and leaves its
    # interval looking exactly as tight as before, because the interval is
    # computed from the retained rows' pure error and knows nothing about the
    # region that is missing. Logging a warning would not change what a reader
    # of `effects.json` sees, so the caveat is attached to the artifacts a
    # consumer actually joins on: `effects.json`'s `exclusion_balance`, and
    # `recommendation.json`'s, next to the bound.
    #
    # It is NOT routed to the policy and it is NOT an `if` deciding the next
    # state — that decision belongs to the compiled policy, and no registered
    # branch reads this. It changes what the campaign CLAIMS, not where it goes.
    if balance.level_correlated:
        logger.warning("%s: %s", stage_name, balance.caveat())

    blocks_for_fit = (None if not fit_blocks else
                      [fit_blocks[i] for i in (keep if dropped else range(len(ys)))])
    fit = fit_effects(
        design_for_fit, ys_for_fit, blocks=blocks_for_fit,
        # A categorical's fit columns are its contrasts, not its factor id;
        # with none, the design's columns ARE fitted_ids (unchanged).
        factor_ids=(design_for_fit.factor_ids if design_for_fit.groups
                    else fitted_ids),
        include_interactions=not interactions_dropped,
        omit_terms=omitted_terms,
    )
    _fit_pos = keep if dropped else list(range(len(ys)))
    # Curvature COVERAGE from the centre rows actually fitted (stage-1 M8): a
    # choice level with no fitted centre row is one the lack-of-fit test never
    # looked under, so "adequate" cannot be claimed for it.
    untested = _curvature_untested_levels(
        factors, fitted_ids, [design_for_fit.points[k].role
                              for k in range(len(design_for_fit.points))],
        [levels_by_pos[i] for i in _fit_pos], lost=lost_levels)
    _fit_records = _fit_row_records(work_dir, outcomes, stage_name, screen_iter,
                                    n_total=len(ys), n_fold=fold_n,
                                    prefix_indices=prefix_indices)
    if design_for_fit.groups:
        # Mixed-level: the planned design's columns are pseudo-factors and the
        # fit's are contrasts -- different widths. Record the planned columns
        # of every fitted FACTOR beside the fitted ones.
        _fitted_f = set(design_for_fit.groups)
        _owner_p = design.groups or design.factor_ids
        _fit_cols = [j for j, g in enumerate(_owner_p) if g in _fitted_f]
        _planned_for_fit = dataclasses.replace(
            design, factor_ids=tuple(design.factor_ids[j] for j in _fit_cols),
            points=tuple(
                dataclasses.replace(
                    design.points[i],
                    coded=tuple(design.points[i].coded[j] for j in _fit_cols),
                )
                for i in _fit_pos
            ),
        )
    else:
        _fit_cols = [design.factor_ids.index(fid) for fid in design_for_fit.factor_ids]
        _planned_for_fit = dataclasses.replace(
            design_for_fit,
            points=tuple(
                dataclasses.replace(
                    design.points[i],
                    coded=tuple(design.points[i].coded[j] for j in _fit_cols),
                )
                for i in _fit_pos
            ),
        )
    artifacts.write_effects(
        iter_dir, fit, factors=factors, stage=stage_name,
        exclusion_balance=(balance.as_dict() if dropped else None),
        fit_coordinates=matrix.fit_coordinates_record(
            _planned_for_fit, design_for_fit,
            statuses=[_fit_records[i][0] for i in _fit_pos],
        ),
        omitted_terms=omitted_terms,
        interactions_dropped=interactions_dropped,
        curvature_untested_levels=untested,
        lost_levels=lost_levels,
        held_out_rows=[r.row_index for r in val_rows],
        planned_aliases_separated=(
            planned_aliases_separated(design_mod.alias_pairs(design), fit)
            if design.groups else None),
    )
    if dropped:
        _write_json(iter_dir / "fit_exclusions.json", {
            "stage": stage_name,
            # planned == fitted + excluded, always. A reader must be able to
            # reconcile the three numbers without consulting runs.jsonl.
            "planned_rows": len(ys),
            "fitted_rows": len(ys_for_fit),
            "excluded_row_indices": dropped,
            # Per-row REASONS, because they mean different things
            # scientifically: `infeasible` is information about X_valid that a
            # re-run will reproduce, while `failed_to_measure` is a repairable
            # hole in the design. Merging them (as the single `reason` string
            # below used to) tells a reader the wrong thing to do next.
            "excluded_reasons": {str(i): excluded_reasons[i] for i in dropped},
            "excluded_by_reason": {
                r: sorted(i for i in dropped if excluded_reasons[i] == r)
                for r in sorted({excluded_reasons[i] for i in dropped})
            },
            "non_identifiable_factors": sorted(non_identifiable_held),
            **({"lost_levels": {k: list(v) for k, v in lost_levels.items()}}
               if lost_levels else {}),
            **({"lost_at_corners": lost_at_corners} if lost_at_corners else {}),
            "interactions_dropped": interactions_dropped,
            "omitted_terms": [list(t) for t in omitted_terms],
            "fitted_ids": list(fitted_ids),
            "exclusion_balance": balance.as_dict(),
            # Kept for backward compatibility with readers (and one test)
            # written against the single-string shape. It now SUMMARISES the
            # per-row reasons rather than asserting one for all of them.
            "reason": (
                "rows did not reach status 'complete' with a usable primary "
                "metric (" + ", ".join(
                    f"{r}: {len([i for i in dropped if excluded_reasons[i] == r])}"
                    for r in sorted({excluded_reasons[i] for i in dropped})
                ) + "); fitting on the complete subset rather than carrying "
                "NaN into every coefficient"
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
    # recommending a configuration it watched fail. Candidates a fitted
    # constraint model predicts CONFIDENTLY infeasible are removed too (below).
    held_now = dict(payload.get("held_fixed") or {})
    # A factor dropped for non-identifiability was not "varied but unfitted":
    # every retained row sat at ONE of its levels, so the argmax must hold it
    # there rather than enumerate levels the reduced fit has no coefficient for.
    # Without this, `decide.ranked` would score candidates at levels the model
    # cannot distinguish and the recommendation could name one purely on
    # tie-break order. `held_fixed` is also what `recommendation.json` records,
    # so the pin is visible next to the narrowed `fitted_ids`.
    held_now.update(non_identifiable_held)
    excluded = _measured_infeasible(work_dir)
    # What was MEASURED inadmissible, kept apart from the synthetic level
    # exclusions below (stage-1b N7): recommendation.json's
    # excluded_measured_infeasible must mean exactly that.
    excluded_measured = list(excluded)
    # Levels the fit cannot speak for: LOST (no retained row, M5) or measured
    # INADMISSIBLE on every row that ran them. Both are excluded from the
    # recommendation outright; ``_excluded`` matches on shared keys, so
    # ``{C: level}`` removes every candidate at that level.
    inadmissible_levels = _inadmissible_categorical_levels(work_dir, factors)
    # LOST levels persist across the epoch's fitting stages (stage-1d Q1): a
    # refine holds a categorical fixed and loses nothing of its own, but a
    # level the screen lost is still unrecommendable.
    lost_levels = _union_levels(_epoch_lost_levels(work_dir), lost_levels)
    _by = {f.id: f for f in factors}
    # A factor is FULLY barred when lost ∪ inadmissible covers every level
    # (stage-1d Q2). Then only the LOST levels (never measured) are excluded;
    # the inadmissible ones (measured) stay candidates and are recorded under
    # all_levels_inadmissible. Lost alone covering every level is an abort.
    _barred_all = _union_levels(inadmissible_levels, lost_levels)
    all_bad = sorted(fid for fid, lvs in _barred_all.items()
                     if fid in _by and len(lvs) >= len(_by[fid].levels))
    for fid in all_bad:
        if len(lost_levels.get(fid, ())) >= len(_by[fid].levels):
            raise OptimizationAborted(
                f"{stage_name}: every level of categorical {fid!r} is LOST "
                f"({lost_levels[fid]}): no retained run at any of them, so no "
                f"configuration of {fid} can be recommended. Re-run the failed "
                f"configurations.")
    if all_bad:
        logger.warning(
            "%s: lost and inadmissible levels together cover EVERY level of %s; "
            "only the lost ones are excluded, the inadmissible ones are recorded "
            "(all_levels_inadmissible) and stay candidates.", stage_name, all_bad)
    # UNION per factor (stage-1c P2): a factor can have one lost AND one
    # inadmissible level; a dict merge would keep only one of the two lists.
    for fid, lvs in _union_levels({k: v for k, v in inadmissible_levels.items()
                                   if k not in all_bad}, lost_levels).items():
        for lv in lvs:
            excluded = list(excluded) + [{fid: lv}]
    # ── the constraint models (constrained response-surface practice) ──────
    #
    # The primary fit knows nothing about `response.constraints`, so without
    # these the ranking happily nominates the INTERIOR of a region every
    # measurement refused (observed: every screen row at one corner measured
    # infeasible, and the two top candidates were interior points of that
    # corner). Each numeric constraint metric is fitted over the same design
    # and model family, on the complete AND infeasible rows -- an infeasible row
    # is precisely a measurement of where the boundary is. A candidate leaves the
    # ranking only when the constraint's one-sided bound at delta_screen sits
    # entirely on the violating side; see `constraint_models` for the rule and
    # for every reason a constraint falls back to measurement only.
    delta_s = pol["objective"]["delta_screen"]
    cmods: list = []
    if _MODEL_CONSTRAINTS and (response_spec.get("constraints") or []):
        cmods = cmodels.fit_constraint_models(
            response_spec.get("constraints") or [], design_run,
            _fit_records,
            fitted_ids=fitted_ids, held_levels=non_identifiable_held,
            levels_by_pos=levels_by_pos, blocks=fit_blocks,
        )
    # ── the candidate space: enumerated, or searched above the cap ─────────
    #
    # Above `decide.CANDIDATE_CAP` the space is searched, not enumerated
    # (`decide._scored`), and the search POOL is seeded with every
    # configuration this epoch measured -- the fitted rows and every other row
    # on disk. The ascent STARTS are the best-predicted pool points, so a
    # measured configuration is a start only when the fit rates it among
    # them; one that cannot be placed on the axes is counted in
    # `candidate_space.seeds_dropped`. Multi-objective campaigns
    # fit their objective models first so the search also climbs every
    # objective and a spread of their weighted sums: the predicted front taken
    # over `scored` then reaches its extremes and interior. Under the cap none
    # of this changes a byte (`seed_levels`/`objectives` are unused there).
    _seed_levels = [dict(lv) for lv in levels_by_pos if lv]
    for _rp in _this_epoch_runs(work_dir):
        _seed_levels += [dict(r["levels"]) for r in artifacts.read_runs(_rp.parent)
                         if r.get("levels")]
    _omodels = None
    _search_objectives = ()
    if pareto_stage.objectives(pol):
        _omodels = cmodels.fit_objective_models(
            [{"metric": o.metric, "direction": o.direction}
             for o in pareto_stage.objectives(pol)],
            design_run, _fit_records, fitted_ids=fitted_ids,
            held_levels=non_identifiable_held, levels_by_pos=levels_by_pos,
            blocks=fit_blocks,
        )
        _search_objectives = tuple(
            (_omodels[o.metric].fit, o.direction)
            for o in pareto_stage.objectives(pol)
            if _omodels.get(o.metric) is not None
            and _omodels[o.metric].fit is not None)
    _search = {"seed_levels": _seed_levels}
    # `top=None` means "no truncation", so one call gives both the shortlist
    # and the size of the space it was chosen from. Ordering stays in `decide`
    # — re-deriving the argmax here would put the tie-break and the direction
    # sign in two places.
    scored = decide.ranked(
        fit, factors, direction=direction, fitted_ids=fitted_ids,
        held_fixed=held_now, exclude_levels=excluded, top=None,
        constraint_models=cmods, constraint_delta=delta_s,
        objectives=_search_objectives, **_search,
    )
    candidate_space = scored.space
    if not candidate_space.exhaustive:
        logger.warning(
            "%s: the candidate space has %s configurations (> CANDIDATE_CAP=%d), "
            "so it was SEARCHED, not enumerated: %d evaluated by %s (seed %s). "
            "The recommendation is the best EVALUATED candidate, not a proven "
            "argmax over X_valid.", stage_name, candidate_space.size,
            decide.CANDIDATE_CAP, candidate_space.evaluated,
            candidate_space.method, candidate_space.seed)
        if candidate_space.seeds_dropped:
            logger.warning(
                "%s: %d measured configuration(s) could not be placed on the "
                "candidate axes and seeded nothing (candidate_space.seeds_dropped).",
                stage_name, candidate_space.seeds_dropped)
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
    # ── MULTI-OBJECTIVE: fit every objective, predict the front ────────────
    #
    # Spec 2026-10-15-pareto-front-design.md steps 1-3. Every objective is
    # fitted on the same complete + infeasible rows, coded as run, with the
    # same reduction as the constraint models; the predicted front is taken
    # over exactly the space `scored` enumerates (measured-infeasible and
    # confidently-infeasible candidates already removed), and the top-level
    # recommendation becomes its PREFERRED point. Gated on the compiled
    # policy registering objectives, so a single-objective recommendation.json
    # is byte-identical.
    mo_record = None
    mo_rejected: list[str] = []
    mo_lof: list[str] = []
    mo_untested: list[str] = []
    mo_survivors: set[str] = set()
    if pareto_stage.objectives(pol):
        _pref_cand, mo_record = pareto_stage.fit_record(
            pol, scored=scored, omodels=_omodels, delta_s=delta_s,
            stage_name=stage_name, held_now=held_now,
            prev_rec=_read_recommendation(work_dir),
        )
        mo_rejected = pareto_stage.models_rejected(_omodels)
        mo_lof = pareto_stage.models_rejected(_omodels, lack_of_fit_only=True)
        mo_untested = pareto_stage.models_untested(_omodels)
        mo_survivors = pareto_stage.survivors(_omodels, factors)
        if _pref_cand is not None:
            rec = _pref_cand
        logger.info(
            "%s: predicted front of %d point(s) over %d candidate(s); preferred "
            "(%s) %s; rejected objective model(s): %s", stage_name,
            mo_record["front_size_predicted"], len(scored),
            pareto_stage.preference(pol).method, rec.levels, mo_rejected or "none",
        )
    # ── the SUPPORTED-FEASIBLE candidate (INV-STAT16) ───────────────────────
    #
    # The exclusion above removes only CONFIDENTLY infeasible candidates, so on
    # a constraint-bound frontier every member of `top` can be of uncertain
    # feasibility -- and confirm, which seats from `top`, would then measure
    # nothing the evidence says is admissible. Name the best-predicted candidate
    # the evidence DOES support (see `constraint_models.supported_feasible`), and
    # a short pool behind it for round-r top-ups; `_confirm_rows` reserves a seat
    # for it. Pure arithmetic over the space already scored: no new fit, no new
    # model call. Written only when constraints are declared, so an
    # unconstrained campaign's recommendation.json is byte-identical.
    supported_record = None
    _declared = response_spec.get("constraints") or []
    if _declared and policy_mod._REFILL_VACATED:
        # The REFILL branch's candidate pool (policy.REFILL_ACCOUNTING): the
        # constraint-filtered ranking, deeper than `top_candidates`, because the
        # configurations a refill needs are the ones BELOW the model's
        # infeasible favourites. A sibling file, not a recommendation.json
        # field, so a constrained campaign that never vacates a seat writes the
        # same governed artifacts it always did.
        _write_json(iter_dir / "refill_pool.json", {
            "stage": stage_name, "iteration": iteration,
            "candidates": [{"levels": c.levels, "coded": c.coded,
                            "predicted": c.predicted} for c in scored[:_REFILL_POOL]],
        })
    if _SUPPORTED_FEASIBLE_SEAT and _declared:
        supported_record = _supported_feasible_record(
            work_dir, factors, _declared, cmods, scored, delta=delta_s,
            pool_size=max(5, _shortlist * 2),
        )
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
        # WP-A A1: enough of the per-challenger profile to cover every seat a
        # confirm round can fill from this record (top_candidates, the best
        # measured, the supported-feasible seat) with headroom.
        profile=3 * _shortlist + 5,
    )
    if not candidate_space.exhaustive:
        # Above the cap the max in eq. (2) ran over the EVALUATED set only, so
        # the number bounds the regret against those challengers -- not
        # against every z in X_valid. Said where the number is, not elsewhere.
        rb = dataclasses.replace(rb, detail=(
            f"{rb.detail}; NOT over all of X_valid: max over the "
            f"{len(scored)} evaluated valid candidate(s) of a "
            f"{candidate_space.size}-configuration space searched by "
            f"{candidate_space.method} (recommendation.json candidate_space)"))
    epsilon = certificate.resolve_epsilon(pol["objective"]["epsilon"], rec.predicted)

    # ── is the aliasing CONSEQUENTIAL? (spec §3.4, paper §Illustrative) ────
    #
    # Costs nothing — pure arithmetic over the coefficients already fitted and
    # the space already enumerated — and it is what turns aliasing from a hidden
    # assumption into a resource decision. Recorded in `recommendation.json`
    # whatever the answer, because "the design confounds AB with CD and it does
    # not matter for the winner" is a claim a reader should be able to check, not
    # an absence they have to trust.
    #
    # Computed at EVERY fitting state, not only at screen. The foldover block
    # resolves the alias it was spent on, so the pairs should come back empty
    # there; recording them is what makes that verifiable rather than assumed,
    # and the foldover state deliberately carries no second foldover branch, so
    # a non-empty list there is a finding for a reader rather than another run.
    alias_record: dict = {}
    alias_pairs_consequential = decide.alias_consequential(
        fit, factors, direction=direction, fitted_ids=fitted_ids,
        held_fixed=held_now, exclude_levels=excluded,
        epsilon_pct=float((pol["objective"]["epsilon"] or {}).get("pct", 2.0)),
        constraint_models=cmods, constraint_delta=delta_s,
        # The stage's own primary argmax (`scored` is sorted by the primary):
        # above the cap it came from the search that also climbed every
        # objective, so it can beat what alias_consequential's own search finds.
        baseline=scored[0] if scored else None, record=alias_record, **_search,
    )
    # Counted over the set the ranking ACTUALLY filtered (`scored.unfiltered`),
    # not a fresh ranking: above the cap a second search would evaluate a
    # different set and could disagree about whether the models applied.
    constraint_record = _constraint_models_record(
        cmods,
        scored.unfiltered if any(m.modelled for m in cmods) else [],
        rec, delta=delta_s,
        applied=(None if candidate_space.exhaustive
                 else bool(candidate_space.constraint_models_applied)),
        evaluated=None if candidate_space.exhaustive else candidate_space.evaluated,
    )
    uncertain_at_rec = [
        e["metric"] for e in constraint_record
        if (e.get("at_recommendation") or {}).get("verdict") == "uncertain"
    ]
    if uncertain_at_rec:
        logger.info(
            "%s: the recommendation is UNCERTAIN on constraint(s) %s -- its "
            "one-sided bound straddles the threshold, so only a measurement can "
            "say whether it is admissible.", stage_name, uncertain_at_rec,
        )
    # MODEL ADEQUACY, three-valued and defined ONCE (stage-1b N1/N5/N3):
    #   False -- lack of fit rejected (or a rejected objective model);
    #   None  -- UNKNOWN: the lack-of-fit test was never computable (no pure
    #            error, or no residual df beyond it), a choice level was never
    #            measured at the centre (curvature_untested), or a mixed fit
    #            could not isolate curvature from its coefficients;
    #   True  -- the test was computed, did not reject, and covered every level.
    # Confirm shortlists an unknown model like an adequate one (its ranking is
    # not REJECTED, and every finalist is re-measured anyway) but certification
    # is withheld with the basis named (``_finish_confirm``).
    adequate, adequacy_basis = _model_adequacy(
        decision, mo_rejected, fit, untested, design_for_fit,
        mo_untested=mo_untested)
    # ── WP-B: how adequacy is DETERMINED beyond lack of fit ──────────────────
    # (spec 2026-10-17-model-adequacy-design.md). The validation prediction
    # check (refine), PRESS and the design's D-efficiency, and the STICKY
    # epoch verdict over every fitting stage.
    adequacy_record, adequate, adequacy_basis = _adequacy_record(
        work_dir, stage_name, fit, design_for_fit, ys_for_fit, factors,
        fitted_ids, interactions_dropped, omitted_terms, adequate,
        adequacy_basis, decision, val_rows, val_outcomes, val_ys,
        response_spec, primary, _omodels, blocks=blocks_for_fit)
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
        # DOES THE TERMINAL STAGE GET TO TRUST THIS RECOMMENDATION?
        #
        # `lack_of_fit` says the registered response class does not describe the
        # measurements, so the argmax over the fitted surface is an artefact of a
        # model the data rejected. The policy still routes to `confirm` — the
        # registered augmentation for model inadequacy IS confirm's fresh
        # measurements, and abandoning the stage would be the "diagnosis without
        # action" defect — but confirm must not seat the model's pick as a
        # finalist. `_confirm_rows` reads this flag and builds the shortlist from
        # MEASURED valid rows only, which is spec §3.6 rung 3 / the paper's
        # "remeasures the leading measured valid candidates rather than choosing
        # the largest noisy observation".
        #
        # Persisted here rather than recomputed at confirm because confirm is a
        # separate `run_iteration` call: the `Fit` is gone by then, and re-deriving
        # inadequacy from effects.json would put the lack-of-fit test in two
        # places. `observations_from_decision` already computes it for the policy;
        # this is the same fact written where the consumer can read it.
        # UNKNOWN (None), not True, when lack of fit did not reject but some
        # choice level was never measured at the centre (stage-1 M8).
        "model_adequate": adequate,
        **({"model_adequate_basis": adequacy_basis} if adequate is None else {}),
        "model_adequacy": adequacy_record,
        **({"curvature_untested_levels": untested} if untested else {}),
        "excluded_measured_infeasible": excluded_measured,
        **({"lost_levels": {k: list(v) for k, v in lost_levels.items()}}
           if lost_levels else {}),
        **({"inadmissible_levels": {k: list(v) for k, v in inadmissible_levels.items()}}
           if inadmissible_levels else {}),
        **({"all_levels_inadmissible": all_bad} if all_bad else {}),
        # Per declared constraint: was it modelled (and if not, why not), how
        # many candidates its model removed as CONFIDENTLY infeasible, and its
        # verdict at the recommendation itself. An auditor can reconcile
        # `top_candidates` against this without refitting anything.
        "constraint_models": constraint_record,
        "recommendation_constraint_uncertain": uncertain_at_rec,
        # The best candidate whose feasibility the evidence supports, and why
        # (or why none qualifies). Confirm reserves a seat for it.
        **({"supported_feasible_candidate": supported_record}
           if supported_record is not None else {}),
        "residual_regret_model": rb.as_dict(),
        # WP-A A1: the largest per-challenger model bounds and the max over the
        # rest, so confirm can bound what screening left OUTSIDE its shortlist.
        **({"residual_regret_model_profile": rb.profile} if rb.profile else {}),
        "epsilon": epsilon,
        "alias_consequential": [list(p) for p in alias_pairs_consequential],
        # 2fi NOT fitted because their corner column lies in the span of kept
        # columns (stage-1 M1): alias_consequential re-attributes ONE coefficient
        # to ONE alternative term, so it cannot assess these (stage-1b N13).
        # In a resolution-III mixed screen they are the 2fi~main aliases rule
        # 30 guards against; listed so the gap is visible, not silent.
        **({"aliases_not_assessed": ["".join(t) for t, _sp in fit.span_aliased]}
           if fit.span_aliased else {}),
        "aliases": [list(p) for p in fit.aliases],
        # ── the caveat travels WITH the bound, not in a sibling file ────────
        #
        # Present only when rows were excluded. `residual_regret_model` sits
        # three keys above it, and that adjacency is the point: the model
        # bound's guarantee is conditional on the registered response class
        # describing the measurements, and a LEVEL-CORRELATED exclusion is
        # evidence that the surface it was fitted on is biased in a named
        # direction rather than merely estimated from fewer rows. Recording the
        # verdict here is also what lets `confirm` read it back — the Fit is gone
        # by then, exactly as `model_adequate` is persisted for the same reason.
        **({"exclusion_balance": balance.as_dict()} if dropped else {}),
        **(mo_record or {}),
        # Present only when the space was SEARCHED rather than enumerated
        # (above `decide.CANDIDATE_CAP`): absence means the argmax, the
        # shortlist, the regret bound and the predicted front were all taken
        # over the whole valid space, exactly as before the search existed.
        **({"candidate_space": candidate_space.as_dict(),
            # Searched, not enumerated: an empty alias list means none was
            # FOUND, and front statuses are relative to the evaluated points.
            "alias_consequential_basis": "searched",
            # Which alias readings the searched test actually assessed (a
            # local search each, at most decide.ALIAS_READINGS_CAP of them,
            # largest coefficient first) and which it did not.
            **({"alias_assessment": alias_record} if alias_record else {}),
            **({"predicted_front_basis": "evaluated_points"}
               if (mo_record or {}).get("predicted_front") is not None else {})}
           if not candidate_space.exhaustive else {}),
    })
    if alias_pairs_consequential:
        logger.info(
            "%s: aliasing is CONSEQUENTIAL — re-attributing the shared estimate "
            "in %s names a different winner, so resolving it can change the "
            "answer. The policy's registered foldover fires if the budget covers "
            "the block.", stage_name,
            [list(p) for p in alias_pairs_consequential],
        )
    elif fit.aliases:
        logger.info(
            "%s: %d alias pair(s) recorded (%s) and NONE is consequential — every "
            "plausible resolution names the same epsilon-optimal winner, so a "
            "foldover would buy a cleaner model and a worse campaign. Not "
            "spending it.", stage_name, len(fit.aliases),
            [list(p) for p in fit.aliases],
        )
    logger.info(
        "%s: recommendation %s (predicted %s=%.6g) — argmax over %d valid "
        "candidate(s)" + ("" if candidate_space.exhaustive else
                          " (SEARCHED, not exhaustive)") + ", %d "
        "measured-infeasible configuration(s) excluded; "
        "residual regret R_%.3g=%s vs epsilon=%.6g (%s)",
        stage_name, rec.levels, primary or "response", rec.predicted,
        len(scored), len(excluded_measured), rb.delta,
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
        direction=direction, lost_levels=lost_levels,
    )
    _write_json(iter_dir / "findings.json", findings)
    # principle_updates.json is a BARE LIST on disk (verified against real
    # campaign artifacts, and required by iteration._merge_principles, which
    # raises on a dict). project_principle_updates returns the
    # principles.schema.json wrapper {"principles": [...]}, which is the
    # shape of the merged principles.json store, not of this per-iteration
    # file — so unwrap it here.
    updates = artifacts.project_principle_updates(
        fit, factors=factors, stage=stage_name, direction=direction,
        lost_levels=lost_levels,
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
            1 for fid in (set(decision.surviving) | mo_survivors
                          if mo_record is not None else decision.surviving)
            if fid in by_fid and is_refinable(by_fid[fid])
        ),
        stationary_in_hull=(
            None if stage_name != Stage.REFINE.value
            # Multi-objective: not computed (see the override below), so the
            # first objective's out-of-hull diagnosis is not logged as one.
            else None if mo_record is not None
            else _stationary_in_hull(fit, stationary, direction)
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
        #
        # `ys[-fold_n:]` rather than `ys`: at foldover `ys` has the SCREEN
        # block's responses prepended, so a bare `zip(outcomes, ys)` would pair
        # this iteration's outcomes with the previous iteration's measurements
        # and report the wrong rows' status. `fold_n` is the count of rows this
        # iteration actually ran, and it equals `len(ys)` at every other state,
        # so the slice is the identity there. The screen half's own NaN check is
        # `screen_nan`, folded in below — a missing screen row breaks the
        # combined design, so it routes to the same branch.
        "nan_response": any(
            v != v and getattr(o, "status", None) == "complete"
            for o, v in zip(outcomes, ys[-fold_n:] if fold_n else ys)
        ) or bool(screen_nan),
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

    # ── the foldover guard's two observations ─────────────────────────────
    #
    # `alias_consequential` is the DECISION fact ("could resolving this change
    # the winner?"); `foldover_affordable` is the RESOURCE fact ("can we pay for
    # it?"). Both must hold, which is exactly the paper's rule — the foldover is
    # spent when it can change the answer AND the budget covers it, never
    # unconditionally and never merely reported.
    #
    # `runs_needed_foldover` is recorded next to the verdict even though no
    # compiled guard reads it. The `when` vocabulary compares an observation
    # against a CONSTANT, so a two-observation comparison
    # (`budget_remaining >= runs_needed_foldover`) cannot be expressed as a
    # predicate and is evaluated here instead. Recording only the boolean would
    # leave a reader of `transitions.jsonl` unable to tell a foldover declined
    # for cost from one declined for irrelevance; recording both makes the
    # arithmetic behind the branch reconstructible from the log alone. This is
    # also what makes the key live rather than dead vocabulary.
    obs["alias_consequential"] = bool(alias_pairs_consequential)
    # The policy observes what the artifact says (stage-1b N1): unknown
    # adequacy is None, never True.
    if adequate is None and obs.get("model_adequate") is True:
        obs["model_adequate"] = None
    if adequate is False:
        obs["model_adequate"] = False
    if mo_record is not None:
        # NOT the semantic "optimum outside the hull" exception. That guard
        # says the declared ranges cannot contain THE optimum; a front has no
        # single optimum, and its extremes sit on the hull boundary by the
        # nature of a trade-off (the first objective's stationary point -- all
        # this fit can solve for -- leaves the hull whenever that objective is
        # monotone in a knob the other objective pays for). Unknown, so the
        # registered default (confirm) applies; report.md's What-to-do-next
        # names widening a range whose extreme the front sits on.
        obs["stationary_in_hull"] = None
    if mo_record is not None and mo_rejected:
        # Spec step 2: `lack_of_fit` = ANY objective's model rejects. It is the
        # registered curvature branch's trigger at screen/foldover, so a
        # curvature visible only in the SECOND objective still buys a refine.
        # An objective that could not be estimated at all is inadequate but is
        # not curvature evidence, so it moves only `model_adequate`.
        obs["lack_of_fit"] = bool(obs.get("lack_of_fit")) or bool(mo_lof)
        obs["model_adequate"] = False
    if stage_name == Stage.SCREEN.value and "foldover" in (pol.get("states") or {}):
        # What the block would cost: the fold design is the screen's corners plus
        # its centre replicates, so it is sized from the design rather than from
        # a config value that could disagree with what `_build_design` builds.
        fold_rows = len(_build_design(
            factors, design_cfg, Stage.FOLDOVER.value, fold_on=None,
        ).points)
        obs["runs_needed_foldover"] = fold_rows
        obs["foldover_affordable"] = obs["budget_remaining"] >= fold_rows
        if alias_pairs_consequential and not obs["foldover_affordable"]:
            logger.warning(
                "screen: the aliasing IS consequential but the registered "
                "foldover needs %d run(s) and only %d remain, so the alias "
                "stays unresolved and the recommendation carries it as an "
                "assumption. recommendation.json records which pairs.",
                fold_rows, obs["budget_remaining"],
            )
    return _close_iteration(
        engine, campaign, work_dir, iter_dir, iteration, stage_name, pol, obs,
        recommendation_levels=None,
    )


def _verify_abort_message(failures, *, test_run=None, factors=()) -> str:
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

    ``test_run`` (the ``runner.NativeTestResults`` of the command run this
    iteration, or None when verdicts were injected) adds the third cause, which
    the old message could not see: the command was KILLED at its ceiling. That
    reads as NEVER EXECUTED for every relation, and the never-executed advice --
    check names, paths, selection -- is exactly wrong for it.
    """
    missing, failed = [], []
    missing_ids: list[str] = []
    for v in failures:
        detail = str(getattr(v, "detail", "") or "")
        entry = (
            f"{getattr(v, 'relation_id', '?')} "
            f"({getattr(v, 'native_test', '?')})"
        )
        if "not executed" in detail:
            missing.append(entry)
            missing_ids.append(str(getattr(v, "native_test", "") or ""))
        else:
            failed.append(entry)

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
    if missing and test_run is not None and getattr(test_run, "timed_out", False):
        parts.append(
            "\nNEVER EXECUTED (" + str(len(missing)) + ") -- not reached "
            "before the test command was killed:\n  " + "\n  ".join(missing)
            + "\n  " + runner.explain_killed(test_run, factors),
        )
    elif missing and test_run is not None:
        parts.append(
            "\nNEVER EXECUTED (" + str(len(missing)) + ") -- the test command "
            "did not report this identifier, which counts as a failure because "
            "'not run' is not evidence of correctness:\n  "
            + "\n  ".join(missing) + "\n  "
            + runner.explain_unmatched(
                missing_ids, sorted(test_run),
                returncode=getattr(test_run, "returncode", None),
                exec_error=getattr(test_run, "exec_error", None),
                log_path=getattr(test_run, "log_path", None),
            )
            + "\n  Note `go test -run <pattern>` exits 0 when the pattern "
            "matches nothing, so a green shell here proves nothing.",
        )
    elif missing:
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


def _plan_max_turns(campaign: dict) -> int:
    """``max_turns.plan``, else the plan stage's default.

    Separate from the build's ceiling on purpose: designing reads and reasons,
    authoring reads, writes and runs tests, so they do not need the same budget.
    """
    from orchestrator.optimize.plan import DEFAULT_MAX_TURNS

    mt = campaign.get("max_turns")
    if isinstance(mt, dict):
        v = mt.get("plan")
        if isinstance(v, int) and v > 0:
            return v
    return DEFAULT_MAX_TURNS


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



def _screen_iteration(work_dir: Path, pol: dict | None = None) -> int | None:
    """The iteration of the most recent transition OUT of ``screen``.

    The foldover state's combined fit needs the screen's responses, and which
    iteration those live in is recorded evidence (``transitions.jsonl``) rather
    than an inference from the iteration index — a resumed work_dir, an
    exception-and-recompile epoch, or a campaign with pre-epoch ``build`` all
    move the screen away from any fixed position.

    SCOPED TO THE EPOCH when ``pol`` is given, and here the scoping is
    numerical rather than cosmetic. A foldover combines its own block with the
    screen's into ONE fit, so pointing it at a previous epoch's screen would fit
    over runs produced under a different compiled policy — possibly a different
    factor set, different ranges, or (in the case that ends an epoch most often)
    a mechanism that has since been revised. The aliasing argument the combined
    fit rests on is an argument about ONE design; two epochs' blocks are not that
    design.
    """
    rows = (
        policy_mod.read_transitions(work_dir) if pol is None
        else policy_mod.epoch_transitions(pol, work_dir)
    )
    hits = [
        int(t["iteration"]) for t in rows
        if t.get("from") == Stage.SCREEN.value and t.get("iteration") is not None
    ]
    return max(hits) if hits else None


def _fold_on(factors, design_cfg: dict, pairs) -> str | None:
    """Which single column the fold block negates, or ``None`` for a full fold.

    Two regimes, and they resolve different confounding (see
    ``design.foldover``):

      * a resolution-III screen aliases two-factor interactions onto MAIN
        effects, and only a FULL foldover (every column negated) clears that —
        so ``None``.
      * anything else (resolution IV, where 2fi are aliased with each other) is
        resolved by negating ONE column: every word containing that factor dies,
        which separates every 2fi involving it from its alias. Choose a factor
        that actually appears in the consequential pair, because folding on a
        factor absent from both sides of the alias would spend the block and
        leave the alias exactly where it was.

    The label is parsed by matching declared factor ids against its prefix
    rather than by splitting on character count: a campaign may declare
    multi-character ids (``KV``, ``BATCH``), and a one-char split would silently
    pick a factor that does not exist.
    """
    return _fold_on_basis(factors, design_cfg, pairs)[0]


def _fold_on_basis(factors, design_cfg: dict, pairs) -> tuple[str | None, str]:
    """``(column, basis)`` for the fold block: ``basis`` is ``"full"`` (a
    resolution-III screen: every column negated), ``"single_column"`` (a
    column read out of the consequential pair) or ``"full_fallback"`` (no
    column could be read out of the pairs, so a full foldover -- recorded in
    design_matrix.json with the unparsed pairs, stage-1 M12).

    MIXED-LEVEL CAVEAT (stage-1 M3): a full foldover negates every
    pseudo-column, and a categorical's contrast ``C[12]`` is the product of two
    of them, so a word like ``C[12]AE`` SURVIVES the negation. The validator
    refuses resolution III with a multi-level categorical while the foldover
    is registered (rule 30), and the foldover state always recomputes and
    records the aliasing left on the COMBINED design.
    """
    resolution = int((design_cfg.get("screen") or {}).get("resolution", 5))
    if resolution <= 3:
        return None, "full"
    ids = [f.id for f in factors]
    from orchestrator.optimize.factors import is_categorical, model_columns

    cats = {f.id: f for f in factors if is_categorical(f)}
    if cats:
        # Mixed-level: a label is a product of COLUMN ids, and a categorical's
        # contrast ``C[12]`` is the product of its pseudo-factors 1 and 2.
        # Negating pseudo-column ``C[i]`` flips every contrast containing i, so
        # it breaks a word through ``C[12]`` when i is in {1, 2}. Prefer a
        # TWO-LEVEL factor in the pair (one column, flips exactly its words);
        # else fold on the lowest pseudo-column of the first contrast.
        toks = sorted(set(ids) | {c for f in cats.values() for c in model_columns(f)},
                      key=len, reverse=True)
        for kept, alt in pairs or ():
            for label in (str(kept), str(alt)):
                parsed, rest = [], label
                while rest:
                    m = next((t for t in toks if rest.startswith(t)), None)
                    if m is None:
                        break
                    parsed.append(m)
                    rest = rest[len(m):]
                two = [t for t in parsed if t in ids and t not in cats]
                if two:
                    return two[0], "single_column"
                for t in parsed:
                    if "[" in t:
                        base, digits = t[:-1].split("[", 1)
                        if base in cats and digits:
                            return f"{base}[{min(digits)}]", "single_column"
        logger.warning(
            "foldover: no column could be read out of the consequential pairs %s; "
            "falling back to a FULL foldover.", list(pairs or ()))
        return None, "full_fallback"
    for kept, _alt in pairs or ():
        rest = str(kept)
        while rest:
            # Longest id first, so `A` never shadows `AB` on a campaign that
            # declares both.
            match = max(
                (fid for fid in ids if rest.startswith(fid)), key=len, default=None,
            )
            if match is None:
                break
            return match, "single_column"
    # Reaching here means either the pairs list was empty or no label matched a
    # declared id. Neither should be possible: the policy only routes to this
    # state after the screen observed `alias_consequential`, and every label
    # `fit_effects` produces is built from `factor_ids`. Fall back to a FULL
    # foldover rather than to `ids[0]` — folding on an arbitrary column would
    # spend the block and, if that column appears in no alias word, resolve
    # nothing at all, whereas a full foldover at least clears every odd-length
    # word. Say so in the log, because it means the recorded pairs and the
    # design disagree.
    logger.warning(
        "foldover: no declared factor could be read out of the recorded "
        "consequential pairs %s (declared ids: %s), so falling back to a FULL "
        "foldover. This means recommendation.json's alias_consequential and the "
        "campaign's factor set disagree — check whether the factor list changed "
        "under a resumed work_dir.", list(pairs or ()), ids,
    )
    return None, "full_fallback"


def _screen_responses(work_dir: Path, screen_iter: int, primary: str,
                      n_expected: int) -> tuple[list[float], bool]:
    """The screen block's responses in DESIGN-ROW order, plus a NaN flag.

    Order is everything: ``fit_effects`` pairs value ``i`` with
    ``design.points[i]``, and ``combine`` concatenates screen-then-fold, so the
    screen half of the response vector must be in ``row_index`` order. Rows land
    in ``runs.jsonl`` in EXECUTION order (the pre-registered randomized
    permutation), so reading the file front-to-back would misalign every
    coefficient while producing a perfectly plausible fit.

    A row that did not complete, or whose primary metric is missing or
    non-numeric, contributes NaN and sets the flag. The caller routes that to
    ``nan_response`` rather than fitting: the combined fit rests on the screen
    block as much as on the fold block, and silently dropping a screen row would
    change the combined design's real resolution — the very thing this state
    exists to improve.
    """
    rows = artifacts.read_runs(Path(work_dir) / "runs" / f"iter-{screen_iter}")
    by_index: dict[int, dict] = {}
    for row in rows:
        idx = row.get("row_index")
        if isinstance(idx, int):
            by_index[idx] = row
    ys: list[float] = []
    saw_nan = False
    for i in range(n_expected):
        row = by_index.get(i)
        raw = None if row is None else (row.get("response") or {}).get(primary)
        if row is None or row.get("status") not in _PRIMARY_FIT_STATUSES or raw is None:
            ys.append(float("nan"))
            saw_nan = True
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            ys.append(float("nan"))
            saw_nan = True
            continue
        if val != val:
            saw_nan = True
        ys.append(val)
    return ys, saw_nan


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
        if root not in ("applied", "applied_args", "applied_env", "applied_patches"):
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
      3. the best SUPPORTED-FEASIBLE candidate
         (``recommendation.json["supported_feasible_candidate"]``, INV-STAT16) —
         a seat reserved, when constraints are declared and ``k >= 2``, for the
         best-predicted candidate every modelled constraint predicts
         confidently feasible and that lies inside the measured-admissible
         region for every unmodelled one, so the comparison always tests at
         least one candidate the evidence says is admissible (see
         ``_seat_supported``);
      4. ``recommendation.json``'s ``top_candidates`` in order — the near
         misses whose intervals still reach above x-hat.

    UNLESS ``recommendation.json["model_adequate"] is False``, in which case rungs
    1 and 2 are replaced by ``_top_measured``'s leading MEASURED valid candidates
    (plural) and rungs 3 and 4 still fill whatever seats remain. A lack-of-fit verdict
    says the response class was rejected, so its argmax must not ANCHOR the
    comparison; it does not say the ranking may nominate nothing. Spec §3.6 rung 3
    constrains the REPORT LADDER — what may be returned as the answer — and every
    member of this shortlist is measured freshly before it can win regardless of
    who nominated it, so seating a model-ranked point tests the model rather than
    trusting it. The branch below records what discarding the ranking would cost,
    measured.

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
    rnd = _confirm_round(work_dir, pol)
    finalists: list[dict] = []
    provenance: list[str] = []
    # Parallel to `finalists`: was this seat nominated by a MEASUREMENT (a
    # carried finalist, the best observed configuration, a measured leader)?
    # The reserved supported-feasible seat may displace a model-ranked
    # nomination, never one of these.
    measured_seat: list[bool] = []
    barred = _barred_levels(work_dir)

    def _add(levels, why: str, *, allow_measured_invalid: bool = False,
             measured: bool = False) -> None:
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
        if _names_barred_level(lv, barred):
            if allow_measured_invalid:
                # The author-declared known_valid_baseline is EXEMPT (stage-1d
                # Q4), as it is from the measured-invalid filter: always act --
                # it is the one configuration the campaign may always return,
                # and the report ladder's baseline rung returns it too. The
                # exemption is recorded, never silent.
                logger.warning(
                    "confirm round %d: seating the known_valid_baseline %s although "
                    "it names a lost or inadmissible categorical level %s (the "
                    "declared baseline is exempt).", rnd, lv, barred)
                why = f"{why} (names a lost/inadmissible level; baseline exempt)"
            else:
                # ONE RULE (stage-1c P1): never seated, so it can never win
                # confirm and the report never recommends it.
                logger.info(
                    "confirm round %d: not seating %s (%s) -- it names a lost or "
                    "inadmissible categorical level %s.", rnd, lv, why, barred)
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
        measured_seat.append(bool(measured))

    def _seat_supported(rec: dict, why: str, *, displace: bool) -> None:
        """Reserve a seat for the best SUPPORTED-FEASIBLE candidate (INV-STAT16).

        The pool is ``recommendation.json["supported_feasible_candidate"]["pool"]``
        (best first): candidates every modelled constraint predicts confidently
        feasible and that lie inside the measured-admissible region for every
        unmodelled one. Without this seat nothing guarantees the terminal
        comparison tests even one candidate the evidence says is admissible --
        on a constraint-bound frontier every model-ranked finalist can be of
        uncertain feasibility, be measured infeasible, and leave a feasible
        improvement untested (two field campaigns; ``SURFACES[
        "deterministic_constraint_axis"]``).

        Walk the pool: a member already on the shortlist satisfies the
        reservation; one measured inadmissible, or (round r > 1) one an earlier
        round already measured -- it either lost or was retired by its bound --
        is skipped; the first remaining member is seated. Needs ``k >= 2``: at
        ``k == 1`` the one seat is the anchor the ladder exists to provide. When
        the shortlist is already full (``k == 2`` with both anchors seated) and
        ``displace`` is set, the seat takes the LAST model-ranked nomination's
        place -- never a measured one, so a measured leader seeded because the
        model is inadequate is never displaced. No pool -- no constraints
        declared, or nothing qualified -- is a no-op, so the shortlist is
        byte-identical to the one this seat did not exist for.
        """
        if not _SUPPORTED_FEASIBLE_SEAT or k < 2:
            return
        pool = (rec.get("supported_feasible_candidate") or {}).get("pool") or []
        retired = _previous_finalist_levels(work_dir) if rnd > 1 else []
        for p in pool:
            lv = dict(p.get("levels") or {})
            if not lv:
                continue
            if any(_same_levels(f, lv) for f in finalists):
                return
            if _measured_infeasible_contains(work_dir, lv) or any(
                    _same_levels(r, lv) for r in retired):
                continue
            if len(finalists) < k:
                _add(lv, why)
                return
            model_ranked = [i for i, m in enumerate(measured_seat) if not m]
            if not displace or not model_ranked:
                return
            i = model_ranked[-1]
            logger.info(
                "confirm round %d: the shortlist is full, so the reserved "
                "supported-feasible seat replaces model-ranked nomination %s (%s) "
                "with %s.", rnd, finalists[i], provenance[i], lv,
            )
            finalists[i], provenance[i], measured_seat[i] = lv, why, False
            return

    refill = rnd > 1 and _refill_round(pol, work_dir)

    def _seat_max_bound(rec: dict) -> None:
        """Seat the largest-model-bound challenger not yet seated (WP-A A1)."""
        for e in ((rec.get("residual_regret_model_profile") or {}).get("top") or []):
            lv = dict(e.get("levels") or {})
            if lv and not any(_same_levels(f, lv) for f in finalists):
                _add(lv, "largest model-bound challenger")
                return

    def _seat_refill_pool() -> None:
        """The REFILL branch's seats: ``_refill_candidates``, best first."""
        for lv_ in _refill_candidates(work_dir, factors):
            _add(lv_, f"round {rnd} refill: nearest measured neighbour admissible")

    if pareto_stage.objectives(pol):
        # ── MULTI-OBJECTIVE: seat the FRONT, not a winner's challengers ────
        #
        # Spec step 4 (round 1: per-objective measured extremes, predicted
        # extremes, the preferred point, then maximin spread) and step 6
        # (round r > 1: the previous preferred point, gap-fill candidates when
        # the front had a large gap, then possibly-dominated front points and
        # their predicted dominators). `_add` keeps its job: de-duplicate, cap
        # at `shortlist_size`, never re-seat a measured-inadmissible point.
        rec = _read_recommendation(work_dir) or {}
        if refill:
            prev_ = (_latest_confirmation(work_dir) or {}).get("pareto") or {}
            _add((prev_.get("preference") or {}).get("chosen"),
                 "previous round's preferred point", measured=True)
            _seat_refill_pool()
        for lv, why, measured in pareto_stage.shortlist_plan(
                pol, work_dir, rec, rnd,
                _latest_confirmation(work_dir) if rnd > 1 else None):
            if lv in finalists:
                continue
            if len(finalists) >= k:
                break
            _add(lv, why, measured=measured)
        _seat_supported(rec, "best supported-feasible candidate", displace=True)
        if not finalists:
            _add(pol.get("known_valid_baseline"), "known_valid_baseline",
                 allow_measured_invalid=True)
    elif rnd > 1:
        prev = _latest_confirmation(work_dir) or {}
        eps = prev.get("epsilon")
        by_key = {f["key"]: f for f in prev.get("finalists") or []}
        winner = by_key.get(prev.get("best") or "")
        if winner:
            _add(winner.get("levels"), "previous round's best", measured=True)
        # The fitted argmax stays on every round's shortlist (WP-A A1): the
        # certificate links the model bound to the winner through x_hat's
        # admissible measurement in THIS round, so retiring x_hat would make
        # every later round uncertifiable (model_recommendation_not_compared).
        _rec_now = _read_recommendation(work_dir) or {}
        if _rec_now.get("model_adequate", True) is not False:
            _add(_rec_now.get("levels"), "fitted argmax (links the model bound)",
                 measured=True)
        for f in prev.get("finalists") or []:
            bound = (prev.get("bounds") or {}).get(f["key"])
            # `None` is UNKNOWN, not "small": a challenger whose bound could
            # not be computed has not been shown to be out of contention, so it
            # stays in the shortlist. Only a bound that was computed AND came
            # in at or below epsilon retires a finalist.
            if f.get("status") == "ok" and (
                eps is None or bound is None or bound > eps
            ):
                _add(f.get("levels"), f"round {rnd - 1} bound above epsilon",
                     measured=True)
        if refill:
            _seat_refill_pool()
    if not finalists and not pareto_stage.objectives(pol):
        # The round-1 ladder, and also the recovery path for a round r > 1 whose
        # entire carry-over was excluded. Both want the same priority order, and
        # both are filtered against measured-invalid levels by `_add`.
        rec = _read_recommendation(work_dir) or {}
        # ── AN INADEQUATE MODEL DOES NOT GET TO ANCHOR THE SHORTLIST ─────────
        #
        # `recommendation.json["model_adequate"] is False` means the fitting
        # stage's lack-of-fit test rejected the registered response class. Its
        # `x_hat` is then the argmax of a surface the data refused, so it does not
        # get to be the point the terminal comparison is built around:
        # `_top_measured` SEEDS the shortlist instead — plural, because one
        # measured leader IS "the largest noisy observation" and re-measuring it
        # alone only says how repeatable it is, whereas several compared freshly
        # against each other is a model-free answer to which is better.
        #
        # WHAT IS DELIBERATELY *NOT* DROPPED: the model's ranked
        # `top_candidates`, which still fill whatever seats the measured leaders
        # leave. READ THE NEXT PARAGRAPH BEFORE "FIXING" THIS — the obvious
        # objection ("spec §3.6 rung 3 says MEASURED candidates, so why is a
        # model-ranked point on the shortlist at all?") rests on applying rung 3
        # to the wrong mechanism.
        #
        # RUNG 3 GOVERNS THE REPORT LADDER, NOT SHORTLIST CONSTRUCTION. "A small
        # reserved budget remeasures the leading measured valid candidates rather
        # than choosing the largest noisy observation" is a rule about what
        # `report.json`'s `basis` may hand back as the campaign's ANSWER, and
        # `_run_report` already honours it unconditionally: the `model` rung is
        # the only one resting on the fitted surface, and it is the one suppressed
        # on `epoch_ended`. Confirm's shortlist is a different mechanism at a
        # different stage. "Measured" here is a POSTCONDITION, not a
        # precondition: every finalist is measured freshly before it can win —
        # that is the entire content of terminal discrimination (spec §3.3, "the
        # final comparison does not rest on the fitted surface") — so seating a
        # model-ranked candidate does not TRUST the model's prediction, it TESTS
        # it, and `_finish_confirm` excludes it outright if a replicate comes back
        # invalid. Whatever survives confirm is by construction a measured valid
        # candidate, so rung 3's actual constraint (never return an unmeasured
        # point) holds regardless of how the candidate was nominated. Turning it
        # into a nomination filter would be a different, stronger rule that
        # neither the paper nor the spec states.
        #
        # And it would cost the campaign its only way to improve. Measured, not
        # reasoned: with the ranking cut, `SURFACES["sla"]` certifies at 6.12% off
        # the true constrained optimum at 3, 5 AND 8 confirm rounds — the extra
        # budget buys literally nothing, because a measured-only shortlist can only
        # re-seat what is already on disk — whereas keeping it reaches 1.02% in
        # three rounds. On `SURFACES["bowl"]` cutting it discards the interior
        # optimum `{A: 9, B: 11}` that the refine stage was spent to find and
        # confirms the centre point instead. Note also what an "inadequate" verdict
        # here actually is: a statistical one. It used to read F ~ 1000 on these
        # near-noiseless surfaces, and most of that was NOT the model class: the
        # fit regressed on the nominal axial coordinates (+-1.41/1.68) that
        # `decode_coded` clamps to the range edge, and coded a choice factor's
        # centre row 0 where it ran at -1 -- an errors-in-variables bias that
        # INV-STAT14 removed (a truly linear surface now rejects at ~alpha). What
        # remains is centre-point replication under-stating the variance the
        # campaign faces (spec §3.5's own warning). Seating the measured leaders
        # ABOVE the ranking discounts it; discarding the ranking would treat that
        # F as proof the ordering carries no information at all.
        #
        # DEFAULTS TO TRUE for an absent key. Every recommendation written before
        # this field existed came from a stage that had no lack-of-fit verdict
        # recorded here, and treating "not stated" as "inadequate" would silently
        # switch every such campaign's terminal stage to a different shortlist.
        # Three-valued (stage-1b N1): only a REJECTED model (False) seeds the
        # shortlist from measured leaders; UNKNOWN (None) shortlists like an
        # adequate one -- its ranking was not rejected and every finalist is
        # re-measured -- and certification is withheld for it instead.
        model_ok = rec.get("model_adequate", True) is not False
        if model_ok:
            _add(rec.get("levels"), f"{rec.get('stage') or 'model'} recommendation")
            best = _best_observed(work_dir, primary, direction=direction)
            if best is not None:
                _add(best["levels"], "best measured valid configuration",
                     measured=True)
        else:
            logger.info(
                "confirm round %d: the fitting stage reported model_adequate="
                "false (its lack-of-fit test, or an objective model's, rejected), "
                "so the shortlist is SEEDED from the "
                "leading MEASURED valid configurations rather than from the "
                "model's argmax — the terminal comparison must not be anchored "
                "on a surface the data rejected. The model's ranked candidates "
                "still fill any remaining seat: every finalist is measured "
                "freshly before it can win, so seating one TESTS the model "
                "rather than trusting it, and they are the only source of points "
                "the campaign has not already run.", rnd,
            )
            for m in _top_measured(
                work_dir, primary, direction=direction, k=_measured_seats(k),
            ):
                _add(m["levels"], "leading measured valid candidate "
                                  "(model inadequate)", measured=True)
        # After the anchors, BEFORE the model's ranking fills the rest: the
        # reserved seat for a candidate whose feasibility the evidence supports.
        _seat_supported(rec, "best supported-feasible candidate", displace=True)
        # WP-A A1: the challenger whose MODEL bound is largest gets the next
        # seat. The certificate needs the model bound over the candidates
        # OUTSIDE the shortlist to be within epsilon, and this is the one
        # candidate that keeps it largest (spec section 3.6 rung 2: "the point
        # the next experiment should be directed at"); measuring it moves its
        # term from the model family to the model-free terminal family.
        if model_ok:
            _seat_max_bound(rec)
        for c in rec.get("top_candidates") or []:
            _add(c.get("levels"), "model top candidate")
        if not finalists:
            _add(pol.get("known_valid_baseline"), "known_valid_baseline",
                 allow_measured_invalid=True)
    elif rnd > 1 and len(finalists) < k and not pareto_stage.objectives(pol):
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
        # top-3 violates the p99 constraint and only a measurement can say so:
        # sla's p99 is deterministic, so its constraint model has no pure error
        # and stays UNMODELLED (`recommendation.json["constraint_models"]` says
        # so). Round 1 excludes all three, and round 2 draws the next candidates
        # down the ranking — which is how the campaign reaches the true
        # CONSTRAINED optimum rather than settling for the one feasible corner
        # that happened to be on the first shortlist.
        #
        # When a constraint IS modelled (pure error, no lack of fit), the fitting
        # stage has already removed every CONFIDENTLY infeasible candidate from
        # `top_candidates` — including interior points of a region that measured
        # infeasible, which the exact-match `_measured_infeasible` skip cannot
        # see (`SURFACES["infeasible_corner_interior"]`, and the field campaign
        # that lost a round to it). What reaches this pool is then either
        # predicted feasible or UNCERTAIN, and an uncertain candidate is exactly
        # what a confirm round is for. The exact-match skip stays: it is the
        # backstop for every unmodelled constraint and for model error.
        invalid = _measured_infeasible(work_dir)
        rec = _read_recommendation(work_dir) or {}
        if rec.get("model_adequate", True) is False:
            # Same priority as the round-1 ladder: an inadequate model does not
            # get first pick, so measured leaders go in ahead of its ranking. The
            # ranking still follows, for the reason the ladder above records at
            # length — spec §3.6 rung 3 constrains what the REPORT may return, not
            # who may be nominated to a shortlist whose members are all measured
            # freshly anyway, and the ranking is the only source of candidates the
            # campaign has not already run.
            for m in _top_measured(
                work_dir, primary, direction=direction, k=_measured_seats(k),
            ):
                _add(m["levels"],
                     f"round {rnd} top-up from measured leaders "
                     f"(model inadequate)", measured=True)
        _seat_supported(rec, f"round {rnd} top-up: best supported-feasible "
                             f"candidate", displace=False)
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
        _why_base = ("no optimization.known_valid_baseline to fall back on"
                     if not pol.get("known_valid_baseline") else
                     "the known_valid_baseline was not seated (already a finalist "
                     "or the list was full)")
        raise OptimizationAborted(
            f"confirm has no finalist to measure: nothing on the ladder survived "
            f"— no seatable recommendation or ranked candidate, no completed run "
            f"to name a best measured configuration, and {_why_base}. "
            + (f"Candidates naming lost/inadmissible categorical levels {barred} "
               f"are never seated. " if barred else "")
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

    # ── WP-A A3: the known_valid_baseline is a PERMANENT reference finalist ──
    #
    # Single-objective only, every round, ONE seat beyond `shortlist_size` when
    # it is not already a finalist. Its replicates share the round's workload
    # seeds (replicate i of every finalist runs draw i), so under
    # `workload.seed_env` the gain over it is a CRN-paired comparison, and
    # report.json's `gain_over_baseline` is a selection-proof simultaneous
    # interval over these fresh replicates (spec 2026-10-17-certification-
    # soundness.md section 5). It competes like any finalist: if it wins, it is
    # the answer. Exempt from the lost/inadmissible bar like every other
    # baseline seat.
    _base = pol.get("known_valid_baseline")
    if (_base and finalists and not pareto_stage.objectives(pol)
            and not any(_same_levels(dict(f), dict(_base)) for f in finalists)):
        finalists.append(dict(_base))
        provenance.append("known_valid_baseline (permanent reference seat)")
        measured_seat.append(True)

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
    # The iteration under derivation 1 (old policies), the concealed seed under 2.
    _ros = policy_mod.run_order_seed(pol, iteration)
    for i in range(r):
        for j in randomized_run_order(len(finalists), seed=_ros * 1000 + i):
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
        "run_order_seed": _ros,
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

    EPOCH-SCOPED (``_this_epoch_runs``): a recompiled epoch is a new
    pre-registration with its own error budget, so an earlier epoch's
    certificate never answers for it -- otherwise an epoch that ended before
    confirming reported the previous epoch's certified finalist, bound and
    front as its own. The earlier result stays in its own iteration's
    artifacts and in ``report.json["error_budget"]``.
    """
    import json

    if work_dir is None:
        return None
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return None

    for d in reversed(_this_epoch_dirs(work_dir)):
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


def _build_design(factors, design_cfg: dict, stage_name: str, *,
                  fold_on: str | None = None):
    """Design for this stage: a screen matrix, or a response surface.

    Takes no ``work_dir``. It used to, solely so the confirm branch could read
    the previous stage's stationary point off disk and encode it as coded
    coordinates — the indirection that let ``role="center"`` discard the point
    silently. Confirm's target is now applied to the ROWS by ``run_stage``
    (from ``recommendation.json``), so design generation is a pure function of
    the factors and the config again, which is what makes it comparable across
    stages in a test without a filesystem.

    ``fold_on`` keeps that property for the foldover state too. The state needs
    to know WHICH column to negate, and that choice comes from the screen's
    recorded ``alias_consequential`` pairs — which live on disk. Rather than
    re-admitting ``work_dir`` here (and with it the whole class of "generation
    silently depends on what some earlier artifact said"), ``run_stage``
    resolves the factor id and passes it in, so this function stays a pure
    function of its arguments and the choice is visible at the call site.
    """
    from orchestrator.optimize.design import (
        central_composite,
        foldover,
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
        ccd = central_composite(
            refinable, center_points=int(cfg.get("center_points", 4)),
        )
        # WP-B B1: the registered off-lattice VALIDATION points, appended LAST
        # (so every CCD row keeps its position and row_index) and held out of
        # the fit. Coded +-0.5 on every refinable axis, chosen by seeded
        # maximin (adequacy.validation_points). `validation_points: 0` builds
        # the plain composite, byte-identical to before.
        from orchestrator.optimize import adequacy as _adq
        from orchestrator.optimize.design import Design as _D, DesignPoint as _P

        m = _adq.n_validation_points(cfg, len(refinable))
        if m:
            vp = _adq.validation_points(len(refinable), m,
                                        int(cfg.get("validation_seed", 0)))
            ccd = _D(points=ccd.points + tuple(
                _P(coded=c, role="validation", replicate=i) for i, c in enumerate(vp)),
                factor_ids=ccd.factor_ids, kind=ccd.kind, resolution=ccd.resolution)
        return ccd
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
    from orchestrator.optimize.factors import is_categorical

    if any(is_categorical(f) for f in factors):
        # A multi-level categorical: the METHOD OF REPLACEMENT (spec
        # 2026-10-16 feature 1) -- m = ceil(log2 L) pseudo-factor columns with
        # the factor-counted resolution guaranteed by construction. Every pure
        # two-level campaign keeps the textbook path below, byte-identical.
        from orchestrator.optimize.design import mixed_screen

        screen = mixed_screen(factors, resolution=resolution,
                              center_points=int(cfg.get("center_points", 4)))
    else:
        base = (
            fractional_factorial(ids, resolution=resolution)
            if is_tabulated(len(ids), resolution)
            else full_factorial(ids)
        )
        screen = with_center_points(base, int(cfg.get("center_points", 4)))
    if stage_name != Stage.FOLDOVER.value:
        return screen
    # The fold block is derived from the SCREEN design, deterministically, from
    # the same config — so it is reproducible from `design_matrix.json` without
    # having to have kept the screen's Design object alive across the process
    # boundary between iterations.
    return foldover(screen, on=fold_on)


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

    ``paired`` comes from the payload, where ``_assign_workload_seeds`` sets it
    exactly when the campaign declared ``optimization.workload.seed_env`` — i.e.
    when replicate *i* of every finalist actually ran the same workload seed
    (common random numbers, spec §3.8). It is then forwarded to
    ``certificate.terminal_regret_bound``, which computes the bound on paired
    DIFFERENCES rather than Welch-combining two independent variances; the
    workload's contribution cancels and the bound shrinks substantially.

    The forwarding is the load-bearing part: pairing that reached only the
    artifact would leave the campaign reporting the wider bound while claiming
    the narrower method. ``RegretBound.method`` records which arithmetic ran
    (``bonferroni_one_sided_t_paired`` vs ``bonferroni_one_sided_welch_t``), so
    the two cannot silently disagree on disk.

    A campaign with NO ``workload`` block gets ``paired: False`` and the Welch
    form — deliberately, though the reason is efficiency and provenance rather
    than soundness. The paired form is not overconfident when the seeds were not
    actually shared: it computes its variance from the OBSERVED differences, so
    a cancellation that never happened simply never shows up as a smaller
    spread, and the bound stays valid at nominal coverage (verified by
    simulation over 6000 falsely-paired trials). What it does lose is
    efficiency — the paired t spends n-1 degrees of freedom on a common term
    that was not there, where the Welch form spends closer to 2n-2 — and,
    worse, ``RegretBound.method`` would then read
    ``bonferroni_one_sided_t_paired`` about an experiment that never paired
    anything. Defaulting to Welch keeps the recorded method true to what
    happened; a mislabelled method costs a reader their ability to audit the
    number even when the number itself is fine.

    Recorded in ``confirmation.json`` so a reader can tell which bound they are
    looking at rather than inferring it from the branch date.
    """
    from statistics import mean, pstdev

    from orchestrator.iteration import _enter_phase, finalize_iteration
    from orchestrator.ledger import append_ledger_row
    from orchestrator.optimize import artifacts, relations

    # ALPHA-SPENDING OVER CONFIRM LOOKS (WP-A A2, spec
    # 2026-10-17-certification-soundness.md). Every round evaluates
    # `certified` and stops on it, so every round is a look; judging each at
    # the full delta_terminal let 4 rounds certify wrongly at 0.108 against a
    # nominal 0.05. Each look is taken at delta_terminal / confirm_looks (the
    # registered round cap, plus the one refill look when that branch is
    # registered), so by the union bound the probability that ANY look's
    # simultaneous family fails is <= delta_terminal. The max with the round
    # number is a backstop: no round is ever judged at more than
    # delta_terminal / rounds spent. Multi-objective uses the same divisor.
    delta_t_declared = float(pol["objective"]["delta_terminal"])
    looks = policy_mod.confirm_looks(pol)
    delta_t = delta_t_declared / max(1, looks, int(payload.get("round") or 1))
    direction = pol["objective"]["direction"]
    sign = 1.0 if direction != "minimize" else -1.0
    paired = bool(payload.get("paired"))
    fin = payload.get("finalists") or []

    by_idx = {r.row_index: r for r in rows}
    samples: dict[str, list[float]] = {f["key"]: [] for f in fin}
    # Multi-objective: every objective's replicates per finalist, for
    # confirmation.json's `means` (C2). None for a single-objective campaign,
    # whose finalists keep exactly the fields they always had.
    mo_samples = ({f["key"]: {o.metric: [] for o in pareto_stage.objectives(pol)}
                   for f in fin} if pareto_stage.objectives(pol) else None)
    status: dict[str, str] = {f["key"]: "ok" for f in fin}
    for o, y in zip(outcomes, ys):
        row = by_idx.get(o.row_index)
        if row is None:
            continue
        key = f"f{(row.apply or {}).get('finalist', 0)}"
        if key not in samples:
            continue
        # Multi-objective: a replicate that measured objective 1 but not
        # another objective is not a measurement of the trade-off -- the
        # finalist is UNMEASURED, exactly like a timed-out one.
        _mo_lacking = o.status == "complete" and y == y and any(
            not (isinstance((o.response or {}).get(_ob.metric), (int, float))
                 and not isinstance((o.response or {}).get(_ob.metric), bool)
                 and math.isfinite((o.response or {}).get(_ob.metric)))
            for _ob in pareto_stage.objectives(pol))
        if o.status != "complete" or y != y or _mo_lacking:
            # WHY the finalist dropped out, not merely THAT it did. Collapsing
            # every non-complete status into one bucket reported a finalist that
            # TIMED OUT under `excluded_infeasible` -- i.e. as though it had
            # violated a declared constraint. Those are opposite claims about a
            # configuration: `infeasible` says the config is inadmissible and is
            # real information about the design space (spec §6.4), while a
            # timeout says the instrument could not measure an admissible config
            # and a re-run may well repair it. An author reading "excluded as
            # infeasible" strikes the configuration off; an author reading
            # "failed to measure" re-runs it with a larger budget.
            #
            # STICKY toward `infeasible`: one inadmissible replicate settles the
            # question for the configuration, and a later replicate that merely
            # timed out must not downgrade it to "unmeasured" -- that relabel
            # turned a measured inadmissible finalist into an unmeasured
            # admissible rival, nulled R_terminal, and told the author to re-run
            # a configuration the data had already struck off.
            if status.get(key) != "infeasible":
                status[key] = (
                    "infeasible" if o.status in ("infeasible", "rejected")
                    else "unmeasured"
                )
        else:
            samples[key].append(float(y))
        if mo_samples is not None and o.status == "complete":
            for _ob in pareto_stage.objectives(pol):
                _v = (o.response or {}).get(_ob.metric)
                if isinstance(_v, (int, float)) and not isinstance(_v, bool) \
                        and math.isfinite(_v):
                    mo_samples[key][_ob.metric].append(float(_v))
    # Any non-"ok" status is out of the running, whatever its reason: the
    # terminal comparison needs fresh usable samples and neither an inadmissible
    # nor an unmeasured finalist has them. The reason survives for the REPORT.
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

    # AN UNMEASURED FINALIST MAKES THE TERMINAL BOUND UNKNOWN, NOT SMALLER.
    #
    # `R_t = max_{z in S} U_t(z, x)`. An INADMISSIBLE finalist is outside X_valid,
    # so dropping it from the max is correct (the bound is over valid rivals). An
    # UNMEASURED one is not: it is an admissible member of S whose `U_t` the
    # instrument never produced, and the max over a set containing an unknown
    # term is unknown. Taking the max over the survivors instead UNDERSTATES the
    # regret exactly when it matters -- on `SURFACES["fails_at_one_level"]` the
    # unmeasured finalist IS the true optimum, and the survivors-only bound read
    # 0.0 while the recommended configuration sat 0.64 below it. It is also the
    # contract `terminal_regret_bound` itself states ("value=None when any
    # finalist has fewer than two replicates"), which filtering to `ok` first
    # used to bypass. An unknown is not a zero (INV-SEM02).
    #
    # The survivors-only bound is still a real comparison that happened, so it
    # is kept -- under a name that says what it covers, never as the bound.
    unmeasured = sorted(
        k for k in samples
        if status[k] == "unmeasured" or (status[k] == "ok" and not samples[k])
    )
    measured_only = None
    if unmeasured and bound.value is not None:
        measured_only = bound
        bound = certificate.RegretBound(
            None, None, delta_t, "none",
            f"finalist(s) {unmeasured} in the shortlist produced no usable "
            f"measurement, so their terminal bound -- and hence the max over "
            f"the shortlist -- is unknown, and an unknown is not a zero. Over "
            f"the measured finalists only, the bound is {measured_only.value!r} "
            f"(terminal_bound_measured_only); that number is silent about the "
            f"unmeasured rival(s) and is not R_terminal.",
        )
    primary_spec = (
        _primary_of((campaign.get("optimization") or {}).get("response"))
    )
    metric = primary_spec.get("metric") or ""
    eps, eps_ref = _confirm_epsilon(
        pol["objective"]["epsilon"], work_dir, metric, direction=direction,
        best_levels=next((f["levels"] for f in fin if f["key"] == best), None),
        best_value=mean(ok[best]) if best else None,
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
    # ── the SAME premise, broken the same way, by a level-correlated loss ───
    #
    # `delta_s` carries the premise that screening did not exclude the true
    # optimum, i.e. that the model's candidate ranking tracks the objective well
    # enough for the top of it to contain the winner. An inadmissible finalist is
    # one kind of evidence against that premise (below). A LEVEL-CORRELATED
    # exclusion in the fit that produced the ranking is another kind of the SAME
    # evidence, and it is strictly upstream: the ranking was computed from a
    # coefficient the missing region BIASES, in a named direction, for a named
    # factor. On the field case that motivated this, every row lost sat at one
    # level of the eviction-policy factor while the same corner at the other
    # level completed — so the fitted eviction effect was biased against exactly
    # the level the mechanism under study exists to evaluate, and a shortlist
    # seated from that ranking carries no reason to contain the constrained
    # optimum.
    #
    # So it suppresses GLOBAL certification for the same reason and by the same
    # mechanism, and — like the exclusion case — leaves `bound` and
    # `residual_regret_terminal` UNTOUCHED. Those are the within-shortlist
    # numbers, they are valid as such (they rest on fresh measurements of the
    # finalists and consult no model at all), and suppressing them would hide the
    # comparison that genuinely did happen. What is withheld is the GLOBAL label,
    # which is the only claim the fitted surface underwrites.
    #
    # Read off `recommendation.json` rather than recomputed: the Fit is gone by
    # now, exactly as with `model_adequate`. A campaign that reached the terminal
    # state straight from a complete screen has no such record, and `False` is
    # then the right reading — there were no exclusions to correlate.
    #
    # NOT a policy branch. This changes what the campaign CLAIMS, never where it
    # goes: the registered `confirm -> confirm` / `confirm -> report` transitions
    # are untouched, and `certified` is an observation the compiled policy already
    # reads.
    # THIS epoch's latest fitting record (as everywhere else in the report and
    # confirm paths): safe today only because every epoch begins at `screen`,
    # which writes a fresh record -- reading the epoch's own makes that
    # independent of the stage order.
    _rec_for_bias = (_epoch_recommendations(work_dir) or [{}])[-1]
    fit_bias = bool(
        (_rec_for_bias.get("exclusion_balance") or {}).get("level_correlated"),
    )
    # ── the SAME premise, with no model behind it at all: lack of fit ───────
    #
    # `recommendation.json["model_adequate"] is False` means the latest fitting
    # stage's lack-of-fit F on pure error REJECTED the registered response
    # class. The shortlist was then seeded from measured leaders plus the
    # ranking of a surface the data refused (`_confirm_rows`), so nothing
    # supports `delta_s`'s premise that screening did not exclude the winner:
    # the true optimum need never have been measured or ranked anywhere near
    # the top. Spec §3.6 places "model inadequate" BELOW rung 1 -- re-measure
    # the leading measured valid candidates and return the best -- and the
    # spec's own §3.3 says the remaining global claim after terminal
    # discrimination is ONLY that screening did not exclude the winner. With
    # the model rejected that claim is unearned, so certification is withheld
    # (`model_inadequate`) while the within-shortlist bound is still reported.
    #
    # Measured on `SURFACES["geometric_knob"]` (linear coding of a log-bowl):
    # screen and refine both reject (p~3.5e-7, p~0.002), the shortlist is the
    # best centre point and its neighbours, and that point is 26.2 (26%) below
    # the true optimum -- certified epsilon-optimal on every seed before this.
    #
    # Absent key reads as adequate (records predating the field), matching
    # `_confirm_rows`. Like `fit_bias`, this changes what the campaign CLAIMS,
    # never where it goes.
    model_inadequate = _rec_for_bias.get("model_adequate") is False
    # UNKNOWN adequacy (stage-1b N1): withhold, naming WHY it is unknown. An
    # absent key still reads as adequate (records predating the field).
    adequacy_unknown = ("model_adequate" in _rec_for_bias
                        and _rec_for_bias["model_adequate"] is None)
    adequacy_reason = str(_rec_for_bias.get("model_adequate_basis")
                          or "model_adequacy_unknown")
    # EVERY non-"ok" status counts, and the reason is a bug this line already
    # caused once. The statuses were split into "infeasible" (measured
    # inadmissible) and "unmeasured" (the instrument failed on an admissible
    # config) so a timed-out finalist would stop being reported as though it had
    # violated a constraint. This comparison still read the retired literal
    # "excluded", so `n_excluded` silently became 0 for every campaign: nothing
    # withheld certification, the registered `confirm -> confirm` top-up never
    # fired, and the sla surface certified round 1's 6.12%-off answer.
    #
    # Both reasons must gate `certified`, for the same reason and by different
    # arguments. An INADMISSIBLE finalist is direct evidence against `delta_s`'s
    # premise that screening did not exclude the true optimum. An UNMEASURED one
    # leaves the terminal comparison with no fresh samples for that candidate at
    # all, so the shortlist it was drawn from was never actually compared. Either
    # way the global epsilon-optimality claim over X_valid is unearned. After an
    # inadmissible finalist `residual_regret_terminal` remains a valid number
    # over the admissible shortlist; after an unmeasured one it is None (see the
    # `unmeasured` block above), and the survivors-only number is recorded as
    # `terminal_bound_measured_only`.
    n_excluded = sum(1 for v in status.values() if v != "ok")
    # ── an infeasible finalist as a CAVEAT rather than a veto (evaluated) ────
    #
    # See `_INFEASIBLE_FINALIST_CAVEAT`. When on, a finalist measured
    # inadmissible no longer withholds certification provided at least two
    # admissible finalists remain, the simultaneous bound over THEM is within
    # epsilon, and the model was adequate; it is then recorded under
    # `certification_caveats`. Unmeasured finalists still veto (their bound is
    # unknown, not small).
    n_infeasible = sum(1 for v in status.values() if v == "infeasible")
    _within_now = bound.value is not None and eps is not None and bound.value <= eps
    infeasible_caveat = bool(
        _INFEASIBLE_FINALIST_CAVEAT and n_infeasible and len(ok) >= 2
        and _within_now and not model_inadequate
    )
    # A REFILLED shortlist inherits the premise failure that vacated it: the
    # round before measured the model's ranking handing out inadmissible
    # finalists, so `delta_s`'s "screening did not exclude the winner" is no
    # better supported because the replacements happen to be admissible.
    # Measured on SURFACES["sla"]: certifying the refill round certified 6/8
    # seeds 0.4 below the true constrained optimum (epsilon 0.38). The refill
    # buys a better ANSWER (1.2 -> 0.4 below) under `terminal_best`. Only the
    # REFILL round itself is barred: a later registered round (round cap
    # permitting) re-ranks and tops up as it always did, and can certify.
    refilled = _refill_round(pol, work_dir)
    # ── THE delta_s HALF OF THE CERTIFICATE (WP-A A1) ──────────────────────
    #
    # `R_terminal <= eps` says the winner w is eps-optimal WITHIN the
    # shortlist S. The global claim also needs the model half, linked to w
    # (spec 2026-10-17-certification-soundness.md section 2). Let x* be the
    # best candidate of the fitted space, x_hat the fitted argmax, i* the
    # best admissible finalist. E_s: every comparison of x* against another
    # candidate is covered by the model family (Bonferroni over all M
    # challengers, so it holds for the data-chosen x_hat; Hsu's MCB argument),
    # Pr >= 1 - delta_screen under the registered response class. E_t: every
    # comparison of i* against another finalist is covered by this look's
    # terminal family, Pr >= 1 - delta_terminal / looks. On E_s and E_t:
    #   x* in S:      f(x*) - f(w) <= f(i*) - f(w) <= R_terminal
    #   x* not in S:  f(x*) - f(w) = [f(x*) - f(x_hat)] + [f(x_hat) - f(w)]
    #                 <= R_model_out + R_terminal       (x_hat admissible in S)
    # where R_model_out is the model bound over the candidates OUTSIDE S.
    # So `certified` requires G = R_model_out + R_terminal <= eps, and x_hat
    # MEASURED admissibly this round (else withheld, named). Not computed when
    # the model is already rejected or of unknown adequacy (those withhold on
    # their own). Measured before this: 17 of 621 certificates wrong on the
    # stage-0 noise sweep, every one with R_model far above eps.
    global_bound, model_reasons = _global_bound(
        _rec_for_bias, fin, status, ok, best, bound, eps, delta_t=delta_t,
        skip=model_inadequate or adequacy_unknown,
        delta_s=float(pol["objective"]["delta_screen"]),
        xhat_measured_infeasible=bool(_rec_for_bias.get("levels")) and
        _measured_infeasible_contains(work_dir, dict(_rec_for_bias["levels"])))
    certified = (
        bound.value is not None and eps is not None and bound.value <= eps
        and not (n_excluded - (n_infeasible if infeasible_caveat else 0))
        and not fit_bias and not model_inadequate and not refilled
        and not adequacy_unknown
        and (bool(pareto_stage.objectives(pol)) or not model_reasons)
    )
    # NO ADMISSIBLE FINALIST is its own reason, not `bound_not_computable`. Every
    # finalist was MEASURED (numerically, completely) and every one had at least
    # one replicate violating a declared constraint, so nothing is unknown about
    # the bound for want of data: there is simply no admissible configuration in
    # this shortlist to bound. Naming it lets a reader tell "re-fill the
    # shortlist from deeper in the ranking / relax the constraint" from "the
    # instrument produced too little to estimate a bound".
    no_admissible = bool(fin) and all(v == "infeasible" for v in status.values())
    within = bound.value is not None and eps is not None and bound.value <= eps
    if fit_bias and within and not n_excluded:
        logger.info(
            "confirm: R_terminal=%.6g is at or below epsilon=%.6g over the "
            "finalists, which is a valid WITHIN-SHORTLIST result and is reported "
            "as such. Not certifying globally: the fit that produced this "
            "shortlist excluded rows in a way that was NOT independent of the "
            "factor levels (%s), so its coefficients are biased by the missing "
            "region rather than merely widened by it, and the delta_screen "
            "premise behind Pr(wrong global decision) <= delta_s + delta_t does "
            "not hold. Re-measure the excluded region in a new epoch to earn the "
            "global claim.",
            bound.value, eps,
            (_rec_for_bias.get("exclusion_balance") or {}).get("flagged_factors"),
        )
    if n_excluded and within:
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
        "round": payload.get("round", _confirm_round(work_dir, pol)),
        "finalists": [
            {"key": f["key"], "levels": f["levels"], "why": f.get("why"),
             "samples": samples[f["key"]],
             "mean": mean(samples[f["key"]]) if samples[f["key"]] else None,
             "n": len(samples[f["key"]]), "status": status[f["key"]],
             **({"means": {m: (sum(v) / len(v) if v else None)
                           for m, v in mo_samples[f["key"]].items()}}
                if mo_samples is not None else {})}
            for f in fin
        ],
        "best": best,
        "bounds": bounds,
        "epsilon": eps,
        # WHICH reference the declared percentage was taken of. Normally the
        # winning finalist's mean; when no finalist is admissible there is no
        # winner, and resolving the percentage against nothing gave epsilon = 0
        # — a width that can never certify and that the author never declared.
        "epsilon_reference": eps_ref,
        "residual_regret_terminal": bound.value,
        "terminal_bound": bound.as_dict(),
        "certified": certified,
        # Always written, empty when certified, so `certified: false` is never an
        # unexplained boolean. The premise-breaking reasons are named separately
        # from "the bound was simply too wide": a reader deciding what to do next
        # needs to know whether to spend more replicates (wide bound) or to
        # re-measure a region in a new epoch (broken premise).
        #
        # `finalist_measured_infeasible` and `finalist_unmeasured` are kept
        # apart for the same reason the finalist statuses are: one says strike
        # the configuration off, the other says re-run it.
        "certification_withheld": [
            r for r, hit in (
                ("no_admissible_finalist", no_admissible),
                ("bound_not_computable",
                 bound.value is None and not no_admissible),
                ("bound_above_epsilon",
                 bound.value is not None and eps is not None
                 and bound.value > eps),
                ("finalist_measured_infeasible",
                 any(s == "infeasible" for s in status.values())
                 and not infeasible_caveat),
                # A certificate needs at least one MEASURED-FEASIBLE rival: with
                # every other finalist inadmissible, R_terminal = 0 bounds the
                # winner against nothing (a real campaign: 2 of 3 finalists
                # infeasible, R_terminal 0, rightly withheld). Named so the
                # remedy -- refill the vacated seats -- is legible.
                ("no_feasible_rival",
                 any(s == "infeasible" for s in status.values()) and len(ok) == 1),
                ("shortlist_refilled", refilled),
                ("finalist_unmeasured", bool(unmeasured)),
                ("fit_exclusions_level_correlated", fit_bias),
                ("model_inadequate", model_inadequate),
                (adequacy_reason, adequacy_unknown),
            ) if hit
        ] + ([] if pareto_stage.objectives(pol) else model_reasons),
        # The certificate's two halves and how they combine (WP-A A1).
        **({"global_bound": global_bound} if global_bound is not None
           and not pareto_stage.objectives(pol) else {}),
        # Alpha-spending over confirm looks (WP-A A2): `delta_terminal` below
        # is the PER-LOOK level this round's bound is stated at.
        "alpha_spending": {
            "delta_terminal_declared": delta_t_declared, "looks": looks,
            "per_look": delta_t,
            "rule": "Bonferroni over the registered confirm looks: "
                    "delta_terminal / (confirm_max_rounds + 1 if the refill "
                    "branch is registered)"},
        **({"terminal_bound_measured_only": measured_only.as_dict()}
           if measured_only is not None else {}),
        **({"certification_caveats": ["finalist_measured_infeasible"]}
           if infeasible_caveat else {}),
        "paired": paired,
        "delta_terminal": delta_t,
        # Name kept for the readers that already exist, and now it is TRUE:
        # only genuinely inadmissible finalists appear here.
        "excluded_infeasible": [
            f["levels"] for f in fin if status[f["key"]] == "infeasible"
        ],
        #: Finalists whose measurement failed (timeout, crash, unparseable
        #: output) rather than being inadmissible. A re-run with a larger budget
        #: may recover these; striking them off the design would be wrong.
        "excluded_unmeasured": [
            f["levels"] for f in fin if status[f["key"]] == "unmeasured"
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

    if pareto_stage.objectives(pol):
        certified, mo_reasons = _finish_confirm_pareto(
            pol, work_dir, summary, rec=_rec_for_bias, status=status, ok=ok,
            unmeasured=unmeasured, fit_bias=fit_bias,
            model_inadequate=model_inadequate,
            adequacy_unknown=(adequacy_reason if adequacy_unknown else None),
        )

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
    maximize = direction != "minimize"
    best_obs = (
        _best_observed(work_dir, metric, direction=direction)
        # Multi-objective: "the winner beat the best observed first objective"
        # is a single-objective question; the measured front answers the real
        # one, so the comparison (and its mis-specification warning) is skipped.
        if metric and "pareto" not in summary else None
    )
    if best_obs is not None and summary["mean"] is not None:
        best_val = best_obs.get(metric)
        if isinstance(best_val, (int, float)):
            confirmed_mean = summary["mean"]
            # The SAME configuration is not a rival. `_best_observed` returns the
            # best single row, so when that row belongs to the winner it is the
            # winner's own luckiest replicate, and comparing the winner's mean to
            # it reported "WORSE than the best configuration already observed --
            # treat the surface as mis-specified" about a configuration against
            # itself (found on a real campaign, gap 0.36%, inside the noise).
            same_config = dict(best_obs.get("levels") or {}) == dict(winner_levels)
            beats = same_config or (
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
                within_eps = isinstance(eps, (int, float)) and gap <= eps
                summary["regression_vs_best_observed"] = {
                    "absolute": gap, "percent": pct,
                    # A single earlier row is an upward-biased estimate of its
                    # configuration (winner's curse), and epsilon is the
                    # campaign's own indifference width: a gap inside it is
                    # recorded, not raised as evidence against the surface.
                    "within_epsilon": bool(within_eps),
                }
                (logger.info if within_eps else logger.warning)(
                    "confirm: the winning finalist (%s=%.6g) is WORSE than the "
                    "best configuration already observed (%.6g at %s) — a gap "
                    "of %.6g (%.2f%%). Treat the observed corner as the "
                    "campaign's answer and the surface as mis-specified.",
                    metric or "response", confirmed_mean, best_val,
                    best_obs.get("levels"), gap, pct,
                )

    # WP-A A3: the gain of the winner over the permanent baseline seat, from
    # THIS round's fresh replicates, as a simultaneous interval that stays
    # valid although the winner was chosen from the same data.
    _gain = _gain_over_baseline(pol, fin, ok, best, delta=delta_t,
                                paired=paired, direction=direction)
    if _gain is not None:
        # The interval is computed at this look's level, but it is REPORTED
        # from the round where the campaign stopped, and stopping depends on
        # that round's data: over the registered looks the guaranteed coverage
        # is 1 - delta_terminal (the declared budget, a union over looks), not
        # 1 - delta_t/L. Record both; the guaranteed one is what is printed.
        _gain["delta_per_look"] = _gain.get("delta")
        _gain["delta_guaranteed"] = float(pol["objective"]["delta_terminal"])
        summary["gain_over_baseline"] = _gain

    # The refill branch's candidate pool, read BEFORE confirmation.json is
    # written so anything it could not read is recorded there (B4).
    _refill_cands: list = []
    if any(v == "infeasible" for v in status.values()) and any(
            t.get("accounting") == policy_mod.REFILL_ACCOUNTING
            for t in pol.get("transitions") or []):
        _refill_warnings: list = []
        _refill_cands = _refill_candidates(work_dir, factors, _refill_warnings)
        if _refill_warnings:
            summary["warnings"] = list(_refill_warnings)
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
        "confirm round %d: winner %s (%s) with R_%.3g=%s vs epsilon=%s (%s) -> %s",
        summary["round"], best, winner_levels, delta_t,
        "unknown" if bound.value is None else f"{bound.value:.6g}",
        "unknown" if eps is None else f"{eps:.6g}", eps_ref["source"],
        "CERTIFIED" if certified else "uncertified",
    )

    obs = {
        "correctness_failed": False,
        # EXACTLY what the key says: a row that ran to COMPLETION reported a
        # non-finite primary. It used to be `not ok` — "no finalist is in the
        # running" — which conflated three different states into the one that
        # blames the instrumentation: every finalist measured INADMISSIBLE (the
        # measurements are fine; the configurations violate a constraint),
        # every finalist UNMEASURED (a re-run repairs it), and a genuine NaN.
        # Observed on a field campaign whose constraint noise straddled its bound:
        # every value was numeric, yet the epoch ended telling the author to fix
        # the metric's definition. The first two are what the registered
        # `confirm -> confirm` top-up (re-fill the shortlist from the ranking,
        # skipping measured-inadmissible configurations) and the round cap /
        # budget guards -> `report` exist for; they need no branch of their own.
        # (`run_stage` routes a NaN on a complete row before confirm is reached,
        # so this is the backstop for any other non-finite value.)
        "nan_response": any(
            o.status == "complete" and not math.isfinite(y)
            for o, y in zip(outcomes, ys)
            if isinstance(y, (int, float))
        ),
        "certified": certified,
        "round": summary["round"],
        "budget_remaining": _budget_remaining(pol, work_dir),
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
    _vacated = sum(1 for v in status.values() if v == "infeasible")
    _refill_registered = any(
        t.get("accounting") == policy_mod.REFILL_ACCOUNTING
        for t in pol.get("transitions") or [])
    if _vacated and _refill_registered:
        # The refill branch's observations, produced ONLY on a round that
        # vacated a seat (an unvacated round's observations are unchanged).
        obs["finalists_vacated"] = _vacated
        obs["feasible_finalists"] = len(ok)
        # DERIVED, like confirm_affordable: no refill spent yet this epoch AND
        # the refill pool still holds a candidate worth measuring.
        obs["refill_available"] = (
            _refills_spent(pol, work_dir) < 1 and bool(_refill_cands)
        )
    if "pareto" in summary:
        # The PREFERENCE scalarisation's terminal pair (spec step 7), and the
        # gap-fill branch's own observation (step 6).
        obs["residual_regret"] = summary["pareto"]["preference"]["scalar_regret"]
        obs["epsilon"] = summary["pareto"]["preference"]["scalar_epsilon"]
        obs["front_gap_large"] = bool(summary["pareto"]["front_gap_large"])

    # ── the confirm-loop's affordability guard, the same shape as foldover's ──
    #
    # `budget_remaining < 1` is a real guard but a blunt one: it fires only once
    # literally nothing is left, so "2 runs remain and the next round needs 9"
    # reads as affordable and the epoch self-loops into a round it cannot
    # complete. The next round's cost is knowable HERE and nowhere else, so it is
    # computed here and the compiled guard reads the verdict.
    #
    # Why a Python comparison rather than a `when` predicate: identical to
    # `foldover_affordable` above — a `when` clause compares an observation
    # against a CONSTANT, and `budget_remaining >= runs_needed_confirm` compares
    # two observations, which the closed grammar deliberately cannot express
    # (spec §3.2). The BOOLEAN is what the guard reads; both operands are logged
    # beside it so a reader of `transitions.jsonl` can reconstruct the
    # arithmetic and tell a round declined for cost from one declined for the
    # round cap.
    #
    # `_next_round_finalists` sizes the round with `_confirm_rows`'s OWN
    # carry-over rule rather than with this round's shortlist size: a round that
    # retired two of three challengers costs a third of what `len(fin)` would
    # claim, and over-estimating the cost would decline rounds the budget can
    # actually pay for.
    _cfg = pol["states"]["confirm"]["design"] or {}
    carry = (
        # A multi-objective round re-seats up to the whole shortlist (front
        # points, gap fills, spread), so the full shortlist is the upper bound.
        max(1, int(_cfg.get("shortlist_size", 3))) if "pareto" in summary
        else _next_round_finalists(
            summary, shortlist_size=_cfg.get("shortlist_size", 3),
            baseline_seat=_baseline_seat_extra(pol, summary))
    )
    if "finalists_vacated" in obs and obs["feasible_finalists"] < 2 \
            and obs["refill_available"]:
        # A refill round re-seats the survivors AND every vacated seat.
        carry = max(1, int(_cfg.get("shortlist_size", 3))) + (
            1 if _baseline_seat_extra(pol, summary) else 0)
    obs["runs_needed_confirm"] = carry * max(1, int(_cfg.get("replicates", 3)))
    obs["confirm_affordable"] = (
        obs["budget_remaining"] >= obs["runs_needed_confirm"]
    )
    if not certified and not obs["confirm_affordable"]:
        logger.warning(
            "confirm round %d: NOT certified and the next round needs %d run(s) "
            "(%d finalist(s) still in contention x %d replicates) with only %d "
            "remaining, so the campaign declines the round rather than starting "
            "one it cannot finish. The winner stands on the rounds already "
            "completed and report.json carries it uncertified.",
            summary["round"], obs["runs_needed_confirm"], carry,
            max(1, int((pol["states"]["confirm"]["design"] or {}).get("replicates", 3))),
            obs["budget_remaining"],
        )
    return _close_iteration(
        engine, campaign, work_dir, iter_dir, iteration, stage_name, pol, obs,
        recommendation_levels=dict(winner_levels) or None,
    )


def _finish_confirm_pareto(pol, work_dir, summary: dict, *, rec: dict, status: dict,
                           ok: dict, unmeasured: list, fit_bias: bool,
                           model_inadequate: bool,
                           adequacy_unknown: str | None = None) -> tuple[bool, list]:
    """The multi-objective verdict of a confirm round, written into ``summary``.

    Spec steps 5-8: the measured front over every admissible configuration of
    the campaign (finalists AND fitting-stage rows), the preferred point by the
    declared preference, and the certificate -- ``certified`` iff the preferred
    point is ``confidently_nondominated`` AND the preference scalarisation's
    terminal regret bound is within ``epsilon_scalar``, with the same premise
    interlocks as the single-objective verdict (an unmeasured finalist, a
    level-correlated fit exclusion, an inadequate objective model). An
    infeasible finalist follows the same rule as the single-objective path
    (``_INFEASIBLE_FINALIST_CAVEAT``), judged on the admissible finalists.

    ``summary["confirmed_at_levels"]`` becomes the preferred point, which is
    what ``_close_iteration`` and the harness read; ``best`` stays the best
    finalist on the first objective, a fact about the shortlist.
    """
    par = pareto_stage.front_record(
        pol, work_dir, rec=rec, rnd=int(summary.get("round") or 1),
        baseline=pol.get("known_valid_baseline"),
    )
    pref = par["preference"]
    reg, eps_s = pref["scalar_regret"], pref["scalar_epsilon"]
    # Confident at the CERTIFICATION level (delta_terminal / max_rounds), which
    # is stricter than the level the front's statuses are reported at.
    chosen_ok = pref.get("chosen_status_at_certification") == "confidently_nondominated"
    within = reg is not None and eps_s is not None and reg <= eps_s
    n_inf = sum(1 for v in status.values() if v == "infeasible")
    caveat = bool(_INFEASIBLE_FINALIST_CAVEAT and n_inf and len(ok) >= 2
                  and within and not model_inadequate)
    infeasible_veto = bool(n_inf) and not caveat
    no_admissible = bool(status) and all(v == "infeasible" for v in status.values())
    refilled = _refill_round(pol, work_dir)
    # A lone admissible configuration has no rival to bound against
    # (pareto.scalar_regret returns None for it): the single-objective rule.
    no_rival = reg is None and str(pref.get("scalar_regret_method") or "").startswith(
        "no_feasible_rival")
    # An UNKNOWN epsilon (a pct of a zero best) resolves nothing and certifies
    # nothing; it is never read as a zero width.
    eps_unknown = bool(par.get("epsilon_unknown")) or eps_s is None
    # A finalist measured on objective 1 but not on another objective is
    # UNMEASURED here, like a timed-out one (pareto.excluded_incomplete).
    incomplete = any(x.get("source") == "confirm" and x.get("dropped", True)
                     for x in par.get("excluded_incomplete") or [])
    certified = bool(pref["chosen"]) and chosen_ok and within and not unmeasured \
        and not infeasible_veto and not fit_bias and not model_inadequate \
        and not refilled and not eps_unknown and not incomplete \
        and not adequacy_unknown
    reasons = [r for r, hit in (
        ("no_admissible_finalist", no_admissible),
        ("no_feasible_rival", no_rival and not no_admissible),
        ("epsilon_unknown", eps_unknown),
        ("bound_not_computable", reg is None and not no_admissible and not no_rival),
        ("bound_above_epsilon", reg is not None and eps_s is not None and reg > eps_s),
        ("front_point_possibly_dominated", bool(pref["chosen"]) and not chosen_ok),
        ("finalist_measured_infeasible", infeasible_veto),
        ("finalist_unmeasured", bool(unmeasured) or incomplete),
        ("fit_exclusions_level_correlated", fit_bias),
        ("model_inadequate", model_inadequate),
        (adequacy_unknown or "", bool(adequacy_unknown)),
        ("shortlist_refilled", refilled),
    ) if hit]
    if not certified and not reasons:
        reasons = ["no_front_point"]
    summary["pareto"] = par
    summary["certified"] = certified
    summary["certification_withheld"] = [] if certified else reasons
    if caveat:
        summary["certification_caveats"] = ["finalist_measured_infeasible"]
    else:
        summary.pop("certification_caveats", None)
    if pref["chosen"]:
        summary["confirmed_at_levels"] = dict(pref["chosen"])
    logger.info(
        "confirm round %s: measured front of %d point(s) (%d confidently "
        "nondominated) over %d admissible configuration(s); preferred (%s) %s "
        "[%s], scalar regret %s vs epsilon %s, hypervolume %s; largest gap "
        "%s (threshold %s) -> %s", summary.get("round"), len(par["front"]),
        sum(1 for f in par["front"] if f["status"] == "confidently_nondominated"),
        par["n_measured_configurations"], pref["method"], pref["chosen"],
        pref["chosen_status"], reg, eps_s, par["hypervolume"]["value"],
        par["gaps_remaining"][0]["size"] if par["gaps_remaining"] else "none",
        par["gap_threshold"], "CERTIFIED" if certified else "uncertified",
    )
    return certified, reasons


def _refill_candidates(work_dir, factors, warnings: list | None = None) -> list[dict]:
    """The REFILL branch's candidates (policy.REFILL_ACCOUNTING), best first.

    The supported-feasible pool first, then the constraint-filtered ranking
    (``refill_pool.json``), minus anything an earlier round measured and
    anything measured inadmissible. Each must also sit in the MEASURED-FEASIBLE
    NEIGHBOURHOOD: its nearest measured configuration (coded space, this
    epoch's rows) is admissible. That is what an unmodelled coupled constraint
    needs -- the admissible box of ``supported_feasible`` contains the very
    corner the finalists were just measured infeasible in (``SURFACES["sla"]``:
    2A + B <= 40, every pool member past the boundary). A heuristic, like the
    box: a refill seat is measured before it can win.

    Nothing degrades silently: a missing or corrupt ``refill_pool.json`` and a
    level that cannot be coded are each logged at WARNING and appended to
    ``warnings`` (``confirmation.json["warnings"]`` when the caller records
    them); an uncodeable candidate or measured row is SKIPPED rather than
    coded as the centre.
    """
    from orchestrator.optimize.factors import code_vector

    def warn(msg: str) -> None:
        logger.warning("refill: %s", msg)
        if warnings is not None and msg not in warnings:
            warnings.append(msg)

    rec_ = _read_recommendation(work_dir) or {}
    if rec_.get("iteration") is None:
        return []
    retired = _previous_finalist_levels(work_dir)
    pool_file = Path(work_dir) / "runs" / f"iter-{rec_.get('iteration')}" / "refill_pool.json"
    try:
        ranked = json.loads(pool_file.read_text()).get("candidates") or []
    except FileNotFoundError:
        ranked = []
        warn(f"{pool_file} is absent: the refill draws on the supported-feasible "
             f"pool only")
    except (OSError, ValueError) as exc:
        ranked = []
        warn(f"{pool_file} is unreadable ({exc}): the refill draws on the "
             f"supported-feasible pool only")
    cands = [dict(p_.get("levels") or {}) for p_ in
             (rec_.get("supported_feasible_candidate") or {}).get("pool") or []]
    cands += [dict(c_.get("levels") or {}) for c_ in ranked]
    by_id = {f.id: f for f in factors}

    def code(lv):
        """Coded coordinates, or ``None`` when a level cannot be coded."""
        out_ = []
        for fid in sorted(lv):
            f = by_id.get(fid)
            if f is None:
                warn(f"factor {fid!r} in {lv} is not declared; skipped")
                return None
            try:
                out_.extend(code_vector(f, lv[fid]))
            except (TypeError, ValueError) as exc:
                warn(f"level {fid}={lv[fid]!r} cannot be coded ({exc}); skipped")
                return None
        return out_

    invalid = _measured_infeasible(work_dir)
    barred = _barred_levels(work_dir)  # read ONCE for the loop (Q3)
    measured = []
    for rp in _this_epoch_runs(work_dir):
        for row in artifacts.read_runs(rp.parent):
            lv_ = row.get("levels")
            if lv_ and row.get("status") in ("complete", "infeasible", "rejected"):
                z_ = code(lv_)
                if z_ is not None:
                    measured.append((z_, _config_admissible(work_dir, lv_, invalid=invalid, barred=barred)))

    def near_feasible(lv) -> bool:
        z = code(lv)
        if z is None:
            return False
        if not measured:
            return True
        return min(measured, key=lambda m: (math.dist(z, m[0]), not m[1]))[1]

    out: list[dict] = []
    for lv_ in cands:
        if (lv_ and not any(_same_levels(r_, lv_) for r_ in retired)
                and not any(_same_levels(o_, lv_) for o_ in out)
                # Redundant with near_feasible (a measured-inadmissible
                # configuration is its own nearest measured neighbour, at
                # distance 0, and that neighbour is inadmissible) -- kept as
                # the rule stated where it is read.
                and not _measured_infeasible_contains(work_dir, lv_, invalid=invalid)
                and near_feasible(lv_)):
            out.append(lv_)
    return out


def _baseline_seat_extra(pol: dict, summary: dict) -> bool:
    """Will the next round seat the baseline OUTSIDE the shortlist cap (A3)?"""
    base = pol.get("known_valid_baseline")
    if not base or pareto_stage.objectives(pol):
        return False
    return True


def _gain_over_baseline(pol, fin, ok, best, *, delta, paired, direction) -> dict | None:
    """``confirmation.json["gain_over_baseline"]`` (WP-A A3).

    Signed in the campaign's direction (positive = the winner is better).
    The interval is two-sided at ``delta`` simultaneously over every finalist
    vs the baseline (Bonferroni, ``certificate.simultaneous_gain_interval``),
    so it covers the selected winner's true gain with probability >= 1 -
    delta. The point estimate is the winner's mean difference on the same
    replicates that selected it and is biased upward; the interval is the
    claim.
    """
    base = pol.get("known_valid_baseline")
    if not base or best is None or pareto_stage.objectives(pol):
        return None
    bkey = next((f["key"] for f in fin if _same_levels(dict(f["levels"]), dict(base))),
                None)
    if bkey is None or bkey not in ok:
        return {"baseline": dict(base), "estimate": None, "low": None, "high": None,
                "delta": delta, "method": "none",
                "detail": "the baseline produced no admissible measurement this round"}
    iv = certificate.simultaneous_gain_interval(ok, best, bkey, delta=delta, paired=paired)
    if iv is None:
        return {"baseline": dict(base), "estimate": None, "low": None, "high": None,
                "delta": delta, "method": "none",
                "detail": "no variance estimate (fewer than two replicates, or zero spread)"}
    sign = 1.0 if direction != "minimize" else -1.0
    lo, hi = sorted((sign * iv["low"], sign * iv["high"]))
    return {"baseline": dict(base), "baseline_key": bkey, "winner_key": best,
            "estimate": sign * iv["estimate"], "low": lo, "high": hi, "delta": delta,
            "method": f"simultaneous_two_sided_{iv['method']}",
            "simultaneous_over": iv["simultaneous_over"],
            "detail": ("Bonferroni over every finalist vs the baseline at two-sided "
                       "delta/(2M), so the interval for the data-selected winner "
                       "covers at >= 1 - delta; the estimate is the winner's mean "
                       "difference on the selecting replicates (biased upward).")}


def _certificate_scope(rec: dict, boundary: dict | None) -> dict:
    """``report.json["certificate_scope"]`` (WP-A A4, spec
    2026-10-17-certification-soundness.md section 4): the region the model
    half of the certificate ranged over, read from this epoch's latest
    fitting record. ``slice`` when that stage held any factor fixed, else
    ``declared_space``; ``searched`` notes a candidate space that was sampled
    rather than enumerated."""
    held = dict((rec or {}).get("held_fixed") or {})
    region = "slice" if held else ("declared_space" if rec else "none")
    out = {
        "region": region,
        "held_fixed": held,
        "fitting_stage": (rec or {}).get("stage"),
        "searched": bool((rec or {}).get("candidate_space")),
        "within_declared_ranges": True,
    }
    if boundary:
        out["boundary_axes"] = list(boundary.get("axes") or [])
    out["statement"] = (
        "no fitting stage: no model half, nothing beyond the finalists is covered"
        if region == "none" else
        ("epsilon-optimal over the declared ranges of the fitted factors with "
         + ", ".join(f"{k}={v!r}" for k, v in sorted(held.items()))
         + " held fixed; the other levels of those factors are NOT covered")
        if held else
        "epsilon-optimal over the declared ranges of every factor")
    return out


def _global_bound(rec: dict, fin: list, status: dict, ok: dict, best,
                  bound, eps, *, delta_t: float, delta_s: float, skip: bool,
                  xhat_measured_infeasible: bool = False) -> tuple[dict | None, list[str]]:
    """``G = R_model_out + R_terminal`` and why it cannot certify (WP-A A1).

    See the A1 block in ``_finish_confirm`` and spec
    2026-10-17-certification-soundness.md section 2. Returns the record
    written to ``confirmation.json["global_bound"]`` (None when the model
    half is not consulted) and the named withheld reasons.
    """
    if skip:
        return None, []
    rb = rec.get("residual_regret_model") or {}
    r_model = rb.get("value")
    xhat = rec.get("levels") or {}
    inside = [dict(f["levels"]) for f in fin if f["key"] in ok]
    r_out = certificate.model_bound_outside(
        rec.get("residual_regret_model_profile"), inside)
    out = {"value": None, "residual_regret_model": r_model,
           "residual_regret_model_outside": r_out,
           "residual_regret_terminal": bound.value,
           "x_hat": dict(xhat), "x_hat_key": None,
           "delta_screen": delta_s, "delta_terminal_per_look": delta_t,
           "rule": "G = R_model_outside + R_terminal, R_model_outside the model "
                   "bound over the candidates OUTSIDE the measured shortlist; "
                   "certified needs G <= epsilon and the fitted argmax measured "
                   "admissibly in this round. Pr(certified and gap > epsilon) "
                   "<= delta_screen + delta_terminal under the stated "
                   "assumptions."}
    if not rec or not isinstance(r_model, (int, float)):
        return out, ["model_bound_not_computable"]
    if r_out is None:
        # A record written before the profile existed: the whole-space bound
        # is a valid (larger) stand-in for the bound outside S.
        r_out = float(r_model)
        out["residual_regret_model_outside"] = r_out
    reasons: list[str] = []
    if rec.get("candidate_space"):
        # Searched, not enumerated: R_model is a max over the EVALUATED
        # candidates only, so it is silent about the rest of X_valid.
        reasons.append("model_bound_not_exhaustive")
    key = next((f["key"] for f in fin
                if xhat and _same_levels(dict(f["levels"]), dict(xhat))), None)
    out["x_hat_key"] = key
    if (key is not None and status.get(key) == "infeasible") or (
            xhat and xhat_measured_infeasible):
        # The fitted argmax is INADMISSIBLE: the step f(x_hat) <= f(i*) needs
        # x_hat admissible, so nothing links the model bound to the winner.
        return out, reasons + ["model_recommendation_infeasible"]
    if key is None or status.get(key) != "ok" or key not in ok or best is None \
            or bound.value is None:
        return out, reasons + ["model_recommendation_not_compared"]
    out["value"] = float(r_out) + float(bound.value)
    if eps is not None and out["value"] > eps:
        reasons.append("model_bound_above_epsilon")
    return out, reasons


def _refills_spent(pol, work_dir) -> int:
    """Refill rounds (``policy.REFILL_ACCOUNTING``) this epoch has already run."""
    return sum(
        1 for t in policy_mod.epoch_transitions(pol, work_dir)
        if (t.get("rule") or {}).get("accounting") == policy_mod.REFILL_ACCOUNTING
    )


def _refill_round(pol, work_dir) -> bool:
    """Is the confirm round about to run the registered REFILL branch?"""
    trans = policy_mod.epoch_transitions(pol, work_dir)
    return bool(trans) and (trans[-1].get("rule") or {}).get(
        "accounting") == policy_mod.REFILL_ACCOUNTING


def _next_round_finalists(summary: dict, *, shortlist_size,
                          baseline_seat: bool = False) -> int:
    """How many finalists a round r+1 would seat, by `_confirm_rows`'s own rule.

    Mirrors the ``rnd > 1`` carry-over branch there: the previous round's winner
    plus every ``ok`` finalist whose per-challenger bound is not KNOWN to be at
    or below epsilon (``None`` is unknown, not small — an uncomputed bound has
    not retired its challenger). Kept as a separate function so the cost
    estimate and the shortlist it estimates cannot drift apart silently: if
    ``_confirm_rows``'s rule changes, this is the one other place to change.

    AN EMPTY CARRY-OVER COSTS ``shortlist_size``, NOT ZERO AND NOT ONE. When
    nothing survives — every finalist excluded on measured invalidity, or every
    bound already at or below epsilon — ``_confirm_rows`` does not run a smaller
    round; its ``if not finalists:`` branch falls through to the ROUND-1 LADDER
    and re-seats up to ``shortlist_size`` seats from ``recommendation.json`` /
    ``_top_measured``. Returning 1 there would under-estimate the round by up to
    a factor of ``shortlist_size`` and let the affordability guard wave through
    exactly the round it exists to decline — the same class of defect as
    ``budget_remaining < 1`` being the only guard. The estimate must be an upper
    bound on what the next round actually spends, or it is not a guard.
    """
    k = max(1, int(shortlist_size or 3))
    eps = summary.get("epsilon")
    bounds = summary.get("bounds") or {}
    best = summary.get("best")
    carry = {
        f["key"] for f in (summary.get("finalists") or [])
        if f.get("status") == "ok" and (
            eps is None or bounds.get(f["key"]) is None or bounds[f["key"]] > eps
        )
    }
    if best:
        carry.add(best)
    # `_confirm_rows` caps the shortlist at `k` regardless of how many the
    # carry-over rule nominates, so the estimate caps there too -- plus the
    # permanent baseline seat (WP-A A3), which sits outside the cap.
    base = 1 if baseline_seat else 0
    return (min(k, len(carry)) if carry else k) + base


def _confirm_epsilon(spec: dict, work_dir, metric: str, *, direction: str,
                     best_levels: dict | None,
                     best_value: float | None) -> tuple[float | None, dict]:
    """Resolve confirm's epsilon and record WHICH reference it rests on.

    ``{"pct": p}`` is a percentage "of the best". The reference, in order:

      1. ``best_finalist`` — the winning admissible finalist's fresh mean (the
         normal case, unchanged);
      2. ``best_observed`` — when no finalist is admissible there is no winner,
         so take the best measured ADMISSIBLE configuration so far
         (``_best_observed``, per-configuration feasibility): a measured value,
         which is what "of the best" means, and the configuration the report's
         ``measured`` rung would return;
      3. ``recommendation`` — the epsilon the fitting stage already resolved
         (``recommendation.json["epsilon"]``, a percentage of its prediction);
      4. ``none`` — nothing to take a percentage of: epsilon is ``None``
         (unknown), never 0. An epsilon of 0 can never certify and is not what
         the author declared.

    ``{"abs": a}`` needs no reference and is recorded as ``declared_abs``.
    """
    if "abs" in spec:
        return float(spec["abs"]), {"source": "declared_abs", "levels": None,
                                    "value": None}
    if best_value is not None:
        return (certificate.resolve_epsilon(spec, best_value),
                {"source": "best_finalist", "levels": dict(best_levels or {}),
                 "value": float(best_value)})
    obs = _best_observed(work_dir, metric, direction=direction) if metric else None
    if obs is not None and isinstance(obs.get(metric), (int, float)):
        eps = certificate.resolve_epsilon(spec, obs[metric])
        if eps > 0:
            return eps, {"source": "best_observed",
                         "levels": dict(obs["levels"]),
                         "value": float(obs[metric])}
    rec_eps = (_read_recommendation(work_dir) or {}).get("epsilon")
    if isinstance(rec_eps, (int, float)) and rec_eps > 0:
        return float(rec_eps), {"source": "recommendation", "levels": None,
                                "value": None}
    return None, {"source": "none", "levels": None, "value": None}


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
    # Every finalist MEASURED inadmissible is not "no usable measurement": the
    # runs measured fine and said the configurations violate a constraint. The
    # experiment is valid; its prediction (the shortlist contains an admissible
    # optimum) is what is refuted.
    no_admissible = "no_admissible_finalist" in (
        summary.get("certification_withheld") or []
    )

    if best is None and no_admissible:
        n_complete = sum(f["n"] for f in summary["finalists"])
        observed = (
            f"no admissible finalist: all {len(summary['finalists'])} "
            f"finalist(s) were measured inadmissible (each had at least one "
            f"replicate violating a declared constraint; {n - n_complete}/{n} "
            f"fresh runs infeasible or otherwise excluded)"
        )
    elif best is None:
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
    if best is None and no_admissible:
        note = (
            "every finalist was measured inadmissible; the measurements are "
            "valid, so this is information about the admissible region, not an "
            "instrumentation failure. The registered confirm -> confirm round "
            "re-fills the shortlist from the ranking (skipping measured-"
            "inadmissible configurations) when the round cap allows; otherwise "
            "the report falls to the best measured admissible configuration"
        )
    elif best is None:
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
        "experiment_valid": best is not None or no_admissible,
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


def _corner_marginal_best(work_dir, iteration, factor_ids, primary: str,
                          direction: str, barred: dict | None = None) -> dict:
    """Each factor's best level by its marginal mean over the CORNER rows.

    Reads ``runs/iter-<iteration>/runs.jsonl``: ``complete`` rows whose
    ``role`` is ``corner`` and whose primary is finite. A factor gets an entry
    only when at least two of its levels were measured there, so a factor the
    corners never varied keeps whatever the caller would otherwise hold it at.
    Ties go to the level that appeared first in the file. See the
    refine held-fixed block for why corners and not the screen's argmax.
    """
    import math

    if iteration is None:
        return {}
    p = Path(work_dir) / "runs" / f"iter-{int(iteration)}" / "runs.jsonl"
    if not p.exists():
        return {}
    sums: dict[str, dict] = {fid: {} for fid in factor_ids}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") != "complete" or row.get("role") != "corner":
            continue
        y = (row.get("response") or {}).get(primary)
        if not isinstance(y, (int, float)) or not math.isfinite(y):
            continue
        for fid in factor_ids:
            lv = (row.get("levels") or {}).get(fid)
            if lv is None:
                continue
            acc = sums[fid].setdefault(json.dumps(lv), [lv, 0.0, 0])
            acc[1] += float(y)
            acc[2] += 1
    sign = -1.0 if direction == "minimize" else 1.0
    out: dict = {}
    for fid, by_level in sums.items():
        # A lost/inadmissible level is never a held level (stage-1d Q1).
        cand = [a for a in by_level.values()
                if a[0] not in (barred or {}).get(fid, ())]
        if len(by_level) < 2 or not cand:
            continue
        best = max(cand, key=lambda a: sign * a[1] / a[2])
        out[fid] = best[0]
    return out


def _model_adequacy(decision, mo_rejected, fit, untested, design_for_fit,
                    mo_untested=()):
    """``(model_adequate, basis)`` -- see the block that calls it. A secondary
    objective's model with no lack-of-fit verdict makes it unknown too
    (stage-1c P6)."""
    if Trigger.LACK_OF_FIT in set(decision.triggers) or mo_rejected:
        return False, None
    if fit.lof_exact == "rejected":
        return False, None
    if (fit.lack_of_fit_p is None and not fit.lof_exact_fit) or mo_untested:
        return None, "lack_of_fit_not_computable"
    if untested:
        return None, "curvature_untested"
    mixed = bool(design_for_fit.groups) and any(
        c != g for c, g in zip(design_for_fit.factor_ids, design_for_fit.groups))
    if (mixed and any(p.role == "center" for p in design_for_fit.points)
            and not fit.centre_isolated):
        return None, "curvature_not_isolated"
    return True, None


def _screen_reuse(work_dir, pol, design, rows, payload, factors):
    """WP-B B4: which refine rows the screen already measured.

    Returns ``(design, rows, payload, record)``; ``record`` is ``{}`` when
    nothing is reused (every guard below refuses quietly, and the stage runs
    exactly as without the option). Guards, each of which refuses:

      1. a screen in THIS epoch (``_screen_iteration``) whose matrix records
         the same ``policy_hash`` -- one pre-registration, one instrument;
      2. NO choice factor declared (a centre row of a choice factor runs the
         diagonal cyclic assignment; one-to-one matching would need the held
         level to coincide with every cycled level) and no multi-level
         categorical;
      3. every held (non-refinable) factor ran at the SAME level on the screen
         row as refine holds it;
      4. the screen row is ``complete``/``infeasible`` (a fit input) and its
         levels equal the refine CUBE corner's levels exactly.

    MATCHED CUBE CORNERS ARE NOT RE-RUN: refine's row keeps its position and
    the screen's measurement fills it (``reused_from``). The screen's matching
    CENTRE rows join as extra block-1 centre rows (appended after the plan's
    rows), so each block has its own centres and the block effect is
    estimable from the replicated centres alone (Box & Draper 2007, §15.3).
    Refine's own centre rows are kept: they are the refine block's pure error
    and its estimate of the block shift.
    """
    import dataclasses

    from orchestrator.optimize.design import DesignPoint
    from orchestrator.optimize.factors import is_refinable

    if any(f.type == "choice" for f in factors):
        logger.info("refine: reuse_screen refused -- a choice factor is declared (its centre rows cycle levels); every row is measured")
        return design, rows, payload, {}
    s_iter = _screen_iteration(work_dir, pol)
    if s_iter is None:
        logger.info("refine: reuse_screen refused -- no screen ran in this epoch; every row is measured")
        return design, rows, payload, {}
    sdir = Path(work_dir) / "runs" / f"iter-{s_iter}"
    try:
        smat = json.loads((sdir / "design_matrix.json").read_text())
    except (OSError, ValueError):
        return design, rows, payload, {}
    if smat.get("policy_hash") != policy_mod.policy_hash(pol):
        logger.info("refine: reuse_screen refused -- the screen ran under a different policy; every row is measured")
        return design, rows, payload, {}
    seeds = smat.get("workload_seeds") or {}
    srows = [r for r in artifacts.read_runs(sdir)
             if r.get("status") in _PRIMARY_FIT_STATUSES and not r.get("reused_from")]
    held_ids = [f.id for f in factors if not is_refinable(f)]
    held_lv = dict(payload.get("held_fixed") or {})

    def _key(lv):
        return json.dumps({k: lv.get(k) for k in sorted(lv)}, sort_keys=True, default=str)

    def _held_ok(lv):
        return all(lv.get(h) == held_lv.get(h, lv.get(h)) for h in held_ids)

    corners = {}
    for i, (p, r) in enumerate(zip(design.points, rows)):
        if p.role == "corner":
            corners.setdefault(_key(dict(r.levels)), i)
    used: dict = {}
    taken: set = set()
    centre_src = []
    centre_lv = next((dict(r.levels) for p, r in zip(design.points, rows)
                      if p.role == "center"), None)
    for sr in sorted(srows, key=lambda r: int(r.get("row_index", 0))):
        lv = dict(sr.get("levels") or {})
        if not _held_ok(lv):
            continue
        if sr.get("role") == "corner":
            i = corners.get(_key(lv))
            if i is not None and i not in taken:
                taken.add(i)
                used[i] = {"row": sr, "row_index": int(sr["row_index"]),
                           "seed": seeds.get(str(sr["row_index"]))}
        elif sr.get("role") == "center" and centre_lv is not None \
                and _key(lv) == _key(centre_lv):
            centre_src.append(sr)
    if not used and not centre_src:
        return design, rows, payload, {}
    # Block-1 centres appended AFTER every planned row (validation included),
    # so every planned row keeps its position and row_index.
    n0 = len(rows)
    proto = next(r for p, r in zip(design.points, rows) if p.role == "center") \
        if centre_src else None
    origin = tuple(0.0 for _ in design.factor_ids)
    new_pts = list(design.points)
    new_rows = list(rows)
    for j, sr in enumerate(centre_src):
        ri = n0 + j
        new_pts.append(DesignPoint(coded=origin, role="center", replicate=1000 + j))
        new_rows.append(dataclasses.replace(proto, row_index=ri, replicate=1000 + j))
        used[ri] = {"row": sr, "row_index": int(sr["row_index"]),
                    "seed": seeds.get(str(sr["row_index"]))}
    design = dataclasses.replace(design, points=tuple(new_pts))
    payload = dict(payload)
    order = list(payload.get("run_order") or range(n0))
    payload["run_order"] = order + list(range(n0, len(new_rows)))
    payload["rows"] = list(payload.get("rows") or []) + [
        {"row_index": r.row_index, "levels": dict(r.levels), "role": r.role,
         "replicate": r.replicate, "apply": r.apply} for r in new_rows[n0:]]
    blocks = [1 if i in used else 0 for i in range(len(new_rows))]
    record = {
        "from_iteration": s_iter, "rows": used,
        "manifest": {
            "kind": "sequential_assembly",
            "from_stage": Stage.SCREEN.value, "from_iteration": s_iter,
            "rule": ("refine cube corners whose levels (held factors included) "
                     "equal a measured screen corner's are filled from it; the "
                     "screen's centre rows at refine's centre join as block-1 "
                     "centres"),
            "reused": {str(i): {"screen_row_index": u["row_index"]}
                       for i, u in sorted(used.items())},
            "reused_count": len(used),
            "block": blocks,
            "blocking_assumption": (
                "no drift between stages beyond a constant shift; the shift is "
                "the fitted block coefficient and is tested (block_effect)"),
        },
    }
    payload["stage_reuse"] = record["manifest"]
    return design, new_rows, payload, record


def _stage_model_class(stage_name: str) -> int:
    """1: first-order + 2fi (screen, foldover); 2: second-order (refine)."""
    return 2 if stage_name == Stage.REFINE.value else 1


def _adequacy_record(work_dir, stage_name, fit, design_for_fit, ys_for_fit,
                     factors, fitted_ids, interactions_dropped, omitted_terms,
                     adequate, basis, decision, val_rows, val_outcomes, val_ys,
                     response_spec, primary, omodels, blocks=None):
    """``(model_adequacy record, model_adequate, basis)`` for this stage.

    THE THIS-STAGE VERDICT. Lack of fit (``_model_adequacy``) as before, and at
    refine the validation prediction check: a rejected check makes the model
    inadequate (False) whatever lack of fit said; a check that could not be
    computed leaves the lack-of-fit verdict standing.

    THE EPOCH VERDICT (sticky). ``adequacy.epoch_verdict`` over this epoch's
    fitting stages: a stage's verdict is superseded only by a later stage of at
    least its model class. One more rule gives the screen's rejection teeth: a
    refine that did NOT complete a validation check (``validation_points: 0``,
    every validation row unmeasured, no pure error) cannot overturn an earlier
    rejection -- its lack-of-fit test alone has ~alpha power against the
    one-dimensional misspecification the screen saw (stage-0 audit Q3) -- so
    the verdict is then UNKNOWN, ``screen_rejection_unresolved``.
    """
    from orchestrator.optimize import adequacy as adq
    from orchestrator.optimize.factors import code_actual

    fit_factor_ids = (design_for_fit.factor_ids if design_for_fit.groups
                      else tuple(fitted_ids))
    labels, terms, cols = adq.model_columns(
        design_for_fit, fit_factor_ids,
        include_interactions=not interactions_dropped, omit_terms=omitted_terms)
    nuis = [[float(b) for b in blocks]] if blocks and len(set(blocks)) > 1 else []
    rec: dict = {
        "lack_of_fit": {
            "f": fit.lack_of_fit_f, "p": fit.lack_of_fit_p,
            "df": ([max(0, len(ys_for_fit) - len(cols) - len(nuis)
                           - int(fit.pure_error_df or 0)),
                    int(fit.pure_error_df or 0)]),
            "exact": fit.lof_exact,
            "rejected": (Trigger.LACK_OF_FIT in set(decision.triggers)
                         or fit.lof_exact == "rejected"),
        },
        "press": adq.press(cols + nuis, ys_for_fit),
        "design_efficiency": adq.design_efficiency(cols, labels),
    }
    if nuis and fit.block_effect is not None:
        b, se, t, pv, df = fit.block_effect
        rec["reuse"] = {"block_effect": {"estimate": b, "se": se, "t": t, "p": pv,
                                         "df": df},
                        "drift_detected": (pv is not None and pv < 0.05)}
    causes: list[str] = []
    if rec["lack_of_fit"]["rejected"] or adequate is False:
        causes.append("lack_of_fit")
    validated = None
    if stage_name == Stage.REFINE.value and val_rows:
        by_id = {f.id: f for f in factors}
        pts, objs = [], {}
        for r, o, y in zip(val_rows, val_outcomes, val_ys):
            if getattr(o, "status", None) not in _PRIMARY_FIT_STATUSES or y != y:
                continue
            lv = dict(r.levels)
            if any(fid not in lv for fid in fitted_ids):
                continue
            coded = {fid: code_actual(by_id[fid], lv[fid]) for fid in fitted_ids}
            pts.append((coded, y))
            for metric, m in (omodels or {}).items():
                v = (getattr(o, "response", None) or {}).get(metric)
                if isinstance(v, (int, float)) and v == v:
                    objs.setdefault(metric, []).append((coded, float(v)))
        check = adq.prediction_check(fit, cols, terms, pts, nuisance=nuis)
        check["points_registered"] = len(val_rows)
        rec["validation"] = check
        validated = check.get("rejected")
        for metric, mpts in objs.items():
            mod = omodels.get(metric)
            if mod is None or mod.fit is None or metric == primary:
                continue
            _l, mterms, mcols = adq.model_columns(
                design_for_fit, fit_factor_ids,
                include_interactions=not interactions_dropped,
                omit_terms=omitted_terms)
            if len(mcols) != len(list(mod.fit.effects) + list(mod.fit.quadratic)) + 1:
                continue        # the objective model was reduced differently
            oc = adq.prediction_check(mod.fit, mcols, mterms, mpts, nuisance=nuis)
            rec.setdefault("validation_objectives", {})[metric] = oc
            if oc.get("rejected"):
                validated = True
                causes.append(f"validation_prediction:{metric}")
        if check.get("rejected"):
            causes.append("validation_prediction")
        if validated:
            adequate, basis = False, None
    rec["this_stage"] = {"verdict": adequate, "basis": basis,
                         "rejected_by": causes}
    # The epoch's earlier fitting stages, from their records on disk.
    hist = []
    for r in _epoch_recommendations(work_dir):
        if r.get("stage") in (None, Stage.CONFIRM.value):
            continue
        st = (r.get("model_adequacy") or {}).get("this_stage") or {}
        v = st.get("verdict", r.get("model_adequate"))
        val = ((r.get("model_adequacy") or {}).get("validation") or {}).get("rejected")
        hist.append((str(r.get("stage")), _stage_model_class(str(r.get("stage"))),
                     v, st.get("basis", r.get("model_adequate_basis")),
                     val is not None))
    validation_done = rec.get("validation", {}).get("rejected") is not None
    stages = [(h[0], h[1], h[2], h[4]) for h in hist] + [
        (stage_name, _stage_model_class(stage_name), adequate, validation_done)]
    ep, decided_by, ep_basis = adq.epoch_verdict(stages)
    if ep is None and ep_basis is None and adequate is None:
        ep_basis = basis
    if ep is None and ep_basis is None:
        # An earlier stage's UNKNOWN decided it: carry that stage's basis.
        ep_basis = next((h[3] for h in hist if h[0] in decided_by and h[2] is None
                         and h[3]), None) or "model_adequacy_unknown"
    rec["epoch"] = {
        "verdict": ep, "basis": ep_basis, "decided_by": decided_by,
        "stages": [{"stage": st, "model_class": c, "verdict": v}
                   for st, c, v, _val in stages],
        "rule": ("a rejection is overturned only by a later stage of a STRICTLY "
                 "higher model class (1: first order + 2fi, 2: second order) "
                 "that completed a validation check; a same-class refit never "
                 "overturns it; a higher class without a completed check makes "
                 "it unknown (screen_rejection_unresolved); any other verdict "
                 "is superseded by a later stage of at least its class"),
    }
    return rec, ep, ep_basis


def _curvature_untested_levels(factors, fitted_ids, roles, levels_rows,
                               lost=None) -> dict:
    """``{choice factor: [levels]}`` with NO fitted centre row: the lack-of-fit
    curvature check never looked under them. Empty when the fit has no centre
    rows at all (then nothing claims curvature was checked), or no choice
    factor is fitted."""
    from orchestrator.optimize.matrix import centre_choice_levels

    centre = [lv for r, lv in zip(roles, levels_rows) if r == "center" and lv]
    if not centre:
        return {}
    out: dict = {}
    fitted = set(fitted_ids)
    for f in factors:
        if f.type != "choice" or f.id not in fitted:
            continue
        seen = {json.dumps(lv.get(f.id)) for lv in centre}
        # A LOST level (no retained row at all) is not "untested curvature":
        # it is reported as lost, and never recommended (stage-1b N12).
        gone = {json.dumps(v) for v in (lost or {}).get(f.id, ())}
        miss = [lv for lv in centre_choice_levels(f)
                if json.dumps(lv) not in seen and json.dumps(lv) not in gone]
        if miss:
            out[f.id] = miss
    return out


def _inadmissible_categorical_levels(work_dir, factors) -> dict:
    """Multi-level categorical levels every MEASURED row of which (this epoch)
    was infeasible or rejected: ``{factor: [level, ...]}``. A heuristic stated
    as such -- "inadmissible wherever it was measured", not proven inadmissible
    everywhere -- recorded in recommendation.json, and the recommendation never
    names such a level (stage-1 M5). A ``rejected`` row (a self-check or
    design-space invariant violation) counts as inadmissible, like an
    ``infeasible`` one; failed / unmeasured rows count as neither."""
    from orchestrator.optimize.factors import is_categorical

    cats = [f for f in factors if is_categorical(f)]
    if not cats:
        return {}
    seen: dict = {f.id: {} for f in cats}
    for rp in _this_epoch_runs(work_dir):
        for row in artifacts.read_runs(rp.parent):
            st, lv = row.get("status"), row.get("levels") or {}
            if st not in ("complete", "infeasible", "rejected"):
                continue
            for f in cats:
                if f.id in lv:
                    a = seen[f.id].setdefault(json.dumps(lv[f.id]), [lv[f.id], 0, 0])
                    a[1] += 1
                    a[2] += st != "complete"
    out: dict = {}
    for f in cats:
        bad = [v[0] for v in seen[f.id].values() if v[1] and v[1] == v[2]]
        if bad:
            # Recorded even when EVERY level is bad (stage-1b N8); the caller
            # then excludes none of them -- excluding all would empty the
            # space -- and says so.
            out[f.id] = bad
    return out


def _centre_mean_best(work_dir, iteration, factors, primary: str,
                      direction: str, barred: dict | None = None) -> dict:
    """Each choice factor's best level by its mean over the CENTRE rows of
    ``runs/iter-<iteration>/runs.jsonl`` -- only for a factor EVERY one of
    whose centre-cycled levels (``matrix.centre_choice_levels``) has at least
    one complete centre row with a finite primary. A factor with an unmeasured
    level is omitted, so the caller keeps its corner-marginal rule: a level
    never seen at the centre cannot be compared there. Ties go to the level
    declared first.
    """
    import math

    from orchestrator.optimize.matrix import centre_choice_levels

    if iteration is None or not factors:
        return {}
    p = Path(work_dir) / "runs" / f"iter-{int(iteration)}" / "runs.jsonl"
    if not p.exists():
        return {}
    acc: dict[str, dict] = {f.id: {} for f in factors}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") != "complete" or row.get("role") != "center":
            continue
        y = (row.get("response") or {}).get(primary)
        if not isinstance(y, (int, float)) or not math.isfinite(y):
            continue
        for f in factors:
            lv = (row.get("levels") or {}).get(f.id)
            if lv is None:
                continue
            a = acc[f.id].setdefault(json.dumps(lv), [0.0, 0])
            a[0] += float(y)
            a[1] += 1
    sign = -1.0 if direction == "minimize" else 1.0
    out: dict = {}
    for f in factors:
        # A lost/inadmissible level is not a candidate held level (stage-1d
        # Q1): its centre rows may well have measured (lost AT THE CORNERS).
        levels = [lv for lv in centre_choice_levels(f)
                  if lv not in (barred or {}).get(f.id, ())]
        if not levels:
            continue
        means = {}
        for lv in levels:
            a = acc[f.id].get(json.dumps(lv))
            if not a:
                break
            means[json.dumps(lv)] = a[0] / a[1]
        else:
            best = max(levels, key=lambda lv: (sign * means[json.dumps(lv)],
                                               -levels.index(lv)))
            out[f.id] = best
    return out


def _best_observed(work_dir, primary: str, *,
                   direction: str = "maximize") -> dict | None:
    """The best ADMISSIBLE configuration observed so far, by primary metric.

    Admissible PER CONFIGURATION (``_config_admissible``): a configuration with
    any ``infeasible`` / ``rejected`` row is never returned, even when some of
    its other rows completed.

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
    top = _top_measured(work_dir, primary, direction=direction, k=1)
    return top[0] if top else None


def _measured_seats(shortlist_size: int) -> int:
    """How many of a ``model_adequate: false`` shortlist's seats go to measured
    leaders, leaving the rest for the model's ranking.

    ``k // 2``, floor 1.

    WHAT THE ORACLE ACTUALLY FORCES is exactly ``f(3) == 1`` — nothing more, and
    saying more here would be overclaiming. Read the two ends:

      * AT LEAST ONE seat to a measured leader, so a rejected response class never
        anchors the comparison on its own argmax. Not a tuning result: at a
        registered ``shortlist_size: 1`` this single seat IS the whole shortlist,
        which is the only configuration under which the rule bites at all.
      * NOT ALL OF THEM, so the model's ranking still nominates candidates the
        campaign has not run. Measured on ``SURFACES["sla"]``: with every seat
        given to measured leaders the campaign certifies 6.12% off the true
        constrained optimum at 3, 5 and 8 confirm rounds alike — the extra budget
        buys nothing, because a measured-only shortlist can only re-seat what is
        already on disk. Reserving a seat for the ranking reaches 1.02% in three
        rounds. On ``SURFACES["bowl"]`` an all-measured shortlist discards the
        interior optimum refine was spent to find and confirms the centre point
        instead.

    Those two facts pin ``f(3) == 1`` and nothing else, because at the DEFAULT
    ``shortlist_size: 3`` the constant ``1``, ``k // 3`` and ``k // 2`` are the
    SAME FUNCTION — all three return 1 — and every campaign in the oracle runs at
    that default. So a 5-variant sweep over ``{1, k//3, k//2, 2k//3, k}`` can only
    separate ``2k//3`` and ``k`` from the rest; it cannot distinguish this
    implementation from ``return 1``.

    ``k // 2`` BEYOND k=3 IS THEREFORE A FIRST-CUT CHOICE, NOT A DERIVED ONE.
    Its rationale is that the two sources answer different questions and neither
    dominates — the measured leaders bound the answer from below with
    configurations that definitely work, the ranking supplies the only chance of
    improving on them — so an even split says a rejected fit is evidence to
    DISCOUNT the ranking rather than to discard it. Spot-checked rather than
    optimised: on ``SURFACES["sla"]`` at ``shortlist_size`` 5 and 7 (2 and 3
    measured seats) the campaign still reaches 1.02%, so the shape does not
    degrade as k grows. A campaign that wants a different split should get an
    explicit knob rather than have this constant retuned against one surface.
    """
    return max(1, int(shortlist_size) // 2)


def _top_measured(work_dir, primary: str, *, direction: str = "maximize",
                  k: int = 3) -> list[dict]:
    """The ``k`` best ADMISSIBLE configurations observed so far, best first.

    A configuration qualifies when it has a ``complete`` row with a finite
    primary AND no row anywhere measured it ``infeasible`` / ``rejected``
    (``_config_admissible``): feasibility is judged per configuration, never
    per row.

    ``_best_observed`` is this with ``k=1``, and the two share one definition on
    purpose: "the best measured valid configuration" is the report's ``measured``
    rung AND the shortlist's model-free seed, and two enumerations of the same
    runs could disagree on the filter (which statuses count, whether a NaN counts
    as a value) while both looked reasonable.

    DEDUPLICATED BY LEVELS and ranked by each configuration's MEAN over its
    complete rows, never by its single best row. Ranking by the max is the
    winner's curse: on a real Go campaign one lucky row (140.6) out-ranked a
    configuration whose five confirm replicates then averaged 116.2, and
    confirm warned that its genuinely better winner was "10.56% worse than the
    best observed". Without deduplication, a confirm round's three replicates of one winner would fill a
    shortlist of three with the SAME configuration and the terminal comparison
    would have nothing to discriminate between — which is the failure mode the
    shortlist exists to retire.

    The caller that needs ``k > 1`` is ``_confirm_rows`` when the fitting stage
    reported ``model_adequate: false``: spec §3.6 rung 3 / the paper's "a small
    reserved budget remeasures the leading MEASURED valid candidates rather than
    choosing the largest noisy observation". Note the plural — one measured
    leader is the largest noisy observation, and re-measuring it alone only says
    how repeatable it is. Several of them, compared freshly against each other,
    is a model-free answer to which is better.

    SCOPED TO THE CURRENT EPOCH (``_this_epoch_runs``). A previous epoch's row
    names levels of factors this epoch may no longer declare: seating it ran the
    configuration with that factor at whatever the run command now fixes, while
    the finalist still CLAIMED the old level (found on the same campaign: an
    epoch-1 ``CONC=2`` seated in epoch 2, where concurrency was pinned to 1).
    """
    sign = 1.0 if direction != "minimize" else -1.0
    seen: dict[str, tuple[dict, list[float]]] = {}
    invalid = _measured_infeasible(work_dir)
    barred = _barred_levels(work_dir)  # read ONCE for the loop (Q3)
    for path in _this_epoch_runs(work_dir):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") != "complete":
                continue
            if _stage_reused(row):
                continue    # the screen row it copies is already counted
            value = (row.get("response") or {}).get(primary)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if numeric != numeric:
                continue
            levels = dict(row.get("levels") or {})
            if not levels:
                continue
            # PER CONFIGURATION, not per row: a complete row at levels that
            # ANOTHER row measured infeasible is not a valid answer (see
            # `_config_admissible`).
            if not _config_admissible(work_dir, levels, invalid=invalid, barred=barred):
                continue
            key = json.dumps(levels, sort_keys=True, default=str)
            seen.setdefault(key, (levels, []))[1].append(numeric)
    means = [(lv, sum(vs) / len(vs), len(vs)) for lv, vs in seen.values()]
    ranked = sorted(means, key=lambda t: -sign * t[1])
    return [{"levels": lv, primary: m, "n": n} for lv, m, n in ranked[:max(1, int(k))]]


def _this_epoch_dirs(work_dir) -> list[Path]:
    """The ``runs/iter-*`` directories of THIS epoch, in numeric order.

    Same epoch rule as ``_this_epoch_runs`` (a ``design_matrix.json`` naming a
    DIFFERENT policy hash excludes the iteration; no matrix or no hash keeps
    it), but over directories rather than ``runs.jsonl`` files: an iteration
    that wrote a recommendation.json or confirmation.json but no rows yet (an
    interrupted iteration, a hand-built fixture) is still this epoch's.
    """
    try:
        current = policy_mod.policy_hash(policy_mod.read_policy(Path(work_dir)))
    except Exception:  # no policy yet: nothing to scope by
        current = None
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return []

    def _idx(d: Path) -> int:
        try:
            return int(d.name.split("-", 1)[1])
        except (IndexError, ValueError):
            return -1

    out = []
    for d in sorted((d for d in runs.glob("iter-*") if d.is_dir()), key=_idx):
        if current is not None:
            dm = d / "design_matrix.json"
            try:
                h = json.loads(dm.read_text()).get("policy_hash") if dm.exists() else None
            except (OSError, ValueError):
                h = None
            if h and h != current:
                continue
        out.append(d)
    return out


def _this_epoch_runs(work_dir) -> list[Path]:
    """``runs.jsonl`` of the iterations that ran under the CURRENT policy.

    An iteration's ``design_matrix.json`` records the ``policy_hash`` it was
    built under; a recompiled epoch has a different hash. An iteration with no
    matrix or no recorded hash (pre-field work dirs, hand-built test fixtures)
    is kept, which reproduces the old behaviour exactly where the epoch cannot
    be told.
    """
    try:
        current = policy_mod.policy_hash(policy_mod.read_policy(Path(work_dir)))
    except Exception:  # no policy yet: nothing to scope by
        current = None
    out = []
    for path in sorted(Path(work_dir).glob("runs/iter-*/runs.jsonl"),
                       key=lambda p: int(p.parent.name.split("-")[1])):
        if current is not None:
            dm = path.parent / "design_matrix.json"
            try:
                h = json.loads(dm.read_text()).get("policy_hash") if dm.exists() else None
            except (OSError, ValueError):
                h = None
            if h and h != current:
                continue
        out.append(path)
    return out


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


def _outcome_from_run_row(row: dict) -> "runner.RunOutcome":
    """A ``RunOutcome`` reconstituted from a ``runs.jsonl`` row.

    The inverse of ``_run_row``, and only used for REUSED rows: a row carried
    forward from a previous attempt has to re-enter the outcome list the fit
    reads, and the log row is the only record of it.

    Round-tripping through JSON is lossless for every field the fit and the
    exclusion accounting use (``status``, ``response``, ``held_out``, the
    verdict lists, the instrumentation counters), because ``_run_row`` writes
    all of them and none is a Python object that JSON cannot represent. The one
    field that does NOT round-trip is ``reused_from`` — it has no ``RunOutcome``
    counterpart and does not need one: it is provenance for a READER of the log,
    and nothing in the fit branches on it. It stays on the log row.
    """
    return runner.RunOutcome(
        row_index=int(row.get("row_index", 0)),
        status=str(row.get("status") or ""),
        response=dict(row.get("response") or {}),
        manipulation=list(row.get("manipulation") or []),
        invariants=list(row.get("invariants") or []),
        duration_ms=int(row.get("duration_ms") or 0),
        error=str(row.get("error") or ""),
        failure_kind=str(row.get("failure_kind") or ""),
        attempts=int(row.get("attempts") or 1),
        last_attempt_ms=int(row.get("last_attempt_ms") or 0),
        held_out=dict(row.get("held_out") or {}),
        self_check=list(row.get("self_check") or []),
    )


def _run_row(row, outcome) -> dict:
    """One ``runs.jsonl`` row from a ConfigRow + RunOutcome pair.

    THE INSTRUMENTATION FIELDS (``duration_ms``, ``failure_kind``, ``attempts``,
    ``last_attempt_ms``) are what make ``runs.jsonl`` sufficient on its own to
    answer the two questions a dead campaign raises first: how long did this
    take, and why did it stop. Both used to require opening
    ``failed_runs/failed_run_N.log`` — a sibling file that a reader consulting
    the primary artifact has no reason to know exists, and which the artifact
    itself did not point at. ``duration_ms`` in particular was structurally
    always 0, so every row read as "measured, instantaneous"; sizing
    ``run_timeout_sec`` from the campaign's own data was impossible.
    """
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
        # Recorded even when every self-check passed, and even when none were
        # declared (an empty list). "Record enough to adjudicate a flag you
        # raise, not just to raise it" (guide §7.7): a reader of a row failed by
        # a self-check needs the observed value the predicate compared, and a
        # reader of a PASSING row needs to be able to tell "the invariant held"
        # from "no invariant was declared".
        "self_check": list(getattr(outcome, "self_check", []) or []),
        "duration_ms": int(outcome.duration_ms or 0),
        # Total across attempts; `attempts` and `last_attempt_ms` are what let a
        # reader tell a retried row's schedule cost (which a timeout budget must
        # cover) from its per-invocation cost (which the ceiling applies to).
        "attempts": int(getattr(outcome, "attempts", 1) or 1),
        "last_attempt_ms": int(getattr(outcome, "last_attempt_ms", 0) or 0),
        "error": outcome.error or "",
        # A closed-vocabulary label, set at the raise site rather than parsed
        # back out of `error`. "The apparatus ran out of time" and "the adapter
        # crashed" call for opposite repairs — a bigger budget versus a code fix
        # — and both arrived as `RuntimeError: ...` in `error`, so telling them
        # apart meant substring-matching prose. Empty on a clean row.
        "failure_kind": str(getattr(outcome, "failure_kind", "") or ""),
    }


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"

GOVERNED_ARTIFACTS: dict[str, str] = {
    "report.json": "report.schema.json",
    "recommendation.json": "recommendation.schema.json",
    "confirmation.json": "confirmation.schema.json",
    "shortlist.json": "shortlist.schema.json",
}
"""Artifacts of this kind whose shape is enforced at the moment they are written.

WHY THE ENFORCEMENT LIVES IN ``_write_json`` rather than at each call site.
A schema file that nothing validates against is not a check; it is a second copy
of the shape that drifts from the code silently, which is the failure mode
``check_policy`` was wired up to close for ``policy.json``. Putting the call in
the one function every artifact write already goes through means a NEW write site
cannot be added that skips validation — there is no per-call-site opt-in to
forget.

``report.json`` carries the load-bearing obligation (design spec §3.5): its
schema requires ``residual_regret_model`` and ``residual_regret_terminal``
INDEPENDENTLY, so a report that dropped either — or that collapsed the two into
one number — cannot reach disk. The two bounds rest on different assumptions
(the model bound carries the registered response class, the terminal bound
carries nothing but the fresh measurements), and one number advertising the
assumption-light guarantee while delivering the model-dependent one is exactly
what the separation exists to prevent.

Artifacts NOT listed here are unaffected — ``findings.json`` and
``principle_updates.json`` are validated by the shared reflective machinery
downstream, and the epoch/build records have no schema yet.
"""

_schema_cache: dict[str, dict] = {}


def _validate_artifact(name: str, payload) -> None:
    """Validate a governed artifact against its schema, or raise.

    Raises ``OptimizationAborted`` rather than letting ``jsonschema``'s own error
    escape, because a malformed artifact is a campaign-level hard-fail of the same
    class as a structurally invalid compiled policy: every downstream reader — the
    report ladder, the terminal state's shortlist seeding, a human auditing the
    certificate — joins on these fields, so shipping a report the schema rejects
    would put an unreadable certificate on disk and only fail later, somewhere
    that cannot say what went wrong.
    """
    schema_name = GOVERNED_ARTIFACTS.get(name)
    if schema_name is None:
        return
    import jsonschema

    if schema_name not in _schema_cache:
        _schema_cache[schema_name] = json.loads(
            (SCHEMA_DIR / schema_name).read_text(),
        )
    try:
        jsonschema.validate(payload, _schema_cache[schema_name])
    except jsonschema.ValidationError as exc:
        raise OptimizationGateFailed(
            f"{name} does not conform to {schema_name}: "
            f"{exc.message} (at {'/'.join(str(p) for p in exc.absolute_path) or '<root>'})",
        ) from exc


def _write_json(target: Path, payload) -> Path:
    import json

    from orchestrator.util import atomic_write

    target = Path(target)
    _validate_artifact(target.name, payload)
    atomic_write(target, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target
