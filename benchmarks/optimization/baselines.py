"""Matched-budget baselines: random search, Latin hypercube, GP-BO (EI).

Every method gets exactly ``budget`` calls to ``Target.measure`` -- the number
of runs Nous spent on the same (surface, noise, seed) -- over the same
candidate axes the oracle's truth is enumerated on. A failed measurement
(``y is None``) still costs a run.

Each method returns TWO recommendations, and the benchmark scores both:

* ``best_observed`` -- the measured configuration with the best MEAN of its
  feasible replicates (a configuration counts as feasible only if every one of
  its replicates passed every constraint, the same sticky rule Nous applies);
* ``gp_mean`` -- the measured, feasible configuration with the best posterior
  mean under the GP of ``gp.py`` fitted to the method's own data. For GP-BO
  this is the standard noisy-BO recommendation; for RS and LHS it is the same
  post-hoc model applied to their data, so the comparison isolates the DESIGN
  (where to measure) from the ESTIMATOR (how to pick from what was measured).

Restricting ``gp_mean`` to measured points is deliberate: recommending an
unmeasured argmax of the mean is an extrapolation no method here can
certify, and it is not what a practitioner deploys.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

import numpy as np

from benchmarks.optimization import gp as G
from benchmarks.optimization.surfaces import Target, axes

#: Candidate pool size above which GP-BO optimizes EI over a random sample of
#: the grid plus every one-factor neighbour of the incumbent (local search)
#: instead of the whole grid.
POOL = 4096


class Coder:
    """Factor levels <-> [0, 1]^d. Log coding for ``scale: log``; one-hot for
    choices with more than two levels; 0/1 for two-level choices."""

    def __init__(self, surface):
        self.ax = axes(surface)

    def __call__(self, lv: dict) -> list[float]:
        out: list[float] = []
        for f, vals in self.ax:
            v = lv[f["id"]]
            if f["type"] == "numeric":
                lo, hi = float(min(vals)), float(max(vals))
                if f.get("scale") == "log" and lo > 0:
                    lo, hi, x = math.log(lo), math.log(hi), math.log(float(v))
                else:
                    x = float(v)
                out.append((x - lo) / (hi - lo) if hi > lo else 0.0)
            else:
                levels = list(f["levels"])
                if len(levels) <= 2:
                    out.append(float(levels.index(v)))
                else:
                    out += [1.0 if v == lv_ else 0.0 for lv_ in levels]
        return out

    @property
    def dim(self) -> int:
        return len(self({f["id"]: vals[0] for f, vals in self.ax}))


def _key(lv: dict) -> tuple:
    return tuple(sorted(lv.items()))


class Log:
    """Every measurement a method made, grouped by configuration."""

    def __init__(self):
        self.rows: list[tuple[dict, float | None, bool, dict]] = []

    def add(self, lv, y, feas, obs=None):
        self.rows.append((dict(lv), y, feas, dict(obs or {})))

    def grouped(self):
        g = defaultdict(lambda: {"lv": None, "ys": [], "feas": True, "n": 0})
        for lv, y, feas, _obs in self.rows:
            e = g[_key(lv)]
            e["lv"], e["n"] = lv, e["n"] + 1
            if y is None:
                continue
            e["ys"].append(y)
            e["feas"] = e["feas"] and feas
        return [e for e in g.values() if e["ys"]]


def best_observed(log: Log) -> dict | None:
    cands = [e for e in log.grouped() if e["feas"]]
    if not cands:
        return None
    return max(cands, key=lambda e: sum(e["ys"]) / len(e["ys"]))["lv"]


def gp_mean_recommendation(log: Log, coder: Coder, seed: int = 0) -> dict | None:
    pts = [(r[0], r[1]) for r in log.rows if r[1] is not None]
    feas = [e["lv"] for e in log.grouped() if e["feas"]]
    if len(pts) < 2 or not feas:
        return best_observed(log)
    X = np.array([coder(lv) for lv, _ in pts])
    y = np.array([v for _, v in pts])
    m = G.GP(restarts=2, seed=seed).fit(X, y)
    mu, _ = m.predict(np.array([coder(lv) for lv in feas]))
    return feas[int(np.argmax(mu))]


def _random_point(ax, rng):
    return {f["id"]: rng.choice(vals) for f, vals in ax}


def _lhs(ax, n, rng):
    """Latin hypercube over the candidate axes: per factor, ``n`` stratified
    uniforms mapped onto the axis, independently permuted."""
    cols = []
    for _f, vals in ax:
        strata = [(i + rng.random()) / n for i in range(n)]
        rng.shuffle(strata)
        cols.append([vals[min(len(vals) - 1, int(u * len(vals)))] for u in strata])
    return [{f["id"]: cols[j][i] for j, (f, _) in enumerate(ax)} for i in range(n)]


def _finish(log, coder, seed):
    return {"best_observed": best_observed(log),
            "gp_mean": gp_mean_recommendation(log, coder, seed)}


def random_search(surface, name, budget, rng):
    ax, tgt, log = axes(surface), Target(surface, name, rng), Log()
    for _ in range(budget):
        lv = _random_point(ax, rng)
        y, feas, _ = tgt.measure(lv)
        log.add(lv, y, feas)
    return _finish(log, Coder(surface), rng.randrange(2 ** 31)), tgt.n


def latin_hypercube(surface, name, budget, rng):
    ax, tgt, log = axes(surface), Target(surface, name, rng), Log()
    for lv in _lhs(ax, budget, rng):
        y, feas, _ = tgt.measure(lv)
        log.add(lv, y, feas)
    return _finish(log, Coder(surface), rng.randrange(2 ** 31)), tgt.n


def n_initial(dim: int, budget: int) -> int:
    """GP-BO initial design size: 2(d+1), at least 6, at most a third of the
    budget (a common default; Jones et al. use 10d, which would consume most
    of these small budgets before the model is ever used)."""
    return max(2, min(max(6, 2 * (dim + 1)), budget // 3))


def _pool(ax, rng, incumbent):
    total = 1
    for _, vals in ax:
        total *= len(vals)
    if total <= POOL:
        import itertools
        return [dict(zip([f["id"] for f, _ in ax], c))
                for c in itertools.product(*[vals for _, vals in ax])]
    pts = [_random_point(ax, rng) for _ in range(POOL)]
    if incumbent is not None:
        for f, vals in ax:
            for v in vals:
                if v != incumbent[f["id"]]:
                    pts.append({**incumbent, f["id"]: v})
    return pts


def refit_schedule(step: int, n: int) -> tuple[bool, int]:
    """``(optimize hyperparameters?, random restarts)`` at BO step ``step``
    with ``n`` observations. Every step while ``n <= 100`` (warm-started),
    every 10th step beyond; two extra random restarts on every 10th step.
    The posterior is always refactorized on all the data."""
    every = 1 if n <= 100 else 10
    return step % every == 0, (2 if step % 10 == 0 else 0)


def gp_bo(surface, name, budget, rng):
    """GP-BO with expected improvement (constrained EI when the surface has
    constraints: EI times the product of each constraint's GP probability of
    satisfaction, Gardner et al. 2014). Hyperparameters are MAP-refitted on
    ``refit_schedule``; the incumbent is the best posterior mean among the
    measured feasible configurations (the usual plug-in for noisy EI)."""
    ax, tgt, log, coder = axes(surface), Target(surface, name, rng), Log(), Coder(surface)
    cons = tgt.constraints
    npseed = rng.randrange(2 ** 31)
    for lv in _lhs(ax, n_initial(coder.dim, budget), rng):
        y, feas, obs = tgt.measure(lv)
        log.add(lv, y, feas, obs)
    model, cmodels, step = G.GP(restarts=2, seed=npseed), {}, 0
    while tgt.n < budget:
        rows = [r for r in log.rows if r[1] is not None]
        if len(rows) < 2:
            lv = _random_point(ax, rng)
        else:
            X = np.array([coder(r[0]) for r in rows])
            y = np.array([r[1] for r in rows])
            refit, restarts = refit_schedule(step, len(rows))
            model.fit(X, y, theta0=model.theta, optimize=refit, restarts=restarts)
            feas_meas = [e["lv"] for e in log.grouped() if e["feas"]]
            inc = None
            if feas_meas:
                mu_m, _ = model.predict(np.array([coder(v) for v in feas_meas]))
                inc_i = int(np.argmax(mu_m))
                inc, inc_val = feas_meas[inc_i], float(mu_m[inc_i])
            pool = _pool(ax, rng, inc)
            P = np.array([coder(p) for p in pool])
            mu, sd = model.predict(P)
            pf = np.ones(len(pool))
            for c in cons:
                cy = np.array([r[3][c["metric"]] for r in rows])
                cm = cmodels.setdefault(c["metric"], G.GP(restarts=1, seed=npseed + 1))
                cm.fit(X, cy, theta0=cm.theta, optimize=refit, restarts=min(restarts, 1))
                cmu, csd = cm.predict(P)
                z = (float(c["value"]) - cmu) / np.maximum(csd, 1e-12)
                from scipy.stats import norm
                pf *= norm.cdf(z) if c["op"] in ("<=", "<") else norm.cdf(-z)
            acq = (G.expected_improvement(mu, sd, inc_val) * pf
                   if inc is not None else pf)
            lv = pool[int(np.argmax(acq))]
            step += 1
        y, feas, obs = tgt.measure(lv)
        log.add(lv, y, feas, obs)
    return _finish(log, coder, npseed), tgt.n


def gp_bo_crude(surface, name, budget, rng):
    """The stage-0 audit's GP-BO (``probe_q6.gpbo``), kept verbatim in spirit
    to reproduce its head-to-head: 6 uniform-random initial points, fixed
    RBF(lengthscale 0.3) + nugget 0.01, EI over the whole grid, recommend the
    best posterior mean among measured points. No constraint handling, no
    hyperparameter fitting."""
    import itertools
    ax, tgt, coder = axes(surface), Target(surface, name, rng), Coder(surface)
    grid = [dict(zip([f["id"] for f, _ in ax], c))
            for c in itertools.product(*[vals for _, vals in ax])]
    if len(grid) > 20000:
        grid = [_random_point(ax, rng) for _ in range(20000)]
    Gx = np.array([coder(g) for g in grid])
    idx = [rng.randrange(len(grid)) for _ in range(min(6, budget))]
    ys = []
    log = Log()
    for i in idx:
        y, feas, _ = tgt.measure(grid[i])
        log.add(grid[i], y, feas)
        ys.append(y)
    while tgt.n < budget:
        ok = [(i, v) for i, v in zip(idx, ys) if v is not None]
        X, y = Gx[[i for i, _ in ok]], np.array([v for _, v in ok])
        mu, sd = G.crude_posterior(X, y, Gx)
        best = mu[[i for i, _ in ok]].max()
        i = int(np.argmax(G.expected_improvement(mu, sd, best)))
        v, feas, _ = tgt.measure(grid[i])
        log.add(grid[i], v, feas)
        idx.append(i)
        ys.append(v)
    ok = [(i, v) for i, v in zip(idx, ys) if v is not None]
    mu, _ = G.crude_posterior(Gx[[i for i, _ in ok]], np.array([v for _, v in ok]),
                              Gx[[i for i, _ in ok]])
    rec = grid[ok[int(np.argmax(mu))][0]]
    return {"best_observed": best_observed(log), "gp_mean": rec}, tgt.n


METHODS = {
    "RS": random_search,
    "LHS": latin_hypercube,
    "GP-BO": gp_bo,
    "GP-BO-crude": gp_bo_crude,
}


def run_method(method: str, surface, name: str, budget: int, seed: int):
    rng = random.Random(f"{name}:{seed}:{method}")
    return METHODS[method](surface, name, budget, rng)
