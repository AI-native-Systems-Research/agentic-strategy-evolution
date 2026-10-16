"""The L-1 df fit of a multi-level categorical, checked against numpy/scipy
(tests may use numpy; orchestrator/optimize may not). Spec
2026-10-16-mixed-level-factors-design.md, feature 1."""
from __future__ import annotations

import random

import numpy as np
import pytest
from scipy.stats import f as fisher_f

from orchestrator.optimize.decide import _scored, candidates, ranked
from orchestrator.optimize.design import mixed_screen
from orchestrator.optimize.effects import factor_test, fit_effects, model_matrix
from orchestrator.optimize.factors import code_vector, model_columns, parse_factors
from orchestrator.optimize.matrix import coded_as_run, expand
from orchestrator.optimize.stage import decide_after_screen
from orchestrator.optimize.synthetic import _choice, _numeric


def _setup(L=3, res=5, n_c=4, effects=None, seed=0, sd=0.1):
    fs = parse_factors([_numeric("A", levels=(2, 16)),
                        _choice("C", levels=tuple(f"l{i}" for i in range(L)))])
    d = mixed_screen(fs, resolution=res, center_points=n_c)
    rows = expand(d, fs)
    run, _ = coded_as_run(d, fs, [r.levels for r in rows])
    eff = effects or {f"l{i}": float(i % 3) for i in range(L)}
    rng = random.Random(seed)
    ys = [10 + 0.05 * r.levels["A"] + eff[r.levels["C"]] + rng.gauss(0, sd)
          for r in rows]
    return fs, d, run, rows, ys


def _X(run):
    labels, terms, cols, _q, _a = model_matrix(run, run.factor_ids)
    return labels, np.array(cols).T


def _X_aug(run):
    """The model columns plus one 0/1 indicator per centre CONFIGURATION: the
    matrix a mixed fit is estimated on (curvature isolation, stage-1 M1), so
    every coefficient comes from the corner rows."""
    labels, X = _X(run)
    keys = {}
    for r, p in enumerate(run.points):
        if p.role == "center":
            keys.setdefault(tuple(p.coded), []).append(r)
    ind = np.zeros((len(run.points), len(keys)))
    for j, rs in enumerate(keys.values()):
        ind[rs, j] = 1.0
    return labels, np.hstack([X, ind])


def test_no_product_of_a_categoricals_own_columns_is_formed():
    fs, _d, run, _rows, _ys = _setup(L=4)
    labels, _X_ = _X(run)
    own = set(model_columns(fs[1]))
    for lab in labels:
        assert sum(c in lab for c in own) <= 1 or lab in own, lab


@pytest.mark.parametrize("L", [3, 4, 5])
def test_exact_ses_equal_sigma_sqrt_xtx_inverse(L):
    fs, _d, run, _rows, ys = _setup(L=L, seed=L)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    labels, X = _X_aug(run)
    inv = np.linalg.inv(X.T @ X)
    for e in fit.effects:
        j = labels.index(e.label)
        assert e.se == pytest.approx(np.sqrt(fit.pure_error_var * inv[j, j]), rel=1e-9)


@pytest.mark.parametrize("L", [3, 4, 5])
def test_the_F_test_equals_the_extra_sum_of_squares_F(L):
    fs, _d, run, rows, ys = _setup(L=L, seed=10 + L)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    t = factor_test(fit, "C")
    labels, X = _X_aug(run)
    y = np.array(ys)
    drop = [labels.index(c) for c in model_columns(fs[1])]
    keep = [j for j in range(X.shape[1]) if j not in drop]
    rss = lambda M: float(np.sum((y - M @ np.linalg.lstsq(M, y, rcond=None)[0]) ** 2))  # noqa: E731
    ss_extra = rss(X[:, keep]) - rss(X)
    f_ref = (ss_extra / (L - 1)) / fit.pure_error_var
    assert t.df == L - 1
    assert t.f == pytest.approx(f_ref, rel=1e-8)
    assert t.p == pytest.approx(1 - fisher_f.cdf(f_ref, L - 1, fit.pure_error_df), rel=1e-6)


def test_a_null_categorical_is_dropped_and_a_live_one_survives():
    fs, _d, run, _r, ys = _setup(L=3, effects={"l0": 0, "l1": 0, "l2": 0}, sd=0.05)
    dec = decide_after_screen(fit_effects(run, ys, factor_ids=run.factor_ids), fs)
    assert "C" in dec.dropped
    fs, _d, run, _r, ys = _setup(L=3, effects={"l0": 0, "l1": 1.0, "l2": 0}, sd=0.05)
    dec = decide_after_screen(fit_effects(run, ys, factor_ids=run.factor_ids), fs)
    assert "C" in dec.surviving


@pytest.mark.parametrize("L", [3, 5])
def test_every_level_is_a_candidate_and_the_argmax_finds_the_best(L):
    eff = {f"l{i}": 0.0 for i in range(L)}
    eff[f"l{L // 2}"] = 2.0
    fs, _d, run, _r, ys = _setup(L=L, effects=eff, sd=0.05)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    cands = candidates(["A", "C"], fs, held_fixed={})
    assert {c.levels["C"] for c in cands} == set(fs[1].levels)
    for c in cands:
        assert [c.coded[k] for k in model_columns(fs[1])] == list(code_vector(fs[1], c.levels["C"]))
    best = ranked(fit, fs, direction="maximize", fitted_ids=["A", "C"], held_fixed={})[0]
    assert best.levels == {"A": 16, "C": f"l{L // 2}"}


def test_the_search_above_the_cap_cycles_a_categorical_through_all_levels():
    """cap=1 forces the seeded coordinate ascent; it must still reach the
    middle level (sample=0, so only the ascent can get there)."""
    eff = {"l0": 0.0, "l1": 0.0, "l2": 2.0, "l3": 0.0, "l4": 0.0}
    fs, _d, run, _r, ys = _setup(L=5, effects=eff, sd=0.05)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    sc = _scored(fit, fs, fitted_ids=["A", "C"], held_fixed={}, exclude_levels=(),
                 cap=1, sample=0)
    assert not sc.space.exhaustive
    assert max(sc, key=lambda c: c.predicted).levels == {"A": 16, "C": "l2"}


def test_collapsed_rows_are_coded_identically_to_canonical_rows():
    fs, _d, run, rows, _ys = _setup(L=3)
    by_level = {}
    for p, r in zip(run.points, rows):
        by_level.setdefault(r.levels["C"], set()).add(
            tuple(p.coded[run.factor_ids.index(c)] for c in model_columns(fs[1])))
    assert all(len(v) == 1 for v in by_level.values())


def test_foldover_of_a_mixed_screen_runs_and_keeps_every_level():
    from orchestrator.optimize.design import combine, foldover

    fs = parse_factors([_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16)),
                        _numeric("D", levels=(2, 16)),
                        _choice("C", levels=("a", "b", "c", "d"))])
    d = mixed_screen(fs, resolution=4, center_points=2)
    fold = foldover(d, on="C[1]")
    rows = expand(combine(d, fold), fs)
    assert {r.levels["C"] for r in rows} == {"a", "b", "c", "d"}


def test_a_hand_written_design_matrix_for_three_collapsed_levels():
    """L=3 in two pseudo-factors: (b0,b1,b2,b3) -> (l0,l1,l2,l0), contrasts
    C[1] (pseudo 1) and C[2] (pseudo 2) at each level's CANONICAL code
    (l0: (-,-), l1: (+,-), l2: (-,+)). Written by hand, not by the code."""
    f = parse_factors([_choice("C", levels=("l0", "l1", "l2"))])[0]
    assert model_columns(f) == ("C[1]", "C[2]")
    assert code_vector(f, "l0") == (-1.0, -1.0)
    assert code_vector(f, "l1") == (1.0, -1.0)
    assert code_vector(f, "l2") == (-1.0, 1.0)
    fs = parse_factors([_numeric("A", levels=(2, 16)),
                        _choice("C", levels=("l0", "l1", "l2"))])
    d = mixed_screen(fs, resolution=5, center_points=0, allow_level_full=False)
    run, _ = coded_as_run(d, fs, [r.levels for r in expand(d, fs)])
    got = sorted(tuple(p.coded) for p in run.points)
    want = sorted((a, *c) for a in (-1.0, 1.0)
                  for c in ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0)))
    assert got == want


def test_variance_inflation_equals_the_uncentred_numpy_value():
    fs, _d, run, _r, ys = _setup(L=3, seed=3)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    labels, X = _X_aug(run)
    inv = np.linalg.inv(X.T @ X)
    for lab, v in fit.variance_inflation:
        j = labels.index(lab)
        assert v == pytest.approx(inv[j, j] * float(X[:, j] @ X[:, j]), rel=1e-9)


@pytest.mark.parametrize("L", [3, 5])
def test_T4_exact_prediction_variance_equals_numpy(L):
    from orchestrator.optimize.effects import prediction_variance

    fs, _d, run, _r, ys = _setup(L=L, seed=7)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    labels, terms, cols, _q, _a = model_matrix(run, run.factor_ids)
    _l, Xa = _X_aug(run)
    inv = np.linalg.inv(Xa.T @ Xa)[:len(labels), :len(labels)]
    for c in candidates(["A", "C"], fs, held_fixed={}):
        x = np.array([1.0] + [np.prod([c.coded[t] for t in ts]) for ts in terms[1:]])
        assert prediction_variance(fit, c.coded) == pytest.approx(
            fit.pure_error_var * float(x @ inv @ x), rel=1e-9)


def test_T4_consumers_use_the_exact_variance_not_the_per_term_sum():
    """Collapsed L=3: the exact x'(X'X)^-1 x differs from the per-term sum
    (which ignores the covariances between coefficients), and
    predicted_with_se / model_regret_bound report the exact one."""
    import dataclasses

    from orchestrator.optimize import certificate
    from orchestrator.optimize.constraint_models import predicted_with_se
    from orchestrator.optimize.effects import prediction_variance

    fs, _d, run, _r, ys = _setup(L=3, seed=5)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    cands = ranked(fit, fs, direction="maximize", fitted_ids=["A", "C"],
                   held_fixed={}, top=None)
    larger = 0
    for c in cands:
        _y, se = predicted_with_se(fit, c.coded)
        assert se ** 2 == pytest.approx(prediction_variance(fit, c.coded), rel=1e-9)
        per_term = fit.pure_error_var / fit.n_runs + sum(
            (e.se or 0) ** 2 * np.prod([c.coded[t] for t in e.terms]) ** 2
            for e in fit.effects)
        larger += abs(se ** 2 - per_term) > 1e-6 * per_term
    assert larger >= len(cands) // 2
    rb = certificate.model_regret_bound(fit, cands, cands[0], delta=0.05,
                                        direction="maximize")
    no_cov = dataclasses.replace(fit, covariance=None)
    rb_old = certificate.model_regret_bound(no_cov, cands, cands[0], delta=0.05,
                                            direction="maximize")
    assert rb.value is not None and rb.value != pytest.approx(rb_old.value)


def test_T5_a_categorical_without_pure_error_is_unknown_and_kept():
    fs, _d, run, _r, ys = _setup(L=3, n_c=0)
    fit = fit_effects(run, ys, factor_ids=run.factor_ids)
    t = factor_test(fit, "C")
    assert t.significant is None and t.f is None
    dec = decide_after_screen(fit, fs)
    assert "C" in dec.surviving and "C" not in dec.dropped
