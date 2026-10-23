"""Nous v2 final answer check (spec 3.8).

Checks answer.json against the on-disk record after REPORT.
No LLM calls.  No re-running experiments by default.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .validators import ValidatorContext, campaign_record, read_json, validate_artifact

logger = logging.getLogger(__name__)


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


_SETUP = re.compile(r"^(export|cd)(\s|$)")
_ASSIGN = re.compile(r"^([A-Za-z_]\w*=\S*\s*)+")
_REDIRECT = re.compile(r"\s+(\d*>>?(&\d+|\s*\S+)|<\s*\S+)")


def _normalize(command: str) -> list[str]:
    """Split on ; and &&, drop export/cd segments and VAR=val prefixes, strip pipes and redirections."""
    out = []
    for seg in re.split(r";|&&", command):
        seg = _REDIRECT.sub("", seg.split("|", 1)[0])
        seg = _ASSIGN.sub("", " ".join(seg.split()))
        if seg and not _SETUP.match(seg):
            out.append(seg)
    return out


def _check_repro(work_dir: Path, repro_command: str | None) -> bool:
    """True if runs.jsonl has a successful run of the (normalized) repro command."""
    wanted = _normalize(repro_command or "")
    if not wanted:
        return False
    jsonl_path = work_dir / "runs.jsonl"
    if not jsonl_path.exists():
        return False
    for n, line in enumerate(jsonl_path.read_text().splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("%s:%d: skipping malformed row", jsonl_path, n)
            continue
        if entry.get("exit_code") == 0 and set(wanted) <= set(
            _normalize(entry.get("command") or "")
        ):
            return True
    return False


def _claims_matched_fraction(
    findings_list: list[dict],
    claims_needed: list[dict],
) -> float:
    """Fraction of claims_needed ids addressed by findings' claims."""
    if not claims_needed:
        return 1.0
    needed_ids = {c.get("id") for c in claims_needed if isinstance(c.get("id"), str)}
    addressed: set[str] = set()
    for hyp in findings_list:
        for claim in hyp.get("claims", []):
            cid = claim.get("claim_id")
            if isinstance(cid, str) and cid in needed_ids:
                addressed.add(cid)
    return len(addressed) / len(needed_ids)


def _find_unmeasured_noise(findings_list: list[dict]) -> list[str]:
    """Return hypothesis ids that have noise_unmeasured=true."""
    return [
        h.get("id", "<unknown>")
        for h in findings_list
        if h.get("noise_unmeasured") is True
    ]


def check_answer(work_dir: Path, limits: dict | None = None) -> dict:
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

    answer = read_json(work_dir / "answer.json")
    if answer is None:
        return report

    ctx = ValidatorContext(work_dir=work_dir, **(limits or {}))
    evidence_errors = validate_artifact("answer", answer, ctx)  # includes each claim's evidence
    report["evidence_errors"] = evidence_errors
    report["answer_valid"] = len(evidence_errors) == 0

    repro_cmd = answer.get("repro")
    if not repro_cmd:
        baseline = read_json(work_dir / "baseline.json")
        repro_cmd = baseline.get("command") if baseline else None
    report["repro_recorded"] = _check_repro(work_dir, repro_cmd)

    iter_dir = _find_latest_iter_dir(work_dir)
    if iter_dir:
        # claims_needed are append-only; a claim answered in any iteration stays answered
        claims_needed, all_hyps = campaign_record(work_dir)
        report["claims_matched_fraction"] = _claims_matched_fraction(all_hyps, claims_needed)
        findings = read_json(iter_dir / "findings.json")
        hypotheses = findings.get("hypotheses", []) if isinstance(findings, dict) else []
        report["unmeasured_noise_findings"] = _find_unmeasured_noise(hypotheses)

    return report
