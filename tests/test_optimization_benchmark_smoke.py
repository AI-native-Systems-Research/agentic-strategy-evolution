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
