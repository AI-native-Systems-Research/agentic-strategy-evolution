"""Tests for the friction-report #245 PR — F1, F3, F4, F11, F12, F15,
F17, F19, F20, F21 acceptance criteria.

Each F-entry is independently exercised. Mocks (per CLAUDE.md): no
live LLM calls; injected fakes for any subprocess that would
otherwise hit the network.

Post-review additions (round 2): F4 auto_approve roundtrip, F19
_resolve_turn_silence_threshold per-phase + scalar back-compat, F17
first-capture-wins idempotency + repo_dirty capture, F11 boundary
at total_files=4/5, F12 RuntimeError swallowing, F20 declared-
deviation real assertion, F21 apply_derived_from_patch round-trip.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
import yaml

from orchestrator.lineage import (
    apply_derived_from_patch,
    emit_cumulative_patch,
    resolve_derived_from,
    summarize_lineage,
)
from orchestrator.plot_specs import invoke_plot_specs
from orchestrator.reproducibility import capture_reproducibility_metadata
from orchestrator.validate import (
    _validate_depth_overrides,
    _validate_locked_parameters,
    _validate_locked_workload,
    _validate_physical_realism,
    compute_campaign_spec_diff,
    validate_design,
)


# ─── F1 / #246: locked_parameters spec-fidelity ────────────────────────────


def test_f1_locked_parameters_pass_when_match():
    campaign = {"locked_parameters": {"model": "llama-3.1", "concurrency_per_tenant": 32}}
    bundle = {"experiment_spec": {"verified_parameters": {
        "model": "llama-3.1", "concurrency_per_tenant": 32,
    }}}
    assert _validate_locked_parameters(bundle, campaign) == []


def test_f1_locked_parameters_fail_lists_all_deviations():
    campaign = {"locked_parameters": {
        "model": "llama-3.1", "concurrency_per_tenant": 32,
        "duration_seconds": 600,
    }}
    bundle = {"experiment_spec": {"verified_parameters": {
        "model": "qwen", "concurrency_per_tenant": 8,
        "duration_seconds": 600,
    }}}
    errors = _validate_locked_parameters(bundle, campaign)
    assert len(errors) == 1
    msg = errors[0]
    # Both deviations must appear in the SAME error message.
    assert "model" in msg and "qwen" in msg
    assert "concurrency_per_tenant" in msg and "8" in msg
    # The matched parameter must NOT appear as a violation.
    assert "duration_seconds" not in msg.split("\n")[-1]


def test_f1_locked_parameters_missing_verified_parameters_fails():
    """When the locked parameter has no entry in verified_parameters, the
    validator reports it as a deviation (with bundle=<missing>) — same
    path as a value mismatch, so the user sees one consistent message
    format regardless of which side is responsible."""
    campaign = {"locked_parameters": {"model": "llama"}}
    bundle = {"experiment_spec": {"verified_parameters": {}}}
    errors = _validate_locked_parameters(bundle, campaign)
    assert len(errors) == 1
    assert "<missing>" in errors[0]
    assert "model" in errors[0]


def test_f1_locked_parameters_no_verified_parameters_block_fails_with_clear_message():
    """When experiment_spec lacks verified_parameters entirely (vs an
    empty dict), surface a structured error pointing the user at the
    bundle field they must populate."""
    campaign = {"locked_parameters": {"model": "llama"}}
    bundle = {"experiment_spec": {}}
    errors = _validate_locked_parameters(bundle, campaign)
    assert len(errors) == 1
    # Either form is acceptable — the missing dict path or the
    # listed-as-deviation path. Both surface enough for the user to act.
    assert "verified_parameters" in errors[0] or "<missing>" in errors[0]


def test_f1_locked_parameters_no_campaign_block_skips():
    bundle = {"experiment_spec": {"verified_parameters": {"model": "x"}}}
    assert _validate_locked_parameters(bundle, None) == []
    assert _validate_locked_parameters(bundle, {}) == []


def test_f1_validate_design_hard_fails_under_locked_parameters_deviation(tmp_path: Path):
    """End-to-end: validate_design (the canonical entry-point) hard-fails
    on locked_parameters deviation regardless of --auto-approve.
    """
    iter_dir = tmp_path / "iter-1"
    (iter_dir / "inputs").mkdir(parents=True)
    (iter_dir / "results").mkdir()
    (iter_dir / "patches").mkdir()
    (iter_dir / "problem.md").write_text("test")
    (iter_dir / "handoff_snapshot.md").write_text("test")
    bundle = {
        "metadata": {"iteration": 1, "family": "f", "research_question": "q"},
        "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m", "diagnostic": "d"}],
        "experiment_spec": {"verified_parameters": {"model": "qwen"}},
    }
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    campaign = {"locked_parameters": {"model": "llama"}}
    result = validate_design(iter_dir, campaign=campaign)
    assert result["status"] == "fail"
    assert any("locked_parameters" in e for e in result["errors"])


# ─── F3 / #248: depth_overrides + invalidates_checks ───────────────────────


def test_f3_depth_overrides_without_invalidates_fails():
    bundle = {"experiment_spec": {"rehearsal_subset": {
        "depth_overrides": {"duration_seconds": 60},
    }}}
    errors = _validate_depth_overrides(bundle)
    assert len(errors) == 1
    assert "invalidates_checks" in errors[0]


def test_f3_depth_overrides_with_invalidates_passes():
    bundle = {"experiment_spec": {"rehearsal_subset": {
        "depth_overrides": {
            "duration_seconds": 60,
            "invalidates_checks": ["pmf-histogram"],
        },
    }}}
    assert _validate_depth_overrides(bundle) == []


def test_f3_no_depth_overrides_passes():
    bundle = {"experiment_spec": {"rehearsal_subset": {"seeds": [42]}}}
    assert _validate_depth_overrides(bundle) == []


# ─── F4 / #249: campaign_spec_diff in gate summary ─────────────────────────


def test_f4_compute_campaign_spec_diff_lists_violations(tmp_path: Path):
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir()
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump({
        "metadata": {"iteration": 1, "family": "f", "research_question": "q"},
        "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m", "diagnostic": "d"}],
        "experiment_spec": {
            "verified_parameters": {"model": "qwen", "concurrency": 8},
            "rehearsal_subset": {"depth_overrides": {
                "duration_seconds": 60,
                "invalidates_checks": ["pmf-histogram"],
            }},
        },
        "workload_changes_from_canonical": {
            "rationale": "x", "diff": [{"field": "P_A", "from": 1024, "to": 4000}],
        },
    }))
    campaign = {"locked_parameters": {"model": "llama", "concurrency": 32}}
    diff = compute_campaign_spec_diff(iter_dir, campaign)
    assert len(diff["locked_parameters_violations"]) == 2
    assert diff["depth_overrides_present"] is True
    assert diff["invalidated_checks_declared"] == ["pmf-histogram"]
    assert diff["workload_changes_from_canonical_declared"] is True


def test_f4_compute_campaign_spec_diff_clean_when_match(tmp_path: Path):
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir()
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump({
        "metadata": {"iteration": 1, "family": "f", "research_question": "q"},
        "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m", "diagnostic": "d"}],
        "experiment_spec": {"verified_parameters": {"model": "llama"}},
    }))
    diff = compute_campaign_spec_diff(iter_dir, {"locked_parameters": {"model": "llama"}})
    assert diff["locked_parameters_violations"] == []
    assert diff["depth_overrides_present"] is False
    assert diff["workload_changes_from_canonical_declared"] is False


# ─── F15 / #260: physical_realism_check soft warning ───────────────────────


def test_f15_physical_realism_warns_at_low_ratio_with_no_justification():
    bundle = {"experiment_spec": {"physical_realism_check": {
        "k_realism_ratio": 0.04, "justification": "",
    }}}
    warnings = _validate_physical_realism(bundle)
    assert len(warnings) == 1
    assert warnings[0].startswith("WARN:")


def test_f15_physical_realism_silent_at_realistic_ratio():
    bundle = {"experiment_spec": {"physical_realism_check": {
        "k_realism_ratio": 0.95, "justification": "",
    }}}
    assert _validate_physical_realism(bundle) == []


def test_f15_physical_realism_silent_with_substantive_justification():
    bundle = {"experiment_spec": {"physical_realism_check": {
        "k_realism_ratio": 0.04,
        "justification": (
            "K is 24x smaller than physical to demonstrate the mechanism "
            "in the contested-cache regime where it actually matters."
        ),
    }}}
    assert _validate_physical_realism(bundle) == []


# ─── F17 / #262: reproducibility_metadata auto-capture ─────────────────────


def test_f17_capture_returns_minimal_block_for_no_repo():
    block = capture_reproducibility_metadata(None)
    assert "captured_at" in block
    assert block["captured_at"].endswith("Z")
    assert "repo_commit" not in block


def test_f17_capture_no_repo_path_no_git_calls(tmp_path: Path):
    """capture is best-effort: a non-existent repo_path returns a
    minimal block, never raises."""
    block = capture_reproducibility_metadata(tmp_path / "nonexistent")
    assert "captured_at" in block


# ─── F19 / #264: per-phase silence threshold ───────────────────────────────


def test_f19_silence_threshold_per_phase_map_validates():
    """Schema accepts the per-phase form."""
    schema = yaml.safe_load(
        (Path("orchestrator/schemas/campaign.schema.yaml")).read_text()
    )
    campaign = {
        "research_question": "q",
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
        "sdk_timeouts": {
            "turn_silence_threshold_seconds": {
                "design": 600, "execute_analyze": 120, "report": 240,
            }
        },
    }
    jsonschema.validate(campaign, schema)


def test_f19_silence_threshold_scalar_still_validates():
    """Backward-compat: scalar form still validates."""
    schema = yaml.safe_load(
        (Path("orchestrator/schemas/campaign.schema.yaml")).read_text()
    )
    campaign = {
        "research_question": "q",
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
        "sdk_timeouts": {"turn_silence_threshold_seconds": 600},
    }
    jsonschema.validate(campaign, schema)


# ─── F20 / #265: locked_workload diff vs bundle.inputs/*.yaml ──────────────


def test_f20_locked_workload_diff_fails_undeclared_deviation(tmp_path: Path):
    iter_dir = tmp_path / "iter-1"
    inputs_dir = iter_dir / "inputs"
    inputs_dir.mkdir(parents=True)
    workload = {"tenants": {"A": {"input_distribution": {"type": "constant", "value": 4000}}}}
    (inputs_dir / "workload.yaml").write_text(yaml.safe_dump(workload))
    campaign = {"locked_workload": {"tenants": {
        "A": {"input_distribution": {"type": "constant", "value": 1024}},
    }}}
    bundle: dict = {}
    errors = _validate_locked_workload(iter_dir, bundle, campaign)
    assert len(errors) == 1
    assert "input_distribution" in errors[0] or "value" in errors[0]


def test_f20_locked_workload_diff_passes_with_declared_deviation(tmp_path: Path):
    """Declared deviation in workload_changes_from_canonical → no error.

    The walker's deviation tuple is ``(tenant, sub_path)`` where
    sub_path is the dotted path BUILT during the walk. For a
    locked_workload structured as ``{tenants: {A: {input_distribution:
    {value: 1024}}}}``, the walker descends:
        path="" + "tenants" → "tenants"
        path="tenants" + "A" → "tenants.A" (tenant id captured)
        path="tenants.A" + "input_distribution" → "tenants.A.input_distribution"
        path="tenants.A.input_distribution" + "value" → "tenants.A.input_distribution.value"
    So a declared diff entry must have field=
    "tenants.A.input_distribution.value" and tenant="A" to match.
    """
    iter_dir = tmp_path / "iter-1"
    inputs_dir = iter_dir / "inputs"
    inputs_dir.mkdir(parents=True)
    workload = {"tenants": {"A": {"input_distribution": {"type": "constant", "value": 4000}}}}
    (inputs_dir / "workload.yaml").write_text(yaml.safe_dump(workload))
    campaign = {"locked_workload": {"tenants": {
        "A": {"input_distribution": {"type": "constant", "value": 1024}},
    }}}
    bundle = {"workload_changes_from_canonical": {
        "rationale": "Pivoted to unit-length construction.",
        "diff": [{"tenant": "A",
                  "field": "tenants.A.input_distribution.value",
                  "from": 1024, "to": 4000}],
    }}
    errors = _validate_locked_workload(iter_dir, bundle, campaign)
    assert errors == [], (
        f"declared deviation should silence the validator, got: {errors}"
    )


def test_f20_malformed_workload_yaml_surfaces_as_deviation(tmp_path: Path):
    """C2 fix: malformed workload yaml is the regime F20 exists to
    catch — it must surface as a hard validation error, not a silent
    skip."""
    iter_dir = tmp_path / "iter-1"
    inputs_dir = iter_dir / "inputs"
    inputs_dir.mkdir(parents=True)
    (inputs_dir / "workload.yaml").write_text("not: valid: yaml: [unbalanced")
    campaign = {"locked_workload": {"tenants": {"A": {}}}}
    errors = _validate_locked_workload(iter_dir, {}, campaign)
    assert len(errors) == 1
    assert "malformed yaml" in errors[0]


def test_f20_locked_workload_no_block_skips(tmp_path: Path):
    iter_dir = tmp_path / "iter-1"
    (iter_dir / "inputs").mkdir(parents=True)
    assert _validate_locked_workload(iter_dir, {}, None) == []
    assert _validate_locked_workload(iter_dir, {}, {}) == []


# ─── F21 / #266: cumulative patches + derived_from ─────────────────────────


def test_f21_emit_cumulative_patch_returns_none_when_git_fails(tmp_path: Path):
    """Best-effort: subprocess errors don't raise."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not a git repo",
        )
        result = emit_cumulative_patch(tmp_path, "nous-exp-x", tmp_path)
        assert result is None


def test_f21_emit_cumulative_patch_writes_diff_when_git_succeeds(tmp_path: Path):
    iter_dir = tmp_path
    with patch("subprocess.run") as mock_run:
        # First call: _git_main_ref returns ok. Second call: diff returns content.
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="abcdef\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="diff --git a/x b/x\n", stderr=""),
        ]
        result = emit_cumulative_patch(tmp_path, "nous-exp-x", iter_dir)
        assert result is not None
        assert result.read_text() == "diff --git a/x b/x\n"


def test_f21_resolve_derived_from_no_block_returns_none():
    assert resolve_derived_from({}) is None
    assert resolve_derived_from({"derived_from": "not a dict"}) is None


def test_f21_resolve_derived_from_finds_cumulative_patch(tmp_path: Path, monkeypatch):
    prior_work = tmp_path / "prior-campaign"
    iter_dir = prior_work / "runs" / "iter-2"
    (iter_dir / "patches").mkdir(parents=True)
    cumulative = iter_dir / "patches" / "cumulative.patch"
    cumulative.write_text("diff --git a/x b/x\n")
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    campaign = {"derived_from": {"campaign": "prior-campaign", "iteration": 2}}
    result = resolve_derived_from(campaign)
    assert result == cumulative


def test_f21_resolve_derived_from_final_picks_highest_iter(tmp_path: Path, monkeypatch):
    prior = tmp_path / "prior-campaign"
    for n in (1, 2, 3):
        d = prior / "runs" / f"iter-{n}" / "patches"
        d.mkdir(parents=True)
        (d / "cumulative.patch").write_text(f"iter-{n} diff\n")
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    campaign = {"derived_from": {"campaign": "prior-campaign", "iteration": "final"}}
    result = resolve_derived_from(campaign)
    assert result is not None
    assert "iter-3" in str(result)


def test_f21_summarize_lineage_handles_missing_dirs(tmp_path: Path):
    summary = summarize_lineage(tmp_path)
    assert "iterations" in summary
    assert summary["iterations"] == []


# ─── F18 / #263: plot_specs invocation ─────────────────────────────────────


def test_f18_invoke_plot_specs_skips_when_no_specs(tmp_path: Path):
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir()
    assert invoke_plot_specs({}, iter_dir) == []
    assert invoke_plot_specs({"plot_specs": []}, iter_dir) == []


def test_f18_invoke_plot_specs_records_missing_script(tmp_path: Path):
    iter_dir = tmp_path / "iter-1"
    (iter_dir / "results").mkdir(parents=True)
    campaign = {"plot_specs": [{"id": "fig-1", "script": "missing.py"}]}
    results = invoke_plot_specs(
        campaign, iter_dir, campaign_yaml_dir=tmp_path,
    )
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "not found" in results[0]["error"]


def test_f18_invoke_plot_specs_runs_script(tmp_path: Path):
    """Use a no-op script to verify the env wiring works."""
    iter_dir = tmp_path / "iter-1"
    (iter_dir / "results").mkdir(parents=True)
    script = tmp_path / "fig.py"
    script.write_text(
        "import os, pathlib\n"
        "fig_dir = pathlib.Path(os.environ['NOUS_FIGURES_DIR'])\n"
        "(fig_dir / 'out.txt').write_text('ok')\n"
    )
    campaign = {"plot_specs": [
        {"id": "fig-1", "script": "fig.py", "outputs": ["out.txt"]},
    ]}
    results = invoke_plot_specs(campaign, iter_dir, campaign_yaml_dir=tmp_path)
    assert len(results) == 1
    assert results[0]["ok"] is True
    assert (iter_dir / "figures" / "out.txt").exists()


# ─── F11 / #256: high-BUILD warning ────────────────────────────────────────


def test_f11_high_build_warning_emits_for_many_files(tmp_path: Path, capsys):
    from orchestrator.iteration import _emit_high_build_warning
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(yaml.safe_dump({
        "arms": [
            {"type": "h-main", "code_changes": [
                {"file": f"f{i}.go", "intent": "x", "rationale": "y"} for i in range(7)
            ]},
        ],
    }))
    _emit_high_build_warning(bundle_path, max_turns_execute_analyze=120)
    captured = capsys.readouterr()
    assert "max_turns.execute_analyze" in captured.out


def test_f11_no_warning_for_low_count(tmp_path: Path, capsys):
    from orchestrator.iteration import _emit_high_build_warning
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(yaml.safe_dump({
        "arms": [{"type": "h-main", "code_changes": [
            {"file": "f.go", "intent": "x", "rationale": "y"},
        ]}],
    }))
    _emit_high_build_warning(bundle_path, max_turns_execute_analyze=120)
    captured = capsys.readouterr()
    assert "max_turns.execute_analyze" not in captured.out


@pytest.mark.parametrize("total_files,should_warn", [
    (3, False),
    (4, False),  # threshold boundary: 4 is silent
    (5, True),   # threshold boundary: 5 trips the warning
    (6, True),
])
def test_f11_warning_threshold_boundary(
    tmp_path: Path, capsys, total_files: int, should_warn: bool,
):
    """The threshold is `total_files >= 5` (line 881). Pin both sides
    of the boundary to catch off-by-one regressions."""
    from orchestrator.iteration import _emit_high_build_warning
    bundle_path = tmp_path / f"bundle-{total_files}.yaml"
    bundle_path.write_text(yaml.safe_dump({
        "arms": [{"type": "h-main", "code_changes": [
            {"file": f"f{i}.go", "intent": "x", "rationale": "y"}
            for i in range(total_files)
        ]}],
    }))
    _emit_high_build_warning(bundle_path, max_turns_execute_analyze=120)
    captured = capsys.readouterr()
    assert ("max_turns.execute_analyze" in captured.out) is should_warn


def test_f11_suggestion_formula_matches_120_plus_30_per_file(
    tmp_path: Path, capsys,
):
    """Pin the suggested raise-target so a regression of the formula
    (currently 120 + 30 * total_files) doesn't silently drift."""
    from orchestrator.iteration import _emit_high_build_warning
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(yaml.safe_dump({
        "arms": [{"type": "h-main", "code_changes": [
            {"file": f"f{i}.go", "intent": "x", "rationale": "y"}
            for i in range(6)
        ]}],
    }))
    _emit_high_build_warning(bundle_path, max_turns_execute_analyze=120)
    captured = capsys.readouterr()
    # 120 + 30*6 = 300
    assert "300" in captured.out


def test_f11_no_warning_when_operator_already_raised(
    tmp_path: Path, capsys,
):
    """Caller-side suppression: if max_turns.execute_analyze is already
    at-or-above the suggested target, the heuristic stays silent."""
    from orchestrator.iteration import _emit_high_build_warning
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(yaml.safe_dump({
        "arms": [{"type": "h-main", "code_changes": [
            {"file": f"f{i}.go", "intent": "x", "rationale": "y"}
            for i in range(6)
        ]}],
    }))
    # Suggested = 120 + 30*6 = 300; operator at 400 should be silent.
    _emit_high_build_warning(bundle_path, max_turns_execute_analyze=400)
    captured = capsys.readouterr()
    assert "max_turns.execute_analyze" not in captured.out


# ─── F4 / #249: campaign_spec_diff under --auto-approve, integration ──────


def test_f4_augment_writes_spec_diff_under_auto_approve(tmp_path: Path):
    """End-to-end: when _augment_summary_with_spec_diff runs (whether
    the LLM summarizer succeeded or failed), the JSON has both
    `campaign_spec_diff` and `auto_approved=True`. This is the
    headline F4 contract.
    """
    from orchestrator.iteration import _augment_summary_with_spec_diff
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir()
    bundle = {
        "metadata": {"iteration": 1, "family": "f", "research_question": "q"},
        "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m", "diagnostic": "d"}],
        "experiment_spec": {"verified_parameters": {"model": "qwen"}},
    }
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    summary_path = iter_dir / "gate_summary_design.json"
    # Pre-existing summary from a (hypothetical) successful summarizer.
    summary_path.write_text(json.dumps(
        {"gate_type": "design", "summary": "ok", "key_points": []}
    ))
    campaign = {"locked_parameters": {"model": "llama"}}
    _augment_summary_with_spec_diff(
        summary_path, iter_dir, campaign, auto_approve=True, stub=False,
    )
    payload = json.loads(summary_path.read_text())
    assert payload["auto_approved"] is True
    assert "campaign_spec_diff" in payload
    diff = payload["campaign_spec_diff"]
    assert any(
        v["param"] == "model" and v["bundle"] == "qwen"
        for v in diff["locked_parameters_violations"]
    )


def test_f4_augment_emits_stub_when_summarizer_failed(tmp_path: Path):
    """When the LLM summarizer fails (stub=True path), the spec diff
    is STILL emitted into a fresh stub summary file. F4 must work
    even when the LLM block is unavailable."""
    from orchestrator.iteration import _augment_summary_with_spec_diff
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir()
    bundle = {
        "metadata": {"iteration": 1, "family": "f", "research_question": "q"},
        "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m", "diagnostic": "d"}],
        "experiment_spec": {"verified_parameters": {"model": "llama"}},
    }
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    summary_path = iter_dir / "gate_summary_design.json"
    # No pre-existing summary — stub=True path.
    _augment_summary_with_spec_diff(
        summary_path, iter_dir, campaign={"locked_parameters": {"model": "llama"}},
        auto_approve=False, stub=True,
    )
    payload = json.loads(summary_path.read_text())
    assert "campaign_spec_diff" in payload
    assert payload["auto_approved"] is False


# ─── F19 / #264: behavioral test of _resolve_turn_silence_threshold ────────


def _build_dispatcher(campaign: dict):
    """Construct an SDKDispatcher without actually starting any SDK
    work — we only need the threshold-resolution attributes
    populated. Bypasses the live-call guards by injecting a no-op
    sdk_runner.
    """
    from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult

    def _noop_runner(**kwargs):
        return SDKResult(text="", input_tokens=0, output_tokens=0,
                         cache_creation_input_tokens=0,
                         cache_read_input_tokens=0,
                         cost_usd=0.0, duration_ms=0, num_turns=0,
                         is_error=False, error_message=None)
    # The dispatcher's _validate_campaign requires target_system.
    # Inject a minimal one — the threshold-resolution path doesn't
    # care about its contents.
    full_campaign = {
        "target_system": {"name": "x", "description": "d"},
        **campaign,
    }
    return SDKDispatcher(
        work_dir=Path("/tmp/nonexistent-workdir-for-test"),
        campaign=full_campaign,
        sdk_runner=_noop_runner,
    )


def test_f19_resolve_turn_silence_threshold_per_phase_map():
    """Per-phase map: each phase returns its declared value."""
    dispatcher = _build_dispatcher({
        "sdk_timeouts": {"turn_silence_threshold_seconds": {
            "design": 800, "execute_analyze": 90, "report": 200,
        }},
    })
    assert dispatcher._resolve_turn_silence_threshold("design") == 800
    assert dispatcher._resolve_turn_silence_threshold("execute_analyze") == 90
    assert dispatcher._resolve_turn_silence_threshold("report") == 200


def test_f19_resolve_turn_silence_threshold_partial_map_falls_back_to_default():
    """A partial map — only design set — leaves execute_analyze and
    report at their hardcoded defaults (120, 240)."""
    dispatcher = _build_dispatcher({
        "sdk_timeouts": {"turn_silence_threshold_seconds": {"design": 999}},
    })
    assert dispatcher._resolve_turn_silence_threshold("design") == 999
    assert dispatcher._resolve_turn_silence_threshold("execute_analyze") == 120
    assert dispatcher._resolve_turn_silence_threshold("report") == 240


def test_f19_resolve_turn_silence_threshold_scalar_back_compat():
    """Scalar form applies the same value to every phase."""
    dispatcher = _build_dispatcher({
        "sdk_timeouts": {"turn_silence_threshold_seconds": 333},
    })
    assert dispatcher._resolve_turn_silence_threshold("design") == 333
    assert dispatcher._resolve_turn_silence_threshold("execute_analyze") == 333
    assert dispatcher._resolve_turn_silence_threshold("report") == 333


def test_f19_resolve_turn_silence_threshold_no_config_uses_phase_defaults():
    """No sdk_timeouts at all → hardcoded per-phase defaults."""
    dispatcher = _build_dispatcher({})
    assert dispatcher._resolve_turn_silence_threshold("design") == 600
    assert dispatcher._resolve_turn_silence_threshold("execute_analyze") == 120
    assert dispatcher._resolve_turn_silence_threshold("report") == 240


# ─── F17 / #262: idempotency + repo_dirty ──────────────────────────────────


def test_f17_attach_to_state_first_capture_wins(tmp_path: Path):
    """Re-running INIT preserves the first capture."""
    from orchestrator.reproducibility import attach_to_state
    state_path = tmp_path / "state.json"
    initial_block = {
        "captured_at": "2026-05-01T00:00:00Z",
        "repo_commit": "aaaaaaaaaaaa",
    }
    state_path.write_text(json.dumps({
        "run_id": "x", "reproducibility_metadata": initial_block,
    }))
    later_block = {
        "captured_at": "2026-06-01T00:00:00Z",
        "repo_commit": "bbbbbbbbbbbb",
    }
    attach_to_state(tmp_path, later_block)
    state = json.loads(state_path.read_text())
    assert state["reproducibility_metadata"]["repo_commit"] == "aaaaaaaaaaaa"
    assert state["reproducibility_metadata"]["captured_at"] == "2026-05-01T00:00:00Z"


def test_f17_attach_to_state_writes_when_missing(tmp_path: Path):
    """On a fresh state.json with no metadata, write the block."""
    from orchestrator.reproducibility import attach_to_state
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"run_id": "x"}))
    block = {"captured_at": "2026-06-01T00:00:00Z", "repo_commit": "abc"}
    attach_to_state(tmp_path, block)
    state = json.loads(state_path.read_text())
    assert state["reproducibility_metadata"] == block


def test_f17_attach_to_state_raises_on_malformed_state(tmp_path: Path):
    """Loud failure: a corrupt state.json is a real defect, not
    something to swallow."""
    from orchestrator.reproducibility import attach_to_state
    (tmp_path / "state.json").write_text("not valid json {")
    with pytest.raises(RuntimeError, match="malformed"):
        attach_to_state(tmp_path, {"captured_at": "x"})


def test_f17_repo_dirty_false_on_clean_tree(tmp_path: Path):
    """When `git status --porcelain` returns empty, repo_dirty=False."""
    from orchestrator.reproducibility import capture_reproducibility_metadata
    repo = tmp_path / "repo"
    repo.mkdir()
    with patch("subprocess.run") as mock_run:
        # rev-parse HEAD → ok; status --porcelain → empty.
        mock_run.side_effect = lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="abc1234\n" if "rev-parse" in args[0] else "",
            stderr="",
        )
        block = capture_reproducibility_metadata(repo)
    assert block["repo_dirty"] is False


def test_f17_repo_dirty_true_on_modified_tree(tmp_path: Path):
    """When porcelain reports changes, repo_dirty=True."""
    from orchestrator.reproducibility import capture_reproducibility_metadata
    repo = tmp_path / "repo"
    repo.mkdir()
    def _fake_run(args, **kwargs):
        if "status" in args:
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=" M file.go\n", stderr="",
            )
        if "rev-parse" in args:
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="abc1234\n", stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
    with patch("subprocess.run", side_effect=_fake_run):
        block = capture_reproducibility_metadata(repo)
    assert block["repo_dirty"] is True


def test_f17_snapshot_iter_files_copies_hardware_config(tmp_path: Path):
    """snapshot_iter_files copies hardware_config.json into iter_dir/snapshots/."""
    from orchestrator.reproducibility import snapshot_iter_files
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hardware_config.json").write_text('{"H100": {}}')
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir()
    written = snapshot_iter_files(repo, iter_dir)
    assert "hardware_config.json" in written
    snapshot = iter_dir / "snapshots" / "hardware_config.json"
    assert snapshot.exists()
    assert snapshot.read_text() == '{"H100": {}}'


# ─── F12 / #257: aclose race-condition explicit cleanup contract ───────────


def test_f12_aclose_runtime_error_is_swallowed():
    """When the underlying generator raises the documented "already
    running" RuntimeError on aclose, the watchdog must NOT propagate
    it (would mask the original failure that triggered the cleanup)."""
    import asyncio as _asyncio

    from orchestrator.sdk_dispatch import aiter_with_silence_watchdog

    class _RacingAclose:
        """Mimics an async iterator that raises RuntimeError on aclose."""

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            raise RuntimeError(
                "aclose(): asynchronous generator is already running"
            )

    async def _drive():
        async for _ in aiter_with_silence_watchdog(_RacingAclose(), threshold=None):
            pass

    # No exception should escape — the RuntimeError is in the
    # documented swallow set.
    _asyncio.run(_drive())


def test_f12_aclose_arbitrary_exception_does_not_mask_primary():
    """A non-documented aclose exception is logged but doesn't
    propagate (we're in a finally; the primary exception should
    survive)."""
    import asyncio as _asyncio

    from orchestrator.sdk_dispatch import aiter_with_silence_watchdog

    class _BrokenAclose:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            raise ValueError("simulated cleanup defect")

    async def _drive():
        async for _ in aiter_with_silence_watchdog(_BrokenAclose(), threshold=None):
            pass

    # ValueError is in the broad fallback (now logged); should not
    # propagate.
    _asyncio.run(_drive())


# ─── F21 / #266: apply_derived_from_patch round-trip ───────────────────────


def test_f21_apply_derived_from_patch_succeeds_with_clean_apply(tmp_path: Path):
    from orchestrator.lineage import apply_derived_from_patch
    patch_path = tmp_path / "p.patch"
    patch_path.write_text("dummy")
    with patch_subprocess(returncodes=[0, 0]) as calls:
        ok, msg = apply_derived_from_patch(tmp_path, patch_path)
    assert ok is True
    assert "applied" in msg
    # Two calls: --check + apply.
    assert len(calls) == 2


def test_f21_apply_derived_from_patch_fails_when_check_rejects(tmp_path: Path):
    from orchestrator.lineage import apply_derived_from_patch
    patch_path = tmp_path / "p.patch"
    patch_path.write_text("dummy")
    with patch_subprocess(returncodes=[1], stderrs=["error: patch does not apply"]):
        ok, msg = apply_derived_from_patch(tmp_path, patch_path)
    assert ok is False
    assert "does not apply cleanly" in msg


def test_f21_full_round_trip(tmp_path: Path, monkeypatch):
    """Emit cumulative.patch in campaign A, resolve it from campaign
    B's derived_from, apply it. Single end-to-end contract test."""
    from orchestrator.lineage import (
        apply_derived_from_patch,
        emit_cumulative_patch,
        resolve_derived_from,
    )
    # Stage prior campaign.
    prior_work = tmp_path / "prior"
    iter_dir = prior_work / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))

    # Emit cumulative.patch by stubbing git.
    with patch_subprocess(
        returncodes=[0, 0, 0],
        stdouts=["origin/main\n", "diff --git a/x b/x\n+a\n", ""],
    ):
        path = emit_cumulative_patch(prior_work, "nous-exp-x", iter_dir)
    assert path is not None
    assert path.read_text().startswith("diff --git")

    # Now resolve from a campaign that points at "prior".
    campaign = {"derived_from": {"campaign": "prior", "iteration": 1}}
    resolved = resolve_derived_from(campaign)
    assert resolved == path

    # And apply (stubbed git apply succeeds).
    with patch_subprocess(returncodes=[0, 0]):
        ok, msg = apply_derived_from_patch(tmp_path, resolved)
    assert ok is True


def test_f21_emit_cumulative_patch_writes_error_sidecar_on_failure(tmp_path: Path):
    """When git diff fails, a sidecar at patches/cumulative.patch.error
    is written so summarize_lineage can surface the failure."""
    from orchestrator.lineage import emit_cumulative_patch
    iter_dir = tmp_path
    with patch_subprocess(
        returncodes=[0, 1],
        stdouts=["origin/main\n", ""],
        stderrs=["", "fatal: bad revision"],
    ):
        result = emit_cumulative_patch(tmp_path, "nous-exp-x", iter_dir)
    assert result is None
    sidecar = iter_dir / "patches" / "cumulative.patch.error"
    assert sidecar.exists()
    assert "fatal: bad revision" in sidecar.read_text()


# ─── Helpers ───────────────────────────────────────────────────────────────


from contextlib import contextmanager


@contextmanager
def patch_subprocess(
    returncodes: list[int],
    stdouts: list[str] | None = None,
    stderrs: list[str] | None = None,
):
    """Context manager that patches ``subprocess.run`` to return a
    sequence of CompletedProcess objects with the given returncodes
    (and optional stdout/stderr). Captures the calls in a list and
    yields it to the caller for assertion.
    """
    stdouts = stdouts or [""] * len(returncodes)
    stderrs = stderrs or [""] * len(returncodes)
    calls: list = []

    def _fake_run(args, **kwargs):
        calls.append(args)
        i = len(calls) - 1
        return subprocess.CompletedProcess(
            args=args,
            returncode=returncodes[i] if i < len(returncodes) else 0,
            stdout=stdouts[i] if i < len(stdouts) else "",
            stderr=stderrs[i] if i < len(stderrs) else "",
        )

    with patch("subprocess.run", side_effect=_fake_run):
        yield calls
