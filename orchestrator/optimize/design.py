"""Factorial and response-surface design generation.

Pure stdlib arithmetic: a design is a list of ±1-coded points, and for the
orthogonal designs this module emits, every effect estimate has an exact
closed form (contrast / N). That keeps the numerics auditable and keeps
numpy out of the harness.

Fractional designs use published generators. A 2^(k-p) design is built by
taking p base factors' full factorial and defining each remaining factor as
a product of base columns; which products you pick determines the
resolution. ``_GENERATORS`` records the standard choices so the alias
structure matches the textbook rather than whatever this module happens to
compute.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

# Standard generator sets, keyed (n_factors, resolution) -> (n_base,
# generator tuples over base column indices). Sources: Box, Hunter & Hunter,
# *Statistics for Experimenters*, 2e, Table 6.5; Montgomery, *Design and
# Analysis of Experiments*, 8e, Table 8.14.
_GENERATORS: dict[tuple[int, int], tuple[int, tuple[tuple[int, ...], ...]]] = {
    # resolution V — no 2fi aliased with a main effect or another 2fi
    (5, 5): (4, ((0, 1, 2, 3),)),                    # E = ABCD, 16 runs
    (6, 5): (5, ((0, 1, 2, 3, 4),)),                 # F = ABCDE, 32 runs
    (7, 5): (6, ((0, 1, 2, 3),)),                    # G = ABCD, 64 runs
    (8, 5): (6, ((0, 1, 2, 3), (0, 1, 4, 5))),       # G=ABCD, H=ABEF, 64 runs
    # resolution IV — mains clear of 2fi; 2fi aliased in pairs
    (4, 4): (3, ((0, 1, 2),)),                       # D = ABC, 8 runs
    (5, 4): (4, ((0, 1, 2),)),                       # 16 runs
    (6, 4): (4, ((0, 1, 2), (0, 1, 3))),             # 16 runs
    (7, 4): (4, ((0, 1, 2), (0, 1, 3), (0, 2, 3))),  # 16 runs
    (8, 4): (4, ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))),  # 16 runs
    # resolution III — saturated; 2fi aliased onto mains
    (7, 3): (3, ((0, 1), (0, 2), (1, 2), (0, 1, 2))),  # 8 runs
}


@dataclass(frozen=True)
class DesignPoint:
    """One row of the design, in ±1 coded space."""

    coded: tuple[float, ...]
    role: str = "corner"
    replicate: int = 0


@dataclass(frozen=True)
class Design:
    """A generated design plus the provenance needed to defend its claims."""

    points: tuple[DesignPoint, ...]
    factor_ids: tuple[str, ...]
    kind: str = "full"
    resolution: int | None = None
    generators: tuple[tuple[int, ...], ...] = ()

    @property
    def corners(self) -> tuple[DesignPoint, ...]:
        return tuple(p for p in self.points if p.role == "corner")


def min_runs_for(k: int, resolution: int) -> int:
    """Run count of the smallest tabulated design for ``k`` factors.

    Exact only for ``(k, resolution)`` pairs present in ``_GENERATORS``.
    For an untabulated pair (with ``resolution >= 3``) this returns
    ``2 ** k`` — the full factorial's run count — as a *conservative upper
    bound*, not the true minimum. A smaller fractional design may well
    exist for that combination; it simply isn't tabulated here, and this
    module has no way to derive one on the fly. Do not treat the fallback
    value as "the minimum achievable run count" for feasibility decisions —
    check ``(k, resolution) in _GENERATORS`` first, and treat an untabulated
    combination as unknown rather than as "needs the full factorial."
    """
    entry = _GENERATORS.get((k, resolution))
    if entry is None:
        if resolution <= 2:
            raise ValueError("resolution must be >= 3")
        return 2 ** k          # conservative upper bound, NOT the true minimum
    n_base, _ = entry
    return 2 ** n_base


def full_factorial(factor_ids) -> Design:
    """All 2^k corners, in a deterministic order."""
    ids = tuple(factor_ids)
    pts = tuple(
        DesignPoint(coded=tuple(float(v) for v in combo))
        for combo in itertools.product((-1, 1), repeat=len(ids))
    )
    return Design(points=pts, factor_ids=ids, kind="full", resolution=None)


def fractional_factorial(factor_ids, resolution: int) -> Design:
    """A 2^(k-p) design achieving ``resolution`` using published generators."""
    ids = tuple(factor_ids)
    k = len(ids)
    if resolution < 3:
        raise ValueError(
            f"resolution must be >= 3 (got {resolution}); resolution II would "
            f"alias main effects with each other and estimate nothing.",
        )
    entry = _GENERATORS.get((k, resolution))
    if entry is None:
        raise ValueError(
            f"no tabulated resolution-{resolution} design for {k} factors. "
            f"Options: use the full factorial ({2 ** k} runs), reduce the "
            f"factor count, or accept a lower resolution and its aliasing.",
        )
    n_base, gens = entry
    pts = []
    for base in itertools.product((-1, 1), repeat=n_base):
        row = [float(v) for v in base]
        for g in gens:
            row.append(float(math.prod(base[i] for i in g)))
        pts.append(DesignPoint(coded=tuple(row)))
    return Design(
        points=tuple(pts), factor_ids=ids, kind="fractional",
        resolution=resolution, generators=gens,
    )


def with_center_points(design: Design, n: int) -> Design:
    """Append ``n`` replicated center points at the origin.

    Center points buy the pure-error estimate that makes a lack-of-fit test
    possible — without them the campaign cannot say whether its own model
    form is adequate.
    """
    if n < 0:
        raise ValueError(f"center_points must be >= 0 (got {n})")
    origin = tuple(0.0 for _ in design.factor_ids)
    centers = tuple(
        DesignPoint(coded=origin, role="center", replicate=i) for i in range(n)
    )
    return Design(
        points=design.points + centers, factor_ids=design.factor_ids,
        kind=design.kind, resolution=design.resolution,
        generators=design.generators,
    )


def central_composite(factor_ids, *, center_points: int,
                      alpha: float | None = None) -> Design:
    """Corners + axial (star) points + replicated centers.

    ``alpha`` defaults to the rotatable value (2^k)^(1/4), which makes the
    prediction variance depend only on distance from the center.
    """
    ids = tuple(factor_ids)
    k = len(ids)
    if k < 1:
        raise ValueError("central_composite needs at least 1 factor")
    a = float(alpha) if alpha is not None else (2 ** k) ** 0.25

    base = full_factorial(ids)
    axial: list[DesignPoint] = []
    for j in range(k):
        for sign in (-1.0, 1.0):
            coded = [0.0] * k
            coded[j] = sign * a
            axial.append(DesignPoint(coded=tuple(coded), role="axial"))

    combined = Design(
        points=base.points + tuple(axial), factor_ids=ids,
        kind="central_composite", resolution=None,
    )
    return with_center_points(combined, center_points)


def _label(idxs, factor_ids) -> str:
    return "".join(factor_ids[i] for i in sorted(idxs))


def is_orthogonal(design: Design) -> bool:
    """Whether every pair of main-effect columns is orthogonal over corners."""
    corners = design.corners
    k = len(design.factor_ids)
    for i, j in itertools.combinations(range(k), 2):
        if sum(p.coded[i] * p.coded[j] for p in corners) != 0:
            return False
    return all(sum(p.coded[j] for p in corners) == 0 for j in range(k))


def alias_pairs(design: Design) -> list[tuple[str, str]]:
    """Confounded (two-factor-interaction, other-term) label pairs.

    Reports 2fi aliased onto a main effect and 2fi aliased onto another 2fi.
    An empty list means every main effect and two-factor interaction is
    separately estimable — the resolution-V property.
    """
    corners = design.corners
    if not corners:
        return []
    k = len(design.factor_ids)
    ids = design.factor_ids

    mains = {ids[j]: tuple(p.coded[j] for p in corners) for j in range(k)}
    twofi = {
        _label((i, j), ids): tuple(p.coded[i] * p.coded[j] for p in corners)
        for i, j in itertools.combinations(range(k), 2)
    }

    out: list[tuple[str, str]] = []
    aliased_to_main: set[str] = set()
    for label, col in twofi.items():
        for mname, mcol in mains.items():
            if col == mcol:
                out.append((label, mname))
                aliased_to_main.add(label)
    # Only report a 2fi-2fi confounding when neither side is already
    # explained by a main-effect alias above; otherwise this pair is a
    # transitive echo of that same relation (both equal the same main
    # effect's column) and carries no new information.
    for (l1, c1), (l2, c2) in itertools.combinations(twofi.items(), 2):
        if c1 == c2 and l1 not in aliased_to_main and l2 not in aliased_to_main:
            out.append((l1, l2))
    return sorted(out)
