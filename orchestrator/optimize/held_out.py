"""What the held-out metrics say about the configurations the report names.

Why this module exists
----------------------
``response.held_out`` is the campaign's generalization check: metrics recorded
on every row but structurally split off the response (``runner._split_held_out``)
so no fitting, ranking, or certification input can ever read them. That split
is enforced. What was missing is the other half -- READING them. The values
sat in ``runs.jsonl`` and no artifact summarised them, so a campaign that
declared a held-out metric and one that did not produced the same report. The
first end-to-end campaign of this kind showed exactly that.

This is a pure read, after every decision is made: ``report.json`` is written
from the ladder first, and this summary is attached beside it. It decides
nothing and feeds nothing -- that is what keeps it a held-out check rather
than a second objective. For each configuration the report names (the
recommendation, then each finalist) it gives the held-out mean over the
epoch's ``complete`` rows at exactly those levels, and the primary metric's
mean over the SAME rows, so a reader can compare the two on equal footing.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean


def _rows(work_dir: Path, iterations) -> list[dict]:
    out: list[dict] = []
    for it in sorted(iterations):
        path = Path(work_dir) / "runs" / f"iter-{it}" / "runs.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _summarise(rows: list[dict], levels: dict, metrics: list[str],
               primary: str) -> dict:
    at = [r for r in rows
          if r.get("status") == "complete" and r.get("levels") == levels]
    entry: dict = {"levels": dict(levels), "n_rows": len(at), "metrics": {}}
    for m in metrics:
        pairs = [(r["held_out"][m], (r.get("response") or {}).get(primary))
                 for r in at if _numeric((r.get("held_out") or {}).get(m))]
        held = [h for h, _ in pairs]
        prim = [p for _, p in pairs if _numeric(p)]
        entry["metrics"][m] = {
            "n": len(held),
            "mean": fmean(held) if held else None,
            "primary_mean_same_rows": fmean(prim) if prim else None,
        }
    return entry


def held_out_summary(work_dir: Path, *, iterations, held_out: list[str],
                     primary: str, recommendation: dict,
                     finalists: list[dict]) -> dict | None:
    """The ``report.json`` ``held_out`` block, or None when none is declared."""
    metrics = [str(m) for m in (held_out or [])]
    if not metrics:
        return None
    rows = _rows(work_dir, iterations)
    out = {
        "metrics": metrics,
        "recommendation": _summarise(rows, recommendation or {}, metrics, primary),
        "finalists": [],
    }
    for f in finalists or []:
        lv = f.get("levels") if isinstance(f, dict) else None
        if isinstance(lv, dict):
            out["finalists"].append(
                {"key": f.get("key"), **_summarise(rows, lv, metrics, primary)})
    return out
