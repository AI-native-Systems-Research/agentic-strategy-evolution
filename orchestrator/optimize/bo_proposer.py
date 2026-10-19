"""WP-D D3: an OPTIONAL Bayesian-optimization proposer (the ``nous[bo]`` extra).

USED ONLY TO PROPOSE. A TPE sampler (Bergstra et al. 2011, via Optuna: Akiba
et al. 2019) suggests configurations, and they go to exactly two places:

* the D1 recombination pool (``allocate.allocate(proposals=...)``), where the
  fitted model scores them like any other candidate;
* ``nous plan-next``'s ``bo_block`` option. This is a model-free next-epoch
  region (the bounding box of the proposals), and it is the planner's one
  alternative when the RSM model is inadequate. The next epoch is still a
  compiled, pre-registered design over that region.

Nothing here certifies, estimates or decides. Certification, effects and
decide never import this module, and a test enforces that.

DETERMINISM, NO HIDDEN STATE. The configuration (``sampler``, ``n_startup``,
``seed``) comes from ``policy.json`` ``planner.bo``, so it is compiled and
hashed before any data. On every call the study is REBUILT in memory from the
epoch's measured rows, in row order: each row becomes a completed trial. There
is no Optuna storage and no study persists between calls. The same rows and
the same seed therefore give the same proposals. Each proposal carries its
provenance: sampler, seed, n_startup, trials-from-rows and the Optuna version.

Optuna is imported LAZILY, inside ``_optuna_sampler``. The core install
(no Optuna) is unaffected. Without the extra, ``propose`` raises
``BOUnavailable``, and the planner records that as a named reason. The seam is
``sampler=``: any callable ``(trials, space, objectives, config, n) -> [params]``.
"""
from __future__ import annotations

import math

DEFAULT_CONFIG = {"sampler": "tpe", "n_startup": 10, "seed": 0}


class BOUnavailable(RuntimeError):
    """The ``nous[bo]`` extra (Optuna) is not installed."""


def bo_config(policy: dict | None) -> dict | None:
    """The compiled ``planner.bo`` block, or ``None`` (no BO declared)."""
    cfg = ((policy or {}).get("planner") or {}).get("bo")
    if cfg is None:
        return None
    return {**DEFAULT_CONFIG, **dict(cfg)}


def search_space(factors) -> dict:
    """``{factor_id: spec}`` over the screen range of each factor.

    ``choice`` and ``levels_only`` numeric factors are categorical over their
    runnable levels. An integer-levelled numeric is an int range (step = grid
    or 1). Any other numeric is a float range (step = grid). ``scale: log``
    gives a log range, with the grid applied after sampling."""
    from orchestrator.optimize.factors import runnable_levels

    out = {}
    for f in factors:
        if f.type == "choice":
            out[f.id] = {"kind": "categorical", "choices": list(f.levels)}
            continue
        if f.levels_only:
            out[f.id] = {"kind": "categorical", "choices": list(runnable_levels(f))}
            continue
        lo, hi = sorted(float(v) for v in f.screen_levels)
        ints = all(isinstance(v, int) and not isinstance(v, bool) for v in f.levels)
        if ints and (f.grid is None or float(f.grid).is_integer()):
            step = int(f.grid) if f.grid else 1
            out[f.id] = {"kind": "int", "low": int(lo), "high": int(hi),
                         "step": 1 if f.scale == "log" else step,
                         "log": f.scale == "log", "grid": step}
        else:
            out[f.id] = {"kind": "float", "low": lo, "high": hi,
                         "step": None if f.scale == "log" else f.grid,
                         "log": f.scale == "log", "grid": f.grid}
    return out


def _inside(spec: dict, v) -> bool:
    if spec["kind"] == "categorical":
        return v in spec["choices"]
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return spec["low"] - 1e-12 <= x <= spec["high"] + 1e-12


def rows_to_trials(rows, space: dict, objectives) -> tuple[list, int]:
    """``(trials, skipped)``. Each trial is ``(params, values)``, in row order.
    A row is skipped when it is not ``complete``, its levels fall outside the
    space, or an objective value is missing or non-finite. The skipped count
    is recorded, never hidden."""
    trials, skipped = [], 0
    for r in rows:
        # Only a COMPLETE row is a measurement of its configuration: a
        # failed, infeasible or rejected row's response is not the objective.
        if r.get("status", "complete") != "complete":
            skipped += 1
            continue
        lv = r.get("levels") or {}
        resp = r.get("response") or {}
        params = {k: lv.get(k) for k in space}
        vals = []
        for o in objectives:
            v = resp.get(o["metric"])
            vals.append(float(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(float(v)) else None)
        if any(v is None for v in vals) or not all(_inside(space[k], params[k]) for k in space):
            skipped += 1
            continue
        trials.append((params, vals))
    return trials, skipped


def _snap(spec: dict, v):
    if spec["kind"] == "categorical":
        return v
    g = spec.get("grid")
    if spec["kind"] == "int":
        g = int(g or 1)
        return int(min(max(round(float(v) / g) * g, spec["low"]), spec["high"]))
    if g:
        from orchestrator.optimize.factors import snap_to_grid

        return snap_to_grid(min(max(float(v), spec["low"]), spec["high"]), g)
    return float(v)


def _on_step(spec: dict, v):
    """``v`` as the distribution's type, on its ``low + k*step`` grid."""
    if spec["kind"] == "categorical":
        return v
    st = spec.get("step")
    if spec["kind"] == "int":
        st = int(st or 1)
        return int(min(max(spec["low"] + round((float(v) - spec["low"]) / st) * st,
                           spec["low"]), spec["high"]))
    if st:
        k = round((float(v) - spec["low"]) / float(st))
        return float(min(max(spec["low"] + k * float(st), spec["low"]), spec["high"]))
    return float(v)


def _optuna_sampler(trials, space, objectives, config, n) -> list[dict]:
    """The default seam: Optuna TPE over an IN-MEMORY study, rebuilt here."""
    try:
        import optuna  # noqa: PLC0415 -- lazy by design (the nous[bo] extra)
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise BOUnavailable("optuna is not installed: pip install 'nous[bo]'") from exc
    if config.get("sampler", "tpe") != "tpe":
        raise ValueError(f"unknown planner.bo.sampler {config.get('sampler')!r} (only 'tpe')")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    dists = {}
    for k, s in space.items():
        if s["kind"] == "categorical":
            dists[k] = optuna.distributions.CategoricalDistribution(tuple(s["choices"]))
        elif s["kind"] == "int":
            dists[k] = optuna.distributions.IntDistribution(
                s["low"], s["high"], step=int(s["step"] or 1), log=bool(s["log"]))
        else:
            dists[k] = optuna.distributions.FloatDistribution(
                s["low"], s["high"], step=s["step"], log=bool(s["log"]))
    sampler = optuna.samplers.TPESampler(seed=int(config["seed"]),
                                         n_startup_trials=int(config["n_startup"]))
    study = optuna.create_study(
        directions=[("minimize" if o["direction"] == "minimize" else "maximize")
                    for o in objectives], sampler=sampler)
    for params, values in trials:
        # Snapped onto the distribution's step grid (create_trial refuses an
        # off-grid value); the row was already checked to be inside the range.
        p = {k: _on_step(space[k], v) for k, v in params.items()}
        study.add_trial(optuna.trial.create_trial(params=p, distributions=dists, values=values))
    return [dict(study.ask(dists).params) for _ in range(int(n))]


def optuna_version() -> str | None:
    from importlib import metadata

    try:
        return metadata.version("optuna")
    except metadata.PackageNotFoundError:
        return None


def propose(rows, *, factors, objectives, config: dict, n: int,
            held_fixed: dict | None = None, sampler=None) -> tuple[list[dict], dict]:
    """``(proposals, provenance)``. Each proposal is ``{levels, source:
    "bo_proposal", provenance}``, with ``held_fixed`` merged in. Proposals that
    duplicate each other, or a measured row, are dropped. Raises
    ``BOUnavailable`` without the extra when no ``sampler`` is injected."""
    cfg = {**DEFAULT_CONFIG, **dict(config or {})}
    space = search_space(factors)
    trials, skipped = rows_to_trials(rows, space, objectives)
    fn = sampler or _optuna_sampler
    raw = fn(trials, space, objectives, cfg, n)
    from orchestrator.optimize.allocate import _key

    measured = {_key(t[0]) for t in trials}
    prov = {"sampler": ("TPESampler" if sampler is None else
                        getattr(sampler, "__name__", type(sampler).__name__)),
            "seed": int(cfg["seed"]), "n_startup": int(cfg["n_startup"]),
            "n_trials_from_rows": len(trials), "rows_skipped": skipped,
            "optuna_version": optuna_version() if sampler is None else None,
            "n_requested": int(n),
            "storage": "in-memory study rebuilt from the epoch's rows on this call; "
                       "nothing persisted"}
    out, seen = [], set()
    for p in raw:
        lv = {k: _snap(space[k], p[k]) for k in space if k in p}
        key = _key(lv)
        if key in seen or key in measured:
            continue
        seen.add(key)
        out.append({"levels": {**dict(held_fixed or {}), **lv}, "source": "bo_proposal",
                    "provenance": prov})
    prov = {**prov, "n_proposed": len(out)}
    for o in out:
        o["provenance"] = prov
    return out, prov
