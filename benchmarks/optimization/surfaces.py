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
    sparse_knobs,
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


# ── the shared candidate domain (P7 review H3) ─────────────────────────────
#: Points per refinable numeric WITHOUT a grid (none in the suite today): such
#: a factor's recommendable domain is continuous, so the truth is taken over a
#: dense grid of this many points and the tolerance is half its spacing.
DENSE_POINTS = 201

#: Largest lattice the truth is ever computed over (streamed, never
#: materialised; sized BEFORE enumeration, resource rule 4).
MAX_LATTICE = 2_000_000


def lattice_axis(f: dict) -> list:
    """Every value factor ``f`` can be RECOMMENDED at, which is also the domain
    every baseline samples:

    * ``choice`` and ``levels_only`` numerics: the declared levels;
    * a two-level numeric: its declared pair plus its CENTRE, the value its
      centre points run at (snapped to ``grid``; an integer when the levels are
      integers, ``factors._integral_as_int``). ``decide._axis`` never
      interpolates such a factor, but confirm can recommend the measured centre
      (measured: ``fails_at_one_level`` recommends CPU = 24 of [8, 40]);
    * a refinable numeric with ``grid: g``: every multiple of ``g`` in
      [min, max], plus the declared levels -- ``decode_coded`` snaps a fitted
      or design value to that lattice, so any of them can be recommended;
    * a refinable numeric with no grid: ``DENSE_POINTS`` evenly spaced points
      (stated tolerance: half the spacing).

    Before this, the truth and the baselines used ``candidate_grid``'s nine
    snapped points per axis, while Nous could recommend any lattice point: on
    ``two_peaks`` the true optimum (14, 3) = 15.653 was off that grid, so a
    recommendation of (15, 3) was scored against 14.754.
    """
    lv = list(f["levels"])
    if f["type"] != "numeric" or f.get("levels_only"):
        return sorted(lv, key=lambda v: (str(type(v)), v))
    lo, hi = min(lv), max(lv)
    if len(lv) <= 2:
        from orchestrator.optimize.factors import snap_to_grid

        mid = (float(lo) + float(hi)) / 2.0
        if f.get("grid") is not None:
            mid = snap_to_grid(mid, float(f["grid"]))
        if all(isinstance(v, int) for v in lv) and float(mid).is_integer():
            mid = int(mid)
        return sorted(set(lv) | {mid}, key=float)
    if f.get("grid") is None:
        return sorted({lo + (hi - lo) * i / (DENSE_POINTS - 1) for i in range(DENSE_POINTS)}
                      | set(lv))
    from orchestrator.optimize.factors import snap_to_grid

    g = float(f["grid"])
    n = int(math.floor((float(hi) - float(lo)) / g + 1e-9))
    return sorted({snap_to_grid(float(lo) + i * g, g) for i in range(n + 1)} | set(lv))


def _judged_factors(surface: Surface):
    """Factors the truth enumerates (the ``active`` ones when declared) and the
    inert ones pinned at their first level -- exact, since nothing judged
    depends on them."""
    act = [f for f in surface.factors if not surface.active or f["id"] in surface.active]
    pinned = {f["id"]: f["levels"][0] for f in surface.factors
              if surface.active and f["id"] not in surface.active}
    return act, pinned


def lattice_size(surface: Surface) -> int:
    act, _ = _judged_factors(surface)
    return math.prod(len(lattice_axis(f)) for f in act)


def iter_lattice(surface: Surface):
    """Stream the judged lattice (refuses one above ``MAX_LATTICE``)."""
    import itertools

    act, pinned = _judged_factors(surface)
    n = lattice_size(surface)
    if n > MAX_LATTICE:
        raise ValueError(f"{surface.name}: truth lattice of {n:,} points exceeds "
                         f"{MAX_LATTICE:,}; declare Surface.active")
    ids = [f["id"] for f in act]
    for combo in itertools.product(*[lattice_axis(f) for f in act]):
        yield {**pinned, **dict(zip(ids, combo))}


def axes(surface: Surface) -> list[tuple[dict, list]]:
    """Each factor with the candidate values a method may choose from: its
    ``lattice_axis`` -- the same domain Nous can recommend from, so every
    method shares one candidate domain and one truth."""
    return [(f, lattice_axis(f)) for f in surface.factors]


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


_TRUTH: dict = {}


def truth(surface: Surface) -> dict:
    """The oracle over the RECOMMENDABLE lattice (``iter_lattice``): optimum,
    its value, and the WORST valid value (the penalty a recommendation earns
    when it is infeasible or missing). Cached per surface name (the noise
    multiplier does not change ``fn``)."""
    if surface.name in _TRUTH:
        return _TRUTH[surface.name]
    sign = 1.0 if surface.direction == "maximize" else -1.0
    best = worst = opt = None
    for lv in iter_lattice(surface):
        if surface.invalid is not None and surface.invalid(lv):
            continue
        v = surface.fn(lv)
        if best is None or sign * v > sign * best:
            best, opt = v, lv
        if worst is None or sign * v < sign * worst:
            worst = v
    if best is None:
        raise ValueError(f"surface {surface.name!r} has no valid point")
    _TRUTH[surface.name] = {"optimum": opt, "best": best, "worst": worst}
    return _TRUTH[surface.name]


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


# ── multi-objective surfaces (the MO arm) ───────────────────────────────────
def mo_surfaces() -> dict[str, Callable[[], Surface]]:
    """``PARETO_SURFACES`` plus ``ALLOCATE_SURFACES["pareto_three_discrete"]``
    when the checkout has it (WP-D P6b). Absent on code before P6b: the
    surface is then listed as unavailable, never silently dropped."""
    from orchestrator.optimize import synthetic as _syn

    out = dict(_syn.PARETO_SURFACES)
    alloc = getattr(_syn, "ALLOCATE_SURFACES", {}) or {}
    if "pareto_three_discrete" in alloc:
        out["pareto_three_discrete"] = alloc["pareto_three_discrete"]
    return out


MO_WANTED = [*__import__("orchestrator.optimize.synthetic", fromlist=["x"]).PARETO_SURFACES,
             "pareto_three_discrete"]


def get_mo(name: str) -> Surface:
    return mo_surfaces()[name]()
