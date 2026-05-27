"""Deterministic promotion-gate decision logic (#224 v1).

After an iteration completes, the engine needs a decision: promote to
the next iteration, revise (halt for operator action), or abort. Today
(post-#218) the engine has no such decision point — iterations run
linearly with no protection against (a) BLOCKING brief_amendments
that haven't been applied to the upstream brief, or (b) feasibility
failures that mean further iterations on this regime are wasted.

This module is the v1 decision-function. The caller — engine
state-machine integration is deferred to v2 — passes a work_dir +
iteration index and gets a structured decision back. Pure Python, no
LLM, no I/O beyond reading on-disk artifacts. Heuristics over
``findings.json``, ``brief_amendments.jsonl`` (#223), and
``applied_amendments.jsonl`` (the future apply-amendments CLI's
provenance log).

**v1 scope:**

- Function returns a structured dict; engine integration is the v2
  concern. This lets the decision logic be tested in isolation
  before any state-machine changes land.
- Decision rule:
   1. ``findings.json`` missing OR ``experiment_valid: false`` → ``abort``
   2. Any unapplied amendment with ``priority: "BLOCKING"`` → ``revise``
   3. else → ``promote``
- Auto-approve interaction (the ``summarize-gate`` LLM-driven override)
  is out of v1 scope. The deterministic decision is the source of
  truth; auto-approve in v2 just rubber-stamps it.

Per CLAUDE.md test discipline (no live LLM calls): this module is pure
Python and trivially testable with synthesized inputs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal


Decision = Literal["promote", "revise", "abort"]

VALID_DECISIONS: tuple[Decision, ...] = ("promote", "revise", "abort")


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file; skip malformed lines silently."""
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        text = path.read_text()
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def evaluate_promote_gate(
    work_dir: Path,
    iteration: int,
) -> dict:
    """Decide whether to promote, revise, or abort after iteration N.

    Returns a structured dict: ``{decision, reasoning, blocking_amendments,
    applied_amendments, feasibility_check}``.

    Decision rule (deterministic; pure Python):
        1. ``runs/iter-N/findings.json`` missing → ``abort``
           ("no apparatus output to evaluate; iteration didn't reach
           the analysis phase").
        2. ``findings.experiment_valid == false`` → ``abort``
           ("the apparatus failed; no scientific signal").
        3. Any ``brief_amendments.jsonl`` row with ``priority:
           BLOCKING`` whose ``id`` is NOT in
           ``<work_dir>/applied_amendments.jsonl`` → ``revise``
           ("blocking amendment must be applied to the brief before
           iter-(N+1) can produce valid data").
        4. Otherwise → ``promote``.

    Engine integration (v2): the engine calls this between iterations
    and acts on ``decision``: ``promote`` → start iter-(N+1),
    ``revise`` → halt with ``CampaignStopped("revise")`` so the operator
    can run ``nous brief apply-amendments``, ``abort`` → halt with
    ``CampaignStopped("abort")``.
    """
    work_dir = Path(work_dir)
    iter_dir = work_dir / "runs" / f"iter-{iteration}"

    # 1+2. Findings.json gate.
    findings = _read_json(iter_dir / "findings.json")
    if not isinstance(findings, dict):
        return _decision(
            "abort",
            reasoning=(
                f"runs/iter-{iteration}/findings.json missing or "
                f"unreadable; the iteration did not reach the analysis "
                f"phase (or analysis failed before writing findings). "
                f"Cannot promote without a scientific outcome."
            ),
            blocking=[],
            applied=[],
            feasibility=False,
        )
    if findings.get("experiment_valid") is False:
        return _decision(
            "abort",
            reasoning=(
                f"runs/iter-{iteration}/findings.json reports "
                f"experiment_valid=false; the apparatus failed. "
                f"Iter-{iteration + 1} won't fix this — operator must "
                f"revise the campaign before any further iteration."
            ),
            blocking=[],
            applied=[],
            feasibility=False,
        )

    # 3. Brief-amendments gate.
    amendments = _read_jsonl(iter_dir / "inputs" / "brief_amendments.jsonl")
    applied_rows = _read_jsonl(work_dir / "applied_amendments.jsonl")
    applied_ids = {
        str(r.get("id"))
        for r in applied_rows
        if isinstance(r, dict) and r.get("id")
    }
    blocking_unapplied = [
        a for a in amendments
        if isinstance(a, dict)
        and a.get("priority") == "BLOCKING"
        and a.get("id") not in applied_ids
    ]
    if blocking_unapplied:
        ids = ", ".join(
            str(a.get("id", "?")) for a in blocking_unapplied[:5]
        )
        if len(blocking_unapplied) > 5:
            ids += f", ... and {len(blocking_unapplied) - 5} more"
        return _decision(
            "revise",
            reasoning=(
                f"{len(blocking_unapplied)} BLOCKING brief_amendment(s) "
                f"({ids}) have not been applied to the upstream brief. "
                f"Iter-{iteration + 1} would re-discover or re-trip "
                f"these issues. Run `nous brief apply-amendments` (post-#223 "
                f"v2) or apply manually, then resume."
            ),
            blocking=[str(a.get("id", "?")) for a in blocking_unapplied],
            applied=sorted(applied_ids),
            feasibility=True,
        )

    # 4. Default → promote.
    return _decision(
        "promote",
        reasoning=(
            f"iter-{iteration} produced valid findings and no BLOCKING "
            f"brief_amendments are pending. Iter-{iteration + 1} can "
            f"proceed."
        ),
        blocking=[],
        applied=sorted(applied_ids),
        feasibility=True,
    )


def _decision(
    decision: Decision,
    *,
    reasoning: str,
    blocking: list[str],
    applied: list[str],
    feasibility: bool,
) -> dict:
    """Build the result dict in the canonical shape."""
    return {
        "decision": decision,
        "reasoning": reasoning,
        "blocking_amendments": blocking,
        "applied_amendments": applied,
        "feasibility_check": {
            "passed": feasibility,
        },
    }
