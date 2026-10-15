"""The objective(s) a ``kind: optimization`` campaign declares, read one way.

A campaign declares EITHER ``response.primary`` (one objective, the original
form) OR ``response.objectives`` (two or more: the trade-off frontier, spec
``2026-10-15-pareto-front-design.md``). Every authoring surface that needs "the
metric(s) being optimized" -- the validator, ``--smoke``, ``--liveness``, the
design preview -- reads them through :func:`declared_objectives`, so a
single-objective campaign is simply the K = 1 case and no caller re-derives
which key is present.

Also resolves the two per-objective declarations whose value may be either one
spec for every objective or a map keyed by objective metric:
``policy.epsilon`` and ``response.noise_estimate_pct``.

Pure data access: no fitting, no front computation (those live in the
estimation core).
"""
from __future__ import annotations

#: ``policy.epsilon`` when the campaign declares none (matches
#: ``policy.compile_policy``'s default).
DEFAULT_EPSILON = {"pct": 2.0}

#: ``response.preference.method`` when the campaign declares none.
DEFAULT_PREFERENCE = "knee"


def _response(opt: dict | None) -> dict:
    resp = (opt or {}).get("response")
    return resp if isinstance(resp, dict) else {}


def declared_objectives(opt: dict | None) -> list[dict]:
    """``[{metric, direction}, ...]`` in declaration order.

    ``response.objectives`` when present (multi-objective), else a one-element
    list built from ``response.primary``, else ``[]``. Malformed entries (not
    a mapping, no metric) are skipped -- the validator reports them; callers
    here only need the usable ones. ``direction`` defaults to ``maximize``.
    """
    resp = _response(opt)
    raw = resp.get("objectives")
    if not isinstance(raw, list):
        raw = [resp.get("primary")] if resp.get("primary") is not None else []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        metric = entry.get("metric")
        if not isinstance(metric, str) or not metric:
            continue
        out.append({"metric": metric,
                    "direction": entry.get("direction") or "maximize"})
    return out


def objective_metrics(opt: dict | None) -> list[str]:
    return [o["metric"] for o in declared_objectives(opt)]


def is_multi_objective(opt: dict | None) -> bool:
    """True when the campaign declares ``response.objectives``."""
    return "objectives" in _response(opt)


def is_epsilon_map(spec) -> bool:
    """A ``policy.epsilon`` in map form (metric -> spec) rather than one spec."""
    return (isinstance(spec, dict) and bool(spec)
            and not ({"abs", "pct"} & set(spec))
            and all(isinstance(v, dict) for v in spec.values()))


def epsilon_spec_for(opt: dict | None, metric: str) -> dict:
    """The indifference-width spec that applies to ``metric``.

    A single ``{abs | pct}`` spec applies to every objective; the map form is
    looked up by metric, and an objective it does not name takes the default.
    """
    pol = (opt or {}).get("policy")
    spec = pol.get("epsilon") if isinstance(pol, dict) else None
    if not isinstance(spec, dict) or not spec:
        return dict(DEFAULT_EPSILON)
    if is_epsilon_map(spec):
        sub = spec.get(metric)
        return dict(sub) if isinstance(sub, dict) and sub else dict(DEFAULT_EPSILON)
    return dict(spec)


def noise_pct_for(opt: dict | None, metric: str) -> float | None:
    """``response.noise_estimate_pct`` for ``metric``: the number, or its map entry."""
    raw = _response(opt).get("noise_estimate_pct")
    if isinstance(raw, dict):
        raw = raw.get(metric)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return None


def improves(direction: str, delta: float) -> float:
    """``delta`` signed so that positive means BETTER under ``direction``."""
    return -delta if direction == "minimize" else delta
