"""Was the information a partial design lost INDEPENDENT of the factor levels?

Why this module exists
----------------------
A real 18-row campaign lost 3 rows (two wall-clock timeouts, one adapter
crash) and Nous logged three generic row failures. The failures were not
generic. Both timeouts sat at ``EV=arc, DEV=sata_ssd, CPU=40GiB``, while both
``EV=lru`` rows at that IDENTICAL corner completed — a perfect 2x2
separation. The eviction policy under study is the one that does the most work
in exactly that region, so dropping those rows deletes the region where the
mechanism matters and biases the fitted ``EV`` coefficient AGAINST ``arc``,
with nothing in any artifact saying so.

Refitting on the completed subset (``stage_runner``'s partial-fit path) is the
right response to information loss. It is the WRONG response, silently, to
information loss that is CORRELATED WITH A LEVEL: a balanced loss widens every
interval, while a level-correlated loss moves the point estimate and leaves the
intervals looking exactly as tight as before. Widening is honest; moving is
not. So the loss has to be measured, not merely counted.

This module is pure arithmetic over ``(levels, excluded)`` pairs. It decides
nothing about the next state — that belongs to the compiled policy — and it
makes no model call. It only answers "is this exclusion pattern
level-correlated, and where?", and the answer is attached to ``effects.json``
and ``recommendation.json`` so the reader who consumes a coefficient sees the
caveat next to it.

Why not a chi-square test (and why not any p-value)
---------------------------------------------------
A screen has 8-18 rows and typically 1-3 exclusions. Every asymptotic
contingency test is invalid there: chi-square needs expected cell counts of
about 5, and with 3 exclusions spread over 2 levels the expected count is 1.5.
Fisher's exact test IS valid at that n, but on a 2x2 table with 3 exclusions
its smallest attainable one-sided p is 0.1 (at n=8, all-on-one-level), so at
any conventional alpha the BLIS pattern — the exact defect this module exists
to catch — comes back "not significant". A test that cannot reject on its own
motivating example is worse than no test: it launders the defect as a checked
null.

So the criterion is DETERMINISTIC and stated in the name of the rule, not a
p-value:

  ``all_exclusions_on_one_level`` — every excluded row shares one level of
  this factor, AND at least two rows in the design carried that level, AND at
  least one row at a DIFFERENT level completed. That last clause is what
  separates a real asymmetry from an artefact of a factor that had only one
  level in the fitted subset at all.

The one-sided reading is deliberate: this asks "did the loss concentrate?",
never "is the loss random?". A concentrated loss is actionable (re-measure that
level, or report the coefficient as caveated); a diffuse loss is already
handled by the widened intervals. The exact one-sided hypergeometric tail IS
computed and reported alongside — ``concentration_p`` — because a reader
comparing two campaigns wants a number, and because at larger n it is the
right statistic. It is REPORTED, never the trigger: ``flagged`` is the
deterministic rule's verdict. Naming both, with the trigger being the one that
can actually fire at n=8, is the honest arrangement.

Which exclusions count as EVIDENCE OF BIAS, and which do not
-------------------------------------------------------------
Not every excluded row is a hole in the design, and the difference decides
whether concentration means anything at all:

  * ``failed_to_measure`` / ``no_metric`` — the configuration is ADMISSIBLE and
    the instrument could not measure it. The region is missing from the fit but
    present in ``X_valid``, so a coefficient estimated without it is estimated
    over a biased subset of the space it claims to describe. Concentration here
    is evidence of bias.
  * ``infeasible`` — the configuration RAN, produced trustworthy numbers, and
    violated a declared constraint. It is excluded from the fit by design (spec
    §6.4) and it is not missing information: it is information, namely that the
    point is outside ``X_valid``. A CONSTRAINED design routinely has every
    inadmissible corner on one level of one factor — that is what a constraint
    boundary looks like — so treating concentration here as bias would flag
    every constrained campaign ever run and would be wrong about all of them.
    Measured: on ``SURFACES["sla"]`` the refine fit excludes both infeasible
    rows at ``A=16``, a perfect concentration that means only "the p99 ceiling
    binds at high A".
  * ``rejected`` — the row ran and its numbers are untrustworthy. Neither a
    measurement nor information about the space. Treated like ``infeasible``
    here (not counted as bias evidence) because a rejected row is usually a
    manipulation or ceiling verdict that is itself a fact about that level, and
    because the conservative direction for a NEW flag is to fire on the case it
    was built for rather than on every case that resembles it. A concentrated
    rejection pattern is still visible in ``by_level`` for a reader.

So ``analyse`` takes ``bias_excluded`` — the rows whose loss can bias a
coefficient — separately from ``excluded``, the rows left out of the fit for any
reason. ``by_level`` counts ALL exclusions (a reader needs the whole table);
only ``flagged`` / ``level_correlated`` / ``cells`` read the bias subset.

Per-factor AND per-cell, because the BLIS pattern implicates both
------------------------------------------------------------------
Per-factor alone would flag ``EV`` (both losses at ``arc``) and would ALSO
flag ``DEV`` and ``CPU``, since both losses happened to share those levels too
— three flags for what is one region. Per-cell alone would report the corner
``(arc, sata_ssd, 40GiB)`` and say nothing about which coefficient a reader
should distrust. Both are needed and they answer different questions:

  * ``factors`` — WHICH COEFFICIENT is not safe to read at face value. This is
    the field the caveat on ``effects.json`` is keyed by.
  * ``cells`` — WHERE in the design the hole is, so the next epoch knows which
    configuration to re-measure (or to declare inadmissible). A cell is
    reported when every row at that combination was excluded and the
    combination has a completed SIBLING differing in exactly one factor — the
    2x2 separation, which is the pattern that says "this corner, not this
    level" and names the factor whose level flipped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import comb
from typing import Any

#: Minimum rows carrying a level before "every exclusion landed here" is a
#: claim about that LEVEL rather than about a level the design barely visited.
#: At 1 the level has a single row, so "every exclusion is at this level" and
#: "this one row failed" are the same statement and the former adds nothing.
#:
#: WHAT THIS DOES **NOT** DO, stated because the obvious reading is wrong: it
#: does not stop a design with ONE exclusion from flagging several factors. One
#: lost row shares one level of EVERY factor, so on the motivating case (row 7
#: of a 2^3 screen) ``EV``, ``DEV`` and ``CPU`` are all flagged. That is the
#: HONEST answer, not a false positive: a single lost row carries no information
#: about which of the three factors is responsible, so naming one of them would
#: be an invention. ``cells`` is what localises the region; ``factors`` is the
#: list of coefficients a reader must not take at face value, and with one
#: exclusion that list is genuinely all of them.
MIN_ROWS_AT_LEVEL = 2


@dataclass(frozen=True)
class FactorImbalance:
    """One factor's exclusion pattern across its levels."""

    factor_id: str
    #: level -> (rows at that level, rows excluded at that level, rows excluded
    #: for a BIAS-RELEVANT reason at that level). Keys are rendered as strings
    #: because a level may be an int, a float or a string and this dataclass is
    #: serialised straight into JSON. All three counts are reported: a reader
    #: needs the whole table, and the third is the only one ``flagged`` reads.
    by_level: dict[str, tuple[int, int, int]]
    flagged: bool
    #: The level every exclusion landed on, when ``flagged``; else ``None``.
    concentrated_at: str | None
    #: Exact one-sided hypergeometric tail: the probability that a uniformly
    #: random choice of which ``n_excluded`` rows to lose would put AT LEAST
    #: this many of them on ``concentrated_at``. REPORTED, never the trigger —
    #: see the module docstring on why a p-value cannot gate this at n=8.
    concentration_p: float | None
    rule: str


@dataclass(frozen=True)
class CellHole:
    """A design cell every row of which was excluded, with a completed sibling.

    ``differs_from_sibling_in`` names the single factor whose level differs
    between this hole and a cell that DID complete. That is the 2x2 separation
    the BLIS defect showed: the corner is not universally unmeasurable, it is
    unmeasurable at one level of one factor while the same corner at another
    level of that factor measured fine.
    """

    levels: dict
    n_rows: int
    sibling_levels: dict
    differs_from_sibling_in: str


@dataclass(frozen=True)
class ExclusionBalance:
    """The whole verdict: is the partial design's loss level-correlated?"""

    n_rows: int
    n_excluded: int
    #: Of ``n_excluded``, how many were excluded for a reason whose loss can
    #: BIAS a coefficient (``failed_to_measure`` / ``no_metric``) rather than
    #: for a reason that is itself information about the space (``infeasible``)
    #: or about the row (``rejected``). Only these drive ``level_correlated``.
    n_bias_excluded: int = 0
    factors: tuple[FactorImbalance, ...] = ()
    cells: tuple[CellHole, ...] = ()

    @property
    def level_correlated(self) -> bool:
        """True when ANY factor's exclusions concentrated on one level.

        Cells alone do not set this: a cell hole with no completed sibling is a
        region the design never covered, which is a coverage fact rather than a
        bias in a coefficient. ``flagged_factors`` is what the caveat keys on.
        """
        return any(f.flagged for f in self.factors)

    @property
    def flagged_factors(self) -> tuple[str, ...]:
        return tuple(f.factor_id for f in self.factors if f.flagged)

    def as_dict(self) -> dict:
        """The JSON shape written into ``effects.json`` / ``recommendation.json``."""
        return {
            "n_rows": self.n_rows,
            "n_excluded": self.n_excluded,
            "n_bias_excluded": self.n_bias_excluded,
            "level_correlated": self.level_correlated,
            "flagged_factors": list(self.flagged_factors),
            "factors": [
                {
                    "factor_id": f.factor_id,
                    "by_level": {
                        k: {"rows": v[0], "excluded": v[1],
                            "excluded_bias_relevant": v[2]}
                        for k, v in sorted(f.by_level.items())
                    },
                    "flagged": f.flagged,
                    "concentrated_at": f.concentrated_at,
                    "concentration_p": f.concentration_p,
                    "rule": f.rule,
                }
                for f in self.factors
            ],
            "cells": [
                {
                    "levels": c.levels,
                    "n_rows": c.n_rows,
                    "sibling_levels": c.sibling_levels,
                    "differs_from_sibling_in": c.differs_from_sibling_in,
                }
                for c in self.cells
            ],
        }

    def caveat(self) -> str:
        """One sentence a reader of a coefficient must not be able to miss."""
        if not self.level_correlated:
            return ""
        parts = []
        for f in self.factors:
            if not f.flagged:
                continue
            parts.append(f"{f.factor_id} (all at {f.concentrated_at})")
        where = ""
        if self.cells:
            where = "; unmeasured cell(s): " + ", ".join(
                f"{c.levels} (sibling {c.sibling_levels} differing only in "
                f"{c.differs_from_sibling_in} completed)"
                for c in self.cells
            )
        return (
            f"{self.n_excluded} of {self.n_rows} row(s) were excluded from this "
            f"fit and the exclusions are NOT independent of the factor levels: "
            + ", ".join(parts)
            + ". The estimate(s) for those factor(s) are biased by the missing "
            f"region, not merely widened by it, so they must not be read as "
            f"certified{where}."
        )


def _key(v: Any) -> str:
    """Stable string key for a level value.

    Levels can be ``int``, ``float`` or ``str`` and the verdict is serialised
    to JSON, whose object keys are strings. ``2`` and ``2.0`` collapse to the
    same key deliberately: they are the same level (``factors._decode_level``
    can produce either representation for one declared level), and treating
    them as two would split a level's row count in half and defeat
    ``MIN_ROWS_AT_LEVEL``.
    """
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _hypergeometric_upper_tail(n: int, k: int, m: int, x: int) -> float:
    """P(X >= x) for X ~ Hypergeometric(population n, successes m, draws k).

    ``n`` rows, ``m`` of which carry the level in question, ``k`` rows lost at
    random; the tail is the chance that at least ``x`` of the lost rows carried
    that level. Exact, in integer arithmetic via ``math.comb`` — no scipy, and
    no continuity correction to be wrong about at n=8.
    """
    if k <= 0 or m <= 0 or n <= 0:
        return 1.0
    total = comb(n, k)
    if total == 0:
        return 1.0
    hi = min(k, m)
    acc = 0
    for i in range(max(x, 0), hi + 1):
        if k - i > n - m:
            continue
        acc += comb(m, i) * comb(n - m, k - i)
    return acc / total


def factor_imbalance(rows, factor_id: str) -> FactorImbalance:
    """One factor's exclusion pattern. ``rows`` is ``(levels, excluded, bias)``.

    ``excluded`` is "left out of the fit for any reason"; ``bias`` is the subset
    whose loss can bias a coefficient. ``by_level`` counts both. ``flagged``
    reads ONLY ``bias`` — see the module docstring on why a constrained design's
    infeasible corners concentrate on one level by construction and mean nothing
    about bias.

    The trigger is the deterministic ``all_exclusions_on_one_level`` rule and
    the hypergeometric tail is reported beside it rather than gating it.
    """
    by_level: dict[str, list[int]] = {}
    for levels, excluded, bias in rows:
        if factor_id not in levels:
            continue
        k = _key(levels[factor_id])
        slot = by_level.setdefault(k, [0, 0, 0])
        slot[0] += 1
        if excluded:
            slot[1] += 1
        if bias:
            slot[2] += 1

    n_rows = sum(v[0] for v in by_level.values())
    n_bias = sum(v[2] for v in by_level.values())
    hit = [k for k, v in by_level.items() if v[2] > 0]

    flagged = False
    at: str | None = None
    p: float | None = None
    rule = "all_exclusions_on_one_level"

    if n_bias > 0 and len(hit) == 1 and len(by_level) >= 2:
        at = hit[0]
        rows_at, _exc_at, bias_at = by_level[at]
        # A level with only one row in the design cannot support the claim.
        # And at least one row at a DIFFERENT level must have COMPLETED --
        # otherwise "the exclusions concentrated at this level" is true only
        # because no other level produced a measurement either.
        other_complete = any(
            v[0] - v[1] > 0 for k, v in by_level.items() if k != at
        )
        if rows_at >= MIN_ROWS_AT_LEVEL and other_complete:
            flagged = True
            p = _hypergeometric_upper_tail(n_rows, n_bias, rows_at, bias_at)

    if p is None and n_bias > 0 and hit:
        # Report the tail for the most-affected level even when the
        # deterministic rule did not fire, so a reader comparing campaigns has
        # the number in every case rather than only in the flagged one.
        worst = max(hit, key=lambda k: (by_level[k][2], by_level[k][0]))
        p = _hypergeometric_upper_tail(
            n_rows, n_bias, by_level[worst][0], by_level[worst][2],
        )

    return FactorImbalance(
        factor_id=factor_id,
        by_level={k: (v[0], v[1], v[2]) for k, v in by_level.items()},
        flagged=flagged, concentrated_at=at, concentration_p=p, rule=rule,
    )


def cell_holes(rows, factor_ids) -> tuple[CellHole, ...]:
    """Design cells lost to a BIAS-RELEVANT exclusion, with a completed sibling.

    A cell is a distinct combination of every factor's level. It is a HOLE when
    every row at that combination was excluded AND at least one of those
    exclusions was bias-relevant -- a cell that is merely INFEASIBLE is not a
    hole, it is the constraint boundary, and reporting it as one would tell the
    next epoch to re-measure a configuration that is genuinely inadmissible.

    Reported only when some OTHER cell differing in exactly one factor completed
    at least one row: that neighbour is what makes the hole a 2x2 separation
    attributable to a level rather than a corner the design never reached.
    """
    ids = tuple(factor_ids)
    cells: dict[tuple, list[int]] = {}
    reps: dict[tuple, dict] = {}
    for levels, excluded, bias in rows:
        if any(fid not in levels for fid in ids):
            continue
        key = tuple(_key(levels[fid]) for fid in ids)
        slot = cells.setdefault(key, [0, 0, 0])
        slot[0] += 1
        if excluded:
            slot[1] += 1
        if bias:
            slot[2] += 1
        reps.setdefault(key, {fid: levels[fid] for fid in ids})

    out: list[CellHole] = []
    for key, (n, n_exc, n_bias) in sorted(cells.items()):
        if n_bias == 0 or n_exc != n:
            continue
        # One entry per (hole, differing factor) pair, not one per hole. A hole
        # in a 2^3 design has up to k one-factor siblings, and each names a
        # DIFFERENT factor whose level flip made the corner measurable -- which
        # is the fact the next epoch acts on. Reporting only the first (as an
        # early `break` would) hides the others and makes the reported factor an
        # artefact of dict iteration order rather than of the design.
        # Deterministic: `sorted` on both loops, so repeated calls on identical
        # input produce byte-identical output, as every writer in this package
        # guarantees.
        for other, (on, oexc, _ob) in sorted(cells.items()):
            if on - oexc <= 0:
                continue
            diff = [i for i in range(len(ids)) if key[i] != other[i]]
            if len(diff) == 1:
                out.append(CellHole(
                    levels=reps[key], n_rows=n, sibling_levels=reps[other],
                    differs_from_sibling_in=ids[diff[0]],
                ))
    return tuple(out)


def analyse(rows, factor_ids) -> ExclusionBalance:
    """The whole verdict over ``(levels, excluded, bias_relevant)`` triples.

    ``factor_ids`` should be the ids actually CARRIED IN THE FIT
    (``_design_factor_ids``'s output), because the claim being made is about a
    fitted coefficient. A factor held fixed for this stage has one level in
    every row, so it can never be flagged anyway -- but passing the fitted set
    keeps the artifact's ``factors`` list aligned with the coefficients a reader
    is deciding whether to trust.

    A two-tuple row is accepted and read as "excluded, and bias-relevant",
    because that is the only sensible reading for a caller that does not
    classify reasons -- and it keeps the pure-function tests of the DETECTOR
    independent of ``stage_runner``'s reason vocabulary.
    """
    ids = tuple(factor_ids)
    norm = [
        (r[0], r[1], (r[2] if len(r) > 2 else r[1])) for r in rows
    ]
    n_exc = sum(1 for r in norm if r[1])
    n_bias = sum(1 for r in norm if r[2])
    if not norm or n_exc == 0:
        return ExclusionBalance(
            n_rows=len(norm), n_excluded=n_exc, n_bias_excluded=n_bias,
        )
    return ExclusionBalance(
        n_rows=len(norm), n_excluded=n_exc, n_bias_excluded=n_bias,
        factors=tuple(factor_imbalance(norm, fid) for fid in ids),
        cells=cell_holes(norm, ids),
    )


# ─── the identifiability floor (FIX 1's part b) ─────────────────────────────


@dataclass(frozen=True)
class Identifiability:
    """Which factors a partial row subset can still estimate a coefficient for.

    ``len(keep) >= 2`` is a FIT-ARITHMETIC floor: it says the normal equations
    have rows. It says nothing about whether any particular coefficient is
    IDENTIFIABLE. A factor every one of whose retained rows sits at the same
    level has a constant column in the reduced model matrix; that column is
    collinear with the intercept, ``_solve_normal_equations`` raises "design
    matrix is singular", and the campaign dies at the fit with a message about
    matrix rank rather than about the factor that lost a level.

    So the check is made here, by name, BEFORE the solve: a factor with fewer
    than two distinct retained levels is DROPPED from the fitted set and said
    to be dropped. Dropping rather than aborting, because the alternative
    discards every surviving coefficient to protect one that was never
    estimable — which is precisely the "throw away 15 valid measurements"
    behaviour the partial fit exists to end. The dropped factor is named in
    ``fit_exclusions.json`` and its absence from ``fitted_ids`` is what a
    reader sees; a coefficient that is silently absent would be worse than one
    that is loudly missing.

    An empty ``estimable`` is the one case that must still abort: no factor has
    two levels, so there is no model to fit at all.
    """

    estimable: tuple[str, ...]
    dropped: tuple[str, ...]
    #: factor_id -> the distinct retained levels, for the abort/log message.
    levels_retained: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _rank(cols: list[list[float]], *, tol: float = 1e-9) -> int:
    """Rank of a small matrix by Gaussian elimination. No numpy.

    ``effects.py`` keeps numpy out of this package deliberately (every number
    auditable by reading it), and the matrices here are tiny — at most a few
    dozen columns — so elimination with partial pivoting is both sufficient and
    consistent with how ``_solve_normal_equations`` already works.
    """
    m = [list(c) for c in cols]
    n_rows = len(m[0]) if m else 0
    rank = 0
    used = [False] * n_rows
    for col in m:
        # find a pivot row not already used
        piv, best = -1, tol
        for r in range(n_rows):
            if not used[r] and abs(col[r]) > best:
                piv, best = r, abs(col[r])
        if piv < 0:
            continue
        used[piv] = True
        rank += 1
        for other in m:
            if other is col:
                continue
            f = other[piv] / col[piv]
            if f:
                for r in range(n_rows):
                    other[r] -= f * col[r]
    return rank


def model_is_full_rank(design, *, include_interactions: bool = True) -> bool:
    """Can the model ``fit_effects`` would build be solved on THIS design?

    WHY THE PER-FACTOR LEVEL CHECK IS NOT ENOUGH, and this is a defect the
    mutation harness surfaced rather than a hypothetical. A design can retain two
    distinct levels of every factor — so ``identifiable_factors`` passes — and
    still be rank-deficient for the FULL model, because ``fit_effects`` also
    fits every two-factor interaction. Measured on the 2^3 screen with corners 3
    and 5 excluded: A, B and C each keep 3 levels, yet the seven-term model
    (intercept + 3 mains + 3 interactions) has rank 6 over the six surviving
    corners, and ``_solve_normal_equations`` raises "design matrix is singular"
    — an exception about matrix rank escaping ``run_stage`` instead of a decision
    about what is estimable.

    Six corners cannot support seven terms; that is arithmetic, not a bug. The
    principled response is the same one ``effects.py`` already takes for aliased
    columns: fit fewer terms and say so. The caller uses this to decide whether
    to drop the interaction block, exactly as it uses ``identifiable_factors`` to
    decide whether to drop a factor.

    Mirrors ``fit_effects``' column construction, including its ALIAS-CLASS
    collapse (a duplicate or negated column is not added), so the rank computed
    here is the rank of the matrix that will actually be solved.
    """
    import itertools as _it

    pts = design.points
    ids = tuple(design.factor_ids)
    if not pts:
        return False
    cols: list[list[float]] = [[1.0] * len(pts)]
    seen: dict[tuple[float, ...], int] = {}
    for j in range(len(ids)):
        col = [p.coded[j] for p in pts]
        seen.setdefault(tuple(col), len(cols))
        cols.append(col)
    if include_interactions and len(ids) >= 2:
        for i, j in _it.combinations(range(len(ids)), 2):
            col = [p.coded[i] * p.coded[j] for p in pts]
            key = tuple(col)
            neg = tuple(-v for v in col)
            if key in seen or neg in seen:
                continue          # aliased: fit_effects adds no column either
            seen[key] = len(cols)
            cols.append(col)
    if any(p.role == "axial" for p in pts):
        for j in range(len(ids)):
            cols.append([p.coded[j] ** 2 for p in pts])
    return _rank(cols) == len(cols)


def identifiable_factors(kept_levels: list[dict], factor_ids) -> Identifiability:
    """Split ``factor_ids`` into estimable and not, over the RETAINED rows.

    ``kept_levels`` is one levels dict per row that survived the exclusion.
    """
    ids = tuple(factor_ids)
    seen: dict[str, set[str]] = {fid: set() for fid in ids}
    for levels in kept_levels:
        for fid in ids:
            if fid in levels:
                seen[fid].add(_key(levels[fid]))
    est = tuple(fid for fid in ids if len(seen[fid]) >= 2)
    drop = tuple(fid for fid in ids if len(seen[fid]) < 2)
    return Identifiability(
        estimable=est, dropped=drop,
        levels_retained={fid: tuple(sorted(seen[fid])) for fid in ids},
    )
