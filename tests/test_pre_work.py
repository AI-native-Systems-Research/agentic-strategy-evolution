"""Behavioral tests for the PRE_WORK phase (issue #167).

PRE_WORK runs before iter-1 DESIGN, performing cheap deterministic
exploration of the target system to inform the campaign's iteration
structure. The artifact is `pre_work.json` at the campaign root.

Test contract:
  - Module-level `run_pre_work(campaign, runner=)` honors injected runners
    and chooses the right default behavior given campaign config.
  - Schema additions are additive: legacy state.json + campaign.yaml validate.
  - PRE_WORK is a recognized phase in engine.Phase + transition map.
  - subprocess hook for `pre_work_script` is mockable; no live subprocess
    in tests.
  - pre_work.json validates against pre_work.schema.json; all fields optional.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.engine import Phase, TRANSITIONS
from orchestrator.pre_work import (
    PreWorkResult,
    run_pre_work,
    write_pre_work,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


# ─── Default runner: Python summary of campaign + repo_cache ──────────────


class TestDefaultRunner:
    def test_default_runner_returns_pre_work_result(self) -> None:
        """With no pre_work_script and no repo_cache, default still returns a result."""
        campaign = {
            "run_id": "test",
            "target_system": {"name": "demo", "description": "d"},
        }
        result = run_pre_work(campaign)
        assert isinstance(result, PreWorkResult)

    def test_default_runner_summarizes_target_system(self) -> None:
        """data_summary captures observable_metrics + controllable_knobs from campaign.yaml."""
        campaign = {
            "run_id": "demo",
            "target_system": {
                "name": "demo",
                "description": "d",
                "observable_metrics": ["latency_p50", "throughput"],
                "controllable_knobs": ["batch_size", "concurrency"],
            },
        }
        result = run_pre_work(campaign)
        assert result.data_summary is not None
        assert "observable_metrics" in result.data_summary
        assert "latency_p50" in result.data_summary["observable_metrics"]
        assert "controllable_knobs" in result.data_summary
        assert "batch_size" in result.data_summary["controllable_knobs"]

    def test_default_runner_is_deterministic(self) -> None:
        """Calling twice on the same campaign returns equal results — no randomness."""
        campaign = {
            "run_id": "demo",
            "target_system": {
                "name": "x",
                "observable_metrics": ["m1"],
                "controllable_knobs": ["k1"],
            },
        }
        a = run_pre_work(campaign)
        b = run_pre_work(campaign)
        assert a.data_summary == b.data_summary


# ─── Subprocess runner: pre_work_script declared in campaign.yaml ─────────


class TestSubprocessRunner:
    def test_pre_work_script_subprocess_is_called(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """When pre_work_script is set, the default path subprocesses it."""
        script = tmp_path / "explore.py"
        script.write_text("# fake")
        campaign = {
            "run_id": "demo",
            "target_system": {"name": "x"},
            "pre_work_script": str(script),
        }

        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            stdout = json.dumps({
                "data_summary": {"rows": 1000},
                "candidate_parameter_ranges": {"rate": [0.1, 10.0]},
            })
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

        monkeypatch.setattr("orchestrator.pre_work.subprocess.run", fake_run)

        result = run_pre_work(campaign)
        assert result.data_summary == {"rows": 1000}
        assert result.candidate_parameter_ranges == {"rate": [0.1, 10.0]}
        assert len(captured) == 1
        assert str(script) in captured[0]

    def test_subprocess_runner_handles_nonzero_exit(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """A failing pre_work_script yields an empty PreWorkResult; campaign continues."""
        script = tmp_path / "explore.py"
        script.write_text("# fake")
        campaign = {
            "run_id": "demo",
            "target_system": {"name": "x"},
            "pre_work_script": str(script),
        }

        def failing_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom")

        monkeypatch.setattr("orchestrator.pre_work.subprocess.run", failing_run)

        result = run_pre_work(campaign)
        # No crash. PreWorkResult has all-None fields — DESIGN proceeds normally.
        assert isinstance(result, PreWorkResult)
        assert result.data_summary is None

    def test_subprocess_runner_handles_invalid_json(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """Invalid JSON output yields empty PreWorkResult, not a crash."""
        script = tmp_path / "explore.py"
        script.write_text("# fake")
        campaign = {
            "run_id": "demo",
            "target_system": {"name": "x"},
            "pre_work_script": str(script),
        }

        def bad_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

        monkeypatch.setattr("orchestrator.pre_work.subprocess.run", bad_run)
        result = run_pre_work(campaign)
        assert isinstance(result, PreWorkResult)
        assert result.data_summary is None


# ─── Injection seam: runner= replaces both default behaviors ──────────────


class TestRunnerInjection:
    def test_injected_runner_replaces_default(self) -> None:
        invocations: list[dict] = []

        def fake_runner(campaign):
            invocations.append(campaign)
            return PreWorkResult(
                data_summary={"injected": True},
                candidate_parameter_ranges=None,
                structural_groupings=["A", "B"],
                baseline_metrics=None,
                recommended_arms_for_iter1=None,
            )

        result = run_pre_work({"run_id": "x"}, runner=fake_runner)
        assert result.data_summary == {"injected": True}
        assert result.structural_groupings == ["A", "B"]
        assert len(invocations) == 1

    def test_injected_runner_overrides_pre_work_script(
        self, monkeypatch,
    ) -> None:
        """Even when pre_work_script is set, runner= takes precedence (test discipline)."""
        called = {"subprocess": 0, "injected": 0}

        def fake_subprocess_run(*args, **kwargs):
            called["subprocess"] += 1
            return subprocess.CompletedProcess([], 0, stdout="{}", stderr="")

        def injected(campaign):
            called["injected"] += 1
            return PreWorkResult()

        monkeypatch.setattr("orchestrator.pre_work.subprocess.run", fake_subprocess_run)
        run_pre_work(
            {"run_id": "x", "pre_work_script": "/fake/path.py"},
            runner=injected,
        )
        assert called["injected"] == 1
        assert called["subprocess"] == 0


# ─── Atomic write to pre_work.json ────────────────────────────────────────


class TestWritePreWork:
    def test_write_round_trips_through_schema(self, tmp_path: Path) -> None:
        result = PreWorkResult(
            data_summary={"rows": 42},
            candidate_parameter_ranges={"rate": [0.0, 10.0]},
            structural_groupings=[{"name": "g1", "members": ["m1", "m2"]}],
            baseline_metrics={"throughput": 100.0},
            recommended_arms_for_iter1=["focus on rate above 5"],
        )
        path = write_pre_work(tmp_path, result)
        assert path == tmp_path / "pre_work.json"

        on_disk = json.loads(path.read_text())
        jsonschema.validate(on_disk, _load_schema("pre_work.schema.json"))

        # Round-trips
        assert on_disk["data_summary"] == {"rows": 42}
        assert on_disk["recommended_arms_for_iter1"] == ["focus on rate above 5"]

    def test_write_empty_result_validates(self, tmp_path: Path) -> None:
        """All-None fields produce a minimal-but-valid pre_work.json."""
        path = write_pre_work(tmp_path, PreWorkResult())
        on_disk = json.loads(path.read_text())
        jsonschema.validate(on_disk, _load_schema("pre_work.schema.json"))


# ─── Engine: PRE_WORK is a recognized phase ───────────────────────────────


class TestPhaseRegistration:
    def test_pre_work_is_in_phase_enum(self) -> None:
        assert Phase.PRE_WORK.value == "PRE_WORK"

    def test_init_can_transition_to_pre_work(self) -> None:
        assert "PRE_WORK" in TRANSITIONS["INIT"]

    def test_pre_work_can_transition_to_design(self) -> None:
        assert "DESIGN" in TRANSITIONS["PRE_WORK"]

    def test_init_to_design_still_allowed(self) -> None:
        """Backward-compat: legacy campaigns can still skip PRE_WORK."""
        assert "DESIGN" in TRANSITIONS["INIT"]


# ─── Schema additions ─────────────────────────────────────────────────────


class TestSchemaAcceptsPreWorkPhase:
    def test_state_with_pre_work_phase_validates(self) -> None:
        state = {
            "last_entered_phase": "PRE_WORK",
            "iteration": 0,
            "run_id": "demo",
            "family": None,
            "timestamp": "2026-05-25T00:00:00Z",
        }
        jsonschema.validate(state, _load_schema("state.schema.json"))

    def test_legacy_state_without_pre_work_validates(self) -> None:
        state = {
            "last_entered_phase": "DESIGN",
            "iteration": 1,
            "run_id": "demo",
            "family": None,
            "timestamp": "2026-05-25T00:00:00Z",
        }
        jsonschema.validate(state, _load_schema("state.schema.json"))


class TestSchemaAcceptsPreWorkScript:
    def test_campaign_with_pre_work_script_validates(self) -> None:
        campaign = {
            "research_question": "q?",
            "run_id": "demo",
            "max_iterations": 1,
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "pre_work_script": "scripts/explore.py",
        }
        jsonschema.validate(campaign, _load_schema("campaign.schema.yaml"))

    def test_legacy_campaign_without_pre_work_script_validates(self) -> None:
        campaign = {
            "research_question": "q?",
            "run_id": "demo",
            "max_iterations": 1,
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
        }
        jsonschema.validate(campaign, _load_schema("campaign.schema.yaml"))

    def test_examples_campaign_yaml_still_validates(self) -> None:
        """Real-world examples/campaign.yaml passes the updated schema."""
        examples = (Path(__file__).resolve().parent.parent
                    / "examples" / "campaign.yaml")
        if not examples.exists():
            pytest.skip("examples/campaign.yaml not present")
        loaded = yaml.safe_load(examples.read_text())
        jsonschema.validate(loaded, _load_schema("campaign.schema.yaml"))


# ─── pre_work.schema.json shape ───────────────────────────────────────────


class TestPreWorkSchema:
    def test_empty_object_validates(self) -> None:
        jsonschema.validate({}, _load_schema("pre_work.schema.json"))

    def test_full_object_validates(self) -> None:
        payload = {
            "data_summary": {"rows": 100},
            "candidate_parameter_ranges": {"rate": [0.0, 10.0]},
            "structural_groupings": [{"name": "g1"}],
            "baseline_metrics": {"throughput": 100.0},
            "recommended_arms_for_iter1": ["arm description"],
        }
        jsonschema.validate(payload, _load_schema("pre_work.schema.json"))

    def test_unknown_top_level_field_rejected(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"surprise": "value"},
                _load_schema("pre_work.schema.json"),
            )
