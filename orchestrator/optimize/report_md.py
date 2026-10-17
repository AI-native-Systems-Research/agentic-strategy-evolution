"""Zero-token human surfaces for ``kind: optimization``: report.md and gate summaries.

Why this module exists
----------------------
The reflective kind writes ``report.md`` and each continue gate's
``gate_summary_continue.json`` with an LLM call through ``LLMDispatcher`` (an
OpenAI-compatible client). For ``kind: optimization`` both were inherited
unchanged, which broke two of the kind's own guarantees:

* **Token budget.** The kind's model calls are ``plan`` and ``build``, and
  nothing else. A summarizer call per iteration plus a report call at the end
  is unbudgeted spend that does not appear in the cost model the guide
  documents.
* **Routing.** ``LLMDispatcher`` reads ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``,
  not the ``ANTHROPIC_*`` variables the SDK calls use. A campaign configured only
  for the SDK sent its gate summary to ``api.openai.com`` and got a 401
  (issue #304) -- a failure in a surface that contributes nothing to the answer.

Everything a reader needs is already in ``report.json`` and the progress
snapshot, and both are deterministic. So these surfaces are RENDERED from those
artifacts: they restate what the artifacts say, add no judgement, and cannot
disagree with them. ``report.json`` stays the record of the campaign's answer;
``report.md`` is a view of it.
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.optimize import progress as _progress

#: Plain-language reading of each rung of the fallback ladder
#: (``report.schema.json`` ``recommendation.basis``), strongest first.
BASIS_MEANING = {
    "certified": "terminal discrimination ran and the residual regret bound is "
                 "within epsilon -- this is a certificate",
    "terminal_best": "terminal discrimination ran but did not certify -- "
                     "the best measured finalist against measured rivals, "
                     "NOT a certificate",
    "model": "no terminal stage ran -- the fitted surface's argmax, standing "
             "on its model bound only",
    "measured": "the best measured valid configuration -- the fitted surface "
                "was not trusted",
    "baseline": "the author's declared known_valid_baseline -- nothing measured "
                "beat or replaced it",
    "none": "no legal configuration survived and no baseline was declared -- "
            "there is nothing to recommend",
}


#: Plain-language reading of each ``certification_withheld`` reason
#: (``report.schema.json``), so ``Certified: no`` is never unexplained.
WITHHELD_MEANING = {
    "bound_above_epsilon": "the terminal bound is wider than epsilon",
    "bound_not_computable": "the terminal bound could not be estimated "
                            "(unknown, not zero)",
    "finalist_measured_infeasible": "a finalist was measured inadmissible",
    "no_admissible_finalist": "every finalist was measured inadmissible (each "
                              "had a replicate violating a declared "
                              "constraint) -- no admissible configuration in "
                              "the shortlist to bound; the measurements "
                              "themselves are valid",
    "finalist_unmeasured": "a finalist produced no usable measurement, so the "
                           "shortlist was never fully compared -- re-run it",
    "fit_exclusions_level_correlated": "the fit behind the shortlist lost rows "
                                       "correlated with factor levels",
    "model_inadequate": "a fitting stage of this epoch rejected its model "
                        "(lack of fit, or the held-out validation runs "
                        "disagreed with its predictions), so nothing supports "
                        "the claim that screening did not exclude the optimum",
    "lack_of_fit_not_computable": "the fit behind the shortlist could not be "
                                  "tested for lack of fit (no pure error, or "
                                  "no residual df beyond it): its adequacy is "
                                  "unknown, not established",
    "curvature_untested": "some choice level was never measured at the centre, "
                          "so the curvature check never looked under it: model "
                          "adequacy is unknown there",
    "curvature_not_isolated": "a mixed-level fit could not estimate its "
                              "coefficients from the corners alone, so curvature "
                              "may have leaked into them: adequacy unknown",
    "screen_rejection_unresolved": "an earlier stage rejected the model and "
                                   "refine completed no validation check that "
                                   "could overturn it: adequacy is unknown",
    "model_adequacy_unknown": "the fit behind the shortlist has unknown "
                              "adequacy",
    "no_terminal_discrimination": "no terminal discrimination ran",
    "front_point_possibly_dominated": "the preferred point of the measured front "
                                      "is only POSSIBLY nondominated -- some rival "
                                      "could not be ruled out as better on every "
                                      "objective by epsilon",
    "no_front_point": "no measured admissible configuration formed a front",
    "no_feasible_rival": "only one finalist was admissible, so the terminal "
                         "bound compares it against nothing -- the vacated "
                         "seats need refilling",
    "epsilon_unknown": "an objective's epsilon has no reference (a percentage "
                       "of a zero best), so no difference on it can be judged "
                       "-- declare it as `abs`",
    "model_bound_above_epsilon": "the model bound over the candidates outside "
                                 "the shortlist, plus the terminal bound, "
                                 "exceeds epsilon: a configuration screening "
                                 "did not shortlist may still beat the winner "
                                 "by more than epsilon",
    "model_bound_not_computable": "no model bound exists for this epoch (no "
                                  "fitting stage, or no pure error), so nothing "
                                  "bounds what screening left out",
    "model_bound_not_exhaustive": "the candidate space was searched, not "
                                  "enumerated, so the model bound is silent "
                                  "about candidates the search never evaluated",
    "model_recommendation_not_compared": "the fitted argmax was not measured "
                                         "admissibly in the final round, so the "
                                         "model bound cannot be linked to the "
                                         "winner",
    "model_recommendation_infeasible": "the fitted argmax was measured "
                                       "inadmissible, so the model bound -- "
                                       "taken against it -- cannot be linked "
                                       "to the admissible winner",
    "shortlist_refilled": "the shortlist was refilled after finalists were "
                          "measured inadmissible; the replacements were "
                          "compared, but the ranking that nominated the "
                          "originals is not trusted to have kept the optimum",
}

#: Plain-language reading of a measured-front status (``report.json["pareto"]``).
FRONT_STATUS_MEANING = {
    "confidently_nondominated": "no rival is better by epsilon on every "
                                "objective, with confidence",
    "possibly_dominated": "a rival could not be ruled out",
}


def _eps_ref(ref) -> str:
    """Which reference a percentage epsilon was taken of, when it was not the winner."""
    if not isinstance(ref, dict) or ref.get("source") in (None, "best_finalist",
                                                         "declared_abs"):
        return ""
    src = ref["source"]
    if src == "best_observed":
        lv = ", ".join(f"{k}={v}" for k, v in sorted((ref.get("levels") or {}).items()))
        return (f" (of the best measured admissible configuration `{lv}` = "
                f"{_fmt(ref.get('value'))}; no finalist was admissible)")
    if src == "recommendation":
        return " (the fitting stage's epsilon; no admissible configuration was measured)"
    return " (no reference: unknown, not zero)"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _candidate_space_note(work_dir: Path) -> list[str]:
    """A note for every fitting stage whose candidate space was SEARCHED.

    ``recommendation.json["candidate_space"]`` is written only above
    ``decide.CANDIDATE_CAP``; an enumerated campaign gets no note (and its
    report is unchanged). The fitted argmax, shortlist, model regret bound and
    predicted front of such a stage are over the evaluated set only.
    """
    from orchestrator.optimize.stage_runner import _this_epoch_dirs

    out = []
    # THIS epoch's stages only: report.json carries this epoch's
    # candidate_space, and the note must not describe another epoch's search.
    for p in (d / "recommendation.json" for d in _this_epoch_dirs(work_dir)):
        if not p.exists():
            continue
        cs = (_read_json(p) or {}).get("candidate_space")
        if not isinstance(cs, dict) or cs.get("exhaustive", True):
            continue
        rec = _read_json(p) or {}
        aa = rec.get("alias_assessment") or {}
        out.append(
            f"- `{rec.get('stage', '?')}` ({p.parent.name}): {cs.get('evaluated')} of "
            f"{cs.get('size')} configurations evaluated by `{cs.get('method')}` "
            f"(seed {cs.get('seed')})"
            + ("; constraint models NOT applied: neither the search nor a "
               "feasibility ascent found a point they admit"
               if cs.get("constraint_models_applied") is False else "")
            + (f"; {len(aa['unassessed'])} of {aa.get('readings')} alias readings "
               f"NOT assessed (the {aa.get('assessed')} with the largest "
               f"coefficients were)" if aa.get("unassessed") else "")
            + (f"; {cs['seeds_dropped']} measured configuration(s) could not seed "
               f"the search" if cs.get("seeds_dropped") else ""))
    if not out:
        return []
    return [
        "> **Candidate space searched, not enumerated.** The fitted factors' "
        "axes multiply to more candidates than `decide.CANDIDATE_CAP`, so the "
        "model's argmax, its runners-up, the model regret bound and any "
        "predicted front were taken over the configurations a seeded search "
        "evaluated, not over every valid configuration. A better configuration "
        "the search did not reach is possible. Likewise an empty "
        "`alias_consequential` means no consequential alias was FOUND "
        "(`alias_consequential_basis: searched`), and a predicted front's "
        "`nondominated` statuses are among evaluated points only. Measured "
        "results (confirm, the terminal bound) are unaffected.",
        "",
        *out,
        "",
    ]


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return "n/a" if value is None else str(value)


def _fmt_levels(levels: dict | None) -> str:
    if not levels:
        return "(none)"
    return ", ".join(f"`{k}={levels[k]}`" for k in sorted(levels))


def _epoch_of(work_dir: Path):
    rep = _read_json(work_dir / "report.json") or {}
    return rep.get("epoch") or (_read_json(work_dir / "policy.json") or {}).get("epoch", 1)


def _out_of_hull_axes(work_dir: Path) -> list[str]:
    """Each axis of the latest fitted stationary point outside ±1, in REAL levels.

    ``recommendation.json`` records the stationary point in coded units, which
    tell an author nothing about what to type into ``levels``. Decoded here --
    through the factor's own scale, unclamped -- with a concrete suggestion one
    half-range past the current edge: an extrapolation is not a measurement, so
    the next epoch should bracket the direction, not jump to the extrapolated
    value.
    """
    import math

    import yaml

    from orchestrator.optimize.factors import _from_axis, _to_axis, parse_factors, snap_to_grid

    from orchestrator.optimize.stage_runner import _epoch_recommendations

    # THIS epoch's latest stationary point: it is in coded units relative to
    # the ranges it was fitted on, and is decoded below against THIS epoch's
    # factors -- an earlier epoch's point would be decoded against the wrong
    # ranges and the "widen to X" advice would be wrong.
    _recs = _epoch_recommendations(work_dir)
    sp = _recs[-1].get("stationary_point") if _recs else None
    # The campaign THIS epoch registered (stage_runner writes it at compile);
    # campaign.yaml is the first epoch's and goes stale once levels are revised.
    epoch_copy = work_dir / f"campaign.epoch-{_epoch_of(work_dir)}.yaml"
    source = epoch_copy if epoch_copy.exists() else work_dir / "campaign.yaml"
    try:
        campaign = yaml.safe_load(source.read_text()) or {}
        factors = {f.id: f for f in parse_factors(
            (campaign.get("optimization") or {}).get("factors") or [])}
    except (OSError, ValueError, yaml.YAMLError):
        return []
    # Constraint evidence at each edge. The stationary point is a property of
    # the PRIMARY surface alone; when the edge it points past was measured
    # infeasible, the constrained optimum is inside the range and "widen" would
    # walk the next epoch into the constraint (found on a real campaign: a write
    # cache whose upper edge broke the durability SLA on every row).
    from orchestrator.optimize.stage_runner import _this_epoch_runs

    rows = []
    for rj in _this_epoch_runs(work_dir):
        for line in Path(rj).read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    primary = ((campaign.get("optimization") or {}).get("response") or {}).get("primary") or {}
    sign = -1.0 if primary.get("direction") == "minimize" else 1.0

    def _measured_peak(fid):
        """The level of ``fid`` with the best MEASURED marginal mean, if any.

        The stationary point is an extrapolation of a fitted quadratic; when
        the measurements themselves peak at an interior level, "extend" or
        "pin the edge" would follow the fit's artefact (found on a real Go
        campaign: the fit put concurrency's optimum below 1 while its measured
        mean at 1 was not the best).
        """
        by_level: dict = {}
        for r in rows:
            v = (r.get("response") or {}).get(primary.get("metric"))
            lv = (r.get("levels") or {}).get(fid)
            if r.get("status") != "complete" or lv is None \
                    or not isinstance(v, (int, float)) or v != v:
                continue
            by_level.setdefault(lv, []).append(float(v))
        means = {lv: sum(vs) / len(vs) for lv, vs in by_level.items() if len(vs) >= 2}
        return max(means, key=lambda lv: sign * means[lv]) if len(means) >= 2 else None

    def _edge_status(fid, edge):
        at = [r for r in rows if (r.get("levels") or {}).get(fid) == edge]
        bad = [r for r in at if r.get("status") in ("infeasible", "rejected")]
        return len(at), len(bad)

    out = []
    for fid, coded in sorted((sp or {}).items()):
        f = factors.get(fid)
        if f is None or f.type != "numeric" or not isinstance(coded, (int, float)) \
                or abs(coded) <= 1.0 or not math.isfinite(coded):
            continue
        lo, hi = _to_axis(f, f.screen_levels[0]), _to_axis(f, f.screen_levels[1])
        mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0
        side = "above" if (coded > 0) == (hi > lo) else "below"
        suggest = _from_axis(f, mid + math.copysign(2.0, coded) * half)
        edge = f.screen_levels[1] if (coded > 0) == (hi > lo) else f.screen_levels[0]
        n_at, n_bad = _edge_status(fid, edge)
        peak = _measured_peak(fid) if primary.get("metric") else None
        if peak is not None and peak != edge and not (n_at and n_bad == n_at):
            out.append(
                f"- **{fid}**: the fitted surface extrapolates past {edge}, but the "
                f"measured means peak INSIDE the range, at {fid}={_fmt(peak)}. "
                f"Keep `{fid}`'s range; if anything, add levels around {_fmt(peak)}."
            )
            continue
        if n_at and n_bad == n_at:
            out.append(
                f"- **{fid}**: the PRIMARY surface keeps rising past {edge}, but "
                f"all {n_at} row(s) measured at {fid}={edge} were infeasible: the "
                f"constrained optimum lies inside the declared range. Do not "
                f"extend `{fid}`; if anything, add interior levels below {edge}."
            )
            continue
        # The suggestion must be a level the target can run: on the grid, and
        # inside the domain the factor's scale admits (a log axis is > 0, and an
        # integral log knob -- a count -- is >= one grid step). Found on a real
        # campaign: "extend concurrency downward to about 0.5" and "GOMAXPROCS
        # to about 22.6".
        floor = (f.grid or 0.0) if f.scale == "log" else None
        suggest = snap_to_grid(suggest, f.grid)
        if f.grid and suggest == edge:  # snapping fell back onto the edge
            step = f.grid if float(edge) >= max(map(float, f.screen_levels)) else -f.grid
            suggest = snap_to_grid(float(edge) + step, f.grid)
        at_floor = (side == "below" and floor is not None and floor > 0
                    and float(edge) <= floor)
        if at_floor:
            out.append(
                f"- **{fid}**: the fitted optimum lies below {edge}, the smallest "
                f"valid value of `{fid}`: the edge IS the answer for this factor. "
                f"Pin `{fid}={edge}` (or drop it) and spend the next epoch's runs "
                f"on the other factors."
            )
            continue
        if side == "below" and floor is not None and floor > 0 and suggest < floor:
            suggest = snap_to_grid(floor, f.grid)
        if getattr(f, "levels_only", False):
            # A levels_only knob takes only listed values, so the suggestion
            # is the next value CONTINUING the declared spacing at that edge
            # (the next power of two on 16..1024), in the factor's own scale.
            from orchestrator.optimize.factors import runnable_levels

            rl = runnable_levels(f)
            if len(rl) >= 2:
                a, b = ((rl[-2], rl[-1]) if side == "above" else (rl[1], rl[0]))
                ya, yb = _to_axis(f, a), _to_axis(f, b)
                suggest = round(_from_axis(f, yb + (yb - ya)), 9)
                if all(isinstance(v, int) for v in f.levels) and float(suggest).is_integer():
                    suggest = int(suggest)
        out.append(
            f"- **{fid}**: the fitted optimum is at about "
            f"{_fmt(_from_axis(f, mid + coded * half))} (coded {coded:+.2f}), "
            f"{side} the declared range {list(f.levels)}. Extend `{fid}`'s levels "
            f"{'upward' if side == 'above' else 'downward'}, e.g. to {_fmt(suggest)}"
            f" -- unless {edge} is already a hard limit of the system (a core "
            f"count, a memory budget, a protocol maximum), in which case the edge "
            f"is the answer: pin `{fid}={edge}`."
        )
    return out


def _next_epoch_section(work_dir: Path, report: dict) -> list[str]:
    """What the author does next, stated where the author reads first."""
    end = _read_json(work_dir / f"epoch_end-{report.get('epoch')}.json") or {}
    needs = str(end.get("next_epoch_requires") or "").strip()
    lines = ["## What to do next", ""]
    if needs:
        lines += [needs, ""]
    axes = _out_of_hull_axes(work_dir)
    if axes:
        lines += axes + [""]
    lines += [
        "Edit the campaign file accordingly, then `nous resume <campaign.yaml>`: "
        "the revised campaign recompiles into a new epoch, starting at `screen`.",
        "",
    ]
    return lines


def _campaign_factors(work_dir: Path) -> tuple[dict, str | None]:
    """``({factor_id: Factor}, problem)``. ``problem`` names why the campaign's
    factors could not be read (B4): logged at WARNING and printed in report.md
    instead of silently dropping the range-edge advice."""
    import logging

    import yaml

    from orchestrator.optimize.factors import parse_factors

    epoch_copy = work_dir / f"campaign.epoch-{_epoch_of(work_dir)}.yaml"
    source = epoch_copy if epoch_copy.exists() else work_dir / "campaign.yaml"
    try:
        campaign = yaml.safe_load(source.read_text()) or {}
        return {f.id: f for f in parse_factors(
            (campaign.get("optimization") or {}).get("factors") or [])}, None
    except (OSError, ValueError, yaml.YAMLError) as exc:
        problem = f"{source.name} could not be read ({type(exc).__name__}: {exc})"
        logging.getLogger(__name__).warning("report.md: %s", problem)
        return {}, problem


def _eps_cell(v) -> str:
    return "**unknown** (no reference for a percentage)" if v is None else _fmt(v)


def _preferred_entry(report: dict) -> dict | None:
    par = report.get("pareto") or {}
    chosen = dict((par.get("preference") or {}).get("chosen") or {})
    return next((f for f in par.get("front") or []
                 if dict(f.get("levels") or {}) == chosen), None) if chosen else None


def _objective_values(report: dict) -> list[str]:
    """C1: every objective's mean (and interval) at the recommendation."""
    par = report.get("pareto") or {}
    f = _preferred_entry(report)
    rec_levels = dict((report.get("recommendation") or {}).get("levels") or {})
    if f is None or dict(f.get("levels") or {}) != rec_levels:
        return [f"- **Value:** not on the measured front (no per-objective "
                f"measurement of the recommendation to show)"]
    out = []
    for o in par.get("objectives") or []:
        m = o["metric"]
        ci = (f.get("ci") or {}).get(m)
        out.append(f"- **{m}** ({o['direction']}): {_fmt((f.get('mean') or {}).get(m))}"
                   + (f" [{_fmt(ci[0])}, {_fmt(ci[1])}]" if ci else "")
                   + f", n={_fmt(f.get('n'))}")
    return out


def _front_section(work_dir: Path, report: dict) -> list[str]:
    """The measured trade-off front (multi-objective campaigns only).

    Sorted by the first objective (the order ``report.json`` stores it in),
    the preferred point marked, each status explained once, then the
    hypervolume and the gaps the campaign did not fill.
    """
    par = report.get("pareto") or {}
    objs = par.get("objectives") or []
    metrics = [o["metric"] for o in objs]
    chosen = (par.get("preference") or {}).get("chosen") or {}
    front = par.get("front") or []
    lines = ["## Trade-off front", ""]
    lines.append("Objectives: " + ", ".join(
        f"`{o['metric']}` ({o['direction']})" for o in objs) + ".")
    lines.append("")
    if not front:
        return lines + ["_No measured admissible configuration formed a front._", ""]
    eps = par.get("epsilon") or {}
    head = "| # | configuration | " + " | ".join(f"{m}" for m in metrics) + \
        " | n | status | source |"
    lines += [head, "|" + "---|" * (len(metrics) + 5)]
    for i, f in enumerate(front):
        mark = " **(preferred)**" if dict(f.get("levels") or {}) == dict(chosen) else ""
        cells = []
        for m in metrics:
            ci = (f.get("ci") or {}).get(m)
            cells.append(_fmt((f.get("mean") or {}).get(m)) + (
                f" [{_fmt(ci[0])}, {_fmt(ci[1])}]" if ci else ""))
        lines.append(
            f"| {i} | {_fmt_levels(f.get('levels'))}{mark} | " + " | ".join(cells)
            + f" | {_fmt(f.get('n'))} | {f.get('status', '')} | {f.get('source', '')} |")
    lines.append("")
    for st, meaning in FRONT_STATUS_MEANING.items():
        n = sum(1 for f in front if f.get("status") == st)
        if n:
            lines.append(f"- `{st}` ({n}): {meaning}.")
    hv = par.get("hypervolume") or {}
    pref = par.get("preference") or {}
    lines += [
        f"- **Preference:** `{pref.get('method', 'knee')}` chose "
        f"{_fmt_levels(chosen)} ({pref.get('chosen_status') or 'n/a'}); scalar "
        f"regret {_fmt(pref.get('scalar_regret'))} vs epsilon "
        f"{_fmt(pref.get('scalar_epsilon'))}.",
        (f"- **Hypervolume:** {_fmt(hv.get('value'))} over "
         f"{sum(1 for f in front if f.get('status') == 'confidently_nondominated')} "
         f"confidently nondominated point(s) (objectives normalised to "
         f"[0, 1] by the measured range; reference "
         + ", ".join(f"{m}={_fmt(v)}" for m, v in sorted((hv.get("reference") or {}).items()))
         + f"; {hv.get('method', '')}).")
        if hv.get("value") is not None else
        f"- **Hypervolume:** undefined -- {hv.get('reason') or 'no confident point'}.",
        "- **Epsilon per objective:** " + ", ".join(
            f"`{m}` {_eps_cell(eps.get(m))}" for m in metrics) + ".",
        (f"- **Predicted rivals:** "
         + ("considered" if (par.get("predicted_rivals") or {}).get("considered")
            else "NOT considered")
         + f" -- {(par.get('predicted_rivals') or {}).get('reason', 'not recorded')}.")
        if par.get("predicted_rivals") else "- **Predicted rivals:** not recorded.",
        f"- **Confirm rounds:** {_fmt(par.get('rounds'))}.",
    ]
    excl = par.get("excluded_incomplete") or []
    gone = [x for x in excl if x.get("dropped", True)]
    rows_only = [x for x in excl if not x.get("dropped", True)]
    if gone:
        lines.append("- **Left out for an incomplete measurement:** " + "; ".join(
            f"{_fmt_levels(x.get('levels'))} (missing {', '.join(x.get('missing') or []) or 'a usable value'}"
            f", {x.get('source', '')})" for x in gone) + ".")
    if rows_only:
        lines.append("- **Rows left out, configuration still measured:** " + "; ".join(
            f"{_fmt_levels(x.get('levels'))} (a row missing "
            f"{', '.join(x.get('missing') or []) or 'a usable value'})" for x in rows_only) + ".")
    gaps = par.get("gaps_remaining") or []
    if gaps and par.get("gap_threshold") is None:
        lines.append("- **Gaps:** no objective's epsilon is known, so no gap can be "
                     "judged against an indifference width.")
    elif gaps:
        lines.append("- **Gaps remaining** (normalised, wider than twice the largest "
                     "normalised epsilon): " + "; ".join(
                         f"between #{g['between'][0]} and #{g['between'][1]} "
                         f"({_fmt(g['size'])})" for g in gaps) + ".")
    else:
        lines.append("- **Gaps remaining:** none wider than twice the largest "
                     "normalised epsilon.")
    lines.append("")
    return lines


def _front_next_steps(work_dir: Path, report: dict) -> list[str]:
    """How to widen or refine the front -- stated from the front itself."""
    par = report.get("pareto") or {}
    front = par.get("front") or []
    objs = par.get("objectives") or []
    out = ["## What to do next", ""]
    if not front:
        # B5: nothing to refine -- say why nothing was admissible.
        n = par.get("n_measured_configurations")
        excl = [x for x in par.get("excluded_incomplete") or [] if x.get("dropped", True)]
        why = []
        if excl:
            why.append(f"{len(excl)} configuration(s) were left out because a row "
                       f"lacked a usable value for some objective "
                       f"({', '.join(sorted({m for x in excl for m in x.get('missing') or []})) or 'see pareto.excluded_incomplete'})"
                       f" -- fix the adapter's output for those objectives")
        if not n:
            why.append("no configuration was measured ADMISSIBLE: every measured row "
                       "was infeasible, rejected or failed -- relax the constraint "
                       "that rejected them, widen the factors' ranges into the "
                       "admissible region, or repair the runs that failed")
        out += [f"- The measured front is EMPTY: " + "; ".join(
            why or ["no admissible configuration produced every objective"]) + ".", ""]
        return out
    if par.get("gaps_remaining"):
        out.append(
            "- **Fill the gaps:** the front has gaps wider than the campaign's "
            "indifference. Raise `optimization.policy.confirm_max_rounds` (each "
            "extra round runs the registered gap-fill branch) or "
            "`optimization.design.confirm.shortlist_size`.")
    n_poss = sum(1 for f in front if f.get("status") == "possibly_dominated")
    if n_poss:
        out.append(
            f"- **Resolve {n_poss} possibly-dominated point(s):** more confirm "
            f"replicates (`design.confirm.replicates`) narrow every interval; a "
            f"wider `policy.epsilon` accepts smaller differences as ties.")
    factors, factors_problem = _campaign_factors(work_dir)
    if factors_problem:
        out.append(f"- _Range-edge advice unavailable: {factors_problem}._")
    edges = []
    for o in objs:
        m, sgn = o["metric"], (-1.0 if o["direction"] == "minimize" else 1.0)
        pts = [f for f in front if isinstance((f.get("mean") or {}).get(m), (int, float))]
        if not pts:
            continue
        best = max(pts, key=lambda f: sgn * f["mean"][m])
        for fid, lv in sorted((best.get("levels") or {}).items()):
            f = factors.get(fid)
            if f is None or f.type != "numeric" or not isinstance(lv, (int, float)):
                continue
            lo, hi = min(f.levels), max(f.levels)
            if lv in (lo, hi):
                edges.append(f"`{fid}={lv}` (the {'upper' if lv == hi else 'lower'} "
                             f"edge) at the best `{m}`")
    if edges:
        out.append("- **Widen the front:** the extreme of an objective sits on a "
                   "declared range edge -- " + "; ".join(edges) + ". Extending "
                   "that factor's levels past the edge may extend the front "
                   "(unless a constraint binds there).")
    if len(out) == 2 and not factors_problem:
        out.append("- The front is resolved at this campaign's epsilon; pick the "
                   "trade-off you want from the table above.")
    return out + [""]


def render_report_markdown(work_dir: Path) -> str:
    """Render ``report.md`` from ``report.json``. Pure; makes no model call.

    When ``report.json`` is absent (the campaign stopped before the report
    stage) the document says so and points at the progress surface, rather than
    inventing an answer.
    """
    work_dir = Path(work_dir)
    report = _read_json(work_dir / "report.json")
    snap = _progress.read_progress_snapshot(work_dir)
    lines = [f"# Optimization campaign report — {snap.run_id or work_dir.name}", ""]

    if not isinstance(report, dict):
        lines += [
            "**No `report.json` was written**: the campaign stopped before its "
            "report stage, so there is no recommendation to restate.",
            "",
            "Where it stopped:",
            "",
            "```",
            _progress.format_progress(snap),
            "```",
            "",
        ]
        return "\n".join(lines)

    rec = report.get("recommendation") or {}
    basis = rec.get("basis", "none")
    lines += [
        "## Recommendation",
        "",
        f"- **Configuration:** {_fmt_levels(rec.get('levels'))}",
        *(_objective_values(report) if isinstance(report.get("pareto"), dict)
          else [f"- **Value:** {_fmt(rec.get('value'))}"]),
        f"- **Basis:** `{basis}` — {BASIS_MEANING.get(basis, 'unknown rung')}",
        f"- **Certified:** {'yes' if report.get('certified') else 'no'}",
    ]
    withheld = report.get("certification_withheld") or []
    if withheld and not report.get("certified"):
        lines.append("- **Certification withheld because:** " + "; ".join(
            f"`{r}` ({WITHHELD_MEANING.get(r, 'unrecognised reason')})"
            for r in withheld))
    g = report.get("gain_over_baseline") or {}
    if g.get("low") is not None:
        lines.append(f"- **Gain over the baseline** {_fmt_levels(g.get('baseline'))}: "
                     f"[{_fmt(g['low'])}, {_fmt(g['high'])}] (coverage >= "
                     f"{1 - float(g.get('delta_guaranteed', g['delta'])):.3g} over the "
                     f"registered confirm looks -- the round reported is the one the "
                     f"campaign stopped at; from that round's fresh replicates; point "
                     f"estimate {_fmt(g.get('estimate'))}, biased upward by selection)")
    scope = report.get("certificate_scope") or {}
    if scope.get("region") == "slice":
        lines.append("- **Certificate scope:** a slice -- "
                     + ", ".join(f"`{k}={v}`" for k, v in sorted(
                         (scope.get("held_fixed") or {}).items()))
                     + " held fixed by the "
                     + f"{scope.get('fitting_stage') or 'fitting'} stage; the other "
                     "levels of those factors are not covered"
                     + ("" if report.get("certified") else
                        " (nothing is certified here in any case)"))
    if "model_adequate" in report and report["model_adequate"] is None:
        # A legacy record may carry null with no basis (stage-1c P9).
        b = str(report.get("model_adequate_basis") or "model_adequacy_unknown")
        lines.append(f"- **Model adequacy:** unknown (`{b}` — {WITHHELD_MEANING.get(b, '')})")
    elif report.get("model_adequate") is False:
        lines += _inadequate_lines(report)
    every = set(report.get("all_levels_inadmissible") or ())
    for key, label in (("curvature_untested_levels", "Curvature never checked under"),
                       ("lost_levels", "Levels lost (no retained run; never "
                                       "recommended except via the exempt "
                                       "known_valid_baseline)"),
                       ("inadmissible_levels",
                        "Levels inadmissible wherever measured (never recommended "
                        "except via the exempt known_valid_baseline)")):
        rows = {fid: lvs for fid, lvs in (report.get(key) or {}).items()
                if not (key == "inadmissible_levels" and fid in every)}
        if rows:
            lines.append(f"- **{label}:** " + "; ".join(
                f"{fid}: {', '.join(map(str, lvs))}" for fid, lvs in rows.items()))
    if every:
        lines.append(f"- **Lost and inadmissible levels cover every level of:** "
                     f"{', '.join(sorted(every))} — only the LOST levels are "
                     f"excluded; the inadmissible ones stay candidates, so the "
                     f"recommendation may name one")
    if report.get("recommendation_names_barred_level"):
        lines.append("- **Recommended baseline names lost/inadmissible level(s):** "
                     + ", ".join(f"{k}={v}" for k, v in
                                 report["recommendation_names_barred_level"].items())
                     + " (the declared known_valid_baseline is exempt)")
    if report.get("aliases_not_assessed"):
        lines.append("- **Aliases not assessed** (2fi in the span of kept columns; "
                     "alias_consequential cannot re-attribute them): "
                     + ", ".join(report["aliases_not_assessed"]))
    lines.append("")
    lines += _candidate_space_note(work_dir)
    if isinstance(report.get("pareto"), dict):
        lines += _front_section(work_dir, report)
        if not report.get("epoch_ended"):
            lines += _front_next_steps(work_dir, report)
    if report.get("epoch_ended"):
        lines += [
            f"> **The epoch ended on a semantic exception:** "
            f"`{report['epoch_ended']}`. The `model` rung is suppressed because "
            f"the exception is evidence against the fitted surface; see "
            f"`epoch_end-{report.get('epoch')}.json`.",
            "",
        ]
        lines += _next_epoch_section(work_dir, report)
    elif report.get("boundary_optimum"):
        b = report["boundary_optimum"]
        lines += [
            f"> **Boundary optimum.** The fitted optimum lies past the declared "
            f"range on {', '.join(f'`{a}`' for a in b.get('axes') or []) or 'some axis'}"
            f", so the recommendation is the best configuration INSIDE the "
            f"declared ranges"
            + (" and the certificate covers only those ranges." if report.get("certified")
               else ".")
            + " Widening the axes below may find a better one.",
            "",
        ]
        lines += _next_epoch_section(work_dir, report)

    par = report.get("pareto") if isinstance(report.get("pareto"), dict) else None
    if par is not None:
        # C3: the single-objective rows describe the FIRST objective only; a
        # multi-objective certificate is the preference scalarisation's.
        pref = par.get("preference") or {}
        first = ((par.get("objectives") or [{}])[0]).get("metric", "")
        lines += [
            "## Bounds",
            "",
            f"The certificate is the `{pref.get('method', 'knee')}` preference's "
            "scalarisation over the measured front (normalised units); per-objective "
            "epsilon is each objective's indifference width.",
            "",
            "| quantity | value |",
            "|---|---|",
            *[f"| epsilon, `{o['metric']}` | {_eps_cell((par.get('epsilon') or {}).get(o['metric']))} |"
              for o in par.get("objectives") or []],
            f"| scalar regret, terminal (preference) | {_fmt(pref.get('scalar_regret'))} |",
            f"| scalar epsilon (preference) | {_fmt(pref.get('scalar_epsilon'))} |",
            f"| residual regret, model (first objective `{first}`, at its argmax) | "
            f"{_fmt(report.get('residual_regret_model'))} |",
            f"| delta, screen | {_fmt(report.get('delta_screen'))} |",
            f"| delta, front statuses | {_fmt(par.get('delta_front'))} |",
            f"| delta, certification | {_fmt(par.get('delta_certification'))} |",
            "",
        ]
    lines += [] if par is not None else [
        "## Bounds",
        "",
        "| quantity | value |",
        "|---|---|",
        f"| epsilon (acceptable regret) | {_fmt(report.get('epsilon'))}"
        f"{_eps_ref(report.get('epsilon_reference'))} |",
        f"| residual regret, model (at the fitted argmax) | {_fmt(report.get('residual_regret_model'))} |",
        f"| residual regret, terminal | {_fmt(report.get('residual_regret_terminal'))} |",
        f"| delta, screen | {_fmt(report.get('delta_screen'))} |",
        f"| delta, terminal | {_fmt(report.get('delta_terminal'))} |",
        "",
    ]
    if basis != "model" and par is None:
        # The model bound is computed at the fitted argmax, which a fallback
        # rung or a terminal winner need not be: printed bare under the
        # recommendation it would read as THAT configuration's regret.
        lines += [
            "_The model bound is computed at the fitted argmax "
            "(`recommendation.json`), not at the recommended configuration; "
            f"under basis `{basis}` it does not bound the recommendation. "
            "The terminal bound is the one that does, when it is present._",
            "",
        ]

    finalists = report.get("finalists") or []
    if finalists and par is not None:
        metrics = [o["metric"] for o in par.get("objectives") or []]
        lines += [
            "## Finalists",
            "",
            "| key | configuration | " + " | ".join(metrics) + " | n | status | why |",
            "|" + "---|" * (len(metrics) + 5),
        ]
        by_levels = {json.dumps(x.get("levels") or {}, sort_keys=True, default=str): x
                     for x in par.get("front") or []}
        for f in finalists:
            means = f.get("means")
            if means is None:
                # Written before confirm recorded per-objective means: the first
                # objective's `mean` is this round's; any other column comes
                # from the measured front (every confirm round), or n/a.
                fr = by_levels.get(json.dumps(f.get("levels") or {}, sort_keys=True,
                                              default=str)) or {}
                means = {**(fr.get("mean") or {}),
                         **({metrics[0]: f.get("mean")} if metrics else {})}
            lines.append(
                f"| {f.get('key', '')} | {_fmt_levels(f.get('levels'))} | "
                + " | ".join(_fmt(means.get(m)) for m in metrics)
                + f" | {_fmt(f.get('n'))} | {f.get('status', '')} | {f.get('why', '')} |")
        lines.append("")
        finalists = []
    if finalists:
        lines += [
            "## Finalists",
            "",
            "| key | configuration | mean | n | status | why |",
            "|---|---|---|---|---|---|",
        ]
        for f in finalists:
            lines.append(
                f"| {f.get('key', '')} | {_fmt_levels(f.get('levels'))} | "
                f"{_fmt(f.get('mean'))} | {_fmt(f.get('n'))} | "
                f"{f.get('status', '')} | {f.get('why', '')} |"
            )
        lines.append("")

    held = report.get("held_out")
    if isinstance(held, dict) and held.get("metrics"):
        lines += [
            "## Held-out check",
            "",
            "Recorded on every row, read by no decision above. Means over this "
            "epoch's complete rows at exactly these levels; `n = 0` means no "
            "complete row measured that configuration.",
            "",
            "| configuration | metric | held-out mean | primary mean (same rows) | n |",
            "|---|---|---|---|---|",
        ]
        entries = [("recommendation", held.get("recommendation") or {})] + [
            (str(f.get("key") or "finalist"), f) for f in held.get("finalists") or []
        ]
        for label, e in entries:
            for m, v in (e.get("metrics") or {}).items():
                lines.append(
                    f"| {label}: {_fmt_levels(e.get('levels'))} | `{m}` | "
                    f"{_fmt(v.get('mean'))} | {_fmt(v.get('primary_mean_same_rows'))} | "
                    f"{v.get('n', 0)} |"
                )
        lines.append("")

    baseline = report.get("known_valid_baseline")
    lines += [
        "## Provenance",
        "",
        f"- **Epoch:** {_fmt(report.get('epoch'))}, written at iteration "
        f"{_fmt(report.get('iteration'))}",
        f"- **Path through the policy:** {' → '.join(report.get('path') or []) or '(none)'}",
        f"- **Policy hash:** `{report.get('policy_hash', '')}`",
        f"- **Known-valid baseline:** {_fmt_levels(baseline) if baseline else '(none declared)'}",
        *_provenance_lines(report),
        "",
        "_Rendered from `report.json` with no model call; `report.json` is the "
        "record of the answer._",
        "",
    ]
    return "\n".join(_insert_error_budget(lines, report))


def _error_budget_lines(report: dict) -> list[str]:
    """The cumulative error budget over every epoch (audit Q7): a reader must
    see the family-wise figure, not only this epoch's deltas."""
    eb = report.get("error_budget")
    if not isinstance(eb, dict):
        return []
    rows = [f"| {e.get('epoch')} | {_fmt(e.get('delta_screen'))} | "
            f"{_fmt(e.get('delta_terminal'))} | {_fmt(e.get('spent'))} | "
            f"{'yes' if e.get('compiled_after_data') else 'no'} |"
            for e in eb.get("epochs") or []]
    cum = _fmt(eb.get("cumulative"))
    if eb.get("cumulative_is_lower_bound"):
        cum = f">= {cum} (epoch(s) {eb.get('unrecovered_epochs')} not recoverable)"
    return [
        "## Error budget across epochs",
        "",
        "| epoch | delta, screen | delta, terminal | spent | compiled after earlier data |",
        "|---|---|---|---|---|",
        *rows,
        "",
        f"**Cumulative (union bound over epochs): {cum}.** Certification above is "
        "judged at this epoch's deltas; the cumulative figure is the probability "
        "bound that ANY epoch's decision on this work_dir is wrong.",
        "",
    ]


def _insert_error_budget(lines: list[str], report: dict) -> list[str]:
    extra = _error_budget_lines(report)
    if not extra:
        return lines
    try:
        at = lines.index("## Provenance")
    except ValueError:
        return lines + extra
    return lines[:at] + extra + lines[at:]


def _provenance_lines(report: dict) -> list[str]:
    prov = report.get("provenance")
    if not isinstance(prov, dict):
        return []
    nous = prov.get("nous") or {}
    ver = nous.get("package_version") or "unknown"
    commit = nous.get("git_commit")
    src = nous.get("source_sha256")
    out = [f"- **Nous:** {ver}" + (f" at `{commit[:12]}`" if commit else "")
           + (f", source sha256 `{src[:12]}`" if src else "")]
    out.append(f"- **Inputs hashed:** {len(prov.get('inputs') or {})} file(s) "
               "(`runs.jsonl`, `design_matrix.json`, `relations.json`, each epoch's "
               "registered campaign); `nous reanalyze` re-derives this report's "
               "analysis from them")
    mdl = prov.get("model") if isinstance(prov.get("model"), dict) else None
    if mdl and mdl.get("calls"):
        seen = sorted({f"{c.get('requested')} -> {c.get('resolved') or 'not reported'}"
                       for c in mdl["calls"]})
        out.append("- **Model (requested -> served):** " + "; ".join(seen)
                   + ("" if mdl.get("snapshot_pinned") else
                      " (the requested ID is an alias, not a dated snapshot)"))
    anc = prov.get("anchor") if isinstance(prov.get("anchor"), dict) else None
    if anc and not anc.get("present"):
        out.append("- **External anchor:** none; the pre-registration is self-attested")
    if anc and anc.get("present"):
        out.append("- **External anchor:** " + (
            f"matches ({anc.get('where')})" if anc.get("matches") else
            "**MISMATCH**: " + "; ".join(anc.get("mismatches") or [])))
        if anc.get("reanchored"):
            out.append(f"- **Re-registered before running:** epoch(s) {anc['reanchored']} "
                       "were anchored with more than one policy; the latest is checked")
    echo = [m for m in prov.get("manipulation_evidence") or [] if m.get("evidence") == "echo"]
    if echo:
        out.append("- **Manipulation checks that are echo-only:** "
                   + ", ".join(f"`{m['factor']}` (`{m.get('observable')}`)" for m in echo)
                   + ". These read Nous's own record of the level it set, so they show "
                     "the lever was sent, not that the target received it")
    for w in prov.get("waivers") or []:
        out.append(f"- **Gate waived:** `{w.get('gate')}` -- {w.get('reason')}"
                   + (f" ({w['note']})" if w.get("note") else ""))
    return out


def write_report_markdown(work_dir: Path) -> Path:
    path = Path(work_dir) / "report.md"
    path.write_text(render_report_markdown(work_dir))
    return path


def write_gate_summary(work_dir: Path, iteration: int, *,
                       gate_type: str = "continue") -> Path:
    """Write ``runs/iter-<N>/gate_summary_<gate_type>.json`` from the progress snapshot.

    Same shape as ``gate_summary.schema.json``, so the gate displays it exactly
    as it displays a model-written one.
    """
    work_dir = Path(work_dir)
    snap = _progress.read_progress_snapshot(work_dir)
    key_points = [ln for ln in _progress.format_progress(snap).splitlines()
                  if ln.strip()]
    doc = {
        "gate_type": gate_type,
        "summary": _progress.format_progress_line(snap),
        "key_points": key_points or ["no progress recorded yet"],
    }
    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    path = iter_dir / f"gate_summary_{gate_type}.json"
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def _inadequate_lines(report: dict) -> list[str]:
    """The model-inadequate block (WP-B B5): say plainly that the surface is
    not well approximated, what the answer then rests on, and what to do."""
    why = [str(c) for c in (report.get("model_rejected_by") or [])]
    reason = {
        "lack_of_fit": "its lack-of-fit test rejected",
        "validation_prediction": ("the held-out validation runs disagreed with "
                                  "its predictions"),
    }
    said = "; ".join(reason.get(c.split(":")[0], c) for c in why) or (
        "its lack-of-fit test (or an objective model's) rejected")
    basis = str((report.get("recommendation") or {}).get("basis") or "")
    rests = {
        "terminal_best": "the measured leaders the terminal stage re-measured "
                         "against each other",
        "certified": "the measured leaders the terminal stage re-measured "
                     "against each other",
        "measured": "the best MEASURED valid configuration",
        "baseline": "the declared known_valid_baseline",
    }.get(basis, "no model-free evidence")
    return [
        f"- **Model adequacy:** rejected — {said}. The response surface is NOT "
        f"well approximated by the registered model over these ranges, so the "
        f"recommendation above is NOT the model's argmax: it rests on {rests}.",
        "- **What to do about it:** narrow the ranges to the region the leaders "
        "sit in (a quadratic is a local approximation); code a geometric knob "
        "with `scale: log`; transform the response; declare more levels on the "
        "factor whose validation points missed; or, for a cliff, threshold or "
        "multi-modal surface, use a method that does not assume a low-order "
        "model (the matched-budget benchmark, docs/benchmarks/"
        "optimization-benchmark.md, shows random search and GP-BO beat this "
        "kind on step, cubic and two-peak surfaces).",
    ]
