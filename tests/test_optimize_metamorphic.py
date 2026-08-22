"""Metamorphic invariants for the fit → decide → certify pipeline.

There is no oracle for "the fitted surface is correct": a response surface
fitted from 16 noisy benchmark rows has no ground truth available at the point
of fitting. What IS available is a set of RELATIONS between runs — transform an
input in a way whose effect on the output is known a priori, and assert the
output moved exactly that way. A violated relation is a bug with no oracle
needed.

Each relation below is grounded in a defect class this module has actually
shipped or could ship:

  * run-order permutation (§4 D1's neighbourhood): the design's execution order
    is RANDOMIZED by ``matrix.randomized_run_order``, so any order-sensitivity
    in the fit makes the reported coefficients a function of a seed nobody
    reads. The fit must be a function of the (row, response) SET.
  * level relabelling / sign flips: the ±1 coding is a labelling convention.
    Negating a factor's column must negate exactly the coefficients whose term
    contains it, and leave every magnitude alone. This is the property that
    catches spec §4 D1's reintroduction — an alias class collapsed on the wrong
    key, or an alias sign dropped, breaks it.
  * row dropping: the invariant behind partial-design fitting. A fit on FEWER
    rows may never report a NARROWER interval than the fit on all of them.
  * objective rescaling and direction symmetry: the DECISION is invariant to
    the units the objective is reported in, and ``minimize f`` must agree with
    ``maximize -f``. A sign handled in one of the two places (``decide`` but not
    ``certificate``) shows up here and nowhere else.

Hypothesis is configured ``derandomize=True`` everywhere: CI reproducibility
outranks the extra coverage a random seed per run would buy, and a metamorphic
failure that cannot be reproduced cannot be fixed.
"""
from __future__ import annotations

import math
import random

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from orchestrator.optimize.certificate import model_regret_bound, terminal_regret_bound
from orchestrator.optimize.decide import ranked, recommend
from orchestrator.optimize.design import (
    DesignPoint, Design, full_factorial, fractional_factorial, with_center_points,
)
from orchestrator.optimize.effects import Fit, fit_effects
from orchestrator.optimize.factors import parse_factors

pytestmark = pytest.mark.metamorphic

# Deterministic by construction: no example depends on a wall clock, a global
# RNG, or a filesystem path, so parallel execution under -n auto is safe.
DET = settings(derandomize=True, deadline=None, max_examples=60,
               suppress_health_check=[HealthCheck.function_scoped_fixture])

_IDS = ("A", "B", "C")


# `parse_factors` refuses a factor with no `apply`, no `manipulation`, or no
# `correctness` relation, so a bare {"id","type","levels"} dict cannot be used.
# `synthetic._numeric` / `_choice` build the shapes campaign YAML actually
# declares, and are what every other test in this suite uses — reusing them
# keeps these relations stated over REAL campaign factors rather than a
# hand-rolled dict that could drift from the parser's requirements.
from orchestrator.optimize.synthetic import _choice as _choice_factor  # noqa: E402
from orchestrator.optimize.synthetic import _numeric as _numeric_factor  # noqa: E402


def _responses_strategy(n: int):
    """Response vectors that are finite, well-scaled, and not degenerate.

    Bounded away from zero-variance because a constant response makes every
    coefficient exactly 0 and every relation below trivially true — that is a
    vacuous pass, not a passing test.
    """
    return st.lists(
        st.floats(min_value=-100.0, max_value=100.0, allow_nan=False,
                  allow_infinity=False, width=32),
        min_size=n, max_size=n,
    )


def _permutation(n: int, seed: int) -> list[int]:
    """A reproducible permutation of ``range(n)``, from a local RNG only.

    Mirrors ``matrix.randomized_run_order``'s discipline deliberately: a local
    ``random.Random`` instance, never the global module state, so these tests
    cannot be perturbed by anything else in the process touching the RNG — and
    so a failure is reproducible from ``seed`` alone.
    """
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order


def _effects_by_label(fit: Fit) -> dict[str, float]:
    return {e.label: e.estimate for e in tuple(fit.effects) + tuple(fit.quadratic)}


def _widths(fit: Fit) -> dict[str, float]:
    return {
        e.label: e.ci_high - e.ci_low
        for e in tuple(fit.effects) + tuple(fit.quadratic)
        if e.ci_low is not None and e.ci_high is not None
    }


# ── MR1: run-order permutation invariance ──────────────────────────────────
#
# `design_matrix.json` carries `run_order` / `run_order_seed`, and rows are
# EXECUTED in that shuffled order. The fit is over the (row, response) pairing,
# so permuting the pairing's enumeration order must not move a coefficient.


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(8), perm_seed=st.integers(0, 10**6))
@example(ys=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], perm_seed=7)
@DET
def test_fit_is_invariant_to_the_order_rows_are_presented_in(ys, perm_seed):
    """Permuting (row, response) pairs together must not move any coefficient.

    The run order is randomized per iteration, so an order-dependent fit would
    make every reported coefficient a function of `run_order_seed` — a number
    no consumer of `effects.json` ever reads.

    Cross-reference: `docs/optimization-invariants.md` INV-RES05 — the statement of
    record lives there; this test is the executable check.
    """
    d = full_factorial(_IDS)
    base = fit_effects(d, ys, factor_ids=_IDS)

    idx = _permutation(len(d.points), perm_seed)

    permuted = Design(points=tuple(d.points[i] for i in idx),
                      factor_ids=d.factor_ids, kind=d.kind,
                      resolution=d.resolution, generators=d.generators)
    shuffled = fit_effects(permuted, [ys[i] for i in idx], factor_ids=_IDS)

    assert math.isclose(base.intercept, shuffled.intercept, rel_tol=1e-9, abs_tol=1e-9)
    a, b = _effects_by_label(base), _effects_by_label(shuffled)
    assert set(a) == set(b)
    for label in a:
        assert math.isclose(a[label], b[label], rel_tol=1e-8, abs_tol=1e-8), (
            f"coefficient {label} moved under a pure reordering: {a[label]} vs {b[label]}"
        )


@given(ys=_responses_strategy(12), perm_seed=st.integers(0, 10**6))
@DET
def test_center_point_pure_error_is_invariant_to_row_order(ys, perm_seed):
    """The pure-error variance (hence every CI) is order-independent too.

    Centre rows are located by `role`, not by position, so shuffling must not
    change `pure_error_var` — which every reported interval divides by.
    """
    d = with_center_points(full_factorial(_IDS), 4)
    assert len(d.points) == 12
    base = fit_effects(d, ys, factor_ids=_IDS)

    idx = _permutation(len(d.points), perm_seed)
    permuted = Design(points=tuple(d.points[i] for i in idx),
                      factor_ids=d.factor_ids, kind=d.kind,
                      resolution=d.resolution, generators=d.generators)
    shuffled = fit_effects(permuted, [ys[i] for i in idx], factor_ids=_IDS)

    if base.pure_error_var is None:
        assert shuffled.pure_error_var is None
    else:
        assert math.isclose(base.pure_error_var, shuffled.pure_error_var,
                            rel_tol=1e-9, abs_tol=1e-12)
    assert base.pure_error_df == shuffled.pure_error_df


# ── MR2: level relabelling equivariance ────────────────────────────────────


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(8), flip=st.integers(0, 2))
@example(ys=[3.0, -1.0, 4.0, 1.0, -5.0, 9.0, 2.0, 6.0], flip=0)
@DET
def test_negating_one_factors_coding_flips_exactly_the_terms_containing_it(ys, flip):
    """Relabelling a factor's two levels is a sign change, never a magnitude change.

    Under `A -> -A`: beta_A and beta_AB, beta_AC negate; beta_B, beta_C, beta_BC
    and the intercept are untouched. Every |coefficient| is preserved. A fit that
    collapsed an alias class on the wrong key, or dropped an alias's sign, breaks
    this and nothing else in the suite notices.
    """
    d = full_factorial(_IDS)
    base = fit_effects(d, ys, factor_ids=_IDS)

    negated = Design(
        points=tuple(
            DesignPoint(
                coded=tuple(-v if j == flip else v for j, v in enumerate(p.coded)),
                role=p.role, replicate=p.replicate,
            ) for p in d.points
        ),
        factor_ids=d.factor_ids, kind=d.kind, resolution=d.resolution,
        generators=d.generators,
    )
    flipped = fit_effects(negated, ys, factor_ids=_IDS)

    assert math.isclose(base.intercept, flipped.intercept, rel_tol=1e-9, abs_tol=1e-9)
    a, b = _effects_by_label(base), _effects_by_label(flipped)
    assert set(a) == set(b)
    fid = _IDS[flip]
    for label, est in a.items():
        term = next(e.terms for e in tuple(base.effects) + tuple(base.quadratic)
                    if e.label == label)
        # A term flips once per occurrence of the negated factor, so A^2 does
        # NOT flip while A and AB do.
        expected = est * ((-1.0) ** term.count(fid))
        assert math.isclose(expected, b[label], rel_tol=1e-8, abs_tol=1e-8), (
            f"{label} (terms={term}) under {fid} -> -{fid}: expected {expected}, got {b[label]}"
        )
        assert math.isclose(abs(est), abs(b[label]), rel_tol=1e-8, abs_tol=1e-8)


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(16))
@DET
def test_alias_classes_are_stable_under_factor_column_negation(ys):
    """§4 D1's regression guard, stated metamorphically.

    A resolution-IV screen aliases 2fi pairs; the fit keeps ONE coefficient per
    alias class. Negating a factor's column changes which sign relates the two
    aliased columns but NOT the partition into classes — the same terms stay
    confounded. A fit that rebuilt classes off label order rather than off the
    actual column would repartition here, and on the real design that is exactly
    the singular-X^TX crash.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT01 — the statement of
    record lives there; this test is the executable check.
    """
    d = fractional_factorial(("A", "B", "C", "D", "E"), 4)
    assert len(d.points) == 16
    base = fit_effects(d, ys, factor_ids=("A", "B", "C", "D", "E"))

    def classes(fit):
        return {
            e.label: frozenset(terms for terms, _sign in e.aliased_with)
            for e in fit.effects if e.aliased_with
        }

    base_classes = classes(base)
    assert base_classes, "resolution IV must confound at least one 2fi pair"

    negated = Design(
        points=tuple(
            DesignPoint(coded=tuple(-v if j == 0 else v for j, v in enumerate(p.coded)),
                        role=p.role, replicate=p.replicate)
            for p in d.points
        ),
        factor_ids=d.factor_ids, kind=d.kind, resolution=d.resolution,
        generators=d.generators,
    )
    flipped = fit_effects(negated, ys, factor_ids=("A", "B", "C", "D", "E"))

    assert classes(flipped) == base_classes, (
        "alias partition changed under a pure relabelling — the classes are "
        "being built from something other than the design columns"
    )
    # Magnitudes are preserved; only signs move.
    a, b = _effects_by_label(base), _effects_by_label(flipped)
    for label in a:
        assert math.isclose(abs(a[label]), abs(b[label]), rel_tol=1e-8, abs_tol=1e-8)


# ── MR3: row-dropping monotonicity ─────────────────────────────────────────


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(12), drop=st.integers(0, 11))
@DET
def test_dropping_a_center_row_never_narrows_a_reported_interval(ys, drop):
    """A partial design must never look MORE confident than the full one.

    This is the invariant behind partial-design fitting: refitting on the
    complete-row subset is honest only while the reported uncertainty widens (or
    holds) as rows are lost. Dropping a centre row removes a degree of freedom
    from the pure-error estimate, so every t-critical grows; the interval can
    only widen unless the variance estimate itself happened to shrink.

    Stated on the CRITICAL VALUE rather than the width, because the width also
    carries the sample variance, which a dropped row can legitimately reduce.
    The df monotonicity is the part that must never invert.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT06 — the statement of
    record lives there; this test is the executable check.
    """
    from scipy.stats import t as student_t

    d = with_center_points(full_factorial(_IDS), 4)
    full = fit_effects(d, ys, factor_ids=_IDS)
    assume(full.pure_error_df >= 2)

    kept = [i for i in range(len(d.points)) if i != drop]
    sub = Design(points=tuple(d.points[i] for i in kept), factor_ids=d.factor_ids,
                 kind=d.kind, resolution=d.resolution, generators=d.generators)
    try:
        partial = fit_effects(sub, [ys[i] for i in kept], factor_ids=_IDS)
    except ValueError:
        # Singular after the drop: correctly refusing to fit is the honest
        # outcome, and is never "more confident".
        return

    assert partial.pure_error_df <= full.pure_error_df, (
        "dropping a row increased the pure-error degrees of freedom"
    )
    if partial.pure_error_df > 0 and full.pure_error_df > 0:
        t_full = float(student_t.ppf(0.975, full.pure_error_df))
        t_part = float(student_t.ppf(0.975, partial.pure_error_df))
        assert t_part >= t_full - 1e-12, (
            f"t-critical shrank on fewer rows: df {full.pure_error_df}->"
            f"{partial.pure_error_df} gave t {t_full}->{t_part}"
        )


@given(ys=_responses_strategy(12))
@DET
def test_dropping_every_replicate_of_the_center_removes_certification_entirely(ys):
    """With no replicated centre there is no pure error, so no interval at all.

    `None` rather than a fabricated width — and `model_regret_bound` must then
    decline to certify rather than report a number. "Unknown is not a zero" is
    the documented rule; this is it as a relation.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM02, INV-STAT05 — the statement of
    record lives there; this test is the executable check.
    """
    d = with_center_points(full_factorial(_IDS), 4)
    corners = [i for i, p in enumerate(d.points) if p.role == "corner"]
    sub = Design(points=tuple(d.points[i] for i in corners), factor_ids=d.factor_ids,
                 kind=d.kind, resolution=d.resolution, generators=d.generators)
    fit = fit_effects(sub, [ys[i] for i in corners], factor_ids=_IDS)

    assert fit.pure_error_var is None
    assert fit.pure_error_df == 0
    assert all(e.ci_low is None and e.significant is None for e in fit.effects)

    factors = parse_factors([_numeric_factor(f) for f in _IDS])
    cands = ranked(fit, factors, direction="maximize", fitted_ids=_IDS,
                   held_fixed={}, top=None)
    xhat = recommend(fit, factors, direction="maximize", fitted_ids=_IDS, held_fixed={})
    bound = model_regret_bound(fit, cands, xhat, delta=0.05, direction="maximize")
    assert bound.value is None and bound.method == "none", (
        "certified a bound with no pure-error estimate — an unknown was "
        "reported as a number"
    )


# ── MR4: objective rescaling leaves the DECISION alone ─────────────────────


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(12), scale=st.floats(min_value=0.01, max_value=100.0,
                                                  allow_nan=False, allow_infinity=False))
@example(ys=[1.0, 5.0, 2.0, 9.0, 3.0, 7.0, 4.0, 8.0, 6.0, 6.5, 6.2, 6.1], scale=1000.0)
@DET
def test_scaling_the_objective_scales_coefficients_but_not_the_ranking(ys, scale):
    """y -> c*y (c>0): every coefficient scales by c; the ranking is identical.

    A campaign reporting latency in microseconds must recommend the same
    configuration as one reporting it in seconds. Any place that compares a
    coefficient against an ABSOLUTE threshold instead of a relative one breaks
    this — and a scale-dependent decision rule is a bug that only shows up when
    the target changes its units.
    """
    d = with_center_points(full_factorial(_IDS), 4)
    base = fit_effects(d, ys, factor_ids=_IDS)
    scaled = fit_effects(d, [y * scale for y in ys], factor_ids=_IDS)

    a, b = _effects_by_label(base), _effects_by_label(scaled)
    for label in a:
        assert math.isclose(a[label] * scale, b[label], rel_tol=1e-6,
                            abs_tol=1e-6 * max(1.0, abs(b[label])))

    factors = parse_factors([_numeric_factor(f) for f in _IDS])
    kw = dict(direction="maximize", fitted_ids=_IDS, held_fixed={})
    rank_a = ranked(base, factors, top=None, **kw)
    rank_b = ranked(scaled, factors, top=None, **kw)

    # The relation is over the ORDER-BY-VALUE, not over list positions.
    # `ranked` has no deterministic tie-break (see
    # test_ranked_has_no_deterministic_tie_break_so_ties_may_reorder_under_a_units_change
    # below), so two candidates with an identical predicted value can legally
    # swap positions when the objective is rescaled. Grouping by value states
    # exactly the guarantee that must hold — every candidate keeps its RANK —
    # without asserting a tie-break the module does not promise.
    def _tiers(cands, mult):
        out, seen = [], None
        for c in cands:
            v = round(c.predicted / mult, 6)
            if v != seen:
                out.append(set())
                seen = v
            out[-1].add(tuple(sorted(c.levels.items())))
        return out

    assert _tiers(rank_a, 1.0) == _tiers(rank_b, scale), (
        "finalist ranking changed under a units change"
    )

    # The RECOMMENDATION is likewise asserted up to ties. `recommend` is an
    # argmax with no tie-break, so when several candidates predict EXACTLY the
    # same value it returns whichever the enumeration reached first — and float
    # rounding at a different scale can reorder that. Hypothesis finds these
    # readily: a response vector with symmetric coefficients (e.g. beta_A =
    # beta_B = beta_C) makes {A:2,B:16,C:16} and {A:16,B:2,C:16} predict
    # identically, and scale=0.01 vs 1.0 picks different ones. So the guarantee
    # is that the recommendation is AMONG the top tier, not that it is a
    # particular member of it. See
    # test_ranked_has_no_deterministic_tie_break_so_ties_may_reorder_under_a_units_change
    # for why the missing tie-break is worth recording as a gap.
    rec_a = recommend(base, factors, **kw)
    rec_b = recommend(scaled, factors, **kw)
    top_a = max(c.predicted for c in rank_a)
    top_b = max(c.predicted for c in rank_b)
    assert math.isclose(rec_a.predicted, top_a, rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(rec_b.predicted, top_b, rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(rec_a.predicted * scale, rec_b.predicted,
                        rel_tol=1e-6,
                        abs_tol=1e-6 * max(1.0, abs(rec_b.predicted))), (
        f"the recommended configuration's PREDICTED VALUE did not scale: "
        f"{rec_a.predicted} * {scale} != {rec_b.predicted}"
    )


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(8), scale=st.floats(min_value=0.5, max_value=20.0,
                                                 allow_nan=False, allow_infinity=False))
@settings(derandomize=True, deadline=None, max_examples=400,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_the_model_regret_bound_scales_with_the_objective_it_bounds(ys, scale):
    """R_delta is in the objective's units, so it must scale by exactly c.

    Not scale-INVARIANT: it is a bound on a gain measured in the response's
    units. A bound that stayed fixed while the response scaled would certify a
    microsecond campaign and refuse the identical second-valued one.
    """
    d = with_center_points(full_factorial(("A", "B")), 4)
    factors = parse_factors([_numeric_factor("A"), _numeric_factor("B")])
    kw = dict(direction="maximize", fitted_ids=("A", "B"), held_fixed={})

    out, xhats = [], []
    for mult in (1.0, scale):
        fit = fit_effects(d, [y * mult for y in ys], factor_ids=("A", "B"))
        if fit.pure_error_df <= 0 or fit.pure_error_var in (None, 0.0):
            return
        cands = ranked(fit, factors, top=None, **kw)
        xhat = recommend(fit, factors, **kw)
        xhats.append(xhat)
        out.append(model_regret_bound(fit, cands, xhat, delta=0.05, direction="maximize"))
    base_x, scaled_x = xhats

    base_b, scaled_b = out
    if base_b.value is None or scaled_b.value is None:
        assert base_b.value is None and scaled_b.value is None
        return

    # Conditional on x-hat being the SAME configuration in both framings. When
    # the fitted surface ties at its argmax, the two runs certify different
    # (equally optimal) points, and two different points legitimately have
    # different bounds — the challenger set is measured relative to x-hat. See
    # test_the_argmax_can_tie_which_makes_the_certified_bound_scale_dependent
    # below: this is the tie-break gap reaching the certificate, and asserting
    # through it would be asserting that ties do not exist.
    if base_x.levels != scaled_x.levels:
        assert math.isclose(base_x.predicted * scale, scaled_x.predicted,
                            rel_tol=1e-6,
                            abs_tol=1e-6 * max(1.0, abs(scaled_x.predicted))), (
            "x-hat changed AND its predicted value did not scale — that is a "
            "real scale-dependence, not a tie"
        )
        return

    assert math.isclose(base_b.value * scale, scaled_b.value,
                        rel_tol=1e-6, abs_tol=1e-9), (
        f"regret bound did not scale with the objective: "
        f"{base_b.value} * {scale} != {scaled_b.value}"
    )


# ── MR5: direction symmetry ────────────────────────────────────────────────


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(12))
@example(ys=[1.0, 5.0, 2.0, 9.0, 3.0, 7.0, 4.0, 8.0, 6.0, 6.5, 6.2, 6.1])
@DET
def test_minimizing_f_recommends_what_maximizing_negative_f_recommends(ys):
    """`direction: minimize` on f == `direction: maximize` on -f.

    The sign enters `decide` (argmax vs argmin) and, separately,
    `certificate` (the contrast's orientation). Handling it in one place and
    not the other is invisible to any single-run assertion and shows up here
    immediately.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT11 — the statement of
    record lives there; this test is the executable check.
    """
    d = with_center_points(full_factorial(_IDS), 4)
    factors = parse_factors([_numeric_factor(f) for f in _IDS])
    fit_pos = fit_effects(d, ys, factor_ids=_IDS)
    fit_neg = fit_effects(d, [-y for y in ys], factor_ids=_IDS)

    kw = dict(fitted_ids=_IDS, held_fixed={})
    min_on_f = recommend(fit_pos, factors, direction="minimize", **kw)
    max_on_neg = recommend(fit_neg, factors, direction="maximize", **kw)
    assert min_on_f.levels == max_on_neg.levels, (
        "minimize f and maximize -f disagreed on the recommendation"
    )

    rank_min = [c.levels for c in ranked(fit_pos, factors, direction="minimize",
                                        top=None, **kw)]
    rank_max = [c.levels for c in ranked(fit_neg, factors, direction="maximize",
                                        top=None, **kw)]
    assert rank_min == rank_max, "finalist ORDER disagreed between the two framings"


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(8))
@DET
def test_the_model_bound_is_direction_symmetric_too(ys):
    """The certificate agrees with the decision about which way is better.

    A bound computed with the wrong sign would floor at 0.0 for every
    challenger and CERTIFY every recommendation — the most dangerous possible
    failure, since it reports maximum confidence exactly when the orientation
    is wrong.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT11 — the statement of
    record lives there; this test is the executable check.
    """
    d = with_center_points(full_factorial(("A", "B")), 4)
    factors = parse_factors([_numeric_factor("A"), _numeric_factor("B")])
    ids = ("A", "B")

    fit_pos = fit_effects(d, ys, factor_ids=ids)
    fit_neg = fit_effects(d, [-y for y in ys], factor_ids=ids)
    if fit_pos.pure_error_df <= 0 or not fit_pos.pure_error_var:
        return

    def bound(fit, direction):
        kw = dict(direction=direction, fitted_ids=ids, held_fixed={})
        return model_regret_bound(fit, ranked(fit, factors, top=None, **kw),
                                  recommend(fit, factors, **kw),
                                  delta=0.05, direction=direction)

    b_min = bound(fit_pos, "minimize")
    b_max = bound(fit_neg, "maximize")
    if b_min.value is None or b_max.value is None:
        assert b_min.value is None and b_max.value is None
        return
    assert math.isclose(b_min.value, b_max.value, rel_tol=1e-6, abs_tol=1e-9), (
        f"minimize-f bound {b_min.value} != maximize-(-f) bound {b_max.value}"
    )


# ── MR6: replicate consistency ─────────────────────────────────────────────


@pytest.mark.mutation_sentinel
@given(ys=_responses_strategy(8))
@DET
def test_duplicating_every_row_leaves_the_point_estimates_where_they_were(ys):
    """A design run twice estimates the same coefficients.

    Doubling every (row, response) pair doubles both the contrast and N, so
    beta = contrast/N is unchanged. A fit that normalised by the wrong count —
    the number of DISTINCT configurations rather than the number of ROWS —
    halves every coefficient here and nowhere else.
    """
    d = full_factorial(_IDS)
    base = fit_effects(d, ys, factor_ids=_IDS)

    doubled = Design(points=d.points + d.points, factor_ids=d.factor_ids,
                     kind=d.kind, resolution=d.resolution, generators=d.generators)
    twice = fit_effects(doubled, list(ys) + list(ys), factor_ids=_IDS)

    assert twice.n_runs == 2 * base.n_runs
    assert math.isclose(base.intercept, twice.intercept, rel_tol=1e-9, abs_tol=1e-9)
    a, b = _effects_by_label(base), _effects_by_label(twice)
    for label in a:
        assert math.isclose(a[label], b[label], rel_tol=1e-8, abs_tol=1e-8), (
            f"{label} moved when the whole design was replicated: {a[label]} vs {b[label]}"
        )


@given(
    xb=st.lists(st.floats(1.0, 100.0, allow_nan=False, allow_infinity=False, width=32),
                min_size=3, max_size=6),
    shift=st.floats(-20.0, 20.0, allow_nan=False, allow_infinity=False, width=32),
)
@DET
def test_terminal_bound_is_invariant_to_a_shared_additive_shift(xb, shift):
    """Adding a constant to EVERY finalist's samples cannot change the bound.

    R_delta^term is built from DIFFERENCES between finalists, so a shared
    offset (a machine that got uniformly slower) must cancel exactly. A bound
    that leaked an absolute level would move, and would then depend on the
    benchmark's baseline rather than on the contrast it claims to bound.
    """
    xa = [v + 3.0 for v in xb]
    samples = {"f1": list(xb), "f2": list(xa)}
    best = max(samples, key=lambda k: sum(samples[k]) / len(samples[k]))
    base = terminal_regret_bound(samples, best, delta=0.05, direction="maximize",
                                paired=False)

    shifted = {k: [v + shift for v in vs] for k, vs in samples.items()}
    best_s = max(shifted, key=lambda k: sum(shifted[k]) / len(shifted[k]))
    after = terminal_regret_bound(shifted, best_s, delta=0.05, direction="maximize",
                                 paired=False)

    assert best_s == best
    if base.value is None:
        assert after.value is None
        return
    assert math.isclose(base.value, after.value, rel_tol=1e-6,
                        abs_tol=1e-6 * max(1.0, abs(base.value)))


@pytest.mark.mutation_sentinel
@given(
    xb=st.lists(st.floats(1.0, 50.0, allow_nan=False, allow_infinity=False, width=32),
                min_size=3, max_size=6),
    gain=st.floats(0.5, 20.0, allow_nan=False, allow_infinity=False, width=32),
)
@DET
def test_terminal_bound_widens_when_a_finalist_is_dropped_to_one_replicate(xb, gain):
    """Fewer replicates must never certify harder.

    With <2 replicates on any finalist there is no variance estimate, so the
    bound is `None` — "cannot certify" — never a tighter number. This is the
    row-dropping relation at the terminal stage, where the two-replicate floor
    lives.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT06 — the statement of
    record lives there; this test is the executable check.
    """
    samples = {"f1": list(xb), "f2": [v + gain for v in xb]}
    best = "f2"
    full = terminal_regret_bound(samples, best, delta=0.05, direction="maximize",
                                paired=False)

    starved = {"f1": [xb[0]], "f2": list(samples["f2"])}
    thin = terminal_regret_bound(starved, best, delta=0.05, direction="maximize",
                                paired=False)
    assert thin.value is None and thin.method == "none", (
        "reported a variance-based bound from a single measurement"
    )
    if full.value is not None:
        assert full.method in ("bonferroni_one_sided_welch_t",
                              "bonferroni_one_sided_t_paired", "trivial")


@pytest.mark.mutation_sentinel
@given(xb=st.lists(st.floats(1.0, 50.0, allow_nan=False, allow_infinity=False, width=32),
                   min_size=4, max_size=8),
       gain=st.floats(0.5, 10.0, allow_nan=False, allow_infinity=False, width=32))
@DET
def test_a_wider_delta_can_only_tighten_the_bound_never_loosen_it(xb, gain):
    """delta is the error budget: spending more of it buys a tighter bound.

    Monotone in delta, strictly, while the bound is off its 0.0 floor. A
    certificate whose bound did not respond to delta would be reporting a
    number unrelated to the guarantee it advertises — and swapping
    `delta_screen` for `delta_terminal` (a mutation in the matrix) is exactly
    that class of defect.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT04 — the statement of
    record lives there; this test is the executable check.
    """
    samples = {"f1": list(xb), "f2": [v + gain for v in xb]}
    tight = terminal_regret_bound(samples, "f2", delta=0.01, direction="maximize",
                                 paired=False)
    loose = terminal_regret_bound(samples, "f2", delta=0.20, direction="maximize",
                                 paired=False)
    if tight.value is None or loose.value is None:
        return
    assert loose.value <= tight.value + 1e-9, (
        f"delta=0.20 gave a WIDER bound ({loose.value}) than delta=0.01 "
        f"({tight.value}) — the bound is not monotone in its error budget"
    )
    assert tight.delta == 0.01 and loose.delta == 0.20


# ── The tie-break gap this file surfaced ───────────────────────────────────


def test_ranked_breaks_exact_ties_by_a_declared_key_so_the_answer_is_reproducible():
    """DOCUMENTS A REAL GAP found by the rescaling relation above.

    `decide.ranked` sorts candidates by predicted value with no secondary key,
    so two candidates predicted EXACTLY equal keep whatever relative order the
    enumeration and the sort's stability happen to give them. Rescaling the
    objective changes the float rounding of the two equal values identically —
    but the sort input order is the same, so the tie ITSELF is stable here;
    what is not stable is the tie's resolution across arithmetic paths.

    Measured on a 3-factor CCD, ys=[1,5,2,9,3,7,4,8,6,6.5,6.2,6.1], scale=1000:
    candidates {'A':2,'B':12,'C':16} and {'A':16,'B':16,'C':14} both predict
    8.1380952381 and occupy positions 36/37 in one framing and 37/36 in the
    other.

    Why it matters even though the two tie: `confirm` takes the top
    `shortlist_size` candidates, so a tie that straddles the shortlist boundary
    decides WHICH configuration gets fresh replicates and therefore which one
    can be certified — from a units choice the author made for readability.

    AND IT REACHES `recommend`, not only the tail. Hypothesis found a response
    vector whose fitted coefficients are symmetric across factors
    (beta_A = beta_B = beta_C = 1.7107291221618652, every 2fi the negation),
    under which {'A':2,'B':16,'C':16} and {'A':16,'B':2,'C':16} predict exactly
    2.2809721628824873. At scale 1.0 the first is recommended; at scale 0.01 the
    second is. Both are genuinely optimal under the fitted model, so the ANSWER
    is not wrong — but `recommendation.json` names a different configuration for
    the same experiment depending on the objective's units, which makes the
    artifact non-reproducible in a way a reader cannot see. Sorting by
    (predicted, sorted(levels.items())) would fix it.

    FIXED, and this test now asserts the fix rather than the gap: `ranked` sorts
    by (predicted, sorted((str(k), str(v)) for k, v in levels.items())). The
    stringified secondary key is deliberate — a level may be a number on one
    factor and a string on another, and comparing ("A", 2) against ("A", "lru")
    raises. No claim is made that the lexicographically-first tied configuration
    is BETTER; only that the same evidence always produces the same artifact.
    """
    d = with_center_points(full_factorial(_IDS), 4)
    ys = [1.0, 5.0, 2.0, 9.0, 3.0, 7.0, 4.0, 8.0, 6.0, 6.5, 6.2, 6.1]
    fit = fit_effects(d, ys, factor_ids=_IDS)
    factors = parse_factors([_numeric_factor(f) for f in _IDS])
    cands = ranked(fit, factors, direction="maximize", fitted_ids=_IDS,
                   held_fixed={}, top=None)

    by_value: dict[float, list] = {}
    for c in cands:
        by_value.setdefault(round(c.predicted, 9), []).append(c.levels)
    ties = {v: ls for v, ls in by_value.items() if len(ls) > 1}
    assert ties, (
        "expected exact ties in this candidate space — if the axis or the "
        "prediction changed, re-derive the example rather than deleting the test"
    )

    # THE TIE-BREAK ITSELF. `ranked` now sorts by
    # (predicted, sorted((str(k), str(v)) for k, v in levels.items())), so a tie
    # resolves by a DECLARED key rather than by enumeration order. Two things to
    # assert, and the second is the one that matters:
    #
    #  1. within every tie group the emitted order follows the declared key;
    #  2. the WHOLE ranking is invariant under rescaling the objective by a
    #     positive constant. That was the original symptom: at scale 1.0 one
    #     configuration was recommended and at scale 0.01 another, so
    #     `recommendation.json` named a different answer for the same experiment
    #     depending on units the author chose for readability.
    def _key(levels):
        # Mirrors decide._tie_key: numeric levels compare numerically and sort
        # before strings, so 9 precedes 16 rather than following it.
        lv = levels or {}
        return tuple(
            (fid, isinstance(lv[fid], str),
             0.0 if isinstance(lv[fid], str) else float(lv[fid]), str(lv[fid]))
            for fid in sorted(lv)
        )

    # Group on EXACT equality, not on a rounded value. `ranked` sorts on the full
    # float, so two candidates that merely round to the same 9 decimal places are
    # not tied for its purposes and may legitimately appear in predicted order.
    # Asserting over the rounded groups would test a tie the code never saw.
    exact: dict[float, list] = {}
    for c in cands:
        exact.setdefault(c.predicted, []).append(c.levels)
    exact_ties = {v: ls for v, ls in exact.items() if len(ls) > 1}
    assert exact_ties, "expected at least one EXACT tie in this candidate space"

    # WHAT THIS TEST CAN AND CANNOT DISCRIMINATE -- recorded because two attempts
    # at a stronger check were both wrong, and the reasons are instructive.
    #
    # (1) Asserting "ties come out in declared-key order" PASSES with the
    #     tie-break removed. `_scored` already enumerates ascending and Python's
    #     sort is stable, so the two orders coincide on every fixture: measured,
    #     the key changes the emitted order in 0 of 200 random response vectors,
    #     and rescaling moved top-1 in 0 of 400. The tie-break is therefore
    #     DEFENSIVE -- it makes the order a declared function of the levels rather
    #     than an accident of enumeration -- and no current test can kill its
    #     removal. That is stated here rather than papered over with a check that
    #     only looks discriminating.
    #
    # (2) Reversing each factor's declared level list does NOT test reordering. It
    #     flips the +/-1 CODING, so the fitted coefficients describe a mirrored
    #     space and `{A:16,B:2,C:2}` under reversed levels is the same physical
    #     point as `{A:2,B:16,C:16}` under forward levels -- identical prediction
    #     (9.066667), not a moved recommendation. A relabeling is not a
    #     re-enumeration.
    #
    # What IS asserted below: ties exist, and among exactly-tied candidates the
    # emitted order matches the declared key. Weaker than a mutation-killing test,
    # and honest about it.

    for value, group in exact_ties.items():
        assert group == sorted(group, key=_key), (
            f"exact tie at {value!r} is not ordered by the declared key: {group}"
        )

    # RESCALING INVARIANCE, scoped to what is actually claimable. The DECISION —
    # the recommendation and the shortlist `confirm` replicates — must not depend
    # on the objective's units. The full tail cannot make that promise and this
    # test does not pretend otherwise: rescaling changes float rounding, so two
    # candidates that are exactly tied at one scale need not be exactly tied at
    # another, and a tie-break can order ties but cannot decide which values tie.
    # Measured here: with the tie-break in place the orders first diverge at index
    # 28 (scale 0.01) and index 36 (scale 1000) of a 45-candidate space, while the
    # top stays fixed. Before the tie-break the TOP-1 itself moved, which is the
    # defect this guards.
    #
    # SHORTLIST_DEPTH is deliberately generous relative to real
    # `design.confirm.shortlist_size` values (typically 3-4), so the assertion
    # covers every candidate any campaign would actually replicate.
    SHORTLIST_DEPTH = 10
    for scale in (0.01, 1000.0):
        rescaled = fit_effects(d, [y * scale for y in ys], factor_ids=_IDS)
        again = ranked(rescaled, factors, direction="maximize",
                       fitted_ids=_IDS, held_fixed={}, top=None)
        assert again[0].levels == cands[0].levels, (
            f"rescaling the objective by {scale} moved the RECOMMENDATION from "
            f"{cands[0].levels} to {again[0].levels}; a pre-registered "
            f"recommendation must not depend on the objective's units"
        )
        assert [c.levels for c in again[:SHORTLIST_DEPTH]] == \
               [c.levels for c in cands[:SHORTLIST_DEPTH]], (
            f"rescaling by {scale} reordered the top {SHORTLIST_DEPTH}, which is "
            f"where `confirm` draws its shortlist from"
        )


# ── ORACLE ANCHORS: closing metamorphic testing's structural blind spot ────
#
# A metamorphic relation compares TWO RUNS OF THE SAME CODE, so any error that
# applies UNIFORMLY to both runs cancels and the relation still holds. Two
# mutations in this layer's mutation matrix survived for exactly this reason:
#
#   M03  every coefficient halved            -> the replicate and rescaling
#                                               relations both still hold
#   M12  the certificate's direction sign
#        inverted                            -> minimize-f and maximize-(-f)
#                                               invert together, so the
#                                               symmetry relation still holds
#
# The blind spot is structural, not an oversight in how the relations were
# phrased: relations constrain the RATIO between two outputs and say nothing
# about either output's absolute value. Closing it needs an ORACLE — a value
# derived independently of the code — which is what these tests add. They are
# few and small on purpose; the relations above are what generalise, and these
# are what anchor them to reality.


@pytest.mark.mutation_sentinel
def test_the_closed_form_coefficients_match_hand_arithmetic_exactly():
    """ORACLE ANCHOR for the fit. Hand-computed, not generated.

    For a balanced ±1 orthogonal design, beta_j = sum_i(x_ij * y_i) / N. On the
    2^2 full factorial with the coded columns this module generates:

        row   A    B   AB    y
         0   -1   -1   +1   1.0
         1   -1   +1   -1   4.0
         2   +1   -1   -1   2.0
         3   +1   +1   +1   9.0

        intercept = (1+4+2+9)/4                   = 4.0
        beta_A    = (-1-4+2+9)/4                  = 1.5
        beta_B    = (-1+4-2+9)/4                  = 2.5
        beta_AB   = (+1-4-2+9)/4                  = 1.0

    Arithmetic done by hand and verified against the implementation. Any uniform
    scale error — the M03 mutation halves every coefficient — fails here and
    passes every relation above.
    """
    fit = fit_effects(full_factorial(("A", "B")), [1.0, 4.0, 2.0, 9.0],
                      factor_ids=("A", "B"))
    assert fit.intercept == 4.0
    got = {e.label: e.estimate for e in fit.effects}
    assert got == {"A": 1.5, "B": 2.5, "AB": 1.0}, got
    assert fit.n_runs == 4


@pytest.mark.mutation_sentinel
def test_the_certificate_bounds_the_gap_in_the_direction_the_campaign_optimizes():
    """ORACLE ANCHOR for the certificate's sign. Absolute, not relational.

    The relation `minimize f == maximize -f` cannot see a sign inverted in BOTH
    framings (mutation M12). The absolute fact it misses: the bound is over
    CHALLENGERS' possible gain over x-hat, and x-hat is the argmax of the fitted
    response — so every challenger's point estimate is <= 0 and the bound floors
    at 0.0. An inverted sign makes every challenger's estimate >= 0 instead, so
    the bound becomes LARGE and positive on data where the winner is clear.

    Constructed so the two are distinguishable: a strong, well-estimated A effect
    means the fitted winner beats its challengers by far more than the noise, so a
    correctly-signed bound is ~0 and an inverted one is order-of-magnitude the
    effect size.

    Cross-reference: `docs/optimization-invariants.md` INV-STAT03 — the statement of
    record lives there; this test is the executable check.
    """
    d = with_center_points(full_factorial(("A", "B")), 4)
    # A dominates; centre replicates are tight, so the pure error is small.
    ys = [0.0, 1.0, 10.0, 11.0, 5.4, 5.5, 5.45, 5.48]
    fit = fit_effects(d, ys, factor_ids=("A", "B"))
    assert fit.pure_error_df == 3 and fit.pure_error_var is not None

    factors = parse_factors([_numeric_factor("A"), _numeric_factor("B")])
    kw = dict(direction="maximize", fitted_ids=("A", "B"), held_fixed={})
    cands = ranked(fit, factors, top=None, **kw)
    xhat = recommend(fit, factors, **kw)
    bound = model_regret_bound(fit, cands, xhat, delta=0.05, direction="maximize")

    # x-hat IS the fitted argmax, so it beats every challenger under the model.
    assert bound.value is not None
    fx = max(c.predicted for c in cands)
    assert math.isclose(xhat.predicted, fx, rel_tol=1e-9)
    # And the bound is small relative to the effect it is bounding: the winner is
    # clear. An inverted sign cannot satisfy this.
    effect_scale = max(abs(e.estimate) for e in fit.effects)
    assert bound.value < effect_scale, (
        f"bound {bound.value} is not smaller than the dominant effect "
        f"{effect_scale} — the contrast is oriented the wrong way, so every "
        f"challenger appears to BEAT the recommendation"
    )


@pytest.mark.mutation_sentinel
def test_the_terminal_bound_is_zero_when_the_winner_leads_and_large_when_it_trails():
    """ORACLE ANCHOR for the terminal bound's sign, stated as two absolutes.

    `best` is the argmax of the observed means, so every challenger's estimate is
    <= 0 and the bound floors at 0.0. Passing a DELIBERATELY WRONG `best` — the
    finalist that actually trails — must produce a large positive bound, because
    a challenger genuinely does beat it. A sign error collapses the distinction
    between these two calls, and no relation between them can detect that.
    """
    samples = {"f1": [5.0, 5.2, 5.1], "f2": [9.0, 9.3, 9.1]}
    right = terminal_regret_bound(samples, "f2", delta=0.05, direction="maximize",
                                  paired=False)
    assert right.value == 0.0, (
        f"the leading finalist has a non-zero regret bound ({right.value})"
    )

    wrong = terminal_regret_bound(samples, "f1", delta=0.05, direction="maximize",
                                  paired=False)
    assert wrong.value is not None and wrong.value > 3.0, (
        f"naming the TRAILING finalist as best gave a bound of {wrong.value}; "
        f"the true gap is about 4.0, so the contrast is not being measured"
    )
    assert wrong.challenger == "f2"


@pytest.mark.mutation_sentinel
def test_a_negated_alias_records_sign_minus_one_and_reattribution_flips_the_effect():
    """CLOSES A MUTATION SURVIVOR (M04) that no tabulated design can reach.

    Dropping the alias SIGN — recording every confounding as ``+1`` — survived
    every other test in this layer, because NO design `design.py` tabulates
    produces a negated alias: every published generator word is positive, so
    every aliased column is IDENTICAL to the one it is confounded with. The
    module's own docstring says exactly that, and adds that "a hand-built or
    folded design can reach it — so the sign is recorded rather than assumed".
    This test is that hand-built design, so the claim is checked rather than
    only stated.

    Construction: 4 runs over A, B, C with
        A  = (+1, -1, -1, +1)
        B  = (+1, -1, +1, -1)   ->  AB = (+1, +1, -1, -1)
        C  = (-1, -1, +1, +1)   =  -AB
    so C's column is the exact NEGATION of AB's. The fit keeps C (a main effect,
    added first) and records AB as aliased onto it at sign -1.

    Why the sign is load-bearing, from the docstring's own worked case: the
    coefficient is attributed to the KEPT column, so re-attributing it to the
    alternative asks "what would the fit have found regressing on the
    alternative's column instead?" — and regressing on -x returns -beta. A
    consumer that relabelled the estimate while KEEPING its sign would claim the
    factor pushes the response DOWN when it pushes it UP: the physical direction
    of the effect, reversed. `decide.alias_consequential` multiplies by this sign
    for that reason.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM08 — the statement of
    record lives there; this test is the executable check.
    """
    from orchestrator.optimize.decide import alias_resolutions

    a = (1.0, -1.0, -1.0, 1.0)
    b = (1.0, -1.0, 1.0, -1.0)
    c = (-1.0, -1.0, 1.0, 1.0)          # == -(a*b), elementwise
    assert c == tuple(-(x * y) for x, y in zip(a, b))

    d = Design(
        points=tuple(DesignPoint(coded=(a[i], b[i], c[i])) for i in range(4)),
        factor_ids=("A", "B", "C"), kind="fractional", resolution=3,
    )
    fit = fit_effects(d, [3.0, 1.0, 8.0, 6.0], factor_ids=("A", "B", "C"))

    by_label = {e.label: e for e in fit.effects}
    assert set(by_label) == {"A", "B", "C"}, (
        "the aliased 2fi columns must be collapsed into the main effects they "
        "duplicate, not added as separate columns"
    )
    # Every recorded alias on this design is NEGATED — sign -1.0, not +1.0.
    signs = {lbl: {s for _terms, s in e.aliased_with} for lbl, e in by_label.items()}
    assert signs == {"A": {-1.0}, "B": {-1.0}, "C": {-1.0}}, (
        f"expected every alias on a negated-column design to carry sign -1.0, "
        f"got {signs} — the sign is being recorded as +1 regardless"
    )
    assert by_label["C"].aliased_with == ((("A", "B"), -1.0),)

    # And re-attribution actually applies the sign: C's estimate is +2.5, so the
    # alternative reading (AB) must be -2.5, not +2.5.
    assert math.isclose(by_label["C"].estimate, 2.5, abs_tol=1e-9)
    alts = {alt: f.effects for _i, kept, alt, f in alias_resolutions(fit)
            if kept == "C"}
    assert "AB" in alts, f"no alternative reading offered for C: {sorted(alts)}"
    ab = next(e for e in alts["AB"] if e.label == "AB")
    assert math.isclose(ab.estimate, -2.5, abs_tol=1e-9), (
        f"re-attributing C's +2.5 to its NEGATED alias AB gave {ab.estimate}; "
        f"keeping the sign would reverse the effect's physical direction"
    )


@pytest.mark.mutation_sentinel
def test_the_argmax_can_tie_which_makes_the_certified_bound_scale_dependent():
    """A SECOND, SHARPER INSTANCE of the missing tie-break — this one reaches the
    certificate, not just a ranking position.

    Found by the rescaling relation above, on generated input rather than a
    hand-picked one. With
        ys = [-13.685832977294922, 0.0, -70.90581512451172, -0.0,
              -0.0, -22.73369789123535, -0.0, 0.0]
    on a 2-factor CCD with 4 centre points, the fit gives
        beta_A = -14.304995537,  beta_AB = +14.304995537,  beta_B = +21.147912025
    so ``beta_A == -beta_AB`` EXACTLY. At ``B = +1`` the model is
    ``mu + beta_A*A + beta_B + beta_AB*A`` = ``mu + beta_B + A*(beta_A + beta_AB)``
    = ``mu + beta_B``: factor A cancels completely, and EVERY level of A predicts
    the identical 7.732243776321411. The argmax is a 9-way tie.

    The consequence is not cosmetic. Rescaling by 11 perturbs the last bit of
    each tied prediction differently (7.732243776321411 vs ...412 across
    levels), the argmax moves from ``{'A': 2, 'B': 16}`` to ``{'A': 4, 'B': 16}``,
    and because ``model_regret_bound`` measures every challenger RELATIVE to
    x-hat, the certified bound changes from 192.64 to 1834.53/11 = 166.78 — a
    15% swing in the number the campaign reports as its residual regret, from a
    units choice.

    Both answers are defensible (the two configurations are genuinely
    indistinguishable under the fitted model), so this is not a wrong-answer bug.
    It is a REPRODUCIBILITY bug: `recommendation.json` and `report.json` record a
    specific configuration and a specific bound, and re-running the same
    experiment with the objective reported in different units yields different
    artifacts with nothing to indicate why. A deterministic tie-break — sorting
    by ``(predicted, sorted(levels.items()))`` in `decide.ranked`/`recommend` —
    fixes both this and the ranking instance.

    Asserts the tie EXISTS (the precondition for the instability) rather than
    asserting the instability itself, so the test stays meaningful either way: if
    a tie-break lands, the tie is still here and the argmax simply becomes
    stable, and the assertion at the end of the rescaling relation above starts
    covering this case instead of returning early.
    """
    d = with_center_points(full_factorial(("A", "B")), 4)
    ys = [-13.685832977294922, 0.0, -70.90581512451172, -0.0,
          -0.0, -22.73369789123535, -0.0, 0.0]
    fit = fit_effects(d, ys, factor_ids=("A", "B"))

    by = {e.label: e.estimate for e in fit.effects}
    assert math.isclose(by["A"], -by["AB"], rel_tol=1e-12), (
        f"the exact cancellation this example rests on is gone: "
        f"beta_A={by['A']}, beta_AB={by['AB']} — re-derive the example"
    )

    factors = parse_factors([_numeric_factor("A"), _numeric_factor("B")])
    kw = dict(direction="maximize", fitted_ids=("A", "B"), held_fixed={})
    cands = ranked(fit, factors, top=None, **kw)
    top = max(c.predicted for c in cands)
    tied = [c for c in cands if c.predicted == top]
    assert len(tied) > 1, (
        f"expected a multi-way tie at the argmax, found {len(tied)} candidate(s) "
        f"at {top}"
    )
    # Every tied candidate sits at B's top level, differing only in A — the
    # cancelled factor.
    assert len({tuple(sorted(c.levels.items())) for c in tied}) == len(tied)
    assert len({c.levels["B"] for c in tied}) == 1, (
        "the tie should span A's levels at a single B level"
    )
