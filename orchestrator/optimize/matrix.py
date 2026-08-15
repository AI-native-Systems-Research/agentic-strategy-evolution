"""Matrix expansion, randomized run order, and post-hoc fidelity checking.

A ``Design`` (``design.py``) is an abstract ±1-coded matrix; a ``Factor``
(``factors.py``) is a parsed declaration of how one knob is applied. This
module is the seam between them: ``expand`` walks every design point and
renders a concrete, runnable configuration -- the CLI args, environment
variables, and config-file patches that make one row of the matrix an
actual thing that can execute. No model call is involved; ``{level}`` is
the only interpolation token, so the rendering is fully mechanical and
auditable.

``matrix_payload`` is what gets written to ``design_matrix.json``: the
pre-registered plan, including a run order that is randomized (so
time-ordered drift like thermal effects or cache warming cannot masquerade
as a factor effect) but recorded against a seed (so the campaign stays
reproducible), and the design's alias structure (from
``design.alias_pairs``) so a heavily confounded design says so in the
artifact itself rather than by omission. ``check_fidelity`` closes the
loop after the fact -- it
compares what the payload promised against what actually ran, by
``row_index``, and reports three distinct hard-failure classes: a level
that drifted, a planned row nothing ran, and a run that names a row the
plan never declared.

``check_invariants`` reuses ``predicates.evaluate`` rather than a second
comparison implementation, so ``design_space.invariants`` share the exact
same vocabulary as ``manipulation`` and ``response.constraints``.
"""
from __future__ import annotations

import math

import random
from dataclasses import dataclass, field
from typing import Any

from orchestrator.optimize.design import Design, DesignPoint, alias_pairs
from orchestrator.optimize.factors import Factor, decode_coded
from orchestrator.optimize.predicates import evaluate


@dataclass(frozen=True)
class ConfigRow:
    """One design point rendered into a runnable configuration."""

    row_index: int
    levels: dict
    role: str
    replicate: int
    apply: dict = field(default_factory=dict)


def _decode_level(f: Factor, point: DesignPoint, idx: int) -> Any:
    """The real-world level factor ``f`` takes at coded position ``idx``.

    At exactly ±1 (corner points) the coded value maps onto the declared
    screen pair without any interpolation or grid-snapping arithmetic --
    using the declared level verbatim (rather than routing it through
    ``decode_coded``'s float math) preserves its original type, e.g. an
    int level stays ``2`` rather than becoming ``2.0``. Any other coded
    value (axial/star points, fractional designs) genuinely needs
    ``decode_coded``'s interpolation.
    """
    low, high = f.screen_levels
    if point.role == "center":
        if f.type == "choice":
            return low
        return decode_coded(f, 0.0)
    coded = point.coded[idx]
    if coded == -1:
        return low
    if coded == 1:
        return high
    return decode_coded(f, coded)


def _render_apply(f: Factor, level: Any) -> dict:
    """Render one factor's ``apply_spec`` for a concrete ``level``.

    ``{level}`` is the only token substituted -- no arbitrary template
    evaluation. Returns a partial ``apply`` dict with at most one of
    ``cli_args`` / ``env`` / ``patches`` populated; ``expand`` merges these
    across all of a row's factors.
    """
    spec = f.apply_spec
    kind = spec.get("kind")
    if kind == "cli_flag":
        template = spec["template"]
        return {"cli_args": [template.replace("{level}", str(level))]}
    if kind == "env_var":
        value = spec["value"]
        rendered = level if value == "{level}" else value
        return {"env": {spec["name"]: rendered}}
    if kind == "config_patch":
        value = spec["value"]
        rendered = level if value == "{level}" else value
        return {"patches": [{
            "path": spec["path"], "pointer": spec["pointer"], "value": rendered,
        }]}
    raise ValueError(f"factor {f.id!r}: unknown apply kind {kind!r}")


def render_apply(factors, levels: dict) -> dict:
    """Compose the ``apply`` payload for an explicit set of levels.

    ``expand`` renders ``apply`` from a design point's CODED coordinates.
    ``confirm`` sometimes needs the same rendering for levels chosen another
    way — the best configuration actually observed, when there is no fitted
    stationary point to reproduce — so the per-factor rendering is exposed
    here rather than duplicated at the call site.
    """
    cli_args: list = []
    env: dict = {}
    patches: list = []
    by_id = {f.id: f for f in factors}
    for fid, level in levels.items():
        f = by_id.get(fid)
        if f is None:
            continue
        rendered = _render_apply(f, level)
        cli_args.extend(rendered.get("cli_args", []))
        env.update(rendered.get("env", {}))
        patches.extend(rendered.get("patches", []))
    return {"cli_args": cli_args, "env": env, "patches": patches}


def expand(design: Design, factors: list[Factor]) -> list[ConfigRow]:
    """Turn every design point into a runnable :class:`ConfigRow`.

    Order matches ``design.points`` exactly -- callers that want a
    randomized execution order should consult ``run_order`` from
    :func:`matrix_payload` rather than reordering this list.
    """
    by_id = {f.id: f for f in factors}
    rows: list[ConfigRow] = []
    for row_index, point in enumerate(design.points):
        levels: dict[str, Any] = {}
        cli_args: list[str] = []
        env: dict[str, Any] = {}
        patches: list[dict] = []
        pinned: dict[str, bool] = {}

        for idx, fid in enumerate(design.factor_ids):
            f = by_id[fid]
            level = _decode_level(f, point, idx)
            levels[fid] = level
            rendered = _render_apply(f, level)
            cli_args.extend(rendered.get("cli_args", []))
            env.update(rendered.get("env", {}))
            patches.extend(rendered.get("patches", []))
            if point.role == "center" and f.type == "choice":
                pinned[fid] = True

        apply: dict[str, Any] = {"cli_args": cli_args, "env": env, "patches": patches}
        if pinned:
            apply["center_choice_pinned"] = pinned

        rows.append(ConfigRow(
            row_index=row_index, levels=levels, role=point.role,
            replicate=point.replicate, apply=apply,
        ))
    return rows


def randomized_run_order(n: int, seed: int) -> list[int]:
    """A permutation of ``range(n)``, reproducible from ``seed`` alone.

    Uses a local ``random.Random`` instance -- never the global ``random``
    module state -- so the same seed always yields the same order,
    independent of what else in the process has touched the RNG.
    """
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order


def matrix_payload(design: Design, factors: list[Factor], *,
                    run_order_seed: int) -> dict:
    """The full ``design_matrix.json`` body: rows plus design provenance.

    ``aliases`` is populated from ``design.alias_pairs(design)`` -- a
    resolution-III design's payload names its confounded terms rather than
    recording an empty list that would misrepresent the design as fully
    resolved. ``alias_pairs`` already returns a sorted list, so this stays
    deterministic across calls, matching ``rows`` and ``run_order``.
    """
    rows = expand(design, factors)
    run_order = randomized_run_order(len(rows), run_order_seed)
    return {
        "factor_ids": list(design.factor_ids),
        "kind": design.kind,
        "resolution": design.resolution,
        "generators": [list(g) for g in design.generators],
        "aliases": [list(pair) for pair in alias_pairs(design)],
        "run_order": run_order,
        "run_order_seed": run_order_seed,
        "rows": [
            {
                "row_index": r.row_index,
                "levels": dict(r.levels),
                "role": r.role,
                "replicate": r.replicate,
                "apply": r.apply,
            }
            for r in rows
        ],
    }


def check_fidelity(payload: dict, runs: list[dict]) -> list[str]:
    """Compare the pre-registered matrix against what actually ran.

    Reports three distinct violation classes, each a hard failure: a run
    whose recorded ``levels`` drifted from the planned row at the same
    ``row_index``; a planned row with no corresponding run (a silently
    skipped cell); and a run whose ``row_index`` names no planned row (an
    unplanned extra run). Any of these changes the design's actual
    resolution, so none is tolerated silently.
    """
    planned = {row["row_index"]: row for row in payload.get("rows", [])}
    seen: set[int] = set()
    violations: list[str] = []

    for run in runs:
        idx = run.get("row_index")
        if idx not in planned:
            violations.append(
                f"unplanned run: row_index {idx!r} is not in the pre-registered matrix",
            )
            continue
        if idx in seen:
            # A fourth violation class the original three missed. On the
            # REDESIGN path (Engine.force_phase("DESIGN"), campaign.py:462)
            # a re-run iteration re-appends every row, so runs.jsonl doubles
            # with every row_index duplicated — and accumulating into `seen`
            # absorbed that silently. The in-memory fit stays correct, but
            # the durable pre-registration audit trail is exactly what this
            # guard exists to protect, so a duplicate must not pass.
            violations.append(
                f"duplicate run: row_index {idx!r} appears more than once, "
                f"so runs.jsonl no longer records one run per planned "
                f"configuration (a resumed or re-run iteration re-appending "
                f"its rows will do this)",
            )
            continue
        seen.add(idx)
        expected_levels = planned[idx]["levels"]
        observed_levels = run.get("levels", {})
        for factor_id, expected in expected_levels.items():
            observed = observed_levels.get(factor_id)
            # Levels round-trip through JSON at the stage-runner's
            # read_runs call, so a float can come back a representation
            # step away from the planned value. Exact != would report
            # spurious drift and abort a legitimate campaign — verified:
            # 0.1 + 0.2 against a planned 0.3. Compare numerics with a
            # tolerance; anything non-numeric still compares exactly,
            # since a choice level must match its declared string.
            if isinstance(expected, (int, float)) and isinstance(
                observed, (int, float),
            ) and not isinstance(expected, bool) and not isinstance(
                observed, bool,
            ):
                if math.isclose(
                    float(observed), float(expected),
                    rel_tol=1e-9, abs_tol=1e-12,
                ):
                    continue
            if observed != expected:
                violations.append(
                    f"level drift at row_index {idx}: factor {factor_id!r} "
                    f"expected {expected!r}, observed {observed!r}",
                )

    for idx in sorted(set(planned) - seen):
        violations.append(
            f"missing run: planned row_index {idx} has no corresponding run "
            f"(silently skipped cell)",
        )

    return violations


def check_invariants(invariants: list[dict], observed: dict, *,
                      level: Any = None) -> list[str]:
    """Check ``design_space.invariants`` against one observation.

    Delegates to ``predicates.evaluate`` -- the same vocabulary used by
    ``manipulation`` and ``response.constraints`` -- so there is exactly
    one comparison implementation across the whole feature. A missing
    observable is a violation: an invariant that was never emitted cannot
    be said to hold.
    """
    violations: list[str] = []
    for inv in invariants:
        verdict = evaluate(inv, observed, level=level)
        if verdict.skipped:
            continue
        if not verdict.ok:
            violations.append(
                f"invariant {inv.get('id')!r} ({inv.get('statement')!r}) violated: "
                f"{verdict.detail}",
            )
    return violations
