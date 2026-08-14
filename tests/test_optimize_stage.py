"""Behavioral tests for the pure-Python stage decision rule.

Between-stage adaptation is arithmetic on effect sizes, not a model call:
these tests build real `Fit`/`Effect` objects (from `effects.py`) and real
`Factor` objects (from `factors.py`) and assert what `stage.py` decides —
never how it decides it.

This module's outputs are enums/tuples/strings, not floats it computes: the
one float-bearing decision (a stationary-point coordinate landing
inside/outside [-1, 1]) is exercised through boundary-value cases below
rather than through arithmetic this test file itself performs, so no
math.isclose is needed here.
"""
from __future__ import annotations

import dataclasses

from orchestrator.optimize.effects import Effect, Fit
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.stage import (
    Stage,
    StageDecision,
    Trigger,
    decide_after_refine,
    decide_after_screen,
    stage_for_iteration,
)


def _numeric_raw(**over):
    raw = {
        "id": "L1", "name": "queue_count", "type": "numeric",
        "levels": [2, 4, 8, 16], "grid": 1,
        "apply": "--queues={level}",
        "manipulation": {"observable": "telemetry.queue_count",
                         "op": "==", "value": "{level}"},
        "relations": [{"id": "R1", "kind": "correctness",
                       "statement": "baseline reproduces baseline",
                       "native_test": "tests/prop_q.py::test_noop"}],
    }
    raw.update(over)
    return raw


def _choice_raw(**over):
    raw = {
        "id": "L5", "name": "batching", "type": "choice",
        "levels": ["off", "on"],
        "apply": {"kind": "env_var", "name": "B", "value": "{level}"},
        "manipulation": {"observable": "telemetry.mean_batch_size",
                         "op": ">", "value": 1, "when": "on"},
        "relations": [{"id": "R3", "kind": "correctness",
                       "statement": "off is byte-identical to baseline",
                       "native_test": "tests/prop_b.py::test_off_noop"}],
    }
    raw.update(over)
    return raw


def _two_level_numeric_raw(**over):
    defaults = dict(id="L2", name="batch_size", levels=[1, 64], grid=1)
    defaults.update(over)
    return _numeric_raw(**defaults)


def _effect(label, estimate, *, ci_low=None, ci_high=None, significant=None,
            se=None, terms=None):
    """Build an Effect with sensible defaults for a main-effect term."""
    return Effect(
        label=label,
        terms=terms if terms is not None else (label,),
        estimate=estimate,
        se=se,
        ci_low=ci_low,
        ci_high=ci_high,
        significant=significant,
    )


def _fit(effects, **over):
    defaults = dict(
        intercept=10.0, effects=tuple(effects), n_runs=8,
        pure_error_var=None, pure_error_df=0,
        lack_of_fit_f=None, lack_of_fit_p=None,
        aliases=(), quadratic=(),
    )
    defaults.update(over)
    return Fit(**defaults)


# ---------------------------------------------------------------------------
# 1. stage_for_iteration default mapping
# ---------------------------------------------------------------------------

def test_stage_for_iteration_default_mapping():
    campaign = {}
    assert stage_for_iteration(campaign, 1) == Stage.VERIFY
    assert stage_for_iteration(campaign, 2) == Stage.SCREEN
    assert stage_for_iteration(campaign, 3) == Stage.REFINE
    assert stage_for_iteration(campaign, 4) == Stage.CONFIRM


# ---------------------------------------------------------------------------
# 2. explicit optimization.stages overrides the default mapping by index
# ---------------------------------------------------------------------------

def test_explicit_stages_list_overrides_default_mapping():
    campaign = {"optimization": {"stages": ["verify", "screen", "confirm"]}}
    assert stage_for_iteration(campaign, 1) == Stage.VERIFY
    assert stage_for_iteration(campaign, 2) == Stage.SCREEN
    assert stage_for_iteration(campaign, 3) == Stage.CONFIRM


# ---------------------------------------------------------------------------
# 3. out-of-range iteration returns CONFIRM, never a fresh SCREEN
# ---------------------------------------------------------------------------

def test_out_of_range_iteration_returns_confirm_not_a_fresh_screen():
    campaign = {}
    assert stage_for_iteration(campaign, 5) == Stage.CONFIRM
    assert stage_for_iteration(campaign, 99) == Stage.CONFIRM

    explicit = {"optimization": {"stages": ["verify", "screen", "confirm"]}}
    assert stage_for_iteration(explicit, 4) == Stage.CONFIRM
    assert stage_for_iteration(explicit, 4) != Stage.SCREEN


# ---------------------------------------------------------------------------
# 4. decide_after_screen drops factors whose CI contains zero, keeps the rest
# ---------------------------------------------------------------------------

def test_decide_after_screen_drops_ci_contains_zero_keeps_the_rest():
    factors = parse_factors([
        _numeric_raw(id="A"), _numeric_raw(id="B"), _numeric_raw(id="C"),
    ])
    fit = _fit([
        _effect("A", -0.95, ci_low=-1.2, ci_high=-0.7, significant=True),
        _effect("B", 2.0, ci_low=1.5, ci_high=2.5, significant=True),
        _effect("C", 0.02, ci_low=-0.05, ci_high=0.09, significant=False),
    ], pure_error_var=0.001, pure_error_df=4)
    decision = decide_after_screen(fit, factors)
    assert decision.dropped == ("C",)
    assert set(decision.surviving) == {"A", "B"}


# ---------------------------------------------------------------------------
# 5. >=1 surviving refinable factor (numeric, >2 levels) -> REFINE
# ---------------------------------------------------------------------------

def test_surviving_refinable_numeric_factor_goes_to_refine():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", -0.95, ci_low=-1.2, ci_high=-0.7, significant=True),
        _effect("B", 0.01, ci_low=-0.05, ci_high=0.07, significant=False),
    ], pure_error_var=0.001, pure_error_df=4)
    decision = decide_after_screen(fit, factors)
    assert decision.next_stage == Stage.REFINE
    assert decision.surviving == ("A",)


# ---------------------------------------------------------------------------
# 6. only choice factors survive -> CONFIRM (nothing to refine)
# ---------------------------------------------------------------------------

def test_only_choice_factors_surviving_goes_to_confirm():
    factors = parse_factors([_choice_raw(id="X"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("X", 1.4, ci_low=1.0, ci_high=1.8, significant=True),
        _effect("B", 0.01, ci_low=-0.05, ci_high=0.07, significant=False),
    ], pure_error_var=0.001, pure_error_df=4)
    decision = decide_after_screen(fit, factors)
    assert decision.surviving == ("X",)
    assert decision.next_stage == Stage.CONFIRM


# ---------------------------------------------------------------------------
# 7. only 2-level numeric factors survive -> CONFIRM
# ---------------------------------------------------------------------------

def test_only_two_level_numeric_factors_surviving_goes_to_confirm():
    factors = parse_factors([_two_level_numeric_raw(id="D"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("D", 3.0, ci_low=2.5, ci_high=3.5, significant=True),
        _effect("B", 0.01, ci_low=-0.05, ci_high=0.07, significant=False),
    ], pure_error_var=0.001, pure_error_df=4)
    decision = decide_after_screen(fit, factors)
    assert decision.surviving == ("D",)
    assert decision.next_stage == Stage.CONFIRM


# ---------------------------------------------------------------------------
# 8. every factor within noise -> ALL_WITHIN_NOISE trigger
# ---------------------------------------------------------------------------

def test_all_factors_within_noise_raises_the_trigger():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", 0.01, ci_low=-0.05, ci_high=0.06, significant=False),
        _effect("B", -0.02, ci_low=-0.08, ci_high=0.03, significant=False),
    ], pure_error_var=0.001, pure_error_df=4)
    decision = decide_after_screen(fit, factors)
    assert decision.surviving == ()
    assert decision.dropped == ("A", "B")
    assert Trigger.ALL_WITHIN_NOISE in decision.triggers


def test_unknown_significance_is_not_treated_as_all_within_noise():
    """An unmeasured (significant is None) effect must never be silently
    dropped as if it were measured and found absent (rule 1). With no
    pure-error estimate, both factors are unknown, not null: this must
    NOT raise ALL_WITHIN_NOISE, and both factors must survive.
    """
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", 0.5, ci_low=None, ci_high=None, significant=None),
        _effect("B", -0.3, ci_low=None, ci_high=None, significant=None),
    ], pure_error_var=None, pure_error_df=0)
    decision = decide_after_screen(fit, factors)
    assert decision.dropped == ()
    assert set(decision.surviving) == {"A", "B"}
    assert Trigger.ALL_WITHIN_NOISE not in decision.triggers


# ---------------------------------------------------------------------------
# 9. lack_of_fit_p < 0.05 -> LACK_OF_FIT trigger
# ---------------------------------------------------------------------------

def test_significant_lack_of_fit_raises_the_trigger():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", 1.0, ci_low=0.5, ci_high=1.5, significant=True),
        _effect("B", 0.5, ci_low=0.1, ci_high=0.9, significant=True),
    ], pure_error_var=0.01, pure_error_df=3,
        lack_of_fit_f=12.0, lack_of_fit_p=0.01)
    decision = decide_after_screen(fit, factors)
    assert Trigger.LACK_OF_FIT in decision.triggers


def test_non_significant_lack_of_fit_does_not_raise_the_trigger():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", 1.0, ci_low=0.5, ci_high=1.5, significant=True),
        _effect("B", 0.5, ci_low=0.1, ci_high=0.9, significant=True),
    ], pure_error_var=0.01, pure_error_df=3,
        lack_of_fit_f=0.4, lack_of_fit_p=0.8)
    decision = decide_after_screen(fit, factors)
    assert Trigger.LACK_OF_FIT not in decision.triggers


# ---------------------------------------------------------------------------
# 10. decide_after_refine, stationary point inside [-1, 1] on every axis
#     -> CONFIRM, no OPTIMUM_OUTSIDE_HULL
# ---------------------------------------------------------------------------

def test_stationary_point_inside_hull_goes_to_confirm_without_trigger():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", -0.1, terms=("A",)),
        _effect("B", 0.2, terms=("B",)),
    ], quadratic=(
        _effect("A^2", -2.0, terms=("A", "A")),
        _effect("B^2", -1.0, terms=("B", "B")),
    ))
    stationary = {"A": 0.5, "B": -0.7}
    decision = decide_after_refine(fit, factors, stationary)
    assert decision.next_stage == Stage.CONFIRM
    assert Trigger.OPTIMUM_OUTSIDE_HULL not in decision.triggers


# ---------------------------------------------------------------------------
# 11. any coordinate outside [-1, 1] -> OPTIMUM_OUTSIDE_HULL trigger
# ---------------------------------------------------------------------------

def test_stationary_point_outside_hull_raises_the_trigger():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", -0.1, terms=("A",)),
        _effect("B", 0.2, terms=("B",)),
    ], quadratic=(
        _effect("A^2", -2.0, terms=("A", "A")),
        _effect("B^2", -1.0, terms=("B", "B")),
    ))
    stationary = {"A": 0.5, "B": 1.4}
    decision = decide_after_refine(fit, factors, stationary)
    assert Trigger.OPTIMUM_OUTSIDE_HULL in decision.triggers


def test_stationary_point_exactly_at_the_hull_boundary_is_inside():
    """[-1, 1] is closed: a coordinate landing exactly on the boundary is
    still a valid, runnable design point and must not raise the trigger.
    """
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", -0.1, terms=("A",)),
        _effect("B", 0.2, terms=("B",)),
    ], quadratic=(
        _effect("A^2", -2.0, terms=("A", "A")),
        _effect("B^2", -1.0, terms=("B", "B")),
    ))
    stationary = {"A": 1.0, "B": -1.0}
    decision = decide_after_refine(fit, factors, stationary)
    assert Trigger.OPTIMUM_OUTSIDE_HULL not in decision.triggers


# ---------------------------------------------------------------------------
# 12. decide_after_refine with stationary is None -> CONFIRM at best
#     observed corner, with a rationale saying so
# ---------------------------------------------------------------------------

def test_stationary_none_confirms_at_best_observed_corner():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])
    fit = _fit([
        _effect("A", -0.1, terms=("A",)),
        _effect("B", 0.2, terms=("B",)),
    ])
    decision = decide_after_refine(fit, factors, None)
    assert decision.next_stage == Stage.CONFIRM
    assert Trigger.OPTIMUM_OUTSIDE_HULL not in decision.triggers
    assert "corner" in decision.rationale.lower()


# ---------------------------------------------------------------------------
# 13. rationale is non-empty in every decision
# ---------------------------------------------------------------------------

def test_rationale_is_never_empty():
    factors = parse_factors([_numeric_raw(id="A"), _numeric_raw(id="B")])

    screen_fit = _fit([
        _effect("A", -0.95, ci_low=-1.2, ci_high=-0.7, significant=True),
        _effect("B", 0.01, ci_low=-0.05, ci_high=0.07, significant=False),
    ], pure_error_var=0.001, pure_error_df=4)
    screen_decision = decide_after_screen(screen_fit, factors)
    assert screen_decision.rationale != ""

    all_noise_fit = _fit([
        _effect("A", 0.01, ci_low=-0.05, ci_high=0.06, significant=False),
        _effect("B", -0.02, ci_low=-0.08, ci_high=0.03, significant=False),
    ], pure_error_var=0.001, pure_error_df=4)
    all_noise_decision = decide_after_screen(all_noise_fit, factors)
    assert all_noise_decision.rationale != ""

    refine_fit = _fit([
        _effect("A", -0.1, terms=("A",)),
        _effect("B", 0.2, terms=("B",)),
    ], quadratic=(
        _effect("A^2", -2.0, terms=("A", "A")),
        _effect("B^2", -1.0, terms=("B", "B")),
    ))
    inside_decision = decide_after_refine(refine_fit, factors, {"A": 0.1, "B": -0.2})
    assert inside_decision.rationale != ""

    outside_decision = decide_after_refine(refine_fit, factors, {"A": 2.0, "B": -0.2})
    assert outside_decision.rationale != ""

    none_decision = decide_after_refine(refine_fit, factors, None)
    assert none_decision.rationale != ""


# ---------------------------------------------------------------------------
# Additional coverage: StageDecision shape, and behavioral-violation trigger
# is namable even though decide_after_screen/decide_after_refine don't
# currently have a behavioral-relation input to raise it from directly.
# ---------------------------------------------------------------------------

def test_trigger_and_stage_enums_are_str_enums_with_expected_members():
    assert Stage.VERIFY == "verify"
    assert Stage.SCREEN == "screen"
    assert Stage.REFINE == "refine"
    assert Stage.CONFIRM == "confirm"
    assert Trigger.ALL_WITHIN_NOISE == "all_within_noise"
    assert Trigger.LACK_OF_FIT == "lack_of_fit"
    assert Trigger.OPTIMUM_OUTSIDE_HULL == "optimum_outside_hull"
    assert Trigger.BEHAVIORAL_VIOLATION == "behavioral_violation"


def test_stage_decision_is_a_frozen_dataclass_with_the_documented_fields():
    factors = parse_factors([_numeric_raw(id="A")])
    fit = _fit([_effect("A", -0.95, ci_low=-1.2, ci_high=-0.7, significant=True)],
               pure_error_var=0.001, pure_error_df=4)
    decision = decide_after_screen(fit, factors)
    assert isinstance(decision, StageDecision)
    assert isinstance(decision.triggers, tuple)
    assert isinstance(decision.surviving, tuple)
    assert isinstance(decision.dropped, tuple)
    assert isinstance(decision.rationale, str)
    try:
        decision.rationale = "mutated"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("StageDecision must be frozen")
