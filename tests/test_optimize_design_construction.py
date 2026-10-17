"""No factor count forces a full factorial: constructed Res III / IV / V designs.

Every claim here is read off the generated DESIGN MATRIX, never off the
generator words the construction chose, so a construction bug cannot certify
itself. The textbook table (k <= 8) is pinned unchanged, so existing
campaigns compile the same designs as before.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

import orchestrator.optimize.design as D
from orchestrator.optimize.design import (
    _GENERATORS,
    alias_pairs,
    central_composite,
    fractional_factorial,
    full_factorial,
    generators_for,
    is_tabulated,
    min_runs_for,
)


def _ids(k):
    return tuple(f"F{i:02d}" for i in range(k))


def _matrix(d):
    return np.array([p.coded for p in d.corners])


def _shortest_word(X, upto):
    """Length of the shortest defining word (a set of columns whose product
    is constant), searched up to ``upto``; ``upto + 1`` means none that short."""
    k = X.shape[1]
    for r in range(1, upto + 1):
        for S in itertools.combinations(range(k), r):
            prod = np.prod(X[:, S], axis=1)
            if np.all(prod == prod[0]):
                return r
    return upto + 1


CASES = [(k, r) for r in (3, 4, 5) for k in range(3, 25)
         if is_tabulated(k, r) and (k, r) not in _GENERATORS]


@pytest.mark.parametrize("k,res", CASES)
def test_every_constructed_design_has_at_least_its_resolution(k, res):
    d = fractional_factorial(_ids(k), res)
    X = _matrix(d)
    assert X.shape == (min_runs_for(k, res), k)
    # Resolution R <=> no defining word shorter than R.
    assert _shortest_word(X, res - 1) >= res
    if res >= 5:
        assert alias_pairs(d) == [], "resolution V aliases no main or 2fi"
    # Main effects are orthogonal to each other and to the mean.
    assert np.allclose(X.T @ X, len(X) * np.eye(k))


# Literal run counts: an independent statement of what the construction must
# give, never a comparison of one helper of this module with another.
RES_III = {3: 4, 7: 8, 8: 16, 15: 16, 16: 32, 31: 32, 32: 64, 63: 64, 64: 128,
           100: 128, 127: 128}
RES_IV = {4: 8, 5: 16, 8: 16, 9: 32, 16: 32, 17: 64, 32: 64, 33: 128, 64: 128,
          65: 256, 100: 256}
RES_V = {5: 16, 6: 32, 8: 64, 9: 128, 11: 128, 12: 256, 17: 256, 18: 512, 23: 512,
         24: 1024, 30: 1024}


@pytest.mark.parametrize("res,table", [(3, RES_III), (4, RES_IV)])
def test_resolution_three_and_four_run_counts(res, table):
    """III: the smallest power of two above k. IV: the smallest power of two
    >= 2k (the even / folded-over design). Both meet Rao's counting bound
    (k + 1 and 2k), so they are optimal among regular designs."""
    for k, n in table.items():
        assert min_runs_for(k, res) == n, (k, res)
        assert D._counting_bound_runs(k, res) == n, (k, res)


def test_resolution_five_run_counts():
    """The largest known resolution-V factor counts -- 6 / 8 / 11 / 17 / 23 in
    32 / 64 / 128 / 256 / 512 runs -- are attained, and 24..30 fit in 1024."""
    for k, n in RES_V.items():
        assert min_runs_for(k, 5) == n, k


@pytest.mark.parametrize("k", [31, 40, 47, 64])
def test_resolution_five_beyond_thirty_is_within_one_doubling(k):
    assert min_runs_for(k, 5) <= 2 * D._smallest_known_runs(k, 5)


def test_a_sixteen_knob_screen_is_a_fraction_not_sixty_five_thousand_runs():
    assert min_runs_for(16, 5) == 256 and min_runs_for(16, 4) == 32
    assert min_runs_for(16, 3) == 32


# ── golden digests: an RNG change must not silently change a design ─────────

# Resolution V at these k needs the seeded restarts (``random.Random``), so a
# change to Python's RNG, to the seed formula or to the candidate order would
# change the design every campaign of that size compiles. Pinned here.
GOLDEN = {
    23: (9, "ddf469e7c4fc774f48b8278799a109aa0d74f17868bb7a3f0b828dda9b2333d7"),
    30: (10, "eba5affdae3c8dab4f36b64cb87449675e2e71c4c0c29b96ae7128227801869e"),
    39: (11, "707545bd2cf1ffff70cfa0935751842ee2a56db25ebac46e048fff157bbf5e0d"),
}


@pytest.mark.parametrize("k", sorted(GOLDEN))
def test_rng_dependent_constructions_are_pinned(k):
    import hashlib

    entry = generators_for(k, 5)
    n_base, digest = GOLDEN[k]
    assert entry[0] == n_base
    assert hashlib.sha256(repr(entry).encode()).hexdigest() == digest


# ── GF(2) check off the matrix, at sizes the brute-force check cannot reach ─

def _bitmasks(d):
    """Each factor's column over the corners as an int: bit i set when run i
    is at -1. Multiplying +/-1 columns is XOR of these masks, and a defining
    word (a product that is constant, +1 OR -1) is an XOR equal to 0 or ALL."""
    cols = []
    for j in range(len(d.factor_ids)):
        m = 0
        for i, p in enumerate(d.corners):
            if p.coded[j] < 0:
                m |= 1 << i
        cols.append(m)
    return cols, (1 << len(d.corners)) - 1


def _shortest_word_gf2(cols, full, upto):
    """Length of the shortest defining word, checked up to ``upto`` <= 4 by
    hashing: length 1 is a constant column; 2, two equal (or complementary)
    columns; 3, a column equal to the XOR of two others; 4, two pairs with
    the same XOR. ``upto + 1`` means none that short."""
    norm = lambda v: min(v, v ^ full)  # noqa: E731 -- a word's sign is irrelevant
    singles = [norm(c) for c in cols]
    if 0 in singles:
        return 1
    if upto >= 2 and len(set(singles)) < len(singles):
        return 2
    if upto < 3:
        return upto + 1
    single_set = set(singles)
    pairs: set[int] = set()
    for i, j in itertools.combinations(range(len(cols)), 2):
        v = norm(cols[i] ^ cols[j])
        if v in single_set:
            return 3
        if upto >= 4:
            if v in pairs:
                return 4
            pairs.add(v)
    return upto + 1


@pytest.mark.parametrize("k", [25, 31, 40, 47, 64])
def test_resolution_five_holds_on_the_matrix_at_many_knobs(k):
    """B4: no defining word of length <= 4, read off the generated matrix."""
    cols, full = _bitmasks(fractional_factorial(_ids(k), 5))
    assert _shortest_word_gf2(cols, full, 4) >= 5


@pytest.mark.parametrize("res", [3, 4])
@pytest.mark.parametrize("k", [9, 17, 33, 64, 65, 100, 128])
def test_resolutions_three_and_four_hold_on_the_matrix_to_128_knobs(k, res):
    cols, full = _bitmasks(fractional_factorial(_ids(k), res))
    assert _shortest_word_gf2(cols, full, res - 1) >= res


def test_the_gf2_checker_has_teeth():
    """A planted word of each length 1..4 is found (columns over 4 runs)."""
    a, b, c = 0b0011, 0b0101, 0b1001
    full = 0b1111
    assert _shortest_word_gf2([a, 0], full, 4) == 1
    assert _shortest_word_gf2([a, a ^ full], full, 4) == 2
    assert _shortest_word_gf2([a, b, a ^ b], full, 4) == 3
    # a length-4 word with sign -1 (the four columns XOR to ALL), over 8 runs
    assert _shortest_word_gf2([a, b, c, a ^ b ^ c ^ 0xFF], 0xFF, 4) == 4
    assert _shortest_word_gf2([a, b, c], 0xFF, 4) == 5


# ── what Nous calls "smallest known" (A3) ────────────────────────────────────

def test_smallest_known_never_exceeds_the_full_factorial():
    """2 and 3 factors at resolution V: the full factorial (4, 8 runs) is the
    smallest design; the old ``_runs_lower_bound`` reported 16 for both."""
    from orchestrator.optimize.design import _runs_lower_bound

    assert D._smallest_known_runs(2, 5) == 4 and D._smallest_known_runs(3, 5) == 8
    # The deprecated alias (kept for one release) gives the same, clamped value.
    assert _runs_lower_bound(2, 5) == 4 and _runs_lower_bound(3, 5) == 8
    assert _runs_lower_bound(2, 3) == 4


def test_no_catalogue_bound_is_claimed_at_resolution_six_or_past_the_catalogue():
    """The resolution-V catalogue says nothing about VI+, nor past 65 factors:
    those are None, and the counting bound is a separate floor."""
    assert D._smallest_known_runs(8, 6) is None
    assert D._smallest_known_runs(70, 5) is None
    assert D._smallest_known_runs(65, 5) == 4096
    # Rao's bound at VI: 1 + 8 + 28 + C(7, 2) = 58 -> 64; 8 factors at VI in
    # fact need 128 (no binary [8, 2, 6] code exists), so a floor is a floor.
    assert D._counting_bound_runs(8, 6) == 64 and min_runs_for(8, 6) == 128
    assert D._counting_bound_runs(100, 5) == 8192


def test_a_resolution_six_preview_names_no_nonexistent_smaller_design():
    """It used to say "smallest known is 64" for 8 factors at resolution VI:
    no such design exists (128 is the minimum)."""
    _, note = _preview_screen_note(8, 6)
    assert "smallest known is 64" not in note
    assert "no catalogue bound for resolution VI+" in note
    assert "counting bound (a theoretical floor) is 64" in note


# ── a stated construction limit, instead of a stall (A8) ────────────────────

def test_resolution_five_past_the_construction_limit_is_refused_fast():
    """101 factors at resolution V is refused at once, naming resolution IV;
    100 is the stated limit. Higher resolutions have lower limits (the greedy
    search tracks sum C(k, j) over j <= R - 2); III and IV have none."""
    import time

    from orchestrator.optimize.design import _construct, max_constructible_factors

    assert max_constructible_factors(5) == 100
    assert max_constructible_factors(4) is None and max_constructible_factors(3) is None
    for k, res in [(101, 5), (max_constructible_factors(8) + 1, 8)]:
        _construct.cache_clear()
        t = time.process_time()
        with pytest.raises(ValueError, match="resolution 4"):
            min_runs_for(k, res)
        assert time.process_time() - t < 0.5
    assert min_runs_for(1000, 4) == 2048 and min_runs_for(1000, 3) == 1024


def test_the_textbook_table_is_unchanged():
    """Existing campaigns (k <= 8) must compile exactly the designs they did."""
    assert sorted(_GENERATORS) == sorted([
        (5, 5), (6, 5), (7, 5), (8, 5), (4, 4), (5, 4), (6, 4), (7, 4), (8, 4), (7, 3)])
    for key, entry in _GENERATORS.items():
        assert generators_for(*key) == entry


@pytest.mark.parametrize("k", [2, 3, 4])
def test_where_the_full_factorial_is_minimal_it_is_used(k):
    """What the screen stage and the refine composite actually BUILD for
    2-4 factors at resolution V: the full 2^k cube."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _build_design
    from orchestrator.optimize.synthetic import _numeric

    assert not is_tabulated(k, 5)
    assert min_runs_for(k, 5) == 2 ** k
    fs = parse_factors([_numeric(i) for i in _ids(k)])
    screen = _build_design(fs, {"screen": {"resolution": 5, "center_points": 0}}, "screen")
    assert screen.kind == "full"
    cube = sorted(p.coded for p in full_factorial(_ids(k)).points)
    assert sorted(p.coded for p in screen.corners) == cube
    assert sorted(p.coded for p in central_composite(_ids(k), center_points=0).corners) == cube


# ── the refine design: a small composite over a resolution-V cube ───────────

def _quadratic_model_matrix(d):
    X = np.array([p.coded for p in d.points])
    k = X.shape[1]
    cols = [np.ones(len(X))] + [X[:, i] for i in range(k)]
    cols += [X[:, i] * X[:, j] for i, j in itertools.combinations(range(k), 2)]
    cols += [X[:, i] ** 2 for i in range(k)]
    return np.column_stack(cols)


@pytest.mark.parametrize("k", [2, 3, 4, 5, 6, 8, 10, 12, 16])
def test_the_composite_design_estimates_a_full_quadratic(k):
    d = central_composite(_ids(k), center_points=4)
    M = _quadratic_model_matrix(d)
    p = 1 + k + k * (k - 1) // 2 + k
    assert np.linalg.matrix_rank(M) == p, "every quadratic term must be estimable"


@pytest.mark.parametrize("k", [2, 3, 4])
def test_a_small_composite_keeps_its_full_factorial_cube(k):
    """Unchanged for the refine stages existing campaigns run."""
    d = central_composite(_ids(k), center_points=4)
    assert len(d.corners) == 2 ** k
    axial = max(abs(c) for p in d.points if p.role == "axial" for c in p.coded)
    assert axial == pytest.approx((2 ** k) ** 0.25)


@pytest.mark.parametrize("k,cube", [(5, 16), (10, 128), (16, 256)])
def test_a_large_composite_uses_a_resolution_five_cube(k, cube):
    d = central_composite(_ids(k), center_points=4)
    assert len(d.corners) == cube < 2 ** k
    assert len(d.points) == cube + 2 * k + 4
    axial = max(abs(c) for p in d.points if p.role == "axial" for c in p.coded)
    assert axial == pytest.approx(cube ** 0.25), "rotatable for the cube it has"


# ── what the author sees: the design preview names the design and its cost ──

def _preview_screen_note(k, res):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview
    from orchestrator.optimize.synthetic import Surface, _numeric

    s = Surface(name="p", factors=tuple(_numeric(f"X{i:02d}") for i in range(k)),
                fn=lambda lv: 0.0)
    c = synthetic_campaign(s, design={"screen": {"resolution": res, "center_points": 4},
                                      "refine": {"kind": "central_composite",
                                                 "center_points": 4},
                                      "confirm": {"replicates": 3}})
    st = build_preview(c, noise_sd=1.0, mean=10.0, run_secs=[1.0]).stages[0]
    return st.runs, st.note


def test_the_preview_prices_a_sixteen_knob_screen_as_a_fraction():
    runs, note = _preview_screen_note(16, 5)
    assert runs == 256 + 4
    assert "resolution-V fraction" in note and "smallest known" in note
    assert "resolution-IV screen would take 32" in note


def test_the_preview_says_when_a_higher_resolution_is_free():
    runs, note = _preview_screen_note(16, 3)
    assert runs == 32 + 4 and "resolution IV costs the same here" in note


def test_the_preview_says_when_the_construction_is_above_the_known_minimum():
    _, note = _preview_screen_note(31, 5)
    assert "smallest known is 1024" in note


def test_resolution_five_at_a_hundred_knobs_is_within_two_doublings_and_cached():
    import time

    from orchestrator.optimize.design import _construct

    _construct.cache_clear()
    t = time.process_time()
    first = min_runs_for(100, 5)
    cold = time.process_time() - t
    t = time.process_time()
    assert min_runs_for(100, 5) == first
    assert time.process_time() - t < max(0.05, cold / 10), "the second ask is cached"
    assert first <= 4 * D._counting_bound_runs(100, 5)


# ── B7: the composite is estimable on the points that actually RAN ──────────

def test_the_composite_is_estimable_on_the_as_run_points(tmp_path):
    """Refine over five factors uses a 16-run resolution-V cube with axial
    points at alpha = 2, which the declared ranges CLAMP to +-1; two factors
    are log-scaled and every level snaps to an integer grid. Rebuild the full
    quadratic model matrix from design_matrix.json's levels via
    ``code_actual`` -- the coordinates the fit uses -- and require full rank."""
    import json
    import math
    from pathlib import Path

    from orchestrator.optimize.factors import code_actual, parse_factors
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.synthetic import Surface, _numeric

    def fac(fid, levels, log=False):
        f = _numeric(fid, levels=levels, grid=1)
        if log:
            f["scale"] = "log"
        return f

    def fn(lv):
        a, b = math.log2(lv["INT"] / 16.0), math.log2(lv["BUF"] / 4096.0)
        return (100 - 2 * a * a - 2 * b * b - 0.3 * (lv["P"] - 12) ** 2
                - 0.3 * (lv["Q"] - 11) ** 2 - 0.3 * (lv["R"] - 5) ** 2)

    decl = (fac("INT", (1, 8, 64), True), fac("BUF", (256, 2048, 16384), True),
            fac("P", (2, 4, 8, 16)), fac("Q", (2, 4, 8, 16)), fac("R", (2, 4, 8, 16)))
    res = run_synthetic_campaign(Surface(name="b7", noise_sd=0.1, fn=fn, factors=decl),
                                 seed=1, parent_dir=tmp_path)
    assert "refine" in res.path
    refine = [p for p in Path(res.work_dir).glob("runs/iter-*/design_matrix.json")
              if any(r["role"] == "axial" for r in json.loads(p.read_text())["rows"])]
    (dm,) = refine
    rows = json.loads(dm.read_text())["rows"]
    by_id = {f.id: f for f in parse_factors(list(decl))}
    ids = sorted(by_id)
    X = np.array([[code_actual(by_id[i], r["levels"][i]) for i in ids] for r in rows])
    assert sum(r["role"] == "corner" for r in rows) == 16
    axial = X[[r["role"] == "axial" for r in rows]]
    assert np.isclose(np.abs(axial).max(), 1.0), "alpha = 2 is clamped to the range"
    assert all(float(r["levels"][i]).is_integer() for r in rows for i in ids)
    k = len(ids)
    cols = [np.ones(len(X))] + [X[:, i] for i in range(k)]
    cols += [X[:, i] * X[:, j] for i, j in itertools.combinations(range(k), 2)]
    cols += [X[:, i] ** 2 for i in range(k)]
    M = np.column_stack(cols)
    assert np.linalg.matrix_rank(M) == 1 + 2 * k + k * (k - 1) // 2
