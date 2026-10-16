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

import dataclasses
import math

import random
from dataclasses import dataclass, field
from typing import Any

from orchestrator.optimize.design import Design, DesignPoint, alias_pairs, factor_columns
from orchestrator.optimize.factors import (
    Factor,
    code_actual,
    code_vector,
    decode_coded,
    is_categorical,
    level_of_bits,
    model_columns,
)
from orchestrator.optimize.predicates import evaluate


@dataclass(frozen=True)
class ConfigRow:
    """One design point rendered into a runnable configuration."""

    row_index: int
    levels: dict
    role: str
    replicate: int
    apply: dict = field(default_factory=dict)


def centre_choice_levels(f: Factor) -> tuple:
    """The levels a choice factor's centre rows cycle through: the levels the
    screen runs it at (its screen pair for a two-level choice, EVERY declared
    level for a multi-level categorical)."""
    if is_categorical(f):
        return tuple(f.levels)
    return tuple(f.screen_levels)


def _decode_factor(f: Factor, point: DesignPoint, idxs, *, n_configs: int = 1) -> Any:
    """The level factor ``f`` runs at ``point``, from ALL of its columns.

    A single-column factor is ``_decode_level``. A multi-level categorical
    (method of replacement) reads its pseudo-factor signs at a corner --
    ``b = sum_i [p_i = +1] 2^(i-1)`` -- and runs ``factors.level_of_bits``
    (collapsing ``b >= L`` onto level ``b - L``); a centre row runs the
    diagonal cyclic assignment over all L levels.
    """
    if not is_categorical(f):
        return _decode_level(f, point, idxs[0], n_configs=n_configs)
    if point.role == "center":
        cyc = centre_choice_levels(f)
        return cyc[(int(point.replicate) % max(1, int(n_configs))) % len(cyc)]
    b = 0
    for i, j in enumerate(idxs):
        v = point.coded[j]
        if v not in (-1.0, 1.0):
            raise ValueError(
                f"factor {f.id!r}: pseudo-factor column {j} is coded {v!r}; a "
                f"categorical's pseudo-factors are two-level (+-1) only")
        if v > 0:
            b |= 1 << i
    return level_of_bits(f, b)


def centre_configurations(n_centre: int, level_counts) -> int:
    """``g``: how many DISTINCT centre configurations ``n_centre`` centre points
    are spread over, given the choice factors' level counts.

    ``g = max(1, min(lcm(L_j), floor(n_centre / 2)))`` -- spec
    2026-10-16-mixed-level-factors-design.md, feature 3, "replication first,
    then coverage". The ``floor(n/2)`` cap guarantees every configuration at
    least two replicates whenever ``n_centre >= 2``, so pure error keeps
    ``n_centre - g >= ceil(n_centre / 2)`` df (Draper & Smith, *Applied
    Regression Analysis*, 3e, §2.1: pure error needs replicates of ONE
    configuration). ``lcm`` is the period of the diagonal cycle: past it a new
    configuration repeats an old one. No choice factor -> ``1``.
    """
    counts = [int(c) for c in level_counts if int(c) > 1]
    if not counts:
        return 1
    period = 1
    for c in counts:
        period = period * c // math.gcd(period, c)
    return max(1, min(period, int(n_centre) // 2))


def _decode_level(f: Factor, point: DesignPoint, idx: int, *,
                  n_configs: int = 1) -> Any:
    """The real-world level factor ``f`` takes at coded position ``idx``.

    At exactly ±1 (corner points) the coded value maps onto the declared
    screen pair without any interpolation or grid-snapping arithmetic --
    using the declared level verbatim (rather than routing it through
    ``decode_coded``'s float math) preserves its original type, e.g. an
    int level stays ``2`` rather than becoming ``2.0``. Any other coded
    value (axial/star points, fractional designs) genuinely needs
    ``decode_coded``'s interpolation.

    A CENTRE row has no categorical coordinate, so a choice factor runs the
    DIAGONAL CYCLIC assignment (spec 2026-10-16, feature 3): centre replicate
    ``i`` is configuration ``c = i mod n_configs`` (``centre_configurations``),
    in which the factor takes ``levels[c mod L]``. With ``n_configs = 1`` --
    every campaign without a choice factor, and a two-level choice at fewer
    than four centre points -- that is the first level, as it always was.
    """
    low, high = f.screen_levels
    if point.role == "center":
        if f.type == "choice":
            cyc = centre_choice_levels(f)
            config = int(point.replicate) % max(1, int(n_configs))
            return cyc[config % len(cyc)]
        return decode_coded(f, 0.0)
    coded = point.coded[idx]
    if coded == -1:
        return low
    if coded == 1:
        return high
    return decode_coded(f, coded)


def _design_centre_configs(design: Design, by_id: dict) -> int:
    """``centre_configurations`` for this design's centre rows and choice
    factors -- the one place ``expand`` and the payload record read it from."""
    n_c = sum(1 for p in design.points if p.role == "center")
    counts = [len(centre_choice_levels(by_id[fid])) for fid, _ in factor_columns(design)
              if fid in by_id and by_id[fid].type == "choice"]
    return centre_configurations(n_c, counts)


def centre_points_record(design: Design, factors) -> dict | None:
    """``design_matrix.json["centre_points"]``: how the centre rows cover the
    choice factors' levels, and what that leaves pure error.

    ``None`` when the design has no centre row or no choice factor, so every
    such campaign's payload is byte-identical to before. Otherwise: the
    assignment rule, the number of distinct configurations ``g``, the
    replicates per configuration, ``pure_error_df = n_centre - g`` (what
    ``effects.fit_effects`` will pool when every centre row measures), each
    choice factor's per-level centre count, and a WARNING per level no centre
    point covers -- curvature is not checked under it.
    """
    by_id = {f.id: f for f in factors}
    cols_of = dict(factor_columns(design))
    choice = [by_id[fid] for fid in cols_of
              if fid in by_id and by_id[fid].type == "choice"]
    centres = [p for p in design.points if p.role == "center"]
    if not centres or not choice:
        return None
    g = _design_centre_configs(design, by_id)
    reps: dict[int, int] = {}
    per_level: dict = {}
    for f in choice:
        per_level[f.id] = {str(lv): 0 for lv in centre_choice_levels(f)}
    for p in centres:
        c = int(p.replicate) % g
        reps[c] = reps.get(c, 0) + 1
        for f in choice:
            per_level[f.id][str(_decode_factor(f, p, cols_of[f.id], n_configs=g))] += 1
    warnings = []
    max_l = max(len(centre_choice_levels(f)) for f in choice)
    for f in choice:
        missing = [lv for lv, n in per_level[f.id].items() if n == 0]
        if missing:
            rep = (", each replicated at least twice" if len(centres) >= 2 else "")
            warnings.append(
                f"choice factor {f.id!r}: level(s) {', '.join(repr(m) for m in missing)} "
                f"get no centre point ({len(centres)} centre point(s) over {g} "
                f"configuration(s){rep}), so curvature is not checked under them. "
                f"center_points >= {2 * max_l} (twice the largest choice level "
                f"count) covers every level of every choice factor twice.")
    return {
        "assignment": "diagonal_cyclic",
        "rule": "g = max(1, min(lcm(L_j), floor(n_centre/2))); replicate i runs "
                "configuration i mod g, choice factor j at levels_j[(i mod g) mod L_j]",
        "n_centre": len(centres),
        "configurations": g,
        "replicates_per_configuration": [reps.get(c, 0) for c in range(g)],
        "pure_error_df": len(centres) - g,
        "per_level": per_level,
        "warnings": warnings,
    }


def coded_as_run(design: Design, factors, levels_by_pos) -> tuple[Design, list[int]]:
    """``design`` with every row re-coded from the levels that ACTUALLY RAN.

    INV-STAT14: the fit's design matrix is the coded actual levels. Two ways
    the nominal coordinates lie about what ran, both measured on the oracle:

      * AXIAL CLAMPING. ``decode_coded`` clamps a central composite's axial
        point (|coded| = 1.41 at k=2, 1.68 at k=3) to the declared range, so
        it RUNS at the edge (``+-1``). Regressing on the nominal ``+-1.68`` is
        an errors-in-variables bias: a truly linear surface then fails lack
        of fit (measured: ~100% rejection on a clamped k=2 CCD; ~alpha once
        recoded) and every coefficient touching the axis shrinks.
      * CHOICE CENTRE POINTS. A categorical has no centre. ``_decode_level``
        runs a choice factor's centre rows at the levels of the diagonal
        cyclic assignment (``centre_configurations``; at fewer than four
        centre points with one two-level choice, its FIRST level), so each
        such row is coded at the level it ran (``-1``/``+1``) for the choice
        factor and ``0`` for every numeric. The
        alternatives were weighed against spec §3.2 and standard mixed-design
        RSM practice:

          - replicating centre points at EACH choice level (the textbook
            mixed-design layout) is a DESIGN change, not a fitting fix -- and
            it is now made, without changing the centre-point count: the
            diagonal cyclic assignment (spec 2026-10-16, feature 3) spreads
            the declared centres over the levels, each configuration
            replicated at least twice, and pure error is pooled within them.
          - dropping the choice columns from centre rows is not expressible
            in a single least-squares matrix without inventing a value.
          - coding the level that ran keeps the centre rows of each
            configuration TRUE REPLICATES of it, which is exactly what the
            pooled pure-error estimate requires, and costs only orthogonality
            of the choice column with the intercept -- an honest
            non-orthogonality the general least-squares solve handles.

        WHAT THE LACK-OF-FIT TEST MEANS with cycled centres: each centre row
        is coded at the level it ran, so the fitted first-order model
        predicts it under that level, and every choice x numeric interaction
        vanishes at the numeric centre. Under H0 (the model is correct: no
        curvature under any covered level) the lack-of-fit F is exactly
        F-distributed; curvature under a covered level -- including under one
        level only -- gives it power. It says nothing about levels no centre
        ran (``effects.json["curvature_untested_levels"]``). ASSUMPTION: the
        first-order part is correctly specified (resolution >= V, or the
        aliased terms are zero). A ``levels_only`` numeric's centre is its
        SNAPPED centre level, not the arithmetic midpoint.

        So the principle is one rule for both defects: code what ran.

    ``levels_by_pos`` holds one levels dict per POSITION of ``design`` (the
    fit's positional convention). A position whose levels are missing any of
    the design's factors keeps its nominal coding and is returned in the
    second element, so the caller decides whether that is admissible (it is
    for a row the fit drops anyway) rather than this function guessing.

    ``design_matrix.json`` is untouched: it records what was PLANNED, and
    ``check_fidelity`` still compares planned levels to recorded levels.
    """
    by_id = {f.id: f for f in factors}
    if any(fid in by_id and is_categorical(by_id[fid])
           for fid, _ in factor_columns(design)):
        return _coded_as_run_mixed(design, by_id, levels_by_pos)
    nominal: list[int] = []
    pts = []
    for i, p in enumerate(design.points):
        lv = levels_by_pos[i] if i < len(levels_by_pos) else None
        if not lv or any(fid not in lv for fid in design.factor_ids):
            nominal.append(i)
            pts.append(p)
            continue
        pts.append(DesignPoint(
            coded=tuple(code_actual(by_id[fid], lv[fid]) for fid in design.factor_ids),
            role=p.role, replicate=p.replicate,
        ))
    return dataclasses.replace(design, points=tuple(pts)), nominal


def _coded_as_run_mixed(design: Design, by_id: dict, levels_by_pos):
    """``coded_as_run`` for a design holding a multi-level categorical.

    The PLANNED design carries each categorical's m pseudo-factor columns;
    the FIT design carries its L-1 contrast columns (``factors.model_columns``)
    coded at the level that ran (``factors.code_vector``), so a collapsed row
    and a canonical row of the same level are coded identically -- the
    pseudo-factor combination is a device for PLACING levels, not a property
    of what ran. ``groups`` maps each fit column to its factor. A position with
    missing levels gets zeros in the fit width and is returned as nominal (the
    caller drops it).
    """
    fids = [fid for fid, _ in factor_columns(design)]
    cols: list[str] = []
    groups: list[str] = []
    for fid in fids:
        for c in model_columns(by_id[fid]):
            cols.append(c)
            groups.append(fid)
    nominal: list[int] = []
    pts = []
    for i, p in enumerate(design.points):
        lv = levels_by_pos[i] if i < len(levels_by_pos) else None
        if not lv or any(fid not in lv for fid in fids):
            nominal.append(i)
            pts.append(DesignPoint(coded=tuple(0.0 for _ in cols), role=p.role,
                                   replicate=p.replicate))
            continue
        coded: list[float] = []
        for fid in fids:
            coded.extend(code_vector(by_id[fid], lv[fid]))
        pts.append(DesignPoint(coded=tuple(coded), role=p.role, replicate=p.replicate))
    return dataclasses.replace(design, points=tuple(pts), factor_ids=tuple(cols),
                               groups=tuple(groups), words=()), nominal


def fit_coordinates_record(planned: Design, fitted: Design,
                           statuses=None) -> dict:
    """What ``effects.json`` records about the rows and coordinates the fit used.

    One entry per FITTED row: the planned (nominal) coding beside the coding
    the regression used, so a reader can audit INV-STAT14 without refitting,
    and -- when ``statuses`` is given -- the row's run status, so a reader can
    see that ``infeasible`` rows were fitted (INV-STAT15) and how many.
    """
    rows = []
    for i, (p, f) in enumerate(zip(planned.points, fitted.points)):
        row = {"role": f.role, "planned": [float(v) for v in p.coded],
               "fitted": [float(v) for v in f.coded]}
        if statuses is not None:
            row["status"] = str(statuses[i])
        rows.append(row)
    out = {"basis": "coded_actual_levels", "factor_ids": list(fitted.factor_ids),
           **({"planned_factor_ids": list(planned.factor_ids),
               "factor_of_column": list(fitted.groups)}
              # Whenever the fit has groups -- even if the planned and fitted
              # column NAMES coincide (L = 4, or a level-space factorial), the
              # columns are contrasts of a factor, not factors.
              if fitted.groups else {}),
           "rows": rows}
    if statuses is not None:
        counts: dict[str, int] = {}
        for st in statuses:
            counts[str(st)] = counts.get(str(st), 0) + 1
        out["rows_by_status"] = dict(sorted(counts.items()))
    return out


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
        # ``factor_id`` rides along so the REALIZED patch can be keyed by factor
        # when the runner records it (``runner._applied_namespace``'s
        # ``applied_patches``). Without it the realized record could only be a
        # LIST, and ``predicates._resolve`` walks dotted paths through dicts
        # only -- there is no list-index token and no ``contains`` operator -- so
        # a manipulation predicate could not address a config_patch factor at
        # all. Verified: ``applied_patches.0.value`` resolves to _MISSING, which
        # fails EVERY row with "the target did not emit it", the same shape that
        # made 115 configurations unusable before ``applied.*`` existed.
        return {"patches": [{
            "factor_id": f.id,
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
    n_configs = _design_centre_configs(design, by_id)
    rows: list[ConfigRow] = []
    for row_index, point in enumerate(design.points):
        levels: dict[str, Any] = {}
        cli_args: list[str] = []
        env: dict[str, Any] = {}
        patches: list[dict] = []
        pinned: dict[str, bool] = {}

        for fid, idxs in factor_columns(design):
            f = by_id[fid]
            level = _decode_factor(f, point, idxs, n_configs=n_configs)
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
    centre = centre_points_record(design, factors)
    cats = categoricals_record(design, factors, rows)
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
        **({"centre_points": centre} if centre is not None else {}),
        **({"categoricals": cats,
            "column_groups": list(design.groups),
            "column_words": [list(w) for w in design.words]} if cats else {}),
    }


def categoricals_record(design: Design, factors, rows) -> list[dict]:
    """``design_matrix.json["categoricals"]``: how the method of replacement
    placed each multi-level categorical -- its pseudo-factor columns, the
    combination -> level map (the COLLAPSING rule, ``factors.level_of_bits``),
    the fit's contrast columns, and how often each level runs at the corners.
    Records the consequences of collapsing rather than leaving them implicit:
    unequal replication and within-factor non-orthogonality."""
    from orchestrator.optimize.factors import n_pseudo

    by_id = {f.id: f for f in factors}
    cols = dict(factor_columns(design))
    out = []
    for fid, idxs in cols.items():
        f = by_id.get(fid)
        if f is None or not is_categorical(f):
            continue
        m = n_pseudo(f)
        L = len(f.levels)
        level_full = design.kind == "mixed_level_full"
        reps = {str(lv): 0 for lv in f.levels}
        for r in rows:
            if r.role == "corner":
                reps[str(r.levels[fid])] += 1
        out.append({
            "factor": fid,
            "levels": list(f.levels),
            "pseudo_factors": [design.factor_ids[j] for j in idxs],
            "contrast_columns": list(model_columns(f)),
            "main_effect_df": L - 1,
            "level_of_combination": {str(b): level_of_bits(f, b)
                                     for b in range(L if level_full else 1 << m)},
            "collapsed": (L < (1 << m)) and not level_full,
            "corner_replication": reps,
            "consequences": (
                "level-space full factorial (no larger than the replacement "
                "fraction): every level combination once, nothing collapsed, "
                "nothing aliased" if level_full else
                f"{(1 << m) - L} surplus pseudo-factor combination(s) collapse onto "
                f"the first-declared level(s), which run twice as often; the "
                f"factor's {L - 1} contrasts are then correlated with each other "
                f"and the intercept (exact (X'X)^-1 inference is used), while "
                f"orthogonality with every other factor's main effect is kept "
                f"(Addelman 1962, proportional frequencies)."
                if L < (1 << m) else
                f"L = 2^{m}: no collapsing; the {L - 1} Walsh contrasts are orthogonal."),
        })
    return out


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
