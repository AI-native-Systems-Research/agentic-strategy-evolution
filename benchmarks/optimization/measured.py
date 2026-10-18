"""The ONE measured-row counter every benchmark arm uses (P7 review M5).

A Nous campaign's budget is its count of FRESH measurements. Two kinds of row
in ``runs/iter-*/runs.jsonl`` are copies, not measurements, and both carry
``reused_from``:

* a stage copy -- refine filling a design point from a measured screen row
  (WP-B B4, ``reused_from.stage``);
* an iteration copy -- a resumed iteration carrying a row forward from the
  attempt that measured it (``resume``), whose source row is still on disk in
  its own iteration directory.

Counting either would charge one measurement twice. Every path -- a finished
campaign, a crashed one, single- and multi-objective -- counts through
``measured_rows``, so they cannot disagree.
"""
from __future__ import annotations

import json
from pathlib import Path


def _iter_dirs(work_dir: Path) -> list[Path]:
    runs = Path(work_dir) / "runs"
    if not runs.exists():
        return []
    dirs = [d for d in runs.iterdir() if d.name.startswith("iter-")]
    return sorted(dirs, key=lambda d: int(d.name.split("-")[1]))


def measured_rows(work_dir) -> list[dict]:
    """Every fresh measurement of the campaign at ``work_dir``, in execution
    order (iteration, then row order within ``runs.jsonl``)."""
    out = []
    for it in _iter_dirs(Path(work_dir)):
        p = it / "runs.jsonl"
        if not p.exists():
            continue
        for ln in p.read_text().splitlines():
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue  # a torn last line from a crash
            if not r.get("reused_from"):
                out.append(r)
    return out


def spent_under(parent) -> int:
    """Fresh measurements of every campaign work_dir under ``parent`` (the
    crash path: the campaign's own work_dir is not known)."""
    return sum(len(measured_rows(w)) for w in sorted(Path(parent).glob("*"))
               if (w / "runs").is_dir())
