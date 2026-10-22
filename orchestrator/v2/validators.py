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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .secrets import check_secrets

logger = logging.getLogger(__name__)


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


def read_json(path: Path) -> Any | None:
    """Parse JSON at *path*; None if missing, corrupt, or unreadable."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        logger.warning("corrupt or unreadable JSON in %s", path)
        return None


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


def iter_context(work_dir: Path, iter_dir: Path | None, **limits: Any) -> ValidatorContext:
    """Context with bundle hypotheses and claims_needed read from *iter_dir* (spec 3.4)."""
    bundle = (read_json(iter_dir / "bundle.json") or {}) if iter_dir else {}
    problem = (read_json(iter_dir / "problem.json") or {}) if iter_dir else {}
    return ValidatorContext(
        work_dir=work_dir, iter_dir=iter_dir, **limits,
        bundle_hypotheses=bundle.get("hypotheses") if isinstance(bundle, dict) else None,
        claims_needed=problem.get("claims_needed") if isinstance(problem, dict) else None,
    )


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


def _resolve_json_pointer(doc: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer against *doc*.

    Raises ``KeyError`` or ``IndexError`` on miss.
    """
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        raise KeyError(f"invalid JSON pointer: {pointer!r}")
    parts = pointer[1:].split("/")
    current = doc
    for part in parts:
        # RFC 6901 escapes
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                raise KeyError(f"list index must be an integer: {part!r}")
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

    if not path_str:
        errors.append("evidence item missing 'path'")
        return errors

    evidence_path = (base_dir / path_str).resolve()
    if not evidence_path.is_relative_to(base_dir.resolve()):
        errors.append(f"evidence path escapes base directory: {path_str!r}")
        return errors
    if not evidence_path.exists():
        errors.append(f"evidence path does not exist: {path_str}")
        return errors

    suffix = evidence_path.suffix.lower()
    try:
        if suffix == ".json":
            doc = json.loads(evidence_path.read_text())
            actual = _resolve_json_pointer(doc, key)
        elif suffix == ".jsonl":
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
        elif suffix in (".csv", ".tsv"):
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
            delimiter = "\t" if suffix == ".tsv" else ","
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
            actual = rows[row_idx][column]
            # Numeric comparison when the expected value is numeric
            if isinstance(value, (int, float)):
                try:
                    actual = float(actual)
                except ValueError:
                    pass
        else:
            # Plain text: key is a regex whose group 1 is the value
            text = evidence_path.read_text()
            match = re.search(key, text)
            if not match:
                errors.append(
                    f"evidence regex {key!r} not found in {path_str}"
                )
                return errors
            if not match.lastindex or match.lastindex < 1:
                errors.append(
                    f"evidence regex {key!r} matched in {path_str} "
                    "but has no capture group to compare against value"
                )
                return errors
            actual = match.group(1)
        if not _values_match(value, actual):
            errors.append(
                f"evidence value mismatch at {path_str}#{key}: "
                f"expected {value!r}, got {actual!r}"
            )
    except (KeyError, IndexError, ValueError, re.error, OSError) as exc:
        errors.append(f"evidence lookup failed for {path_str}#{key}: {exc}")

    return errors


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
        needed_ids = {c.get("id") for c in ctx.claims_needed if isinstance(c, dict)}
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
            h.get("id") for h in ctx.bundle_hypotheses if isinstance(h, dict) and h.get("control")
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
                for t_run in treatment_runs:
                    for c_run in control_runs:
                        t_seeds = sorted(t_run.get("seeds", []))
                        c_seeds = sorted(c_run.get("seeds", []))
                        if t_seeds != c_seeds:
                            errors.append(
                                f"hypothesis {hid!r}: treatment run "
                                f"{t_run.get('id')!r} and control run "
                                f"{c_run.get('id')!r} must use the same "
                                "seeds (paired comparison)"
                            )

    # locked_parameters / locked_workload checks
    for label, locked in (
        ("parameter", ctx.locked_parameters),
        ("workload parameter", ctx.locked_workload),
    ):
        if not locked:
            continue
        for run in runs:
            params = run.get("parameters", {})
            wl_changes = set(run.get("workload_changes", []))
            for key, locked_val in locked.items():
                if key in params and key not in wl_changes:
                    if params[key] != locked_val:
                        errors.append(
                            f"run {run.get('id')!r}: {label} {key!r} "
                            f"deviates from locked value {locked_val!r} "
                            f"(got {params[key]!r}) without workload_changes "
                            "declaration"
                        )

    return errors


def _get_baseline_noise_sd(ctx: ValidatorContext) -> float | None:
    """Read baseline.noise.sd, returning 0 for deterministic noise."""
    baseline = read_json(ctx.work_dir / "baseline.json")
    if baseline is None:
        return None
    noise = baseline.get("noise", {})
    if noise.get("deterministic") is True:
        return 0.0
    if "sd" in noise:
        return noise["sd"]
    return None


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

        # Noise honesty: CONFIRMED/REFUTED must declare noise measurement
        # and show effect > 2x noise (spec 3.4)
        if status in ("CONFIRMED", "REFUTED"):
            has_noise_sd = "noise_sd" in h
            has_unmeasured = h.get("noise_unmeasured") is True

            # Resolve noise: finding's own noise_sd, else baseline noise
            noise_sd: float | None = None
            if has_noise_sd:
                noise_sd = h["noise_sd"]
            elif not has_unmeasured:
                baseline_noise = _get_baseline_noise_sd(ctx)
                if baseline_noise is not None:
                    noise_sd = baseline_noise
                else:
                    errors.append(
                        f"hypothesis {hid!r}: {status} requires either "
                        "'noise_sd', 'noise_unmeasured: true', or a "
                        "baseline with measured noise"
                    )

            if noise_sd is not None:
                effect = h.get("effect", {})
                effect_value = effect.get("value") if isinstance(effect, dict) else None
                if effect_value is None:
                    errors.append(
                        f"hypothesis {hid!r}: {status} with noise_sd "
                        "requires 'effect.value'"
                    )
                elif isinstance(noise_sd, (int, float)):
                    if abs(effect_value) <= 2 * noise_sd:
                        errors.append(
                            f"hypothesis {hid!r}: |effect| "
                            f"{abs(effect_value):.4g} <= 2 * noise_sd "
                            f"{noise_sd:.4g}; add seeds, set status to "
                            "INCONCLUSIVE, or set noise_unmeasured with "
                            "a reason"
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
        known_ids = {h.get("id") for h in ctx.bundle_hypotheses if isinstance(h, dict)}
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

    # Secret check (3.14): no literal secret value anywhere in answer.json or report.md
    if ctx.secrets:
        report = ctx.work_dir / "report.md"
        texts = {"answer.json": json.dumps(data)}
        if report.is_file():
            texts["report.md"] = report.read_text(errors="replace")
        for label, text in texts.items():
            for name in check_secrets(text, ctx.secrets):
                errors.append(f"{label} contains secret {name!r}")

    return errors


def _check_task_limits(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check task_limits (B11) against runs.jsonl if available."""
    errors: list[str] = []
    if not ctx.task_limits or not ctx.runs_jsonl:
        return errors
    if not ctx.runs_jsonl.exists():
        return errors

    rows: list[dict] = []
    corrupt_lines: list[int] = []
    for i, line in enumerate(ctx.runs_jsonl.read_text().strip().splitlines()):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            corrupt_lines.append(i)
    if corrupt_lines:
        errors.append(f"runs.jsonl: corrupt JSON on lines {corrupt_lines}")
    # B11: only experiment commands count against the task's run limit
    run_count = sum(1 for r in rows if r.get("experiment") is True)

    max_runs = ctx.task_limits.get("max_runs")
    if max_runs is not None and run_count > max_runs:
        errors.append(
            f"task_limits: {run_count} runs exceeds max_runs={max_runs}"
        )

    max_wall_s = ctx.task_limits.get("max_wall_seconds")
    if max_wall_s is not None:
        total_wall = sum(r.get("wall_seconds", 0) for r in rows)
        if total_wall > max_wall_s:
            errors.append(
                f"task_limits: total wall time {total_wall:.1f}s "
                f"exceeds max_wall_seconds={max_wall_s}"
            )

    return errors


def bundle_hash(data: dict) -> str:
    """Compute sha256 hash of a bundle for the ledger's bundle_hash field."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# Dispatch table: artifact_type -> semantic check fn (absent = none)
_SEMANTIC_CHECKS: dict[str, Any] = {
    "bundle": _check_bundle_semantics,
    "plan": _check_plan_semantics,
    "findings": _check_findings_semantics,
    "principle_updates": _check_principle_updates_semantics,
    "answer": _check_answer_semantics,
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
    _move_extras(data, schema)  # logs only; unknown keys never fail

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


def validate_phase_artifacts(
    work_dir: Path, phase_dir: Path, artifact_types: list[str], **limits: Any,
) -> list[str]:
    """Run validators on phase artifacts, return error list."""
    all_errors: list[str] = []
    for atype in artifact_types:
        path = phase_dir / f"{atype}.json"
        if not path.exists():
            all_errors.append(f"{atype}: file not found")
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            all_errors.append(f"{atype}: invalid JSON — {exc}")
            continue
        ctx = iter_context(work_dir, phase_dir, **limits)
        for e in validate_artifact(atype, data, ctx):
            all_errors.append(f"{atype}: {e}")
    return all_errors
