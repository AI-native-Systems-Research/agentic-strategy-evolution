"""answer.json and evidence checks.

Every public function returns a ``list[str]`` of error messages; an empty
list means the artifact is valid.  Validators never raise on validation
failure.
"""

from __future__ import annotations

import csv
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


ANSWER_SCHEMA = Path(__file__).resolve().parent / "schemas" / "answer.schema.json"


def load_answer_schema() -> dict:
    return json.loads(ANSWER_SCHEMA.read_text())


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
    """Where evidence paths resolve, and which secret values must not appear."""

    work_dir: Path
    secrets: dict[str, str] | None = None
    repo_dir: Path | None = None  # target repo: a second root for evidence paths


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


def resolve_evidence_path(path_str: str, roots: list[Path]) -> tuple[Path | None, str]:
    """Find *path_str* under the first root that holds it; absolute paths must lie in a root."""
    roots = [r.resolve() for r in roots if r is not None]
    names = ", ".join(str(r) for r in roots)
    p = Path(path_str)
    cands = [p.resolve()] if p.is_absolute() else [(r / p).resolve() for r in roots]
    if not p.is_absolute() and len(p.parts) > 1:  # "work/x.json" said from the work dir's parent
        cands += [(r / Path(*p.parts[1:])).resolve() for r in roots if r.name == p.parts[0]]
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


_COPY_VALUE = ("copy the exact value from the file; claims are quantitative "
               "(put prose in `answer`)")


def _same_value(a: Any, b: Any) -> bool:
    return _values_match(a, b, rel_tol=1e-9)


def _check_answer_semantics(data: dict, ctx: ValidatorContext) -> list[str]:
    """Check answer-specific rules."""
    errors: list[str] = []

    repro = data.get("repro", "")
    if re.search(r"(^|[;&|(\n]\s*)cd(\s|$)", repro.strip()):
        errors.append("repro must not `cd` anywhere: it runs from the repository root, in any copy of it")
    for root in (ctx.repo_dir, ctx.work_dir):
        # The root as a whole path component: /x/proj, not /x/proj-data
        if root and str(root) and re.search(re.escape(str(Path(root).resolve())) + r"(?=[/\s'\"]|$)", repro):
            errors.append(f"repro must not use the absolute path {Path(root).resolve()}: use paths relative "
                          "to the repository root, so it runs in any copy")

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


MAX_SCHEMA_ERRORS = 10  # keeps a repair message small


def validate_answer(data: dict, context: ValidatorContext) -> list[str]:
    """Validate answer.json content.  Returns list of error strings (empty = valid).

    Moves unknown top-level keys to ``data["extra"]`` before the schema check.
    """
    schema = load_answer_schema()
    _move_extras(data, schema)  # logs only; unknown keys never fail

    # JSON Schema validation: every error at once (capped), each with its path
    schema_errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data),
                           key=lambda e: list(map(str, e.absolute_path)))
    if schema_errors:
        # Return early on schema failure; semantic checks assume valid shape
        return [f"schema: {'/'.join(map(str, e.absolute_path)) or '(top level)'}: {e.message[:200]}"
                for e in schema_errors[:MAX_SCHEMA_ERRORS]]
    return _check_answer_semantics(data, context)


def validate_answer_file(work_dir: Path, **limits: Any) -> list[str]:
    """Validate work_dir/answer.json; each error is prefixed ``answer: ``."""
    path = work_dir / "answer.json"
    if not path.exists():
        return [f"answer: file not found at {path.name}"]
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as exc:  # bad JSON or undecodable bytes
        return [f"answer: invalid JSON — {exc}"]
    return [f"answer: {e}" for e in validate_answer(data, ValidatorContext(work_dir=work_dir, **limits))]
