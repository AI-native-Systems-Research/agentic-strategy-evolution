"""The recommendation: x-hat = argmax over X_valid of the fitted response.

Spec §3.3. A stationary point of a quadratic is where the gradient vanishes —
which is a saddle or a minimum as readily as a maximum, and which ignores
choice factors entirely. Observed on a live campaign: the confirmed
"optimum" was 38% below a corner the screen had already measured. The paper's
recommendation is enumeration over the valid space instead; for the small
spaces this kind handles that is exact and needs no model judgement.

Three properties the stationary-point solve could not have:

  * a SADDLE is correctly rejected. ``solve_stationary_point`` reports the
    point where the gradient vanishes and says nothing about whether it is a
    maximum; on ``synthetic.SURFACES["saddle"]`` that point is the worst
    place to sit along one axis. Enumeration compares predictions, so the
    curvature's sign is accounted for without ever forming a Hessian.
  * CHOICE factors participate. There is no gradient in a categorical
    direction, so the solve could only ever hold such a factor at one level
    and optimize the rest around it — which loses the optimum outright when
    the numeric optimum flips with the choice level
    (``SURFACES["choice_x_numeric"]``).
  * the answer is always INSIDE the declared space. Every candidate level
    comes from ``decode_coded``, which snaps to the author's grid and clamps
    to the declared range, so a recommendation is by construction a
    configuration the target can run.

The cost is exponential in the number of fitted factors: at most 9 points per
refinable numeric axis and 2 per choice/two-level axis, so k=8 refinable
numerics would be 9^8. That is far outside what this kind's designs support
(``design.min_runs_for`` caps k at 8 and a refine stage rarely carries more
than 3), and the validator's run-budget rules bind first, so the enumeration
is left exact rather than replaced by a search.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from orchestrator.optimize.effects import Fit
from orchestrator.optimize.factors import Factor, decode_coded, is_refinable


@dataclass(frozen=True)
class Candidate:
    """One point of X_valid: its real levels, its coding, its prediction."""

    levels: dict
    coded: dict
    predicted: float


def predict(fit: Fit, coded: dict) -> float:
    """intercept + sum over every fitted term of estimate * product(coded).

    ``fit.quadratic`` terms carry ``terms == (fid, fid)``, so the same
    product form covers curvature without a special case.
    """
    y = float(fit.intercept)
    for e in list(fit.effects) + list(fit.quadratic):
        y += e.estimate * math.prod(float(coded[t]) for t in e.terms)
    return y


def _axis(f: Factor, *, max_points: int = 9) -> list[tuple[float, object]]:
    """The ``(coded, level)`` pairs factor ``f`` can take in a candidate.

    A ``choice`` factor and a two-level numeric have nothing between their
    screen levels, so the axis is exactly the coded pair. A refinable
    numeric gets up to ``max_points`` evenly spaced coded points decoded
    through ``decode_coded`` — which snaps to the declared grid and clamps to
    the declared range — then DE-DUPLICATED BY DECODED LEVEL, because a
    coarse grid maps several coded values onto one runnable level and
    enumerating the duplicate would only re-predict the same point at a
    slightly different coding.

    The coding returned for an interior point is re-derived from the level
    (``(level - mid) / half``) rather than kept from the loop variable: the
    level is what will actually run, so the prediction must be evaluated at
    the coding of THAT level, not of the unsnapped request.
    """
    low, high = f.screen_levels
    # `not is_refinable(f)` is the LOAD-BEARING half and it already subsumes
    # the choice test — `is_refinable` is `type == "numeric" and len(levels) >
    # 2`, so a choice factor is never refinable (verified exhaustively over
    # every (type, n_levels) a parsed Factor can hold; VALID_TYPES has two
    # members and parse_factors enforces len(levels) >= 2). The choice clause
    # is kept as deliberate redundancy: it says at the read site why a
    # categorical has no interior, rather than making the reader unfold
    # `is_refinable` to find out.
    #
    # DO NOT "simplify" this by keeping the choice clause and dropping the
    # other one. That is the mutation that offers a factor declared [2, 16]
    # the nine levels 2/4/6/7/9/11/12/14/16 — configurations the author never
    # said were runnable, from a fit built on two points that has no evidence
    # about anything between them. It went undetected by the entire suite
    # until `test_axis_restricts_a_two_level_numeric_to_its_screen_pair`;
    # that test and its space-level sibling are what fail now.
    if f.type == "choice" or not is_refinable(f):
        return [(-1.0, low), (1.0, high)]
    mid = (float(low) + float(high)) / 2.0
    half = (float(high) - float(low)) / 2.0 or 1.0
    seen: dict = {}
    for i in range(max_points):
        coded = -1.0 + 2.0 * i / (max_points - 1)
        level = decode_coded(f, coded)
        seen.setdefault(level, (float(level) - mid) / half)
    return sorted(((c, lv) for lv, c in seen.items()), key=lambda p: p[0])


def _excluded(levels: dict, exclude_levels) -> bool:
    """Whether ``levels`` matches an excluded configuration.

    The match is on the SHARED keys only. An excluded row recorded at refine
    names just the refined factors, and a candidate carries the held-fixed
    ones too, so requiring identical key sets would let the exclusion miss
    the very point it recorded. An exclusion with no shared key at all
    matches nothing, rather than everything.
    """
    for ex in exclude_levels or ():
        shared = set(ex) & set(levels)
        if shared and all(levels[k] == ex[k] for k in shared):
            return True
    return False


def candidates(fit_ids, factors, *, held_fixed: dict,
               exclude_levels=()) -> list[Candidate]:
    """Every valid combination of the fitted factors' axes.

    ``predicted`` is NaN here: this function enumerates the space and knows
    nothing about a fit. ``recommend``/``ranked`` score it.

    Held-fixed factors enter every candidate's ``levels`` — the target needs
    every flag on the command line, and the recommendation has to name a
    complete configuration — but never its ``coded``, because they carry no
    fitted term and so contribute nothing to the prediction.
    """
    by_id = {f.id: f for f in factors}
    ids = list(fit_ids)
    unknown = [fid for fid in ids if fid not in by_id]
    if unknown:
        raise ValueError(
            f"cannot build a candidate axis for {unknown!r}: no such factor was "
            f"declared (declared: {sorted(by_id)}). `fitted_ids` must name the "
            f"columns of the design that was actually built — see "
            f"stage_runner._design_factor_ids.",
        )
    axes = [_axis(by_id[fid]) for fid in ids]
    out: list[Candidate] = []
    for combo in itertools.product(*axes):
        coded = {fid: c for fid, (c, _) in zip(ids, combo)}
        levels = {**dict(held_fixed), **{fid: lv for fid, (_, lv) in zip(ids, combo)}}
        if _excluded(levels, exclude_levels):
            continue
        out.append(Candidate(levels=levels, coded=coded, predicted=float("nan")))
    return out


def _scored(fit: Fit, factors, *, fitted_ids, held_fixed: dict,
            exclude_levels) -> list[Candidate]:
    return [
        Candidate(levels=c.levels, coded=c.coded, predicted=predict(fit, c.coded))
        for c in candidates(fitted_ids, factors, held_fixed=held_fixed,
                            exclude_levels=exclude_levels)
    ]


def recommend(fit: Fit, factors, *, direction: str, fitted_ids, held_fixed: dict,
              exclude_levels=()) -> Candidate:
    """x-hat: the best-predicted valid candidate.

    Raises when every candidate was excluded — an empty X_valid is a fact
    about the campaign that must be reported where it is knowable, not a
    None that reaches ``recommendation.json`` as a null configuration.
    """
    sign = 1.0 if direction != "minimize" else -1.0
    best = None
    for c in _scored(fit, factors, fitted_ids=fitted_ids, held_fixed=held_fixed,
                     exclude_levels=exclude_levels):
        if best is None or sign * c.predicted > sign * best.predicted:
            best = c
    if best is None:
        raise ValueError(
            "no valid candidate remains after exclusions — every point of the "
            "candidate space matched a configuration already measured "
            "infeasible or rejected. Widen the factors' declared levels or "
            "relax the constraint that rejected them.",
        )
    return best


def ranked(fit: Fit, factors, *, direction: str, fitted_ids, held_fixed: dict,
           exclude_levels=(), top: int | None = 5) -> list[Candidate]:
    """The best ``top`` candidates, best first; ``top=None`` for all of them.

    ``recommendation.json``'s ``top_candidates``: a reader can see how close
    the runner-up was, which is what says whether the recommendation is a
    clear winner or a coin flip between neighbours. ``top=None`` returns the
    whole scored space, so a caller that wants both the shortlist and the size
    of the space it came from enumerates once.
    """
    sign = 1.0 if direction != "minimize" else -1.0
    scored = _scored(fit, factors, fitted_ids=fitted_ids, held_fixed=held_fixed,
                     exclude_levels=exclude_levels)
    scored.sort(key=lambda c: -sign * c.predicted)
    return scored if top is None else scored[:top]
