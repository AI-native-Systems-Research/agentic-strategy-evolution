"""The benchmark suite: which surfaces, which campaign each one runs, and the
measurement model every method shares.

Three families:

* every single-objective surface shipped in ``orchestrator.optimize.synthetic``
  (``SURFACES``) -- the quadratic-class surfaces Nous was built for, plus the
  defect surfaces (constraints, NaN corner, failing level, drift);
* three deliberately NON-quadratic surfaces (``step_cliff``, ``ridge_cubic``,
  ``two_peaks``), copied from the stage-0 audit probe (``probelib.py``) so the
  numbers here can be compared with the audit's;
* many-knob sparse surfaces ``sparse_knobs(k)``.

Multi-objective (Pareto) surfaces are out of scope: none of the baselines
here is a multi-objective method, and a matched comparison would need EHVI or
ParEGO rather than EI.

Noise. ``mult`` scales the surface's primary-metric noise (``noise_sd``) and
nothing else; constraint observables keep their own declared noise. The same
``measure`` function generates every baseline's observation, and Nous's
synthetic runner draws from the same model, so no method sees a different
target.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable

from orchestrator.optimize.synthetic import (
    SURFACES,
    Surface,
    _choice,
    _numeric,
    candidate_grid,
    sparse_knobs,
    true_optimum,
)


# ── deliberately non-quadratic surfaces (from the stage-0 audit probe) ──────
def two_peaks() -> Surface:
    """Narrow global peak at (14, 3), broad local hump at the centre (9, 9)."""
    def fn(lv):
        a, b = float(lv["A"]), float(lv["B"])
        broad = 3.0 * math.exp(-((a - 9) ** 2 + (b - 9) ** 2) / 40.0)
        narrow = 5.0 * math.exp(-((a - 14) ** 2 + (b - 3) ** 2) / 4.0)
        return 10.0 + broad + narrow
    return Surface(name="two_peaks", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B")), fn=fn)


def step_cliff() -> Surface:
    """Monotone rise that drops 6 units past A = 12 (a cache-overflow cliff)."""
    def fn(lv):
        a, b = float(lv["A"]), float(lv["B"])
        return 10.0 + 0.3 * a + 0.1 * b - (6.0 if a > 12 else 0.0)
    return Surface(name="step_cliff", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B")), fn=fn)


def ridge_cubic() -> Surface:
    """Cubic in A with an interior maximum near A = 6, plus a hidden A*B*C
    three-way interaction that makes C = off optimal."""
    def fn(lv):
        a, b = float(lv["A"]), float(lv["B"])
        c = 1.0 if lv["C"] == "on" else -1.0
        x = (a - 9) / 7.0
        return (12.0 - 2.0 * x ** 3 - 2.0 * x ** 2 + 1.5 * x
                + 0.3 * c * x * ((b - 9) / 7.0) * 3)
    return Surface(name="ridge_cubic", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B"), _choice("C")), fn=fn)


NON_QUADRATIC: dict[str, Callable[[], Surface]] = {
    "step_cliff": step_cliff,
    "ridge_cubic": ridge_cubic,
    "two_peaks": two_peaks,
}

SPARSE: dict[str, Callable[[], Surface]] = {
    f"sparse_knobs_{k}": (lambda k=k: sparse_knobs(k)) for k in (6, 8, 12)
}

#: Every surface the benchmark knows, by name.
ALL: dict[str, Callable[[], Surface]] = {**SURFACES, **NON_QUADRATIC, **SPARSE}

FAMILY = {**{n: "shipped" for n in SURFACES},
          **{n: "non-quadratic" for n in NON_QUADRATIC},
          **{n: "many-knob sparse" for n in SPARSE}}

#: Surfaces whose factors are all 2-level: ``refine`` has nothing to refine
#: (see ``harness.synthetic_campaign``), so their campaign skips it.
NO_REFINE = {"drift", "interaction_only", "nan_at_corner"}

#: The ``response.constraints`` each constrained surface was built for. Without
#: them the campaign optimizes the unconstrained primary and its "regret" would
#: be measured against an optimum it was never asked for.
CONSTRAINTS = {
    "sla": [{"metric": "p99_ms", "op": "<=", "value": 40}],
    "infeasible_corner_interior": [{"metric": "p99_ms", "op": "<=", "value": 90}],
    "stochastic_constraint_boundary": [{"metric": "stall_ms", "op": "<=", "value": 10}],
    "deterministic_constraint_axis": [{"metric": "backlog", "op": "<=", "value": 7}],
}


def get(name: str, mult: float = 1.0) -> Surface:
    """Surface ``name`` with its primary noise scaled by ``mult``."""
    s = ALL[name]()
    return dataclasses.replace(s, noise_sd=s.noise_sd * mult) if mult != 1.0 else s


def campaign_overrides(name: str) -> dict | None:
    o: dict = {}
    if name in NO_REFINE:
        o["stages"] = ["verify", "screen", "confirm"]
    if name in CONSTRAINTS:
        o["response"] = {"primary": {"metric": "m", "direction": "maximize"},
                         "constraints": CONSTRAINTS[name]}
    return o or None


# ── the shared measurement model ────────────────────────────────────────────
def axes(surface: Surface) -> list[tuple[dict, list]]:
    """Each factor with the candidate values a method may choose from: the
    same per-factor axis ``synthetic.candidate_grid`` (and therefore the
    oracle's truth) uses -- declared levels plus, for gridded numerics, nine
    snapped points spanning the range."""
    out = []
    for f in surface.factors:
        vals = sorted({g[f["id"]] for g in candidate_grid([f])},
                      key=lambda v: (str(type(v)), v))
        out.append((f, vals))
    return out


def grid_size(surface: Surface) -> int:
    n = 1
    for _, vals in axes(surface):
        n *= len(vals)
    return n


def _ok(value: float, op: str, bound: float) -> bool:
    return {"<=": value <= bound, "<": value < bound,
            ">=": value >= bound, ">": value > bound}[op]


class Target:
    """One method's private copy of the synthetic target.

    ``measure`` returns ``(y, feasible)`` -- ``y`` is ``None`` when the target
    produced no usable number (``fails_at`` raises, ``exception_at`` emits
    NaN), which still consumes one run of the budget. ``feasible`` is whether
    every declared constraint observable passed on THIS replicate. The run
    counter drives ``drift_per_run`` exactly as ``make_synthetic_runner``'s
    does, so a method that measures in a trending order pays for it.
    """

    def __init__(self, surface: Surface, name: str, rng):
        self.s, self.rng, self.n = surface, rng, 0
        self.constraints = CONSTRAINTS.get(name, [])

    def measure(self, lv: dict) -> tuple[float | None, bool, dict]:
        s, rng = self.s, self.rng
        counter = self.n
        self.n += 1
        if s.fails_at is not None and s.fails_at(lv):
            return None, False, {}
        if s.exception_at and all(lv.get(k) == v for k, v in s.exception_at.items()):
            return None, False, {}
        y = s.fn(lv) + rng.gauss(0.0, s.noise_sd) + s.drift_per_run * counter
        obs = dict(s.extra_observables(lv))
        if s.noisy_observables is not None:
            obs.update(s.noisy_observables(lv, rng))
        feas = all(_ok(float(obs[c["metric"]]), c["op"], float(c["value"]))
                   for c in self.constraints)
        return y, feas, {c["metric"]: float(obs[c["metric"]]) for c in self.constraints}


def truth(surface: Surface) -> dict:
    """The oracle: optimum, its value, and the WORST valid value (the penalty
    a recommendation earns when it is infeasible or missing)."""
    opt, best = true_optimum(surface)
    from orchestrator.optimize.synthetic import _truth_grid

    worst = min(surface.fn(lv) for lv in _truth_grid(surface)
                if surface.invalid is None or not surface.invalid(lv))
    return {"optimum": opt, "best": best, "worst": worst}


def true_regret(surface: Surface, rec: dict | None, tr: dict) -> tuple[float, str]:
    """``(regret, status)`` of a recommendation, judged NOISELESSLY.

    ``status`` is ``ok``, ``infeasible`` (outside X_valid) or ``none`` (no
    recommendation). Both failure statuses are charged ``best - worst``, the
    regret of the worst admissible configuration: an answer you cannot deploy
    is no better than the worst one you could.
    """
    if not rec:
        return tr["best"] - tr["worst"], "none"
    if surface.invalid is not None and surface.invalid(rec):
        return tr["best"] - tr["worst"], "infeasible"
    # Not clamped: a recommendation off the truth grid can beat its optimum.
    return tr["best"] - surface.fn(rec), "ok"
