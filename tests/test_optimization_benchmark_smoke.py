"""Smoke test of the matched-budget benchmark (benchmarks/optimization/).

The benchmark itself is NOT part of the default run (it takes tens of CPU
minutes); this checks, in a few seconds, that the harness still runs end to
end and that its contract holds: every baseline spends exactly Nous's budget,
regret is judged on the noiseless surface, and the GP baseline is a real
fitted GP. Zero LLM, zero subprocess.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import json

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.optimization import gp as G  # noqa: E402
from benchmarks.optimization import surfaces as S  # noqa: E402
from benchmarks.optimization.run import run_baseline, run_nous, summarize  # noqa: E402


def test_gp_gradient_matches_finite_differences():
    rs = np.random.RandomState(0)
    X = rs.rand(12, 3)
    y = np.sin(3 * X[:, 0]) + X[:, 1] ** 2
    yn = (y - y.mean()) / y.std()
    m = G.GP()
    th = np.array([-1.0, -0.5, 0.3, 0.2, -2.0])
    _, g = m._neg_log_post(th, X, yn)
    h = 1e-6
    num = [(m._neg_log_post(th + e, X, yn)[0] - m._neg_log_post(th - e, X, yn)[0]) / (2 * h)
           for e in np.eye(len(th)) * h]
    assert np.allclose(g, num, rtol=1e-4, atol=1e-6)


def test_fitted_gp_recovers_a_smooth_function_and_its_noise_level():
    rs = np.random.RandomState(1)
    X = rs.rand(40, 2)
    f = lambda Z: np.sin(4 * Z[:, 0]) + np.cos(3 * Z[:, 1])  # noqa: E731
    y = f(X) + 0.05 * rs.randn(40)
    m = G.GP(restarts=2, seed=0).fit(X, y)
    Xs = rs.rand(200, 2)
    mu, sd = m.predict(Xs)
    assert np.sqrt(np.mean((mu - f(Xs)) ** 2)) < 0.1
    # Hyperparameters were fitted, not fixed: the noise sd lands near 0.05.
    assert 0.01 < math.sqrt(m.noise) * m.ys < 0.15


def test_every_method_spends_exactly_nous_budget_and_is_judged_in_truth(tmp_path):
    nous = run_nous("bowl", 1.0, 1, str(tmp_path))
    assert "error" not in nous, nous
    assert nous["budget"] > 0 and nous["status"] == "ok"
    rows = [run_baseline(m, "bowl", 1.0, 1, nous["budget"])
            for m in ("RS", "LHS", "GP-BO", "GP-BO-crude")]
    tr = S.truth(S.get("bowl"))
    for r in rows:
        assert r["used"] == nous["budget"], r
        for rule in ("best_observed", "gp_mean"):
            assert 0.0 <= r[f"regret_{rule}"] <= tr["best"] - tr["worst"] + 1e-9, r
    summary = summarize([nous], rows, ["RS", "LHS", "GP-BO", "GP-BO-crude"])
    w, t, l = summary["head_to_head"]["GP-BO"]["gp_mean"]["exact"]
    assert w + t + l == 1


def test_an_infeasible_recommendation_is_charged_the_worst_admissible_regret():
    s = S.get("sla")
    tr = S.truth(s)
    bad = {"A": 16, "B": 16}               # 2A + B = 48 > 40: outside X_valid
    assert s.invalid(bad)
    reg, status = S.true_regret(s, bad, tr)
    assert status == "infeasible" and reg == tr["best"] - tr["worst"]
    assert S.true_regret(s, None, tr)[1] == "none"


# ─── review B1-B4 ────────────────────────────────────────────────────────────


def _count_failed(monkeypatch):
    from benchmarks.optimization import surfaces as S_

    counts = {"failed": 0, "total": 0}
    orig = S_.Target.measure

    def measure(self, lv):
        y, feas, obs = orig(self, lv)
        counts["total"] += 1
        counts["failed"] += y is None
        return y, feas, obs
    monkeypatch.setattr(S_.Target, "measure", measure)
    return counts


def test_gp_bo_does_not_spend_its_budget_re_measuring_a_failing_configuration(monkeypatch):
    from benchmarks.optimization.baselines import run_method

    counts = _count_failed(monkeypatch)
    for seed in (1, 2):
        run_method("GP-BO", S.get("fails_at_one_level"), "fails_at_one_level", 40, seed)
    # Before the fix 31 of 40 runs went to one failing configuration.
    assert counts["failed"] <= 0.25 * counts["total"], counts


def test_an_errored_nous_campaign_is_charged_not_dropped(tmp_path, monkeypatch):
    from orchestrator.optimize import harness

    def boom(*a, **k):
        raise TypeError("driver regression")
    monkeypatch.setattr(harness, "run_synthetic_campaign", boom)
    r = run_nous("bowl", 1.0, 1, str(tmp_path))
    tr = S.truth(S.get("bowl"))
    assert r["status"] == "error" and r["regret"] == tr["best"] - tr["worst"]
    summary = summarize([r], [], [])
    assert summary["rows"] and summary["rows"][0]["nous_regret"] == r["regret"]


def test_rows_record_the_code_they_came_from_and_the_header_hides_the_cache_path(tmp_path):
    from benchmarks.optimization.run import _meta

    r = run_baseline("RS", "bowl", 1.0, 1, 10)
    assert r["code"]
    meta = _meta(["--cache-dir", "/secret/path", "--seeds", "1"], [1], [1.0])
    assert "/secret/path" not in meta["argv"] and "<cache-dir>" in meta["argv"]


def test_chunked_predictions_agree_with_unchunked():
    rs = np.random.RandomState(3)
    X, Xs = rs.rand(30, 3), rs.rand(500, 3)
    y = X.sum(1) + 0.01 * rs.randn(30)
    m = G.GP(restarts=0, seed=0).fit(X, y)
    a, b = m.predict(Xs, chunk=7), m.predict(Xs, chunk=10_000)
    assert np.allclose(a[0], b[0]) and np.allclose(a[1], b[1])
    c, d = G.crude_posterior(X, y, Xs, chunk=7), G.crude_posterior(X, y, Xs, chunk=10_000)
    assert np.allclose(c[0], d[0]) and np.allclose(c[1], d[1])


def test_a_baselines_regret_matches_the_hand_computed_noiseless_value():
    from benchmarks.optimization.baselines import run_method

    s = S.get("bowl")
    recs, _ = run_method("RS", s, "bowl", 12, 5)
    rec = recs["best_observed"]
    a, b = float(rec["A"]), float(rec["B"])
    by_hand = 20.0 - (20.0 - 0.05 * (a - 9) ** 2 - 0.05 * (b - 11) ** 2)
    assert S.true_regret(s, rec, S.truth(s)) == (pytest.approx(by_hand), "ok")
    assert run_baseline("RS", "bowl", 1.0, 5, 12)["regret_best_observed"] == pytest.approx(by_hand)


# ─── round 2, C6 / C7 ────────────────────────────────────────────────────────


def test_a_seed_that_crashed_before_measuring_still_gets_baselines():
    from benchmarks.optimization.run import _budget_for

    crashed = {"surface": "bowl", "mult": 1.0, "seed": 1, "budget": 0, "regret": 1.0,
               "error": "TypeError: x"}
    ok = {"surface": "bowl", "mult": 1.0, "seed": 2, "budget": 29, "regret": 0.0}
    assert _budget_for(crashed, [crashed, ok]) == 29


def test_legacy_error_rows_without_a_regret_are_not_listed_as_charged():
    legacy = {"surface": "bowl", "mult": 1.0, "seed": 1, "error": "old"}
    charged = {"surface": "bowl", "mult": 1.0, "seed": 2, "error": "new", "budget": 3,
               "regret": 1.0, "status": "error", "certified": False, "false_cert": False,
               "wall_s": 0, "cpu_s": 0}
    s = summarize([legacy, charged], [], [])
    assert [e["seed"] for e in s["errors"]] == [2]


def test_a_cached_row_from_other_code_is_not_reused(tmp_path):
    from benchmarks.optimization.run import run_suite

    cache = tmp_path / "cache"
    cache.mkdir()
    stale = {"_key": "deadbeefdeadbeef|bowl|1.0|1", "surface": "bowl", "mult": 1.0,
             "seed": 1, "budget": 29, "regret": 999.0, "status": "ok",
             "certified": False, "false_cert": False, "wall_s": 0, "cpu_s": 0}
    (cache / "nous.jsonl").write_text(json.dumps(stale) + "\n")
    nous, base = run_suite(["bowl"], [1.0], [1], ["RS"], 1, str(tmp_path), cache)
    assert nous[0]["regret"] != 999.0
    assert base and base[0]["dead_fallbacks"] == 0


# ─── round 3, E1/E2 ──────────────────────────────────────────────────────────


def test_a_cell_where_every_seed_crashed_still_gets_baselines_at_the_planned_budget():
    from benchmarks.optimization.run import _budget_for, planned_budget

    crashed = {"surface": "bowl", "mult": 1.0, "seed": 1, "budget": 0, "regret": 1.0,
               "error": "TypeError: x"}
    planned = planned_budget("bowl", 1.0)
    assert planned > 0
    assert _budget_for(crashed, [crashed]) == planned


def test_uncompared_cells_and_dead_fallbacks_are_surfaced():
    r = {"surface": "bowl", "mult": 1.0, "seed": 1, "budget": 0, "regret": 1.0,
         "status": "error", "error": "x", "certified": False, "false_cert": False,
         "wall_s": 0, "cpu_s": 0}
    s = summarize([r], [], [])
    assert s["uncompared_cells"] == [("bowl", 1.0)] and s["dead_fallbacks"] == 0


def test_the_nous_cache_key_includes_the_benchmark_digest(tmp_path, monkeypatch):
    from benchmarks.optimization import run as R

    cache = tmp_path / "cache"
    cache.mkdir()
    nd = R._nous_digest()
    stale = {"_key": f"{nd}|bowl|1.0|1", "surface": "bowl", "mult": 1.0, "seed": 1,
             "budget": 29, "regret": 999.0, "status": "ok", "certified": False,
             "false_cert": False, "wall_s": 0, "cpu_s": 0}
    (cache / "nous.jsonl").write_text(json.dumps(stale) + "\n")
    nous, _ = R.run_suite(["bowl"], [1.0], [1], ["RS"], 1, str(tmp_path), cache)
    assert nous[0]["regret"] != 999.0          # a key without the bench digest is not reused


# ─── P7 (#321 H2, #320 D4): anytime curves, intervals, MO, renderer ─────────


def test_bootstrap_ci_is_seeded_and_brackets_the_mean():
    from benchmarks.optimization import stats as ST

    v = [0.0, 1.0, 2.0, 3.0, 4.0]
    a, b = ST.bootstrap_mean_ci(v), ST.bootstrap_mean_ci(v)
    assert a == b                                  # same seed, same interval
    est, lo, hi = a
    assert est == 2.0 and lo < 2.0 < hi and 0.0 <= lo and hi <= 4.0
    assert ST.bootstrap_mean_ci(v, seed=1) != a or True  # another seed is allowed to differ
    assert ST.bootstrap_mean_ci([0.5, 0.5]) == (0.5, 0.5, 0.5)
    assert all(x != x for x in ST.bootstrap_mean_ci([]))


def test_t_interval_matches_the_hand_computed_value():
    from benchmarks.optimization import stats as ST

    # mean 2, sd sqrt(2.5), n 5, t_{0.975,4} = 2.7764451052
    est, lo, hi = ST.t_mean_ci([0, 1, 2, 3, 4])
    half = 2.7764451052 * math.sqrt(2.5) / math.sqrt(5)
    assert est == 2.0 and lo == pytest.approx(2 - half, abs=1e-6)
    assert hi == pytest.approx(2 + half, abs=1e-6)


def test_wilson_interval_matches_the_hand_computed_value():
    from benchmarks.optimization import stats as ST

    # k = 5 of n = 10 at z = 1.959964: centre 0.5, half-width 0.2933
    p, lo, hi = ST.wilson_ci(5, 10)
    assert p == 0.5 and lo == pytest.approx(0.2366, abs=1e-4)
    assert hi == pytest.approx(0.7634, abs=1e-4)
    p, lo, hi = ST.wilson_ci(0, 8)
    assert p == 0.0 and lo == 0.0 and hi == pytest.approx(0.3244, abs=1e-4)


def test_anytime_counts_and_nous_best_so_far_on_a_fixed_row_list():
    from benchmarks.optimization.run import FRACTIONS, anytime_counts, best_so_far, nous_anytime

    assert anytime_counts(10) == [1, 2, 4, 6, 8, 10] and len(FRACTIONS) == 6
    assert anytime_counts(0) == []
    s = S.get("bowl")
    tr = S.truth(s)

    def row(a, b, m, status="complete"):
        return {"levels": {"A": a, "B": b}, "status": status, "response": {"m": m}}

    rows = [row(2, 2, 15.0), row(16, 16, 25.0, "infeasible"), row(8, 10, 19.9),
            row(9, 11, 19.5), row(9, 11, 20.5), row(2, 2, 15.0), row(2, 2, 15.0),
            row(2, 2, 15.0), row(2, 2, 15.0), row(2, 2, 15.0)]
    # The infeasible row's configuration is struck even though it looks best.
    assert best_so_far(rows[:2]) == {"A": 2, "B": 2}
    # After 4 rows (9,11) has mean 19.5 < (8,10)'s 19.9; after 5 its mean is 20.0.
    assert best_so_far(rows[:4]) == {"A": 8, "B": 10}
    assert best_so_far(rows[:5]) == {"A": 9, "B": 11}
    curve = nous_anytime(rows, s, tr, len(rows))
    r22 = tr["best"] - s.fn({"A": 2, "B": 2})
    r810 = tr["best"] - s.fn({"A": 8, "B": 10})
    assert curve == pytest.approx([r22, r22, r810, 0.0, 0.0, 0.0])


def test_a_baselines_anytime_curve_ends_at_its_recorded_answer_and_never_rises_for_obs():
    r = run_baseline("RS", "bowl", 1.0, 3, 20)
    assert len(r["anytime"]) == 6 and r["anytime"][-1] == r["regret_best_observed"]
    g = run_baseline("GP-BO", "bowl", 1.0, 3, 20)
    assert len(g["anytime"]) == 6 and g["anytime"][-1] == g["regret_gp_mean"]


def test_family_primary_and_anytime_summary_on_a_tiny_fixed_input():
    from benchmarks.optimization.run import anytime_summary, family_primary

    nous = [{"surface": "bowl", "mult": 1.0, "seed": s, "regret": 0.0, "norm": 2.0,
             "anytime": [2.0, 1.0, 0.0, 0.0, 0.0, 0.0]} for s in (1, 2)]
    base = [{"surface": "bowl", "mult": 1.0, "seed": 1, "method": "RS", "norm": 2.0,
             "regret_best_observed": 1.0, "anytime": [2, 2, 2, 1, 1, 1]},
            {"surface": "bowl", "mult": 1.0, "seed": 2, "method": "RS", "norm": 2.0,
             "regret_best_observed": 0.0, "anytime": [2, 2, 2, 1, 1, 0]}]
    pr = family_primary(nous, base, ["RS"])["shipped"]["RS"]
    assert pr["seeds"] == 2 and pr["bootstrap"][0] == pytest.approx(-0.25)
    lo, hi = pr["bootstrap"][1:]
    assert lo == pytest.approx(-0.5) and hi == pytest.approx(0.0)
    cur = anytime_summary(nous, base, ["RS"])["shipped"]
    assert [p[0] for p in cur["Nous"]] == pytest.approx([1.0, 0.5, 0, 0, 0, 0])
    assert [p[0] for p in cur["RS"]] == pytest.approx([1, 1, 1, 0.5, 0.5, 0.25])


def test_hypervolume_regret_against_a_hand_computed_front():
    """pareto_convex: f1 = 10 + 4u_A + u_B, f2 = 14 - 4u_A^2 + u_B. With B at
    its top (u_B = 1) the front is the A-sweep. Frame: each objective over the
    valid grid, f1 in [10, 15], f2 in [10, 15] -> z = (f - 10) / 5."""
    from benchmarks.optimization import mo as MO
    from orchestrator.optimize.synthetic import PARETO_SURFACES

    s = PARETO_SURFACES["pareto_convex"]()
    t = MO.HVTruth(s)
    assert t.regret([]) == 1.0
    # One point, A = 2 (u_A = 0), B = 16: (f1, f2) = (11, 15) -> z = (0.2, 1.0),
    # HV = 0.2 * 1.0 against the reference (0, 0).
    one = t.regret([{"A": 2, "B": 16}])
    assert one == pytest.approx((t.true - 0.2) / t.true)
    # A = 16 (u_A = 1), B = 16: (15, 11) -> z (1.0, 0.2); with A=2 the union is
    # 0.2 + 0.2 - 0.04 = 0.36.
    two = t.regret([{"A": 2, "B": 16}, {"A": 16, "B": 16}])
    assert two == pytest.approx((t.true - 0.36) / t.true)
    # The whole true front scores 0.
    from orchestrator.optimize.synthetic import true_front
    assert t.regret([lv for lv, _ in true_front(s)]) == pytest.approx(0.0, abs=1e-12)


def test_measured_front_uses_means_and_strikes_infeasible_configurations():
    from benchmarks.optimization import mo as MO

    objs = ({"metric": "f1", "direction": "maximize"},
            {"metric": "f2", "direction": "minimize"})
    a, b, c = {"A": 1}, {"A": 2}, {"A": 3}
    rows = [(a, {"f1": 1.0, "f2": 1.0}, True), (b, {"f1": 2.0, "f2": 2.0}, True),
            (c, {"f1": 9.0, "f2": 0.0}, False),
            (b, {"f1": 0.0, "f2": 2.0}, True)]  # b's mean f1 is 1.0: dominated by a
    assert MO.measured_front(rows, objs) == [a]


def test_mo_baselines_spend_exactly_the_budget():
    from benchmarks.optimization import mo as MO
    from orchestrator.optimize.synthetic import PARETO_SURFACES

    s = PARETO_SURFACES["pareto_with_constraint"]()
    for m in MO.MO_METHODS:
        rows, used = MO.run_mo_method(m, s, "pareto_with_constraint", 14, 1)
        assert used == 14 and len(rows) == 14


def test_an_unavailable_arm_is_reported_not_raised(tmp_path, monkeypatch):
    from benchmarks.optimization import run as R
    from orchestrator.optimize import policy

    monkeypatch.delattr(policy, "ALLOCATE_ACCOUNTING", raising=False)
    r = R.run_nous("bowl", 1.0, 1, str(tmp_path), arm="nous+alloc")
    assert r["status"] == "unavailable" and "P6b" in r["unavailable"]
    ab = R.summarize_ablations([], [r])
    assert ab["nous+alloc"]["unavailable"]
    assert "Unavailable on this checkout" in R.render_ablations(ab)


def test_the_renderer_states_the_primary_intervals_and_false_certificates():
    from benchmarks.optimization import run as R

    nous = [{"surface": "bowl", "mult": 1.0, "seed": s, "budget": 10, "regret": 0.0,
             "norm": 2.0, "status": "ok", "certified": s == 1, "false_cert": False,
             "epsilon": 0.1, "wall_s": 0, "cpu_s": 0, "code": "n0",
             "anytime": [1, 1, 0, 0, 0, 0]} for s in (1, 2)]
    base = [{"surface": "bowl", "mult": 1.0, "seed": s, "method": "RS", "budget": 10,
             "norm": 2.0, "regret_best_observed": 0.5, "regret_gp_mean": 0.5,
             "cpu_s": 0, "code": "b0", "anytime": [2, 1, 1, 1, 0.5, 0.5]} for s in (1, 2)]
    summ = R.summarize(nous, base, ["RS"])
    meta = {"argv": "--x", "git_commit": "abc", "nous_version": "0", "seeds": [1, 2],
            "mults": [1.0]}
    md = R.render_markdown(summ, meta, ["RS"])
    assert "PRIMARY (pre-declared)" in md and "-0.2500" in md
    assert "nous: 1 certified of 2, **0 false**" in md
    assert "Wilson 95%" in md and "Anytime regret" in md and "10% N" in md
    assert "digest(s) n0" in md and "b0" in md


def test_the_mo_and_ablation_renderers_carry_certificates_and_digests():
    from benchmarks.optimization import run as R

    nous = [{"surface": "pareto_convex", "seed": s, "arm": "nous", "status": "ok",
             "budget": 20, "hv_regret": 0.1, "certified": True, "false_cert": False,
             "code": "n0", "anytime": [1, .5, .3, .2, .1, .1]} for s in (1, 2)]
    base = [{"surface": "pareto_convex", "seed": s, "method": m, "budget": 20,
             "hv_regret": 0.2, "anytime": [1, 1, .5, .4, .3, .2], "code": "b0"}
            for s in (1, 2) for m in R.MO_METHOD_NAMES]
    mo = R.summarize_mo(nous, base)
    md = R.render_mo(mo, {"argv": "--mo", "git_commit": "abc", "seeds": [1, 2],
                          "nous_digests": ["n0"], "bench_digests": ["b0"]})
    assert "nous: 2 certified of 2, **0 false**" in md and "2 / 0 / 0" in md
    assert "n0" in md and "b0" in md
    d = [{"surface": "drift", "mult": 1.0, "seed": 1, "regret": 0.0, "norm": 1.0,
          "budget": 17, "certified": True, "false_cert": False}]
    a = [{**d[0], "arm": "nous-order", "regret": 0.5, "certified": False}]
    ab = R.summarize_ablations(d, a)
    md2 = R.render_ablations(ab)
    assert "nous-order" in md2 and "0.5000" in md2 and "1/0" in md2 and "0/0" in md2


def test_the_drift_ablation_executes_in_design_order_and_restores_it():
    from benchmarks.optimization import run as R
    from orchestrator.optimize import matrix

    before = matrix.randomized_run_order(5, 3)
    with R._arm_context("nous-order"):
        assert matrix.randomized_run_order(5, 3) == [0, 1, 2, 3, 4]
    assert matrix.randomized_run_order(5, 3) == before


def test_mo_pooled_paired_differences_on_a_fixed_input():
    from benchmarks.optimization import run as R

    nous = [{"surface": "s", "seed": sd, "arm": a, "status": "ok", "budget": 10,
             "hv_regret": v} for sd in (1, 2)
            for a, v in (("nous", 0.2), ("nous+alloc", 0.1))]
    base = [{"surface": "s", "seed": sd, "method": "RS", "budget": 10, "hv_regret": 0.5}
            for sd in (1, 2)]
    pl = R.mo_pooled(nous, base, ["RS"])
    assert pl["arm_minus_default"]["nous+alloc"][0] == pytest.approx(-0.1)
    assert pl["default_minus_baseline"]["RS"][0] == pytest.approx(-0.3)
    assert pl["arm_mean"]["nous:runs"] == 10
