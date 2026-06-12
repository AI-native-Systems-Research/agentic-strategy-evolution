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
    # #188: provenance for `nous run --bundle <path>` (pre-authored
    # bundle, skips DESIGN dispatch).
    "bundle_manifest.json",
}


def _check_unexpected_files(
    iter_dir: Path,
    extra_allowed: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    """Flag files at iter root that aren't known protocol artifacts.

    #199: ``extra_allowed`` is a per-campaign extension to the global
    ``_KNOWN_ROOT_FILES`` whitelist. Campaigns that need additional
    iter-root artifacts (e.g. paper-* needing ``analysis_summary.json``
    + ``manifest.json``) declare them via ``campaign.validation.iter_root_extensions``
    in the campaign YAML.
    """
    if not iter_dir.is_dir():
        return []
    allowed = _KNOWN_ROOT_FILES | set(extra_allowed)
    errors = []
    for f in iter_dir.iterdir():
        if f.is_dir():
            continue
        if f.name not in allowed:
            errors.append(
                f"unexpected file at iter root: {f.name} "
                f"(should be in inputs/ or results/)"
            )
    return errors


def _campaign_iter_root_extensions(campaign: dict | None) -> frozenset[str]:
    """Read ``campaign.validation.iter_root_extensions`` (#199).

    Returns an empty frozenset for campaigns that don't declare it (the
    common case — most campaigns are fine with the global whitelist).
    """
    if not campaign:
        return frozenset()
    validation = campaign.get("validation") or {}
    extensions = validation.get("iter_root_extensions") or []
    return frozenset(str(x) for x in extensions if x)


def _campaign_required_iter_root(campaign: dict | None) -> frozenset[str]:
    """Read ``campaign.validation.required_iter_root`` (#199 v2).

    Files declared here are treated as MUST-EXIST at validate_execution
    time. Required ⊆ allowed: a required file is also implicitly an
    iter-root extension, so campaigns don't need to list it twice.
    """
    if not campaign:
        return frozenset()
    validation = campaign.get("validation") or {}
    required = validation.get("required_iter_root") or []
    return frozenset(str(x) for x in required if x)


def _check_required_iter_root(
    iter_dir: Path, required: set[str] | frozenset[str],
) -> list[str]:
    """Return one error per required iter-root file that's missing.

    #199 v2: campaign.validation.required_iter_root declares files the
    campaign promises to produce by EXECUTE_ANALYZE end. Missing entries
    are surfaced with a clear "required iter-root file missing: X"
    message so the operator (or a future incomplete-iteration diagnostic
    in the spirit of #187 / #200) sees what the campaign committed to.
    """
    errors: list[str] = []
    if not iter_dir.is_dir():
        return errors
    for name in sorted(required):
        if not (iter_dir / name).exists():
            errors.append(f"required iter-root file missing: {name}")
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


def validate_principles_have_empirical_content(
    principles: list[dict],
) -> list[str]:
    """Return WARN strings for category=domain principles missing #86 fields.

    Issue #179: even after the deterministic classifier
    (``orchestrator.principles_classifier``) runs, some principles
    will have a statement too neutral for the heuristic to classify.
    This validator surfaces those residuals so the human can act on
    them at the design gate or in the report.

    Meta-category principles (constraint principles emitted by
    ``orchestrator.refute_constraints`` per #169) are exempt — they're
    orchestrator-emitted facts, not LLM-extracted observations, and
    the empirical/algebraic distinction doesn't apply to them.

    Returned strings are advisory (``WARN:`` prefix); they don't fail
    validation. Callers may surface them via the design-gate summary
    or via a campaign-end report.
    """
    if not isinstance(principles, list):
        return []
    warnings: list[str] = []
    for i, p in enumerate(principles):
        if not isinstance(p, dict):
            continue
        if p.get("category") == "meta":
            continue
        if p.get("empirical_content") is None or p.get("derivation_type") is None:
            pid = p.get("id", f"principles[{i}]")
            warnings.append(
                f"WARN: principle {pid} has unset empirical_content / "
                f"derivation_type (issue #86). The classifier (#179) "
                f"could not infer the fields from the statement. Add "
                f"explicit empirical_content + derivation_type to the "
                f"principle, or refine the statement so it cites either "
                f"a concrete measurement (empirical) or an algebraic / "
                f"definitional marker (e.g. 'iff', 'theorem', "
                f"'by definition')."
            )
    return warnings


def _validate_locked_parameters(
    bundle: dict, campaign: dict | None,
) -> list[str]:
    """Issue #246 (F1): hard-fail when bundle deviates from campaign.locked_parameters.

    Closes the spec-fidelity gap left by HUMAN_DESIGN_GATE bypass under
    --auto-approve. The bundle's ``experiment_spec.verified_parameters``
    is the canonical place where DESIGN pins concrete values; comparing
    each ``campaign.locked_parameters[k]`` against
    ``verified_parameters.get(k)`` catches the failure mode where
    DESIGN silently rewrites locked workload parameters to its own
    guess (paper-memorytime-mirage iter-1: ``model``, ``concurrency``,
    ``duration``, ``warmup`` all overwritten).

    The error message lists EVERY deviation in one shot, not just the
    first — so a single re-run of the gate sees the full diff.
    """
    if not campaign:
        return []
    locked = campaign.get("locked_parameters")
    if not isinstance(locked, dict) or not locked:
        return []
    spec = bundle.get("experiment_spec") or {}
    verified = spec.get("verified_parameters") or {}
    if not isinstance(verified, dict):
        return [
            "campaign.locked_parameters is set but "
            "bundle.experiment_spec.verified_parameters is missing or "
            "malformed; cannot verify spec-fidelity (#246)."
        ]
    deviations: list[str] = []
    for key, expected in locked.items():
        if key not in verified:
            deviations.append(
                f"  - {key}: campaign={expected!r}, bundle=<missing>"
            )
            continue
        actual = verified[key]
        if actual != expected:
            deviations.append(
                f"  - {key}: campaign={expected!r}, bundle={actual!r}"
            )
    if not deviations:
        return []
    return [
        "bundle.experiment_spec.verified_parameters deviates from "
        "campaign.locked_parameters (#246/F1). Each entry must match "
        "exactly:\n" + "\n".join(deviations)
    ]


def _validate_locked_workload(
    iter_dir: Path, bundle: dict, campaign: dict | None,
) -> list[str]:
    """Issue #265 (F20): hard-fail when bundle.inputs/*.yaml deviates
    from campaign.locked_workload, unless bundle.workload_changes_from_canonical
    explicitly declares the deviation.

    Workload distributions live in ``inputs/<workload>.yaml`` (referenced
    from the bundle), not in ``verified_parameters``, so #246's check
    misses them. This validator does the structural diff.

    Resolution: scan ``iter_dir/inputs/*.yaml``; for each top-level field
    that also appears in ``locked_workload``, compare. If the values
    differ, fail unless ``workload_changes_from_canonical.diff`` declares
    that field-tuple.
    """
    if not campaign:
        return []
    locked = campaign.get("locked_workload")
    if not isinstance(locked, dict) or not locked:
        return []
    declared = bundle.get("workload_changes_from_canonical") or {}
    declared_diffs = declared.get("diff") or [] if isinstance(declared, dict) else []
    declared_fields = {
        (entry.get("tenant"), entry.get("field"))
        for entry in declared_diffs
        if isinstance(entry, dict)
    }

    inputs_dir = iter_dir / "inputs"
    if not inputs_dir.is_dir():
        # Workload yaml may not exist yet; nothing to diff.
        return []
    deviations: list[str] = []
    workload_yamls = sorted(inputs_dir.glob("*.yaml")) + sorted(inputs_dir.glob("*.yml"))
    for workload_path in workload_yamls:
        try:
            data = yaml.safe_load(workload_path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        # Compare every top-level locked field.
        _walk_locked_workload(
            locked, data, declared_fields, deviations, workload_path.name,
        )
    if not deviations:
        return []
    return [
        f"workload yaml deviates from campaign.locked_workload "
        f"(#265/F20). Each must match exactly OR be declared in "
        f"bundle.workload_changes_from_canonical.diff:\n"
        + "\n".join(deviations)
    ]


def _walk_locked_workload(
    locked: dict, actual: dict, declared: set, errors: list[str], src: str,
    *, path: str = "", tenant: str | None = None,
) -> None:
    """Recursive walk for #265: compare locked dict against actual,
    report any mismatch not present in ``declared`` (set of (tenant, field)
    tuples from workload_changes_from_canonical.diff).
    """
    for key, expected in locked.items():
        sub_path = f"{path}.{key}" if path else key
        if isinstance(expected, dict) and isinstance(actual.get(key), dict):
            # Recurse — for ``tenants`` block, the key at this level is
            # the tenant id, threaded through to the deviation tuple.
            _walk_locked_workload(
                expected, actual[key], declared, errors, src,
                path=sub_path, tenant=tenant or (key if path == "tenants" else tenant),
            )
            continue
        actual_value = actual.get(key, "<missing>")
        if actual_value != expected:
            if (tenant, sub_path) in declared or (None, sub_path) in declared:
                continue  # explicitly declared deviation
            errors.append(
                f"  - {src}: {sub_path}: canonical={expected!r}, "
                f"actual={actual_value!r}"
                + (f" (tenant={tenant})" if tenant else "")
            )


def _validate_depth_overrides(bundle: dict) -> list[str]:
    """Issue #248 (F3): if rehearsal_subset.depth_overrides has any
    payload field set (i.e. anything besides ``invalidates_checks``),
    ``invalidates_checks`` must be populated — otherwise the rehearsal
    silently weakens scale-dependent apparatus checks.
    """
    spec = bundle.get("experiment_spec") or {}
    rehearsal = spec.get("rehearsal_subset") or {}
    overrides = rehearsal.get("depth_overrides")
    if not isinstance(overrides, dict) or not overrides:
        return []
    payload_keys = [k for k in overrides if k != "invalidates_checks"]
    if not payload_keys:
        return []
    invalidates = overrides.get("invalidates_checks") or []
    if not invalidates:
        return [
            "rehearsal_subset.depth_overrides sets payload field(s) "
            f"{payload_keys} without declaring invalidates_checks. "
            "Depth shrinkage silently invalidates scale-dependent "
            "apparatus checks; the campaign author must list which "
            "checks they're surrendering (#248/F3)."
        ]
    return []


def _validate_physical_realism(bundle: dict) -> list[str]:
    """Issue #260 (F15): soft-warn when k_realism_ratio is far from 1
    and justification is missing/perfunctory. WARN-prefixed; never
    hard-fails the gate (the campaign author may legitimately choose
    a synthetic regime to demonstrate the mechanism).
    """
    spec = bundle.get("experiment_spec") or {}
    block = spec.get("physical_realism_check")
    if not isinstance(block, dict):
        return []
    ratio = block.get("k_realism_ratio")
    if not isinstance(ratio, (int, float)):
        return []
    if 0.5 <= ratio <= 2.0:
        return []
    justification = (block.get("justification") or "").strip()
    # Perfunctory = empty or under 30 chars.
    if len(justification) >= 30:
        return []
    return [
        f"WARN: physical_realism_check.k_realism_ratio={ratio:.3f} "
        f"is far from 1 (synthetic-regime risk: \"you constructed "
        f"your own contention\"), and justification is empty or "
        f"perfunctory. Add a substantive justification or raise K to "
        f"the realistic value (#260/F15)."
    ]


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


def compute_campaign_spec_diff(
    iter_dir: Path, campaign: dict | None,
) -> dict:
    """Issue #249 (F4): structured campaign-vs-bundle deviation report.

    Used by ``_generate_gate_summary`` to populate the
    ``campaign_spec_diff`` block on every gate summary, regardless of
    --auto-approve. The diff is "soft" (informational) by default —
    F1's ``_validate_locked_parameters`` is the hard-fail layer.

    Returns a dict with three sub-keys:
      * ``locked_parameters_violations`` — list of {param, campaign,
        bundle} entries (these are also hard validation failures
        upstream; recorded here so an auditor sees them in one place).
      * ``locked_workload_violations`` — list of {field, canonical, actual,
        tenant?} entries (these are also hard validation failures upstream).
      * ``depth_overrides_present`` — bool.
      * ``invalidated_checks_declared`` — list of strings.
      * ``workload_changes_from_canonical_declared`` — bool.

    All keys are present so the consumer can grep for missing keys as
    a regression signal (PR #235 pattern).
    """
    diff: dict = {
        "locked_parameters_violations": [],
        "locked_workload_violations": [],
        "depth_overrides_present": False,
        "invalidated_checks_declared": [],
        "workload_changes_from_canonical_declared": False,
    }
    bundle_path = iter_dir / "bundle.yaml"
    if not bundle_path.exists():
        return diff
    try:
        bundle = yaml.safe_load(bundle_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return diff
    if not isinstance(bundle, dict):
        return diff
    spec = bundle.get("experiment_spec") or {}
    verified = (spec.get("verified_parameters") or {}) if isinstance(spec, dict) else {}

    locked = (campaign or {}).get("locked_parameters") or {}
    if isinstance(locked, dict) and isinstance(verified, dict):
        for k, expected in locked.items():
            actual = verified.get(k, "<missing>")
            if actual != expected:
                diff["locked_parameters_violations"].append(
                    {"param": k, "campaign": expected, "bundle": actual}
                )

    rehearsal = spec.get("rehearsal_subset") or {} if isinstance(spec, dict) else {}
    overrides = rehearsal.get("depth_overrides") if isinstance(rehearsal, dict) else None
    if isinstance(overrides, dict):
        payload_keys = [k for k in overrides if k != "invalidates_checks"]
        diff["depth_overrides_present"] = bool(payload_keys)
        invalidates = overrides.get("invalidates_checks") or []
        if isinstance(invalidates, list):
            diff["invalidated_checks_declared"] = [str(x) for x in invalidates]

    diff["workload_changes_from_canonical_declared"] = (
        isinstance(bundle.get("workload_changes_from_canonical"), dict)
    )
    return diff


def validate_design(iter_dir: Path, campaign: dict | None = None) -> dict:
    """Check design artifacts exist and conform to schemas.

    #199: ``campaign`` is optional but recommended — it enables the
    per-campaign iter-root whitelist extension via
    ``campaign.validation.iter_root_extensions``.
    """
    iter_dir = Path(iter_dir)
    errors = []
    # #279 review: WARN-prefixed advisory entries (ground-truth
    # independence #85, physical realism #260) were detected then dropped.
    # Collect them and return them so the caller can surface them at the
    # design gate instead of silently discarding tautology / synthetic-
    # regime warnings.
    warnings: list[str] = []

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
            # #246 (F1): locked_parameters spec-fidelity. Hard-fail under
            # auto-approve too — that's the whole point.
            errors.extend(_validate_locked_parameters(bundle, campaign))
            # #265 (F20): locked_workload diff against bundle.inputs/*.yaml.
            errors.extend(_validate_locked_workload(iter_dir, bundle, campaign))
            # #248 (F3): depth_overrides without invalidates_checks.
            errors.extend(_validate_depth_overrides(bundle))
            # #260 (F15): physical-realism soft warning. WARN-prefixed.
            for entry in _validate_physical_realism(bundle):
                if entry.startswith("WARN:"):
                    warnings.append(entry)
                else:
                    errors.append(entry)
            # Issue #85: WARN-prefixed entries are advisory and don't fail
            # validation (the human gate sees them but the campaign continues).
            for entry in _validate_ground_truth_independence(bundle):
                if entry.startswith("WARN:"):
                    warnings.append(entry)
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

    # #199 v2: required ⊆ allowed at design time too. We don't enforce
    # required-presence here (most required files are written during
    # EXECUTE, not DESIGN), but if the campaign agent does write one
    # during DESIGN, the unexpected-file check must not reject it.
    extensions = _campaign_iter_root_extensions(campaign)
    required = _campaign_required_iter_root(campaign)
    errors.extend(_check_unexpected_files(iter_dir, extensions | required))

    if errors:
        return {"status": "fail", "errors": errors, "warnings": warnings}
    return {"status": "pass", "warnings": warnings}


def validate_execution(iter_dir: Path, campaign: dict | None = None) -> dict:
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

    # #199 v2: required ⊆ allowed (a required file is also implicitly
    # allowed at iter-root, so campaigns don't have to declare it
    # twice). Merge before the unexpected-file check.
    extensions = _campaign_iter_root_extensions(campaign)
    required = _campaign_required_iter_root(campaign)
    errors.extend(_check_unexpected_files(iter_dir, extensions | required))
    errors.extend(_check_required_iter_root(iter_dir, required))

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
