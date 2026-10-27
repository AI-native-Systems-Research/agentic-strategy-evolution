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
    repo_dir: Path | None = None  # target repo: a third root for evidence paths
    prior_claim_ids: set | None = None  # claims_needed ids of earlier iterations (append-only)


def _iter_num(d: Path | None) -> int:
    name = d.name if d else ""
    return int(name[5:]) if name.startswith("iter-") and name[5:].isdigit() else 0


def campaign_record(work_dir: Path, up_to: int | None = None) -> tuple[list[dict], list[dict]]:
    """(claims_needed union, findings hypotheses) over iterations 1..up_to: claims_needed
    are append-only; a later entry for an id overrides the earlier fields."""
    runs = work_dir / "runs"
    nums = sorted(_iter_num(d) for d in runs.iterdir()) if runs.is_dir() else []
    needed: dict = {}
    hyps: list[dict] = []
    for n in (n for n in nums if n and (up_to is None or n <= up_to)):
        problem = read_json(runs / f"iter-{n}" / "problem.json")
        for c in (problem.get("claims_needed") or []) if isinstance(problem, dict) else []:
            if isinstance(c, dict) and isinstance(c.get("id"), str):
                needed[c["id"]] = {**needed.get(c["id"], {}), **c}
        findings = read_json(runs / f"iter-{n}" / "findings.json")
        if isinstance(findings, dict):
            hyps += [h for h in findings.get("hypotheses") or [] if isinstance(h, dict)]
    return list(needed.values()), hyps


def iter_context(work_dir: Path, iter_dir: Path | None, **limits: Any) -> ValidatorContext:
    """Context with bundle hypotheses and claims_needed read from *iter_dir* (spec 3.4).
    Claims already answered in earlier iterations need no hypothesis again."""
    bundle = (read_json(iter_dir / "bundle.json") or {}) if iter_dir else {}
    problem = (read_json(iter_dir / "problem.json") or {}) if iter_dir else {}
    needed = problem.get("claims_needed") if isinstance(problem, dict) else None
    n = _iter_num(iter_dir)
    prior_needed, prior_hyps = campaign_record(work_dir, n - 1) if n > 1 else ([], [])
    answered = {c.get("claim_id") for h in prior_hyps for c in h.get("claims") or [] if isinstance(c, dict)}
    if isinstance(needed, list):
        needed = [c for c in needed if not (isinstance(c, dict) and c.get("id") in answered)]
    return ValidatorContext(
        work_dir=work_dir, iter_dir=iter_dir, **limits,
        bundle_hypotheses=bundle.get("hypotheses") if isinstance(bundle, dict) else None,
        claims_needed=needed, prior_claim_ids={c["id"] for c in prior_needed},
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


def _num(v: Any) -> float | None:
    """A number, or a numeric string, as float; None otherwise (bools are not numbers)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v.strip()) if isinstance(v, str) else None
    except ValueError:
        return None


def _values_match(expected: Any, actual: Any, rel_tol: float = 1e-3) -> bool:
    """Numbers (or numeric strings) match within tolerance; anything else exactly."""
    a, b = _num(expected), _num(actual)
    if a is not None and b is not None:
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=1e-9)
    return expected == actual


EVIDENCE_KEY_HINT = ("Evidence keys: .json a JSON pointer /a/b; .jsonl N@/ptr; .csv/.tsv col@row; "
                     "other text a regex with one capture group. Relative paths resolve against "
                     "the iteration dir, the work dir, then the repository.")


def evidence_hint(errors: list[str]) -> str:
    """One-line reminder of the evidence key formats, only when an evidence error occurred."""
    return f"\n{EVIDENCE_KEY_HINT}" if any("evidence" in e for e in errors) else ""


def resolve_evidence_path(path_str: str, roots: list[Path]) -> tuple[Path | None, str]:
    """Find *path_str* under the first root that holds it; absolute paths must lie in a root."""
    roots = [r.resolve() for r in roots if r is not None]
    names = ", ".join(str(r) for r in roots)
    p = Path(path_str)
    cands = [p.resolve()] if p.is_absolute() else [(r / p).resolve() for r in roots]
    inside = [c for c in cands if any(c.is_relative_to(r) for r in roots)]
    if not inside:
        return None, f"evidence path escapes the allowed roots ({names}): {path_str!r}"
    for c in inside:
        if c.exists():
            return c, ""
    return None, f"evidence path does not exist: {path_str} (searched {names})"


def _ptr(key: str) -> str:
    return key if key == "" or key.startswith("/") else "/" + key


def check_evidence_item(item: dict, base_dir: Path, *more_roots: Path | None) -> list[str]:
    """Validate a single evidence item ``{path, key, value}``; a relative path resolves
    against *base_dir*, then each of *more_roots* in order."""
    if not isinstance(item, dict):
        return [f"evidence item must be an object {{path, key, value}}, got {item!r}"]
    errors: list[str] = []
    path_str = item.get("path", "")
    key = item.get("key", "")
    value = item.get("value")

    if not path_str:
        errors.append("evidence item missing 'path'")
        return errors

    evidence_path, err = resolve_evidence_path(path_str, [base_dir, *more_roots])
    if evidence_path is None:
        return [err]

    suffix = evidence_path.suffix.lower()
    try:
        if suffix == ".json":
            try:
                doc = json.loads(evidence_path.read_text())
            except ValueError:
                return [f"evidence file {path_str} is not JSON; save JSON output as .json "
                        "or use a .txt/.log path with a regex key"]
            actual = _resolve_json_pointer(doc, _ptr(key))
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
            actual = _resolve_json_pointer(doc, _ptr(pointer))
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

    # wait_for names a file (path) or a command; a bare run id would be polled for hours
    for run in runs:
        wf = run.get("wait_for")
        if isinstance(wf, str) and wf and not wf.startswith("cmd:") and not any(c in wf for c in "/."):
            errors.append(
                f"run {run.get('id')!r}: wait_for {wf!r} must be a file path or cmd:<command>; "
                "omit it for runs that finish within the turn"
            )

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

            if noise_sd:  # zero noise (deterministic): nothing to beat, no effect needed
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
        for ev in h.get("evidence", []):
            errors.extend(check_evidence_item(ev, ctx.iter_dir or ctx.work_dir, ctx.work_dir, ctx.repo_dir))

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


_COPY_VALUE = ("copy the exact value from the file; claims are quantitative "
               "(put prose in `answer`)")


def _same_value(a: Any, b: Any) -> bool:
    return _values_match(a, b, rel_tol=1e-9)


def _check_answer_semantics(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check answer-specific rules."""
    errors: list[str] = []

    if data.get("repro", "").lstrip().startswith("cd "):
        errors.append("repro must not start with `cd`: it runs from the repository root")

    # Evidence checks on claims; the claim value must be the evidence value
    roots = [ctx.work_dir, ctx.repo_dir]
    for claim in data.get("claims", []):
        ev = claim.get("evidence_detail") or claim.get("evidence")
        value, cid = claim.get("value"), claim.get("id")
        if isinstance(ev, str):  # contract form: the path must exist and hold the value
            path, err = resolve_evidence_path(ev, roots)
            if path is None or not path.is_file():
                errors.append(err or f"evidence file not found: {ev}")
            elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
                text = path.read_text(errors="replace")
                forms = {str(value), repr(value)} if isinstance(value, float) else {str(value)}
                if not any(f in text for f in forms):
                    errors.append(f"claim {cid!r}: value {value!r} not found in {ev}; {_COPY_VALUE}")
        elif ev:
            errors.extend(check_evidence_item(ev, *roots))
            if isinstance(ev, dict) and not _same_value(value, ev.get("value")):
                errors.append(f"claim {cid!r}: value {value!r} != evidence value "
                              f"{ev.get('value')!r}; {_COPY_VALUE}")

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


def _check_problem_semantics(data: dict, ctx: ValidatorContext) -> list[str]:
    """claims_needed are append-only across iterations."""
    ids = {c.get("id") for c in data.get("claims_needed", [])}
    dropped = sorted((ctx.prior_claim_ids or set()) - ids)
    if dropped:
        return [f"claims_needed ids may be added, not removed (missing {dropped}); "
                "mark them answered in findings instead"]
    return []


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

    return errors


def bundle_hash(data: dict) -> str:
    """Compute sha256 hash of a bundle for the ledger's bundle_hash field."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# Dispatch table: artifact_type -> semantic check fn (absent = none)
_SEMANTIC_CHECKS: dict[str, Any] = {
    "problem": _check_problem_semantics,
    "bundle": _check_bundle_semantics,
    "plan": _check_plan_semantics,
    "findings": _check_findings_semantics,
    "principle_updates": _check_principle_updates_semantics,
    "answer": _check_answer_semantics,
}


MAX_SCHEMA_ERRORS = 10  # keeps a repair message small


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

    # JSON Schema validation: every error at once (capped), each with its path
    schema_errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data),
                           key=lambda e: list(map(str, e.absolute_path)))
    if schema_errors:
        # Return early on schema failure; semantic checks assume valid shape
        return [f"schema: {'/'.join(map(str, e.absolute_path)) or '(top level)'}: {e.message[:200]}"
                for e in schema_errors[:MAX_SCHEMA_ERRORS]]

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
            all_errors.append(f"{atype}: file not found at {path.name}")
            continue
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError) as exc:  # bad JSON or undecodable bytes
            all_errors.append(f"{atype}: invalid JSON — {exc}")
            continue
        ctx = iter_context(work_dir, phase_dir, **limits)
        all_errors.extend(f"{atype}: {e}" for e in validate_artifact(atype, data, ctx))
    return all_errors
