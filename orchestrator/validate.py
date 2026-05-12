"""Validation gates for Nous artifacts.

Usage:
    python -m orchestrator.validate design --dir runs/iter-1/
    python -m orchestrator.validate execution --dir runs/iter-1/
"""
import argparse
import json
import sys
from pathlib import Path

import jsonschema
import yaml

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _load_yaml_schema(name: str) -> dict:
    return yaml.safe_load((SCHEMAS_DIR / name).read_text())


def _load_json_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


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
        except (yaml.YAMLError, KeyError):
            pass  # plan parse issues already caught above

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
        except yaml.YAMLError:
            pass  # bundle parse issues already caught by design validation
        except KeyError as exc:
            errors.append(f"bundle.yaml arm missing required field: {exc}")

    if errors:
        return {"status": "fail", "errors": errors}
    return {"status": "pass"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Nous artifacts for a given phase.",
    )
    parser.add_argument(
        "phase", choices=["design", "execution"],
        help="Which phase to validate",
    )
    parser.add_argument(
        "--dir", required=True, type=Path,
        help="Path to the iteration directory (e.g., runs/iter-1/)",
    )
    args = parser.parse_args()

    if args.phase == "design":
        result = validate_design(args.dir)
    else:
        result = validate_execution(args.dir)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
