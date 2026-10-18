"""Multi-objective arm of the benchmark: hypervolume regret, the shared
multi-objective measurement model, and the baselines (RS, LHS, ParEGO).

SCORING. A method reports a set of configurations (its front). The front is
scored in TRUTH: hypervolume of the NOISELESS objective vectors of the
reported configurations that are truly valid (in ``X_valid``), against the
hypervolume of the true front (``synthetic.true_front``), both in
``harness.true_front_hypervolume``'s frame (each objective normalised by its
range over the valid grid; reference = the worst valid value of each).

    hv_regret = (HV(true front) - HV(reported, valid)) / HV(true front)

0 is a perfect front, 1 an empty or worthless one. A truly invalid reported
point contributes nothing (it cannot be deployed), so it is charged by
omission, never credited.

WHAT A BASELINE REPORTS. The non-dominated set, by mean observed objective
values, of the measured configurations every replicate of which passed every
constraint (the sticky feasibility rule of the single-objective arm).

PAREGO (Knowles 2006). Each step draws a weight vector uniformly from the
simplex, scalarises every measured row by the augmented Chebyshev function
``min_k(w_k u_k) + rho * sum_k(w_k u_k)`` (``u`` = the objectives normalised
to [0, 1] over the observed rows, larger better, ``rho = 0.05`` as in the
paper), fits the GP of ``gp.py`` to the scalarised values and measures the
pool point of maximal expected improvement (times each constraint GP's
probability of satisfaction, as GP-BO). The initial design and the pool are
GP-BO's. Nothing here is specific to any surface.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from benchmarks.optimization import gp as G
from benchmarks.optimization.baselines import (
    Coder,
    _failed_only,
    _key,
    _lhs,
    _pool,
    _random_point,
    n_initial,
    refit_schedule,
)
from benchmarks.optimization.surfaces import _ok, axes

RHO = 0.05


def _sign(o) -> float:
    return -1.0 if o["direction"] == "minimize" else 1.0


class MOTarget:
    """One method's copy of a multi-objective synthetic target: every
    objective with its own declared noise, constraints from the surface's own
    ``constraints`` / ``noisy_observables``, a run counter, and a failure
    (``fails_at`` / ``exception_at``) still costs a run."""

    def __init__(self, surface, rng):
        self.s, self.rng, self.n = surface, rng, 0
        self.constraints = list(surface.constraints or ())

    def measure(self, lv: dict):
        s, rng = self.s, self.rng
        self.n += 1
        if s.fails_at is not None and s.fails_at(lv):
            return None, False, {}
        if s.exception_at and all(lv.get(k) == v for k, v in s.exception_at.items()):
            return None, False, {}
        vals = {o["metric"]: float(o["fn"](lv)) + rng.gauss(0.0, float(o.get("noise_sd", 0.0)))
                for o in s.objectives}
        obs = dict(s.extra_observables(lv))
        if s.noisy_observables is not None:
            obs.update(s.noisy_observables(lv, rng))
        feas = all(_ok(float(obs[c["metric"]]), c["op"], float(c["value"]))
                   for c in self.constraints)
        return vals, feas, {c["metric"]: float(obs[c["metric"]]) for c in self.constraints}


def measured_front(rows, objectives) -> list[dict]:
    """``rows``: ``(levels, values|None, feasible)`` in measurement order. The
    non-dominated set of the always-feasible measured configurations, by mean
    observed objective values."""
    from orchestrator.optimize.pareto import nondominated_indices

    g = defaultdict(lambda: {"lv": None, "vals": [], "feas": True})
    for lv, vals, feas in rows:
        if vals is None:
            continue
        e = g[_key(lv)]
        e["lv"] = lv
        e["vals"].append(vals)
        e["feas"] = e["feas"] and bool(feas)
    cands = [e for e in g.values() if e["feas"] and e["vals"]]
    if not cands:
        return []
    vec = [[_sign(o) * (sum(v[o["metric"]] for v in e["vals"]) / len(e["vals"]))
            for o in objectives] for e in cands]
    return [cands[i]["lv"] for i in nondominated_indices(vec)]


class HVTruth:
    """The true front and its hypervolume over the RECOMMENDABLE lattice
    (``surfaces.iter_lattice``, P7 review H3) -- the domain every method
    shares. Frame as ``harness.true_front_hypervolume``: each objective
    normalised by its range over the valid lattice, reference = the worst
    valid value of each. Enumerated once per surface."""

    def __init__(self, surface):
        from orchestrator.optimize import pareto
        from orchestrator.optimize.synthetic import objective_values

        from benchmarks.optimization.surfaces import iter_lattice

        self.s = surface
        self._ov = objective_values
        self._hvf = pareto.hypervolume
        valid = [lv for lv in iter_lattice(surface)
                 if surface.invalid is None or not surface.invalid(lv)]
        objs = [pareto.Objective(o["metric"], o["direction"], {}) for o in surface.objectives]
        self.frame = pareto.make_frame(objs, [objective_values(surface, lv) for lv in valid], {})
        self.ref = [0.0] * len(objs)
        signs = [_sign(o) for o in surface.objectives]
        vec = [[sg * objective_values(surface, lv)[o["metric"]]
                for sg, o in zip(signs, surface.objectives)] for lv in valid]
        self.front = [valid[i] for i in pareto.nondominated_indices(vec)]
        self.true = self.hv(self.front)

    def hv(self, levels_list) -> float:
        pts = [self.frame.z(self._ov(self.s, lv)) for lv in levels_list]
        return self._hvf(pts, self.ref)[0] if pts else 0.0

    def regret(self, levels_list) -> float:
        valid = [lv for lv in levels_list
                 if self.s.invalid is None or not self.s.invalid(lv)]
        if not self.true > 0:
            return 0.0
        return (self.true - self.hv(valid)) / self.true


def anytime_hv(rows, surface, counts, truth: HVTruth | None = None) -> list[float]:
    """HV regret of the measured front after the first ``n`` rows, per ``n``."""
    truth = truth or HVTruth(surface)
    return [truth.regret(measured_front(rows[:n], surface.objectives)) for n in counts]


# ── baselines ───────────────────────────────────────────────────────────────
def _rs(surface, budget, rng):
    ax, tgt, rows = axes(surface), MOTarget(surface, rng), []
    for _ in range(budget):
        lv = _random_point(ax, rng)
        v, f, _ = tgt.measure(lv)
        rows.append((lv, v, f))
    return rows, tgt.n


def _lhs_mo(surface, budget, rng):
    ax, tgt, rows = axes(surface), MOTarget(surface, rng), []
    for lv in _lhs(ax, budget, rng):
        v, f, _ = tgt.measure(lv)
        rows.append((lv, v, f))
    return rows, tgt.n


def chebyshev(u: np.ndarray, w: np.ndarray, rho: float = RHO) -> np.ndarray:
    """Augmented Chebyshev scalarisation, larger is better (``u`` in [0,1])."""
    return (u * w).min(axis=1) + rho * (u * w).sum(axis=1)


def _parego(surface, budget, rng):
    from scipy.stats import norm

    ax, tgt, coder = axes(surface), MOTarget(surface, rng), Coder(surface)
    objs = surface.objectives
    rows, obs_rows = [], []
    npseed = rng.randrange(2 ** 31)
    for lv in _lhs(ax, n_initial(coder.dim, budget), rng):
        v, f, o = tgt.measure(lv)
        rows.append((lv, v, f))
        obs_rows.append(o)
    model, cmodels, step = G.GP(restarts=2, seed=npseed), {}, 0
    while tgt.n < budget:
        ok = [(r, o) for r, o in zip(rows, obs_rows) if r[1] is not None]
        if len(ok) < 2:
            lv = _random_point(ax, rng)
        else:
            X = np.array([coder(r[0]) for r, _ in ok])
            Y = np.array([[_sign(o_) * r[1][o_["metric"]] for o_ in objs] for r, _ in ok])
            lo, hi = Y.min(0), Y.max(0)
            U = (Y - lo) / np.where(hi > lo, hi - lo, 1.0)
            w = np.array([rng.expovariate(1.0) for _ in objs])
            w = w / w.sum()
            y = chebyshev(U, w)
            refit, restarts = refit_schedule(step, len(ok))
            model.fit(X, y, theta0=model.theta, optimize=refit, restarts=restarts)
            feas_meas = [r[0] for r, _ in ok if r[2]]
            inc_val = None
            if feas_meas:
                mu_m, _ = model.predict(np.array([coder(v_) for v_ in feas_meas]))
                inc_val = float(np.max(mu_m))
            dead = _failed_only_mo(rows)
            full = _pool(ax, rng, None)
            pool = [p for p in full if _key(p) not in dead] or full
            P = np.array([coder(p) for p in pool])
            mu, sd = model.predict(P)
            pf = np.ones(len(pool))
            for c in tgt.constraints:
                cy = np.array([o[c["metric"]] for _, o in ok])
                cm = cmodels.setdefault(c["metric"], G.GP(restarts=1, seed=npseed + 1))
                cm.fit(X, cy, theta0=cm.theta, optimize=refit, restarts=min(restarts, 1))
                cmu, csd = cm.predict(P)
                z = (float(c["value"]) - cmu) / np.maximum(csd, 1e-12)
                pf *= norm.cdf(z) if c["op"] in ("<=", "<") else norm.cdf(-z)
            acq = (G.expected_improvement(mu, sd, inc_val) * pf
                   if inc_val is not None else pf)
            lv = pool[int(np.argmax(acq))]
            step += 1
        v, f, o = tgt.measure(lv)
        rows.append((lv, v, f))
        obs_rows.append(o)
    return rows, tgt.n


def _failed_only_mo(rows) -> set:
    class _L:
        pass
    lg = _L()
    lg.rows = [(lv, (None if v is None else 0.0), f, {}) for lv, v, f in rows]
    return _failed_only(lg)


MO_METHODS = {"RS": _rs, "LHS": _lhs_mo, "ParEGO": _parego}


def run_mo_method(method: str, surface, name: str, budget: int, seed: int):
    """``(rows, used)`` for one baseline run at ``budget``."""
    import random

    rng = random.Random(f"{name}:{seed}:{method}:mo")
    return MO_METHODS[method](surface, budget, rng)


def nous_mo_rows(work_dir, surface) -> list[tuple]:
    """Nous's fresh measurements (``measured.measured_rows``) in execution
    order as ``(levels, values|None, feasible)``, for the anytime curve."""
    from benchmarks.optimization.measured import measured_rows

    out = []
    cons = list(surface.constraints or ())
    for r in measured_rows(work_dir):
        resp = r.get("response") or {}
        vals = None
        if r.get("status") == "complete":
            try:
                vals = {o["metric"]: float(resp[o["metric"]]) for o in surface.objectives}
            except (KeyError, TypeError, ValueError):
                vals = None
            if vals is not None and not all(math.isfinite(x) for x in vals.values()):
                vals = None
        feas = vals is not None and all(
            c["metric"] in resp and _ok(float(resp[c["metric"]]), c["op"], float(c["value"]))
            for c in cons)
        out.append((dict(r["levels"]), vals, feas))
    return out
