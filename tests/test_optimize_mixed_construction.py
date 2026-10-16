"""The mixed-level screen by the METHOD OF REPLACEMENT, checked off the matrix
(spec 2026-10-16-mixed-level-factors-design.md, feature 1).

Two independent readings of "generalized resolution R":

* WORDS, off the PSEUDO-COLUMN matrix (Wu & Zhang 1993's word length, the
  four-level factor counted once): for every set T of at most R-1 distinct
  factors and every choice of one nonzero element of each factor's contrast
  subspace, the product of those columns over the corner runs is NOT constant.
  A constant product is a defining word of length |T| < R.
* STRENGTH, off the LEVEL matrix (Rao 1947; Addelman 1962's proportional
  frequencies, which collapsing preserves): every R-1 factors' level
  combinations occur with frequency N * prod(p_level), where p is each
  factor's marginal level proportion. Resolution R <=> strength R-1.
"""
from __future__ import annotations

import itertools
import math
import random
from collections import Counter

import pytest

from orchestrator.optimize.design import (
    alias_pairs,
    fractional_factorial,
    full_factorial,
    mixed_fraction,
    mixed_screen,
)
from orchestrator.optimize.factors import (
    code_vector,
    is_categorical,
    model_columns,
    n_pseudo,
    parse_factors,
)
from orchestrator.optimize.matrix import expand
from orchestrator.optimize.synthetic import _choice, _numeric


def _factors(Ls):
    raw = []
    for i, L in enumerate(Ls):
        fid = f"F{i}"
        raw.append(_choice(fid, levels=tuple(f"l{j}" for j in range(L)))
                   if L > 2 else _numeric(fid, levels=(2, 16)))
    return parse_factors(raw)


def _subspace_cols(design, f):
    """Every nonzero element of factor f's contrast subspace, as a column of
    +-1 over the corners (products of its pseudo columns)."""
    idx = [j for j, g in enumerate(design.groups or design.factor_ids) if g == f.id]
    corners = design.corners
    out = []
    for r in range(1, len(idx) + 1):
        for sub in itertools.combinations(idx, r):
            out.append(tuple(math.prod(p.coded[j] for j in sub) for p in corners))
    return out


def _min_word_length(design, factors, upto):
    subs = {f.id: _subspace_cols(design, f) for f in factors}
    n = len(design.corners)
    for t in range(1, upto + 1):
        for T in itertools.combinations(factors, t):
            for choice in itertools.product(*(subs[f.id] for f in T)):
                prod = [math.prod(c[r] for c in choice) for r in range(n)]
                if len(set(prod)) == 1:
                    return t
    return None


def _strength_ok(rows, factors, t):
    N = len(rows)
    marg = {f.id: Counter(r.levels[f.id] for r in rows) for f in factors}
    for T in itertools.combinations(factors, t):
        cnt = Counter(tuple(r.levels[f.id] for f in T) for r in rows)
        for combo in itertools.product(*(list(marg[f.id]) for f in T)):
            expect = N * math.prod(marg[f.id][lv] / N for f, lv in zip(T, combo))
            if not math.isclose(cnt.get(combo, 0), expect, abs_tol=1e-9):
                return False
    return True


# ── the pure two-level path is untouched ────────────────────────────────────


@pytest.mark.parametrize("k, res", [(4, 4), (5, 5), (7, 3), (6, 4)])
def test_two_level_factors_never_take_the_mixed_path(k, res):
    fs = _factors([2] * k)
    assert not any(is_categorical(f) for f in fs)
    assert all(model_columns(f) == (f.id,) for f in fs)


# ── coding ───────────────────────────────────────────────────────────────────


def test_pseudo_factor_count_is_ceil_log2_of_the_level_count():
    for L, m in [(3, 2), (4, 2), (5, 3), (8, 3), (9, 4)]:
        assert n_pseudo(_factors([L])[0]) == m


@pytest.mark.parametrize("L", [3, 4, 5, 6, 7, 8])
def test_contrast_coding_has_L_minus_1_columns_spanning_every_level(L):
    """L-1 columns which, with the intercept, separate every level: the main
    effect has exactly L-1 df."""
    import numpy as np

    f = _factors([L])[0]
    assert len(model_columns(f)) == L - 1
    X = np.array([[1.0, *code_vector(f, lv)] for lv in f.levels])
    assert np.linalg.matrix_rank(X) == L


def test_a_power_of_two_categorical_is_coded_orthogonally():
    import numpy as np

    f = _factors([4])[0]
    X = np.array([code_vector(f, lv) for lv in f.levels])
    assert np.allclose(X.T @ X, 4 * np.eye(3))
    assert np.allclose(X.sum(axis=0), 0)


# ── generalized resolution, read off the matrix ─────────────────────────────


@pytest.mark.parametrize("Ls, res", [
    ((3, 2, 2), 5), ((4, 2, 2, 2), 4), ((3, 3, 2), 3), ((5, 2), 5),
    ((8, 2, 2), 4), ((3, 4, 5), 3), ((4, 4, 2, 2), 5),
])
def test_named_mixes_reach_their_resolution(Ls, res):
    fs = _factors(Ls)
    d = mixed_screen(fs, resolution=res, center_points=0)
    assert _min_word_length(d, fs, res - 1) is None
    assert _strength_ok(expand(d, fs), fs, res - 1)
    assert d.resolution == res


def test_random_mixes_reach_their_resolution_off_the_matrix():
    """Property test: 40 random mixes of L in {2..8}, R in {3, 4, 5}."""
    rng = random.Random(20261016)
    checked = 0
    while checked < 40:
        R = rng.choice([3, 4, 5])
        k = rng.randint(2, 5 if R == 5 else 6)
        Ls = [rng.randint(2, 8) for _ in range(k)]
        if not any(L > 2 for L in Ls):
            continue
        fs = _factors(Ls)
        d = mixed_screen(fs, resolution=R, center_points=0)
        assert _min_word_length(d, fs, R - 1) is None, (Ls, R)
        assert _strength_ok(expand(d, fs), fs, R - 1), (Ls, R)
        checked += 1


def test_every_level_of_every_categorical_runs_in_the_screen():
    fs = _factors([3, 5, 2])
    rows = expand(mixed_screen(fs, resolution=4, center_points=0), fs)
    for f in fs:
        assert {r.levels[f.id] for r in rows} == set(f.levels)


def test_collapsing_replicates_the_first_levels_twice():
    """L = 5 in 2^3 slots: b = 5, 6, 7 collapse onto levels 0, 1, 2."""
    fs = _factors([5, 2])
    rows = expand(mixed_screen(fs, resolution=3, center_points=0), fs)
    c = Counter(r.levels["F0"] for r in rows)
    assert c["l0"] == c["l1"] == c["l2"] == 2 * c["l3"] == 2 * c["l4"]


def test_the_construction_is_deterministic_and_meets_the_df_bound():
    blocks = (2, 2, 1, 1)
    a = mixed_fraction(blocks, 3)
    assert a == mixed_fraction(blocks, 3)
    n_base, _assign = a
    assert 2 ** n_base >= 1 + 3 + 3 + 1 + 1
    assert 2 ** n_base <= 16


def test_mixed_alias_pairs_are_empty_at_resolution_five():
    fs = _factors([3, 2, 2])
    assert alias_pairs(mixed_screen(fs, resolution=5, center_points=0)) == []


def test_mixed_alias_pairs_name_contrast_components_at_resolution_four():
    fs = _factors([4, 2, 2, 2, 2])
    d = mixed_screen(fs, resolution=4, center_points=0)
    pairs = alias_pairs(d)
    # Every reported pair is 2fi ~ 2fi (resolution IV: no 2fi on a main).
    mains = {lab for f in fs for lab in model_columns(f)}
    assert pairs and all(a not in mains and b not in mains for a, b in pairs)
