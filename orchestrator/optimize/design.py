"""Factorial and response-surface design generation.

Pure stdlib arithmetic: a design is a list of ±1-coded points, and for the
orthogonal designs this module emits, every effect estimate has an exact
closed form (contrast / N). That keeps the numerics auditable and keeps
numpy out of the harness.

Fractional designs are regular 2^(k-p) designs: the full factorial in
n = k - p base factors, with each remaining factor defined as a product of
base columns; which products you pick determines the resolution.
``_GENERATORS`` records the textbook choices for 4-8 factors (so the alias
structure there matches the textbook rather than whatever this module happens
to compute); ``_construct`` builds a design for every other ``(k,
resolution)``.
"""
from __future__ import annotations

import functools
import itertools
import math
import random
from dataclasses import dataclass

# Standard generator sets, keyed (n_factors, resolution) -> (n_base,
# generator tuples over base column indices). Sources: Box, Hunter & Hunter,
# *Statistics for Experimenters*, 2e, Table 6.5; Montgomery, *Design and
# Analysis of Experiments*, 8e, Table 8.14.
_GENERATORS: dict[tuple[int, int], tuple[int, tuple[tuple[int, ...], ...]]] = {
    # resolution V — no 2fi aliased with a main effect or another 2fi
    (5, 5): (4, ((0, 1, 2, 3),)),                    # E = ABCD, 16 runs
    # F = ABCDE gives a single defining word of length 6, so this design is
    # actually resolution VI. It is tabulated under 5 because VI implies V:
    # every claim a resolution-V campaign makes still holds, so this
    # under-claims rather than over-claims.
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
    #: Which factor's column ``foldover`` negated, or ``None`` for a full
    #: foldover (every column negated). Also carried by ``combine``'s result,
    #: so the combined design records how the aliasing it resolves was broken.
    folded_on: str | None = None
    #: The FACTOR each column belongs to, one entry per column; empty means
    #: every column is its own factor (every two-level design). A multi-level
    #: categorical owns several columns: its pseudo-factors in a planned
    #: mixed-level screen (``mixed_screen``), its L-1 contrasts in a fit design
    #: (``matrix.coded_as_run``).
    groups: tuple[str, ...] = ()
    #: Mixed-level screens only: each column's GF(2) word over the base bits
    #: (the base-column indices whose product it is), the construction's
    #: provenance, recorded in ``design_matrix.json``.
    words: tuple[tuple[int, ...], ...] = ()

    @property
    def corners(self) -> tuple[DesignPoint, ...]:
        return tuple(p for p in self.points if p.role == "corner")


#: Restarts of the seeded column search per base size, for resolution >= 5
#: (resolutions III and IV are reached by a fixed column order; see
#: ``_construct``). Measured at resolution V: weight order alone reaches 6, 8,
#: 11, 17, 22 and 29 factors at 32..1024 runs; 64 restarts add the 23rd factor
#: at 512 runs (the largest known) and a 30th at 1024 (largest known: 33).
_RESTARTS = 64


def _weight(m: int) -> int:
    return bin(m).count("1")


#: The largest k for which a REGULAR resolution-V 2^(k-p) design in 2^n runs
#: is KNOWN: n -> k_max, for n = 4..12. Such a design is a set of k columns of
#: F_2^n no four or fewer of which sum to zero, i.e. the parity-check matrix of
#: a binary linear [k, k - n, >= 5] code, so k_max is the longest such code with
#: redundancy n. For n <= 10 the values are PROVEN maxima: the exact largest
#: dimension of a binary [len, dim, 5] code is known for every len <= 33, and no
#: [34, 24, 5] code exists (Bouyukliev & Varbanov, "Some results for linear
#: binary codes with minimum distance 5", 2004). For n = 11 and 12 they are
#: the BEST KNOWN: a [47, 36, 5] code (C. L. Chen, IEEE Trans. Inform. Theory
#: 37, 1991, p. 1429) and a cyclic [65, 53, 5] code, both listed in Grassl's
#: code tables (codetables.de), where a longer code at the same redundancy is
#: open. Draper & Lin (Technometrics 32, 1990) relate these designs to
#: resolution-III* designs; Chen, Sun & Wu (Int. Statist. Rev. 61, 1993)
#: catalogue the small-run cases.
_RES_V_MAX_FACTORS = {4: 5, 5: 6, 6: 8, 7: 11, 8: 17, 9: 23, 10: 33, 11: 47, 12: 65}

#: The construction refuses a ``(k, resolution >= 5)`` whose greedy search
#: would track more column subsets than resolution V at 100 factors does
#: (``sum_{j=1}^{R-2} C(k, j)``; 166,750). Measured cold, the worst admitted
#: case takes about 2 s (resolution V at 100 factors, VII at 29); resolution V
#: at 150 factors took 10.7 s and resolution VIII grows as C(k, 6). Such a
#: screen is never affordable anyway: resolution V at 100 factors needs at
#: least 8,192 runs by the counting bound. Resolutions III and IV are built by
#: a fixed column order and are not limited.
_MAX_SUBSETS_TRACKED = sum(math.comb(100, j) for j in range(1, 4))


def _subsets_tracked(k: int, resolution: int) -> int:
    return sum(math.comb(k, j) for j in range(1, resolution - 1))


def max_constructible_factors(resolution: int) -> int | None:
    """The largest factor count ``_construct`` accepts at ``resolution``
    (``None``: unlimited, resolutions III and IV)."""
    if resolution < 5:
        return None
    k = resolution
    while _subsets_tracked(k + 1, resolution) <= _MAX_SUBSETS_TRACKED:
        k += 1
    return k


def _pow2_at_least(need: int) -> int:
    n = 0
    while (1 << n) < need:
        n += 1
    return 1 << n


def _counting_bound_runs(k: int, resolution: int) -> int:
    """The theoretical floor on a regular two-level design's run count.

    Rao's (1947) bound for an orthogonal array of strength t = resolution - 1
    with k two-level factors (Hedayat, Sloane & Stufken, *Orthogonal Arrays*,
    1999, Thm 2.1): N >= sum_{i<=e} C(k, i) for t = 2e, plus C(k-1, e) for
    t = 2e + 1 -- k + 1 at resolution III, 2k at IV, 1 + k + C(k, 2) at V.
    Rounded up to a power of two (a regular design's run count) and capped at
    the full factorial. A FLOOR: no design need attain it.
    """
    t = resolution - 1
    e = t // 2
    need = sum(math.comb(k, i) for i in range(e + 1))
    if t % 2:
        need += math.comb(k - 1, e)
    return min(_pow2_at_least(need), 1 << k)


def _smallest_known_runs(k: int, resolution: int) -> int | None:
    """Run count of the smallest regular 2-level design of this resolution
    that is KNOWN to exist, or ``None`` where no catalogue says.

      * III and IV: the counting bound (``_counting_bound_runs``: k + 1 and 2k,
        rounded up to a power of two), which the saturated and the even
        designs attain -- so the minimum among REGULAR designs. (A
        non-regular Plackett-Burman design can be smaller at resolution III.)
      * V: the smallest 2^n whose known maximum (``_RES_V_MAX_FACTORS``)
        reaches k, for k <= 65; ``None`` beyond the catalogue.
      * VI and above: ``None`` -- no catalogue is consulted.

    Never more than the full factorial, 2^k (3 factors at resolution V: 8).
    """
    if resolution <= 4:
        return _counting_bound_runs(k, max(resolution, 3))
    if resolution == 5:
        for n in sorted(_RES_V_MAX_FACTORS):
            if _RES_V_MAX_FACTORS[n] >= k:
                return min(1 << n, 1 << k)
    return None


def _runs_lower_bound(k: int, resolution: int) -> int:
    """DEPRECATED alias of ``_smallest_known_runs`` (kept for one release).

    Always an int, as it used to be: the counting bound where no catalogue
    says. Note the name was never accurate -- see ``_smallest_known_runs``.
    """
    known = _smallest_known_runs(k, resolution)
    return known if known is not None else _counting_bound_runs(k, resolution)


def _construction_start_runs(k: int, resolution: int) -> int:
    """Where ``_construct`` starts its search: a power of two no larger than
    the smallest regular design of ``resolution`` (so starting there loses
    nothing). Resolution III / IV: the counting bound; V and above: the
    resolution-V catalogue, then its counting bound -- below the true minimum
    at VI+, which only costs the search a few failed base sizes.
    """
    if resolution <= 3:
        need = k + 1
    elif resolution == 4:
        need = 2 * k
    else:
        for n in sorted(_RES_V_MAX_FACTORS):
            if _RES_V_MAX_FACTORS[n] >= k:
                return 1 << n
        need = 1 + k + k * (k - 1) // 2
    return _pow2_at_least(need)


def _greedy_columns(n: int, k: int, resolution: int, order) -> list[int] | None:
    """``k`` columns over ``n`` base bits, the first ``n`` the base itself,
    such that no ``resolution - 1`` or fewer of them XOR to zero -- exactly
    "every defining word has length >= resolution".

    ``sums[j]`` holds the XOR of every set of ``j`` chosen columns, for
    ``j <= resolution - 2``. A candidate ``c`` closes a word of length
    ``j + 1`` iff ``c`` is in ``sums[j]``, so accepting only candidates in no
    ``sums[j]`` keeps every word at length >= resolution BY CONSTRUCTION --
    the guarantee does not rest on a table or on a later check.
    """
    depth = max(1, resolution - 2)
    cols = [1 << i for i in range(n)]
    sums: list[set[int]] = [set() for _ in range(depth + 1)]
    for c in cols:
        for j in range(depth, 1, -1):
            sums[j] |= {c ^ x for x in sums[j - 1]}
        sums[1].add(c)
    for c in order:
        if len(cols) == k:
            break
        if c == 0 or any(c in sums[j] for j in range(1, depth + 1)):
            continue
        for j in range(depth, 1, -1):
            sums[j] |= {c ^ x for x in sums[j - 1]}
        sums[1].add(c)
        cols.append(c)
    return cols if len(cols) == k else None


@functools.lru_cache(maxsize=None)
def _construct(k: int, resolution: int) -> tuple[int, tuple[tuple[int, ...], ...]] | None:
    """A regular 2^(k-p) design of at least ``resolution`` for ANY ``k``.

    Well-established constructions, smallest base first:

      * III -- the saturated design: any distinct columns of weight >= 2.
        Reaches 2^n - 1 factors in 2^n runs, which meets the counting bound
        N >= k + 1 (optimal among regular designs).
      * IV  -- the even design (a resolution-III design folded over): only
        ODD-weight columns, so every defining word has even length, hence
        length >= 4. Reaches 2^(n-1) factors in 2^n runs (N = 2k), which
        meets the bound N >= 2k that holds for any strength-3 orthogonal
        array.
      * V and above -- a column set no ``resolution - 1`` or fewer of which
        XOR to zero, built by ``_greedy_columns`` in weight order and then
        over seeded restarts. At resolution V it attains the smallest known
        regular design for every k up to 30 (128 runs to 11 factors, 256 to
        17, 512 to 23, 1024 to 30). Beyond, it needs one more doubling than
        the best known for 31-33, 40-47 and 53-65 factors (and matches it
        for 34-39 and 48-52); past the catalogue it takes 16384 runs for
        69-88 factors and 32768 for 89-100, where the double-error-correcting
        BCH code (columns ``(x, x^3)`` for nonzero x in GF(2^7)) gives up to
        127 factors in 16384 and the counting bound at 100 factors is 8192.
        The design preview reports the run count against
        ``_smallest_known_runs`` / ``_counting_bound_runs``. Refused past
        ``max_constructible_factors`` (see ``_MAX_SUBSETS_TRACKED``). Cached:
        the validator and preview ask repeatedly.

    Returns ``None`` when no generator is needed (the full factorial is
    already the smallest design of that resolution). Deterministic: the same
    ``(k, resolution)`` always yields the same columns.
    """
    if resolution < 3:
        raise ValueError("resolution must be >= 3")
    limit = max_constructible_factors(resolution)
    if limit is not None and k > limit:
        raise ValueError(
            f"{k} factors at resolution {resolution}: Nous constructs resolution "
            f"{resolution} designs for at most {limit} factors (beyond that the "
            f"column search is too costly to run in the validator), and such a "
            f"screen would need at least {_counting_bound_runs(k, resolution)} "
            f"runs by the counting bound anyway. Screen at resolution 4 "
            f"({_counting_bound_runs(k, 4)} runs: main effects clear of every "
            f"two-factor interaction), keep the live factors, and screen those "
            f"at a higher resolution next epoch.",
        )
    n = _construction_start_runs(k, resolution).bit_length() - 1
    while n < k:
        cands = [m for m in range(1, 1 << n) if _weight(m) >= 2]
        if resolution == 4:
            cands = [m for m in cands if _weight(m) % 2 == 1]
        cands.sort(key=lambda m: (_weight(m), m))
        cols = _greedy_columns(n, k, resolution, cands)
        if cols is None and resolution >= 5:
            rng = random.Random(1000 * resolution + k)
            for _ in range(_RESTARTS):
                shuffled = cands[:]
                rng.shuffle(shuffled)
                cols = _greedy_columns(n, k, resolution, shuffled)
                if cols is not None:
                    break
        if cols is not None:
            gens = tuple(tuple(i for i in range(n) if c >> i & 1) for c in cols[n:])
            return n, gens
        n += 1
    return None


def generators_for(k: int, resolution: int) -> tuple[int, tuple[tuple[int, ...], ...]] | None:
    """``(n_base, generators)`` of the design used for ``(k, resolution)``,
    or ``None`` when the full factorial is already the smallest such design.

    The textbook table first (``_GENERATORS``: 4-8 factors at IV, 5-8 at V,
    7 at III), then ``_construct`` for every other combination -- so no
    factor count forces a full factorial at resolution III, IV or V. Raises
    ``ValueError`` past ``max_constructible_factors``.
    """
    if resolution < 3:
        raise ValueError("resolution must be >= 3")
    entry = _GENERATORS.get((k, resolution))
    if entry is not None:
        return entry
    return _construct(k, resolution)


def is_tabulated(k: int, resolution: int) -> bool:
    """Whether a FRACTIONAL design exists for ``(k, resolution)``.

    The name is historical (it predates ``_construct``): it no longer means
    "in the textbook table" but "a fraction smaller than the full factorial
    exists", tabulated or constructed.

    True for every combination the full factorial does not already make
    minimal (tabulated or constructed, see ``generators_for``). False means
    the full factorial IS the smallest design of that resolution -- e.g. 3
    factors at resolution V -- so callers use it.
    """
    return generators_for(k, resolution) is not None


def min_runs_for(k: int, resolution: int) -> int:
    """Run count of the design Nous uses for ``k`` factors at ``resolution``.

    Exact: ``2 ** n_base`` of the tabulated or constructed design, or
    ``2 ** k`` when the full factorial is already minimal. Compare with
    ``_smallest_known_runs`` (the best known construction) and
    ``_counting_bound_runs`` (the theoretical floor).
    """
    entry = generators_for(k, resolution)
    return 2 ** (entry[0] if entry is not None else k)


def full_factorial(factor_ids) -> Design:
    """All 2^k corners, in a deterministic order."""
    ids = tuple(factor_ids)
    pts = tuple(
        DesignPoint(coded=tuple(float(v) for v in combo))
        for combo in itertools.product((-1, 1), repeat=len(ids))
    )
    return Design(points=pts, factor_ids=ids, kind="full", resolution=None)


def fractional_factorial(factor_ids, resolution: int) -> Design:
    """A 2^(k-p) design achieving ``resolution`` (``generators_for``)."""
    ids = tuple(factor_ids)
    k = len(ids)
    if resolution < 3:
        raise ValueError(
            f"resolution must be >= 3 (got {resolution}); resolution II would "
            f"alias main effects with each other and estimate nothing.",
        )
    entry = generators_for(k, resolution)
    if entry is None:
        raise ValueError(
            f"no fractional resolution-{resolution} design exists for {k} "
            f"factors with fewer runs than the full factorial ({2 ** k} runs), "
            f"which is already the smallest design of that resolution: use "
            f"full_factorial.",
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
        generators=design.generators, folded_on=design.folded_on,
        groups=design.groups, words=design.words,
    )


def central_composite(factor_ids, *, center_points: int,
                      alpha: float | None = None) -> Design:
    """Corners + axial (star) points + replicated centers.

    The cube is the full factorial while that is the smallest resolution-V
    design (k <= 4), and a resolution-V FRACTION beyond -- the central
    composite design of Box & Wilson (1951) and Box & Hunter (1957), whose
    cube may be any resolution-V fraction. Resolution V is SUFFICIENT for the
    second-order model (every main effect and 2fi clear of one another, the
    axial and centre points supplying the pure quadratics), not necessary:
    the "small composite" designs of Hartley (1959) and Draper & Lin (1990)
    use a smaller resolution-III* cube, which this function does not build.
    A full 2^k cube made refining ten survivors cost 1,024 corners where 128
    suffice.

    ``alpha`` defaults to the rotatable value (cube runs)^(1/4), which makes
    the prediction variance depend only on distance from the center.
    """
    ids = tuple(factor_ids)
    k = len(ids)
    if k < 1:
        raise ValueError("central_composite needs at least 1 factor")
    base = (fractional_factorial(ids, 5) if is_tabulated(k, 5)
            else full_factorial(ids))
    a = float(alpha) if alpha is not None else len(base.points) ** 0.25
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
    if design.kind == "mixed_level_full":
        return []          # a full factorial aliases nothing
    if is_mixed(design):
        return _mixed_alias_pairs(design)
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


def foldover(design: Design, *, on: str | None = None) -> Design:
    """The fold-over runs: negate every corner column, or only column ``on``.

    A fractional design cannot separate aliased terms; no arithmetic can. What
    resolves the confounding is MORE RUNS — a second block whose sign pattern
    breaks the defining relation that created the alias. That is the paper's
    "registered foldover": it spends budget, and it is spent only when the
    aliasing could change the recommended answer (``decide.alias_consequential``
    is the test, ``policy``'s ``screen -> foldover`` rule is the registration).

    Two flavours, and they resolve DIFFERENT confounding:

      * ``on=None`` — FULL foldover, every column negated. This kills the
        odd-length words of the defining relation, so a resolution-III design
        (2fi aliased onto MAIN effects) becomes resolution IV: every main effect
        is then clear of every two-factor interaction. It does NOT separate 2fi
        from each other, because an even-length word survives negation of every
        column — so a full foldover of a resolution-IV design leaves
        ``AB = CD`` exactly where it was.
      * ``on=<factor id>`` — SINGLE-FACTOR foldover, only that factor's column
        negated. This kills every word CONTAINING that factor, which separates
        every two-factor interaction involving ``on`` from its alias — and,
        because each such alias pair is ``(on-containing, not-on-containing)``
        on a resolution-IV four-factor design, that separates the whole family.
        Verified on ``fractional_factorial("ABCD", 4)``: folding on any single
        factor empties ``alias_pairs(combine(base, fold))``.

    Centre points are REPLICATED at the same count rather than carried over as
    the same rows: they buy the pure-error estimate, and the fold block is a
    fresh set of runs on (possibly) a drifted machine, so it needs its own
    replicates for the pooled pure error to mean anything. ``resolution`` is
    ``None`` on the result because a fold block on its own has no resolution to
    claim — the design whose resolution improved is ``combine``'s output.
    """
    ids = design.factor_ids
    if on is not None and on not in ids:
        raise ValueError(
            f"cannot fold over on {on!r}: no such factor in this design "
            f"(factor_ids={list(ids)}). Pass a declared factor id, or None for "
            f"a full foldover.",
        )
    j = None if on is None else ids.index(on)
    corners = tuple(
        DesignPoint(
            coded=tuple(
                -c if (j is None or k == j) else c for k, c in enumerate(p.coded)
            ),
            role="corner",
        )
        for p in design.corners
    )
    centers = tuple(
        DesignPoint(coded=p.coded, role="center", replicate=p.replicate)
        for p in design.points if p.role == "center"
    )
    return Design(
        points=corners + centers, factor_ids=ids, kind="foldover",
        resolution=None, generators=design.generators, folded_on=on,
        groups=design.groups, words=design.words,
    )


def combine(a: Design, b: Design) -> Design:
    """Both blocks as one design: the matrix the combined fit is estimated on.

    Points are concatenated in ``a``-then-``b`` order, which is the order the
    responses must be supplied in — ``fit_effects`` pairs value ``i`` with
    ``points[i]``, so a caller that concatenates its response vectors the other
    way round would misalign every coefficient. ``kind="combined"`` and
    ``resolution=None`` because the combined design is not a member of any
    tabulated family; what it can estimate is reported by ``alias_pairs``, which
    reads the columns rather than the label.
    """
    if a.factor_ids != b.factor_ids:
        raise ValueError(
            f"cannot combine designs over different factors: {list(a.factor_ids)} "
            f"vs {list(b.factor_ids)}. The combined fit indexes both blocks' "
            f"points by the same column order, so the factor sets must match "
            f"exactly (order included).",
        )
    return Design(
        points=a.points + b.points, factor_ids=a.factor_ids, kind="combined",
        resolution=None, generators=a.generators, folded_on=b.folded_on,
        groups=a.groups, words=a.words,
    )


# ── mixed-level screens: the method of replacement ──────────────────────────
#
# Spec 2026-10-16-mixed-level-factors-design.md, feature 1. Literature:
# Addelman (1962a, b); Wu & Hamada, Experiments, chs. 7-8 (method of
# replacement, 2^m 4^n designs); Wu & Zhang (1993, Biometrika 80) for word
# length with a four-level factor counted ONCE, here extended to 2^m-level
# pseudo-factor subspaces (Mukerjee & Wu 2006, mixed-level regular designs).
# "Resolution" below is that FACTOR-COUNTED word length -- not Deng & Tang's
# (1999, Statistica Sinica 9) generalized resolution for non-regular designs.
# Rao (1947, "Factorial experiments derivable from combinatorial arrangements
# of arrays", JRSS Suppl. 9:128-139) / Hedayat, Sloane & Stufken (1999):
# resolution R <=> orthogonal-array strength R-1; after collapsing, strength
# holds in Addelman's proportional-frequency sense.


def is_mixed(design: Design) -> bool:
    """Whether some factor owns more than one column of ``design``."""
    g = design.groups
    return bool(g) and len(set(g)) < len(g)


def factor_columns(design: Design) -> list[tuple[str, list[int]]]:
    """``(factor_id, column indices)`` in first-appearance order."""
    groups = design.groups or design.factor_ids
    out: dict[str, list[int]] = {}
    for j, g in enumerate(groups):
        out.setdefault(g, []).append(j)
    return list(out.items())


def _span(vectors) -> list[int]:
    """Every nonzero XOR combination of ``vectors`` (bit-masks)."""
    span = [0]
    for v in vectors:
        span += [x ^ v for x in span]
    return span[1:]


def _mixed_runs_lower_bound(blocks, resolution: int) -> int:
    """The df bound: N - 1 >= sum_f (2^m_f - 1) estimable main-effect
    components (valid for every resolution >= III); for R >= V also every
    two-factor-interaction component, sum_{f<g} d_f d_g. A power of two."""
    d = [(1 << m) - 1 for m in blocks]
    need = 1 + sum(d)
    if resolution >= 5:
        need += sum(a * b for a, b in itertools.combinations(d, 2))
    n = 0
    while (1 << n) < need:
        n += 1
    return 1 << n


def _greedy_blocks(n: int, blocks, resolution: int, order) -> list[tuple[int, ...]] | None:
    """``_greedy_columns`` generalized from columns to BLOCKS.

    ``sums[j]`` holds every XOR of j nonzero elements drawn from j DISTINCT
    placed factors, j <= R-2. A factor's block is grown vector by vector; a
    vector ``v`` is accepted iff every NEW element of the block's span is
    nonzero, not already in the block, and in no ``sums[j]`` -- i.e. it closes
    no defining word of length <= R-1 with the factors already placed. So the
    factor-counted resolution holds BY CONSTRUCTION; no table, no later check.
    Returns one tuple of vectors per factor, in ``blocks`` order.
    """
    depth = max(1, resolution - 2)
    sums: list[set[int]] = [set() for _ in range(depth + 1)]
    placed: list[tuple[int, ...] | None] = [None] * len(blocks)
    place_order = sorted(range(len(blocks)), key=lambda i: (-blocks[i], i))
    for fi in place_order:
        vecs: list[int] = []
        elems: set[int] = set()
        for _slot in range(blocks[fi]):
            hit = None
            for v in order:
                new = [v] + [v ^ e for e in elems]
                if any(e == 0 or e in elems for e in new):
                    continue
                if any(e in sums[j] for e in new for j in range(1, depth + 1)):
                    continue
                hit = v
                elems.update(new)
                break
            if hit is None:
                return None
            vecs.append(hit)
        for j in range(depth, 1, -1):
            sums[j] |= {e ^ x for e in elems for x in sums[j - 1]}
        sums[1] |= elems
        placed[fi] = tuple(vecs)
    return placed  # type: ignore[return-value]


@functools.lru_cache(maxsize=None)
def mixed_fraction(blocks: tuple[int, ...], resolution: int):
    """``(n_base, vectors per factor)`` of a regular 2^n design in which factor
    ``f`` owns ``blocks[f]`` independent pseudo-factor columns and every
    defining word -- counted in FACTORS, one nonzero element of each touched
    factor's subspace -- has length >= ``resolution``.

    The base size starts at ``_mixed_runs_lower_bound`` and grows by one bit
    until the greedy (candidates in (weight, value) order, then ``_RESTARTS``
    seeded shuffles -- applied at EVERY resolution here, unlike ``_construct``,
    which restarts only at V and above) succeeds. It always terminates: at
    n = sum(blocks) the unit vectors give the full factorial in the
    pseudo-factors, which has no defining word. Deterministic and cached.
    """
    if resolution < 3:
        raise ValueError("resolution must be >= 3")
    blocks = tuple(int(b) for b in blocks)
    n = max(_mixed_runs_lower_bound(blocks, resolution).bit_length() - 1, max(blocks))
    total = sum(blocks)
    while n < total:
        cands = sorted(range(1, 1 << n), key=lambda m: (_weight(m), m))
        got = _greedy_blocks(n, blocks, resolution, cands)
        if got is None:
            rng = random.Random(7919 * resolution + 31 * total + len(blocks))
            for _ in range(_RESTARTS):
                sh = cands[:]
                rng.shuffle(sh)
                got = _greedy_blocks(n, blocks, resolution, sh)
                if got is not None:
                    break
        if got is not None:
            return n, tuple(got)
        n += 1
    units, i = [], 0
    for b in blocks:
        units.append(tuple(1 << (i + t) for t in range(b)))
        i += b
    return total, tuple(units)


def mixed_screen(factors, *, resolution: int, center_points: int,
                 allow_level_full: bool = True) -> Design:
    """The mixed-level screen: every factor's pseudo-factor columns
    (``factors.pseudo_ids``) over the 2^n full factorial in the base bits,
    each column the product of the base bits in its word, plus centre points.

    ``kind`` is ``"mixed_fraction"`` (``"mixed_full"`` when no generator was
    needed); ``resolution`` is the FACTOR-COUNTED resolution the construction
    guarantees; ``groups`` maps each column to its factor and ``words``
    records each column's base word.
    """
    from orchestrator.optimize.factors import n_pseudo, pseudo_ids

    fs = list(factors)
    blocks = tuple(n_pseudo(f) for f in fs)
    n, vecs = mixed_fraction(blocks, int(resolution))
    if allow_level_full and level_full_runs(fs) <= 1 << n:
        # The LEVEL-SPACE full factorial is no larger than the replacement
        # fraction (stage-1 M4: three 3-level factors and a 2-level one are
        # 54 runs as a factorial, 128 as a resolution-V replacement fraction,
        # because a 3-level factor occupies a 4-slot pseudo-factor subspace).
        # It aliases NOTHING and replicates every level equally, so it is
        # used instead. Non-regular mixed-level orthogonal arrays (OA(18),
        # Xu 2002's algorithmic designs) can be smaller still; they are NOT
        # implemented.
        return with_center_points(_level_full(fs), int(center_points))
    ids: list[str] = []
    groups: list[str] = []
    words: list[tuple[int, ...]] = []
    for f, vs in zip(fs, vecs):
        for cid, v in zip(pseudo_ids(f), vs):
            ids.append(cid)
            groups.append(f.id)
            words.append(tuple(i for i in range(n) if v >> i & 1))
    pts = []
    for base in itertools.product((-1, 1), repeat=n):
        pts.append(DesignPoint(coded=tuple(
            float(math.prod(base[i] for i in w)) for w in words)))
    d = Design(points=tuple(pts), factor_ids=tuple(ids),
               kind="mixed_full" if n == sum(blocks) else "mixed_fraction",
               resolution=int(resolution), groups=tuple(groups),
               words=tuple(words))
    return with_center_points(d, int(center_points))


def mixed_lower_bound(factors, resolution: int) -> int:
    """The df lower bound on the run count of the mixed screen (preview)."""
    from orchestrator.optimize.factors import n_pseudo

    return _mixed_runs_lower_bound(tuple(n_pseudo(f) for f in factors), int(resolution))


def _subspace_elements(design: Design, cols: list[int], fid: str):
    """``(label, column over corners)`` for every nonzero element of one
    factor's pseudo-column subspace; a single column keeps its id."""
    corners = design.corners
    if len(cols) == 1:
        j = cols[0]
        return [(design.factor_ids[j], tuple(p.coded[j] for p in corners))]
    out = []
    for r in range(1, len(cols) + 1):
        for sub in itertools.combinations(range(len(cols)), r):
            lab = f"{fid}[" + "".join(str(i + 1) for i in sub) + "]"
            out.append((lab, tuple(math.prod(p.coded[cols[i]] for i in sub)
                                   for p in corners)))
    return out


def _mixed_alias_pairs(design: Design) -> list[tuple[str, str]]:
    """``alias_pairs`` with word length counted in FACTORS: every element of a factor's
    contrast subspace is a main-effect column, every product of elements of
    two DISTINCT factors a 2fi column. Reports 2fi ~ main and 2fi ~ 2fi
    coincidences (up to sign), with the same transitive-echo rule."""
    elems = {fid: _subspace_elements(design, cols, fid)
             for fid, cols in factor_columns(design)}
    mains = [(lab, col) for es in elems.values() for lab, col in es]
    twofi = []
    for (fa, ea), (fb, eb) in itertools.combinations(elems.items(), 2):
        for la, ca in ea:
            for lb, cb in eb:
                twofi.append((f"{la}{lb}", tuple(x * y for x, y in zip(ca, cb))))
    out: list[tuple[str, str]] = []
    to_main: set[str] = set()
    for lab, col in twofi:
        neg = tuple(-v for v in col)
        for mlab, mcol in mains:
            if col == mcol or neg == mcol:
                out.append((lab, mlab))
                to_main.add(lab)
    for (l1, c1), (l2, c2) in itertools.combinations(twofi, 2):
        if (c1 == c2 or tuple(-v for v in c2) == c1) and l1 not in to_main \
                and l2 not in to_main:
            out.append((l1, l2))
    return sorted(out)


def level_full_runs(factors) -> int:
    """Runs of the full factorial in LEVEL space: prod_categorical L_i x
    2^(number of two-level-screened factors)."""
    from orchestrator.optimize.factors import is_categorical

    return math.prod(len(f.levels) if is_categorical(f) else 2 for f in factors)


def _level_full(factors) -> Design:
    """Every level combination, each categorical level at its CANONICAL
    pseudo-sign code (no collapsed combination is ever run). Same columns and
    groups as ``mixed_screen``; ``kind="mixed_level_full"``; no resolution
    (a full factorial aliases nothing)."""
    from orchestrator.optimize.factors import is_categorical, n_pseudo, pseudo_ids

    ids, groups, axes = [], [], []
    for f in factors:
        m = n_pseudo(f)
        for cid in pseudo_ids(f):
            ids.append(cid)
            groups.append(f.id)
        if is_categorical(f):
            axes.append([tuple(1.0 if (b >> i) & 1 else -1.0 for i in range(m))
                         for b in range(len(f.levels))])
        else:
            axes.append([(-1.0,), (1.0,)])
    pts = tuple(DesignPoint(coded=tuple(v for part in combo for v in part))
                for combo in itertools.product(*axes))
    return Design(points=pts, factor_ids=tuple(ids), kind="mixed_level_full",
                  resolution=None, groups=tuple(groups))


def mixed_screen_options(factors, resolution: int) -> dict:
    """Both candidate screens' corner runs and which ``mixed_screen`` builds:
    ``{"replacement": N, "level_full": M, "chosen": ...}`` (preview, rule 29)."""
    from orchestrator.optimize.factors import n_pseudo

    n, _ = mixed_fraction(tuple(n_pseudo(f) for f in factors), int(resolution))
    rep, full = 1 << n, level_full_runs(factors)
    return {"replacement": rep, "level_full": full,
            "chosen": "level_full" if full <= rep else "replacement"}
