"""Nous v2 artifact validators (spec 3.4).

Every public function returns a ``list[str]`` of error messages; an empty
list means the artifact is valid.  Validators never raise on validation
failure.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from .secrets import check_secrets

logger = logging.getLogger(__name__)

# ── Schema directory ─────────────────────────────────────────────────────

_SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

_SCHEMA_MAP: dict[str, str] = {
    "baseline": "baseline.schema.json",
    "problem": "problem.schema.json",
    "bundle": "bundle.schema.json",
    "plan": "plan.schema.json",
    "findings": "findings.schema.json",
    "principle_updates": "principle_updates.schema.json",
    "answer": "answer.schema.json",
    "ledger_entry": "ledger_entry.schema.json",
}


def _load_schema(name: str) -> dict:
    path = _SCHEMAS_DIR / _SCHEMA_MAP[name]
    return json.loads(path.read_text())


# ── Context ──────────────────────────────────────────────────────────────


@dataclass
class ValidatorContext:
    """Carries campaign/iteration context needed by semantic validators."""

    work_dir: Path
    iter_dir: Path | None = None
    locked_parameters: dict | None = None
    locked_workload: dict | None = None
    task_limits: dict | None = None
    secrets: dict[str, str] | None = None
    bundle_hypotheses: list[dict] | None = None
    claims_needed: list[dict] | None = None
    runs_jsonl: Path | None = None


# ── Extra-field handling (B5) ────────────────────────────────────────────


def _move_extras(data: dict, schema: dict) -> list[str]:
    """Move unknown top-level keys into ``data["extra"]``.

    Returns a list of warning strings for each moved key.
    """
    known = set(schema.get("properties", {}).keys())
    unknown = [k for k in list(data.keys()) if k not in known]
    warnings: list[str] = []
    if unknown:
        extra = data.setdefault("extra", {})
        for key in unknown:
            extra[key] = data.pop(key)
            warnings.append(f"unknown key {key!r} moved to extra")
        logger.warning("Moved unknown keys to extra: %s", unknown)
    return warnings


# ── Evidence checking (3.4) ──────────────────────────────────────────────


_JSON_EXTENSIONS = {".json"}
_JSONL_EXTENSIONS = {".jsonl"}
_CSV_EXTENSIONS = {".csv"}
_TSV_EXTENSIONS = {".tsv"}
_EVIDENCE_EXTENSIONS = _JSON_EXTENSIONS | _JSONL_EXTENSIONS | _CSV_EXTENSIONS | _TSV_EXTENSIONS


def _resolve_json_pointer(doc: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer against *doc*.

    Raises ``KeyError`` or ``IndexError`` on miss.
    """
    if pointer == "" or pointer == "/":
        return doc
    if not pointer.startswith("/"):
        raise KeyError(f"invalid JSON pointer: {pointer!r}")
    parts = pointer.lstrip("/").split("/")
    current = doc
    for part in parts:
        # RFC 6901 escapes
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(f"cannot descend into {type(current).__name__}")
    return current


def _values_match(expected: Any, actual: Any) -> bool:
    """Compare two values with tolerance for numbers, exact for strings."""
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(expected, actual, rel_tol=1e-3, abs_tol=1e-9)
    return expected == actual


def check_evidence_item(item: dict, base_dir: Path) -> list[str]:
    """Validate a single evidence item ``{path, key, value}``."""
    errors: list[str] = []
    path_str = item.get("path", "")
    key = item.get("key", "")
    value = item.get("value")

    evidence_path = base_dir / path_str
    if not evidence_path.exists():
        errors.append(f"evidence path does not exist: {path_str}")
        return errors

    suffix = evidence_path.suffix.lower()
    try:
        if suffix in _JSON_EXTENSIONS:
            doc = json.loads(evidence_path.read_text())
            actual = _resolve_json_pointer(doc, key)
            if not _values_match(value, actual):
                errors.append(
                    f"evidence value mismatch at {path_str}#{key}: "
                    f"expected {value!r}, got {actual!r}"
                )
        elif suffix in _JSONL_EXTENSIONS:
            # key format: line_number@pointer
            m = re.match(r"^(\d+)@(.*)$", key)
            if not m:
                errors.append(
                    f"invalid JSONL key format {key!r} "
                    "(expected line_number@pointer)"
                )
                return errors
            line_no = int(m.group(1))
            pointer = m.group(2)
            lines = evidence_path.read_text().strip().splitlines()
            if line_no < 0 or line_no >= len(lines):
                errors.append(
                    f"JSONL line {line_no} out of range "
                    f"(file has {len(lines)} lines)"
                )
                return errors
            doc = json.loads(lines[line_no])
            actual = _resolve_json_pointer(doc, pointer)
            if not _values_match(value, actual):
                errors.append(
                    f"evidence value mismatch at {path_str}#"
                    f"{key}: expected {value!r}, got {actual!r}"
                )
        elif suffix in _CSV_EXTENSIONS | _TSV_EXTENSIONS:
            # key format: column@row_index
            m = re.match(r"^(.+)@(\d+)$", key)
            if not m:
                errors.append(
                    f"invalid CSV/TSV key format {key!r} "
                    "(expected column@row_index)"
                )
                return errors
            column = m.group(1)
            row_idx = int(m.group(2))
            delimiter = "\t" if suffix in _TSV_EXTENSIONS else ","
            with open(evidence_path, newline="") as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                rows = list(reader)
            if row_idx < 0 or row_idx >= len(rows):
                errors.append(
                    f"CSV/TSV row {row_idx} out of range "
                    f"(file has {len(rows)} data rows)"
                )
                return errors
            if column not in rows[row_idx]:
                errors.append(
                    f"CSV/TSV column {column!r} not found in {path_str}"
                )
                return errors
            cell = rows[row_idx][column]
            # Try numeric comparison first
            try:
                cell_num = float(cell)
                if isinstance(value, (int, float)):
                    if not _values_match(value, cell_num):
                        errors.append(
                            f"evidence value mismatch at {path_str}#"
                            f"{key}: expected {value!r}, got {cell_num!r}"
                        )
                elif not _values_match(value, cell):
                    errors.append(
                        f"evidence value mismatch at {path_str}#"
                        f"{key}: expected {value!r}, got {cell!r}"
                    )
            except ValueError:
                if not _values_match(value, cell):
                    errors.append(
                        f"evidence value mismatch at {path_str}#"
                        f"{key}: expected {value!r}, got {cell!r}"
                    )
        else:
            # Plain text: key is a regex whose group 1 is the value
            text = evidence_path.read_text()
            match = re.search(key, text)
            if not match:
                errors.append(
                    f"evidence regex {key!r} not found in {path_str}"
                )
                return errors
            if match.lastindex and match.lastindex >= 1:
                actual = match.group(1)
                if not _values_match(value, actual):
                    errors.append(
                        f"evidence value mismatch at {path_str}#"
                        f"{key}: expected {value!r}, got {actual!r}"
                    )
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        errors.append(f"evidence lookup failed for {path_str}#{key}: {exc}")

    return errors


# ── Per-artifact semantic checks ─────────────────────────────────────────


def _check_noise_schema(noise: dict) -> list[str]:
    """Validate the noise sub-object against one of the three allowed forms."""
    errors: list[str] = []
    if "deterministic" in noise:
        if noise.get("deterministic") is not True:
            errors.append("noise.deterministic must be true")
    elif "unmeasured" in noise:
        if noise.get("unmeasured") is not True:
            errors.append("noise.unmeasured must be true")
        if "reason" not in noise:
            errors.append("noise with unmeasured=true requires 'reason'")
    elif "seeds" in noise:
        for field_name in ("seeds", "values", "sd"):
            if field_name not in noise:
                errors.append(f"measured noise requires '{field_name}'")
    else:
        errors.append(
            "noise must be one of: {seeds,values,sd}, "
            "{deterministic:true}, {unmeasured:true,reason}"
        )
    return errors


def _check_bundle_semantics(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check bundle-specific rules beyond JSON Schema."""
    errors: list[str] = []
    hypotheses = data.get("hypotheses", [])

    # At least 2 distinct families OR single_family_reason
    families = {h.get("family") for h in hypotheses}
    if len(families) < 2 and not data.get("single_family_reason"):
        errors.append(
            "bundle requires at least 2 distinct family values "
            "or a non-empty single_family_reason"
        )

    # Each hypothesis must have control or no_control_reason
    for h in hypotheses:
        if not h.get("control") and not h.get("no_control_reason"):
            errors.append(
                f"hypothesis {h.get('id')!r} requires 'control' or "
                "'no_control_reason'"
            )

    # claims_needed coverage
    if ctx.claims_needed:
        needed_ids = {c["id"] for c in ctx.claims_needed}
        covered = set()
        for h in hypotheses:
            covered.update(h.get("claim_ids", []))
        missing = needed_ids - covered
        if missing:
            errors.append(
                f"claims_needed ids not covered by any hypothesis: "
                f"{sorted(missing)}"
            )

    return errors


def _check_plan_semantics(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check plan-specific rules beyond JSON Schema."""
    errors: list[str] = []
    runs = data.get("runs", [])

    # Paired-seed check: for each hypothesis with a control,
    # treatment and control runs must use the same seeds
    if ctx.bundle_hypotheses:
        hyps_with_control = {
            h["id"] for h in ctx.bundle_hypotheses if h.get("control")
        }
        # Group runs by hypothesis_id
        by_hyp: dict[str, dict[str, list]] = {}
        for run in runs:
            hid = run.get("hypothesis_id", "")
            role = run.get("role", "")
            by_hyp.setdefault(hid, {}).setdefault(role, []).append(run)

        for hid in hyps_with_control:
            groups = by_hyp.get(hid, {})
            treatment_runs = groups.get("treatment", [])
            control_runs = groups.get("control", [])
            if treatment_runs and control_runs:
                t_seeds = sorted(treatment_runs[0].get("seeds", []))
                c_seeds = sorted(control_runs[0].get("seeds", []))
                if t_seeds != c_seeds:
                    errors.append(
                        f"hypothesis {hid!r}: treatment and control "
                        "runs must use the same seeds (paired comparison)"
                    )

    # locked_parameters check
    if ctx.locked_parameters:
        for run in runs:
            params = run.get("parameters", {})
            wl_changes = set(run.get("workload_changes", []))
            for key, locked_val in ctx.locked_parameters.items():
                if key in params and key not in wl_changes:
                    if params[key] != locked_val:
                        errors.append(
                            f"run {run.get('id')!r}: parameter {key!r} "
                            f"deviates from locked value {locked_val!r} "
                            f"(got {params[key]!r}) without workload_changes "
                            "declaration"
                        )

    # locked_workload check
    if ctx.locked_workload:
        for run in runs:
            params = run.get("parameters", {})
            wl_changes = set(run.get("workload_changes", []))
            for key, locked_val in ctx.locked_workload.items():
                if key in params and key not in wl_changes:
                    if params[key] != locked_val:
                        errors.append(
                            f"run {run.get('id')!r}: workload parameter "
                            f"{key!r} deviates from locked value "
                            f"{locked_val!r} (got {params[key]!r}) without "
                            "workload_changes declaration"
                        )

    return errors


def _check_findings_semantics(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check findings-specific rules beyond JSON Schema."""
    errors: list[str] = []

    for h in data.get("hypotheses", []):
        hid = h.get("id", "?")
        status = h.get("status", "")

        # PARTIALLY_CONFIRMED requires partial_note
        if status == "PARTIALLY_CONFIRMED" and not h.get("partial_note"):
            errors.append(
                f"hypothesis {hid!r}: PARTIALLY_CONFIRMED requires "
                "'partial_note'"
            )

        # Noise honesty: CONFIRMED/REFUTED must show effect > 2x noise
        # or carry noise_unmeasured
        if status in ("CONFIRMED", "REFUTED"):
            has_noise_sd = "noise_sd" in h
            has_unmeasured = h.get("noise_unmeasured") is True
            if not has_noise_sd and not has_unmeasured:
                errors.append(
                    f"hypothesis {hid!r}: {status} requires either "
                    "'noise_sd' or 'noise_unmeasured: true'"
                )

        # Evidence path checks
        base_dir = ctx.iter_dir or ctx.work_dir
        for ev in h.get("evidence", []):
            errors.extend(check_evidence_item(ev, base_dir))

    return errors


def _check_principle_updates_semantics(
    data: dict, ctx: ValidatorContext
) -> list[str]:
    """Check that finding_ref values are valid hypothesis ids."""
    errors: list[str] = []
    if ctx.bundle_hypotheses:
        known_ids = {h["id"] for h in ctx.bundle_hypotheses}
        for upd in data.get("updates", []):
            ref = upd.get("finding_ref", "")
            if ref not in known_ids:
                errors.append(
                    f"principle update {upd.get('id')!r}: finding_ref "
                    f"{ref!r} is not a known hypothesis id"
                )
    return errors


def _check_answer_semantics(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check answer-specific rules."""
    errors: list[str] = []

    # Evidence checks on claims
    base_dir = ctx.work_dir
    for claim in data.get("claims", []):
        ev = claim.get("evidence")
        if ev:
            errors.extend(check_evidence_item(ev, base_dir))

    # Secret check: answer must not contain literal secret values
    if ctx.secrets:
        for field_name in ("answer", "deliverable", "repro"):
            text = data.get(field_name, "")
            leaked = check_secrets(text, ctx.secrets)
            for name in leaked:
                errors.append(
                    f"answer.{field_name} contains secret {name!r}"
                )

    return errors


def _check_task_limits(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check task_limits (B11) against runs.jsonl if available."""
    errors: list[str] = []
    if not ctx.task_limits or not ctx.runs_jsonl:
        return errors
    if not ctx.runs_jsonl.exists():
        return errors

    lines = ctx.runs_jsonl.read_text().strip().splitlines()
    run_count = len(lines)

    max_runs = ctx.task_limits.get("max_runs")
    if max_runs is not None and run_count > max_runs:
        errors.append(
            f"task_limits: {run_count} runs exceeds max_runs={max_runs}"
        )

    # Check total wall time if present
    max_wall_s = ctx.task_limits.get("max_wall_seconds")
    if max_wall_s is not None:
        total_wall = 0.0
        for line in lines:
            try:
                entry = json.loads(line)
                total_wall += entry.get("wall_seconds", 0)
            except json.JSONDecodeError:
                pass
        if total_wall > max_wall_s:
            errors.append(
                f"task_limits: total wall time {total_wall:.1f}s "
                f"exceeds max_wall_seconds={max_wall_s}"
            )

    return errors


# ── Bundle hash ──────────────────────────────────────────────────────────


def bundle_hash(data: dict) -> str:
    """Compute sha256 hash of a bundle for the ledger's bundle_hash field."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Public API ───────────────────────────────────────────────────────────

# Dispatch table: artifact_type -> (has_semantic_check_fn or None)
_SEMANTIC_CHECKS: dict[str, Any] = {
    "baseline": None,
    "problem": None,
    "bundle": _check_bundle_semantics,
    "plan": _check_plan_semantics,
    "findings": _check_findings_semantics,
    "principle_updates": _check_principle_updates_semantics,
    "answer": _check_answer_semantics,
    "ledger_entry": None,
}


def validate_artifact(
    artifact_type: str,
    data: dict,
    context: ValidatorContext,
) -> list[str]:
    """Validate a v2 artifact.  Returns list of error strings (empty = valid).

    Moves unknown top-level keys to ``data["extra"]`` before schema check.
    """
    if artifact_type not in _SCHEMA_MAP:
        return [f"unknown artifact type: {artifact_type!r}"]

    errors: list[str] = []

    # B5: move unknown keys to extra
    schema = _load_schema(artifact_type)
    warnings = _move_extras(data, schema)
    errors.extend(warnings)

    # JSON Schema validation
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        errors.append(f"schema: {exc.message}")
        # Return early on schema failure; semantic checks assume valid shape
        return errors

    # Noise sub-schema validation for baseline
    if artifact_type == "baseline":
        noise = data.get("noise", {})
        errors.extend(_check_noise_schema(noise))

    # Semantic checks
    check_fn = _SEMANTIC_CHECKS.get(artifact_type)
    if check_fn is not None:
        errors.extend(check_fn(data, context))

    # Task limits (B11) for findings
    if artifact_type == "findings":
        errors.extend(_check_task_limits(data, context))

    return errors
