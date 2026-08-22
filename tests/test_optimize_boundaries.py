"""Boundary-value analysis and equivalence partitioning at the abort/proceed line.

Every case here sits on a numeric or structural boundary where the code changes
its mind: fit or refuse, certify or decline, serial or parallel, tabulated or
not. For each knob the module docstring-level comment states the EQUIVALENCE
CLASSES, and the tests exercise one representative per class plus BOTH SIDES of
every boundary — the value at the boundary and the value one step either way,
because an off-by-one in a `<` vs `<=` is exactly the defect this technique
exists to find.

Where a boundary produced a real finding it is called out at the test. The
highest-value one in this file is the terminal certificate's replicate floor:
the `>= 2 replicates` requirement is a COUNT check, so three IDENTICAL
measurements satisfy a floor that exists to guarantee a variance estimate — and
the bound then certifies exact optimality from zero information.
"""
from __future__ import annotations

import math

import pytest

from orchestrator.optimize import concurrency, design as design_mod
from orchestrator.optimize.certificate import (
    model_regret_bound, resolve_epsilon, terminal_regret_bound,
)
from orchestrator.optimize.decide import ranked, recommend
from orchestrator.optimize.design import (
    full_factorial, fractional_factorial, is_tabulated, min_runs_for,
    with_center_points,
)
from orchestrator.optimize.effects import fit_effects, pure_error
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.policy import compile_policy, check_policy, step
from orchestrator.optimize.synthetic import _choice, _numeric

pytestmark = pytest.mark.boundary


def _campaign(**opt_over) -> dict:
    opt = {
        "response": {"primary": {"metric": "m", "direction": "maximize"}},
        "factors": [_numeric("A", levels=(2, 4, 8, 16)), _choice("B")],
        "design": {"screen": {"resolution": 5, "center_points": 4},
                   "refine": {"kind": "central_composite", "center_points": 4},
                   "confirm": {"shortlist_size": 3, "replicates": 3}},
    }
    opt.update(opt_over)
    return {"kind": "optimization", "run_id": "bva", "research_question": "q",
            "target_system": {"name": "t", "description": "d"},
            "optimization": opt}


# ══ 1. pure_error's replicate floor ════════════════════════════════════════
#
# EQUIVALENCE CLASSES for the number of replicated centre points n:
#   n = 0      -> no centre rows at all           -> (None, 0)
#   n = 1      -> one row, no variance estimable  -> (None, 0)   [BOUNDARY]
#   n = 2      -> the minimum estimable            -> (var, 1)   [BOUNDARY]
#   n >= 3     -> estimable, more df               -> (var, n-1)
# The boundary is between 1 and 2, and BOTH sides are tested.


@pytest.mark.parametrize("n,expect_var,expect_df", [
    (0, False, 0), (1, False, 0), (2, True, 1), (3, True, 2), (8, True, 7),
])
def test_pure_error_replicate_floor_at_both_sides_of_two(n, expect_var, expect_df):
    """The 1-vs-2 boundary: a single measurement has no variance.

    Below the floor `pure_error` returns `None` rather than 0.0, which is the
    difference between "cannot estimate" and "estimated zero" — and every
    interval in the fit divides by this number.
    """
    vals = [10.0 + 0.1 * i for i in range(n)]
    var, df = pure_error(vals)
    assert (var is not None) is expect_var, (n, var)
    assert df == expect_df
    if var is not None:
        assert var >= 0.0


@pytest.mark.mutation_sentinel
def test_pure_error_of_identical_replicates_is_exactly_zero_not_none():
    """The DEGENERATE case inside the estimable class: variance 0.0, df > 0.

    A deterministic target legitimately returns identical numbers. `pure_error`
    correctly reports 0.0 with real degrees of freedom — it is not the defect.
    The defect is downstream, in what the certificate does with a zero variance;
    see `test_terminal_bound_certifies_from_zero_information`.
    """
    var, df = pure_error([7.0, 7.0, 7.0])
    assert var == 0.0 and df == 2


# ══ 2. the terminal certificate's replicate + variance boundaries ══════════
#
# EQUIVALENCE CLASSES for terminal_regret_bound's inputs:
#   |finalists| = 1          -> "trivial", value 0.0    [no discrimination]
#   any finalist n < 2       -> "none", value None      [BOUNDARY: 1 vs 2]
#   n >= 2, variance > 0     -> a real Welch/paired bound
#   n >= 2, variance == 0    -> ??? -- THE FINDING BELOW


@pytest.mark.parametrize("n", [1, 2, 3])
def test_terminal_bound_replicate_floor_at_both_sides_of_two(n):
    """n=1 cannot bound; n=2 is the minimum that can."""
    samples = {"f1": [5.0 + 0.3 * i for i in range(n)],
               "f2": [7.0 + 0.2 * i for i in range(n)]}
    b = terminal_regret_bound(samples, "f2", delta=0.05, direction="maximize",
                              paired=False)
    if n < 2:
        assert b.value is None and b.method == "none"
    else:
        assert b.value is not None and b.value >= 0.0


def test_a_single_finalist_is_the_no_discrimination_boundary():
    """shortlist_size = 1 makes terminal DISCRIMINATION impossible.

    The bound is 0.0 by the honest argument (there is nothing to compare
    against), and the method says `trivial` rather than naming a test that was
    never run. `shortlist_size: 3` is the default for exactly this reason — one
    configuration replicated measures repeatability, not superiority.
    """
    b = terminal_regret_bound({"f1": [1.0, 2.0, 3.0]}, "f1", delta=0.05,
                              direction="maximize", paired=False)
    assert b.value == 0.0 and b.method == "trivial" and b.challenger is None


@pytest.mark.mutation_sentinel
def test_terminal_bound_refuses_to_certify_from_zero_information():
    """THE VARIANCE BOUNDARY, at exactly 0. FIXED -- xfail removed.

    A deterministic target (or a cached/stale read — the very thing the adapter's
    freshness guard exists to catch) returns identical replicates. The count
    floor passes, `variance([7,7,7]) == 0`, the standard error is 0, and the
    one-sided bound collapses to the point estimate — so the campaign reports
    `residual_regret_terminal = 0.0` and `basis: certified`: PROVEN optimal, from
    measurements carrying no information about variability at all.

    Contrast at the boundary, which is what makes this a BVA finding rather than
    a style objection:
      variance = 0      -> value 0.0, method bonferroni_one_sided_t_paired  (certifies)
      variance = 1e-12  -> a real bound, essentially 0.0                    (certifies)
      variance = 1.0    -> a real bound, wide                               (declines)
    The first row should be `None`/"none" like `model_regret_bound`'s
    zero-df case, because a zero SAMPLE variance from 3 points is not evidence of
    a zero POPULATION variance.

    The machine-checkable symptom, and the reason this is also a metamorphic
    failure: a genuine bound RESPONDS to its error budget. Here it is 0.0 for
    every delta, so the certificate is delta-independent.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT05 — the statement of
    record lives there; this test is the executable check.
    """
    zero_var = {"f1": [5.0, 5.0, 5.0], "f2": [7.0, 7.0, 7.0]}
    b = terminal_regret_bound(zero_var, "f2", delta=0.05, direction="maximize",
                              paired=True)
    assert b.value is None and b.method == "none", (
        f"certified value={b.value} method={b.method!r} from zero-variance "
        f"replicates — exact optimality proven from no information"
    )


def test_the_refusal_is_delta_independent_but_a_real_bound_never_is():
    """FIXED, and updated exactly as the previous version said it should be.

    That version pinned the defect: at zero variance the bound returned 0.0 for
    EVERY delta, which was the machine-checkable symptom — a genuine bound
    responds to its error budget, and one that ignores delta entirely is not
    reading any evidence. It said "if the bound starts returning None, this
    test's 0.0 expectations fail loudly and it gets updated alongside." They did,
    and this is the update.

    The refusal is still delta-independent, and that is correct: whether a
    variance is estimable does not depend on how much risk the author is willing
    to take. What must respond to delta is a bound that exists.
    """
    zero_var = {"f1": [5.0, 5.0, 5.0], "f2": [7.0, 7.0, 7.0]}
    refusals = {d: terminal_regret_bound(zero_var, "f2", delta=d,
                                         direction="maximize", paired=True)
                for d in (0.001, 0.05, 0.5)}
    assert {b.value for b in refusals.values()} == {None}, refusals
    assert {b.method for b in refusals.values()} == {"none"}, refusals

    # Off the boundary, the bound behaves like a bound: it moves with delta.
    # That contrast is the whole finding.
    #
    # The comparison data has to have genuinely VARYING paired differences, not
    # merely non-identical samples. `{"f1":[5,5,5.000001], "f2":[7,7,7.000001]}`
    # still gives value 0.0 at every delta, because the paired differences are
    # (2.0, 2.0, 2.0) — variance exactly 0 — so a constant OFFSET between two
    # noisy finalists reproduces the zero-information certificate even when
    # neither finalist's own samples are constant. That is a WIDER reachability
    # surface for the defect than three identical numbers: any two finalists
    # whose measurements differ by a fixed amount certify unconditionally under
    # common random numbers.
    varying = {"f1": [5.0, 5.4, 5.2], "f2": [7.0, 7.1, 7.6]}
    moved = {d: terminal_regret_bound(varying, "f2", delta=d, direction="maximize",
                                      paired=True).value
             for d in (0.001, 0.5)}
    assert moved[0.001] != moved[0.5], (
        "a bound with a real variance estimate must respond to its error budget"
    )
    assert moved[0.001] > 0.0 and moved[0.5] == 0.0

    # And the CONSTANT-OFFSET case, which is the wider reachability this file
    # documented and which the fix had to cover too: neither finalist's own
    # samples are constant, but the PAIRED DIFFERENCES are (2.0, 2.0, 2.0), so the
    # paired variance is exactly 0 and the old code certified from it. It now
    # refuses, for the same reason as the identical-replicate case -- the paired
    # path has no variance to estimate from -- which is why a count check on
    # replicates could never have caught it.
    const_offset = {"f1": [5.0, 5.4, 5.2], "f2": [7.0, 7.4, 7.2]}
    flat = {d: terminal_regret_bound(const_offset, "f2", delta=d,
                                     direction="maximize", paired=True).value
            for d in (0.001, 0.5)}
    assert set(flat.values()) == {None}, (
        f"a constant paired offset carries no variance and must not certify: {flat}"
    )


@pytest.mark.mutation_sentinel
def test_the_model_bound_declines_at_the_zero_degrees_of_freedom_boundary():
    """The SIBLING boundary, which is handled correctly — the contrast that
    proves the terminal one is an inconsistency rather than a deliberate choice.

    `model_regret_bound` checks `pure_error_df <= 0` and returns
    `None`/"none" with the reason spelled out. Same question, same module,
    opposite answer.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM02 — the statement of
    record lives there; this test is the executable check.
    """
    d = full_factorial(("A", "B"))          # corners only: no centre rows
    ys = [1.0, 4.0, 2.0, 8.0]
    fit = fit_effects(d, ys, factor_ids=("A", "B"))
    assert fit.pure_error_df == 0
    factors = parse_factors([_numeric("A"), _numeric("B")])
    kw = dict(direction="maximize", fitted_ids=("A", "B"), held_fixed={})
    b = model_regret_bound(fit, ranked(fit, factors, top=None, **kw),
                           recommend(fit, factors, **kw),
                           delta=0.05, direction="maximize")
    assert b.value is None and b.method == "none"
    assert "unknown is not zero" in b.detail


# ══ 3. delta boundaries ════════════════════════════════════════════════════
#
# EQUIVALENCE CLASSES for delta (the error budget):
#   delta <= 0     -> degenerate: t-quantile at 1-0 = +inf         [BOUNDARY 0]
#   0 < delta < 1  -> the legitimate class; monotone (bigger = tighter)
#   delta = 0.5    -> the median: t-critical is 0, bound == estimate [BOUNDARY]
#   delta >= 1     -> degenerate: quantile at <= 0                 [BOUNDARY 1]


@pytest.mark.parametrize("delta", [0.001, 0.01, 0.05, 0.2, 0.5])
def test_the_bound_is_monotone_across_the_legitimate_delta_class(delta):
    """Inside 0 < delta <= 0.5 the bound only tightens as delta grows."""
    samples = {"f1": [5.0, 5.4, 5.2, 5.1], "f2": [7.0, 7.3, 6.8, 7.1]}
    b = terminal_regret_bound(samples, "f2", delta=delta, direction="maximize",
                              paired=False)
    tighter = terminal_regret_bound(samples, "f2", delta=min(0.5, delta * 2),
                                    direction="maximize", paired=False)
    assert b.value is not None and tighter.value is not None
    assert tighter.value <= b.value + 1e-12
    assert b.delta == delta


def test_delta_at_one_half_makes_the_bound_the_point_estimate_itself():
    """delta = 0.5 is the exact boundary where the t-critical is 0.

    At the median the "bound" adds nothing to the point estimate. Since the
    estimate is <= 0 for every challenger (best is the argmax), the bound floors
    at 0.0 — a delta of 0.5 therefore certifies unconditionally, which is why a
    campaign must never be allowed to declare it as an error budget.
    """
    samples = {"f1": [5.0, 5.4, 5.2], "f2": [7.0, 7.3, 6.8]}
    b = terminal_regret_bound(samples, "f2", delta=0.5, direction="maximize",
                              paired=False)
    assert b.value == 0.0, (
        "at delta=0.5 the one-sided bound equals the (non-positive) point "
        "estimate, so it floors at exactly 0"
    )


def test_a_compiled_policys_deltas_stay_inside_the_open_unit_interval():
    """Both deltas are probabilities; `delta_s + delta_t` is the guarantee.

    Compile-time boundary check: 0 and 1 are both meaningless as error budgets,
    and they are the values a careless YAML most easily produces.
    """
    pol = compile_policy(_campaign())
    for key in ("delta_screen", "delta_terminal"):
        v = pol["objective"][key]
        assert 0.0 < v < 1.0, f"{key} = {v}"
    assert pol["objective"]["delta_screen"] + pol["objective"]["delta_terminal"] < 1.0


# ══ 4. epsilon (indifference width) boundaries ════════════════════════════
#
# EQUIVALENCE CLASSES:
#   {"abs": x}     -> exactly x, whatever the reference        [abs wins]
#   {"pct": p}     -> p% of |reference|
#   reference = 0  -> a pct width collapses to 0               [BOUNDARY]
#   reference < 0  -> taken against the MAGNITUDE, stays > 0   [BOUNDARY]


@pytest.mark.parametrize("spec,ref,want", [
    ({"abs": 0.0}, 100.0, 0.0),          # an exact-indifference boundary
    ({"abs": 2.5}, 100.0, 2.5),
    ({"abs": 2.5}, 0.0, 2.5),            # abs ignores the reference entirely
    ({"pct": 2.0}, 100.0, 2.0),
    ({"pct": 2.0}, -100.0, 2.0),         # negated objective: width stays positive
    ({"pct": 2.0}, 0.0, 0.0),            # BOUNDARY: no scale to be relative to
    ({"pct": 0.0}, 100.0, 0.0),
    ({}, 100.0, 2.0),                    # the documented 2% default
])
def test_epsilon_resolves_at_every_boundary_of_its_two_forms(spec, ref, want):
    """`abs` wins over `pct`; a pct is taken against |reference|.

    The negative-reference case is load-bearing: a latency campaign reports a
    NEGATED response so that "maximize" is well defined, and a width computed
    against the signed value would come out negative — an indifference band with
    negative width would make every comparison significant.
    """
    assert math.isclose(resolve_epsilon(spec, ref), want, rel_tol=1e-12,
                        abs_tol=1e-12)


def test_epsilon_is_never_negative_for_any_reference_sign():
    for ref in (-1e6, -1.0, -1e-9, 0.0, 1e-9, 1.0, 1e6):
        assert resolve_epsilon({"pct": 5.0}, ref) >= 0.0


# ══ 5. design-resolution boundaries ═══════════════════════════════════════
#
# EQUIVALENCE CLASSES for (k factors, resolution r):
#   r <= 2                -> refused: mains aliased with each other  [BOUNDARY 2/3]
#   (k, r) tabulated      -> a real generator set
#   (k, r) untabulated    -> refused with actionable options
#   k < r - 1             -> too few factors to support the claim


@pytest.mark.parametrize("res", [0, 1, 2])
def test_resolution_below_three_is_refused_at_the_boundary(res):
    """r=2 would alias main effects with each other and estimate nothing.

    Both sides: 2 raises, 3 is the smallest tabulated (k=7).
    """
    with pytest.raises(ValueError, match="resolution must be >= 3"):
        fractional_factorial(("A", "B", "C", "D", "E", "F", "G"), res)


def test_resolution_three_is_accepted_on_the_other_side_of_that_boundary():
    d = fractional_factorial(("A", "B", "C", "D", "E", "F", "G"), 3)
    assert len(d.points) == 8 and d.resolution == 3


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("k,res", [(2, 4), (3, 4), (3, 5), (4, 5), (2, 5), (9, 4)])
def test_too_few_factors_for_a_resolution_is_refused_not_silently_downgraded(k, res):
    """A resolution claim the factor count cannot support must ABORT.

    k=3 at resolution V is the interesting boundary: a 3-factor design has only
    three 2fi, so "resolution V" is vacuously satisfiable by the full factorial
    — but it is NOT tabulated, and inventing a fraction on the fly is what would
    silently produce a design whose real resolution is lower than the campaign
    pre-registered. `min_runs_for`'s untabulated fallback is a conservative
    UPPER bound (2**k), never the true minimum, so a feasibility decision must
    consult `is_tabulated` first.
    """
    ids = tuple(chr(ord("A") + i) for i in range(k))
    assert not is_tabulated(k, res), "re-pick a genuinely untabulated pair"
    with pytest.raises(ValueError, match="no tabulated resolution"):
        fractional_factorial(ids, res)
    assert min_runs_for(k, res) == 2 ** k, (
        "the untabulated fallback must be the conservative full-factorial bound"
    )


@pytest.mark.parametrize("k,res,n", [(4, 4, 8), (5, 4, 16), (5, 5, 16), (8, 4, 16),
                                     (7, 3, 8), (8, 5, 64)])
def test_every_tabulated_pair_builds_the_run_count_it_advertises(k, res, n):
    ids = tuple(chr(ord("A") + i) for i in range(k))
    d = fractional_factorial(ids, res)
    assert len(d.points) == n == min_runs_for(k, res)
    assert is_tabulated(k, res)


# ══ 6. degenerate designs: one factor, one level ══════════════════════════
#
# EQUIVALENCE CLASSES for a design's shape:
#   k = 1                 -> no interaction exists; the fit is a line
#   k = 0                 -> nothing to fit                     [BOUNDARY]
#   a factor with 1 level -> no contrast; the column is constant [BOUNDARY]


@pytest.mark.mutation_sentinel
def test_a_single_factor_design_fits_a_line_and_declares_no_interactions():
    """k=1 is the lower boundary of a meaningful design.

    `include_interactions=True` must be a no-op rather than an error: there is no
    pair to interact. A fit that unconditionally built pair columns would produce
    an empty column set and a singular solve.
    """
    d = with_center_points(full_factorial(("A",)), 3)
    ys = [1.0, 5.0, 3.0, 3.1, 2.9]
    fit = fit_effects(d, ys, factor_ids=("A",))
    assert [e.label for e in fit.effects] == ["A"]
    assert fit.quadratic == ()
    assert fit.pure_error_df == 2


@pytest.mark.mutation_sentinel
def test_a_zero_factor_design_is_refused_rather_than_fitting_an_intercept_alone():
    """k=0: `full_factorial(())` yields exactly one point, so a 'fit' would be
    the single response with no residual df and no estimable term.

    Asserts the CURRENT behaviour at the boundary (it fits an intercept and
    nothing else), which is benign only because no campaign can declare zero
    factors — the validator requires at least one. Recorded so that if that
    validation ever moves, the boundary's behaviour is already written down.
    """
    d = full_factorial(())
    assert len(d.points) == 1
    fit = fit_effects(d, [42.0], factor_ids=())
    assert fit.effects == () and fit.intercept == 42.0
    assert fit.pure_error_var is None


@pytest.mark.mutation_sentinel
def test_a_constant_response_yields_exactly_zero_effects_and_zero_variance():
    """The response-side degenerate boundary: every measurement identical.

    Every coefficient is exactly 0.0 and the pure error is 0.0 with real df, so
    NOTHING is significant — which is correct, and is the honest reading of "the
    knob did nothing". This is the `--liveness` "dead axis" case seen from the
    fit's side.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM07 — the statement of
    record lives there; this test is the executable check.
    """
    d = with_center_points(full_factorial(("A", "B")), 4)
    fit = fit_effects(d, [3.0] * len(d.points), factor_ids=("A", "B"))
    assert fit.intercept == 3.0
    assert all(e.estimate == 0.0 for e in fit.effects)
    assert fit.pure_error_var == 0.0 and fit.pure_error_df == 3
    # `have_se` requires `pure_error_var > 0`, so a zero variance yields NO
    # standard error and significance stays `None` — not `False`. That is the
    # right answer for the same reason "unknown is not a zero" applies
    # everywhere else: a zero SAMPLE variance from 4 identical centre points is
    # not evidence that the knob's effect is distinguishable from zero, it is
    # evidence that this instrument cannot tell. Note the contrast with
    # `terminal_regret_bound`, which faces the identical zero-variance input and
    # instead CERTIFIES (fixed; see the variance-boundary test above) — `fit_effects` is the module that
    # gets this boundary right.
    assert all(e.se is None for e in fit.effects)
    assert all(e.significant is None for e in fit.effects), (
        "reported a significance verdict from a zero variance estimate"
    )


# ══ 7. the fit floor: how few rows may be fitted ═════════════════════════
#
# EQUIVALENCE CLASSES for kept rows vs model terms p:
#   kept < p       -> singular: refuse                       [BOUNDARY kept=p]
#   kept == p      -> saturated: fits exactly, zero residual df
#   kept > p       -> the ordinary class
# Agent A's partial-design floor (`len(keep) < 2`) sits inside the first class.


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("kept", [1, 2, 3, 4, 5, 8])
def test_the_fit_refuses_exactly_when_the_kept_rows_cannot_estimate_the_terms(kept):
    """Both sides of the saturation boundary, for the 2-factor model (p=4).

    p = intercept + A + B + AB = 4. Below 4 kept rows the solve MUST raise
    (`design matrix is singular`) rather than return arbitrary numbers; at
    exactly 4 it fits with zero residual degrees of freedom, which is estimable
    but uncertifiable.

    This is the boundary partial-design fitting has to respect: refitting on a
    complete-row SUBSET is only legitimate while the subset can still estimate
    the model. A floor stated as `len(keep) < 2` is necessary but NOT sufficient
    for a 2-factor design — 3 kept rows clears that floor and is still singular.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT10 — the statement of
    record lives there; this test is the executable check.
    """
    d = full_factorial(("A", "B"))
    ys = [1.0, 4.0, 2.0, 9.0]
    pts, resp = [], []
    src = list(zip(d.points, ys))
    while len(pts) < kept:                      # repeat rows if kept > 4
        p_, y_ = src[len(pts) % 4]
        pts.append(p_)
        resp.append(y_)
    sub = design_mod.Design(points=tuple(pts), factor_ids=("A", "B"),
                            kind="full", resolution=None)
    if kept < 4:
        with pytest.raises(ValueError, match="singular"):
            fit_effects(sub, resp, factor_ids=("A", "B"))
    else:
        fit = fit_effects(sub, resp, factor_ids=("A", "B"))
        assert len(fit.effects) == 3
        # Saturated or replicated-saturated: no independent error estimate.
        assert fit.pure_error_df == 0
        assert all(e.se is None for e in fit.effects)


def test_a_response_vector_of_the_wrong_length_is_refused_on_both_sides():
    """One too few and one too many rows both abort.

    Every planned run needs exactly one response; a length mismatch means the
    caller silently lost or duplicated a measurement, and quietly zipping to the
    shorter of the two would fit a design that was never run.
    """
    d = full_factorial(("A", "B"))
    for n in (3, 5):
        with pytest.raises(ValueError, match="every planned run needs exactly one"):
            fit_effects(d, [1.0] * n, factor_ids=("A", "B"))
    fit_effects(d, [1.0, 2.0, 3.0, 4.0], factor_ids=("A", "B"))   # exactly right


# ══ 8. parallel width boundaries (Agent B's surface) ═════════════════════
#
# EQUIVALENCE CLASSES for declared max_parallel:
#   absent / non-int / bool -> treated as ABSENT (1, or the basis default)
#   <= 0                    -> absent                          [BOUNDARY 0/1]
#   1                       -> serial, explicitly               [BOUNDARY]
#   2 .. cpu_ceiling        -> the ordinary class
#   > cpu_ceiling           -> capped at the machine's CPUs      [BOUNDARY]


@pytest.mark.mutation_sentinel
@pytest.mark.pending_parallel
@pytest.mark.parametrize("declared,expect", [
    (None, 1), (0, 1), (-1, 1), (False, 1), (True, 1), ("4", 1),
    (1, 1), (2, 2), (3, 3),
])
def test_declared_width_treats_every_non_positive_or_non_integer_as_absent(
        declared, expect):
    """0 and -1 resolve to 1, not to 0 (which would run nothing) or to a crash.

    `True` is `isinstance(True, int)` in Python, so the bool exclusion is
    load-bearing: without it `max_parallel: true` in YAML would resolve to a
    width of 1 by accident rather than by rule, and `max_parallel: false` to 0.
    """
    opt = {} if declared is None else {"max_parallel": declared}
    assert concurrency.declared_width(opt) == expect


@pytest.mark.pending_parallel
def test_a_width_above_the_machines_cpu_count_is_capped_not_honoured():
    """The upper boundary: cpu_ceiling, and one step past it.

    Honouring a declared width above the machine's CPUs would oversubscribe and
    make the contention floor — measured at a width the machine can actually run
    — describe a configuration that never happened.
    """
    ceiling = concurrency.cpu_ceiling()
    assert ceiling >= 1
    for declared in (ceiling, ceiling + 1, ceiling * 4):
        v = concurrency.resolve({"max_parallel": declared,
                                 "concurrency": {"load_independent": True}},
                                stage_name="screen", confirm_stage="confirm")
        assert 1 <= v.width <= ceiling, (declared, v.width, ceiling)
        assert v.basis == concurrency.BASIS_LOAD_INDEPENDENT


@pytest.mark.pending_parallel
def test_a_stage_with_no_evidence_of_load_independence_stays_serial():
    """The DEFAULT side of the boundary: absent declaration -> width 1.

    A spending stage that has neither an author's load-independence claim nor a
    measured contention floor must run serially. Parallelising it without either
    would silently make machine load a hidden factor in every measurement.
    """
    v = concurrency.resolve({"max_parallel": 8}, stage_name="screen",
                            confirm_stage="confirm")
    assert v.width == 1 and v.basis == concurrency.BASIS_SERIAL


@pytest.mark.pending_parallel
def test_a_measured_floor_never_widens_beyond_the_width_it_was_certified_at():
    """"Never wider than the evidence" as a boundary: certified_width is a cap.

    Both sides: a declared width below the certified one is honoured as declared;
    above it, the certified width wins.
    """
    # `Verdict` refuses to be CONSTRUCTED inconsistently — a stronger guarantee
    # than capping at resolve() time, and the right place for it: a Verdict
    # claiming width 4 on evidence gathered at width 2 is unrepresentable, so no
    # downstream consumer has to remember to re-check.
    with pytest.raises(ValueError, match="exceeds the width"):
        concurrency.Verdict(width=4, basis=concurrency.BASIS_CONTENTION_FLOOR,
                            certified_width=2)

    measured = concurrency.Verdict(
        width=2, basis=concurrency.BASIS_CONTENTION_FLOOR, certified_width=2,
    )
    for declared, want in ((1, 1), (2, 2), (3, 2), (99, 2)):
        v = concurrency.resolve({"max_parallel": declared}, stage_name="screen",
                                confirm_stage="confirm", measured=measured)
        assert v.width == want, (declared, v.width)
        assert v.basis == concurrency.BASIS_CONTENTION_FLOOR
        assert v.width <= (measured.certified_width or 1), "wider than the evidence"


# ══ 9. shortlist_size and replicates boundaries in the compiled policy ════
#
# EQUIVALENCE CLASSES:
#   shortlist_size = 1     -> no discrimination possible        [BOUNDARY]
#   shortlist_size >= 2    -> discrimination; M = size - 1
#   replicates = 1         -> unpaired only, no variance        [BOUNDARY 1/2]
#   replicates >= 2        -> paired possible under CRN


@pytest.mark.parametrize("size", [1, 2, 3, 10])
def test_shortlist_size_is_carried_into_the_policy_unchanged_at_every_boundary(size):
    """Including 1, which legally reproduces the old single-point confirm."""
    pol = compile_policy(_campaign(design={
        "screen": {"resolution": 5, "center_points": 4},
        "confirm": {"shortlist_size": size, "replicates": 3}}))
    assert pol["states"]["confirm"]["design"]["shortlist_size"] == size
    assert check_policy(pol) == []


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("declared,expect", [(0, 1), (-3, 1), (1, 1), (2, 2), (5, 5)])
def test_replicates_are_floored_at_one_because_zero_replicates_measures_nothing(
        declared, expect):
    """`max(1, ...)`: a confirm round with 0 replicates would schedule no runs
    and then report on them. Both sides of the 0/1 boundary."""
    pol = compile_policy(_campaign(design={
        "screen": {"resolution": 5, "center_points": 4},
        "confirm": {"shortlist_size": 3, "replicates": declared}}))
    assert pol["states"]["confirm"]["design"]["replicates"] == expect


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("max_rounds,current_round,expect", [
    (1, 1, "report"),        # BOUNDARY: at the cap -> stop
    (3, 2, "confirm"),       # one below the cap -> another round
    (3, 3, "report"),        # BOUNDARY: at the cap -> stop
    (3, 4, "report"),        # past the cap (unreachable, but must not loop)
])
def test_the_confirm_round_cap_fires_at_the_boundary_not_one_past_it(
        max_rounds, current_round, expect):
    """`round >= max_rounds` -> report. Tested AT the cap, below it, and past it.

    A `>` instead of `>=` here spends one extra unregistered round of terminal
    discrimination — runs the pre-registration did not authorise. Both sides of
    the boundary are needed to distinguish the two operators: `round == cap`
    is the only observation they disagree on.

    Cross-reference: `docs/optimization-invariants.md` INV-TMP06 — the statement of
    record lives there; this test is the executable check.
    """
    pol = compile_policy(_campaign(policy={"confirm_max_rounds": max_rounds}))
    nxt, _ = step(pol, "confirm", {"certified": False, "round": current_round,
                                   "budget_remaining": 100,
                                   "confirm_affordable": True})
    assert nxt == expect


@pytest.mark.mutation_sentinel
@pytest.mark.parametrize("budget,expect", [(0, "report"), (1, "confirm")])
def test_the_exhausted_budget_guard_fires_at_exactly_zero_runs_remaining(
        budget, expect):
    """`budget_remaining < 1` -> report. Both sides of 0/1.

    One run remaining is not nothing, so it does not fire; zero is.
    """
    pol = compile_policy(_campaign(policy={"confirm_max_rounds": 5}))
    nxt, _ = step(pol, "confirm", {"certified": False, "round": 1,
                                   "budget_remaining": budget,
                                   "confirm_affordable": True})
    assert nxt == expect


# ══ 10. center_points and noise boundaries ═══════════════════════════════


@pytest.mark.parametrize("n", [0, 1, 2, 4])
def test_center_points_at_every_boundary_of_certifiability(n):
    """0 and 1 centre points leave the fit uncertifiable; 2 is the minimum.

    The design is still BUILT at every count — refusing to run a screen because
    it cannot certify would be worse than running it and reporting `None` — but
    `significant` must stay `None` below the boundary rather than defaulting to
    False (which would read as "measured, and not significant").
    """
    d = with_center_points(full_factorial(("A", "B")), n)
    assert len(d.points) == 4 + n
    ys = [1.0, 4.0, 2.0, 9.0] + [3.0 + 0.1 * i for i in range(n)]
    fit = fit_effects(d, ys, factor_ids=("A", "B"))
    if n < 2:
        assert fit.pure_error_var is None and fit.pure_error_df == 0
        assert all(e.significant is None for e in fit.effects), (
            "reported a significance verdict with no error estimate"
        )
    else:
        assert fit.pure_error_var is not None and fit.pure_error_df == n - 1
        assert all(e.significant is not None for e in fit.effects)


@pytest.mark.mutation_sentinel
@pytest.mark.pending_parallel
def test_max_parallel_true_is_not_a_width_of_one_by_accident():
    """CLOSES A MUTATION SURVIVOR (M24) that the table above could not catch.

    `isinstance(True, int)` is True in Python, so `declared_width` excludes bools
    explicitly. But `max_parallel: true` and `max_parallel: 1` BOTH resolve to a
    width of 1 whether or not that exclusion is present — the exclusion routes
    `True` down the "absent" path, and with no concurrency block the absent path
    also returns 1. The two are indistinguishable there, so removing the bool
    check survived the boundary table.

    They separate as soon as a `concurrency` block is declared: an ABSENT
    `max_parallel` then resolves to `default_width()` (> 1 on any multi-core
    machine), while a declared integer is honoured as declared. So `true` must
    behave like ABSENT (default_width), not like the integer 1.

    Why it matters beyond pedantry: `max_parallel: true` is a plausible YAML typo
    for "yes, parallelise", and `max_parallel: false` is the matching one. Under
    the mutation, `false` resolves to 0 — `isinstance(False, int)` with
    `raw > 0` False, so it falls through to the block default — while `true`
    silently pins the campaign to serial execution and reports no problem. The
    schema declares `type: integer, minimum: 1`, so a schema-validated campaign
    cannot reach this; a hand-edited or programmatically-built one can, and
    `declared_width`'s own docstring commits to treating an unschema-able value
    as absent rather than raising.
    """
    block = {"concurrency": {"load_independent": True}}
    absent = concurrency.declared_width(dict(block))
    as_true = concurrency.declared_width({**block, "max_parallel": True})
    as_one = concurrency.declared_width({**block, "max_parallel": 1})

    assert absent == concurrency.default_width()
    assert as_one == 1, "an explicitly declared 1 must stay 1"
    assert as_true == absent, (
        f"max_parallel: true resolved to {as_true}, not to the absent-value "
        f"default {absent} — the bool exclusion is not in force, so `true` is "
        f"being read as the integer 1"
    )
    if concurrency.default_width() > 1:
        assert as_true != as_one, (
            "true and 1 are indistinguishable even with a concurrency block; "
            "re-derive this test's discriminator"
        )
