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

import numpy as np

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
