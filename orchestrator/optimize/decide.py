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


def alias_resolutions(fit: Fit) -> list[tuple[int, str, str, Fit]]:
    """Every alternative reading of this fit's confounded coefficients.

    One entry per ``(effect, alternative)`` pair on ``Effect.aliased_with``:
    ``(effect_index, kept_label, alt_label, alt_fit)`` where ``alt_fit`` is
    ``fit`` with that one coefficient RE-ATTRIBUTED to the alternative term —
    relabelled, re-termed, and **re-signed**.

    THE RE-SIGNING IS THE POINT, AND IT IS WHY THIS IS A NAMED FUNCTION RATHER
    THAN AN INLINE LOOP. A fractional design's aliased columns are either
    identical or exact negatives of each other. For an orthogonal ±1 design the
    coefficient is ``sum_i x_ij y_i / N``, so the alternative reading of a
    NEGATED alias is ``-beta``, not ``beta``. Verified arithmetic: on a 4-run
    design with ``col_C = -col_AB`` and a response driven purely by ``C`` at
    ``+2.0``, the fit reports ``beta_C = +2.0`` and ``beta_AB = -2.0``.
    Re-labelling without re-signing therefore claims the alternative term pushes
    the response in the OPPOSITE physical direction from what the data says —
    and since the two readings then differ, the error is not self-cancelling: a
    consumer would compare the recommendation against a resolution nobody
    proposed.

    Observable directly: with ``C = +5.0`` aliased onto ``(A, B)``, the
    alternative reading recommends ``A*B = +1`` at ``sign = +1`` and
    ``A*B = -1`` at ``sign = -1`` — opposite advice about the same two factors.
    ``test_alias_resolutions_re_signs_a_negated_alias`` pins exactly that.

    Note what re-signing does NOT change: whether the alias is *consequential*.
    Dropping the kept term frees every factor it spanned, and when that
    coefficient is large SOME member of the alternative's optimal set is
    materially worse under the fitted reading whichever way the sign points. So
    the boolean verdict is usually sign-invariant while the RECOMMENDED
    CONFIGURATION is not — which is precisely why the sign must be right even
    though a boolean-level test cannot see it.
    """
    import dataclasses

    out: list[tuple[int, str, str, Fit]] = []
    for i, e in enumerate(fit.effects):
        for alt_terms, sign in e.aliased_with:
            swapped = list(fit.effects)
            swapped[i] = dataclasses.replace(
                e, terms=tuple(alt_terms), label="".join(alt_terms),
                estimate=e.estimate * float(sign), aliased_with=(),
            )
            out.append((
                i, e.label, "".join(alt_terms),
                dataclasses.replace(fit, effects=tuple(swapped)),
            ))
    return out


def alias_consequential(fit: Fit, factors, *, direction: str, fitted_ids,
                        held_fixed: dict, exclude_levels=(),
                        epsilon_pct: float = 2.0) -> list[tuple[str, str]]:
    """Aliased pairs whose resolution could change the recommended winner.

    Spec §3.4 / paper §Illustrative: "If every plausible resolution of an alias
    gives the same winner, resolving it cannot change the decision; if one can
    change the winner, the policy may spend a registered foldover." This is the
    test that makes aliasing a RESOURCE question. It costs nothing to run (pure
    arithmetic over the fitted coefficients and the candidate space) and it is
    what gates the one state in this kind that spends budget purely to remove an
    assumption.

    Returns ``(kept_label, alt_label)`` pairs — ``AB``'s estimate could just as
    truthfully belong to ``CD``, and believing the latter would move the answer.
    An empty list means the aliasing is real, recorded, and irrelevant to the
    decision, so a foldover would buy a cleaner model and a worse campaign.

    HOW A RESOLUTION IS CONSTRUCTED. For each alternative on
    ``Effect.aliased_with``, the kept effect is RELABELLED to the alternative's
    terms and its estimate multiplied by the recorded ``sign``. Both halves
    matter:

      * relabelling moves the coefficient onto the alternative's column, which
        is the whole content of "the shared estimate might belong to CD";
      * the sign converts the coefficient from "per unit of the kept column" to
        "per unit of the alternative column". For an orthogonal +/-1 design
        ``beta = sum_i x_ij y_i / N``, so a column that is the exact negation of
        the kept one carries exactly ``-beta``. Skipping the multiply on a
        negated alias would swap in a term pointing the WRONG WAY — the
        recommendation would then be compared against a resolution nobody
        proposed, and the test could both fire spuriously and miss a real flip.
        (No tabulated design produces a negated alias today; a hand-built or
        folded one can, and ``effects.py`` has always detected the case.)

    WHY THE COMPARISON IS NOT ``alt.levels != base.levels``. Two reasons, both
    measured on the synthetic oracle:

      1. FALSE POSITIVES. Removing the kept term from the model leaves the
         factors it spanned unconstrained, so ``recommend`` falls back to its
         enumeration tie-break for them — and any factor whose main effect is
         indistinguishable from zero will happily flip level for a difference of
         1e-2. On ``SURFACES["additive"]`` at four 2-level factors (no
         interaction anywhere in the truth) a bare level comparison fired on
         12 of 30 seeds, which would make the "registered" foldover effectively
         unconditional — the opposite defect from never spending it.
      2. FALSE NEGATIVES. The same tie-break can also land on the SAME levels by
         luck, hiding a genuinely consequential alias. On
         ``SURFACES["interaction_only"]``, where ``AB`` is the entire signal and
         ``CD`` is noise, a bare level comparison fired on only 16 of 30 seeds.

    So the criterion is the paper's own, quantified over the ALTERNATIVE's
    optimal set rather than over its arbitrary argmax: take every candidate the
    alternative resolution rates within its own epsilon of best — those are the
    configurations that resolution calls "the winner" — and ask whether ANY of
    them loses more than epsilon under the resolution actually fitted. If some
    resolution's winner is materially worse under the other reading, the two
    readings disagree about the winner and a run can settle it. With this
    criterion the same two surfaces separate completely: 30/30 on
    ``interaction_only``, 0/30 on the additive control.

    ``epsilon_pct`` is the indifference width as a percentage of the leading
    prediction, matching ``certificate.resolve_epsilon``'s ``pct`` default. It
    is a percentage rather than the resolved absolute width because the two
    resolutions predict different values, so each side is measured against its
    own scale.
    """
    kw = dict(direction=direction, fitted_ids=fitted_ids, held_fixed=held_fixed,
              exclude_levels=exclude_levels)
    base_all = ranked(fit, factors, top=None, **kw)
    if not base_all:
        return []
    base = base_all[0]
    eps = abs(base.predicted) * float(epsilon_pct) / 100.0
    sign_d = 1.0 if direction != "minimize" else -1.0

    out: list[tuple[str, str]] = []
    for _i, kept_label, alt_label, alt_fit in alias_resolutions(fit):
        alt_all = ranked(alt_fit, factors, top=None, **kw)
        if not alt_all:
            continue
        alt_eps = abs(alt_all[0].predicted) * float(epsilon_pct) / 100.0
        for c in alt_all:
            # Everything this resolution is indifferent between: its own
            # epsilon-optimal set. `alt_all` is sorted best-first, so the first
            # candidate outside that set ends the scan. Anything worse than it is
            # not a candidate for "the winner under this resolution".
            if sign_d * (alt_all[0].predicted - c.predicted) > alt_eps:
                break
            loss = sign_d * (base.predicted - predict(fit, c.coded))
            if loss > eps:
                out.append((kept_label, alt_label))
                break
    return out


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
    # DETERMINISTIC TIE-BREAK, and an honest account of what it does and does not
    # buy. Exact ties are real and common here -- 53 tie groups in a 45-candidate
    # 3-factor space on one fixture -- and they arise structurally: whenever a
    # main effect cancels against an interaction it participates in
    # (beta_A = -beta_AB), every level of A predicts the same response at the
    # level of B where they cancel.
    #
    # WHAT THIS FIXES: nothing currently observable, and that was measured rather
    # than assumed. `_scored` enumerates the grid in ascending factor order, which
    # is exactly the order this key reproduces, and Python's sort is stable -- so
    # across 200 random response vectors the key changed the emitted order ZERO
    # times, and across 400 vectors rescaling the objective by 0.01/1.0/1000 moved
    # the top-1 candidate ZERO times with OR without it. An earlier claim that
    # this repaired a moving recommendation did not survive that check and is
    # retracted.
    #
    # WHY IT STAYS: it makes the order a DECLARED FUNCTION OF THE LEVELS rather
    # than an accident of how `_scored` happens to iterate. Today those agree; the
    # guarantee is that they cannot silently stop agreeing. A future change to the
    # enumeration -- a different candidate generator, a dict that stops preserving
    # insertion order, parallel scoring -- would otherwise move a recommendation
    # with no change to any measurement, and `confirm` draws its shortlist from
    # this order, so a reorder at the shortlist boundary decides which
    # configuration gets fresh replicates and can be certified.
    #
    # The secondary key is the (factor_id, level) pairs in FACTOR-ID order, with
    # each level rendered as a (is_not_number, number, text) triple. Mixed level
    # types are the reason for the triple rather than a bare `str(v)`: a level may
    # be numeric on one factor and a string on another, so `("A", 2) < ("A", "lru")`
    # raises, while plain stringification sorts 16 before 9 and would make the
    # tie-break needlessly surprising to a reader comparing artifacts. Numbers
    # therefore compare numerically among themselves and sort before strings, and
    # strings compare lexicographically among themselves.
    #
    # No claim is made that the first tied configuration is BETTER. The
    # requirement is only that the order is a declared function of the levels, so
    # the same evidence always yields the same artifact.
    def _tie_key(c):
        levels = c.levels or {}
        return tuple(
            (fid, isinstance(levels[fid], str), 
             0.0 if isinstance(levels[fid], str) else float(levels[fid]),
             str(levels[fid]))
            for fid in sorted(levels)
        )

    scored.sort(key=lambda c: (-sign * c.predicted, _tie_key(c)))
    return scored if top is None else scored[:top]
