"""Deterministic ledger append for the Nous orchestrator.

Reads findings, bundle, and principles from a completed iteration and appends
a schema-conformant row to ledger.json.  No LLM calls — purely deterministic.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


def append_ledger_row(work_dir: Path, iteration: int) -> None:
    """Append a ledger row for the given iteration.

    Reads ``runs/iter-{iteration}/findings.json`` and ``bundle.yaml``,
    plus the top-level ``principles.json``, to build the row.

    If ``findings.json`` does not exist the call is a no-op (logged as
    warning) — this lets callers invoke it safely even on aborted iterations.
    """
    work_dir = Path(work_dir)
    iter_dir = work_dir / "runs" / f"iter-{iteration}"

    findings_path = iter_dir / "findings.json"
    if not findings_path.exists():
        logger.warning(
            "No findings.json for iteration %d — skipping ledger append.", iteration,
        )
        return

    findings = json.loads(findings_path.read_text())
    bundle = _read_bundle(iter_dir / "bundle.yaml")
    principles = _read_principles(work_dir / "principles.json")

    row = _build_row(iteration, findings, bundle, principles)

    ledger_path = work_dir / "ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
    else:
        ledger = {"iterations": []}

    # Idempotency guard: skip if this iteration already has a ledger row
    if any(r.get("iteration") == iteration for r in ledger["iterations"]):
        logger.info("Ledger row for iteration %d already exists — skipping.", iteration)
        return

    ledger["iterations"].append(row)
    atomic_write(ledger_path, json.dumps(ledger, indent=2) + "\n")
    logger.info("Appended ledger row for iteration %d.", iteration)


def _read_bundle(path: Path) -> dict:
    if not path.exists():
        logger.warning("No bundle.yaml at %s — ledger row will use family='unknown'.", path)
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _read_principles(path: Path) -> dict:
    if not path.exists():
        logger.warning("No principles.json at %s — ledger row will have empty principles.", path)
        return {"principles": []}
    return json.loads(path.read_text())


def _build_row(
    iteration: int,
    findings: dict,
    bundle: dict,
    principles: dict,
) -> dict:
    family = bundle.get("metadata", {}).get("family", "unknown")
    arms = findings.get("arms", [])

    h_main_result = _find_arm_status(arms, "h-main")
    control_result = _find_arm_status(arms, "h-control-negative")
    robustness_result = _find_arm_status(arms, "h-robustness")
    ablation_results = _collect_ablation_results(arms)
    accuracy = _compute_accuracy(arms)
    extracted = _detect_principle_changes(principles, iteration)

    return {
        "iteration": iteration,
        "family": family,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "candidate_id": f"iter-{iteration}",
        "h_main_result": h_main_result,
        "ablation_results": ablation_results,
        "control_result": control_result,
        "robustness_result": robustness_result,
        "prediction_accuracy": accuracy,
        "principles_extracted": extracted,
        "frontier_update": None,
    }


def _find_arm_status(arms: list[dict], arm_type: str) -> str | None:
    """Return the status of the first arm matching *arm_type*, or None."""
    for arm in arms:
        if arm.get("arm_type") == arm_type:
            return arm.get("status")
    return None


def _collect_ablation_results(arms: list[dict]) -> dict[str, str]:
    """Collect ablation arm results keyed by component or index."""
    results: dict[str, str] = {}
    idx = 0
    for arm in arms:
        if arm.get("arm_type") == "h-ablation":
            key = arm.get("component", f"ablation-{idx}")
            status = arm.get("status", "REFUTED")
            results[key] = status
            idx += 1
    return results


def _compute_accuracy(arms: list[dict]) -> dict | None:
    """Compute prediction accuracy across all arms."""
    if not arms:
        return None
    total = len(arms)
    correct = sum(1 for a in arms if a.get("status") == "CONFIRMED")
    return {
        "arms_correct": correct,
        "arms_total": total,
        "accuracy_pct": round(100 * correct / total, 1),
    }


def _detect_principle_changes(
    principles: dict, iteration: int,
) -> list[dict]:
    """Detect which principles were added/changed in this iteration."""
    extracted: list[dict] = []
    for p in principles.get("principles", []):
        ext_iter = p.get("extraction_iteration")
        if ext_iter != iteration:
            continue
        status = p.get("status", "active")
        if status == "active":
            action = "INSERT"
        elif status == "updated":
            action = "UPDATE"
        elif status == "pruned":
            action = "PRUNE"
        else:
            action = "INSERT"
        extracted.append({"id": p.get("id", "unknown"), "action": action})
    return extracted
