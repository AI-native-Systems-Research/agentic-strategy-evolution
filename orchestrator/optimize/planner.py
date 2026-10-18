"""WP-D D2: ``nous plan-next`` -- the epoch planner (zero model tokens).

DECISION THEORY OWNS ALLOCATION; STATISTICS OWNS INFERENCE. After an epoch
ends at ``report``, this module enumerates the candidate NEXT epochs and
scores each one by expected value of information per run, under a STATED
utility. It writes ``planner_decision.json`` and a proposed next campaign (a
validated diff against the current one). Nothing here decides a certificate.
The next epoch is still compiled and pre-registered from the accepted
campaign, before any of its data exist, and it certifies at its own (charged)
error budget. The decision file records the choice, its scores, the
assumptions and the cross-epoch error budget. ``--accept`` applies it, and an
override (``--choose X --reason R``) is recorded in the next epoch's
provenance (``epoch_end.planned-<e>.json`` -> ``report.json``
``provenance.planner``).

THE UTILITY AND ITS BOUND (WP-D review H1)
-------------------------------------------
``U(move) = E[ max(tau_R, ...) ]`` is defined through the increment of
adding the move's region R to the measured set M:

    single objective:  Delta = max(max_M f, max_R f) - max_M f
    several:           Delta = HV(front(f(M ∪ R))) - HV(front(f(M)))

Here f is the TRUE mean response, a random function under the belief. The
belief is the fitted model's JOINT posterior: coefficients ~ multivariate t
on the pure-error df, so f(M) and f(x) are correlated as the model says.
Pointwise, ``Delta >= (f(x) - max_M f)^+`` (resp. ``HV(front(f(M)) + f(x)) -
HV(front(f(M)))``) for EVERY x in R. The SCORE

    max_{x in S} E[(f(x) - max_M f)^+]  /  runs    (several: E[HVI])

is therefore a TRUE LOWER BOUND on E[Delta] / runs, for any S ⊆ R. ``S`` is
the top ``allocate.JOINT_PRESELECT`` (``_MO``) candidates by marginal score.
A subset is looser but still a bound, and its size is recorded. The
expectation is a Monte Carlo with ``allocate.JOINT_SAMPLES`` (``_MO``)
draws and seed ``allocate.JOINT_SEED``, both recorded on every option.
Common random numbers across candidates and moves mean differences between
moves are not Monte Carlo noise of independent runs. ``runs`` is the next
epoch's worst-case run count (``preview.build_preview(...).max_runs``). The
bound credits the region only with its best single point and assumes the
next epoch's design finds that point. That optimism is recorded.

(The earlier score, ``max_R EI - max_M EI``, was a difference of two lower
bounds and bounded nothing. On 100 i.i.d. N(0, 1) measured points with
tau = 0 and one N(0.5, 1) candidate, it gave 0.299 against a true increment
of 0.014. ``tests/test_optimize_planner.py`` keeps that case.)

STOP
----
``stop`` is chosen when no feasible move's score exceeds the declared
threshold (``optimization.planner.stop_value_per_run``; default: one
epsilon, or one epsilon-box of normalised hypervolume, per run this epoch
spent). It is also chosen when every move is infeasible: the remaining
charged error budget or run budget cannot cover the next epoch, or no
proposal validates. When the model is not adequate (or allocation declines
for any other named reason), no move can be scored. The planner then chooses
``stop`` with ``decision_basis: no_scorable_move`` and lists the model-free
alternatives (``bo_block``, ``replicate``), which a human or agent may take
with ``--choose``.
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import json
import math
import random
import shlex
from datetime import datetime, timezone
from pathlib import Path

import yaml

#: Candidates scored per region, single objective (EI is O(p^2) each).
REGION_CAP_SO = 50_000
#: Candidates scored per region, multi-objective (EHVI is costlier).
REGION_CAP_MO = 2_000
REGION_SEED = 0
#: How far a widened axis may be scored past its fitted edge, in coded units.
WIDEN_MAX_CODED = 2.0
BO_PROPOSALS = 8
PLAN_DIR = "plan_next"
DECISION_FILE = "planner_decision.json"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "planner_decision.schema.json"


class PlanError(RuntimeError):
    """plan-next cannot plan: the reason is the message (a named decline)."""


def boundary_path(work_dir: Path, epoch: int) -> Path:
    """The planned epoch-boundary record. ``stage_runner._epoch_index`` counts
    ``epoch_end*.json``, so this file is what makes the next ``nous resume``
    recompile into epoch ``epoch + 1``. Its name deliberately does not match
    ``epoch_end-<e>.json``, which means a semantic exception. The reader on
    the report path is ``provenance.planner_provenance``, which never imports
    this module."""
    from orchestrator.optimize.provenance import planned_boundary_path

    return planned_boundary_path(work_dir, epoch)


# ── reading the finished epoch ───────────────────────────────────────────────


def _read(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def _epoch_iterations(work_dir: Path, epoch: int) -> list[int]:
    from orchestrator.optimize.policy import read_transitions

    return sorted({int(r["iteration"]) for r in read_transitions(work_dir)
                   if int(r.get("epoch", 1)) == epoch and isinstance(r.get("iteration"), int)})


def _rows(work_dir: Path, iters) -> list[dict]:
    from orchestrator.optimize import artifacts

    out = []
    for i in iters:
        d = Path(work_dir) / "runs" / f"iter-{i}"
        if d.exists():
            out += [r for r in artifacts.read_runs(d)
                    if not (r.get("reused_from") or {}).get("stage")]
    return out


def _fit_from_effects(eff: dict):
    """The primary's Fit, rebuilt from effects.json. The covariance is
    exact (X'X)^-1 over the recorded fitted coordinates, which is identical to
    the fit's. For a mixed or blocked fit (nuisance columns that
    ``fit_coordinates`` does not carry), the per-term diagonal is used and
    recorded as such."""
    from orchestrator.optimize.certificate import fit_from_record
    from orchestrator.optimize.effects import _invert

    effs = list(eff.get("effects") or []) + list(eff.get("quadratic") or [])
    rec = {"intercept": eff["intercept"], "effects": eff.get("effects") or [],
           "quadratic": eff.get("quadratic") or [], "pure_error_var": eff.get("pure_error_var"),
           "pure_error_df": eff.get("pure_error_df") or 0, "n_runs": eff.get("n_runs") or 0,
           "term_terms": [], "covariance": None}
    fc = eff.get("fit_coordinates") or {}
    nuisance = bool(eff.get("categoricals") or eff.get("centre_isolated")
                    or (fc.get("factor_of_column")))
    how = "per_term_diagonal (mixed-level fit: nuisance columns not recorded)"
    if fc.get("rows") and not nuisance:
        ids = fc["factor_ids"]
        terms = [()] + [tuple(e["terms"]) for e in effs]
        X = [[math.prod(dict(zip(ids, r["fitted"]))[t] for t in ts) for ts in terms]
             for r in fc["rows"]]
        try:
            C = _invert([[sum(a[i] * a[j] for a in X) for j in range(len(terms))]
                         for i in range(len(terms))])
            rec["term_terms"], rec["covariance"] = [list(t) for t in terms], C
            how = "exact (X'X)^-1 over effects.json fit_coordinates"
        except (ValueError, KeyError):
            how = "per_term_diagonal (fit coordinates singular or incomplete)"
    return fit_from_record(rec), how


def load_epoch(work_dir: Path) -> dict:
    """Everything the planner reads, or raise ``PlanError`` naming why not."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import read_policy

    wd = Path(work_dir)
    pol = read_policy(wd)
    if pol is None:
        raise PlanError("no_policy: policy.json is absent; the campaign never compiled an epoch")
    e = int(pol.get("epoch", 1))
    if boundary_path(wd, e).exists():
        raise PlanError(f"already_planned: epoch {e}'s plan was accepted "
                        f"({boundary_path(wd, e).name}); run `nous resume` to start epoch {e + 1}")
    rep = _read(wd / "report.json")
    if not rep or int(rep.get("epoch", 0)) != e:
        raise PlanError(f"epoch_not_finished: report.json for epoch {e} is absent")
    if rep.get("epoch_ended"):
        raise PlanError("epoch_ended_on_exception: a semantic exception ended this epoch; "
                        "revise per epoch_end-<e>.json (`next_epoch_requires`) instead")
    cpath = wd / f"campaign.epoch-{e}.yaml"
    if not cpath.exists():
        raise PlanError(f"no_registered_campaign: {cpath.name} is absent")
    campaign = yaml.safe_load(cpath.read_text()) or {}
    iters = _epoch_iterations(wd, e)
    fit_rec = fit_iter = screen_rec = screen_eff = None
    for i in iters:
        r = _read(wd / "runs" / f"iter-{i}" / "recommendation.json")
        if r and r.get("stage") in ("screen", "foldover", "refine"):
            fit_rec, fit_iter = r, i
            if r.get("stage") == "screen" and screen_rec is None:
                screen_rec = r
                screen_eff = _read(wd / "runs" / f"iter-{i}" / "effects.json")
    if fit_rec is None:
        raise PlanError("no_fit: no fitting stage of this epoch wrote recommendation.json")
    opt = campaign.get("optimization") or {}
    factors = parse_factors(opt["factors"])
    objs = (pol["objective"].get("objectives")
            or [{"metric": pol["objective"]["metric"],
                 "direction": pol["objective"]["direction"]}])
    objs = [{"metric": o["metric"], "direction": o["direction"]} for o in objs]
    fits, predictive = {}, {}
    if len(objs) > 1:
        from orchestrator.optimize.certificate import fit_from_record

        for o in objs:
            d = (fit_rec.get("objective_fits") or {}).get(o["metric"])
            fits[o["metric"]] = fit_from_record(d) if d else None
            predictive[o["metric"]] = ("exact" if d and d.get("covariance") is not None
                                       else "per_term_diagonal")
    else:
        eff = _read(wd / "runs" / f"iter-{fit_iter}" / "effects.json")
        if eff is None:
            raise PlanError(f"no_fit: runs/iter-{fit_iter}/effects.json is absent")
        fits[objs[0]["metric"]], predictive[objs[0]["metric"]] = _fit_from_effects(eff)
    rows = _rows(wd, iters)
    by_cfg: dict = {}
    for r in rows:
        if r.get("status") != "complete":
            continue
        k = json.dumps(r.get("levels") or {}, sort_keys=True, default=str)
        ent = by_cfg.setdefault(k, {"levels": dict(r.get("levels") or {}), "vals": {}})
        for o in objs:
            v = (r.get("response") or {}).get(o["metric"])
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                ent["vals"].setdefault(o["metric"], []).append(float(v))
    measured = [{"levels": v["levels"],
                 "mean": {m: sum(xs) / len(xs) for m, xs in v["vals"].items()}}
                for v in by_cfg.values()]
    return {"work_dir": wd, "policy": pol, "epoch": e, "report": rep, "campaign": campaign,
            "factors": factors, "objectives": objs, "fits": fits, "predictive": predictive,
            "fit_rec": fit_rec, "fit_iter": fit_iter, "screen_rec": screen_rec,
            "screen_eff": screen_eff, "iterations": iters, "rows": rows,
            "measured": measured, "runs_spent": len(rows),
            "fitted_ids": list(fit_rec.get("fitted_ids") or []),
            "held_fixed": dict(fit_rec.get("held_fixed") or {}),
            "model_adequate": fit_rec.get("model_adequate")}


# ── campaign surgery (every move is a full next campaign) ────────────────────


def _axis_levels(f, lo: float, hi: float, n: int) -> list:
    """``n`` evenly spaced levels on ``f``'s axis between ``lo`` and ``hi``
    (raw units), snapped to its grid, de-duplicated, integral when the
    declared levels are."""
    from orchestrator.optimize.factors import _from_axis, _to_axis, snap_to_grid

    a, b = _to_axis(f, lo), _to_axis(f, hi)
    out = []
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in f.levels)
    for i in range(n):
        v = _from_axis(f, a + (b - a) * i / (n - 1))
        v = snap_to_grid(v, f.grid) if f.grid else v
        if ints:
            v = int(round(float(v)))
        else:
            v = round(float(v), 12)
        if v not in out:
            out.append(v)
    return sorted(out)


def _pin(campaign: dict, pins: dict, fid: str, value) -> str | None:
    """Remove factor ``fid``, folding its ``apply`` at ``value`` into
    ``run_command``, and record it in ``pins`` (the region grid needs the
    pinned value). Returns a reason string when the factor cannot be pinned
    that way (a config_patch apply, or no run_command)."""
    opt = campaign["optimization"]
    raw = next(f for f in opt["factors"] if f["id"] == fid)
    ap = raw.get("apply")
    rc = opt.get("run_command")
    if not rc:
        return "no run_command to fold the pinned flag into"
    if isinstance(ap, str) or (isinstance(ap, dict) and ap.get("kind") == "cli_flag"):
        tpl = ap if isinstance(ap, str) else ap["template"]
        opt["run_command"] = f"{rc} {shlex.quote(tpl.replace('{level}', str(value)))}"
    elif isinstance(ap, dict) and ap.get("kind") == "env_var":
        val = value if ap.get("value") == "{level}" else ap.get("value")
        opt["run_command"] = f"env {ap['name']}={shlex.quote(str(val))} {rc}"
    else:
        return f"apply kind {ap.get('kind') if isinstance(ap, dict) else ap!r} cannot be pinned in run_command"
    opt["factors"] = [f for f in opt["factors"] if f["id"] != fid]
    pins[fid] = value
    for key in ("known_valid_baseline",):
        if isinstance(opt.get(key), dict):
            opt[key].pop(fid, None)
            if not opt[key]:
                opt.pop(key)
    return None


def _set_levels(campaign: dict, fid: str, levels: list, *, levels_only: bool | None = None):
    opt = campaign["optimization"]
    for f in opt["factors"]:
        if f["id"] == fid:
            f["levels"] = list(levels)
            f.pop("screen_levels", None)
            if levels_only is not None:
                if levels_only:
                    f["levels_only"] = True
                    f.pop("grid", None)
                else:
                    f.pop("levels_only", None)
    base = opt.get("known_valid_baseline")
    if isinstance(base, dict) and fid in base and base[fid] not in levels:
        return f"known_valid_baseline {fid}={base[fid]!r} is outside the new levels"
    return None


def _repair(campaign: dict) -> list[str]:
    """Keep the next campaign compilable after surgery: drop ``refine`` when
    fewer than two refinable factors remain; drop the screen centre points'
    need for nothing. Returns what was changed."""
    from orchestrator.optimize.factors import is_refinable, parse_factors

    opt = campaign["optimization"]
    notes = []
    fs = parse_factors(opt["factors"])
    if sum(1 for f in fs if is_refinable(f)) < 2 and "refine" in (opt.get("design") or {}):
        opt["design"].pop("refine")
        if opt.get("stages"):
            opt["stages"] = [s for s in opt["stages"] if s != "refine"]
        notes.append("design.refine dropped: fewer than two refinable factors remain")
    return notes


def validate_campaign(campaign: dict) -> list[str]:
    import jsonschema

    from orchestrator.validate import validate_optimization_campaign

    schema = yaml.safe_load((Path(__file__).resolve().parents[1] / "schemas"
                             / "campaign.schema.yaml").read_text())
    errs = [f"[schema] {'.'.join(map(str, e.absolute_path)) or '(top)'}: {e.message}"
            for e in jsonschema.Draft202012Validator(schema).iter_errors(campaign)]
    errs += [e for e in validate_optimization_campaign(campaign) if not e.startswith("WARN")]
    try:
        from orchestrator.optimize.policy import compile_policy

        compile_policy(campaign)
    except Exception as exc:  # noqa: BLE001 -- recorded as the move's reason
        errs.append(f"[compile] {type(exc).__name__}: {exc}")
    return errs


def campaign_hash(campaign: dict) -> str:
    """The same hash ``policy.compiled_from.campaign_hash`` records."""
    from orchestrator.optimize.policy import _canonical

    return hashlib.sha256(_canonical(campaign.get("optimization") or {}).encode()).hexdigest()


# ── the moves ────────────────────────────────────────────────────────────────


def dead_knobs(ep: dict) -> dict:
    """``{factor: (pin_value, evidence)}``. A knob is dead when it was held
    (not fitted) by the final fitting stage AND either the screen found no
    main effect on every objective, or the certificate's held-factor
    inertness check showed it inert (TOST)."""
    from scipy.stats import t as student_t

    held = ep["held_fixed"]
    out = {}
    inert = set(((ep["report"].get("certificate_scope") or {}).get("inertness") or {})
                .get("shown_inert") or [])
    recs = []
    if ep["screen_eff"] and len(ep["objectives"]) == 1:
        recs = [ep["screen_eff"]]
    elif ep["screen_rec"]:
        recs = list((ep["screen_rec"].get("objective_fits") or {}).values())
    for fid, val in held.items():
        if fid in inert:
            out[fid] = (val, "certificate_scope.inertness.shown_inert (TOST)")
            continue
        if not recs:
            continue
        dead = True
        for r in recs:
            df = int(r.get("pure_error_df") or 0)
            if df < 1:
                dead = False
                break
            tc = float(student_t.ppf(0.975, df))
            mains = [e for e in r.get("effects") or [] if len(e.get("terms") or []) == 1
                     and (e["terms"][0] == fid or str(e["terms"][0]).startswith(fid + "["))]
            if not mains or any(e.get("se") is None or abs(e["estimate"]) > tc * e["se"]
                                for e in mains):
                dead = False
                break
        if dead:
            out[fid] = (val, "screen: no main effect at alpha=0.05 on any objective")
    return out


def _active_box(ep: dict, frame_cands) -> dict:
    """``{fid: (lo, hi)}`` (raw units, numeric fitted factors) and
    ``{fid: [levels]}`` (choice) of the active region. Single objective: the
    old-grid candidates not confidently worse than the best (UCB >= max LCB,
    one-sided t at 0.95). Multi-objective: the recorded predicted front."""
    from scipy.stats import t as student_t

    from orchestrator.optimize.constraint_models import predicted_with_se

    objs = ep["objectives"]
    if len(objs) > 1:
        pts = [p["levels"] for p in ep["fit_rec"].get("predicted_front") or []]
    else:
        o = objs[0]
        fit = ep["fits"][o["metric"]]
        sg = -1.0 if o["direction"] == "minimize" else 1.0
        tc = float(student_t.ppf(0.95, max(int(fit.pure_error_df), 1)))
        scored = []
        for lv, c in frame_cands:
            y, s = predicted_with_se(fit, c)
            scored.append((lv, sg * y - tc * s, sg * y + tc * s))
        best_lcb = max(x[1] for x in scored)
        pts = [lv for lv, _l, u in scored if u >= best_lcb]
    return pts


def _grid(campaign: dict, ep: dict, *, cap: int, max_coded: float,
          pins: dict | None = None) -> tuple[list, dict]:
    """The candidates of the move's region, coded for the CURRENT fit:
    ``([(levels, coded)], record)``. The size is computed before anything is
    enumerated; above ``cap`` a seeded uniform sample is taken and recorded."""
    from orchestrator.optimize.allocate import coded_of
    from orchestrator.optimize.decide import _axis
    from orchestrator.optimize.factors import parse_factors

    new = {f.id: f for f in parse_factors(campaign["optimization"]["factors"])}
    held = ep["held_fixed"]
    ids = [fid for fid in ep["fitted_ids"] if fid in new]
    axes = [[lv for _c, lv in _axis(new[fid])] for fid in ids]
    pinned = {**held, **dict(pins or {})}
    size = math.prod(len(a) for a in axes) if axes else 0
    rec = {"size": size, "cap": cap, "sampled": size > cap, "max_coded": max_coded}
    if size > cap:
        rng = random.Random(REGION_SEED)
        combos = {tuple(rng.randrange(len(a)) for a in axes) for _ in range(cap)}
        combos = [tuple(a[i] for a, i in zip(axes, c)) for c in sorted(combos)]
        rec["seed"] = REGION_SEED
    else:
        import itertools

        combos = list(itertools.product(*axes))
    out, dropped = [], 0
    for combo in combos:
        lv = {**pinned, **dict(zip(ids, combo))}
        try:
            out.append((lv, coded_of(lv, fitted_ids=ep["fitted_ids"], factors=ep["factors"],
                                     held_fixed=held, max_coded=max_coded)))
        except (ValueError, KeyError):
            dropped += 1
    rec["scored"] = len(out)
    rec["outside_model"] = dropped
    if pins:
        rec["pinned"] = dict(pins)
    return out, rec


def _moves(ep: dict) -> list[dict]:
    """Every candidate next epoch: ``{id, kind, campaign, notes, max_coded}``."""
    from orchestrator.optimize.decide import _axis
    from orchestrator.optimize.factors import _to_axis, is_refinable

    base = ep["campaign"]
    by_id = {f.id: f for f in ep["factors"]}
    out = []
    dead = dead_knobs(ep)

    def fresh():
        return copy.deepcopy(base)

    # pin_dead
    if dead:
        c, notes, pins = fresh(), [], {}
        for fid, (v, why) in sorted(dead.items()):
            r = _pin(c, pins, fid, v)
            notes.append(f"pin {fid}={v!r} ({why})" if r is None else f"cannot pin {fid}: {r}")
        out.append({"id": "pin_dead", "kind": "pin_dead", "campaign": c, "notes": notes,
                    "max_coded": 1.0, "pins": pins})

    # narrow around the active region
    old_cands, pts = [], []
    try:
        if len(ep["objectives"]) == 1:
            old_cands, _ = _grid(base, ep, cap=REGION_CAP_SO, max_coded=1.0)
        pts = _active_box(ep, old_cands) if old_cands or len(ep["objectives"]) > 1 else []
    except Exception as exc:  # noqa: BLE001 -- recorded as the option's reason (M4)
        out.append({"id": "narrow", "kind": "narrow", "campaign": None,
                    "failed": f"region_failed: {type(exc).__name__}: {exc}",
                    "notes": ["the active region could not be computed"], "max_coded": 1.0})
        pts = []
    if pts:
        c, notes, changed, pins = fresh(), [], False, {}
        for fid in ep["fitted_ids"]:
            f = by_id[fid]
            vals = [p[fid] for p in pts if fid in p]
            if not vals:
                continue
            if f.type == "choice":
                keep = [lv for lv in f.levels if lv in vals]
                if len(keep) == 1:
                    r = _pin(c, pins, fid, keep[0])
                    notes.append(f"pin {fid}={keep[0]!r} (the only level in the active region)"
                                 if r is None else f"cannot pin {fid}: {r}")
                    changed = changed or r is None
                elif len(keep) < len(f.levels):
                    _set_levels(c, fid, keep)
                    notes.append(f"{fid} levels -> {keep}")
                    changed = True
                continue
            ax = [lv for _c, lv in _axis(f)]
            idx = [ax.index(v) for v in vals if v in ax]
            if not idx:
                continue
            lo_i, hi_i = max(min(idx) - 1, 0), min(max(idx) + 1, len(ax) - 1)
            lo, hi = ax[lo_i], ax[hi_i]
            if (lo, hi) == (min(ax, key=lambda v: _to_axis(f, v)),
                            max(ax, key=lambda v: _to_axis(f, v))):
                continue
            if f.levels_only:
                lv = [x for x in f.levels if float(lo) <= float(x) <= float(hi)]
            else:
                lv = _axis_levels(f, float(lo), float(hi), max(3, min(len(f.levels), 5)))
            if len(lv) < 2:
                r = _pin(c, pins, fid, lo)
                notes.append(f"pin {fid}={lo!r} (active region is one level)"
                             if r is None else f"cannot pin {fid}: {r}")
            else:
                why = _set_levels(c, fid, lv)
                notes.append(f"{fid} range {list(f.screen_levels)} -> [{lv[0]}, {lv[-1]}] "
                             f"(active region plus one candidate step)" + (f"; {why}" if why else ""))
            changed = True
        for fid, (v, _w) in sorted(dead.items()):
            if any(x["id"] == fid for x in c["optimization"]["factors"]):
                if _pin(c, pins, fid, v) is None:
                    notes.append(f"pin dead {fid}={v!r}")
        if changed:
            notes += _repair(c)
            out.append({"id": "narrow", "kind": "narrow", "campaign": c, "notes": notes,
                        "max_coded": 1.0, "active_points": len(pts), "pins": pins})

    # widen the boundary edges
    axes = list((ep["report"].get("boundary_optimum") or {}).get("axes") or [])
    sp = ep["fit_rec"].get("stationary_point") or {}
    axes += [a for a, v in sp.items() if isinstance(v, (int, float)) and abs(v) > 1.0
             and a not in axes and a in by_id and is_refinable(by_id[a])]
    if axes and len(ep["objectives"]) == 1:
        from orchestrator.optimize.factors import _from_axis

        c, notes, pins = fresh(), [], {}
        rec_lv = (ep["report"].get("recommendation") or {}).get("levels") or {}
        for fid in axes:
            f = by_id.get(fid)
            if f is None or f.type != "numeric":
                continue
            a, b = sorted((_to_axis(f, f.screen_levels[0]), _to_axis(f, f.screen_levels[1])))
            half = (b - a) / 2.0
            up = (sp.get(fid, 0.0) > 0) if fid in sp else (
                rec_lv.get(fid) is not None and _to_axis(f, rec_lv[fid]) >= b - 1e-12)
            na, nb = ((b - half, b + half) if up else (a - half, a + half))
            lo, hi = _from_axis(f, na), _from_axis(f, nb)
            if f.scale != "log" and not up and lo <= 0 < min(map(float, f.levels)):
                lo = (f.grid or min(map(float, f.levels)) / 2.0)
            lv = _axis_levels(f, lo, hi, max(3, min(len(f.levels), 5)))
            why = _set_levels(c, fid, lv, levels_only=False if f.levels_only else None)
            notes.append(f"{fid} range {list(f.screen_levels)} -> [{lv[0]}, {lv[-1]}], "
                         f"re-centred on the {'upper' if up else 'lower'} edge (assumes the "
                         f"edge is not a hard system limit)" + (f"; {why}" if why else ""))
        for fid, (v, _w) in sorted(dead.items()):
            if _pin(c, pins, fid, v) is None:
                notes.append(f"pin dead {fid}={v!r}")
        notes += _repair(c)
        out.append({"id": "widen_edge", "kind": "widen_edge", "campaign": c, "notes": notes,
                    "max_coded": WIDEN_MAX_CODED, "axes": axes, "pins": pins})

    # raise resolution once fewer knobs remain
    if dead:
        pd = next(m for m in out if m["id"] == "pin_dead")
        c, pins = copy.deepcopy(pd["campaign"]), dict(pd["pins"])
        d = c["optimization"].setdefault("design", {})
        scr = d.setdefault("screen", {})
        notes = []
        if int(scr.get("resolution", 5)) < 5:
            scr["resolution"] = 5
            notes.append("screen resolution -> V (every 2fi estimable)")
        from orchestrator.optimize.factors import parse_factors

        if "refine" not in d and sum(1 for f in parse_factors(c["optimization"]["factors"])
                                     if is_refinable(f)) >= 2:
            d["refine"] = {"kind": "central_composite", "center_points": 4}
            if c["optimization"].get("stages") and "refine" not in c["optimization"]["stages"]:
                st = c["optimization"]["stages"]
                st.insert(st.index("confirm") if "confirm" in st else len(st), "refine")
            notes.append("refine (second-order) added")
        if notes:
            out.append({"id": "raise_resolution", "kind": "raise_resolution", "campaign": c,
                        "notes": ["pin dead knobs (as pin_dead)"] + notes, "max_coded": 1.0,
                        "pins": pins})

    # recombination block (D1): the front's disagreeing values, the rest pinned
    out += _recombination_move(ep, fresh)
    return out


def _front_points(ep: dict) -> tuple[list[dict], dict]:
    rep = ep["report"]
    par = rep.get("pareto")
    if isinstance(par, dict):
        pts = [dict(f["levels"]) for f in par.get("front") or [] if not f.get("dominated_by")]
        pref = dict((par.get("preference") or {}).get("chosen") or (pts[0] if pts else {}))
    else:
        pts = [dict(f["levels"]) for f in rep.get("finalists") or [] if f.get("status") == "ok"]
        pref = dict((rep.get("recommendation") or {}).get("levels") or {})
    return pts, pref


def _recombination_move(ep: dict, fresh) -> list[dict]:
    from orchestrator.optimize.allocate import disagreeing_knobs

    pts, pref = _front_points(ep)
    if len(pts) < 2 or not pref:
        return []
    d = disagreeing_knobs(pts)
    if not d:
        return []
    by_id = {f.id: f for f in ep["factors"]}
    c, notes, pins = fresh(), [], {}
    for fid in [f["id"] for f in ep["campaign"]["optimization"]["factors"]]:
        f = by_id[fid]
        if fid in d:
            vals = sorted(d[fid], key=lambda v: (str(type(v)), v)) if f.type != "choice" \
                else [lv for lv in f.levels if lv in d[fid]]
            lo_only = f.type == "numeric" and len(vals) > 2
            why = _set_levels(c, fid, vals, levels_only=lo_only or None)
            notes.append(f"{fid} levels -> {vals} (values the front disagrees on)"
                         + (f"; {why}" if why else ""))
        elif fid in pref:
            r = _pin(c, pins, fid, pref[fid])
            notes.append(f"pin {fid}={pref[fid]!r} (every front point agrees)" if r is None
                         else f"cannot pin {fid}: {r}")
    notes += _repair(c)
    return [{"id": "recombination", "kind": "recombination", "campaign": c, "notes": notes,
             "max_coded": 1.0, "front_points": len(pts), "pins": pins}]


def _bo_move(ep: dict, fresh) -> tuple[list[dict], dict | None]:
    from orchestrator.optimize import bo_proposer

    cfg = bo_proposer.bo_config(ep["policy"])
    if cfg is None:
        return [], None
    try:
        props, prov = bo_proposer.propose(ep["rows"], factors=ep["factors"],
                                          objectives=ep["objectives"], config=cfg,
                                          n=BO_PROPOSALS)
    except bo_proposer.BOUnavailable as exc:
        return [], {"unavailable": str(exc)}
    if not props:
        return [], {**prov, "unavailable": "no new proposal"}
    from orchestrator.optimize.factors import _to_axis

    c, notes, pins = fresh(), [], {}
    for f in ep["factors"]:
        vals = [p["levels"][f.id] for p in props if f.id in p["levels"]]
        if not vals:
            continue
        if f.type == "choice":
            keep = [lv for lv in f.levels if lv in vals]
            if len(keep) == 1:
                if _pin(c, pins, f.id, keep[0]) is None:
                    notes.append(f"pin {f.id}={keep[0]!r} (every proposal)")
            elif len(keep) < len(f.levels):
                _set_levels(c, f.id, keep)
                notes.append(f"{f.id} levels -> {keep}")
            continue
        lo = min(vals, key=lambda v: _to_axis(f, v))
        hi = max(vals, key=lambda v: _to_axis(f, v))
        if lo == hi:
            if _pin(c, pins, f.id, lo) is None:
                notes.append(f"pin {f.id}={lo!r} (every proposal)")
            continue
        lv = ([x for x in f.levels if float(lo) <= float(x) <= float(hi)] if f.levels_only
              else _axis_levels(f, float(lo), float(hi), max(3, min(len(f.levels), 5))))
        why = _set_levels(c, f.id, lv)
        notes.append(f"{f.id} range -> [{lv[0]}, {lv[-1]}] (bounding box of the TPE "
                     f"proposals)" + (f"; {why}" if why else ""))
    notes += _repair(c)
    return [{"id": "bo_block", "kind": "bo_block", "campaign": c, "notes": notes,
             "max_coded": 1.0, "proposals": props, "model_free": True, "pins": pins}], prov


# ── scoring and budgets ──────────────────────────────────────────────────────


def _frame(ep: dict):
    from orchestrator.optimize import pareto
    from orchestrator.optimize.allocate import coded_of
    from orchestrator.optimize.constraint_models import predicted_with_se

    objs = [pareto.Objective(o["metric"], o["direction"], {}) for o in ep["objectives"]]
    rows = [dict(m["mean"]) for m in ep["measured"]]
    for m in ep["measured"]:
        try:
            c = coded_of(m["levels"], fitted_ids=ep["fitted_ids"], factors=ep["factors"],
                         held_fixed=ep["held_fixed"])
        except (ValueError, KeyError):
            continue
        rows.append({o.metric: predicted_with_se(ep["fits"][o.metric], c)[0] for o in objs})
    eps = dict(((ep["report"].get("pareto") or {}).get("epsilon")) or {})
    return pareto.make_frame(objs, rows, eps), eps


def _region_bound(ep: dict, cands, frame, *, keep_all: bool = False) -> dict:
    """The MARGINAL score of each candidate (EI over the plug-in incumbent, or
    marginal EHVI), used ONLY to preselect candidates for the joint bound
    (``_value``). It is not itself a bound on a move's increment."""
    from orchestrator.optimize import allocate
    from orchestrator.optimize.constraint_models import predicted_with_se

    objs = ep["objectives"]
    if not cands:
        return {"value": None, "reason": "empty_region"}
    if len(objs) == 1:
        o = objs[0]
        fit = ep["fits"][o["metric"]]
        sg = -1.0 if o["direction"] == "minimize" else 1.0
        nu = float(fit.pure_error_df)
        mc = _measured_coded(ep)
        if not mc:
            return {"value": None, "reason": "no_measured_incumbent"}
        tau = max(sg * predicted_with_se(fit, c)[0] for c in mc)
        per = []
        for _lv, c in cands:
            y, s = predicted_with_se(fit, c)
            per.append(allocate.expected_improvement(sg * y, s, tau, nu))
        return {"value": max(per), "per": per}
    al = allocate.score([{"levels": lv, "source": "region", "_i": i}
                         for i, (lv, _c) in enumerate(cands)],
                        fits=ep["fits"], objectives=objs, factors=ep["factors"],
                        fitted_ids=ep["fitted_ids"], held_fixed=ep["held_fixed"],
                        measured=ep["measured"], model_adequate=ep["model_adequate"],
                        replicates=1,
                        max_coded=max(1.0, max(max((abs(x) for x in c.values()), default=0)
                                               for _l, c in cands)),
                        frame=frame)
    if al.declined:
        return {"value": None, "reason": al.declined}
    by = {allocate._key(r["levels"]): r["ehvi"] for r in al.ranked}
    per = [by.get(allocate._key(lv), 0.0) for lv, _c in cands]
    return {"value": max(per), "per": per}


def _measured_coded(ep: dict) -> list[dict]:
    from orchestrator.optimize.allocate import coded_of

    out = []
    for m in ep["measured"]:
        try:
            out.append(coded_of(m["levels"], fitted_ids=ep["fitted_ids"], factors=ep["factors"],
                                held_fixed=ep["held_fixed"]))
        except (ValueError, KeyError):
            continue
    return out


def _value(ep: dict, cands, frame) -> dict:
    """The move's value: a TRUE lower bound on the expected increment of
    adding its region to the measured set (WP-D review H1).

    ``max_{x in S} E[(f(x) - max_{m in M} f(m))^+]`` (one objective) or
    ``max_{x in S} E[HVI(f(x) | front(f(M)))]`` (several), under the JOINT
    posterior of the fitted model (``allocate.joint_increment_bound``). Here
    ``S`` is a subset of the region preselected by the marginal score
    (``_region_bound``): the top ``allocate.JOINT_PRESELECT`` candidates
    (``JOINT_PRESELECT_MO`` for several objectives). A max over a subset is
    still a lower bound, only looser."""
    from orchestrator.optimize import allocate

    marg = _region_bound(ep, cands, frame, keep_all=True)
    if marg.get("value") is None:
        return marg
    mo = len(ep["objectives"]) > 1
    k = allocate.JOINT_PRESELECT_MO if mo else allocate.JOINT_PRESELECT
    order = sorted(range(len(cands)), key=lambda i: (-marg["per"][i], i))[:k]
    sub = [cands[i] for i in order]
    jb = allocate.joint_increment_bound(
        fits=ep["fits"], objectives=ep["objectives"], measured_coded=_measured_coded(ep),
        cand_coded=[c for _l, c in sub], frame=frame,
        samples=allocate.JOINT_SAMPLES_MO if mo else allocate.JOINT_SAMPLES)
    if jb.get("value") is None:
        return {"value": None, "reason": jb["declined"]}
    lv = sub[jb["index"]][0]
    return {"value": jb["value"], "argmax": lv, "method": jb["method"],
            "samples": jb["samples"], "seed": jb["seed"],
            "preselected": len(sub), "region_size": len(cands),
            "marginal_bound_not_used": marg["value"]}


def _cost(campaign: dict) -> tuple[int | None, str | None]:
    from orchestrator.optimize.preview import build_preview

    try:
        pv = build_preview(campaign, noise_sd=None, mean=None, run_secs=None)
    except Exception as exc:  # noqa: BLE001 -- recorded as the move's reason
        return None, f"preview_failed: {type(exc).__name__}: {exc}"
    cap = ((campaign.get("optimization") or {}).get("design") or {}).get("max_runs")
    runs = min(pv.max_runs, int(cap)) if cap else pv.max_runs
    return int(runs), None


def budget_state(ep: dict) -> dict:
    """The cross-epoch error budget (``provenance.error_budget``, P2) and run
    budget as they stand after this epoch."""
    from orchestrator.optimize.provenance import error_budget

    eb = error_budget(ep["work_dir"], ep["policy"])
    out = {"cumulative": eb.get("cumulative"),
           "cumulative_is_lower_bound": eb.get("cumulative_is_lower_bound"),
           "mode": eb.get("mode", "informational"),
           "epochs": eb.get("epochs")}
    if eb.get("mode") == "charged":
        out.update({"campaign_total": eb["campaign_total"],
                    "declared_totals": eb.get("declared_totals"),
                    "within_total": eb.get("within_total"),
                    "remaining": eb["campaign_total"] - float(eb["cumulative"])})
    pl = (ep["policy"].get("planner") or {})
    total_runs = sum(1 for _ in _rows(ep["work_dir"], _all_iters(ep["work_dir"])))
    out["runs_spent_campaign"] = total_runs
    if pl.get("campaign_max_runs"):
        out["campaign_max_runs"] = int(pl["campaign_max_runs"])
        out["runs_remaining"] = int(pl["campaign_max_runs"]) - total_runs
    return out


def _all_iters(work_dir: Path) -> list[int]:
    d = Path(work_dir) / "runs"
    return sorted(int(p.name.split("-")[1]) for p in d.glob("iter-*")
                  if p.name.split("-")[1].isdigit()) if d.exists() else []


def _next_epoch_budget(campaign: dict, ep: dict, bstate: dict) -> dict:
    """The next epoch's charge, and whether the remaining budget covers it.
    A next epoch never runs past the charged total: such a move is
    infeasible (``error_budget_insufficient``) and cannot be overridden."""
    from orchestrator.optimize.policy import compile_policy, delta_stated

    pol = compile_policy(campaign, epoch=ep["epoch"] + 1)
    d = delta_stated(pol)
    cd = pol["objective"].get("campaign_delta")
    out = {"next_epoch": ep["epoch"] + 1, "next_epoch_delta": d,
           "cumulative_after": (bstate["cumulative"] or 0.0) + d}
    if bstate["mode"] == "charged" or cd:
        totals = [bstate.get("campaign_total")] + ([float(cd["total"])] if cd else [])
        binding = min(t for t in totals if t is not None)
        remaining = binding - float(bstate["cumulative"] or 0.0)
        out.update({"binding_total": binding, "remaining_before": remaining,
                    "share_exhausted": bool((cd or {}).get("exhausted")),
                    "fits": (d <= remaining + 1e-12) and not (cd or {}).get("exhausted")})
        if bstate.get("cumulative_is_lower_bound"):
            # An earlier epoch's deltas could not be recovered, so the spend is
            # a lower bound and `remaining` an upper one: never plan into it.
            out["fits"] = False
            out["note"] = ("the cumulative spend is a lower bound (an earlier epoch's "
                           "deltas are unrecovered), so the remaining charged budget "
                           "cannot be shown to cover the next epoch")
        if not cd:
            out["note"] = ("the next campaign does not declare campaign_delta, but the "
                           "charged mode stays binding once declared (P2): the next epoch "
                           "would certify nothing")
            out["fits"] = False
    else:
        out["fits"] = True
        out["note"] = ("informational (no campaign_delta declared): cumulative_after is the "
                       "union bound over epochs, not a binding cap")
    return out


def _threshold(ep: dict, frame, eps_mo: dict) -> tuple[float | None, str]:
    pl = ep["policy"].get("planner") or {}
    if pl.get("stop_value_per_run") is not None:
        return float(pl["stop_value_per_run"]), "declared: optimization.planner.stop_value_per_run"
    n = max(int(ep["runs_spent"]), 1)
    if len(ep["objectives"]) == 1:
        eps = ep["report"].get("epsilon")
        if eps is None:
            return None, "undefined: epsilon unknown and no stop_value_per_run declared"
        return float(eps) / n, (f"default: epsilon ({float(eps):.6g}) per run of this epoch "
                                f"({n} runs) -- a whole epoch must be expected to buy one epsilon")
    ez = frame.eps_z(eps_mo)
    if any(x is None for x in ez):
        return None, "undefined: an objective's epsilon is unknown"
    box = math.prod(float(x) for x in ez)
    return box / n, (f"default: one epsilon-box of normalised hypervolume ({box:.3g}) per "
                     f"run of this epoch ({n} runs)")


# ── the plan ─────────────────────────────────────────────────────────────────


def plan(work_dir: Path) -> dict:
    """Build the decision (no file written). Raises ``PlanError``."""
    from orchestrator.optimize import allocate

    ep = load_epoch(work_dir)
    gate = allocate._check_models(ep["fits"], ep["model_adequate"])
    scorable = gate is None
    frame, eps_mo = _frame(ep) if scorable else (None, {})
    thr, thr_rule = _threshold(ep, frame, eps_mo) if scorable else (None, "not needed")
    bstate = budget_state(ep)
    moves = _moves(ep)
    bo_moves, bo_prov = _bo_move(ep, lambda: copy.deepcopy(ep["campaign"]))
    moves += bo_moves
    if not scorable:
        moves.append({"id": "replicate", "kind": "replicate",
                      "campaign": copy.deepcopy(ep["campaign"]),
                      "notes": ["re-run the same registered region as a fresh epoch "
                                "(model-free alternative)"], "max_coded": 1.0,
                      "model_free": True})
    seen, options = {}, []
    base_hash = campaign_hash(ep["campaign"])

    cap = REGION_CAP_SO if len(ep["objectives"]) == 1 else REGION_CAP_MO
    for mv in moves:
        c = mv["campaign"]
        opt = {"id": mv["id"], "kind": mv["kind"], "changes": mv["notes"], "score": None}
        if mv.get("failed"):
            opt.update(feasible=False, reason=mv["failed"])
            options.append(opt)
            continue
        h = campaign_hash(c)
        opt["campaign_hash"] = h
        if h == base_hash and mv["kind"] != "replicate":
            opt.update(feasible=False, reason="no_change: identical to the current campaign")
            options.append(opt)
            continue
        if h in seen:
            opt.update(feasible=False, reason=f"duplicate_of:{seen[h]}")
            options.append(opt)
            continue
        seen[h] = mv["id"]
        errs = validate_campaign(c)
        if errs:
            opt.update(feasible=False, reason="proposal_invalid", errors=errs[:12])
            options.append(opt)
            continue
        cost, why = _cost(c)
        opt["cost_runs"] = cost
        if cost is None:
            opt.update(feasible=False, reason=why)
            options.append(opt)
            continue
        opt["error_budget"] = _next_epoch_budget(c, ep, bstate)
        if not opt["error_budget"]["fits"]:
            opt.update(feasible=False, reason="error_budget_insufficient")
        elif bstate.get("runs_remaining") is not None and cost > bstate["runs_remaining"]:
            opt.update(feasible=False, reason="run_budget_insufficient")
        else:
            opt["feasible"] = True
        if mv.get("proposals"):
            opt["proposals"] = [{"levels": p["levels"]} for p in mv["proposals"]]
            opt["proposal_provenance"] = mv["proposals"][0]["provenance"]
        if scorable:
            cands, grid_rec = _grid(c, ep, cap=cap, max_coded=mv["max_coded"],
                                    pins=mv.get("pins"))
            opt["region"] = grid_rec
            opt["extrapolated"] = mv["max_coded"] > 1.0
            v = _value(ep, cands, frame)
            opt["utility"] = v
            opt["score"] = (v["value"] / cost) if v.get("value") is not None and cost else None
            if mv["kind"] == "recombination":
                pts, pref = _front_points(ep)
                al = allocate.allocate(front_points=pts, preferred=pref, fits=ep["fits"],
                                       objectives=ep["objectives"], factors=ep["factors"],
                                       fitted_ids=ep["fitted_ids"],
                                       held_fixed=ep["held_fixed"], measured=ep["measured"],
                                       model_adequate=ep["model_adequate"],
                                       proposals=[p for m in bo_moves for p in m["proposals"]])
                opt["allocation"] = {"declined": al.declined, "method": al.method,
                                     "ranked": al.ranked[:8]}
        else:
            opt["score"] = None
            opt["unscored"] = gate.declined
        opt["_campaign"] = c
        options.append(opt)
    options.append({"id": "stop", "kind": "stop", "feasible": True, "score": 0.0,
                    "changes": ["no next epoch: keep this epoch's report"], "cost_runs": 0})

    live = [o for o in options if o.get("feasible") and o["id"] != "stop"
            and o.get("score") is not None]
    if not scorable:
        chosen, basis = "stop", "no_scorable_move"
    elif thr is None:
        chosen, basis = "stop", "threshold_undefined"
    elif not [o for o in options if o.get("feasible") and o["id"] != "stop"]:
        chosen, basis = "stop", "no_feasible_move"
    else:
        best = max(live, key=lambda o: (o["score"], o["id"])) if live else None
        if best is not None and best["score"] > thr:
            chosen, basis = best["id"], "max_value_per_run_above_threshold"
        else:
            chosen, basis = "stop", "no_move_beats_threshold"
    pts, pref = _front_points(ep)
    decision = {
        "planner_version": 1,
        "work_dir": str(ep["work_dir"]),
        "epoch": ep["epoch"],
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tokens": 0,
        "inputs": _input_hashes(ep),
        "model": {"fitting_iteration": ep["fit_iter"], "stage": ep["fit_rec"].get("stage"),
                  "model_adequate": ep["model_adequate"], "fitted_ids": ep["fitted_ids"],
                  "held_fixed": ep["held_fixed"], "predictive": ep["predictive"],
                  **({"declined": gate.declined, "detail": gate.detail} if gate else {})},
        "utility": _utility_statement(ep),
        "stopping": {"threshold_per_run": thr, "rule": thr_rule},
        "assumptions": _assumptions(ep),
        "error_budget": bstate,
        **({"bo": bo_prov} if bo_prov is not None else {}),
        "options": [{k: v for k, v in o.items() if not k.startswith("_")} for o in options],
        "chosen": chosen,
        "decision_basis": basis,
        "scored_choice": chosen,
        "override": None,
        "model_free_alternatives": [o["id"] for o in options if o["id"] in ("bo_block", "replicate")
                                    and o.get("feasible")] if not scorable else [],
        "front_points": len(pts),
    }
    return {"decision": decision, "campaigns": {o["id"]: o["_campaign"] for o in options
                                                if "_campaign" in o},
            "epoch": ep}


def _utility_statement(ep: dict) -> dict:
    if len(ep["objectives"]) == 1:
        o = ep["objectives"][0]
        return {"name": "expected_improvement_per_run",
                "definition": (f"E[max(max_M f, max_R f) - max_M f] / runs, where f is "
                               f"{o['metric']}'s true mean ({o['direction']}) under the "
                               f"fitted model's joint posterior, M this epoch's measured "
                               f"configurations, R the move's region, and runs the next "
                               f"epoch's worst-case run count"),
                "computed_as": "max_{x in S} E[(f(x) - max_{m measured} f(m))^+] / runs "
                               "under the model's joint posterior (S = the top "
                               "JOINT_PRESELECT region points by marginal EI): a TRUE lower "
                               "bound on the expected increment of adding the region to the "
                               "measured set; seeded Monte Carlo (samples and seed on each "
                               "option)",
                "units": f"{o['metric']} per benchmark run"}
    return {"name": "expected_hypervolume_improvement_per_run",
            "definition": ("E[HV(front(f(M ∪ R))) - HV(front(f(M)))] / runs in the "
                           "normalised frame (pareto.make_frame), f the true means under the "
                           "fitted models' joint posteriors"),
            "computed_as": "max_{x in S} E[HV(front(f(M)) + f(x)) - HV(front(f(M)))] / "
                           "runs over the RANDOM measured front under the joint "
                           "posteriors (S = the top JOINT_PRESELECT_MO points by marginal "
                           "EHVI): a TRUE lower bound on the expected hypervolume "
                           "increment; seeded Monte Carlo, each draw's hypervolume exact",
            "units": "normalised hypervolume per benchmark run"}


def _assumptions(ep: dict) -> list[str]:
    diag = sorted(m for m, h in (ep.get("predictive") or {}).items() if h != "exact"
                  and not str(h).startswith("exact"))
    return ([f"objective(s) {diag}: predictive se from the per-term diagonal (the fit's "
             f"exact covariance was not recorded); understates se for non-orthogonal "
             f"columns"] if diag else []) + [
        "the belief about every objective is the current epoch's fitted model's JOINT "
        "coefficient posterior, a multivariate t on the pure-error df (flat-prior posterior "
        "of the linear model; requires model_adequate is True, else nothing is scored)",
        "the next epoch's design finds the best configuration of its region (optimistic: "
        "the score is the value of reaching it, not the probability of doing so)",
        "a widened axis is scored past its fitted edge out to |coded| <= "
        f"{WIDEN_MAX_CODED:g} (extrapolated: true on that option)",
        "objectives independent (multi-objective EHVI)",
        "a 'dead' knob (pin_dead) is one the screen found no main effect for at alpha=0.05 "
        "on every objective, or one the certificate's TOST showed inert: non-significance "
        "is effect sparsity (Box & Meyer 1986), not proof of inertness; the next epoch's "
        "certificate is scoped to the pinned value",
        "a widened edge is assumed not to be a hard limit of the system",
        "moves are compared by single-point lower bounds of different tightness: a "
        "larger region's batch value is understated relative to its cost, so the ranking "
        "leans toward small, cheap moves (q-EI / q-EHVI would remove the lean; not "
        "computed)",
        "the region is represented by its top candidates by marginal score; a max over a "
        "subset is a looser, still valid, lower bound",
        "cost is the next epoch's worst-case run count from the design preview "
        "(every registered branch taken, every confirm round)",
        "the planner chooses only WHERE the next epoch looks; the next epoch is compiled, "
        "pre-registered and certified on its own fresh measurements at its own charged "
        "error budget",
    ]


def _input_hashes(ep: dict) -> dict:
    """sha256 of EVERY file the decision read (review M1): the analysis inputs
    ``provenance.input_hashes`` covers (every iteration's runs, design matrix
    and relations, every ``campaign.epoch-*.yaml``, accepted boundaries),
    plus every fitting stage's effects and recommendation, the report, the
    policy, ``transitions.jsonl`` and ``delta_ledger.jsonl``; and the Nous
    source the decision was computed by (``nous:source_sha256``)."""
    from orchestrator.optimize.provenance import input_hashes, nous_version_info, sha256_file

    wd = ep["work_dir"]
    out = dict(input_hashes(wd))
    names = ["report.json", "policy.json", "policy.sha256", "transitions.jsonl",
             "delta_ledger.jsonl"]
    for d in sorted((wd / "runs").glob("iter-*")):
        for n in ("effects.json", "recommendation.json", "confirmation.json"):
            names.append(f"runs/{d.name}/{n}")
    out.update({n: sha256_file(wd / n) for n in names if (wd / n).exists()})
    out.update({n: "absent" for n in names[:5] if not (wd / n).exists()})
    out["nous:source_sha256"] = str(nous_version_info().get("source_sha256") or "")
    return out


def _current_inputs(wd: Path, recorded: dict) -> list[str]:
    """Names in ``recorded`` whose content changed, or new input files."""
    from orchestrator.optimize.provenance import input_hashes, nous_version_info, sha256_file

    stale = []
    for n, h in recorded.items():
        if n == "nous:source_sha256":
            if str(nous_version_info().get("source_sha256") or "") != h:
                stale.append(n)
        elif h == "absent":
            if (wd / n).exists():
                stale.append(n)
        elif not (wd / n).exists() or sha256_file(wd / n) != h:
            stale.append(n)
    stale += [n for n in input_hashes(wd) if n not in recorded]
    return stale


# ── the decision seal (review M2) ────────────────────────────────────────────

SEAL_SUFFIX = ".seal"


def _seal_key(wd: Path) -> bytes:
    """The work_dir's key under the Nous state home (``gate_records.key_path``),
    never in the work_dir. Created only if no build seal exists yet, as
    ``gate_records.ensure_key`` does, so a missing key can never be re-minted
    to forge a seal over an edited decision."""
    from orchestrator.optimize import gate_records as gr

    return gr._key(wd, create=not (wd / gr.SEAL_FILE).exists()
                   and not any((wd / PLAN_DIR).glob("epoch-*/*" + SEAL_SUFFIX)))


def _mac(key: bytes, data: bytes) -> str:
    import hmac

    return hmac.new(key, b"planner_decision\0" + data, hashlib.sha256).hexdigest()


def _seal_decision(wd: Path, path: Path) -> None:
    (path.parent / (path.name + SEAL_SUFFIX)).write_text(
        _mac(_seal_key(wd), path.read_bytes()) + "\n")


def _check_seal(wd: Path, path: Path) -> None:
    import hmac

    from orchestrator.optimize import gate_records as gr

    sp = path.parent / (path.name + SEAL_SUFFIX)
    if not sp.exists():
        raise PlanError(f"decision_unsealed: {sp.name} is absent; re-run `nous plan-next`")
    try:
        key = gr._key(wd)
    except gr.GateRecordError as exc:
        raise PlanError(f"decision_unsealed: {exc}") from exc
    if not hmac.compare_digest(sp.read_text().strip(), _mac(key, path.read_bytes())):
        raise PlanError("decision_tampered: planner_decision.json does not match its seal "
                        "(edited after `nous plan-next` wrote it)")


# ── writing, choosing, accepting ─────────────────────────────────────────────


def _dump(c: dict) -> str:
    return yaml.safe_dump(c, default_flow_style=False, sort_keys=False)


def write_plan(result: dict, *, choose: str | None = None, reason: str | None = None) -> Path:
    """Write ``plan_next/epoch-<e>/``: planner_decision.json, every option's
    proposed campaign, and the chosen one's diff. Returns the decision path."""
    import jsonschema

    d = result["decision"]
    ep = result["epoch"]
    out = Path(ep["work_dir"]) / PLAN_DIR / f"epoch-{d['epoch']}"
    (out / "options").mkdir(parents=True, exist_ok=True)
    if choose is not None:
        apply_override(d, choose, reason)
    for oid, c in result["campaigns"].items():
        (out / "options" / f"{oid}.campaign.yaml").write_text(_dump(c))
    cur = _dump(ep["campaign"])
    if d["chosen"] != "stop":
        new = _dump(result["campaigns"][d["chosen"]])
        (out / "proposed_campaign.yaml").write_text(new)
        diff = "".join(difflib.unified_diff(
            cur.splitlines(True), new.splitlines(True),
            fromfile=f"campaign.epoch-{d['epoch']}.yaml",
            tofile=f"campaign.epoch-{d['epoch'] + 1}.yaml (proposed: {d['chosen']})"))
        (out / "proposed_campaign.diff").write_text(diff)
        d["proposed_campaign"] = {"path": str(out / "proposed_campaign.yaml"),
                                  "diff": str(out / "proposed_campaign.diff"),
                                  "campaign_hash": campaign_hash(result["campaigns"][d["chosen"]])}
    else:
        for n in ("proposed_campaign.yaml", "proposed_campaign.diff"):
            (out / n).unlink(missing_ok=True)
        d["proposed_campaign"] = None
    jsonschema.validate(d, json.loads(SCHEMA_PATH.read_text()))
    p = out / DECISION_FILE
    p.write_text(json.dumps(d, indent=2, sort_keys=True, default=str) + "\n")
    _seal_decision(Path(ep["work_dir"]), p)
    return p


NOT_OVERRIDABLE = ("error_budget_insufficient", "run_budget_insufficient", "proposal_invalid",
                   "preview_failed", "duplicate_of", "no_change", "region_failed")


def _overridable(opt: dict) -> bool:
    return not str(opt.get("reason") or "").startswith(NOT_OVERRIDABLE)


def apply_override(d: dict, choose: str, reason: str | None) -> None:
    """Record ``--choose``: the scored choice stays, the override names who
    chose what and why. Infeasible-by-budget options are refused."""
    if not reason or not reason.strip():
        raise PlanError("override_needs_reason: --choose requires --reason \"<text>\"")
    opt = next((o for o in d["options"] if o["id"] == choose), None)
    if opt is None:
        raise PlanError(f"unknown_option: {choose!r} (options: "
                        f"{[o['id'] for o in d['options']]})")
    if not _overridable(opt):
        raise PlanError(f"option_not_overridable: {choose} is {opt.get('reason')}; the "
                        f"remaining budget or the validator forbids it")
    d["override"] = {"chosen": choose, "reason": reason.strip(),
                     "scored_choice": d["scored_choice"],
                     "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    d["chosen"] = choose


def _recheck_choice(d: dict) -> None:
    """Accept re-applies the choice rules to the decision it is about to act
    on (review M2): ``chosen`` is the scored choice, or an override with a
    reason of an option that may be overridden."""
    opt = next((o for o in d.get("options") or [] if o.get("id") == d.get("chosen")), None)
    if opt is None:
        raise PlanError(f"decision_invalid: chosen {d.get('chosen')!r} is not an option")
    if d["chosen"] != d.get("scored_choice"):
        ov = d.get("override") or {}
        if ov.get("chosen") != d["chosen"] or not str(ov.get("reason") or "").strip():
            raise PlanError("decision_invalid: chosen differs from the scored choice "
                            "without a recorded override and reason")
        if not _overridable(opt):
            raise PlanError(f"option_not_overridable: {d['chosen']} is {opt.get('reason')}")
    elif d["chosen"] != "stop" and not opt.get("feasible"):
        raise PlanError(f"decision_invalid: {d['chosen']} is not feasible ({opt.get('reason')})")


def accept(work_dir: Path, campaign_path: Path, *, force_overwrite: bool = False) -> dict:
    """Apply the written decision: write the proposed campaign over
    ``campaign_path`` and the planned epoch-boundary record, which makes the
    next ``nous resume`` compile epoch ``e + 1``. A ``stop`` decision writes
    ``accepted_stop.json`` only (no new epoch). Every refusal is named:

    * ``decision_unsealed`` / ``decision_tampered``: the decision's HMAC seal
      (key under the Nous state home) is missing or does not match (M2);
    * ``decision_invalid`` / ``option_not_overridable``: the choice rules,
      re-applied here (M2);
    * ``stale_decision``: any input the planner read changed (M1);
    * ``error_budget_insufficient`` / ``run_budget_insufficient``: the next
      epoch no longer fits, re-checked against the budgets as they stand (M1);
    * ``campaign_edited_since_plan``: ``campaign_path`` is not the campaign
      this epoch registered (H2). ``force_overwrite`` overrides that one
      check only.

    The replaced file is saved first as ``<name>.bak-epoch-<e>`` (H2)."""
    import shutil

    from orchestrator.optimize.policy import read_policy
    from orchestrator.optimize.provenance import sha256_file

    wd = Path(work_dir)
    pol = read_policy(wd)
    if pol is None:
        raise PlanError("no_policy")
    e = int(pol.get("epoch", 1))
    dp = wd / PLAN_DIR / f"epoch-{e}" / DECISION_FILE
    if not dp.exists():
        raise PlanError(f"no_decision: run `nous plan-next` first ({dp} is absent)")
    if boundary_path(wd, e).exists():
        raise PlanError(f"already_planned: {boundary_path(wd, e).name} exists")
    _check_seal(wd, dp)
    d = json.loads(dp.read_text())
    _recheck_choice(d)
    stale = _current_inputs(wd, d.get("inputs") or {})
    if stale:
        raise PlanError(f"stale_decision: inputs changed since planning: {stale[:8]}")
    rec = {"epoch": e, "kind": "planned_continuation" if d["chosen"] != "stop" else "stop",
           "decision": str(dp.relative_to(wd)), "decision_sha256": sha256_file(dp),
           "chosen": d["chosen"], "scored_choice": d["scored_choice"],
           "decision_basis": d["decision_basis"], "override": d.get("override"),
           "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if d["chosen"] == "stop":
        (wd / PLAN_DIR / f"epoch-{e}" / "accepted_stop.json").write_text(
            json.dumps(rec, indent=2, sort_keys=True) + "\n")
        return rec
    prop = Path(d["proposed_campaign"]["path"])
    text = prop.read_text()
    c = yaml.safe_load(text)
    if campaign_hash(c) != d["proposed_campaign"]["campaign_hash"]:
        raise PlanError("stale_decision: the proposed campaign file was edited after planning")
    errs = validate_campaign(c)
    if errs:
        raise PlanError(f"proposal_invalid: {errs[:3]}")
    # The budgets as they stand NOW, not as the decision recorded them.
    ep = load_epoch(wd)
    bstate = budget_state(ep)
    nb = _next_epoch_budget(c, ep, bstate)
    if not nb["fits"]:
        raise PlanError(f"error_budget_insufficient: {nb}")
    cost, why = _cost(c)
    if cost is None:
        raise PlanError(f"proposal_invalid: {why}")
    if bstate.get("runs_remaining") is not None and cost > bstate["runs_remaining"]:
        raise PlanError(f"run_budget_insufficient: {cost} > {bstate['runs_remaining']}")
    rec["proposed_campaign_hash"] = d["proposed_campaign"]["campaign_hash"]
    cp = Path(campaign_path)
    registered = (wd / f"campaign.epoch-{e}.yaml").read_bytes()
    if cp.exists():
        same = cp.read_bytes() == registered or (
            campaign_hash(yaml.safe_load(cp.read_text()) or {})
            == campaign_hash(yaml.safe_load(registered) or {})
            and yaml.safe_load(cp.read_text()) == yaml.safe_load(registered))
        if not same and not force_overwrite:
            raise PlanError(f"campaign_edited_since_plan: {cp} is not the campaign epoch "
                            f"{e} registered (campaign.epoch-{e}.yaml); accepting would "
                            f"discard those edits. Re-plan from the edited campaign, or "
                            f"pass --force-overwrite (the file is backed up either way).")
        rec["replaced_campaign_sha256"] = sha256_file(cp)
        rec["replaced_matches_registered"] = bool(same)
        bak = cp.with_name(f"{cp.name}.bak-epoch-{e}")
        shutil.copy2(cp, bak)
        rec["backup"] = str(bak)
    cp.write_text(text)
    boundary_path(wd, e).write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec


def summary_lines(d: dict) -> list[str]:
    lines = [f"plan-next: epoch {d['epoch']} -> chosen: {d['chosen']} ({d['decision_basis']})",
             f"  utility: {d['utility']['name']} -- {d['utility']['computed_as']}",
             f"  stop threshold per run: {d['stopping']['threshold_per_run']} "
             f"({d['stopping']['rule']})"]
    eb = d["error_budget"]
    lines.append(f"  error budget: cumulative {eb['cumulative']} ({eb['mode']})"
                 + (f", remaining {eb['remaining']:.6g} of {eb['campaign_total']:.6g}"
                    if eb.get("remaining") is not None else ""))
    for o in d["options"]:
        sc = o.get("score")
        lines.append(f"  - {o['id']:<17} feasible={o.get('feasible')!s:<5} "
                     f"score/run={'n/a' if sc is None else format(sc, '.4g')} "
                     f"runs={o.get('cost_runs')}"
                     + (f"  [{o['reason']}]" if o.get("reason") else "")
                     + (f"  [unscored: {o['unscored']}]" if o.get("unscored") else ""))
    if d.get("override"):
        lines.append(f"  OVERRIDE: {d['override']['chosen']} (scored choice "
                     f"{d['override']['scored_choice']}): {d['override']['reason']}")
    return lines
