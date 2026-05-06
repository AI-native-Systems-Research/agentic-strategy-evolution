"""Tests for CLIDispatcher — claude -p subprocess invocation."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema
import pytest
import yaml

from orchestrator.protocols import Dispatcher


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


def _make_campaign(repo_path: str = "/tmp/fake-repo") -> dict:
    return {
        "research_question": "Does batch size affect latency?",
        "target_system": {
            "name": "TestSystem",
            "description": "A test system.",
            "repo_path": repo_path,
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


# Default campaign for tests that don't need a real repo_path
SAMPLE_CAMPAIGN = _make_campaign()

VALID_BUNDLE_YAML = """\
metadata:
  iteration: 1
  family: test-family
  research_question: "Does batch size affect latency?"
arms:
  - type: h-main
    prediction: "latency decreases by 20%"
    mechanism: "Larger batches amortize overhead"
    diagnostic: "Check overhead distribution"
  - type: h-control-negative
    prediction: "no effect at batch_size=1"
    mechanism: "No batching means no amortization"
    diagnostic: "Verify single-item path"
"""

VALID_FINDINGS_JSON = json.dumps({
    "iteration": 1,
    "bundle_ref": "runs/iter-1/bundle.yaml",
    "experiment_valid": True,
    "arms": [
        {
            "arm_type": "h-main",
            "predicted": "latency decreases by 20%",
            "observed": "latency decreased by 18%",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": None,
        },
        {
            "arm_type": "h-control-negative",
            "predicted": "no effect at batch_size=1",
            "observed": "no significant change",
            "status": "CONFIRMED",
            "error_type": None,
            "diagnostic_note": None,
        },
    ],
    "discrepancy_analysis": "All arms confirmed.",
    "dominant_component_pct": None,
}, indent=2)


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    """Create a work directory with minimal structure and a real repo_path dir."""
    iter_dir = tmp_path / "runs" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "problem.md").write_text(
        "# Problem Framing\n\n## Research Question\n"
        "Does batch size affect latency?\n"
    )
    (iter_dir / "bundle.yaml").write_text(VALID_BUNDLE_YAML)
    (iter_dir / "findings.json").write_text(VALID_FINDINGS_JSON)
    (tmp_path / "principles.json").write_text(
        json.dumps({"principles": []}, indent=2)
    )
    # Create a real repo_path directory so CLIDispatcher cwd validation passes
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    return tmp_path


@pytest.fixture()
def campaign(work_dir: Path) -> dict:
    """Campaign with repo_path pointing to a real directory."""
    return _make_campaign(repo_path=str(work_dir / "repo"))


class TestCLIDispatcherProtocol:
    def test_satisfies_dispatcher_protocol(self, work_dir: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher
        d = CLIDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN)
        assert isinstance(d, Dispatcher)


class TestCLIDispatcherUnit:
    """Unit tests with mocked subprocess."""

    def test_dispatch_planner_design_writes_raw_output(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        raw_design_text = (
            "# Experiment Design\n\n"
            "## Research Question\nDoes batch size affect latency?\n\n"
            "## Arms\n- h-main: larger batches amortize overhead\n"
            "- h-control-negative: no effect at batch_size=1\n"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = raw_design_text
        mock_result.stderr = ""

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        assert out.exists()
        content = out.read_text()
        assert "Experiment Design" in content
        assert "Research Question" in content

    def test_dispatch_executor_execute_analyze_produces_valid_output(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        valid_json = json.dumps({
            "plan": {
                "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
                "arms": [{"arm_id": "h-main", "conditions": [{"name": "baseline", "cmd": "echo baseline"}]}],
            },
            "findings": {
                "iteration": 1,
                "bundle_ref": "runs/iter-1/bundle.yaml",
                "arms": [{"arm_type": "h-main", "predicted": "lower latency", "observed": "10ms reduction", "status": "CONFIRMED", "error_type": None, "diagnostic_note": None}],
                "experiment_valid": True,
                "discrepancy_analysis": "None.",
            },
            "principle_updates": [{
                "id": "RP-1", "statement": "Test principle", "confidence": "medium",
                "regime": "all", "evidence": ["iteration-1-h-main"], "contradicts": [],
                "extraction_iteration": 1, "mechanism": "test", "applicability_bounds": "test",
                "superseded_by": None, "category": "domain", "status": "active",
            }],
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = f"```json\n{valid_json}\n```\n"
        mock_result.stderr = ""

        # Create bundle.yaml (required by context builder)
        (work_dir / "runs" / "iter-1").mkdir(parents=True, exist_ok=True)
        (work_dir / "runs" / "iter-1" / "bundle.yaml").write_text("metadata:\n  iteration: 1\n")

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "execute_analyze_output.json"
            d.dispatch("executor", "execute-analyze", output_path=out, iteration=1)

        assert out.exists()
        data = json.loads(out.read_text())
        assert "plan" in data
        assert "findings" in data
        assert "principle_updates" in data

    def test_dispatch_planner_design_writes_response_text(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        response_text = "# Design Output\n\nThis is the raw design response.\n"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = response_text
        mock_result.stderr = ""

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design_out.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        assert out.exists()
        assert out.read_text() == response_text

    def test_claude_not_found_raises(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            side_effect=FileNotFoundError("claude not found"),
        ):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            with pytest.raises(RuntimeError, match="claude.*not found"):
                d.dispatch(
                    "planner", "design",
                    output_path=work_dir / "out.md", iteration=1,
                )

    def test_claude_nonzero_exit_raises(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: API key not set"

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            with pytest.raises(RuntimeError, match="claude.*exited.*1"):
                d.dispatch(
                    "planner", "design",
                    output_path=work_dir / "out.md", iteration=1,
                )

    def test_prompt_includes_campaign_context(self, work_dir: Path, campaign: dict) -> None:
        """The system prompt passed to claude -p should include campaign info."""
        from orchestrator.cli_dispatch import CLIDispatcher

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "# Design\nStub."
        mock_result.stderr = ""

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch(
                "planner", "design",
                output_path=work_dir / "out.md", iteration=1,
            )

        call_kwargs = mock_run.call_args
        stdin_text = call_kwargs.kwargs.get("input") or call_kwargs[1].get("input", "")
        assert "TestSystem" in stdin_text

    def test_uses_repo_path_as_cwd(self, work_dir: Path, tmp_path: Path) -> None:
        """When repo_path is set, claude -p runs with that as cwd."""
        from orchestrator.cli_dispatch import CLIDispatcher

        repo_dir = tmp_path / "fake-repo"
        repo_dir.mkdir()
        campaign = {
            **SAMPLE_CAMPAIGN,
            "target_system": {
                **SAMPLE_CAMPAIGN["target_system"],
                "repo_path": str(repo_dir),
            },
        }

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "# Design\nStub."
        mock_result.stderr = ""

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch(
                "planner", "design",
                output_path=work_dir / "out.md", iteration=1,
            )

        call_kwargs = mock_run.call_args
        cwd_used = call_kwargs.kwargs.get("cwd") or call_kwargs[1].get("cwd")
        assert str(cwd_used) == str(repo_dir)

    def test_unknown_role_phase_raises(self, work_dir: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        d = CLIDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN)
        with pytest.raises(ValueError, match="Unknown role/phase"):
            d.dispatch("wizard", "conjure", output_path=work_dir / "x", iteration=1)

    def test_configurable_timeout(self, work_dir: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        d = CLIDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, timeout=120)
        assert d.timeout == 120

    def test_override_cwd_changes_subprocess_cwd(self, work_dir: Path, tmp_path: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        repo_dir = tmp_path / "fake-repo"
        repo_dir.mkdir()
        override_dir = tmp_path / "worktree"
        override_dir.mkdir()

        campaign = {
            **SAMPLE_CAMPAIGN,
            "target_system": {
                **SAMPLE_CAMPAIGN["target_system"],
                "repo_path": str(repo_dir),
            },
        }

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "# Design\nStub."
        mock_result.stderr = ""

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            with d.override_cwd(override_dir):
                d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        call_kwargs = mock_run.call_args
        cwd_used = call_kwargs.kwargs.get("cwd") or call_kwargs[1].get("cwd")
        assert str(cwd_used) == str(override_dir)

    def test_override_cwd_restores_original(self, work_dir: Path, tmp_path: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        repo_dir = tmp_path / "fake-repo"
        repo_dir.mkdir()
        override_dir = tmp_path / "worktree"
        override_dir.mkdir()

        campaign = {
            **SAMPLE_CAMPAIGN,
            "target_system": {
                **SAMPLE_CAMPAIGN["target_system"],
                "repo_path": str(repo_dir),
            },
        }

        d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
        original_cwd = d._cwd

        with d.override_cwd(override_dir):
            assert d._cwd == override_dir

        assert d._cwd == original_cwd
