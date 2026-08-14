"""Stage decision rule: what the campaign does next, in pure Python.

Between-stage adaptation is arithmetic on effect sizes, not a model call.
``decide_after_screen`` and ``decide_after_refine`` are pure functions of a
fitted model (``Fit``) plus the declared factors: no I/O, no LLM, no
randomness. Iteration N+1 inherits estimates and confidence intervals, not a
prose summary — a stronger form of "use what N learned" than passing
principles forward.

The four stages, one per campaign iteration by default::

    verify  -> screen -> refine -> confirm

``verify`` proves each lever engages and its native property tests pass.
``screen`` fits main effects (+ two-factor interactions) and asks which
factors matter. ``refine`` fits curvature on the survivors and solves for an
interior optimum. ``confirm`` reproduces the predicted optimum.

Four triggers name the cases this module cannot decide on its own — the
caller (``iteration.py``) decides whether a trigger warrants re-consulting
the model:

  * ``ALL_WITHIN_NOISE``     — every factor's main effect measured null;
                               the declared factor set was probably wrong.
  * ``LACK_OF_FIT``          — the linear model doesn't fit; the model form
                               (missing interaction/curvature) is inadequate.
  * ``OPTIMUM_OUTSIDE_HULL`` — the fitted stationary point falls outside the
                               screened range on some axis; the declared
                               ranges were too narrow to contain the optimum.
  * ``BEHAVIORAL_VIOLATION`` — a possible real non-monotonicity worth a
                               human/model look, not a bug in the fit.

Only ``significant is False`` is a measured null. ``significant is None``
means unknown (no independent error estimate — see ``effects.py``), and an
unknown effect is never dropped as if it were known and absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from orchestrator.optimize.effects import Fit
from orchestrator.optimize.factors import Factor, is_refinable
from orchestrator.optimize.relations import RelationVerdict

_HULL_LOW, _HULL_HIGH = -1.0, 1.0
_LOF_ALPHA = 0.05


class Stage(str, Enum):
    """The four stages of an optimization campaign, in order."""

    VERIFY = "verify"
    SCREEN = "screen"
    REFINE = "refine"
    CONFIRM = "confirm"


_DEFAULT_ORDER: tuple[Stage, ...] = (Stage.VERIFY, Stage.SCREEN, Stage.REFINE, Stage.CONFIRM)


class Trigger(str, Enum):
    """Cases where Python cannot decide and the model should be re-consulted.

    Reported, not acted on: this module only names them.
    """

    ALL_WITHIN_NOISE = "all_within_noise"
    LACK_OF_FIT = "lack_of_fit"
    OPTIMUM_OUTSIDE_HULL = "optimum_outside_hull"
    BEHAVIORAL_VIOLATION = "behavioral_violation"


@dataclass(frozen=True)
class StageDecision:
    """What happens next, and why."""

    next_stage: Stage | None
    triggers: tuple[Trigger, ...]
    surviving: tuple[str, ...]
    dropped: tuple[str, ...]
    rationale: str


def stage_for_iteration(campaign: dict, iteration: int) -> Stage:
    """Which stage a given iteration number runs.

    Defaults to the canonical verify -> screen -> refine -> confirm order.
    ``optimization.stages`` in the campaign dict overrides that mapping by
    index (1-based iteration -> 0-based list position), letting a campaign
    skip a stage (e.g. no refine when every factor is a 2-level choice).

    An iteration past the end of the mapping returns CONFIRM rather than
    wrapping back to an earlier stage — in particular never SCREEN, which
    would spend the whole benchmark budget re-answering a question the
    campaign already answered.
    """
    raw_stages = (campaign.get("optimization") or {}).get("stages")
    order = tuple(Stage(s) for s in raw_stages) if raw_stages else _DEFAULT_ORDER

    idx = iteration - 1
    if 0 <= idx < len(order):
        return order[idx]
    return Stage.CONFIRM


def _behavioral_trigger_note(behavioral_failures: tuple[RelationVerdict, ...]) -> str | None:
    """Rationale fragment naming the behavioral violation, or None if none."""
    if not behavioral_failures:
        return None
    names = ", ".join(v.relation_id for v in behavioral_failures)
    return (
        f"behavioral relation(s) {names} violated -- possible real "
        f"non-monotonicity worth interpreting (does not fail the campaign)"
    )


def _rationale_screen(surviving: tuple[str, ...], dropped: tuple[str, ...],
                       unknown: tuple[str, ...], next_stage: Stage,
                       triggers: tuple[Trigger, ...]) -> str:
    parts = []
    if dropped:
        parts.append(f"dropped {', '.join(dropped)} (CI contains zero)")
    if unknown:
        parts.append(f"kept {', '.join(unknown)} as unknown (no pure-error estimate)")
    if surviving:
        parts.append(f"surviving: {', '.join(surviving)}")
    else:
        parts.append("no factor survived screening")
    parts.append(f"-> {next_stage.value}" if next_stage else "-> escalate to model")
    if triggers:
        parts.append(f"triggers: {', '.join(t.value for t in triggers)}")
    return "; ".join(parts)


def decide_after_screen(fit: Fit, factors: list[Factor], *,
                         alpha: float = 0.05,
                         behavioral_failures: tuple[RelationVerdict, ...] = ()) -> StageDecision:
    """Decide the next stage from a screening fit.

    Drops factors whose main-effect CI contains zero (``significant is
    False``); keeps everything else, including factors with ``significant
    is None`` (unknown, not null — rule: an unmeasured effect is never
    silently dropped as if it were measured and found absent).

    Next stage:
      * REFINE if at least one surviving factor is refinable (numeric,
        more than two levels) -- there is curvature to fit.
      * CONFIRM otherwise -- either nothing survived, or everything that
        survived is a choice factor or a 2-level numeric factor, neither of
        which can carry curvature. Spending a refine stage on factors that
        cannot be refined is pure waste.

    ``alpha`` is accepted for interface symmetry with ``fit_effects``, but
    this function does not refit: it only reads the ``significant`` flags
    ``fit_effects`` already computed at whatever alpha it was called with.

    ``behavioral_failures`` are ``RelationVerdict``s (from
    ``relations.classify_failures``) for ``behavioral``-kind relations that
    did not pass their native test -- a possible real non-monotonicity
    (e.g. a lever that measures worse in isolation yet is required for the
    winning combination). This raises ``BEHAVIORAL_VIOLATION`` but, unlike
    ``ALL_WITHIN_NOISE`` / ``LACK_OF_FIT``, never by itself blocks the
    stage from advancing: a behavioral violation is a discovery worth
    interpreting, not a reason to stop. ``correctness`` relation failures
    are not this function's concern -- those hard-fail the campaign
    upstream of stage decisions entirely.
    """
    by_id = {f.id: f for f in factors}
    main_effects = {}
    for f in factors:
        for e in fit.effects:
            if e.terms == (f.id,):
                main_effects[f.id] = e
                break

    dropped: list[str] = []
    surviving: list[str] = []
    unknown: list[str] = []
    for f in factors:
        eff = main_effects.get(f.id)
        if eff is None or eff.significant is None:
            surviving.append(f.id)
            if eff is not None:
                unknown.append(f.id)
            continue
        if eff.significant is False:
            dropped.append(f.id)
        else:
            surviving.append(f.id)

    blocking_triggers: list[Trigger] = []
    # Every factor that was actually MEASURED (significant is not None) and
    # found null -- i.e. nothing informative survived, and something was
    # dropped for cause. Distinct from "everything is unknown", which is
    # not evidence the factor set was wrong.
    if not surviving and dropped:
        blocking_triggers.append(Trigger.ALL_WITHIN_NOISE)

    if fit.lack_of_fit_p is not None and fit.lack_of_fit_p < _LOF_ALPHA:
        blocking_triggers.append(Trigger.LACK_OF_FIT)

    # Behavioral violations are reported but never block advancement: a
    # monotonicity break is a discovery, not a reason to stop.
    triggers = list(blocking_triggers)
    if behavioral_failures:
        triggers.append(Trigger.BEHAVIORAL_VIOLATION)

    refinable_survivors = [fid for fid in surviving if is_refinable(by_id[fid])]
    if blocking_triggers:
        next_stage = None
    elif refinable_survivors:
        next_stage = Stage.REFINE
    else:
        next_stage = Stage.CONFIRM

    rationale = _rationale_screen(tuple(surviving), tuple(dropped), tuple(unknown),
                                   next_stage, tuple(triggers))
    behavioral_note = _behavioral_trigger_note(behavioral_failures)
    if behavioral_note:
        rationale = f"{rationale}; {behavioral_note}"

    return StageDecision(
        next_stage=next_stage,
        triggers=tuple(triggers),
        surviving=tuple(surviving),
        dropped=tuple(dropped),
        rationale=rationale,
    )


def _in_hull(stationary: dict) -> bool:
    return all(_HULL_LOW <= v <= _HULL_HIGH for v in stationary.values())


def decide_after_refine(fit: Fit, factors: list[Factor],
                         stationary: dict | None, *,
                         behavioral_failures: tuple[RelationVerdict, ...] = ()) -> StageDecision:
    """Decide the next stage from a refinement fit and its stationary point.

    ``stationary`` is the coded-space stationary point from
    ``solve_stationary_point`` (or ``None`` when the fit had no curvature
    terms to solve). Coordinates are compared against the screened design's
    coded range, [-1, 1] inclusive:

      * every coordinate inside [-1, 1] -> CONFIRM at the fitted optimum.
      * any coordinate outside [-1, 1]  -> OPTIMUM_OUTSIDE_HULL: the
        declared factor ranges were too narrow to contain the true optimum,
        so Python cannot pick a runnable confirm point on its own.
      * stationary is None -> CONFIRM at the best observed corner (there is
        no interior optimum to chase; report the best point actually run).

    ``behavioral_failures`` are ``RelationVerdict``s (from
    ``relations.classify_failures``) for ``behavioral``-kind relations that
    did not pass their native test. This raises ``BEHAVIORAL_VIOLATION``
    but never changes ``next_stage`` -- a behavioral violation is a
    discovery worth interpreting, not a reason to stop.

    Always proceeds to CONFIRM in this module's judgment (the "next stage"
    a caller would take absent escalation) even when OPTIMUM_OUTSIDE_HULL
    fires, because the trigger -- not a missing next_stage -- is what tells
    the caller a model consult is warranted before committing to a confirm
    point outside the declared design space.
    """
    surviving = tuple(f.id for f in factors)

    triggers: list[Trigger] = []
    if fit.lack_of_fit_p is not None and fit.lack_of_fit_p < _LOF_ALPHA:
        triggers.append(Trigger.LACK_OF_FIT)
    if behavioral_failures:
        triggers.append(Trigger.BEHAVIORAL_VIOLATION)
    behavioral_note = _behavioral_trigger_note(behavioral_failures)

    if stationary is None:
        rationale = (
            "no stationary point (fit has no curvature terms); confirming at "
            "the best observed corner instead of an interior optimum"
        )
        if triggers:
            rationale += f"; triggers: {', '.join(t.value for t in triggers)}"
        if behavioral_note:
            rationale += f"; {behavioral_note}"
        return StageDecision(
            next_stage=Stage.CONFIRM,
            triggers=tuple(triggers),
            surviving=surviving,
            dropped=(),
            rationale=rationale,
        )

    if not _in_hull(stationary):
        triggers.insert(0, Trigger.OPTIMUM_OUTSIDE_HULL)
        outside = {k: v for k, v in stationary.items()
                   if not (_HULL_LOW <= v <= _HULL_HIGH)}
        rationale = (
            f"stationary point {stationary} falls outside the declared design "
            f"space on {', '.join(sorted(outside))}; ranges were too narrow to "
            f"contain the optimum -- escalate before confirming"
        )
        if behavioral_note:
            rationale += f"; {behavioral_note}"
        return StageDecision(
            next_stage=Stage.CONFIRM,
            triggers=tuple(triggers),
            surviving=surviving,
            dropped=(),
            rationale=rationale,
        )

    rationale = f"stationary point {stationary} is inside the declared design space; confirming"
    if behavioral_note:
        rationale += f"; {behavioral_note}"
    if triggers:
        rationale += f"; triggers: {', '.join(t.value for t in triggers)}"
    return StageDecision(
        next_stage=Stage.CONFIRM,
        triggers=tuple(triggers),
        surviving=surviving,
        dropped=(),
        rationale=rationale,
    )
