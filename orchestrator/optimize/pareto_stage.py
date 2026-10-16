"""Multi-objective glue between ``stage_runner`` and the pure ``pareto`` core.

Every function here reads only artifacts already on disk (``runs.jsonl``,
``recommendation.json``, ``confirmation.json``) or values the caller holds, and
returns plain dicts for the stage runner to write. Nothing here is reached by a
single-objective campaign: every call site is gated on
``pareto.policy_objectives(pol)`` being non-empty, which is what keeps those
campaigns byte-identical (metamorphic oracle, ``tests/test_optimize_pareto.py``).
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from orchestrator.optimize import pareto
from orchestrator.optimize.pareto import MeasuredPoint, PredictedPoint

logger = logging.getLogger(__name__)

#: Whether round r > 1 seats GAP-FILL candidates when the previous round
#: reported ``front_gap_large``. Not a campaign knob (the branch is registered
#: by the compiled policy); it exists so the metamorphic oracle can run the same
#: campaign with and without the gap fill and check that filling gaps never
#: lowers the hypervolume (spec oracle property 5).
_FRONT_GAP_FILL = True


def objectives(pol) -> list:
    return pareto.policy_objectives(pol)


def preference(pol) -> pareto.Preference:
    objs = objectives(pol)
    return pareto.parse_preference((pol.get("objective") or {}).get("preference"), objs)


# ── measured points ──────────────────────────────────────────────────────────


def _iter_index(path: Path) -> int:
    try:
        return int(path.name.split("-", 1)[1])
    except (IndexError, ValueError):
        return -1


def _stage_of(iter_dir: Path) -> str:
    """The fitting stage an iteration ran, for a measured point's ``source``.

    No effects/recommendation file at all is a confirm iteration. A file that
    exists but cannot be read is NOT silently a confirm one: it is logged and
    the source is recorded as ``unknown`` (B4)."""
    for name in ("effects.json", "recommendation.json"):
        p = iter_dir / name
        if p.exists():
            try:
                return str(json.loads(p.read_text()).get("stage") or "screen")
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("%s is unreadable (%s): the points it measured are "
                               "recorded with source 'unknown'", p, exc)
                return "unknown"
    return "confirm"


def measured_points(work_dir, objs) -> list[MeasuredPoint]:
    """``measured_points_and_incomplete(...)[0]``."""
    return measured_points_and_incomplete(work_dir, objs)[0]


def _usable(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def measured_points_and_incomplete(work_dir, objs) -> tuple[list[MeasuredPoint], list[dict]]:
    """Every measured ADMISSIBLE configuration with its complete-row samples
    per objective, and the configurations left out for an INCOMPLETE row.

    Admissible per configuration (``stage_runner._config_admissible``: one
    infeasible or rejected row anywhere strikes it off). ``source`` is
    ``confirm`` when any of its rows came from a confirm round, otherwise the
    first fitting stage that measured it.

    A configuration confirm measured is represented by its CONFIRM rows only.
    Its fitting-stage rows are what nominated it (a measured extreme is seated
    BECAUSE its screen value was high), so pooling them in would carry the
    winner's curse into the mean -- the reason single-objective terminal
    discrimination compares fresh replicates only. Fitting-stage-only
    configurations keep their fitting rows; they were not selected by them.

    ROW-WISE COMPLETENESS. A complete row that lacks a usable value for SOME
    objective (missing, null, NaN, a string) is not a measurement of the
    trade-off. A fitting-stage configuration keeps only its fully measured
    rows. A CONFIRM configuration with any such replicate is left out entirely
    and listed (it is UNMEASURED, exactly like a finalist that timed out) --
    never silently re-based on its fitting rows, which would bring the winner's
    curse back, and never dropped without a record. Returns ``(points,
    excluded)``, ``excluded`` = ``[{levels, missing, source}]``."""
    from orchestrator.optimize import artifacts
    from orchestrator.optimize.stage_runner import (
        _config_admissible,
        _measured_infeasible,
        _this_epoch_runs,
    )

    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return [], []
    invalid = _measured_infeasible(work_dir)
    pts: dict[str, MeasuredPoint] = {}
    fresh: dict[str, dict] = {}
    missing: dict[str, dict] = {}  # key -> {"fit": set, "confirm": set}
    # EPOCH-SCOPED, like `_top_measured`: a previous epoch measured a
    # different declared space (or mechanism), so its rows are not this
    # epoch's evidence. Feasibility stays sticky across epochs
    # (`_measured_infeasible`), as everywhere else.
    for d in (p.parent for p in _this_epoch_runs(work_dir)):
        rows = artifacts.read_runs(d)
        if not rows:
            continue
        stage = None
        for row in rows:
            lv = row.get("levels")
            if row.get("status") != "complete" or not lv:
                continue
            if not _config_admissible(work_dir, lv, invalid=invalid):
                continue
            key = json.dumps(lv, sort_keys=True, default=str)
            role = row.get("role")
            if stage is None:
                stage = _stage_of(d)
            src = "confirm" if role == "confirm" else stage
            p = pts.get(key)
            if p is None:
                p = pts[key] = MeasuredPoint(dict(lv), {o.metric: [] for o in objs}, src)
                fresh[key] = {o.metric: [] for o in objs}
                missing[key] = {"fit": set(), "confirm": set()}
            elif src == "confirm":
                p.source = "confirm"
            resp = row.get("response") or {}
            lacking = [o.metric for o in objs if not _usable(resp.get(o.metric))]
            if lacking:
                missing[key]["confirm" if role == "confirm" else "fit"].update(lacking)
                continue
            for o in objs:
                (fresh[key] if role == "confirm" else p.samples)[o.metric].append(
                    float(resp[o.metric]))
    out, excluded = [], []
    for key, p in pts.items():
        if p.source == "confirm":
            if missing[key]["confirm"] or not all(fresh[key][o.metric] for o in objs):
                excluded.append({"levels": dict(p.levels), "source": "confirm",
                                 "missing": sorted(missing[key]["confirm"])})
                continue
            p.samples = fresh[key]
        elif not all(p.samples[o.metric] for o in objs):
            excluded.append({"levels": dict(p.levels), "source": p.source,
                             "missing": sorted(missing[key]["fit"])})
            continue
        out.append(p)
    return out, excluded


def pooled(points, objs) -> dict:
    return {o.metric: pareto.pooled_variance(points, o.metric) for o in objs}


def best_reference(points, objs) -> dict:
    out = {}
    for o in objs:
        vals = [p.mean(o.metric) for p in points if p.mean(o.metric) is not None]
        if vals:
            s = pareto.sign(o.direction)
            out[o.metric] = s * max(s * v for v in vals)
    return out


# ── the fitting stages ──────────────────────────────────────────────────────


def _predicted_from_record(entries) -> list[PredictedPoint]:
    out = []
    for e in entries or ():
        out.append(PredictedPoint(levels=dict(e.get("levels") or {}), coded={},
                                  predicted=dict(e.get("predicted") or {}),
                                  se=dict(e.get("se") or {}),
                                  status=e.get("status") or "possibly_nondominated"))
    return out


def fit_record(pol, *, scored, omodels, delta_s: float, stage_name: str,
               held_now: dict, prev_rec: dict | None):
    """The multi-objective half of a fitting stage's ``recommendation.json``.

    Returns ``(preferred_candidate, record)``. ``preferred_candidate`` is the
    ``decide.Candidate`` the top-level ``levels``/``predicted`` must name (spec:
    the PREFERRED point of the predicted front), or ``None`` when no objective
    could be predicted (the caller keeps the primary argmax then).

    OTHER BRANCHES ARE CARRIED. Refine holds every non-refinable (choice)
    factor at the screen's preferred level, so its own predicted front sees one
    branch only; entries of the previous stage's predicted front that sit at a
    DIFFERENT level of a held factor are appended (``stage`` names where they
    were predicted), so a front split by a choice factor reaches confirm's pool
    whole.
    """
    objs = objectives(pol)
    front, n_nd = pareto.predicted_front(scored, omodels, objs, delta=delta_s)
    nd = [p for p in front if p.status == "nondominated"]
    pref = preference(pol)
    chosen = None
    if nd:
        vals = [p.predicted for p in nd]
        eps = pareto.resolve_eps(objs, best_reference_pred(vals, objs))
        frame = pareto.make_frame(objs, vals, eps)
        zs = [frame.z(v) for v in vals]
        i = pareto.preferred_index(pref, objs, zs, [p.levels for p in nd],
                                   frame.eps_z(eps))
        if i is not None:
            want = nd[i].levels
            chosen = next((c for c in scored if c.levels == want), None)
    entries = [{**p.as_dict(), "stage": stage_name} for p in front]
    if held_now and prev_rec:
        seen = {json.dumps(e["levels"], sort_keys=True, default=str) for e in entries}
        for e in prev_rec.get("predicted_front") or ():
            lv = e.get("levels") or {}
            if not any(k in lv and lv[k] != v for k, v in held_now.items()):
                continue
            key = json.dumps(lv, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            entries.append({**e, "stage": e.get("stage") or prev_rec.get("stage") or "screen"})
    if chosen is not None:
        basis = {"basis": "predicted_front_preference", "method": pref.method,
                 "reason": f"the {pref.method} point of the predicted front"}
    else:
        unfit = sorted(m for m, om in omodels.items() if om.fit is None)
        basis = {"basis": "primary_argmax_fallback", "method": pref.method,
                 "reason": (f"no predicted front: objective model(s) {unfit} could not "
                            f"be estimated, so every prediction is undefined"
                            if unfit else "no predicted front point matched a "
                                          "scored candidate")
                 + f"; the recommendation is objective {objs[0].metric!r}'s argmax"}
    record = {
        "objectives": [o.metric for o in objs],
        "preferred_basis": basis,
        "objective_models": {m: om.as_dict() for m, om in omodels.items()},
        "predicted_front": entries,
        "front_size_predicted": n_nd,
    }
    return chosen, record


def best_reference_pred(values, objs) -> dict:
    out = {}
    for o in objs:
        vs = [v[o.metric] for v in values
              if isinstance(v.get(o.metric), (int, float)) and math.isfinite(v[o.metric])]
        if vs:
            s = pareto.sign(o.direction)
            out[o.metric] = s * max(s * x for x in vs)
    return out


def models_rejected(omodels, *, lack_of_fit_only: bool = False) -> list[str]:
    """Objectives whose model the data rejected (lack of fit) or -- unless
    ``lack_of_fit_only`` -- that could not be estimated at all. A model with no
    pure error is NOT rejected: there is no test to fail, exactly as for the
    primary's ``model_adequate``."""
    from orchestrator.optimize.constraint_models import LACK_OF_FIT_ALPHA

    out = []
    for m, om in omodels.items():
        f = om.fit
        if f is None:
            if not lack_of_fit_only:
                out.append(m)
        elif f.lack_of_fit_p is not None and f.lack_of_fit_p < LACK_OF_FIT_ALPHA:
            out.append(m)
    return out


def survivors(omodels, factors) -> set[str]:
    """Factors significant for ANY objective (spec step 2)."""
    from orchestrator.optimize.stage import decide_after_screen

    out: set[str] = set()
    for om in omodels.values():
        if om.fit is not None:
            out |= set(decide_after_screen(om.fit, factors).surviving)
    return out


def nan_on_complete(outcome, objs) -> bool:
    resp = getattr(outcome, "response", None) or {}
    return any(isinstance(resp.get(o.metric), float) and resp[o.metric] != resp[o.metric]
               for o in objs)


# ── confirm: the shortlist ──────────────────────────────────────────────────


def _z_of(frame, values: dict) -> list[float]:
    return frame.z(values)


def _resolution_margin(pol, par: dict, objs, eps: dict) -> dict:
    """Per objective, ``t * se(difference) - eps``: how far apart two points
    measured with confirm's replicate count must be on an objective for the
    dominance test to separate them (the same t the front uses)."""
    reps = max(1, int(((pol.get("states") or {}).get("confirm") or {}).get(
        "design", {}).get("replicates", 3) or 3))
    n = max(2, int(par.get("n_measured_configurations") or 2))
    out = {}
    for o in objs:
        pv = (par.get("pooled_variance") or {}).get(o.metric) or {}
        v, df = pv.get("variance"), int(pv.get("df") or 0)
        if v is None or df <= 0:
            out[o.metric] = 0.0
            continue
        t = pareto.tcrit(_alpha(float(par.get("delta_front") or 0.05), n, len(objs)), df)
        # An unknown epsilon is not subtracted: the margin is then the full
        # t * se, the conservative reading.
        e = eps.get(o.metric)
        out[o.metric] = max(0.0, t * math.sqrt(2.0 * v / reps) - (e if e is not None else 0.0))
    return out


def _resolvable(cand: dict, endpoint: dict, margin: dict, objs) -> bool:
    ahead = behind = False
    for o in objs:
        d = pareto.sign(o.direction) * (float(cand[o.metric]) - float(endpoint[o.metric]))
        m = margin.get(o.metric, 0.0)
        ahead = ahead or d > m
        behind = behind or d < -m
    return ahead and behind


def shortlist_plan(pol, work_dir, rec: dict, rnd: int, prev_conf: dict | None):
    """The ordered seat nominations for a multi-objective confirm round.

    Returns ``[(levels, why, measured)]``; the caller's ``_add`` de-duplicates,
    caps at ``shortlist_size`` and skips measured-inadmissible configurations.

    Round 1 (spec step 4): the best measured admissible configuration per
    objective, the predicted extremes, the preferred (knee by default) point of
    the predicted front, then spread points that maximise the minimum
    normalised distance to what is already seated.

    Round r > 1: the previous round's preferred point, then -- when the
    previous round reported ``front_gap_large`` -- the predicted-front candidate
    nearest the midpoint of each largest gap (``pareto.in_gap``), then front
    points still ``possibly_dominated`` (more replicates resolve them), then
    predicted candidates named as possible dominators, then spread.
    """
    from orchestrator.optimize.stage_runner import _top_measured

    objs = objectives(pol)
    pf = _predicted_from_record(rec.get("predicted_front"))
    pts = measured_points(work_dir, objs)
    vals = [p.means() for p in pts] + [p.predicted for p in pf
                                       if all(isinstance(p.predicted.get(o.metric), (int, float))
                                              for o in objs)]
    eps = pareto.resolve_eps(objs, best_reference(pts, objs) or best_reference_pred(vals, objs))
    frame = pareto.make_frame(objs, vals, eps)
    plan: list[tuple[dict, str, bool]] = []
    seated_z: list[list[float]] = []

    def nominate(levels, why, measured, values):
        if not levels:
            return
        plan.append((dict(levels), why, measured))
        if values:
            seated_z.append(_z_of(frame, values))

    by_key = {json.dumps(p.levels, sort_keys=True, default=str): p for p in pts}

    def measured_values(levels):
        p = by_key.get(json.dumps(levels, sort_keys=True, default=str))
        return p.means() if p else None

    pred_by_key = {json.dumps(p.levels, sort_keys=True, default=str): p for p in pf}

    def pred_values(levels):
        p = pred_by_key.get(json.dumps(levels, sort_keys=True, default=str))
        return p.predicted if p else None

    if rnd > 1 and prev_conf and prev_conf.get("pareto"):
        par = prev_conf["pareto"]
        chosen = (par.get("preference") or {}).get("chosen")
        nominate(chosen, "previous round's preferred point", True,
                 measured_values(chosen or {}))
        front = par.get("front") or []
        if par.get("front_gap_large") and _FRONT_GAP_FILL:
            margin = _resolution_margin(pol, par, objs, eps)
            for g in par.get("gaps_remaining") or []:
                i, j = g["between"]
                if i >= len(front) or j >= len(front):
                    continue
                za, zb = frame.z(front[i]["mean"]), frame.z(front[j]["mean"])
                mid = [(a + b) / 2 for a, b in zip(za, zb)]
                inside = [p for p in sorted(pf, key=lambda p: p.status != "nondominated")
                          if all(
                    isinstance(p.predicted.get(o.metric), (int, float)) for o in objs)
                    and pareto.in_gap(frame.z(p.predicted), za, zb)
                    and json.dumps(p.levels, sort_keys=True, default=str)
                    not in {json.dumps(f["levels"], sort_keys=True, default=str) for f in front}]
                # Only a candidate the next round could tell apart from BOTH
                # endpoints: ahead of each on some objective and behind it on
                # another by the resolution margin t * se - eps (predicted
                # values, the replicate count confirm uses). An unresolvable
                # fill only adds a rival that strips its neighbours' status.
                inside = [p for p in inside
                          if _resolvable(p.predicted, front[i]["mean"], margin, objs)
                          and _resolvable(p.predicted, front[j]["mean"], margin, objs)]
                if inside:
                    # A point-NONDOMINATED prediction first: a merely possibly-
                    # nondominated one inside the gap is predicted to be beaten.
                    tier = [p for p in inside if p.status == "nondominated"] or inside
                    best = min(tier, key=lambda p: math.dist(frame.z(p.predicted), mid))
                    nominate(best.levels, f"gap fill between front points {i} and {j} "
                                          f"(size {g['size']:.3g})", False, best.predicted)
        for f in front:
            if f.get("status") == "possibly_dominated":
                nominate(f["levels"], "front point still possibly dominated", True, f["mean"])
        for f in front:
            for d in f.get("dominated_by") or []:
                if d.get("kind") == "predicted":
                    nominate(d["levels"], "predicted possible dominator of a front point",
                             False, pred_values(d["levels"]))
    else:
        for o in objs:
            top = _top_measured(work_dir, o.metric, direction=o.direction, k=1)
            if top:
                nominate(top[0]["levels"], f"best measured admissible {o.metric}", True,
                         measured_values(top[0]["levels"]))
        nd = [p for p in pf if p.status == "nondominated"]
        for o in objs:
            s = pareto.sign(o.direction)
            ok = [p for p in nd if isinstance(p.predicted.get(o.metric), (int, float))]
            if ok:
                ex = max(ok, key=lambda p: s * p.predicted[o.metric])
                nominate(ex.levels, f"predicted extreme of {o.metric}", False, ex.predicted)
        basis = (rec.get("preferred_basis") or {}).get("basis")
        nominate(rec.get("levels"),
                 f"objective {objs[0].metric!r} argmax (no predicted front)"
                 if basis == "primary_argmax_fallback" else
                 f"preferred point of the predicted front ({preference(pol).method})",
                 False, pred_values(rec.get("levels") or {}))
    # Round r > 1 spends its seats on what the campaign has NOT measured
    # freshly yet. Re-seating an already-confirmed point the front is sure of
    # buys nothing for the front, and on a noisy constraint boundary it is how
    # an admissible point gets struck off by one unlucky replicate (measured on
    # `pareto_with_constraint`: a third round re-measured two confident front
    # points and lost both). Points still `possibly_dominated` were already
    # nominated above, on purpose.
    confirmed = ({json.dumps(p.levels, sort_keys=True, default=str)
                  for p in pts if p.source == "confirm"} if rnd > 1 else set())

    def fresh(levels) -> bool:
        return json.dumps(levels, sort_keys=True, default=str) not in confirmed

    # Spread over the point-NONDOMINATED predictions first; only then over the
    # merely possibly-nondominated ones, so a seat is never spent on a point the
    # models predict is beaten while a predicted front point is still unseated.
    for tier in ("nondominated", "possibly_nondominated"):
        pool = [p for p in pf if p.status == tier and fresh(p.levels) and all(
            isinstance(p.predicted.get(o.metric), (int, float)) for o in objs)]
        for i in pareto.spread_order([frame.z(p.predicted) for p in pool], seated_z):
            nominate(pool[i].levels, "spread along the predicted front", False,
                     pool[i].predicted)
    return plan


# ── confirm: the measured front ─────────────────────────────────────────────


def front_record(pol, work_dir, *, rec: dict, rnd: int,
                 baseline: dict | None) -> dict:
    """The measured front, the preferred point, its certificate inputs, the
    hypervolume and the gaps (spec steps 5-8). Pure over what is on disk."""
    objs = objectives(pol)
    metrics = [o.metric for o in objs]
    pts, incomplete = measured_points_and_incomplete(work_dir, objs)
    delta_t = float(pol["objective"]["delta_terminal"])
    max_rounds = int(((pol.get("states") or {}).get("confirm") or {}).get(
        "design", {}).get("max_rounds", 1) or 1)
    # Two levels, two looks. The front's STATUSES (and the hypervolume over the
    # confident points) are a claim made once, at the end, over the measured
    # points: delta_terminal. CERTIFICATION is a stopping rule evaluated every
    # round -- certified -> report -- so it pays for every registered look:
    # delta_terminal / max_rounds ("front gap fill, Bonferroni over rounds").
    # Charging the round count to the statuses too made every extra registered
    # round shrink the confident set even when it bought new points (measured
    # on `pareto_noisy`).
    delta_front = delta_t
    # A refill round (policy.REFILL_ACCOUNTING) is a look beyond the cap, so
    # the divisor is the larger of the registered cap and the rounds spent.
    delta_cert = delta_t / max(1, max_rounds, int(rnd or 1))
    pool = pooled(pts, objs)
    # UNKNOWN STAYS UNKNOWN: an epsilon with no reference (a pct of a zero
    # best) is None all the way through -- it resolves nothing, blocks
    # certification (`epsilon_unknown`) and is printed as unknown.
    eps = pareto.resolve_eps(objs, best_reference(pts, objs))
    eps_unknown = sorted(m for m, e in eps.items() if e is None)
    frame = pareto.make_frame(objs, [p.means() for p in pts], eps)
    om = rec.get("objective_models") or {}
    adequate = bool(om) and all((om.get(m) or {}).get("modelled") for m in metrics)
    predicted = _predicted_from_record(rec.get("predicted_front")) if adequate else []
    if predicted:
        # A configuration the campaign MEASURED inadmissible is outside the
        # space: its prediction is no rival of an admissible point. (The
        # predicted front was written before confirm measured it -- found on a
        # vacated round whose only "dominator" was a finalist it had just
        # struck off.)
        from orchestrator.optimize.stage_runner import (
            _config_admissible,
            _measured_infeasible,
        )

        _invalid = _measured_infeasible(work_dir)
        predicted = [pp for pp in predicted
                     if _config_admissible(work_dir, pp.levels, invalid=_invalid)]
    if adequate:
        predicted_rivals = {"considered": True, "n": len(predicted),
                            "reason": "every objective model adequate: predicted-front "
                                      "candidates are checked as rivals of each "
                                      "measured point"}
    else:
        bad = sorted(m for m in metrics if not (om.get(m) or {}).get("modelled"))
        predicted_rivals = {"considered": False, "n": 0,
                            "reason": (f"objective model(s) {bad} not adequate "
                                       f"(no pure error, lack of fit, or not "
                                       f"estimable): statuses rest on measured "
                                       f"rivals only")}
    entries = pareto.measured_front(pts, objs, eps, delta=delta_front,
                                    pooled=pool, predicted=predicted)
    entries.sort(key=lambda e: (-pareto.sign(objs[0].direction)
                                * pts[e.index].mean(metrics[0]), e.index))
    confident = [e for e in entries if e.status == "confidently_nondominated"]
    # The preference runs over the WHOLE measured front; confidence decides
    # certification (chosen_cert_status below), not which point is preferred.
    # Restricting the choice to confident points made the knee degenerate on a
    # real campaign: two confident points, both extremes of themselves, so the
    # "knee" was the tie-break -- the lowest-memory point, 24% slower than a
    # front point that gave up 4 MiB for +16% throughput.
    choose_from = entries
    zs_all = [frame.z(pts[e.index].means()) for e in entries]
    ref_z = [0.0] * len(objs)
    ref_raw = {o.metric: frame.worst[o.metric] for o in objs}
    if baseline:
        b = next((p for p in pts if _same(p.levels, baseline)), None)
        if b is not None:
            ref_z = [max(0.0, x) for x in frame.z(b.means())]
            ref_raw = b.means()
    pref = preference(pol)
    eps_z = frame.eps_z(eps)
    chosen_entry = None
    if choose_from:
        zs = [frame.z(pts[e.index].means()) for e in choose_from]
        i = pareto.preferred_index(pref, objs, zs, [pts[e.index].levels for e in choose_from],
                                   eps_z, ref_z)
        chosen_entry = choose_from[i] if i is not None else None
    # The preferred point's status at the CERTIFICATION level (see above).
    chosen_cert_status = None
    if chosen_entry is not None:
        at_cert = pareto.measured_front(pts, objs, eps, delta=delta_cert,
                                        pooled=pool, predicted=predicted)
        chosen_cert_status = next((e.status for e in at_cert
                                   if e.index == chosen_entry.index), None)
    regret, regret_method = None, "no front"
    # The regret is taken over EVERY measured admissible configuration, not
    # only the front: a point the front eps-dominates in point estimate can
    # still carry an upper bound above the chosen point's, and leaving it out
    # would understate the bound.
    if chosen_entry is not None:
        ci = entries.index(chosen_entry)
        if pref.method == "knee" and len(objs) > 2:
            regret, regret_method = pareto.min_improvement_regret(
                objs, pts, chosen_entry.index, list(range(len(pts))), frame,
                ref_z, pool, delta=delta_cert)
        else:
            a = pareto.scalar_direction(pref, objs, zs_all, ci, ref_z)
            regret, regret_method = pareto.scalar_regret(
                objs, pts, chosen_entry.index, list(range(len(pts))), a,
                frame, pool, delta=delta_cert)
    eps_scalar = pareto.scalar_epsilon(pref, objs, eps_z)
    if confident:
        hv, hv_method = pareto.hypervolume(
            [frame.z(pts[e.index].means()) for e in confident], ref_z)
        hv_reason = None
    else:
        # Not zero: "the confident front encloses nothing" and "no point is
        # confident" are different facts.
        hv, hv_method = None, "none"
        hv_reason = "no confidently_nondominated point: the hypervolume is undefined"
    gaps = pareto.front_gaps(zs_all)
    # The spec's threshold is 2 x max_k(eps_k / range_k). A gap is also only
    # worth a round when a point placed at its midpoint could be told apart
    # from BOTH neighbours at the replicate count confirm uses: on its
    # trade-off coordinate it differs from each by about gap / 2, and the
    # dominance test resolves a pair once that difference exceeds
    # t * se(difference) - eps. Below that a fill only adds an unresolvable
    # rival -- which can LOWER the confident hypervolume (measured on
    # `pareto_noisy`) -- so the threshold is the larger of the two.
    reps = max(1, int(((pol.get("states") or {}).get("confirm") or {}).get(
        "design", {}).get("replicates", 3) or 3))
    resolvable = []
    for o, ez in zip(objs, eps_z):
        v, df = pool.get(o.metric, (None, 0))
        if v is None or df <= 0 or ez is None:
            continue
        t = pareto.tcrit(_alpha(delta_front, len(pts), len(objs)), df)
        se_z = math.sqrt(2.0 * v / reps) / frame.range[o.metric]
        resolvable.append(2.0 * max(0.0, t * se_z - ez))
    known_z = [ez for ez in eps_z if ez is not None]
    # No known epsilon at all: there is no indifference to compare a gap with,
    # so no gap is called large (and every gap is listed as remaining).
    threshold = max([2.0 * max(known_z)] + resolvable) if known_z else None
    gap_large = bool(gaps) and threshold is not None and gaps[0]["size"] > threshold

    def _ci(p, o):
        v, df = pool.get(o.metric, (None, 0))
        mu = p.mean(o.metric)
        if v is None or df <= 0:
            return None
        h = pareto.tcrit(delta_t / 2.0, df) * math.sqrt(v / p.n(o.metric))
        return [mu - h, mu + h]

    front = []
    for e in entries:
        p = pts[e.index]
        front.append({
            "levels": dict(p.levels),
            "n": min(p.n(m) for m in metrics),
            "mean": {m: p.mean(m) for m in metrics},
            "ci": {o.metric: _ci(p, o) for o in objs},
            "status": e.status,
            "dominated_by": e.dominated_by,
            "source": p.source,
        })
    return {
        "objectives": [{"metric": o.metric, "direction": o.direction} for o in objs],
        "front": front,
        "hypervolume": {"value": hv, "reference": ref_raw, "normalized": True,
                        "method": hv_method, "n_points": len(confident),
                        **({"reason": hv_reason} if hv_reason else {}),
                        "over": "confidently_nondominated points, objectives "
                                "normalised to [0, 1] by the measured range"},
        "preference": {"method": pref.method,
                       "chosen": dict(pts[chosen_entry.index].levels) if chosen_entry else {},
                       "chosen_status": chosen_entry.status if chosen_entry else None,
                       "chosen_status_at_certification": chosen_cert_status,
                       "scalar_regret": regret, "scalar_epsilon": eps_scalar,
                       "scalar_regret_method": regret_method},
        "rounds": rnd,
        "gaps_remaining": [g for g in gaps
                           if threshold is None or g["size"] > threshold],
        "gap_threshold": threshold,
        "front_gap_large": gap_large,
        "epsilon": eps,
        "epsilon_unknown": eps_unknown,
        **({"excluded_incomplete": incomplete} if incomplete else {}),
        "predicted_rivals": predicted_rivals,
        "delta_front": delta_front,
        "delta_certification": delta_cert,
        "pooled_variance": {m: {"variance": v, "df": df} for m, (v, df) in pool.items()},
        "frame": frame.as_dict(),
        "n_measured_configurations": len(pts),
        "dominance_method": (
            "pooled within-configuration variance per objective (one-way ANOVA "
            "mean square), one-sided t at delta_front / (N (N - 1) K), Bonferroni "
            "over every (member, rival, objective) bound so the statuses hold "
            "SIMULTANEOUSLY over the front; delta_front = delta_terminal. The "
            "preferred point's certificate (its status and the scalar regret) "
            "is re-taken at delta_certification = delta_terminal / max_rounds"),
    }


def _alpha(delta: float, n: int, k: int) -> float:
    """The per-bound level of the simultaneous front claim (pareto.measured_front)."""
    return float(delta) / max(1, n * (n - 1) * k)


def _same(a: dict, b: dict) -> bool:
    from orchestrator.optimize.stage_runner import _same_levels

    return set(a) == set(b) and _same_levels(a, b)
