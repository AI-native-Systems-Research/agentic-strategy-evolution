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
only this epoch's rows, a later ``nous run --resume`` over the same work_dir
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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from orchestrator.optimize import artifacts, certificate, decide, matrix, relations, runner
from orchestrator.optimize import design as design_mod
from orchestrator.optimize import policy as policy_mod
from orchestrator.optimize.effects import fit_effects, solve_stationary_point
from orchestrator.optimize.factors import is_refinable, parse_factors
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

    THE NaN-ON-A-COMPLETE-ROW CASE NO LONGER REACHES HERE. ``run_stage`` checks
    for it before calling this function and routes it to the policy's
    ``nan_response -> exception`` branch, because that condition is SEMANTIC (the
    objective and the target's instrumentation disagree about what is measurable
    at that configuration; no re-run repairs it) and the paper's rule is that it
    ends the epoch while the campaign still returns an action. An abort here would
    end the campaign with no report at all.

    The remaining aborts are a DIFFERENT failure class each, and all four stay:

      * ``primary`` is also declared ``held_out`` — a campaign misconfiguration,
        caught before any measurement is interpreted;
      * a held-out metric reached a fitting input — the leak this path exists to
        refuse, one of the three checks that hard-fail under auto-approve;
      * the primary metric is a string or a structure — an instrumentation
        mismatch, not a measurement, and not a NaN (see ``_primary_is_nan``);
      * rows that never reached ``complete`` carry no measurement — a MEASUREMENT
        failure, which re-running the configurations repairs. Nothing semantic has
        been discovered, so ending the epoch would tell the next agent to revise
        an interface that is fine.
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
    noise = ((_opt_block(campaign) or {}).get("response") or {}).get(
        "noise_estimate_pct",
    )
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


def _check_tests_failed_before_build(
    campaign: dict, work_dir: Path, factors, test_results: dict | None,
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
    if not path.exists():
        return
    if _build_checks(campaign).get("allow_preexisting_tests"):
        logger.info(
            "verify: build_checks.allow_preexisting_tests is set — not checking "
            "whether declared correctness tests already passed before the build",
        )
        return
    try:
        pre = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OptimizationAborted(
            f"pre_build_tests.json exists but could not be read ({exc}). It is "
            f"the record of which declared tests passed BEFORE the mechanism "
            f"existed, and that question is unanswerable now that it does — "
            f"delete the work_dir and re-run the build stage rather than "
            f"proceeding without the check.",
        ) from exc
    already = set(pre.get("passed") or ())
    if not already:
        return
    bad = sorted({
        v.native_test for v in relations.reconcile(factors, test_results or {})
        if v.kind == "correctness" and v.native_test in already
    })
    if not bad:
        return
    raise OptimizationAborted(
        f"native test(s) {', '.join(bad)} passed before the mechanism existed "
        f"— a test that passes without the mechanism does not test it, so it "
        f"cannot certify the apparatus every later measurement rests on. Either "
        f"strengthen the test so it fails against the pre-build tree, or set "
        f"optimization.build_checks.allow_preexisting_tests: true if the test "
        f"genuinely covers pre-existing behaviour (a backward-compatibility "
        f"relation is the legitimate case).",
    )


def _check_baseline_equivalence(
    campaign: dict, work_dir: Path, factors, config_runner: Callable | None,
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
    Every not-armed path says so at WARNING, because the alternative is a
    campaign author assuming a check ran when nothing did.
    """
    path = Path(work_dir) / "baseline_equivalence.json"
    if not path.exists():
        return
    try:
        rec = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OptimizationAborted(
            f"baseline_equivalence.json exists but could not be read ({exc}). It "
            f"holds the pre-build control measurement, which cannot be retaken "
            f"now that the mechanism is in the tree — re-run the build stage "
            f"rather than proceeding without the check.",
        ) from exc
    pre = list(rec.get("pre") or ())
    levels = dict(rec.get("levels") or {})
    unavailable = rec.get("pre_unavailable")
    if unavailable and not pre:
        # The build stage tried and could not. Say so loudly and proceed: the
        # pre-build measurement is gone for good (the mechanism is in the tree
        # now), so there is nothing to compare against and no way to recover it
        # without re-running the build.
        logger.warning(
            "verify: ORACLE 2(c) IS NOT ARMED for this campaign. The control "
            "configuration %s could not be measured before the build (%s), so "
            "nothing verifies that the mechanism is inert at its control level "
            "— a mechanism that shifts the metric at its OFF setting would "
            "confound every effect this epoch measures, and that would not be "
            "detected. The epoch proceeds. To arm the oracle, make the "
            "run_command able to execute the control configuration BEFORE the "
            "build stage runs, then start a fresh campaign.",
            levels or "<unrecorded>", unavailable,
        )
        return
    if not pre or not levels:
        return
    if config_runner is None:
        logger.warning(
            "verify: a pre-build control measurement exists but no config_runner "
            "is available, so baseline equivalence cannot be re-measured. The "
            "epoch will run without oracle 2(c).",
        )
        return

    from orchestrator.optimize import build as build_mod

    metric = (
        (((_opt_block(campaign) or {}).get("response") or {}).get("primary") or {})
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
    raise OptimizationAborted(
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
    try:
        policy_mod.write_policy(work_dir, pol)
    except ValueError as exc:
        # `check_policy` covers the closed observation/operator vocabulary and
        # reachability; `write_policy`'s schema check covers the shape
        # constraints neither `check_policy` nor `compile_policy` enforces
        # (`policy_version` pinned to 1, the `epsilon` `abs`/`pct` `oneOf`, the
        # delta bounds). Both are pre-registration failures of the same class,
        # so both abort the campaign the same way.
        raise OptimizationAborted(str(exc)) from exc
    return pol


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
    factor), and the NEXT ``nous run --resume`` is what has to notice. Notice it
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
    recorded = Path(work_dir) / "policy.sha256"
    if recorded.exists() and recorded.read_text().strip() != policy_mod.policy_hash(pol):
        raise OptimizationAborted(
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
        raise OptimizationAborted(
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

    base = iteration if confirm else int(payload.get("run_order_seed", iteration))
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
        raise OptimizationAborted(
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
            "not rest on the fitted surface; a revision plus `nous run --resume` "
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
        and not _measured_infeasible_contains(work_dir, rec["levels"])
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

    # EPOCH-SCOPED, like every other consumer of this file. `transitions.jsonl`
    # is append-only ACROSS epochs (see `policy.epoch_transitions`), so an
    # unfiltered read would splice the previous epoch's rows into THIS epoch's
    # reported `path` — a campaign whose epoch 1 ended at `exception` and
    # recompiled would report `screen -> screen -> confirm -> report`, naming a
    # state transition that never happened in the epoch the report describes.
    trans = policy_mod.epoch_transitions(pol, work_dir)
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
        # Present ONLY when a semantic exception ended the epoch, and then it is
        # the guard that fired. A reader must be able to tell an ordinary report
        # from one written on the way out of a failed epoch without reading the
        # log, which is the same reason `basis` exists — and `epoch_end-<e>.json`
        # carries the full record next to it.
        **({"epoch_ended": epoch_ended} if epoch_ended else {}),
        "policy_hash": policy_mod.policy_hash(pol),
        "iteration": iteration,
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
            opt["test_command"], cwd=Path(repo),
            log_path=Path(work_dir) / "runs" / f"iter-{iteration}" / "test_output.log",
        )
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
            opt["run_command"], cwd=Path(repo),
            metric_path=((opt.get("response") or {}).get("primary") or {}).get(
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
        _write_json(Path(work_dir) / "pre_build_tests.json", {
            "passed": sorted(t for t, ok in (test_results or {}).items() if ok),
            "ran": sorted(test_results or {}),
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
                ((opt.get("response") or {}).get("primary") or {}).get("metric") or ""
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
        build_mod.run_build(
            campaign, work_dir,
            iteration=iteration,
            declared_tests=build_mod.declared_native_tests(_factors_for_build),
            model=model,
            max_turns=_build_max_turns(campaign),
            sdk_runner=sdk_runner,
        )
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
    elif repo and stage_name not in policy_mod.pre_epoch_stages(campaign):
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
            current = build_mod.current_mechanism_hash(
                Path(repo), allowlist=_paths,
            )
            if current != recorded:
                _scope = (
                    f"scope: {', '.join(_paths)}" if _paths else
                    "scope: the whole working tree — if the difference is an "
                    "artifact of the test or run command (a .pytest_cache/, a "
                    "log, a coverage file) rather than a code change, that is "
                    "a FALSE POSITIVE: gitignore it, or declare "
                    "optimization.build_checks.mechanism_paths naming only the "
                    "mechanism's own files"
                )
                raise OptimizationAborted(
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
    primary = ((response_spec.get("primary") or {}).get("metric")) or ""
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
        # ── oracle 2(b)/(c): the two build claims that "tests pass" cannot make ──
        #
        # Run BEFORE the policy is compiled, deliberately. A compiled policy is
        # a pre-registration; writing one and then discovering the apparatus was
        # never actually tested (2(b)) or is not the system the control
        # describes (2(c)) would leave a signed commitment to a broken
        # experiment on disk for a later resume to pick up.
        _check_tests_failed_before_build(campaign, work_dir, factors, test_results)
        _check_baseline_equivalence(campaign, work_dir, factors, config_runner)
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
        on = _fold_on(factors, design_cfg, pairs)
        screen_design = _build_design(factors, design_cfg, Stage.SCREEN.value)
        design = _build_design(
            factors, design_cfg, stage_name, fold_on=on,
        )
        payload = matrix.matrix_payload(design, factors, run_order_seed=iteration)
        rows = matrix.expand(design, factors)
        # Provenance the combined fit rests on: WHICH column was negated, and
        # WHICH iteration's runs are the other half of the response vector. A
        # reader who cannot answer both cannot reproduce the effects.json this
        # iteration writes.
        payload["folded_on"] = on
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
        if getattr(o, "status", None) == "complete" and _primary_is_nan(o, primary)
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
    alias_pairs_consequential = decide.alias_consequential(
        fit, factors, direction=direction, fitted_ids=fitted_ids,
        held_fixed=held_now, exclude_levels=excluded,
        epsilon_pct=float((pol["objective"]["epsilon"] or {}).get("pct", 2.0)),
    )
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
        "model_adequate": Trigger.LACK_OF_FIT not in set(decision.triggers),
        "excluded_measured_infeasible": excluded,
        "residual_regret_model": rb.as_dict(),
        "epsilon": epsilon,
        "alias_consequential": [list(p) for p in alias_pairs_consequential],
        "aliases": [list(p) for p in fit.aliases],
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
    resolution = int((design_cfg.get("screen") or {}).get("resolution", 5))
    if resolution <= 3:
        return None
    ids = [f.id for f in factors]
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
            return match
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
    return None


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
        if row is None or row.get("status") != "complete" or raw is None:
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
      3. ``recommendation.json``'s ``top_candidates`` in order — the near
         misses whose intervals still reach above x-hat.

    UNLESS ``recommendation.json["model_adequate"] is False``, in which case rungs
    1 and 2 are replaced by ``_top_measured``'s leading MEASURED valid candidates
    (plural) and rung 3 still fills whatever seats remain. A lack-of-fit verdict
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
        # here actually is: a statistical one, F ~ 1000 on these near-noiseless
        # surfaces because center-point replication under-states the variance the
        # campaign faces (spec §3.5's own warning). Seating the measured leaders
        # ABOVE the ranking discounts it; discarding the ranking would treat that
        # F as proof the ordering carries no information at all.
        #
        # DEFAULTS TO TRUE for an absent key. Every recommendation written before
        # this field existed came from a stage that had no lack-of-fit verdict
        # recorded here, and treating "not stated" as "inadequate" would silently
        # switch every such campaign's terminal stage to a different shortlist.
        model_ok = bool(rec.get("model_adequate", True))
        if model_ok:
            _add(rec.get("levels"), f"{rec.get('stage') or 'model'} recommendation")
            best = _best_observed(work_dir, primary, direction=direction)
            if best is not None:
                _add(best["levels"], "best measured valid configuration")
        else:
            logger.info(
                "confirm round %d: the fitting stage reported model_adequate="
                "false (lack of fit), so the shortlist is SEEDED from the "
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
                                  "(model inadequate)")
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
        if not rec.get("model_adequate", True):
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
                     f"(model inadequate)")
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
        "round": payload.get("round", _confirm_round(work_dir, pol)),
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
    carry = _next_round_finalists(summary, shortlist_size=_cfg.get("shortlist_size", 3))
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


def _next_round_finalists(summary: dict, *, shortlist_size) -> int:
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
    # carry-over rule nominates, so the estimate caps there too.
    return min(k, len(carry)) if carry else k


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
    """The ``k`` best COMPLETED configurations observed so far, best first.

    ``_best_observed`` is this with ``k=1``, and the two share one definition on
    purpose: "the best measured valid configuration" is the report's ``measured``
    rung AND the shortlist's model-free seed, and two enumerations of the same
    runs could disagree on the filter (which statuses count, whether a NaN counts
    as a value) while both looked reasonable.

    DEDUPLICATED BY LEVELS, keeping the best measurement of each configuration.
    Without that, a confirm round's three replicates of one winner would fill a
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
    """
    sign = 1.0 if direction != "minimize" else -1.0
    best: dict[str, tuple[dict, float]] = {}
    for path in sorted(Path(work_dir).glob("runs/iter-*/runs.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
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
            levels = dict(row.get("levels") or {})
            if not levels:
                continue
            key = json.dumps(levels, sort_keys=True, default=str)
            prior = best.get(key)
            if prior is None or sign * numeric > sign * prior[1]:
                best[key] = (levels, numeric)
    ranked = sorted(best.values(), key=lambda pair: -sign * pair[1])
    return [{"levels": lv, primary: v} for lv, v in ranked[:max(1, int(k))]]


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
        raise OptimizationAborted(
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
