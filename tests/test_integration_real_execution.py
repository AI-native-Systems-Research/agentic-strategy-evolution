"""Integration tests for real experiment execution flow."""
import json
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from run_iteration import run_experiment_commands

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


# ------------------------------------------------------------------
# Fake simulator: a script that writes known metrics JSON
# ------------------------------------------------------------------

FAKE_SIMULATOR_SCRIPT = """\
#!/usr/bin/env python3
import json, sys

# Parse --metrics-path from args
metrics_path = None
args = sys.argv[1:]
for i, arg in enumerate(args):
    if arg == "--metrics-path" and i + 1 < len(args):
        metrics_path = args[i + 1]

if not metrics_path:
    print("Error: --metrics-path required", file=sys.stderr)
    sys.exit(1)

metrics = {
    "ttft_p99_ms": 250.8,
    "e2e_p99_ms": 5678.9,
    "responses_per_sec": 47.6,
    "completed_requests": 500,
}

# If --batch-size is in args, adjust metrics
if "--batch-size" in args:
    idx = args.index("--batch-size")
    bs = int(args[idx + 1])
    if bs > 1:
        metrics["ttft_p99_ms"] = 200.0  # improved
    else:
        metrics["ttft_p99_ms"] = 250.8  # unchanged

with open(metrics_path, "w") as f:
    json.dump(metrics, f, indent=2)
"""


@pytest.fixture
def fake_simulator(tmp_path):
    """Create a fake simulator script."""
    script = tmp_path / "sim"
    script.write_text(FAKE_SIMULATOR_SCRIPT)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


# ------------------------------------------------------------------
# Mock LLM helpers
# ------------------------------------------------------------------

EXPERIMENT_PLAN = {
    "baseline": {
        "description": "Default config baseline",
        "command": "{simulator} --metrics-path {metrics_path}",
    },
    "experiments": [
        {
            "arm_type": "h-main",
            "description": "Test batch size doubling",
            "config_changes": "Added --batch-size 64",
            "command": "{simulator} --batch-size 64 --metrics-path {metrics_path}",
        },
        {
            "arm_type": "h-control-negative",
            "description": "Single item batch",
            "config_changes": "Set --batch-size 1",
            "command": "{simulator} --batch-size 1 --metrics-path {metrics_path}",
        },
    ],
}

FINDINGS = {
    "iteration": 1,
    "bundle_ref": "runs/iter-1/bundle.yaml",
    "arms": [
        {
            "arm_type": "h-main",
            "predicted": "latency decreases by 20%",
            "observed": "TTFT P99 decreased from 250.8ms to 200.0ms (20.2% reduction)",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": "Real metrics confirm batch amortization.",
        },
        {
            "arm_type": "h-control-negative",
            "predicted": "no effect at batch_size=1",
            "observed": "TTFT P99 unchanged at 250.8ms",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": None,
        },
    ],
    "discrepancy_analysis": "All arms confirmed by real experiment data.",
    "dominant_component_pct": None,
}

BUNDLE_YAML = """\
metadata:
  iteration: 1
  family: test-family
  research_question: "Does batch size affect latency?"
arms:
  - type: h-main
    prediction: "latency decreases by 20% when batch_size doubles"
    mechanism: "Larger batches amortize fixed overhead"
    diagnostic: "Check if overhead is actually fixed"
  - type: h-control-negative
    prediction: "no effect at batch_size=1"
    mechanism: "No batching means no amortization"
    diagnostic: "Verify single-item path"
"""


def make_mock_completion(responses: list[str]):
    idx = {"n": 0}
    def mock_fn(**kwargs):
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=responses[idx["n"]]))]
        idx["n"] += 1
        return resp
    return mock_fn


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestRunExperimentCommands:
    """Test the command execution helper directly."""

    def test_runs_baseline_and_arms(self, fake_simulator, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)

        plan = {
            "baseline": {
                "description": "baseline",
                "command": f"{sys.executable} {fake_simulator} --metrics-path {{metrics_path}}",
            },
            "experiments": [
                {
                    "arm_type": "h-main",
                    "description": "batch 64",
                    "command": f"{sys.executable} {fake_simulator} --batch-size 64 --metrics-path {{metrics_path}}",
                },
            ],
        }
        results = run_experiment_commands(
            plan, work_dir=tmp_path, iter_dir=iter_dir, timeout=30,
        )
        assert "baseline" in results
        assert "h-main" in results
        assert results["baseline"]["ttft_p99_ms"] == 250.8
        assert results["h-main"]["ttft_p99_ms"] == 200.0

    def test_command_failure_raises(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)

        plan = {
            "baseline": {
                "description": "will fail",
                "command": f"{sys.executable} -c \"import sys; sys.exit(1)\" --metrics-path {{metrics_path}}",
            },
            "experiments": [
                {"arm_type": "h-main", "description": "x", "command": "echo {metrics_path}"},
            ],
        }
        with pytest.raises(RuntimeError, match="Command failed"):
            run_experiment_commands(plan, work_dir=tmp_path, iter_dir=iter_dir, timeout=30)

    def test_timeout_raises(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)

        plan = {
            "baseline": {
                "description": "will timeout",
                "command": f"{sys.executable} -c \"import time; time.sleep(10)\" --metrics-path {{metrics_path}}",
            },
            "experiments": [
                {"arm_type": "h-main", "description": "x", "command": "echo {metrics_path}"},
            ],
        }
        with pytest.raises(RuntimeError, match="timed out"):
            run_experiment_commands(plan, work_dir=tmp_path, iter_dir=iter_dir, timeout=1)

    def test_missing_metrics_file_raises(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)

        # Command succeeds but doesn't write metrics (placeholder present but ignored)
        plan = {
            "baseline": {
                "description": "no metrics",
                "command": f"{sys.executable} -c \"print('ok')\" --dummy {{metrics_path}}",
            },
            "experiments": [
                {"arm_type": "h-main", "description": "x", "command": "echo {metrics_path}"},
            ],
        }
        with pytest.raises(RuntimeError, match="Metrics file not found"):
            run_experiment_commands(plan, work_dir=tmp_path, iter_dir=iter_dir, timeout=30)

    def test_invalid_json_metrics_raises(self, fake_simulator, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)

        # Write a script that produces invalid JSON
        bad_script = tmp_path / "bad_sim"
        bad_script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "mp = sys.argv[sys.argv.index('--metrics-path')+1]\n"
            "open(mp, 'w').write('not valid json')\n"
        )
        bad_script.chmod(bad_script.stat().st_mode | stat.S_IEXEC)

        plan = {
            "baseline": {
                "description": "bad json",
                "command": f"{sys.executable} {bad_script} --metrics-path {{metrics_path}}",
            },
            "experiments": [
                {"arm_type": "h-main", "description": "x",
                 "command": f"{sys.executable} {fake_simulator} --metrics-path {{metrics_path}}"},
            ],
        }
        with pytest.raises(RuntimeError, match="invalid JSON"):
            run_experiment_commands(plan, work_dir=tmp_path, iter_dir=iter_dir, timeout=30)


class TestFullRealExecutionIteration:
    """End-to-end test with fake simulator and mocked LLM."""

    def test_real_execution_path_direct(self, fake_simulator, tmp_path, monkeypatch):
        """Test the real execution path by exercising run_experiment_commands
        and the LLMDispatcher routes end-to-end."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)

        # Write bundle
        (iter_dir / "bundle.yaml").write_text(BUNDLE_YAML)
        (work_dir / "principles.json").write_text(json.dumps({"principles": []}, indent=2))

        sim_path = f"{sys.executable} {fake_simulator}"

        campaign = {
            "research_question": "Does batch size affect latency?",
            "target_system": {
                "name": "TestSystem",
                "description": "Test system with fake simulator.",
                "observable_metrics": ["ttft_p99_ms"],
                "controllable_knobs": ["batch_size"],
                "execution": {
                    "run_command": f"{sim_path} --metrics-path {{metrics_path}}",
                    "repo_path": None,
                    "timeout": 30,
                },
            },
            "review": {
                "design_perspectives": ["rigor"],
                "findings_perspectives": ["rigor"],
                "max_review_rounds": 1,
            },
            "prompts": {
                "methodology_layer": "prompts/methodology",
                "domain_adapter_layer": None,
            },
        }

        # Step 1: LLM designs experiment plan
        plan_with_sim = json.loads(json.dumps(EXPERIMENT_PLAN).replace("{simulator}", sim_path))
        plan_response = f"```json\n{json.dumps(plan_with_sim, indent=2)}\n```"

        from orchestrator.llm_dispatch import LLMDispatcher
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=campaign,
            completion_fn=make_mock_completion([plan_response]),
        )
        d.dispatch("executor", "run-plan", output_path=iter_dir / "experiment_plan.json", iteration=1)

        plan = json.loads((iter_dir / "experiment_plan.json").read_text())
        plan_schema = load_schema("experiment_plan.schema.json")
        jsonschema.validate(plan, plan_schema)

        # Step 2: Run commands, collect metrics
        results = run_experiment_commands(plan, work_dir=tmp_path, iter_dir=iter_dir, timeout=30)
        assert results["baseline"]["ttft_p99_ms"] == 250.8
        assert results["h-main"]["ttft_p99_ms"] == 200.0
        assert results["h-control-negative"]["ttft_p99_ms"] == 250.8

        # Write results to disk
        from orchestrator.util import atomic_write
        atomic_write(
            iter_dir / "experiment_results.json",
            json.dumps(results, indent=2) + "\n",
        )

        # Step 3: LLM analyzes real metrics
        analyze_response = f"```json\n{json.dumps(FINDINGS, indent=2)}\n```"
        d2 = LLMDispatcher(
            work_dir=work_dir,
            campaign=campaign,
            completion_fn=make_mock_completion([analyze_response]),
        )
        d2.dispatch("executor", "run-analyze", output_path=iter_dir / "findings.json", iteration=1)

        findings = json.loads((iter_dir / "findings.json").read_text())
        findings_schema = load_schema("findings.schema.json")
        jsonschema.validate(findings, findings_schema)
        assert findings["arms"][0]["status"] == "CONFIRMED"


class TestAnalysisModeFallback:
    """Verify analysis mode still works with no execution config."""

    def test_no_execution_config_uses_analysis_mode(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "bundle.yaml").write_text(BUNDLE_YAML)
        (work_dir / "principles.json").write_text(json.dumps({"principles": []}, indent=2))

        campaign_no_exec = {
            "research_question": "Test?",
            "target_system": {
                "name": "TestSystem",
                "description": "Test.",
                "observable_metrics": ["latency_ms"],
                "controllable_knobs": ["config"],
            },
            "review": {
                "design_perspectives": ["rigor"],
                "findings_perspectives": ["rigor"],
                "max_review_rounds": 1,
            },
            "prompts": {
                "methodology_layer": "prompts/methodology",
                "domain_adapter_layer": None,
            },
        }

        findings_json = json.dumps({
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "arms": [
                {
                    "arm_type": "h-main",
                    "predicted": "latency decreases",
                    "observed": "analysis suggests decrease",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": "Analysis mode.",
                },
                {
                    "arm_type": "h-control-negative",
                    "predicted": "no effect",
                    "observed": "no effect expected",
                    "status": "CONFIRMED",
                    "error_type": None,
                    "diagnostic_note": None,
                },
            ],
            "discrepancy_analysis": "Analysis mode findings.",
            "dominant_component_pct": None,
        }, indent=2)

        response = f"```json\n{findings_json}\n```"

        from orchestrator.llm_dispatch import LLMDispatcher
        d = LLMDispatcher(
            work_dir=work_dir,
            campaign=campaign_no_exec,
            completion_fn=make_mock_completion([response]),
        )
        d.dispatch("executor", "run", output_path=iter_dir / "findings.json", iteration=1)
        assert (iter_dir / "findings.json").exists()
        # No experiment_plan.json or experiment_results.json should exist
        assert not (iter_dir / "experiment_plan.json").exists()
        assert not (iter_dir / "experiment_results.json").exists()


# ---------------------------------------------------------------------------
# Resume logic tests
# ---------------------------------------------------------------------------

from run_iteration import (
    _enter_phase, _PHASE_ORDER, _PHASE_INDEX,
    run_iteration, IterationOutcome, setup_work_dir,
)
from orchestrator.engine import Engine, Phase


class TestEnterPhase:
    """Tests for _enter_phase resume logic."""

    def test_skip_past_phase(self, tmp_path):
        """When engine is past a phase, _enter_phase returns False (skip)."""
        state = {
            "phase": "RUNNING", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "FRAMING") is False
        assert _enter_phase(engine, "DESIGN") is False
        assert _enter_phase(engine, "HUMAN_DESIGN_GATE") is False
        assert engine.phase == "RUNNING"  # unchanged

    def test_redo_current_phase(self, tmp_path):
        """When engine is at a phase, _enter_phase returns True without transition."""
        state = {
            "phase": "RUNNING", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "RUNNING") is True
        assert engine.phase == "RUNNING"  # no transition happened

    def test_advance_to_next_phase(self, tmp_path):
        """When engine is before a phase, _enter_phase transitions and returns True."""
        state = {
            "phase": "INIT", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "FRAMING") is True
        assert engine.phase == "FRAMING"

    def test_done_skips_everything(self, tmp_path):
        """When engine is DONE, all phases are skipped."""
        state = {
            "phase": "DONE", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        for phase in _PHASE_ORDER:
            assert _enter_phase(engine, phase) is (phase == "DONE")

    def test_phase_order_matches_engine_phases(self):
        """_PHASE_ORDER must contain exactly the same phases as the engine."""
        engine_phases = {p.value for p in Phase}
        order_phases = set(_PHASE_ORDER)
        assert engine_phases == order_phases, (
            f"Mismatch: engine has {engine_phases - order_phases}, "
            f"_PHASE_ORDER has {order_phases - engine_phases}"
        )

    def test_fast_fail_resume_from_findings_review(self, tmp_path):
        """Resuming at FINDINGS_REVIEW skips RUNNING and earlier phases."""
        state = {
            "phase": "FINDINGS_REVIEW", "iteration": 0,
            "run_id": "test", "family": None, "timestamp": "t",
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        engine = Engine(tmp_path)

        assert _enter_phase(engine, "RUNNING") is False
        assert _enter_phase(engine, "FINDINGS_REVIEW") is True
        assert engine.phase == "FINDINGS_REVIEW"
        # Can advance to next
        assert _enter_phase(engine, "HUMAN_FINDINGS_GATE") is True
        assert engine.phase == "HUMAN_FINDINGS_GATE"


# ---------------------------------------------------------------------------
# IterationOutcome tests
# ---------------------------------------------------------------------------

from orchestrator.dispatch import StubDispatcher
import warnings


def _setup_stub_iteration(tmp_path, monkeypatch):
    """Prepare a work_dir with stub dispatcher for testing run_iteration outcomes."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    # Copy templates
    import shutil
    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    for t in ["state.json", "ledger.json", "principles.json"]:
        shutil.copy(templates_dir / t, work_dir / t)
    state = json.loads((work_dir / "state.json").read_text())
    state["run_id"] = "test"
    (work_dir / "state.json").write_text(json.dumps(state, indent=2))

    campaign = {
        "research_question": "Test question?",
        "target_system": {
            "name": "TestSystem",
            "description": "Test system.",
            "observable_metrics": ["latency_ms"],
            "controllable_knobs": ["config"],
        },
        "review": {
            "design_perspectives": ["rigor"],
            "findings_perspectives": ["rigor"],
            "max_review_rounds": 1,
        },
        "prompts": {
            "methodology_layer": "prompts/methodology",
            "domain_adapter_layer": None,
        },
    }

    # Monkeypatch LLMDispatcher -> StubDispatcher in run_iteration module
    import run_iteration as ri
    def stub_factory(work_dir, campaign, model=None):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return StubDispatcher(work_dir)

    monkeypatch.setattr(ri, "LLMDispatcher", stub_factory)
    return work_dir, campaign


class TestIterationOutcome:
    """Test that run_iteration returns correct IterationOutcome values."""

    def test_returns_completed_by_default(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value="approve")))

        result = run_iteration(campaign, work_dir, iteration=1)

        assert result == IterationOutcome.COMPLETED
        engine = Engine(work_dir)
        assert engine.phase == "DONE"

    def test_returns_continue_when_not_final(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value="approve")))

        result = run_iteration(campaign, work_dir, iteration=1, final=False)

        assert result == IterationOutcome.CONTINUE
        engine = Engine(work_dir)
        assert engine.phase == "EXTRACTION"

    def test_returns_aborted_on_design_gate_abort(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value="abort")))

        result = run_iteration(campaign, work_dir, iteration=1)

        assert result == IterationOutcome.ABORTED

    def test_returns_redesign_on_design_gate_reject(self, tmp_path, monkeypatch):
        work_dir, campaign = _setup_stub_iteration(tmp_path, monkeypatch)
        import run_iteration as ri
        monkeypatch.setattr(ri, "HumanGate", lambda: MagicMock(prompt=MagicMock(return_value="reject")))

        result = run_iteration(campaign, work_dir, iteration=1)

        assert result == IterationOutcome.REDESIGN
