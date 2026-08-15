"""Factor declaration parsing for optimization campaigns.

A factor is one knob the campaign varies. ``type`` answers a domain
question, not a statistics question: are values *between* the declared
levels runnable?

  * ``numeric`` — interpolation is meaningful (thresholds, ratios, counts).
    ``grid`` snaps a fitted optimum to a runnable step so ``confirm``
    never tries to run K=4.7.
  * ``choice`` — nothing lives between the levels (policies, mechanisms,
    on/off).

The retired vocabulary ``continuous`` / ``ordinal`` / ``categorical`` is
rejected with a pointer to the replacement: it made authors reason about
how fitting works, and the fitting question is fully determined by
``type`` + ``grid``.
"""
from __future__ import annotations

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
        ))
    return out


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
    can actually run.
    """
    low, high = f.screen_levels
    if f.type == "choice":
        return high if coded > 0 else low
    mid = (float(low) + float(high)) / 2.0
    half = (float(high) - float(low)) / 2.0
    value = snap_to_grid(mid + coded * half, f.grid)

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
        return snap_to_grid(clamped, f.grid)
    return value


def is_refinable(f: Factor) -> bool:
    """Whether ``f`` can carry curvature in the refine stage."""
    return f.type == "numeric" and len(f.levels) > 2
