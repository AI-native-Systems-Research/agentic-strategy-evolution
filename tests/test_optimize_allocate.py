"""WP-D D1: the recombination pool and its acquisition scores (allocate.py).

Behavioral: every test builds a fitted model from a known surface and checks
what the allocator returns -- ranked candidates, scores against independent
Monte Carlo, named declines -- never how it computed them.
"""
from __future__ import annotations

import itertools
import math
import random

import pytest

from orchestrator.optimize import allocate
from orchestrator.optimize.design import Design, DesignPoint
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.synthetic import _numeric

FACTORS = parse_factors([_numeric(f, levels=(2, 16)) for f in "ABC"])
IDS = ["A", "B", "C"]
LV = {-1.0: 2, 1.0: 16}


def _fit(fn, *, noise=0.02, seed=0, centres=4):
    """A first-order + 2fi fit of ``fn`` (a function of coded ±1 values) on a
    2^3 full factorial with replicated centres for pure error."""
    rng = random.Random(seed)
    pts = [DesignPoint(coded=tuple(float(v) for v in c))
           for c in itertools.product((-1, 1), repeat=3)]
    pts += [DesignPoint(coded=(0.0, 0.0, 0.0), role="center", replicate=i)
            for i in range(centres)]
    d = Design(points=tuple(pts), factor_ids=tuple(IDS))
    ys = [fn(*p.coded) + rng.gauss(0.0, noise) for p in pts]
    return fit_effects(d, ys, factor_ids=IDS)


def _lv(a, b, c):
    return {"A": LV[a], "B": LV[b], "C": LV[c]}


# ── D4 oracle: recombination finds a front point no measured point had ──────


def test_recombination_finds_a_front_point_no_measured_point_had():
    """f1 = 2A + B and f2 = 2C + B. The measured front is p1 = (A+, B-, C-) and
    p2 = (A-, B+, C+); each wins one objective. The point that dominates both,
    (A+, B+, C+), takes A from p1 and B and C from p2. Neither measured point
    has it. The allocator must put it in the pool and rank it first by EHVI."""
    f1 = _fit(lambda a, b, c: 10 + 2 * a + b, seed=1)
    f2 = _fit(lambda a, b, c: 10 + 2 * c + b, seed=2)
    p1, p2 = _lv(1, -1, -1), _lv(-1, 1, 1)
    measured = [{"levels": p1, "mean": {"f1": 11.0, "f2": 7.0}},
                {"levels": p2, "mean": {"f1": 9.0, "f2": 13.0}}]
    out = allocate.allocate(
        front_points=[p1, p2], preferred=p1,
        fits={"f1": f1, "f2": f2},
        objectives=[{"metric": "f1", "direction": "maximize"},
                    {"metric": "f2", "direction": "maximize"}],
        factors=FACTORS, fitted_ids=IDS, held_fixed={}, measured=measured,
        model_adequate=True)
    assert out.declined is None
    assert out.ranked[0]["levels"] == _lv(1, 1, 1)
    assert out.ranked[0]["source"] == "front_recombination"
    assert all(r["levels"] not in (p1, p2) for r in out.ranked)
    assert out.method["ehvi_method"] == "exact_2d_strip_decomposition"
    assert out.method["pool"]["product_size"] == 8
    assert out.ranked[0]["rationale"]


def test_single_objective_recombination_ranks_the_unmeasured_combination_first():
    """f = A + B. The finalists (A+, B-) and (A-, B+) tie. The recombination
    (A+, B+) is better than both, and KG per run ranks it first."""
    fit = _fit(lambda a, b, c: 5 + a + b, seed=3)
    p1, p2 = _lv(1, -1, -1), _lv(-1, 1, -1)
    out = allocate.allocate(
        front_points=[p1, p2], preferred=p1, fits={"m": fit},
        objectives=[{"metric": "m", "direction": "maximize"}],
        factors=FACTORS, fitted_ids=IDS, held_fixed={},
        measured=[{"levels": p1, "mean": {"m": 5.0}}, {"levels": p2, "mean": {"m": 5.0}}],
        model_adequate=True)
    assert out.declined is None
    assert out.ranked[0]["levels"] == _lv(1, 1, -1)
    assert out.ranked[0]["kg"] > 0 and out.ranked[0]["ei"] > 0
    assert out.method["score"] == "knowledge_gradient_per_run"


def test_a_minimised_objective_ranks_by_its_own_direction():
    fit = _fit(lambda a, b, c: 5 + a + b, seed=4)
    p1, p2 = _lv(1, -1, -1), _lv(-1, 1, -1)
    out = allocate.allocate(
        front_points=[p1, p2], preferred=p1, fits={"m": fit},
        objectives=[{"metric": "m", "direction": "minimize"}],
        factors=FACTORS, fitted_ids=IDS, held_fixed={},
        measured=[{"levels": p1, "mean": {"m": 5.0}}, {"levels": p2, "mean": {"m": 5.0}}],
        model_adequate=True)
    assert out.ranked[0]["levels"] == _lv(-1, -1, -1)


# ── D4 oracle: the allocator declines when the model is inadequate ──────────


@pytest.mark.parametrize("verdict,reason", [(False, "model_inadequate"),
                                            (None, "model_adequacy_unknown"),
                                            ("true", "model_adequacy_unknown")])
def test_allocation_declines_unless_the_model_is_adequate(verdict, reason):
    fit = _fit(lambda a, b, c: 5 + a + b)
    out = allocate.allocate(
        front_points=[_lv(1, -1, -1), _lv(-1, 1, -1)], preferred=_lv(1, -1, -1),
        fits={"m": fit}, objectives=[{"metric": "m", "direction": "maximize"}],
        factors=FACTORS, fitted_ids=IDS, held_fixed={}, measured=[],
        model_adequate=verdict)
    assert out.declined == reason and out.ranked == []
    assert out.detail
    assert reason in allocate.DECLINE_REASONS


def test_no_pure_error_and_too_few_df_are_named_declines():
    no_pe = _fit(lambda a, b, c: 5 + a, centres=0)
    out = allocate.score([{"levels": _lv(1, 1, 1)}], fits={"m": no_pe},
                         objectives=[{"metric": "m", "direction": "maximize"}],
                         factors=FACTORS, fitted_ids=IDS, held_fixed={}, measured=[],
                         model_adequate=True)
    assert out.declined == "no_pure_error"
    one_df = _fit(lambda a, b, c: 5 + a, centres=2)
    out = allocate.score([{"levels": _lv(1, 1, 1)}], fits={"m": one_df},
                         objectives=[{"metric": "m", "direction": "maximize"}],
                         factors=FACTORS, fitted_ids=IDS, held_fixed={}, measured=[],
                         model_adequate=True)
    assert out.declined == "predictive_df_too_small"
    out = allocate.score([{"levels": _lv(1, 1, 1)}], fits={"m": None},
                         objectives=[{"metric": "m", "direction": "maximize"}],
                         factors=FACTORS, fitted_ids=IDS, held_fixed={}, measured=[],
                         model_adequate=True)
    assert out.declined == "no_fit"


def test_a_pool_larger_than_the_cap_declines_instead_of_truncating():
    pts = [{"A": a, "B": b} for a, b in zip(range(10), range(10))]
    assert allocate.pool_size(pts) == 100
    pool, rec = allocate.recombination_pool(pts, pts[0], cap=50)
    assert pool == [] and rec["declined"] == "pool_too_large" and rec["product_size"] == 100
    fit = _fit(lambda a, b, c: a)
    out = allocate.allocate(front_points=pts, preferred=pts[0], fits={"m": fit},
                            objectives=[{"metric": "m", "direction": "maximize"}],
                            factors=FACTORS, fitted_ids=IDS, held_fixed={},
                            measured=[], model_adequate=True, cap=50)
    assert out.declined == "pool_too_large"


def test_a_pool_with_only_unpredictable_points_is_an_empty_pool_decline():
    fit = _fit(lambda a, b, c: a)
    out = allocate.score([{"levels": {"A": 2, "B": 2, "C": 99}, "source": "x"}],
                         fits={"m": fit}, objectives=[{"metric": "m", "direction": "maximize"}],
                         factors=FACTORS, fitted_ids=IDS, held_fixed={}, measured=[],
                         model_adequate=True)
    assert out.declined == "empty_pool"
    assert out.unscored and "unpredictable" in out.unscored[0]["reason"]


def test_a_held_factor_at_another_level_is_unscored_not_extrapolated():
    fit = _fit(lambda a, b, c: a)
    out = allocate.score([{"levels": {**_lv(1, 1, 1), "D": "on"}},
                          {"levels": {**_lv(-1, 1, 1), "D": "off"}}],
                         fits={"m": fit}, objectives=[{"metric": "m", "direction": "maximize"}],
                         factors=FACTORS, fitted_ids=IDS, held_fixed={"D": "off"},
                         measured=[{"levels": {**_lv(-1, -1, -1), "D": "off"}}],
                         model_adequate=True)
    assert [r["levels"]["D"] for r in out.ranked] == ["off"]
    assert "held factor D" in out.unscored[0]["reason"]


# ── the scores against independent Monte Carlo ──────────────────────────────


def test_expected_improvement_matches_monte_carlo_under_the_t():
    rng = random.Random(7)
    m, s, tau, nu = 1.0, 0.5, 1.3, 5.0
    n = 200_000
    tot = 0.0
    for _ in range(n):
        t = rng.gauss(0, 1) / math.sqrt(rng.gammavariate(nu / 2, 2) / nu)
        tot += max(m + s * t - tau, 0.0)
    assert allocate.expected_improvement(m, s, tau, nu) == pytest.approx(tot / n, rel=0.02)


def test_exact_2d_ehvi_matches_monte_carlo():
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(3)
    front = [[0.2, 0.9], [0.5, 0.6], [0.8, 0.3]]
    m, s, nu = [0.6, 0.7], [0.15, 0.2], [4.0, 6.0]
    exact = allocate.ehvi_2d(m, s, nu, front)
    n = 200_000
    y1 = m[0] + s[0] * rng.standard_t(nu[0], n)
    y2 = m[1] + s[1] * rng.standard_t(nu[1], n)

    def hv(points):
        pts = sorted((p for p in points if p[0] > 0 and p[1] > 0), key=lambda p: -p[0])
        tot, best = 0.0, 0.0
        for x, y in pts:
            if y > best:
                tot += x * (y - best)
                best = y
        return tot

    base = hv(front)
    # the vectorised added area of a point (y1, y2) over the step front
    add = np.zeros(n)
    srt = sorted(front)
    edges = [0.0] + [p[0] for p in srt]
    heights = [p[1] for p in srt] + [0.0]
    for lo, hi, h in zip(edges, edges[1:] + [np.inf], heights):
        w = np.clip(np.minimum(y1, hi) - lo, 0, None)
        add += w * np.clip(y2 - h, 0, None)
    assert base == pytest.approx(hv(front))
    assert exact == pytest.approx(float(add.mean()), rel=0.02)


def test_knowledge_gradient_matches_monte_carlo():
    """KG of a finite decision set: E[max(a + b Z)] - max(a)."""
    rng = random.Random(11)
    a = [0.0, 0.3, -0.2, 0.25]
    b = [0.5, -0.1, 0.9, 0.2]
    n = 300_000
    tot = 0.0
    for _ in range(n):
        z = rng.gauss(0, 1)
        tot += max(x + y * z for x, y in zip(a, b))
    assert allocate._kg_lines(a, b) == pytest.approx(tot / n - max(a), abs=2e-3)


def test_three_objective_ehvi_is_seeded_and_states_its_sample():
    fits = {k: _fit(fn, seed=i) for i, (k, fn) in enumerate({
        "f1": lambda a, b, c: 10 + a, "f2": lambda a, b, c: 10 + b,
        "f3": lambda a, b, c: 10 + c}.items())}
    pts = [_lv(1, -1, -1), _lv(-1, 1, -1), _lv(-1, -1, 1)]
    kw = dict(front_points=pts, preferred=pts[0], fits=fits,
              objectives=[{"metric": m, "direction": "maximize"} for m in ("f1", "f2", "f3")],
              factors=FACTORS, fitted_ids=IDS, held_fixed={},
              measured=[{"levels": p, "mean": {}} for p in pts], model_adequate=True)
    a, b = allocate.allocate(**kw), allocate.allocate(**kw)
    assert a.as_dict() == b.as_dict()
    assert a.method["ehvi_method"] == (f"monte_carlo(n={allocate.MC_SAMPLES},"
                                       f"seed={allocate.MC_SEED},common_random_numbers)")
    assert a.ranked[0]["levels"] == _lv(1, 1, 1)


def test_bo_and_predicted_front_entries_join_the_pool_with_their_source():
    fit = _fit(lambda a, b, c: a + b + c)
    p1 = _lv(1, -1, -1)
    out = allocate.allocate(
        front_points=[p1], preferred=p1, fits={"m": fit},
        objectives=[{"metric": "m", "direction": "maximize"}],
        factors=FACTORS, fitted_ids=IDS, held_fixed={},
        measured=[{"levels": p1, "mean": {"m": 1.0}}], model_adequate=True,
        predicted_front=[{"levels": _lv(1, 1, -1)}],
        proposals=[{"levels": _lv(1, 1, 1), "provenance": {"sampler": "fake"}}])
    by = {tuple(sorted(r["levels"].items())): r["source"] for r in out.ranked}
    assert by[tuple(sorted(_lv(1, 1, 1).items()))] == "bo_proposal"
    assert by[tuple(sorted(_lv(1, 1, -1).items()))] == "predicted_front"
    assert out.method["pool_sources"] == {"front_recombination": 0,
                                          "predicted_front": 1, "bo_proposal": 1}


def test_single_objective_without_a_measured_incumbent_declines():
    fit = _fit(lambda a, b, c: a)
    out = allocate.score([{"levels": _lv(1, 1, 1)}], fits={"m": fit},
                         objectives=[{"metric": "m", "direction": "maximize"}],
                         factors=FACTORS, fitted_ids=IDS, held_fixed={}, measured=[],
                         model_adequate=True)
    assert out.declined == "no_measured_incumbent"
