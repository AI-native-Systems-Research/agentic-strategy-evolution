"""Validation gates for Nous artifacts.

Usage:
    python -m orchestrator.validate design --dir runs/iter-1/
    python -m orchestrator.validate execution --dir runs/iter-1/
    python -m orchestrator.validate meta-findings --dir <work_dir>/
"""
import argparse
import json
import sys
from pathlib import Path

import jsonschema
import yaml

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def _load_yaml_schema(name: str) -> dict:
    return yaml.safe_load((SCHEMAS_DIR / name).read_text())


def _load_json_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


# Files that the orchestrator or agents are expected to write at iter_dir root.
# If you add a new root-level artifact, add it here — otherwise validation
# will flag it as an unexpected file.
_KNOWN_ROOT_FILES = {
    ".experiment_id",
    "problem.md", "bundle.yaml", "handoff_snapshot.md",
    "experiment_plan.yaml", "findings.json", "principle_updates.json",
    "design_log.md", "executor_log.md", "design_raw.md",
    "execute_analyze_output.json",
    "gate_summary_design.json", "gate_summary_findings.json",
    "gate_summary_continue.json",
    "human_feedback.json",
}


def _check_unexpected_files(iter_dir: Path) -> list[str]:
    """Flag files at iter root that aren't known protocol artifacts."""
    if not iter_dir.is_dir():
        return []
    errors = []
    for f in iter_dir.iterdir():
        if f.is_dir():
            continue
        if f.name not in _KNOWN_ROOT_FILES:
            errors.append(
                f"unexpected file at iter root: {f.name} "
                f"(should be in inputs/ or results/)"
            )
    return errors


def _validate_ground_truth_independence(bundle: dict) -> list[str]:
    """Cross-field check that the ground truth can disagree with the detector (issue #85).

    Returns a list of strings:
      * Plain strings are HARD ERRORS (validator fails).
      * Strings starting with "WARN:" are advisory (validator passes
        but surfaces the warning to the human gate).

    The four tautological-campaign failure mode (#84) is caught when an
    author either (a) self-declares ``shares_computation_with_detector: true``
    or (b) omits the ``ground_truth`` block entirely while testing a
    detector — the schema can't enforce (b) without breaking legacy
    bundles, so the absence of the block is silently allowed for now.
    """
    errors: list[str] = []
    gt = bundle.get("ground_truth")
    if not isinstance(gt, dict):
        return errors  # legacy bundles validate unchanged

    if gt.get("shares_computation_with_detector") is True:
        errors.append(
            "ground_truth.shares_computation_with_detector=true: the "
            "experiment is tautological by construction (the ground "
            "truth uses the same computation as the detector under test). "
            "Choose an independent ground truth — see issue #85."
        )
        return errors  # no point in further checks if the design is broken

    if not gt.get("independence_argument"):
        errors.append(
            "WARN: ground_truth.independence_argument is missing. Provide "
            "a plain-English justification that the ground truth can "
            "disagree with the detector — required to defend the "
            "experiment at the design gate."
        )

    mt = gt.get("measurement_type")
    dmt = gt.get("detector_measurement_type")
    if mt and dmt and mt == dmt:
        errors.append(
            f"WARN: ground_truth.measurement_type ({mt!r}) equals "
            f"detector_measurement_type ({dmt!r}); they may secretly "
            f"measure the same physical signal. Re-check the "
            f"independence_argument."
        )

    return errors


def _validate_typed_arm_fields(bundle: dict) -> list[str]:
    """Cross-field rules per arm type that JSON Schema can't easily express.

    H-dose-response (issue #157) requires knob, values (>=3 distinct),
    metric, and expected_shape. JSON Schema accepts these as optional
    so existing arm types stay valid; this function enforces them
    when the arm type asks for them.

    H-tradeoff (issue #158) requires metric, secondary_metric, and
    a tradeoff prediction with secondary_budget — see #158's
    extension to this function.
    """
    errors: list[str] = []
    arms = bundle.get("arms") or []
    if not isinstance(arms, list):
        return errors
    for i, arm in enumerate(arms):
        if not isinstance(arm, dict):
            continue
        arm_type = arm.get("type")
        if arm_type == "h-dose-response":
            for field in ("knob", "values", "metric", "expected_shape"):
                if field not in arm:
                    errors.append(
                        f"arms[{i}] (h-dose-response) missing required field {field!r}"
                    )
            values = arm.get("values")
            if isinstance(values, list):
                if len(values) < 3:
                    errors.append(
                        f"arms[{i}] (h-dose-response) has < 3 values "
                        f"({len(values)}); dose-response needs >= 3."
                    )
                if len(values) != len(set(map(repr, values))):
                    errors.append(
                        f"arms[{i}] (h-dose-response) has duplicate values; "
                        f"distinct knob settings required."
                    )
        elif arm_type == "h-tradeoff":
            for field in (
                "metric", "secondary_metric", "secondary_budget",
                "secondary_direction",
            ):
                if field not in arm:
                    errors.append(
                        f"arms[{i}] (h-tradeoff) missing required field {field!r}"
                    )
            if (
                arm.get("metric") is not None
                and arm.get("metric") == arm.get("secondary_metric")
            ):
                errors.append(
                    f"arms[{i}] (h-tradeoff): secondary_metric must differ "
                    f"from primary metric (both = {arm.get('metric')!r})."
                )
    return errors


def validate_design(iter_dir: Path) -> dict:
    """Check design artifacts exist and conform to schemas."""
    iter_dir = Path(iter_dir)
    errors = []

    # problem.md
    problem_path = iter_dir / "problem.md"
    if not problem_path.exists():
        errors.append("problem.md not found")
    elif problem_path.stat().st_size == 0:
        errors.append("problem.md is empty")

    # bundle.yaml
    bundle_path = iter_dir / "bundle.yaml"
    if not bundle_path.exists():
        errors.append("bundle.yaml not found")
    else:
        try:
            bundle = yaml.safe_load(bundle_path.read_text())
            schema = _load_yaml_schema("bundle.schema.yaml")
            jsonschema.validate(bundle, schema)
            errors.extend(_validate_typed_arm_fields(bundle))
            # Issue #85: WARN-prefixed entries are advisory and don't fail
            # validation (the human gate sees them but the campaign continues).
            for entry in _validate_ground_truth_independence(bundle):
                if entry.startswith("WARN:"):
                    # TODO: surface warnings to gate_summary, not as errors.
                    pass
                else:
                    errors.append(entry)
        except yaml.YAMLError as exc:
            errors.append(f"bundle.yaml is not valid YAML: {exc}")
        except jsonschema.ValidationError as exc:
            errors.append(f"bundle.yaml schema error: {exc.message}")

    # handoff_snapshot.md
    handoff_path = iter_dir / "handoff_snapshot.md"
    if not handoff_path.exists():
        errors.append("handoff_snapshot.md not found")
    elif handoff_path.stat().st_size == 0:
        errors.append("handoff_snapshot.md is empty")

    errors.extend(_check_unexpected_files(iter_dir))

    if errors:
        return {"status": "fail", "errors": errors}
    return {"status": "pass"}


def validate_execution(iter_dir: Path) -> dict:
    """Check execution artifacts exist, conform to schemas, and patches are valid."""
    iter_dir = Path(iter_dir)
    errors = []

    # experiment_plan.yaml
    plan_path = iter_dir / "experiment_plan.yaml"
    if not plan_path.exists():
        errors.append("experiment_plan.yaml not found")
    else:
        try:
            plan = yaml.safe_load(plan_path.read_text())
            schema = _load_yaml_schema("experiment_plan.schema.yaml")
            jsonschema.validate(plan, schema)
        except yaml.YAMLError as exc:
            errors.append(f"experiment_plan.yaml is not valid YAML: {exc}")
        except jsonschema.ValidationError as exc:
            errors.append(f"experiment_plan.yaml schema error: {exc.message}")

    # findings.json
    findings_path = iter_dir / "findings.json"
    if not findings_path.exists():
        errors.append("findings.json not found")
    else:
        try:
            findings = json.loads(findings_path.read_text())
            schema = _load_json_schema("findings.schema.json")
            jsonschema.validate(findings, schema)
        except json.JSONDecodeError as exc:
            errors.append(f"findings.json is not valid JSON: {exc}")
        except jsonschema.ValidationError as exc:
            errors.append(f"findings.json schema error: {exc.message}")

    # principle_updates.json
    principles_path = iter_dir / "principle_updates.json"
    if not principles_path.exists():
        errors.append("principle_updates.json not found")
    else:
        try:
            updates = json.loads(principles_path.read_text())
            if not isinstance(updates, list):
                errors.append(
                    f"principle_updates.json should be a list, got {type(updates).__name__}"
                )
            else:
                for i, entry in enumerate(updates):
                    if not isinstance(entry, dict) or "id" not in entry:
                        errors.append(
                            f"principle_updates.json entry {i} missing 'id'"
                        )
        except json.JSONDecodeError as exc:
            errors.append(f"principle_updates.json is not valid JSON: {exc}")

    # file references — check that output and input files in plan conditions exist
    if plan_path.exists():
        try:
            plan = yaml.safe_load(plan_path.read_text())
            for arm in plan.get("arms", []):
                for cond in arm.get("conditions", []):
                    output = cond.get("output")
                    if output:
                        output_file = Path(output)
                        if not output_file.is_absolute():
                            output_file = iter_dir / output
                        if not output_file.exists():
                            errors.append(
                                f"output file {cond['output']} referenced in "
                                f"{arm['arm_id']}/{cond['name']} not found"
                            )
                    for input_path in cond.get("inputs", []):
                        input_file = Path(input_path)
                        if not input_file.is_absolute():
                            input_file = iter_dir / input_path
                        if not input_file.exists():
                            errors.append(
                                f"input file {input_path} referenced in "
                                f"{arm['arm_id']}/{cond['name']} not found"
                            )
        except yaml.YAMLError:
            pass  # plan parse issues already caught above
        except KeyError as exc:
            errors.append(f"experiment_plan.yaml arm/condition missing key: {exc}")

    # patches — only required when bundle has code_changes
    bundle_path = iter_dir / "bundle.yaml"
    if bundle_path.exists():
        try:
            bundle = yaml.safe_load(bundle_path.read_text())
            arms_with_code = [
                arm for arm in bundle.get("arms", [])
                if arm.get("code_changes")
            ]
            if arms_with_code:
                patches_dir = iter_dir / "patches"
                if not patches_dir.is_dir():
                    errors.append(
                        "patches/ directory not found but bundle has arms with code_changes"
                    )
                else:
                    for arm in arms_with_code:
                        arm_type = arm["type"]
                        patch_file = patches_dir / f"{arm_type}.patch"
                        if not patch_file.exists():
                            errors.append(f"patches/{arm_type}.patch not found")
                        elif patch_file.stat().st_size == 0:
                            errors.append(f"patches/{arm_type}.patch is empty")
        except yaml.YAMLError as exc:
            errors.append(f"bundle.yaml is not valid YAML (patches check skipped): {exc}")
        except KeyError as exc:
            errors.append(f"bundle.yaml arm missing required field: {exc}")

    errors.extend(_check_unexpected_files(iter_dir))

    if errors:
        return {"status": "fail", "errors": errors}
    return {"status": "pass"}


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Nous artifacts for a given phase.",
    )
    parser.add_argument(
        "phase", choices=["design", "execution", "meta-findings"],
        help="Which phase to validate",
    )
    parser.add_argument(
        "--dir", required=True, type=Path,
        help="Path to the iteration directory (or work_dir for meta-findings)",
    )
    args = parser.parse_args()

    if args.phase == "design":
        result = validate_design(args.dir)
    elif args.phase == "execution":
        result = validate_execution(args.dir)
    else:
        result = validate_meta_findings(args.dir)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
