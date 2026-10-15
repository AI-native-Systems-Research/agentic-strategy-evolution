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
    "model_inadequate": "the fit behind the shortlist failed its lack-of-fit "
                        "test, so nothing supports the claim that screening "
                        "did not exclude the optimum",
    "no_terminal_discrimination": "no terminal discrimination ran",
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
    import glob
    import math

    import yaml

    from orchestrator.optimize.factors import _from_axis, _to_axis, parse_factors

    recs = sorted(glob.glob(str(work_dir / "runs" / "iter-*" / "recommendation.json")),
                  key=lambda p: int(Path(p).parent.name.split("-")[1]))
    sp = (_read_json(Path(recs[-1])) or {}).get("stationary_point") if recs else None
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
    rows = []
    for rj in glob.glob(str(work_dir / "runs" / "iter-*" / "runs.jsonl")):
        for line in Path(rj).read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue

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
        if n_at and n_bad == n_at:
            out.append(
                f"- **{fid}**: the PRIMARY surface keeps rising past {edge}, but "
                f"all {n_at} row(s) measured at {fid}={edge} were infeasible: the "
                f"constrained optimum lies inside the declared range. Do not "
                f"extend `{fid}`; if anything, add interior levels below {edge}."
            )
            continue
        out.append(
            f"- **{fid}**: the fitted optimum is at about "
            f"{_fmt(_from_axis(f, mid + coded * half))} (coded {coded:+.2f}), "
            f"{side} the declared range {list(f.levels)}. Extend `{fid}`'s levels "
            f"{'upward' if side == 'above' else 'downward'}, e.g. to about "
            f"{_fmt(suggest)}."
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
        f"- **Value:** {_fmt(rec.get('value'))}",
        f"- **Basis:** `{basis}` — {BASIS_MEANING.get(basis, 'unknown rung')}",
        f"- **Certified:** {'yes' if report.get('certified') else 'no'}",
    ]
    withheld = report.get("certification_withheld") or []
    if withheld and not report.get("certified"):
        lines.append("- **Certification withheld because:** " + "; ".join(
            f"`{r}` ({WITHHELD_MEANING.get(r, 'unrecognised reason')})"
            for r in withheld))
    lines.append("")
    if report.get("epoch_ended"):
        lines += [
            f"> **The epoch ended on a semantic exception:** "
            f"`{report['epoch_ended']}`. The `model` rung is suppressed because "
            f"the exception is evidence against the fitted surface; see "
            f"`epoch_end-{report.get('epoch')}.json`.",
            "",
        ]
        lines += _next_epoch_section(work_dir, report)

    lines += [
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
    if basis != "model":
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
        "",
        "_Rendered from `report.json` with no model call; `report.json` is the "
        "record of the answer._",
        "",
    ]
    return "\n".join(lines)


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
