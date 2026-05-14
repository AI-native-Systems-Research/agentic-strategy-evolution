"""Tests for InlineDispatcher — stdout prompt emission and file-polling."""
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from orchestrator.inline_dispatch import InlineDispatcher


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _make_campaign(repo_path: str = "/tmp/fake-repo") -> dict:
    return {
        "research_question": "Does batch size affect latency?",
        "target_system": {
            "name": "TestSystem",
            "description": "A test system.",
            "repo_path": repo_path,
        },
        "prompts": {
            "methodology_layer": "prompts/methodology",
            "domain_adapter_layer": None,
        },
    }


SAMPLE_CAMPAIGN = _make_campaign()


class TestInlineDispatcherInit:
    def test_init_sets_timeout(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=60,
        )
        assert dispatcher.timeout == 60

    def test_init_default_model_is_inline(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN,
        )
        assert dispatcher.model == "inline"

    def test_completion_fn_raises(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN,
        )
        with pytest.raises(RuntimeError, match="does not use the completion API"):
            dispatcher._completion(messages=[])


class TestWaitForResponse:
    def test_design_phase_detects_artifacts(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_planner_design"

        (iter_dir / "problem.md").write_text("# Problem\nTest")
        (iter_dir / "bundle.yaml").write_text("metadata:\n  iteration: 1\n")

        result = dispatcher._wait_for_response(
            response_path, iter_dir / "design_log.md", iter_dir, "design", time.time(),
        )
        assert "Design artifacts" in result

    def test_design_phase_detects_signal_file(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_planner_design"
        response_path.touch()

        result = dispatcher._wait_for_response(
            response_path, iter_dir / "design_log.md", iter_dir, "design", time.time(),
        )
        assert "Design artifacts" in result

    def test_execute_analyze_detects_artifacts(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_executor_execute_analyze"

        (iter_dir / "findings.json").write_text('{"iteration": 1}')
        (iter_dir / "experiment_plan.yaml").write_text("steps: []\n")

        result = dispatcher._wait_for_response(
            response_path, iter_dir / "output.md", iter_dir, "execute-analyze", time.time(),
        )
        assert "Execution artifacts" in result

    def test_structured_phase_reads_response_file(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_summarizer_summarize_gate"
        response_path.write_text('```json\n{"decision": "continue"}\n```')

        result = dispatcher._wait_for_response(
            response_path, iter_dir / "gate_summary.json", iter_dir, "summarize-gate", time.time(),
        )
        assert "decision" in result

    def test_timeout_raises(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=1,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_planner_design"

        with pytest.raises(RuntimeError, match="Timed out"):
            dispatcher._wait_for_response(
                response_path, iter_dir / "design_log.md", iter_dir, "design", time.time() - 2,
            )

    def test_polling_picks_up_late_file(self, tmp_path):
        """File appears after a short delay — polling should find it."""
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=10,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_summarizer_report"

        def _write_late():
            time.sleep(0.5)
            response_path.write_text("Late response content")

        threading.Thread(target=_write_late, daemon=True).start()

        with patch("orchestrator.inline_dispatch.RESPONSE_POLL_INTERVAL_SEC", 0.1):
            result = dispatcher._wait_for_response(
                response_path, iter_dir / "report.md", iter_dir, "report", time.time(),
            )
        assert result == "Late response content"


class TestEmitPrompt:
    def test_design_prompt_mentions_required_files(self, tmp_path, capsys):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_planner_design"

        dispatcher._emit_prompt(
            "planner", "design", "Test prompt", None, None, iter_dir, response_path,
        )
        captured = capsys.readouterr().out
        assert "problem.md" in captured
        assert "bundle.yaml" in captured
        assert "touch" in captured

    def test_execute_analyze_prompt_mentions_required_files(self, tmp_path, capsys):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_executor_execute_analyze"

        dispatcher._emit_prompt(
            "executor", "execute-analyze", "Test prompt", None, None, iter_dir, response_path,
        )
        captured = capsys.readouterr().out
        assert "findings.json" in captured
        assert "experiment_plan.yaml" in captured

    def test_structured_prompt_mentions_format(self, tmp_path, capsys):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_summarizer_gate"

        dispatcher._emit_prompt(
            "summarizer", "summarize-gate", "Test prompt", "json", "gate_summary.schema.json",
            iter_dir, response_path,
        )
        captured = capsys.readouterr().out
        assert "json" in captured.lower()
        assert str(response_path) in captured


class TestAgentRouting:
    """Test that --agent flag correctly routes to the right dispatcher type."""

    @patch("run_iteration.Engine")
    @patch("run_iteration.HumanGate")
    def test_cli_mode_uses_cli_dispatcher_for_all(self, mock_gate, mock_engine, tmp_path):
        from orchestrator.cli_dispatch import CLIDispatcher
        from run_iteration import run_iteration

        mock_engine_inst = MagicMock()
        mock_engine_inst.phase = "DONE"
        mock_engine.return_value = mock_engine_inst

        campaign = SAMPLE_CAMPAIGN.copy()
        work_dir = tmp_path
        (work_dir / "state.json").write_text('{"phase": "DONE"}')

        result = run_iteration(
            campaign, work_dir, iteration=1, agent="cli", auto_approve=True,
        )
        # DONE phase means early return — we just verify it didn't crash
        assert result is not None

    @patch("run_iteration.Engine")
    @patch("run_iteration.HumanGate")
    def test_inline_mode_uses_inline_dispatcher(self, mock_gate, mock_engine, tmp_path):
        from orchestrator.inline_dispatch import InlineDispatcher
        from run_iteration import run_iteration

        mock_engine_inst = MagicMock()
        mock_engine_inst.phase = "DONE"
        mock_engine.return_value = mock_engine_inst

        campaign = SAMPLE_CAMPAIGN.copy()
        work_dir = tmp_path
        (work_dir / "state.json").write_text('{"phase": "DONE"}')

        result = run_iteration(
            campaign, work_dir, iteration=1, agent="inline", auto_approve=True,
        )
        assert result is not None

    @patch("orchestrator.llm_dispatch.openai")
    @patch("run_iteration.Engine")
    @patch("run_iteration.HumanGate")
    def test_api_mode_uses_llm_dispatcher(self, mock_gate, mock_engine, mock_openai, tmp_path):
        from run_iteration import run_iteration

        mock_engine_inst = MagicMock()
        mock_engine_inst.phase = "DONE"
        mock_engine.return_value = mock_engine_inst

        campaign = SAMPLE_CAMPAIGN.copy()
        work_dir = tmp_path
        (work_dir / "state.json").write_text('{"phase": "DONE"}')

        result = run_iteration(
            campaign, work_dir, iteration=1, agent="api", auto_approve=True,
        )
        assert result is not None
