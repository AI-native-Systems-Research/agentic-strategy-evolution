"""Validation gate for campaign-end meta_findings.json (issue #155)."""
import json
from pathlib import Path

import jsonschema

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def _load_json_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def validate_meta_findings(work_dir: Path) -> dict:
    """Check meta_findings.json conforms to schema and citation floor.

    The citation floor (``orchestrator.meta_findings.evidence_is_concrete``)
    rejects entries whose ``evidence`` is a vague platitude. Schema does
    minLength + enum; the floor catches anything that passes minLength
    but is still aspirational.
    """
    work_dir = Path(work_dir)
    errors: list[str] = []

    target = work_dir / "meta_findings.json"
    if not target.exists():
        return {"status": "fail", "errors": [f"{target.name} not found at {work_dir}"]}

    try:
        payload = json.loads(target.read_text())
    except json.JSONDecodeError as exc:
        return {"status": "fail", "errors": [f"meta_findings.json is not valid JSON: {exc}"]}

    try:
        schema = _load_json_schema("meta_findings.schema.json")
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        errors.append(f"meta_findings.json schema error: {exc.message}")

    # Citation floor — applied to every evidence string in every stream.
    from orchestrator.meta_findings import validate_evidence

    for stream_name in ("campaign_design_lessons", "target_system_asks", "nous_asks"):
        items = payload.get(stream_name) or []
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence", "")
            err = validate_evidence(evidence)
            if err:
                errors.append(f"{stream_name}[{i}]: {err}")

    if errors:
        return {"status": "fail", "errors": errors}
    return {"status": "pass"}
