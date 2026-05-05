"""Tests for orchestrator/metrics.py — LLM cost/token logging."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from orchestrator.metrics import log_metrics, summarize_metrics


@pytest.fixture
def metrics_path(tmp_path):
    return tmp_path / "llm_metrics.jsonl"


class TestLogMetrics:
    def test_creates_file_and_appends(self, metrics_path):
        log_metrics(metrics_path, {"dispatcher": "cli", "role": "planner", "phase": "frame", "input_tokens": 100})
        log_metrics(metrics_path, {"dispatcher": "llm", "role": "reviewer", "phase": "review-design", "input_tokens": 50})

        lines = metrics_path.read_text().splitlines()
        assert len(lines) == 2
        entry1 = json.loads(lines[0])
        assert entry1["dispatcher"] == "cli"
        assert entry1["input_tokens"] == 100
        assert "timestamp" in entry1

    def test_preserves_existing_timestamp(self, metrics_path):
        log_metrics(metrics_path, {"timestamp": "2026-01-01T00:00:00Z", "input_tokens": 10})
        entry = json.loads(metrics_path.read_text().strip())
        assert entry["timestamp"] == "2026-01-01T00:00:00Z"


class TestSummarizeMetrics:
    def test_empty_file(self, metrics_path):
        summary = summarize_metrics(metrics_path)
        assert summary["total_calls"] == 0
        assert summary["total_cost_usd"] == 0

    def test_aggregates_correctly(self, metrics_path):
        entries = [
            {"dispatcher": "cli", "role": "planner", "phase": "frame", "input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.05, "duration_ms": 5000},
            {"dispatcher": "cli", "role": "executor", "phase": "plan-execution", "input_tokens": 2000, "output_tokens": 500, "cost_usd": 0.10, "duration_ms": 8000},
            {"dispatcher": "llm", "role": "reviewer", "phase": "review-design", "input_tokens": 800, "output_tokens": 300, "cost_usd": None, "duration_ms": 3000},
            {"dispatcher": "llm", "role": "extractor", "phase": "extract", "input_tokens": 600, "output_tokens": 150, "cost_usd": None, "duration_ms": 2000},
        ]
        for e in entries:
            log_metrics(metrics_path, e)

        summary = summarize_metrics(metrics_path)
        assert summary["total_calls"] == 4
        assert abs(summary["total_cost_usd"] - 0.15) < 1e-9
        assert summary["total_input_tokens"] == 4400
        assert summary["total_output_tokens"] == 1150
        assert summary["total_duration_ms"] == 18000

        # by_phase
        assert summary["by_phase"]["frame"]["calls"] == 1
        assert summary["by_phase"]["plan-execution"]["cost_usd"] == 0.10
        assert summary["by_phase"]["review-design"]["input_tokens"] == 800

        # by_dispatcher
        assert summary["by_dispatcher"]["cli"]["calls"] == 2
        assert summary["by_dispatcher"]["llm"]["calls"] == 2
        assert abs(summary["by_dispatcher"]["cli"]["cost_usd"] - 0.15) < 1e-9

    def test_handles_none_cost(self, metrics_path):
        """cost_usd=None (from LLM API calls) should be treated as 0."""
        log_metrics(metrics_path, {"cost_usd": None, "input_tokens": 100, "output_tokens": 50, "duration_ms": 1000, "dispatcher": "llm", "phase": "design", "role": "planner"})
        summary = summarize_metrics(metrics_path)
        assert summary["total_cost_usd"] == 0


class TestCLIDispatcherMetrics:
    """Test that CLIDispatcher correctly parses --output-format=json and logs metrics."""

    def test_json_output_parsed_and_logged(self, tmp_path):
        from orchestrator.cli_dispatch import CLIDispatcher

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "runs" / "iter-1").mkdir(parents=True)
        (work_dir / "runs" / "iter-1" / "problem.md").write_text(
            "# Problem\n\n## Research Question\nTest question\n"
        )
        (work_dir / "runs" / "iter-1" / "bundle.yaml").write_text(
            "metadata:\n  iteration: 1\n  family: test\n  research_question: test\n"
            "arms:\n  - type: h-main\n    prediction: test\n    mechanism: test\n    diagnostic: test\n"
            "  - type: h-control-negative\n    prediction: test\n    mechanism: test\n    diagnostic: test\n"
        )
        (work_dir / "principles.json").write_text('{"principles": []}')

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        campaign = {
            "research_question": "Test?",
            "target_system": {"name": "T", "description": "D", "repo_path": str(repo_dir)},
            "review": {"design_perspectives": ["rigor"], "findings_perspectives": ["rigor"], "max_review_rounds": 1},
            "prompts": {"methodology_layer": "prompts/methodology", "domain_adapter_layer": None},
        }

        # Simulate claude -p returning JSON with metrics
        bundle_yaml = (
            "metadata:\n  iteration: 1\n  family: test\n  research_question: test\n"
            "arms:\n  - type: h-main\n    prediction: p\n    mechanism: m\n    diagnostic: d\n"
            "  - type: h-control-negative\n    prediction: p\n    mechanism: m\n    diagnostic: d\n"
        )
        cli_json_output = json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": f"```yaml\n{bundle_yaml}```",
            "total_cost_usd": 0.0523,
            "duration_ms": 15234,
            "num_turns": 3,
            "usage": {
                "input_tokens": 2847,
                "output_tokens": 1024,
                "cache_creation_input_tokens": 28706,
                "cache_read_input_tokens": 0,
            },
        })

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = cli_json_output
        mock_result.stderr = ""

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "bundle.yaml"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        # Check artifact was written
        assert out.exists()
        bundle = yaml.safe_load(out.read_text())
        assert bundle["metadata"]["iteration"] == 1

        # Check metrics were logged
        metrics_path = work_dir / "llm_metrics.jsonl"
        assert metrics_path.exists()
        entry = json.loads(metrics_path.read_text().strip())
        assert entry["dispatcher"] == "cli"
        assert entry["role"] == "planner"
        assert entry["phase"] == "design"
        assert entry["cost_usd"] == 0.0523
        assert entry["input_tokens"] == 2847
        assert entry["output_tokens"] == 1024
        assert entry["cache_creation_input_tokens"] == 28706
        assert entry["duration_ms"] == 15234
        assert entry["num_turns"] == 3


class TestLLMDispatcherMetrics:
    """Test that LLMDispatcher logs token usage from API responses."""

    def test_usage_logged_when_present(self, tmp_path):
        from orchestrator.llm_dispatch import LLMDispatcher

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "runs" / "iter-1").mkdir(parents=True)
        (work_dir / "principles.json").write_text('{"principles": []}')

        campaign = {
            "research_question": "Test?",
            "target_system": {"name": "T", "description": "D", "observable_metrics": ["x"], "controllable_knobs": ["y"]},
            "review": {"design_perspectives": ["rigor"], "findings_perspectives": ["rigor"], "max_review_rounds": 1},
            "prompts": {"methodology_layer": "prompts/methodology", "domain_adapter_layer": None},
        }

        # Mock completion that returns usage
        def mock_completion(**kwargs):
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content="# Problem framing\n\nSome content."))]
            resp.usage = MagicMock()
            resp.usage.prompt_tokens = 5000
            resp.usage.completion_tokens = 800
            return resp

        d = LLMDispatcher(work_dir=work_dir, campaign=campaign, completion_fn=mock_completion)
        out = work_dir / "runs" / "iter-1" / "problem.md"
        d.dispatch("planner", "frame", output_path=out, iteration=1)

        # Check metrics logged
        metrics_path = work_dir / "llm_metrics.jsonl"
        assert metrics_path.exists()
        entry = json.loads(metrics_path.read_text().strip())
        assert entry["dispatcher"] == "llm"
        assert entry["role"] == "planner"
        assert entry["phase"] == "frame"
        assert entry["input_tokens"] == 5000
        assert entry["output_tokens"] == 800
        assert entry["cost_usd"] is None
