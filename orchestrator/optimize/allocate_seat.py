"""WP-D D1 / P6b: the registered ALLOCATE confirm round (opt-in).

STATISTICS OWNS INFERENCE; DECISION THEORY OWNS ALLOCATION. This module is the
only path from the confirm runtime (``stage_runner``) to the allocator
(``allocate``). What it hands back is NOMINATIONS -- configurations, a reason
string and a JSON record of how they were ranked -- never a fitted model, a
prediction or a score that any bound reads. The seated configurations are then
measured on FRESH replicates like every other finalist, and their certificate
is the ordinary terminal / front certificate over those replicates. Nothing in
``certificate``, ``pareto``, ``noise`` or the bound code reads the record this
module writes (``tests/test_optimize_allocate_seat.py`` checks it behaviourally:
rewriting every predicted number leaves every bound unchanged).

THE BRANCH. ``optimization.design.confirm.allocate: {seats: k}`` (default off).
When declared, ``policy.compile_policy`` registers one ``confirm -> confirm``
transition (``policy.ALLOCATE_ACCOUNTING``) guarded by ``allocate_available``,
``confirm_affordable`` and the round cap. It fires at most once per epoch, AT
the cap, so it is exactly one extra look, and ``policy.confirm_looks`` and the
P3 replicate floor (``policy._registered_looks``) charge that look whether or
not it is taken. Every confirm-stage Bonferroni divisor therefore includes it.

WHAT IS SEATED. At the end of every confirm round (until the branch is spent)
``plan`` runs ``allocate.allocate`` on what is on disk: the round's measured
admissible finalists (single objective) or the measured non-dominated front
(multi-objective) as the recombination basis, the round's winner / preferred
point as the anchor, the fitting stage's model and its ranked candidates or
predicted front, and (when ``planner.bo`` is compiled) BO proposals. The top
``seats`` ranked candidates that can be seated (not measured, not measured
inadmissible, not naming a barred level) are written into that round's
``confirmation.json["allocation"]``, and ``allocate_available`` is true exactly
when there is at least one. The allocate round then reads those seats from the
record -- it does not recompute them -- so what was registered before the
transition is what runs.

DECLINES ARE NAMED. ``allocate.DECLINE_REASONS`` (the model gate first:
``model_inadequate``, ``model_adequacy_unknown``, ...) plus the reasons this
module adds (``SEAT_DECLINE_REASONS``). A declined round seats nothing and the
branch does not fire.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: The reasons this module adds to ``allocate.DECLINE_REASONS``.
SEAT_DECLINE_REASONS = {
    "no_fit_record": "the fitting stage left no model record confirm can read "
                     "(no effects.json / objective_fits)",
    "no_seatable_candidate": "the allocator ranked candidates, but every one was "
                             "already measured, measured inadmissible or names a "
                             "barred level",
    "no_expected_value": "every seatable candidate scores zero (knowledge gradient "
                         "/ EHVI per run): the model expects no gain from measuring "
                         "it, so the round is not spent",
}


def constants() -> dict:
    """The allocator's constants, for ``provenance.analysis_constants``."""
    from orchestrator.optimize import allocate

    return {"allocate.POOL_CAP": allocate.POOL_CAP,
            "allocate.MC_SAMPLES": allocate.MC_SAMPLES,
            "allocate.MC_SEED": allocate.MC_SEED,
            "allocate.MC_WORK_CAP": allocate.MC_WORK_CAP}


def decline_reasons() -> dict:
    from orchestrator.optimize import allocate

    return {**allocate.DECLINE_REASONS, **SEAT_DECLINE_REASONS}


def seats_declared(pol: dict) -> int:
    """``seats`` of the compiled allocate branch, 0 when it is not registered."""
    from orchestrator.optimize.policy import ALLOCATE_ACCOUNTING

    if not any(t.get("accounting") == ALLOCATE_ACCOUNTING
               for t in (pol or {}).get("transitions") or []):
        return 0
    cfg = ((((pol.get("states") or {}).get("confirm") or {}).get("design") or {})
           .get("allocate") or {})
    return max(0, int(cfg.get("seats", 0) or 0))


def _rule_accounting(t: dict) -> str | None:
    return (t.get("rule") or {}).get("accounting")


def spent(pol: dict, work_dir) -> bool:
    """Has this epoch already entered its allocate round?"""
    from orchestrator.optimize import policy as policy_mod

    return any(_rule_accounting(t) == policy_mod.ALLOCATE_ACCOUNTING
               for t in policy_mod.epoch_transitions(pol, Path(work_dir)))


def is_allocate_round(pol: dict, work_dir) -> bool:
    """Is the confirm round about to run the registered allocate branch?"""
    from orchestrator.optimize import policy as policy_mod

    trans = policy_mod.epoch_transitions(pol, Path(work_dir))
    return bool(trans) and _rule_accounting(trans[-1]) == policy_mod.ALLOCATE_ACCOUNTING


def seats_digest(seats) -> str:
    """sha256 of the registered seats (canonical JSON). Round r records it in
    its transition's observations (``allocate_seats_sha256``) and writes the
    record to ``runs/iter-r/allocation.json`` (a hashed provenance input), so
    an edit to the seats after registration is detected before they run."""
    import hashlib

    return hashlib.sha256(json.dumps(seats or [], sort_keys=True, default=str)
                          .encode()).hexdigest()


def registered_seats(pol: dict, work_dir, conf: dict | None) -> list[dict]:
    """The seats ``conf`` (the previous round's confirmation.json) registered,
    VERIFIED against the digest the transition out of that round recorded.
    Raises ``OptimizationGateFailed`` naming the file on a mismatch: what runs
    must be what was registered before the transition fired (P6b review H1)."""
    from orchestrator.optimize import policy as policy_mod
    from orchestrator.optimize.stage_runner import OptimizationGateFailed

    seats = ((conf or {}).get("allocation") or {}).get("seats") or []
    if not seats:
        return []
    it = (conf or {}).get("iteration")
    row = next((t for t in reversed(policy_mod.epoch_transitions(pol, Path(work_dir)))
                if t.get("iteration") == it and t.get("from") == "confirm"), None)
    want = ((row or {}).get("observations") or {}).get("allocate_seats_sha256")
    got = seats_digest(seats)
    if want != got:
        raise OptimizationGateFailed(
            f"runs/iter-{it}/confirmation.json: the allocate seats on disk "
            f"(sha256 {got[:12]}) are not the seats registered when the round "
            f"closed (transitions.jsonl iteration {it} records "
            f"{str(want)[:12] if want else 'no digest'}). The registered seats "
            f"were edited after registration; refusing to measure them.")
    return seats


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, ValueError):
        return None


def _so_fit(work_dir, rec: dict):
    """The primary's Fit from the fitting stage's effects.json, or None."""
    from orchestrator.optimize.planner import _fit_from_effects

    it = rec.get("iteration")
    if not isinstance(it, int):
        return None, None
    eff = _read(Path(work_dir) / "runs" / f"iter-{it}" / "effects.json")
    if not eff or eff.get("intercept") is None:
        return None, None
    return _fit_from_effects(eff)


def _epoch_rows(work_dir) -> list[dict]:
    from orchestrator.optimize.stage_runner import _this_epoch_runs

    out = []
    for p in _this_epoch_runs(work_dir):
        for ln in p.read_text().splitlines():
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    return out


def _bo_proposals(pol, work_dir, factors, objectives, held_fixed) -> tuple[list, dict | None]:
    cfg = ((pol or {}).get("planner") or {}).get("bo")
    if cfg is None:
        return [], None
    from orchestrator.optimize import bo_proposer

    try:
        props, prov = bo_proposer.propose(
            [r for r in _epoch_rows(work_dir) if r.get("status") == "complete"],
            factors=factors, objectives=objectives,
            config=bo_proposer.bo_config(pol), n=8, held_fixed=held_fixed)
    except bo_proposer.BOUnavailable as exc:
        return [], {"unavailable": str(exc)}
    return props, prov


def _seatable(work_dir, levels: dict, measured_keys: set) -> bool:
    from orchestrator.optimize.stage_runner import (
        _barred_levels,
        _measured_infeasible_contains,
        _names_barred_level,
    )

    key = json.dumps(levels, sort_keys=True, default=str)
    if key in measured_keys:
        return False
    if _names_barred_level(levels, _barred_levels(work_dir)):
        return False
    return not _measured_infeasible_contains(work_dir, levels)


def plan(pol: dict, work_dir, factors, conf: dict, rec: dict | None) -> dict:
    """The allocation record for the round ``conf`` describes (its summary,
    multi-objective ``pareto`` block included). ``record["seats"]`` is what
    the allocate round will measure, ``[]`` on any decline (named)."""
    from orchestrator.optimize import allocate, pareto_stage
    from orchestrator.optimize.stage_runner import _top_measured

    k = seats_declared(pol)
    rec = rec or {}
    objs = pareto_stage.objectives(pol)
    obj_list = ([{"metric": o.metric, "direction": o.direction} for o in objs] if objs
                else [{"metric": pol["objective"]["metric"],
                       "direction": pol["objective"]["direction"]}])
    reps = max(1, int(((pol["states"]["confirm"] or {}).get("design") or {}).get(
        "replicates", 3)))
    out = {"seats_declared": k, "seats": [], "declined": None, "detail": "",
           "selection": "on the fitted model's predictions (allocate.py); the claim "
                        "about any seat rests on its fresh replicates only"}

    def decline(reason: str, detail: str = "", **kw) -> dict:
        out.update(declined=reason, detail=detail or decline_reasons()[reason], **kw)
        logger.info("confirm: the allocate branch declines (%s): %s", reason, out["detail"])
        return out

    # The model gate first, before any fit is even rebuilt (allocate does the
    # same): an inadequate model never ranks anything.
    if rec.get("model_adequate") is False:
        return decline("model_inadequate")
    if objs:
        from orchestrator.optimize.certificate import fit_from_record

        fr = rec.get("objective_fits") or {}
        fits = {o.metric: (fit_from_record(fr[o.metric]) if fr.get(o.metric) else None)
                for o in objs}
        par = conf.get("pareto") or {}
        front_points = [dict(f["levels"]) for f in par.get("front") or []
                        if not f.get("dominated_by")]
        preferred = dict((par.get("preference") or {}).get("chosen") or {})
        pts = pareto_stage.measured_points(work_dir, objs)
        measured = [{"levels": dict(p.levels), "mean": p.means()} for p in pts]
        predicted = [{"levels": dict(e.get("levels") or {}), "source": "predicted_front"}
                     for e in rec.get("predicted_front") or () if e.get("levels")]
    else:
        fit, how = _so_fit(work_dir, rec)
        if fit is None:
            return decline("no_fit_record")
        fits = {obj_list[0]["metric"]: fit}
        out["predictive"] = how
        front_points = [dict(f["levels"]) for f in conf.get("finalists") or []
                        if f.get("status") == "ok"]
        preferred = dict(conf.get("confirmed_at_levels") or {})
        m = obj_list[0]["metric"]
        measured = [{"levels": dict(t["levels"]), "mean": {m: t[m]}}
                    for t in _top_measured(work_dir, m, direction=obj_list[0]["direction"],
                                           k=10 ** 9)]
        predicted = [{"levels": dict(c.get("levels") or {}), "source": "model_top_candidate"}
                     for c in rec.get("top_candidates") or () if c.get("levels")]
    held = dict(rec.get("held_fixed") or {})
    props, bo_prov = _bo_proposals(pol, work_dir, factors, obj_list, held)
    if bo_prov is not None:
        out["bo"] = bo_prov
    al = allocate.allocate(
        front_points=front_points, preferred=preferred, fits=fits,
        objectives=obj_list, factors=factors,
        fitted_ids=list(rec.get("fitted_ids") or []), held_fixed=held,
        measured=measured, model_adequate=rec.get("model_adequate"),
        replicates=reps, predicted_front=predicted, proposals=props)
    out["method"] = {kk: v for kk, v in (al.method or {}).items()
                     if kk not in ("frame",)}
    out["pool_size"] = al.pool_size
    out["ranked_top"] = [{"levels": r["levels"], "source": r.get("source"),
                          "score": r.get("score"), "rationale": r.get("rationale")}
                         for r in al.ranked[:max(8, k)]]
    if al.declined is not None:
        return decline(al.declined, al.detail)
    measured_keys = {json.dumps(x["levels"], sort_keys=True, default=str) for x in measured}
    seatable = [r for r in al.ranked
                if _seatable(work_dir, dict(r["levels"]), measured_keys)]
    if not seatable:
        return decline("no_seatable_candidate")
    # A seat is spent only where the model expects a gain: a zero score means
    # measuring the candidate cannot move the best claimable value (KG) or the
    # front (EHVI). Allocation buys information, it does not fill seats.
    for r in seatable:
        if len(out["seats"]) >= k:
            break
        if not (isinstance(r.get("score"), (int, float)) and r["score"] > 0.0):
            break       # ranked best first: nothing after it scores either
        lv = dict(r["levels"])
        if any(s["levels"] == lv for s in out["seats"]):
            continue
        out["seats"].append({"levels": lv, "source": r.get("source"),
                             "score": float(r["score"]),
                             "why": f"allocate: {r.get('rationale')}"})
    if not out["seats"]:
        return decline("no_expected_value")
    return out
