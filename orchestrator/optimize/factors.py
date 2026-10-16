"""Factor declaration parsing for optimization campaigns.

A factor is one knob the campaign varies. ``type`` answers a domain
question, not a statistics question: are values *between* the declared
levels runnable?

  * ``numeric`` — interpolation is meaningful (thresholds, ratios, counts).
    ``grid`` snaps a fitted optimum to a runnable step so ``confirm``
    never tries to run K=4.7.
  * ``choice`` — nothing lives between the levels (policies, mechanisms,
    on/off).
  * ``numeric`` + ``levels_only: true`` — ordered, so interpolation is
    meaningful for MODELLING, but only the declared values are RUNNABLE
    (powers of two, a fixed menu of buffer sizes). Every value produced from
    a coded value snaps to the nearest declared level in the factor's axis
    space (spec 2026-10-16-mixed-level-factors-design.md, feature 2).

The retired vocabulary ``continuous`` / ``ordinal`` / ``categorical`` is
rejected with a pointer to the replacement: it made authors reason about
how fitting works, and the fitting question is fully determined by
``type`` + ``grid``.
"""
from __future__ import annotations

import functools
import math

from dataclasses import dataclass
from typing import Any

VALID_TYPES = ("numeric", "choice")
_CMP_KEYS = frozenset({"observable", "metric", "op", "value", "when", "when_not"})


@dataclass(frozen=True)
class Factor:
    """One declared factor. Immutable so a parsed design can't drift."""

    id: str
    name: str
    type: str
    levels: tuple
    grid: float | None
    screen_levels: tuple
    apply_spec: dict
    manipulation: dict
    relations: tuple[dict, ...]
    #: ``"linear"`` (default) or ``"log"``: the space the ±1 coding is linear
    #: in. A geometric knob (a cache size, a batch size, an interval spanning
    #: orders of magnitude) is coded in log space, so the centre point is the
    #: geometric mean and equal coded steps are equal RATIOS.
    scale: str = "linear"
    #: ``True``: only the declared ``levels`` are runnable, so every value
    #: Nous derives from a coded coordinate (a fitted optimum, an axial or
    #: centre point, a candidate) is the NEAREST DECLARED LEVEL in axis space
    #: (log space under ``scale: log``). Numeric factors only; never with
    #: ``grid`` (two declarations of the runnable set that can disagree).
    levels_only: bool = False


def _normalise_apply(raw: Any, factor_id: str) -> dict:
    """A bare string is CLI-flag shorthand: ``"--queues={level}"``."""
    if isinstance(raw, str):
        return {"kind": "cli_flag", "template": raw}
    if isinstance(raw, dict) and raw.get("kind"):
        return dict(raw)
    raise ValueError(
        f"factor {factor_id!r}: 'apply' must be a template string "
        f"(e.g. \"--queues={{level}}\") or a dict with a 'kind' of "
        f"cli_flag / env_var / config_patch; got {raw!r}",
    )


def _check_manipulation(man: Any, factor_id: str) -> dict:
    if not isinstance(man, dict) or not man:
        raise ValueError(
            f"factor {factor_id!r}: a 'manipulation' check is required — it is "
            f"how Nous verifies the lever actually engaged. Use "
            f"{{observable: <telemetry path>, op: '==', value: '{{level}}'}}.",
        )
    unknown = set(man) - _CMP_KEYS
    if unknown:
        raise ValueError(
            f"factor {factor_id!r}: manipulation has unknown key(s) "
            f"{sorted(unknown)}; allowed: {sorted(_CMP_KEYS)}",
        )
    if "when" in man and "when_not" in man:
        raise ValueError(
            f"factor {factor_id!r}: manipulation may set 'when' or 'when_not', "
            f"not both — they are complementary level guards.",
        )
    if not man.get("op"):
        raise ValueError(f"factor {factor_id!r}: manipulation needs an 'op'.")
    return dict(man)


def _check_relations(rels: Any, factor_id: str) -> tuple[dict, ...]:
    rels = list(rels or [])
    if not any(r.get("kind") == "correctness" for r in rels if isinstance(r, dict)):
        raise ValueError(
            f"factor {factor_id!r}: at least one relation with "
            f"kind: correctness is required. A 'behavioral' relation alone is "
            f"not enough — behavioral violations are recorded as findings and "
            f"never fail the campaign, so nothing would catch a broken lever.",
        )
    for r in rels:
        if r.get("kind") not in ("correctness", "behavioral"):
            raise ValueError(
                f"factor {factor_id!r}: relation {r.get('id')!r} has kind "
                f"{r.get('kind')!r}; must be 'correctness' or 'behavioral'.",
            )
        if not r.get("native_test"):
            raise ValueError(
                f"factor {factor_id!r}: relation {r.get('id')!r} needs a "
                f"'native_test' identifier — the test lives in the TARGET "
                f"repo's own test tree and runs under its own runner.",
            )
    return tuple(dict(r) for r in rels)


def parse_factors(raw: list[dict]) -> list[Factor]:
    """Parse and validate a campaign's ``optimization.factors`` list."""
    if not raw:
        raise ValueError("optimization.factors must declare at least one factor")

    out: list[Factor] = []
    seen: set[str] = set()
    for entry in raw:
        fid = str(entry.get("id") or "")
        if not fid:
            raise ValueError("every factor needs an 'id' (e.g. L1)")
        if fid in seen:
            raise ValueError(f"duplicate factor id {fid!r}")
        seen.add(fid)

        ftype = entry.get("type")
        if ftype not in VALID_TYPES:
            raise ValueError(
                f"factor {fid!r}: type must be 'numeric' or 'choice' (got "
                f"{ftype!r}). Ask: are values BETWEEN the declared levels "
                f"runnable? Yes -> numeric. No -> choice. The older "
                f"continuous/ordinal/categorical vocabulary was retired.",
            )

        levels = tuple(entry.get("levels") or ())
        if len(levels) < 2:
            raise ValueError(
                f"factor {fid!r}: 'levels' needs at least 2 entries "
                f"(got {list(levels)!r})",
            )

        screen = entry.get("screen_levels")
        if screen is not None and ftype == "choice" and len(levels) > 2:
            raise ValueError(
                f"factor {fid!r}: a choice factor with {len(levels)} levels is "
                f"screened at EVERY level (method of replacement), so "
                f"screen_levels does not apply. To screen fewer levels, declare "
                f"fewer levels.",
            )
        if screen is None:
            screen_pair_ = (levels[0], levels[-1])
        else:
            screen_pair_ = tuple(screen)
            if len(screen_pair_) != 2:
                raise ValueError(
                    f"factor {fid!r}: screen_levels must name exactly 2 levels",
                )
            missing = [s for s in screen_pair_ if s not in levels]
            if missing:
                raise ValueError(
                    f"factor {fid!r}: screen_levels {missing!r} are not members "
                    f"of levels {list(levels)!r}",
                )

        grid = entry.get("grid")
        scale = str(entry.get("scale") or "linear")
        if scale not in ("linear", "log"):
            raise ValueError(
                f"factor {fid!r}: scale must be 'linear' or 'log' (got {scale!r})",
            )
        if scale == "log":
            if ftype != "numeric":
                raise ValueError(
                    f"factor {fid!r}: scale: log applies to numeric factors only "
                    f"-- a choice factor has no axis to rescale",
                )
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and v > 0 for v in levels):
                raise ValueError(
                    f"factor {fid!r}: scale: log needs strictly positive levels "
                    f"(got {list(levels)!r}); log space has no zero",
                )
        levels_only = entry.get("levels_only", False)
        if not isinstance(levels_only, bool):
            raise ValueError(
                f"factor {fid!r}: levels_only must be true or false (got "
                f"{levels_only!r})",
            )
        if levels_only:
            _check_levels_only(fid, ftype, levels, grid)
        out.append(Factor(
            id=fid,
            name=str(entry.get("name") or fid),
            type=ftype,
            levels=levels,
            grid=float(grid) if grid is not None else None,
            screen_levels=screen_pair_,
            apply_spec=_normalise_apply(entry.get("apply"), fid),
            manipulation=_check_manipulation(entry.get("manipulation"), fid),
            relations=_check_relations(entry.get("relations"), fid),
            scale=scale,
            levels_only=levels_only,
        ))
    return out


def _check_levels_only(fid: str, ftype: str, levels: tuple, grid) -> None:
    """The hard errors ``levels_only`` admits (spec feature 2, "Validation").

    * on a ``choice`` factor it is redundant -- a choice already runs only its
      levels -- and accepting it would suggest the levels are ORDERED, which a
      choice factor's are not;
    * with ``grid`` it is contradictory: ``grid: 1`` declares every integer in
      range runnable, ``levels_only`` declares only the listed ones; Nous will
      not guess which declaration the author meant;
    * the levels must be distinct numbers: nearest-level snapping is defined
      over a set of points on the axis.
    """
    if ftype != "numeric":
        raise ValueError(
            f"factor {fid!r}: levels_only applies to numeric factors only -- a "
            f"choice factor already runs only its declared levels, and has no "
            f"order for nearest-level snapping to use. Remove levels_only.",
        )
    if grid is not None:
        raise ValueError(
            f"factor {fid!r}: levels_only and grid both declare which values "
            f"are runnable, and they disagree (grid {grid!r} admits values "
            f"between the declared levels; levels_only admits only the "
            f"levels). Keep levels_only for a knob that takes only the listed "
            f"values, or grid for one that takes every multiple of the step.",
        )
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(float(v)) for v in levels):
        raise ValueError(
            f"factor {fid!r}: levels_only needs numeric levels (got "
            f"{list(levels)!r})",
        )
    if len({float(v) for v in levels}) != len(levels):
        raise ValueError(
            f"factor {fid!r}: levels_only needs distinct levels; {list(levels)!r} "
            f"has a duplicate, so the nearest declared level is not unique.",
        )


def screen_pair(f: Factor) -> tuple:
    """The two levels the screening design uses for ``f``."""
    return f.screen_levels


def code_level(f: Factor, level: Any) -> int:
    """Map a real level onto the ±1 coding the design matrix uses."""
    low, high = f.screen_levels
    if level == low:
        return -1
    if level == high:
        return +1
    raise ValueError(
        f"factor {f.id!r}: level {level!r} is not part of the screen pair "
        f"{f.screen_levels!r}; only the screen pair has a ±1 coding.",
    )


def _to_axis(f: Factor, value: Any) -> float:
    """A numeric level in the space the coding is linear in."""
    return math.log(float(value)) if f.scale == "log" else float(value)


def _from_axis(f: Factor, y: float) -> float:
    return math.exp(y) if f.scale == "log" else y


def code_actual(f: Factor, level: Any) -> float:
    """The coded coordinate of a level that ACTUALLY RAN (INV-STAT14).

    The inverse of ``decode_coded`` over everything ``decode_coded`` can
    return, which ``code_level`` (screen pair only) is not:

      * ``choice``: ``-1`` / ``+1`` for the screen pair. A categorical has no
        interior, so a centre point -- which ``matrix._decode_level`` runs at
        the FIRST level -- codes ``-1``, not the design's nominal ``0``.
      * ``numeric``: ``(level - mid) / half`` over the screen pair. A clamped
        axial point codes at the range edge it ran at (``+-1``), not at the
        nominal ``+-1.41`` / ``+-1.68``; a grid-snapped point codes at the
        snapped level. This is the same formula ``decide._axis`` scores
        candidates at, so the fit and the argmax share one coordinate system.
    """
    low, high = f.screen_levels
    if is_categorical(f):
        raise ValueError(
            f"factor {f.id!r} has {len(f.levels)} levels and is coded by "
            f"{len(model_columns(f))} contrast columns, not one coordinate: "
            f"use code_vector",
        )
    if f.type == "choice":
        return float(code_level(f, level))
    lo, hi = _to_axis(f, low), _to_axis(f, high)
    half = (hi - lo) / 2.0
    if half == 0.0:
        raise ValueError(f"factor {f.id!r}: screen pair {f.screen_levels!r} has no width")
    mid = (lo + hi) / 2.0
    return (_to_axis(f, level) - mid) / half


def snap_to_grid(value: float, grid: float | None) -> float | int:
    """Round ``value`` to the nearest multiple of ``grid``.

    Returns an ``int`` when the grid is integral and the snapped value lands
    on a whole number, because the value is rendered straight into the
    target's command line and many targets accept only integers there.
    Verified on a live campaign: a factor declared ``[64, 256]`` with
    ``grid: 1`` produced ``160.0``, and BLIS rejected
    ``--max-num-running-reqs=160.0`` as a usage error — failing 16 of 80
    refine runs even though the value was in range and on the grid.

    ``grid: 1`` means "integral steps", so an integral result should render
    as an integer. A fractional grid (``0.005``) keeps returning a float,
    which is what that author asked for.
    """
    if grid is None:
        return float(value)
    if grid <= 0:
        raise ValueError(f"grid must be > 0 (got {grid!r})")
    snapped = round(float(value) / grid) * grid
    if float(grid).is_integer() and float(snapped).is_integer():
        return int(snapped)
    return snapped


def decode_coded(f: Factor, coded: float) -> Any:
    """Turn a coded (±1-scaled) value back into a runnable level.

    ``choice`` factors have no interior, so the sign picks a declared
    level. ``numeric`` factors interpolate between the screen pair and then
    snap to ``grid`` — so the value handed to ``confirm`` is one the target
    can actually run. A ``levels_only`` numeric snaps to the nearest DECLARED
    level in axis space instead (``snap_to_levels``), so an axial point, a
    centre point or a fitted optimum is always a value the knob takes.
    """
    low, high = f.screen_levels
    if f.type == "choice":
        return high if coded > 0 else low
    lo, hi = _to_axis(f, low), _to_axis(f, high)
    mid = (lo + hi) / 2.0
    half = (hi - lo) / 2.0
    if f.levels_only:
        return snap_to_levels(f, mid + coded * half)
    value = snap_to_grid(_from_axis(f, mid + coded * half), f.grid)

    # CLAMP to the declared range. A central composite places axial points at
    # |coded| = (2^k)^(1/4) > 1 -- 1.68 for k=3 -- so linear extrapolation
    # walks OUTSIDE the levels the author declared. Verified on a live
    # campaign: a factor declared [64, 256] produced MAXRUN=-1 and
    # MAXRUN=-112, i.e. a negative request cap, and the target rejected 16 of
    # 80 refine runs with a usage error.
    #
    # Clamping is the honest repair rather than widening the range: the
    # author declared these bounds, and a value outside them is a
    # configuration they never said was legal (it may be physically
    # meaningless, as a negative cap is). The cost is that axial points
    # collapse onto the range edge, so curvature is estimated over a
    # narrower span than a textbook CCD assumes -- which understates
    # curvature rather than inventing it, and is reported honestly by the
    # lack-of-fit test.
    lo_bound = min(float(low), float(high))
    hi_bound = max(float(low), float(high))
    clamped = min(max(float(value), lo_bound), hi_bound)
    if clamped != float(value):
        value = snap_to_grid(clamped, f.grid)
    return _integral_as_int(f, value)


def runnable_levels(f: Factor) -> list:
    """A ``levels_only`` factor's declared levels inside its screen range,
    ascending on the axis: the set every decoded value is drawn from.

    The screen range bounds it for the same reason ``decode_coded`` clamps an
    ordinary numeric to it: the coded space is [-1, +1] over the screen pair,
    and a level outside that span is one the design never brackets.
    """
    lo_b = min(float(v) for v in f.screen_levels)
    hi_b = max(float(v) for v in f.screen_levels)
    inside = [lv for lv in f.levels if lo_b <= float(lv) <= hi_b]
    return sorted(inside, key=lambda lv: (_to_axis(f, lv), float(lv)))


def snap_to_levels(f: Factor, axis_value: float) -> Any:
    """The declared level nearest ``axis_value`` (a coordinate in the factor's
    AXIS space: ``log(level)`` under ``scale: log``), returned verbatim.

    Clamped to the screen range first (as ``decode_coded`` clamps an ordinary
    numeric -- an axial point at coded 1.68 runs at the edge), then the nearest
    declared level by axis distance. TIES GO TO THE LOWER LEVEL: deterministic,
    and on a geometric knob the cheaper setting. Nearest in AXIS space is the
    right metric because the fitted surface is a polynomial in the axis
    coordinate, so axis distance is what the model's interpolation is linear
    in. The snap only chooses which level RUNS; the
    candidate axis (``decide._axis``) scores EVERY declared level, so the
    recommendation is the fitted argmax over the runnable set, not a rounded
    stationary point.
    """
    levels = runnable_levels(f)
    lo, hi = _to_axis(f, levels[0]), _to_axis(f, levels[-1])
    y = min(max(float(axis_value), lo), hi)
    # Distances are rounded to 12 places so a tie that is exact in real
    # arithmetic (log2 = 8.5 between 2^8 and 2^9) stays a tie in floating point
    # and the documented lower-level rule decides it, not a 1e-16 residue.
    return min(levels, key=lambda lv: (round(abs(_to_axis(f, lv) - y), 12),
                                       _to_axis(f, lv)))


def _integral_as_int(f: Factor, value: Any) -> Any:
    """An integral point of an all-integer factor is an ``int``, not ``20.0``.

    The value is rendered straight onto the target's command line, and
    ``decode_coded``'s float arithmetic turned the centre of ``[8, 20, 32]`` into
    ``--batch-size=20.0`` -- which an integer-parsing target rejects as a usage
    error. Observed on a live target (16 of 80 refine runs failed) and again on
    the first end-to-end run of this kind. An all-integer level list is the
    author's statement of what the knob takes, so a whole number keeps that
    type. A FRACTIONAL point is left as-is: without ``grid`` Nous does not
    decide the knob is integer-only (a threshold declared ``[2, 4]`` may run
    at 3.5); ``validate`` warns about that case instead of guessing.
    """
    integer_levels = all(
        isinstance(lv, int) and not isinstance(lv, bool) for lv in f.levels
    )
    if integer_levels and float(value).is_integer():
        return int(value)
    return value


# ── multi-level categoricals: the method of replacement ─────────────────────
#
# Spec 2026-10-16-mixed-level-factors-design.md, feature 1. A choice factor
# with L > 2 levels occupies m = ceil(log2 L) two-level PSEUDO-FACTOR columns
# in the screen (Addelman 1962; Wu & Hamada, Experiments, ch. 7). A row's
# pseudo signs p_1..p_m give b = sum_i [p_i = +1] 2^(i-1); b < L runs level b,
# b >= L COLLAPSES onto level b - L. The fit codes the level that RAN with
# L-1 Walsh contrasts (products of canonical pseudo signs).


def is_categorical(f: Factor) -> bool:
    """A choice factor with more than two levels: several columns, L-1 df."""
    return f.type == "choice" and len(f.levels) > 2


def n_pseudo(f: Factor) -> int:
    """m = ceil(log2 L) pseudo-factors (1 for every single-column factor)."""
    if not is_categorical(f):
        return 1
    return max(1, (len(f.levels) - 1).bit_length())


def pseudo_ids(f: Factor) -> tuple[str, ...]:
    """The planned design's columns for ``f``: ``C[1]..C[m]``, or ``(id,)``."""
    if not is_categorical(f):
        return (f.id,)
    return tuple(f"{f.id}[{i + 1}]" for i in range(n_pseudo(f)))


def level_of_bits(f: Factor, b: int) -> Any:
    """The level a pseudo-sign combination ``b`` RUNS -- the collapsing rule:
    ``b < L`` is level ``b``; a surplus combination ``b >= L`` falls on level
    ``b - L``, so the first-declared levels (conventionally the baseline) run
    twice as often. Addelman (1962a): collapsing preserves proportional
    frequencies with every other factor, i.e. main-effect orthogonality across
    factors; it costs within-factor orthogonality and equal replication."""
    L = len(f.levels)
    return f.levels[b if b < L else b - L]


def _signs_of(b: int, m: int) -> tuple[float, ...]:
    return tuple(1.0 if (b >> i) & 1 else -1.0 for i in range(m))


def _walsh(mask: int, signs) -> float:
    return math.prod(s for i, s in enumerate(signs) if (mask >> i) & 1)


@functools.lru_cache(maxsize=None)
def _contrast_masks(L: int) -> tuple[int, ...]:
    """The Walsh contrasts (pseudo-sign products, as bitmasks) the fit uses.

    L = 2^m: all 2^m - 1 -- orthogonal, +-1, exactly the columns the generalized
    resolution guarantee is about, so exact alias detection applies unchanged.
    L < 2^m: the first L-1 masks in (weight, value) order that are linearly
    independent with the intercept over the CANONICAL codes of the L levels
    (b = 0..L-1); any such basis spans the same L-1 df main effect, so
    predictions do not depend on the choice.
    """
    m = max(1, (L - 1).bit_length())
    order = sorted(range(1, 1 << m), key=lambda x: (bin(x).count("1"), x))
    if L == 1 << m:
        return tuple(order)
    rows = [[1.0] for _ in range(L)]
    chosen: list[int] = []
    for mask in order:
        cand = [r + [_walsh(mask, _signs_of(b, m))] for b, r in enumerate(rows)]
        if _rank(cand) == len(chosen) + 2:
            rows, chosen = cand, chosen + [mask]
            if len(chosen) == L - 1:
                break
    return tuple(chosen)


def _rank(rows) -> int:
    a = [list(r) for r in rows]
    rank, ncol = 0, len(a[0]) if a else 0
    for c in range(ncol):
        piv = max(range(rank, len(a)), key=lambda r: abs(a[r][c]), default=None)
        if piv is None or abs(a[piv][c]) < 1e-9:
            continue
        a[rank], a[piv] = a[piv], a[rank]
        for r in range(len(a)):
            if r != rank:
                fac = a[r][c] / a[rank][c]
                a[r] = [x - fac * y for x, y in zip(a[r], a[rank])]
        rank += 1
    return rank


def contrast_label(f: Factor, mask: int) -> str:
    """``C[12]`` for the product of pseudo-factors 1 and 2 of ``C``."""
    return f"{f.id}[" + "".join(str(i + 1) for i in range(n_pseudo(f))
                                 if (mask >> i) & 1) + "]"


def model_columns(f: Factor) -> tuple[str, ...]:
    """The FIT's columns for ``f``: ``(id,)``, or its L-1 contrast labels."""
    if not is_categorical(f):
        return (f.id,)
    return tuple(contrast_label(f, mk) for mk in _contrast_masks(len(f.levels)))


def code_vector(f: Factor, level: Any) -> tuple[float, ...]:
    """The coded coordinates of a level that RAN, one per ``model_columns``.

    ``(code_actual(f, level),)`` for a single-column factor; for a categorical
    the Walsh contrasts at the level's CANONICAL code (its own index ``b``),
    so every row that ran a level -- canonical or collapsed onto it -- is coded
    identically (INV-STAT14: code what ran)."""
    if not is_categorical(f):
        return (code_actual(f, level),)
    try:
        b = f.levels.index(level)
    except ValueError:
        raise ValueError(
            f"factor {f.id!r}: level {level!r} is not one of {list(f.levels)!r}",
        ) from None
    signs = _signs_of(b, n_pseudo(f))
    return tuple(_walsh(mk, signs) for mk in _contrast_masks(len(f.levels)))


def is_refinable(f: Factor) -> bool:
    """Whether ``f`` can carry curvature in the refine stage."""
    return f.type == "numeric" and len(f.levels) > 2
