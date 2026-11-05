"""The agent's notebook (notebook.jsonl): hypotheses before tests, results with evidence.

Pure Python, no LLM. Checked once, when the agent tries to finish.
"""

from __future__ import annotations

import json
from pathlib import Path

from .validators import check_evidence_item

KINDS = ("hypothesis", "result", "note")
STATUSES = ("confirmed", "refuted", "inconclusive")


def read_notebook(work_dir: Path) -> tuple[list[dict], list[str]]:
    """(entries in order, errors for unreadable lines)."""
    path = work_dir / "notebook.jsonl"
    if not path.is_file():
        return [], []
    entries, errors = [], []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"notebook line {n}: not JSON")
            continue
        if isinstance(e, dict):
            e["_line"] = n
            entries.append(e)
        else:
            errors.append(f"notebook line {n}: not a JSON object")
    return entries, errors


def check_notebook(work_dir: Path, repo_dir: Path | None = None) -> list[str]:
    """Errors in the notebook: unknown kinds, results without an earlier hypothesis, results whose
    evidence does not check out. An empty notebook has no errors (it is reported, not required)."""
    entries, errors = read_notebook(work_dir)
    hypothesised: set = set()
    latest: dict = {}  # id -> its last result entry; a rerun appends a new result, older ones are history
    for e in entries:
        kind, n = e.get("kind"), e["_line"]
        if kind not in KINDS:
            errors.append(f"notebook line {n}: kind must be one of {list(KINDS)}")
        elif not isinstance(e.get("id"), (str, type(None))):
            errors.append(f"notebook line {n}: `id` must be a string")
        elif kind == "hypothesis":
            if not e.get("id") or not e.get("predict"):
                errors.append(f"notebook line {n}: a hypothesis needs `id` and `predict`")
            hypothesised.add(e.get("id"))
        elif kind == "result":
            if e.get("id") not in hypothesised:
                errors.append(f"notebook line {n}: result {e.get('id')!r} has no earlier hypothesis entry")
            latest[e.get("id")] = e
    for e in latest.values():
        n = e["_line"]
        if e.get("status") not in STATUSES:
            errors.append(f"notebook line {n}: status must be one of {list(STATUSES)}")
        evidence = e.get("evidence") or []
        if e.get("status") in ("confirmed", "refuted") and not evidence:
            errors.append(f"notebook line {n}: a {e.get('status')} result needs `evidence`")
        for ev in evidence if isinstance(evidence, list) else [evidence]:
            if not isinstance(ev, dict) or not isinstance(ev.get("path", ""), str):
                errors.append(f"notebook line {n}: evidence item must be an object with a string `path`, "
                              f"got {ev!r}")
                continue
            errors.extend(f"notebook line {n}: {x}" for x in check_evidence_item(ev, work_dir, repo_dir))
    return errors


def summary(work_dir: Path) -> dict:
    """Counts for the record: hypotheses, results by status."""
    entries, _ = read_notebook(work_dir)
    out = {"hypotheses": 0, "confirmed": 0, "refuted": 0, "inconclusive": 0, "notes": 0}
    for e in entries:
        k = e.get("kind")
        if k == "hypothesis":
            out["hypotheses"] += 1
        elif k == "note":
            out["notes"] += 1
        elif k == "result" and e.get("status") in STATUSES:
            out[e["status"]] += 1
    return out
