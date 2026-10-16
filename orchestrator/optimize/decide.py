"""The recommendation: x-hat = argmax over X_valid of the fitted response
(exact by enumeration at or below ``CANDIDATE_CAP`` candidates; over a seeded
search's evaluated set above it -- see "THE CANDIDATE SPACE" below).

Spec §3.3. A stationary point of a quadratic is where the gradient vanishes —
which is a saddle or a minimum as readily as a maximum, and which ignores
choice factors entirely. Observed on a live campaign: the confirmed
"optimum" was 38% below a corner the screen had already measured. The paper's
recommendation is enumeration over the valid space instead; for a small
space that is exact and needs no model judgement.

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

THE CANDIDATE SPACE, AND WHEN IT IS NOT ENUMERATED. The space is the product
of the fitted factors' axes: at most 9 points per refinable numeric axis and 2
per choice/two-level axis. Its size is exponential in the number of fitted
factors -- a 6-knob campaign is 9^6 = 531k candidates, 12 knobs 9^12 = 2.8e11 --
so exhaustive enumeration stops being a computation at all somewhere around
seven refinable knobs (measured: 3.19M ``predict`` calls and 74 s at six; seven
did not finish in nine minutes).

  * At or below ``CANDIDATE_CAP`` (product of axis sizes) the space is
    ENUMERATED exactly, as it always was. Every claim above about the argmax
    being exact holds there. The cap is chosen so every campaign this kind has
    run stays exhaustive: the synthetic oracle surfaces are <= 4 factors
    (<= 9^4 = 6561 candidates) and the largest real campaign ~ 26k.
  * Above it the space is SEARCHED (``_search``): a deterministic, seeded,
    multi-start coordinate ascent over the full axes, from a pool of every
    measured configuration of the epoch plus a seeded uniform sample. Each
    move cycles one factor through ALL its axis values with the rest held, so
    it finds that axis's exact conditional optimum on the grid (for any model:
    the axis is enumerated, not solved); interactions make the result a LOCAL
    optimum, which the multiple starts guard against without any global
    guarantee. The argmax is then over the EVALUATED set, which is not claimed
    exhaustive: ``Scored.space`` says so, and the fitting stage records it as
    ``recommendation.json["candidate_space"]``.

The same exclusions apply at every evaluated point in either mode: measured-
inadmissible configurations (``exclude_levels``) and, with constraint models,
confidently-infeasible candidates.
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass

from orchestrator.optimize.effects import Fit
from orchestrator.optimize.factors import Factor, code_actual, decode_coded, is_refinable


#: Product of axis sizes at or below which the candidate space is ENUMERATED
#: exactly (byte-identical to the pre-search behaviour). Above it the space is
#: searched (``_search``). 50k keeps every campaign this kind has run exhaustive
#: -- oracle surfaces <= 4 factors (<= 6561 candidates), the largest real
#: campaign ~ 26k -- and is the size at which a 6-term fit enumerates in well
#: under a second.
CANDIDATE_CAP = 50_000

#: The search's seed. A constant, like ``pareto.HV_MC_SEED``: the same fit and
#: exclusions always yield the same evaluated set and so the same artifact.
SEARCH_SEED = 0

#: Size of the seeded uniform sample in the search pool. Smaller than the cap
#: on purpose: the sample only supplies diverse STARTS for the ascent (which
#: does the optimizing), while every sampled point is also carried into every
#: downstream consumer of the evaluated set (the regret bound, the predicted
#: front, the constraint record). Measured once, not pinned by a test: on six
#: planted concave quadratics at 12 and at 16 knobs both a 4k and a 50k sample
#: reached the planted optimum every time, and on six random INDEFINITE ones
#: at each size they named the same predicted maximum.
SEARCH_SAMPLE = 4_000

#: Above the cap, at most this many alias READINGS are assessed per call of
#: ``alias_consequential`` (largest |coefficient| first), each by a local
#: search; the rest are recorded as unassessed. A resolution-IV screen of 16
#: knobs has ~100 readings and of 24 ~250, and one full search per reading
#: was 120 of a 131 s campaign; a local search per reading costs ~0.05 s.
ALIAS_READINGS_CAP = 64

#: Ascent starts per objective direction (the best pooled points), and per
#: multi-objective weight vector.
SEARCH_STARTS = 8
SEARCH_STARTS_WEIGHTED = 3


@dataclass(frozen=True)
class CandidateSpace:
    """How the scored candidate set was obtained -- ``recommendation.json``'s
    ``candidate_space``.

    ``size`` is the product of the axis sizes (the full space), ``evaluated``
    the number of distinct configurations the search touched -- pooled, or
    visited by an ascent, whether scored or rejected as inadmissible (before
    exclusions; the feasibility descent's points included),
    ``method`` ``"enumeration"`` or ``"sampled_coordinate_ascent"``; ``seed``
    is the search seed (``None`` when enumerated: nothing was random).
    """

    exhaustive: bool
    size: int
    evaluated: int
    method: str
    seed: int | None
    #: Whether the confidently-infeasible exclusion was applied: ``None`` when
    #: no constraint was modelled, ``False`` when the models were dropped
    #: because no admissible point was found (enumerated: none EXISTS;
    #: searched: neither the search nor the feasibility ascent found one).
    constraint_models_applied: bool | None = None
    #: Measured configurations offered as search seeds that could not be
    #: placed on the axes (a fitted factor missing, a choice level off the
    #: axis, a level that cannot be coded) and so seeded nothing. Counted
    #: rather than dropped silently; 0 when enumerated (nothing is seeded).
    seeds_dropped: int = 0

    def as_dict(self) -> dict:
        return {"exhaustive": self.exhaustive, "size": int(self.size),
                "evaluated": int(self.evaluated), "method": self.method,
                "seed": self.seed,
                "constraint_models_applied": self.constraint_models_applied,
                "seeds_dropped": int(self.seeds_dropped)}


class Scored(list):
    """A list of scored ``Candidate``s that also says how it was obtained.

    A plain list to every existing consumer (iteration, slicing, sorting, the
    regret bound, the predicted front); ``.space`` is a ``CandidateSpace``.
    Slicing returns a plain ``list``, so only the whole set carries the record.
    """

    space: "CandidateSpace"
    #: Every scored candidate BEFORE the confidently-infeasible filter (after
    #: the measured-inadmissible one): the set the constraint record counts
    #: exclusions over. The same set ``ranked`` would score with no models.
    unfiltered: list

    def __init__(self, items=(), space: "CandidateSpace | None" = None,
                 unfiltered=None):
        super().__init__(items)
        self.space = space
        self.unfiltered = list(self) if unfiltered is None else list(unfiltered)


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
    seen: dict = {}
    for i in range(max_points):
        coded = -1.0 + 2.0 * i / (max_points - 1)
        level = decode_coded(f, coded)
        # `code_actual` owns the coordinate transform (linear or log), so the
        # candidate is scored in exactly the space the fit was coded in.
        seen.setdefault(level, code_actual(f, level))
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


def _axes(fit_ids, factors) -> tuple[list, list]:
    """``(ids, axes)`` for the fitted factors, refusing an undeclared id."""
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
    return ids, [_axis(by_id[fid]) for fid in ids]


def space_size(fit_ids, factors) -> int:
    """The number of candidates in the full space: the product of axis sizes."""
    _ids, axes = _axes(fit_ids, factors)
    return math.prod(len(a) for a in axes)


def candidates(fit_ids, factors, *, held_fixed: dict,
               exclude_levels=()) -> list[Candidate]:
    """Every valid combination of the fitted factors' axes.

    ``predicted`` is NaN here: this function enumerates the space and knows
    nothing about a fit. ``recommend``/``ranked`` score it.

    Held-fixed factors enter every candidate's ``levels`` — the target needs
    every flag on the command line, and the recommendation has to name a
    complete configuration — but never its ``coded``, because they carry no
    fitted term and so contribute nothing to the prediction.

    This is the EXHAUSTIVE enumeration, whatever the size: ``_scored`` calls
    it only at or below ``CANDIDATE_CAP`` and searches above it.
    """
    ids, axes = _axes(fit_ids, factors)
    out: list[Candidate] = []
    for combo in itertools.product(*axes):
        coded = {fid: c for fid, (c, _) in zip(ids, combo)}
        levels = {**dict(held_fixed), **{fid: lv for fid, (_, lv) in zip(ids, combo)}}
        if _excluded(levels, exclude_levels):
            continue
        out.append(Candidate(levels=levels, coded=coded, predicted=float("nan")))
    return out


# ── the search above the cap ─────────────────────────────────────────────────


def _compiled(fit: Fit, ids):
    """``predict(fit, .)`` over a coded TUPLE in ``ids`` order.

    The same terms in the same order with the same arithmetic as ``predict``
    (``y = intercept``, then ``y += estimate * prod(coded)`` per term), so the
    value is bit-for-bit ``predict``'s -- only the dict lookups are hoisted.
    """
    pos = {fid: j for j, fid in enumerate(ids)}
    terms = [(float(e.estimate), tuple(pos[t] for t in e.terms))
             for e in list(fit.effects) + list(fit.quadratic)]
    b0 = float(fit.intercept)

    def f(x) -> float:
        y = b0
        for est, ts in terms:
            y += est * math.prod([x[t] for t in ts])
        return y

    return f


def _snap(levels: dict, ids, axes, by_id) -> tuple | None:
    """The axis-index tuple nearest a measured configuration, or ``None``.

    A choice level must match exactly; a numeric one goes to the axis point
    nearest its coding (a CCD axial point beyond the screen range, an
    off-grid level), ties to the lower index. A configuration missing a
    fitted factor, or with a level that cannot be coded, seeds nothing --
    and ``_scored`` counts it in ``CandidateSpace.seeds_dropped``.
    """
    out = []
    for fid, axis in zip(ids, axes):
        if fid not in levels:
            return None
        v = levels[fid]
        f = by_id[fid]
        hit = next((j for j, (_c, lv) in enumerate(axis) if lv == v), None)
        if hit is None:
            if f.type == "choice":
                return None
            try:
                c = code_actual(f, v)
            except (TypeError, ValueError):
                return None
            hit = min(range(len(axis)), key=lambda j: (abs(axis[j][0] - c), j))
        out.append(hit)
    return tuple(out)


def _weight_vectors(k: int, step: int = 4) -> list[tuple[float, ...]]:
    """Interior points of the simplex lattice with spacing ``1/step``.

    The vertices are the single-objective directions, searched separately; the
    rest reach the predicted front's interior (the centroid is the knee
    direction for equally scaled objectives).
    """
    out = []

    def rec(prefix, left, slots):
        if slots == 1:
            out.append(prefix + (left,))
            return
        for a in range(left, -1, -1):
            rec(prefix + (a,), left - a, slots - 1)

    rec((), step, k)
    return [tuple(a / step for a in w) for w in out if max(w) < step]


def _search(fit: Fit, ids, axes, by_id, *, direction: str, objectives,
            seed_levels, admissible, seed: int, sample: int,
            extra_pool=()) -> list[tuple]:
    """Every distinct axis-index tuple the search touched (pooled, or tried by
    an ascent move -- scored or rejected as inadmissible), ascending.

    Pool: the axes' centre, ``extra_pool`` (index tuples), ``seed_levels``
    snapped onto the axes, then ``sample`` seeded uniform draws. Then, per
    direction, a coordinate ascent from each of the
    best pooled admissible points: cycle every factor through ALL its axis
    values holding the others, move to the best admissible improvement, and
    repeat until a full sweep improves nothing. Directions: ``fit`` at
    ``direction``; each ``(fit, direction)`` in ``objectives``; and, with two
    or more objectives, a lattice of weight vectors over their
    pool-range-normalised sum (the predicted front's interior). Every scored
    tuple is returned, admissible or not; ``admissible`` (a cached predicate)
    gates only the starts and the moves.
    """
    sizes = [len(a) for a in axes]
    n = len(ids)

    def coded_of(idx):
        return tuple(axes[j][idx[j]][0] for j in range(n))

    # The centre of every axis always seeds the pool, so a search with no
    # measured configuration and no sample still has a start.
    centre = tuple(s // 2 for s in sizes)
    seen: dict[tuple, None] = {centre: None}
    pool: list[tuple] = [centre]
    for idx in extra_pool:
        if idx not in seen:
            seen[idx] = None
            pool.append(idx)
    for lv in seed_levels or ():
        idx = _snap(lv, ids, axes, by_id)
        if idx is not None and idx not in seen:
            seen[idx] = None
            pool.append(idx)
    rng = random.Random(seed)
    for _ in range(int(sample)):
        idx = tuple(rng.randrange(s) for s in sizes)
        if idx not in seen:
            seen[idx] = None
            pool.append(idx)

    sign = lambda d: 1.0 if d != "minimize" else -1.0  # noqa: E731
    dirs = [(_compiled(fit, ids), sign(direction))]
    objs = [(_compiled(o_fit, ids), sign(o_dir)) for o_fit, o_dir in objectives or ()
            if o_fit is not None]
    dirs += objs
    adm_pool = [idx for idx in pool if admissible(idx)]

    def scorer(fs):
        cache: dict[tuple, float] = {}

        def s(idx):
            v = cache.get(idx)
            if v is None:
                x = coded_of(idx)
                v = sum(w * sg * f(x) for f, sg, w in fs)
                cache[idx] = v
            return v
        return s

    scorers = [(scorer([(f, sg, 1.0)]), SEARCH_STARTS) for f, sg in dirs]
    if len(objs) >= 2 and adm_pool:
        span = []
        for f, sg in objs:
            vals = [f(coded_of(idx)) for idx in adm_pool]
            r = max(vals) - min(vals)
            span.append(r if r > 0 and math.isfinite(r) else 1.0)
        for w in _weight_vectors(len(objs)):
            fs = [(f, sg, wk / sp) for (f, sg), wk, sp in zip(objs, w, span) if wk > 0]
            scorers.append((scorer(fs), SEARCH_STARTS_WEIGHTED))

    for score, m in scorers:
        starts = sorted(adm_pool, key=lambda idx: -score(idx))[:m]
        for cur in starts:
            cur_s = score(cur)
            improved = True
            while improved:
                improved = False
                for j in range(n):
                    best_v, best_s = cur[j], cur_s
                    for v in range(sizes[j]):
                        if v == cur[j]:
                            continue
                        cand = cur[:j] + (v,) + cur[j + 1:]
                        seen.setdefault(cand, None)
                        if not admissible(cand):
                            continue
                        sc = score(cand)
                        if sc > best_s:
                            best_v, best_s = v, sc
                    if best_v != cur[j]:
                        cur = cur[:j] + (best_v,) + cur[j + 1:]
                        cur_s = best_s
                        improved = True
    return sorted(seen)


def _feasibility_ascent(pool, axes, margins, *, starts: int, ok,
                        allowed=lambda idx: True) -> list[tuple]:
    """Coordinate DESCENT on the total constraint VIOLATION, from the
    ``starts`` pooled points with the least of it; every tuple it scored,
    ascending.

    ``margins(idx)`` is one number per modelled constraint: how far the
    violating-side bound is from confidently excluding the point (positive:
    that constraint does not exclude it). The violation is the hinge sum
    ``sum_c max(0, -margin_c)``. Climbing the MINIMUM margin instead stalls
    when several constraints bind jointly: a single-coordinate move raises
    one constraint's margin, never the minimum over the others (three
    constraints on disjoint factor pairs is the reviewed repro). The hinge
    sum falls with every such move, and a constraint already satisfied adds
    nothing, so moves that help one constraint without hurting another are
    taken.

    Used only when the objective search found no admissible point, to tell
    "the feasible region is narrow and the pool missed it" from "nothing is
    feasible" -- the case in which the enumerated path drops the models. A
    move never enters a point ``allowed`` refuses (a configuration measured
    inadmissible), and each descent stops at the FIRST point ``ok`` accepts
    (admissible: no model confidently excludes it and it is not measured
    inadmissible), checked after every move; from there the objective
    search takes over.
    """
    sizes = [len(a) for a in axes]
    n = len(axes)
    cache: dict[tuple, float] = {}

    def viol(idx):
        v = cache.get(idx)
        if v is None:
            v = cache[idx] = sum(max(0.0, -m) for m in margins(idx))
        return v

    for cur in sorted(pool, key=lambda idx: (viol(idx), idx))[:starts]:
        if ok(cur):
            continue
        cur_v = viol(cur)
        improved = True
        while improved and not ok(cur):
            improved = False
            for j in range(n):
                best_v, best_s = cur[j], cur_v
                for v in range(sizes[j]):
                    if v == cur[j]:
                        continue
                    cand = cur[:j] + (v,) + cur[j + 1:]
                    if not allowed(cand):
                        continue
                    sv = viol(cand)
                    if sv < best_s:
                        best_v, best_s = v, sv
                if best_v != cur[j]:
                    cur = cur[:j] + (best_v,) + cur[j + 1:]
                    cur_v = best_s
                    improved = True
                    if ok(cur):
                        break
    return sorted(cache)


def _scored(fit: Fit, factors, *, fitted_ids, held_fixed: dict,
            exclude_levels, constraint_models=(),
            constraint_delta: float = 0.05, direction: str = "maximize",
            objectives=(), seed_levels=(), cap: int | None = None,
            seed: int | None = None, sample: int | None = None) -> Scored:
    """Every valid candidate, scored -- minus the CONFIDENTLY infeasible ones.

    ``constraint_models`` (``constraint_models.fit_constraint_models``) removes a
    candidate only when some modelled constraint's one-sided ``1 - delta``
    bound lies entirely on the violating side; an uncertain candidate stays,
    because only a measurement can settle it. Unmodelled constraints exclude
    nothing. If the models would exclude EVERY candidate the exclusion is not
    applied at all: spec §3.6 says always act, and a confirm round can still
    measure what the model doubts, whereas an empty space can only abort.

    "Every" holds at or below ``cap`` (default ``CANDIDATE_CAP``), where the
    space is enumerated. Above it the candidates are those ``_search`` scored
    (``direction`` and ``objectives`` steer it; ``seed_levels`` -- measured
    configurations -- seed its pool), with the same two exclusions applied at
    every one; ``.space`` on the result records which mode ran.
    """
    cap = CANDIDATE_CAP if cap is None else int(cap)
    ids, axes = _axes(fitted_ids, factors)
    size = math.prod(len(a) for a in axes)
    modelled = any(getattr(m, "modelled", False) for m in constraint_models or ())
    if size <= cap:
        scored = [
            Candidate(levels=c.levels, coded=c.coded, predicted=predict(fit, c.coded))
            for c in candidates(fitted_ids, factors, held_fixed=held_fixed,
                                exclude_levels=exclude_levels)
        ]
        if not modelled:
            return Scored(scored, CandidateSpace(True, size, size, "enumeration", None))
        from orchestrator.optimize.constraint_models import confidently_infeasible

        kept = [c for c in scored
                if not confidently_infeasible(constraint_models, c.coded,
                                              delta=constraint_delta)]
        return Scored(kept or scored,
                      CandidateSpace(True, size, size, "enumeration", None, bool(kept)),
                      unfiltered=scored)

    from orchestrator.optimize.constraint_models import confidently_infeasible

    seed = SEARCH_SEED if seed is None else int(seed)
    sample = SEARCH_SAMPLE if sample is None else int(sample)
    by_id = {f.id: f for f in factors}
    held = dict(held_fixed)

    def build(idx) -> Candidate:
        coded = {fid: axes[j][idx[j]][0] for j, fid in enumerate(ids)}
        levels = {**held, **{fid: axes[j][idx[j]][1] for j, fid in enumerate(ids)}}
        return Candidate(levels=levels, coded=coded, predicted=float("nan"))

    def run(use_models: bool, extra_pool=()):
        memo: dict[tuple, bool] = {}

        def admissible(idx) -> bool:
            ok = memo.get(idx)
            if ok is None:
                c = build(idx)
                ok = not _excluded(c.levels, exclude_levels) and not (
                    use_models and confidently_infeasible(
                        constraint_models, c.coded, delta=constraint_delta))
                memo[idx] = ok
            return ok

        visited = _search(fit, ids, axes, by_id, direction=direction,
                          objectives=objectives, seed_levels=seed_levels,
                          admissible=admissible, seed=seed, sample=sample,
                          extra_pool=extra_pool)
        return visited, [i for i in visited if admissible(i)]

    applied = None
    visited, kept = run(modelled)
    if modelled:
        applied = True
    if modelled and not kept:
        # No EVALUATED point is admissible -- which is not "none exists". The
        # enumerated path drops the models only when the whole space is
        # confidently infeasible, so look for a feasible point first: a
        # descent on the total constraint violation, then the objective
        # search again with whatever it found in its pool.
        from orchestrator.optimize.constraint_models import bound, per_constraint_delta

        d = per_constraint_delta(constraint_models, constraint_delta)
        live = [m for m in constraint_models if m.modelled]

        def margins(idx) -> tuple:
            coded = build(idx).coded
            out_ = []
            for m in live:
                b = bound(m, coded, delta=d)
                out_.append(float(m.value) - b["lower"] if m.op in ("<", "<=")
                            else b["upper"] - float(m.value))
            return tuple(out_)

        def allowed(idx) -> bool:
            return not _excluded(build(idx).levels, exclude_levels)

        def feasible(idx) -> bool:
            return allowed(idx) and not confidently_infeasible(
                constraint_models, build(idx).coded, delta=constraint_delta)

        feas_seen = _feasibility_ascent(visited, axes, margins, starts=SEARCH_STARTS,
                                        ok=feasible, allowed=allowed)
        found = [i for i in feas_seen if feasible(i)]
        if found:
            v2, kept = run(True, extra_pool=found)
            visited = sorted(set(visited) | set(feas_seen) | set(v2))
        if not kept:
            # Nothing feasible found anywhere: as in the enumerated case, the
            # exclusion is not applied at all -- and the record says so.
            applied = False
            v3, kept = run(False)
            visited = sorted(set(visited) | set(feas_seen) | set(v3))

    def scored_of(idxs):
        out_ = []
        for idx in idxs:
            c = build(idx)
            out_.append(Candidate(levels=c.levels, coded=c.coded,
                                  predicted=predict(fit, c.coded)))
        return out_

    kept_set = set(kept)
    out = scored_of(sorted(kept_set))
    unfiltered = (scored_of(i for i in visited
                            if not _excluded(build(i).levels, exclude_levels))
                  if modelled else out)
    dropped = sum(1 for lv in seed_levels or () if _snap(lv, ids, axes, by_id) is None)
    return Scored(out, CandidateSpace(False, size, len(visited),
                                      "sampled_coordinate_ascent", seed, applied,
                                      seeds_dropped=dropped),
                  unfiltered=unfiltered)


def recommend(fit: Fit, factors, *, direction: str, fitted_ids, held_fixed: dict,
              exclude_levels=(), constraint_models=(),
              constraint_delta: float = 0.05, **search) -> Candidate:
    """x-hat: the best-predicted valid candidate.

    Best over the WHOLE space at or below ``CANDIDATE_CAP``; above it, best
    over what the search evaluated (``_scored``; ``search`` passes
    ``objectives`` / ``seed_levels`` / ``cap`` / ``seed`` / ``sample``).

    "Valid" excludes configurations measured inadmissible (``exclude_levels``)
    and, when ``constraint_models`` are given, candidates some modelled
    constraint predicts CONFIDENTLY infeasible at ``constraint_delta`` (see
    ``_scored``). The argmax may still be UNCERTAIN on a constraint; the
    fitting stage records that in ``recommendation.json``.

    Raises when every candidate was excluded — an empty X_valid is a fact
    about the campaign that must be reported where it is knowable, not a
    None that reaches ``recommendation.json`` as a null configuration.
    """
    sign = 1.0 if direction != "minimize" else -1.0
    best = None
    for c in _scored(fit, factors, fitted_ids=fitted_ids, held_fixed=held_fixed,
                     exclude_levels=exclude_levels,
                     constraint_models=constraint_models,
                     constraint_delta=constraint_delta, direction=direction,
                     **search):
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
                        epsilon_pct: float = 2.0, constraint_models=(),
                        constraint_delta: float = 0.05,
                        baseline: Candidate | None = None,
                        record: dict | None = None,
                        **search) -> list[tuple[str, str]]:
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

    ABOVE ``CANDIDATE_CAP`` the test is only as good as the searches: each
    resolution's "optimal set" is over what ITS search evaluated, so an empty
    list means no consequential alias was FOUND (the fitting stage records
    ``alias_consequential_basis: "searched"``). Two things keep it from being
    weaker than it has to be. ``baseline`` -- the stage's own primary argmax,
    from the search that ALSO climbed every objective -- is the reference
    winner when it is better than this function's own (objective-free)
    search finds; and every resolution's search is seeded with the baseline's
    levels, so the alternative reading is asked about the region the fitted
    reading actually recommends. Extra objectives are not passed on: the
    question is about the primary fit's winner. Under the cap ``baseline`` is
    ignored -- enumeration already found the exact argmax.

    BOUNDED WORK ABOVE THE CAP. One full search per reading made this the
    dominant cost of a many-knob campaign (a resolution-IV screen has one
    reading per member of every 2fi alias chain: ~100 at 16 knobs, ~250 at
    24). Above the cap each reading is instead assessed by a LOCAL search --
    no uniform sample; the pool is the reference winner, the fitted reading's
    ``SEARCH_STARTS`` best evaluated points and the measured configurations --
    and at most ``ALIAS_READINGS_CAP`` readings are assessed, largest
    |coefficient| first: with coded levels in [-1, 1], re-attributing a
    coefficient beta changes any prediction by at most 2|beta|, so a member of
    the alternative's optimal set loses at most 4|beta| plus that reading's own
    epsilon under the fitted one -- small coefficients are the least able to
    move the winner. Nothing is skipped silently: ``record``, when given,
    is filled with ``{readings, assessed, unassessed: [[kept, alt], ...],
    method}``, which the fitting stage writes as
    ``recommendation.json["alias_assessment"]``. Under the cap every reading
    is enumerated, as before, and ``record`` says so.
    """
    search = {k: v for k, v in search.items() if k != "objectives"}
    kw = dict(direction=direction, fitted_ids=fitted_ids, held_fixed=held_fixed,
              exclude_levels=exclude_levels, constraint_models=constraint_models,
              constraint_delta=constraint_delta, **search)
    base_all = ranked(fit, factors, top=None, **kw)
    if not base_all:
        return []
    base = base_all[0]
    sign_d = 1.0 if direction != "minimize" else -1.0
    if baseline is not None and not base_all.space.exhaustive:
        if sign_d * baseline.predicted > sign_d * base.predicted:
            base = baseline
        kw["seed_levels"] = [dict(baseline.levels), *(kw.get("seed_levels") or ())]
    eps = abs(base.predicted) * float(epsilon_pct) / 100.0

    readings = alias_resolutions(fit)
    if base_all.space.exhaustive:
        assessed = set(range(len(readings)))
        method = "enumeration"
    else:
        order = sorted(range(len(readings)),
                       key=lambda r: (-abs(fit.effects[readings[r][0]].estimate), r))
        assessed = set(order[:ALIAS_READINGS_CAP])
        method = "local_coordinate_ascent"
        kw["sample"] = 0
        kw["seed_levels"] = ([dict(base.levels)]
                             + [dict(c.levels) for c in base_all[:SEARCH_STARTS]]
                             + list(kw.get("seed_levels") or ()))
    if record is not None:
        record.update({
            "readings": len(readings), "assessed": len(assessed), "method": method,
            "unassessed": [[readings[r][1], readings[r][2]]
                           for r in range(len(readings)) if r not in assessed],
        })

    out: list[tuple[str, str]] = []
    for r, (_i, kept_label, alt_label, alt_fit) in enumerate(readings):
        if r not in assessed:
            continue
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
           exclude_levels=(), top: int | None = 5, constraint_models=(),
           constraint_delta: float = 0.05, **search) -> list[Candidate]:
    """The best ``top`` candidates, best first; ``top=None`` for all of them.

    ``top=None`` returns a ``Scored`` (a list carrying ``.space``): the whole
    space at or below ``CANDIDATE_CAP``, the search's evaluated set above it.
    ``search`` is ``_scored``'s ``objectives`` / ``seed_levels`` / ``cap`` /
    ``seed`` / ``sample``; ``objectives`` (``(fit, direction)`` pairs) makes
    the search also climb every objective and a spread of their weighted sums,
    so a predicted front taken over the result reaches its extremes and
    interior.

    ``recommendation.json``'s ``top_candidates``: a reader can see how close
    the runner-up was, which is what says whether the recommendation is a
    clear winner or a coin flip between neighbours. ``top=None`` returns the
    whole scored space, so a caller that wants both the shortlist and the size
    of the space it came from enumerates once.
    """
    sign = 1.0 if direction != "minimize" else -1.0
    scored = _scored(fit, factors, fitted_ids=fitted_ids, held_fixed=held_fixed,
                     exclude_levels=exclude_levels,
                     constraint_models=constraint_models,
                     constraint_delta=constraint_delta, direction=direction,
                     **search)
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
