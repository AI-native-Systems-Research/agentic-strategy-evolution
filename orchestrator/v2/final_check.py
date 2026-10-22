"""Nous v2 final answer check (spec 3.8).

Checks answer.json against the on-disk record after REPORT.
No LLM calls.  No re-running experiments by default.
"""

from __future__ import annotations

import json
from pathlib import Path

from .validators import ValidatorContext, check_evidence_item, validate_artifact


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _find_latest_iter_dir(work_dir: Path) -> Path | None:
    """Find the highest-numbered runs/iter-N directory."""
    runs_dir = work_dir / "runs"
    if not runs_dir.exists():
        return None
    iters = sorted(
        (d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("iter-")),
        key=lambda d: int(d.name.split("-", 1)[1]),
    )
    return iters[-1] if iters else None


def _check_repro(work_dir: Path, repro_command: str | None) -> bool:
    """Check if the repro command appears in runs.jsonl."""
    if not repro_command:
        return False
    paths = [work_dir / "runs.jsonl"]
    runs_dir = work_dir / "runs"
    if runs_dir.exists():
        paths.extend(runs_dir.rglob("runs.jsonl"))
    for jsonl_path in paths:
        if not jsonl_path.exists():
            continue
        try:
            for line in jsonl_path.read_text().strip().splitlines():
                entry = json.loads(line)
                if entry.get("command") == repro_command:
                    return True
        except (json.JSONDecodeError, OSError):
            continue
    return False


def _claims_matched_fraction(
    findings_list: list[dict],
    claims_needed: list[dict],
) -> float:
    """Fraction of claims_needed ids addressed by findings' claims."""
    if not claims_needed:
        return 1.0
    needed_ids = {c.get("id") for c in claims_needed if c.get("id")}
    addressed: set[str] = set()
    for hyp in findings_list:
        for claim in hyp.get("claims", []):
            cid = claim.get("claim_id")
            if cid in needed_ids:
                addressed.add(cid)
    return len(addressed) / len(needed_ids)


def _find_unmeasured_noise(findings_list: list[dict]) -> list[str]:
    """Return hypothesis ids that have noise_unmeasured=true."""
    return [
        h.get("id", "<unknown>")
        for h in findings_list
        if h.get("noise_unmeasured") is True
    ]


def check_answer(work_dir: Path) -> dict:
    """Check answer.json against the on-disk record.

    Returns a report dict with answer_valid, evidence_errors,
    repro_recorded, claims_matched_fraction, unmeasured_noise_findings.
    """
    report: dict = {
        "answer_valid": False,
        "evidence_errors": [],
        "repro_recorded": False,
        "claims_matched_fraction": 0.0,
        "unmeasured_noise_findings": [],
    }

    answer = _read_json(work_dir / "answer.json")
    if answer is None:
        return report

    ctx = ValidatorContext(work_dir=work_dir)
    schema_errors = validate_artifact("answer", answer, ctx)
    if schema_errors:
        report["evidence_errors"] = schema_errors
        return report

    evidence_errors: list[str] = []
    for claim in answer.get("claims", []):
        ev = claim.get("evidence")
        if ev:
            evidence_errors.extend(check_evidence_item(ev, work_dir))
    report["evidence_errors"] = evidence_errors
    report["answer_valid"] = len(evidence_errors) == 0

    repro_cmd = answer.get("repro")
    if not repro_cmd:
        baseline = _read_json(work_dir / "baseline.json")
        repro_cmd = baseline.get("command") if baseline else None
    report["repro_recorded"] = _check_repro(work_dir, repro_cmd)

    iter_dir = _find_latest_iter_dir(work_dir)
    if iter_dir:
        findings = _read_json(iter_dir / "findings.json")
        problem = _read_json(iter_dir / "problem.json")

        hypotheses = findings.get("hypotheses", []) if findings else []
        claims_needed = problem.get("claims_needed", []) if problem else []

        report["claims_matched_fraction"] = _claims_matched_fraction(
            hypotheses, claims_needed,
        )
        report["unmeasured_noise_findings"] = _find_unmeasured_noise(hypotheses)

    return report
