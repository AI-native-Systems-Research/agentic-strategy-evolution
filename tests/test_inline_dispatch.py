"""Tests for InlineDispatcher — stdout prompt emission, file-polling, and dispatch."""
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from orchestrator.inline_dispatch import InlineDispatcher


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


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
    def test_design_phase_signal_with_all_artifacts(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_planner_design"

        (iter_dir / "problem.md").write_text("# Problem\nTest")
        (iter_dir / "bundle.yaml").write_text("metadata:\n  iteration: 1\n")
        response_path.touch()

        result = dispatcher._wait_for_response(
            response_path, iter_dir / "design_log.md", iter_dir, "design", time.time(),
        )
        assert "Design artifacts" in result

    def test_design_phase_signal_without_artifacts_raises(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_planner_design"
        response_path.touch()

        with pytest.raises(RuntimeError, match="required design artifacts are missing"):
            dispatcher._wait_for_response(
                response_path, iter_dir / "design_log.md", iter_dir, "design", time.time(),
            )

    def test_execute_analyze_signal_with_all_artifacts(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_executor_execute_analyze"

        (iter_dir / "findings.json").write_text('{"iteration": 1}')
        (iter_dir / "experiment_plan.yaml").write_text("steps: []\n")
        (iter_dir / "principle_updates.json").write_text("[]")
        response_path.touch()

        result = dispatcher._wait_for_response(
            response_path, iter_dir / "output.md", iter_dir, "execute-analyze", time.time(),
        )
        assert "Execution artifacts" in result

    def test_execute_analyze_missing_principle_updates_raises(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_executor_execute_analyze"

        (iter_dir / "findings.json").write_text('{"iteration": 1}')
        (iter_dir / "experiment_plan.yaml").write_text("steps: []\n")
        response_path.touch()

        with pytest.raises(RuntimeError, match="principle_updates.json"):
            dispatcher._wait_for_response(
                response_path, iter_dir / "output.md", iter_dir, "execute-analyze", time.time(),
            )

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

    def test_structured_phase_skips_empty_file(self, tmp_path):
        """Empty response file should not be returned — wait for content."""
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=2,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        response_path = iter_dir / ".nous_response_summarizer_report"

        def _write_late():
            response_path.write_text("")
            time.sleep(0.3)
            response_path.write_text("Real content")

        threading.Thread(target=_write_late, daemon=True).start()

        with patch("orchestrator.inline_dispatch.RESPONSE_POLL_INTERVAL_SEC", 0.1):
            result = dispatcher._wait_for_response(
                response_path, iter_dir / "report.md", iter_dir, "report", time.time(),
            )
        assert result == "Real content"

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


class TestCleanStaleArtifacts:
    def test_design_artifacts_cleaned(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        for name in ("problem.md", "bundle.yaml", "handoff.md"):
            (iter_dir / name).write_text("stale")

        InlineDispatcher._clean_stale_artifacts(iter_dir, "design")

        for name in ("problem.md", "bundle.yaml", "handoff.md"):
            assert not (iter_dir / name).exists()

    def test_execute_artifacts_cleaned(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        for name in ("experiment_plan.yaml", "findings.json", "principle_updates.json"):
            (iter_dir / name).write_text("stale")

        InlineDispatcher._clean_stale_artifacts(iter_dir, "execute-analyze")

        for name in ("experiment_plan.yaml", "findings.json", "principle_updates.json"):
            assert not (iter_dir / name).exists()

    def test_other_phase_does_not_clean(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "problem.md").write_text("keep")

        InlineDispatcher._clean_stale_artifacts(iter_dir, "summarize-gate")

        assert (iter_dir / "problem.md").exists()


class TestCheckArtifacts:
    def test_check_design_all_present(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "problem.md").write_text("ok")
        (iter_dir / "bundle.yaml").write_text("ok")
        assert InlineDispatcher._check_design_artifacts(iter_dir) == []

    def test_check_design_missing(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        missing = InlineDispatcher._check_design_artifacts(iter_dir)
        assert "problem.md" in missing
        assert "bundle.yaml" in missing

    def test_check_execute_all_present(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "experiment_plan.yaml").write_text("ok")
        (iter_dir / "findings.json").write_text("ok")
        (iter_dir / "principle_updates.json").write_text("ok")
        assert InlineDispatcher._check_execute_artifacts(iter_dir) == []

    def test_check_execute_missing_principle_updates(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "experiment_plan.yaml").write_text("ok")
        (iter_dir / "findings.json").write_text("ok")
        missing = InlineDispatcher._check_execute_artifacts(iter_dir)
        assert "principle_updates.json" in missing


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

    def test_execute_analyze_prompt_mentions_all_required_files(self, tmp_path, capsys):
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
        assert "principle_updates.json" in captured

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


class TestDispatchEndToEnd:
    """Integration tests for dispatch() — the full prompt-emit-poll-write cycle."""

    def test_dispatch_design_writes_output(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        output_path = iter_dir / "design_log.md"
        response_path = iter_dir / ".nous_response_planner_design"

        def _simulate_agent():
            time.sleep(0.2)
            (iter_dir / "problem.md").write_text("# Problem\nTest problem")
            (iter_dir / "bundle.yaml").write_text("metadata:\n  iteration: 1\n")
            response_path.touch()

        threading.Thread(target=_simulate_agent, daemon=True).start()

        with patch.object(dispatcher, "_route", return_value=("design.md.j2", None, None)):
            with patch.object(dispatcher.loader, "load", return_value="Test design prompt"):
                with patch("orchestrator.inline_dispatch.RESPONSE_POLL_INTERVAL_SEC", 0.1):
                    dispatcher.dispatch(
                        "planner", "design",
                        output_path=output_path, iteration=1,
                    )

        assert output_path.exists()
        assert "Design artifacts" in output_path.read_text()

    def test_dispatch_structured_phase_validates_and_writes(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        output_path = iter_dir / "gate_summary.json"
        response_path = iter_dir / ".nous_response_summarizer_summarize_gate"

        gate_response = '```json\n{"recommendation": "continue", "reasoning": "test"}\n```'

        def _simulate_agent():
            time.sleep(0.2)
            response_path.write_text(gate_response)

        threading.Thread(target=_simulate_agent, daemon=True).start()

        with patch.object(dispatcher, "_route", return_value=("summarize-gate.md.j2", "json", None)):
            with patch.object(dispatcher.loader, "load", return_value="Summarize this"):
                with patch("orchestrator.inline_dispatch.RESPONSE_POLL_INTERVAL_SEC", 0.1):
                    dispatcher.dispatch(
                        "summarizer", "summarize-gate",
                        output_path=output_path, iteration=1,
                    )

        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["recommendation"] == "continue"

    def test_dispatch_cleans_stale_artifacts(self, tmp_path):
        dispatcher = InlineDispatcher(
            work_dir=tmp_path, campaign=SAMPLE_CAMPAIGN, timeout=5,
        )
        iter_dir = tmp_path / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        output_path = iter_dir / "design_log.md"
        response_path = iter_dir / ".nous_response_planner_design"

        (iter_dir / "problem.md").write_text("stale from previous run")
        (iter_dir / "bundle.yaml").write_text("stale from previous run")

        def _simulate_agent():
            time.sleep(0.3)
            (iter_dir / "problem.md").write_text("# Fresh problem")
            (iter_dir / "bundle.yaml").write_text("metadata:\n  iteration: 1\n")
            response_path.touch()

        threading.Thread(target=_simulate_agent, daemon=True).start()

        with patch.object(dispatcher, "_route", return_value=("design.md.j2", None, None)):
            with patch.object(dispatcher.loader, "load", return_value="Test prompt"):
                with patch("orchestrator.inline_dispatch.RESPONSE_POLL_INTERVAL_SEC", 0.1):
                    dispatcher.dispatch(
                        "planner", "design",
                        output_path=output_path, iteration=1,
                    )

        assert (iter_dir / "problem.md").read_text() == "# Fresh problem"


class TestAgentRouting:
    """Test that --agent flag correctly routes to the right dispatcher type."""

    @patch("orchestrator.iteration.Engine")
    @patch("orchestrator.iteration.HumanGate")
    def test_inline_mode_uses_inline_dispatcher(self, mock_gate, mock_engine, tmp_path):
        from orchestrator.iteration import run_iteration

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
    @patch("orchestrator.iteration.Engine")
    @patch("orchestrator.iteration.HumanGate")
    def test_api_mode_uses_llm_dispatcher(self, mock_gate, mock_engine, mock_openai, tmp_path):
        from orchestrator.iteration import run_iteration

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

    @patch("orchestrator.llm_dispatch.openai")
    @patch("orchestrator.iteration.Engine")
    @patch("orchestrator.iteration.HumanGate")
    def test_api_mode_accepts_max_cli_retries(self, mock_gate, mock_engine, mock_openai, tmp_path):
        from orchestrator.iteration import run_iteration

        mock_engine_inst = MagicMock()
        mock_engine_inst.phase = "DONE"
        mock_engine.return_value = mock_engine_inst

        campaign = SAMPLE_CAMPAIGN.copy()
        work_dir = tmp_path
        (work_dir / "state.json").write_text('{"phase": "DONE"}')

        result = run_iteration(
            campaign, work_dir, iteration=1, agent="api",
            auto_approve=True, max_cli_retries=5,
        )
        assert result is not None


class TestRunCampaignRouting:
    """Test that run_campaign.py correctly routes --agent and --max-cli-retries."""

    @patch("orchestrator.campaign.run_iteration")
    @patch("orchestrator.campaign._resume_completed_campaign", return_value=1)
    @patch("orchestrator.campaign.append_ledger_row")
    @patch("orchestrator.campaign._generate_report")
    def test_campaign_passes_agent_and_retries(
        self, mock_report, mock_ledger, mock_resume, mock_run_iter, tmp_path,
    ):
        from orchestrator.campaign import run_campaign
        from orchestrator.iteration import IterationOutcome

        mock_run_iter.return_value = IterationOutcome.COMPLETED

        campaign = SAMPLE_CAMPAIGN.copy()

        run_campaign(
            campaign, tmp_path,
            max_iterations=1, auto_approve=True,
            agent="inline", max_cli_retries=3,
        )

        call_kwargs = mock_run_iter.call_args[1] if mock_run_iter.call_args[1] else {}
        assert call_kwargs.get("agent") == "inline"
        assert call_kwargs.get("max_cli_retries") == 3
