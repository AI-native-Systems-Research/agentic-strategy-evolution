"""Deterministic constraint-principle generation from REFUTED arms (issue #169).

Audit of inference-sim ledgers (May 2026) shows campaigns like
``mech-design-kvtime`` (acc 25%/0%), ``fp-delay-frontier`` (acc 0%),
and ``sgsf-unification`` (REFUTED twice) walked away with no
deployable artifact and no recorded reason for the next iteration to
avoid the dead end. The engine itself doesn't have a REFUTE → DONE
shortcut — that's confirmed by the test in
``test_engine_search_continuation.py`` — but the *next* iteration's
designer also gets no help.

This module closes that gap: each REFUTED arm becomes a constraint
principle (``category=meta``) recorded in ``principles.json``, so
the next DESIGN reads "this mechanism was refuted in iter-N under
regime X" and can redirect search.

Pure deterministic Python — zero LLM tokens, idempotent, atomic write
to disk. The seam matches ``meta_findings.emit_meta_findings``: scan
on-disk artifacts, compute, write.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


def _constraint_id(iteration: int, arm_idx: int, arm_type: str) -> str:
    """Stable id: encodes iteration + arm index so re-runs collide
    with prior emissions and the existing_ids check skips duplicates."""
    return f"C-iter{iteration}-arm{arm_idx}-{arm_type}"


def _statement(arm: dict, family: str) -> str:
    arm_type = arm.get("arm_type", "?")
    predicted = (arm.get("predicted") or "").strip()
    # Statement is human-readable but starts with "Refuted:" so the
    # designer prompt can grep for it. Trim long predictions.
    head = f"Refuted: family={family!r}, arm_type={arm_type!r}"
    if predicted:
        snippet = predicted[:120].replace("\n", " ")
        if len(predicted) > 120:
            snippet += "…"
        return f"{head}. Prediction was: {snippet}"
    return head


def _applicability_bounds(arm: dict, family: str, iteration: int) -> str:
    """Capture where the mechanism failed: family + iteration + observed snippet."""
    observed = (arm.get("observed") or "").strip()
    snippet = observed[:120].replace("\n", " ")
    if len(observed) > 120:
        snippet += "…"
    if snippet:
        return (
            f"family={family!r}, iter-{iteration}; observed: {snippet}"
        )
    return f"family={family!r}, iter-{iteration}"


def make_constraints_from_findings(
    findings: dict,
    *,
    iteration: int,
    family: str,
    existing_ids: set[str] | None = None,
) -> list[dict]:
    """Return one constraint-principle dict per REFUTED arm.

    Args:
        findings: Parsed findings.json for the iteration.
        iteration: Iteration index (used in id + applicability_bounds).
        family: Mechanism family (used in statement + applicability_bounds).
        existing_ids: Set of constraint ids already in principles.json;
            constraints with these ids are skipped (idempotent re-run).

    Returns:
        List of new constraint principles, each conforming to
        principles.schema.json. ``status="active"``, ``category="meta"``.
    """
    existing = existing_ids or set()
    constraints: list[dict] = []

    arms = findings.get("arms") if isinstance(findings, dict) else None
    if not isinstance(arms, list):
        return constraints

    for idx, arm in enumerate(arms):
        if not isinstance(arm, dict):
            continue
        if arm.get("status") != "REFUTED":
            continue

        arm_type = str(arm.get("arm_type") or "?")
        cid = _constraint_id(iteration, idx, arm_type)
        if cid in existing:
            continue

        constraints.append({
            "id": cid,
            "statement": _statement(arm, family),
            "confidence": "high",
            "regime": f"family={family!r}",
            "evidence": [f"iter-{iteration}/findings.json arm {arm_type}"],
            "contradicts": [],
            "extraction_iteration": iteration,
            "mechanism": "",
            "applicability_bounds": _applicability_bounds(arm, family, iteration),
            "superseded_by": None,
            "status": "active",
            "category": "meta",
        })

    return constraints


def apply_refute_constraints(
    work_dir: Path,
    *,
    iteration: int,
    family: str,
) -> list[dict]:
    """End-to-end: read findings.json, generate constraints, merge into principles.json.

    Idempotent: re-running on the same iteration produces no
    duplicates (the existing_ids check sees the prior constraint ids
    and skips). Atomic write — never leaves principles.json
    half-written if interrupted.

    Args:
        work_dir: Campaign work dir (containing ``runs/iter-N/findings.json``
            and ``principles.json``).
        iteration: Which iteration's findings to read.
        family: Mechanism family for statement context.

    Returns:
        The new constraints inserted (empty list if findings missing
        or no REFUTED arms).
    """
    work_dir = Path(work_dir)

    findings_path = work_dir / "runs" / f"iter-{iteration}" / "findings.json"
    if not findings_path.exists():
        return []
    try:
        findings = json.loads(findings_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "apply_refute_constraints: cannot read %s: %s",
            findings_path, exc,
        )
        return []

    principles_path = work_dir / "principles.json"
    if principles_path.exists():
        try:
            store = json.loads(principles_path.read_text())
        except (OSError, json.JSONDecodeError):
            store = {"principles": []}
    else:
        store = {"principles": []}

    if not isinstance(store, dict) or not isinstance(
        store.get("principles"), list,
    ):
        store = {"principles": []}

    existing_ids: set[str] = {
        p["id"] for p in store["principles"]
        if isinstance(p, dict) and isinstance(p.get("id"), str)
    }
    new_constraints = make_constraints_from_findings(
        findings,
        iteration=iteration,
        family=family,
        existing_ids=existing_ids,
    )
    if not new_constraints:
        return []

    store["principles"] = list(store["principles"]) + new_constraints
    atomic_write(principles_path, json.dumps(store, indent=2) + "\n")
    return new_constraints
