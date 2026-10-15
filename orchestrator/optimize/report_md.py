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
    "finalist_unmeasured": "a finalist produced no usable measurement, so the "
                           "shortlist was never fully compared -- re-run it",
    "fit_exclusions_level_correlated": "the fit behind the shortlist lost rows "
                                       "correlated with factor levels",
    "no_terminal_discrimination": "no terminal discrimination ran",
}


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

    lines += [
        "## Bounds",
        "",
        "| quantity | value |",
        "|---|---|",
        f"| epsilon (acceptable regret) | {_fmt(report.get('epsilon'))} |",
        f"| residual regret, model | {_fmt(report.get('residual_regret_model'))} |",
        f"| residual regret, terminal | {_fmt(report.get('residual_regret_terminal'))} |",
        f"| delta, screen | {_fmt(report.get('delta_screen'))} |",
        f"| delta, terminal | {_fmt(report.get('delta_terminal'))} |",
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
