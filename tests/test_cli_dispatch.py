"""Tests for CLIDispatcher — claude -p subprocess invocation."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema
import pytest
import yaml



SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


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
        mock_result.stdout = json.dumps({
            "result": raw_design_text, "is_error": False, "usage": {},
            "total_cost_usd": 0, "duration_ms": 100, "num_turns": 1,
        })
        mock_result.stderr = ""

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        assert out.exists()
        content = out.read_text()
        assert "Experiment Design" in content
        assert "Research Question" in content

    def test_dispatch_executor_execute_analyze_saves_raw_output(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        executor_text = "All experiments completed. Artifacts written to iter_dir."
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "result": executor_text, "is_error": False, "usage": {},
            "total_cost_usd": 0, "duration_ms": 100, "num_turns": 1,
        })
        mock_result.stderr = ""

        # Create bundle.yaml (required by context builder)
        (work_dir / "runs" / "iter-1").mkdir(parents=True, exist_ok=True)
        (work_dir / "runs" / "iter-1" / "bundle.yaml").write_text("metadata:\n  iteration: 1\n")

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "executor_log.md"
            d.dispatch("executor", "execute-analyze", output_path=out, iteration=1)

        assert out.exists()
        assert "Artifacts written" in out.read_text()

    def test_dispatch_planner_design_writes_response_text(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        response_text = "# Design Output\n\nThis is the raw design response.\n"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "result": response_text, "is_error": False, "usage": {},
            "total_cost_usd": 0, "duration_ms": 100, "num_turns": 1,
        })
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

    def test_claude_nonzero_exit_raises_after_retries(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: something went wrong"

        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=mock_result):
            with patch("orchestrator.cli_dispatch.time.sleep"):
                d = CLIDispatcher(work_dir=work_dir, campaign=campaign, max_retries=0)
                with pytest.raises(RuntimeError, match="still failing"):
                    d.dispatch(
                        "planner", "design",
                        output_path=work_dir / "out.md", iteration=1,
                    )

    def test_prompt_includes_campaign_context(self, work_dir: Path, campaign: dict) -> None:
        """The system prompt passed to claude -p should include campaign info."""
        from orchestrator.cli_dispatch import CLIDispatcher

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"result": "# Design\nStub.", "is_error": False, "usage": {}, "total_cost_usd": 0, "duration_ms": 100, "num_turns": 1})
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
        mock_result.stdout = json.dumps({"result": "# Design\nStub.", "is_error": False, "usage": {}, "total_cost_usd": 0, "duration_ms": 100, "num_turns": 1})
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

    def test_default_max_retries_is_10(self, work_dir: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        d = CLIDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN)
        assert d.max_retries == 10

    def test_max_retries_none_means_unlimited(self, work_dir: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        d = CLIDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, max_retries=None)
        assert d.max_retries is None

    def test_max_retries_zero_means_disabled(self, work_dir: Path) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        d = CLIDispatcher(work_dir=work_dir, campaign=SAMPLE_CAMPAIGN, max_retries=0)
        assert d.max_retries == 0

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
        mock_result.stdout = json.dumps({"result": "# Design\nStub.", "is_error": False, "usage": {}, "total_cost_usd": 0, "duration_ms": 100, "num_turns": 1})
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


def _make_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Helper: build a subprocess.CompletedProcess mock."""
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def _success_result(text: str = "agent output") -> MagicMock:
    """Successful claude -p output as JSON envelope."""
    payload = json.dumps({
        "result": text, "is_error": False, "usage": {},
        "total_cost_usd": 0, "duration_ms": 100, "num_turns": 1,
    })
    return _make_result(returncode=0, stdout=payload)


def _transient_socket_result() -> MagicMock:
    """Non-zero exit with a transient socket error in stdout JSON."""
    payload = json.dumps({
        "type": "result", "subtype": "error", "is_error": True,
        "api_error_status": None,
        "result": "API Error: The socket connection was closed unexpectedly.",
        "total_cost_usd": 0.01, "duration_ms": 500, "num_turns": 1,
        "usage": {"input_tokens": 100, "output_tokens": 0,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    })
    return _make_result(returncode=1, stdout=payload, stderr="")


def _transient_5xx_result() -> MagicMock:
    """Non-zero exit with api_error_status=503 in JSON."""
    payload = json.dumps({
        "type": "result", "subtype": "error", "is_error": True,
        "api_error_status": 503,
        "result": "Service unavailable",
        "total_cost_usd": 0.0, "duration_ms": 200, "num_turns": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    })
    return _make_result(returncode=1, stdout=payload, stderr="")


def _transient_is_error_result() -> MagicMock:
    """Zero exit, is_error=True with transient socket text."""
    payload = json.dumps({
        "type": "result", "subtype": "error", "is_error": True,
        "api_error_status": None,
        "result": "API Error: The socket connection was closed unexpectedly.",
        "total_cost_usd": 0.01, "duration_ms": 500, "num_turns": 1,
        "usage": {"input_tokens": 100, "output_tokens": 0,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    })
    return _make_result(returncode=0, stdout=payload, stderr="")


def _non_transient_is_error_result() -> MagicMock:
    """Zero exit, is_error=True with an agent-side (non-transient) error."""
    payload = json.dumps({
        "type": "result", "subtype": "error", "is_error": True,
        "api_error_status": None,
        "result": "invalid YAML in bundle: mapping values are not allowed here",
        "total_cost_usd": 0.02, "duration_ms": 600, "num_turns": 2,
        "usage": {"input_tokens": 200, "output_tokens": 50,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    })
    return _make_result(returncode=0, stdout=payload, stderr="")


def _non_transient_nonzero_result() -> MagicMock:
    """Non-zero exit with a non-transient stderr message."""
    return _make_result(returncode=1, stdout="", stderr="Error: API key not set")


def _transient_stderr_nonzero_result() -> MagicMock:
    """Non-zero exit with a transient error in stderr (no parseable JSON stdout)."""
    return _make_result(returncode=1, stdout="not json", stderr="ECONNRESET: connection reset")


class TestCLIDispatcherRetry:
    """Tests for transient-error retry logic in CLIDispatcher."""

    @pytest.fixture()
    def fast_sleep(self):
        with patch("orchestrator.cli_dispatch.time.sleep") as m:
            yield m

    def test_transient_socket_error_retries_then_succeeds(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        success = _success_result("# Design\nStub.")
        side_effects = [
            _transient_socket_result(),
            _transient_socket_result(),
            success,
        ]

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=side_effects) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        assert mock_run.call_count == 3
        assert out.exists()
        # First sleep: after failure 1 → 5s; second: after failure 2 → 30s
        assert fast_sleep.call_count == 2
        assert fast_sleep.call_args_list[0][0][0] == 5
        assert fast_sleep.call_args_list[1][0][0] == 30

    def test_transient_5xx_retries_then_succeeds(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        side_effects = [_transient_5xx_result(), _success_result("# Design\nStub.")]

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=side_effects) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_transient_is_error_retries(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """is_error=True with a transient message should also be retried."""
        from orchestrator.cli_dispatch import CLIDispatcher

        side_effects = [_transient_is_error_result(), _success_result("# Design\nStub.")]

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=side_effects) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_transient_stderr_nonzero_retries(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """Non-zero exit with a transient string in stderr (no parseable JSON) retries."""
        from orchestrator.cli_dispatch import CLIDispatcher

        side_effects = [_transient_stderr_nonzero_result(), _success_result("# Design\nStub.")]

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=side_effects) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_unknown_is_error_retries(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """Unknown is_error (not a permanent pattern) is retried."""
        from orchestrator.cli_dispatch import CLIDispatcher

        success = _success_result("# Design\nStub.")
        side_effects = [_non_transient_is_error_result(), success]

        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            side_effect=side_effects,
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_nonzero_exit_retries(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """All non-zero exits are retried (no permanent classification)."""
        from orchestrator.cli_dispatch import CLIDispatcher

        success = _success_result("# Design\nStub.")
        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            side_effect=[_non_transient_nonzero_result(), success],
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_max_retries_zero_disables_retries(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """max_retries=0 means no retries — the first transient failure raises immediately."""
        from orchestrator.cli_dispatch import CLIDispatcher

        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            return_value=_transient_socket_result(),
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign, max_retries=0)
            with pytest.raises(RuntimeError, match="still failing after 1 attempt"):
                d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 1
        fast_sleep.assert_not_called()

    def test_max_retries_bound_raises(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """When max_retries is set, exhaust the budget and raise RuntimeError."""
        from orchestrator.cli_dispatch import CLIDispatcher

        # max_retries=2 means: 1 original + 2 retries = 3 total attempts before giving up
        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            return_value=_transient_socket_result(),
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign, max_retries=2)
            with pytest.raises(RuntimeError, match="still failing after 3 attempt"):
                d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 3
        assert fast_sleep.call_count == 2

    def test_timeout_retries_with_backoff(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """subprocess.TimeoutExpired enters the retry loop."""
        import subprocess as _subprocess
        from orchestrator.cli_dispatch import CLIDispatcher

        timeout_exc = _subprocess.TimeoutExpired(cmd=["claude"], timeout=1800)
        success = _make_result(
            returncode=0,
            stdout=json.dumps({"result": "# Design\nStub.", "is_error": False, "usage": {}}),
        )

        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            side_effect=[timeout_exc, success],
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_file_not_found_does_not_retry(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """FileNotFoundError (missing claude CLI) is NOT retried."""
        from orchestrator.cli_dispatch import CLIDispatcher

        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            side_effect=FileNotFoundError("claude not found"),
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            with pytest.raises(RuntimeError, match="claude.*not found"):
                d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 1
        fast_sleep.assert_not_called()

    def test_auth_error_retries(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """Auth errors are retried (LiteLLM can produce transient auth failures)."""
        from orchestrator.cli_dispatch import CLIDispatcher

        auth_resp = _make_result(
            returncode=0,
            stdout=json.dumps({
                "result": "invalid_api_key: Your API key is invalid",
                "is_error": True,
                "usage": {},
                "total_cost_usd": 0, "duration_ms": 0, "num_turns": 0,
            }),
        )
        success = _success_result("# Design\nStub.")

        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            side_effect=[auth_resp, success],
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_max_turns_error_retries(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """error_max_turns response enters the retry loop (not permanent)."""
        from orchestrator.cli_dispatch import CLIDispatcher

        max_turns_resp = _make_result(
            returncode=0,
            stdout=json.dumps({
                "result": "error_max_turns: Turn limit reached",
                "is_error": True,
                "usage": {},
                "total_cost_usd": 0, "duration_ms": 0, "num_turns": 0,
            }),
        )
        success = _success_result("# Design\nStub.")

        with patch(
            "orchestrator.cli_dispatch.subprocess.run",
            side_effect=[max_turns_resp, success],
        ) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        assert mock_run.call_count == 2
        fast_sleep.assert_called_once_with(5)

    def test_retry_events_logged_to_retry_log(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """Each failure is recorded in retry_log.jsonl."""
        import subprocess as _subprocess
        from orchestrator.cli_dispatch import CLIDispatcher

        timeout_exc = _subprocess.TimeoutExpired(cmd=["claude"], timeout=1800)
        success = _success_result("# Design\nStub.")

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=[timeout_exc, success]):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        log_path = work_dir / "retry_log.jsonl"
        assert log_path.exists()
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        assert len(entries) == 1
        assert entries[0]["failure_type"] == "timeout"
        assert entries[0]["phase"] == "design"
        assert entries[0]["attempt"] == 1
        assert "timestamp" in entries[0]

    def test_prompt_enriched_on_timeout_retry(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """Retry after timeout enriches the prompt with continuation note."""
        import subprocess as _subprocess
        from orchestrator.cli_dispatch import CLIDispatcher

        timeout_exc = _subprocess.TimeoutExpired(cmd=["claude"], timeout=1800)
        success = _success_result("# Design\nStub.")

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=[timeout_exc, success]) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        # Second call should have enriched prompt
        second_call_kwargs = mock_run.call_args_list[1]
        prompt_sent = second_call_kwargs.kwargs.get("input") or second_call_kwargs[1].get("input", "")
        assert "previous attempt was interrupted" in prompt_sent
        assert "continue from where you left off" in prompt_sent

    def test_prompt_enriched_on_max_turns_retry(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """Retry after max_turns enriches the prompt with continuation note."""
        from orchestrator.cli_dispatch import CLIDispatcher

        max_turns_resp = _make_result(
            returncode=0,
            stdout=json.dumps({
                "result": "error_max_turns: Turn limit reached",
                "is_error": True,
                "usage": {},
                "total_cost_usd": 0, "duration_ms": 0, "num_turns": 0,
            }),
        )
        success = _success_result("# Design\nStub.")

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=[max_turns_resp, success]) as mock_run:
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.dispatch("planner", "design", output_path=work_dir / "out.md", iteration=1)

        second_call_kwargs = mock_run.call_args_list[1]
        prompt_sent = second_call_kwargs.kwargs.get("input", "")
        assert "previous attempt was interrupted" in prompt_sent
        assert "continue from where you left off" in prompt_sent

    def test_metrics_logged_per_attempt(
        self, work_dir: Path, campaign: dict, fast_sleep,
    ) -> None:
        """Metrics are recorded for every attempt, including transient-failure ones."""
        from orchestrator.cli_dispatch import CLIDispatcher

        success_payload = json.dumps({
            "type": "result", "subtype": "success", "is_error": False,
            "result": "# Design\nStub.",
            "total_cost_usd": 0.05, "duration_ms": 1000, "num_turns": 2,
            "usage": {"input_tokens": 500, "output_tokens": 100,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        })
        side_effects = [
            _transient_is_error_result(),
            _transient_is_error_result(),
            _make_result(returncode=0, stdout=success_payload),
        ]

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=side_effects):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            out = work_dir / "runs" / "iter-1" / "design.md"
            d.dispatch("planner", "design", output_path=out, iteration=1)

        metrics_path = work_dir / "llm_metrics.jsonl"
        assert metrics_path.exists()
        lines = [l for l in metrics_path.read_text().strip().splitlines() if l]
        # _transient_is_error_result uses returncode=0 so log_metrics fires before the
        # is_error raise; 2 transient attempts + 1 success = 3 entries.
        assert len(lines) == 3


class TestPreflightCheck:
    """Tests for CLIDispatcher.preflight_check()."""

    def test_preflight_passes_on_success(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        success = _success_result("OK")
        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=success):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            d.preflight_check()

    def test_preflight_fails_on_missing_cli(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        with patch("orchestrator.cli_dispatch.subprocess.run", side_effect=FileNotFoundError):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            with pytest.raises(RuntimeError, match="Pre-flight.*not found"):
                d.preflight_check()

    def test_preflight_fails_on_auth_error(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        auth_resp = _make_result(
            returncode=0,
            stdout=json.dumps({"result": "invalid_api_key", "is_error": True, "usage": {}}),
        )
        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=auth_resp):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            with pytest.raises(RuntimeError, match="Pre-flight.*invalid_api_key"):
                d.preflight_check()

    def test_preflight_fails_on_nonzero_exit(self, work_dir: Path, campaign: dict) -> None:
        from orchestrator.cli_dispatch import CLIDispatcher

        fail_resp = _make_result(returncode=1, stderr="connection refused")
        with patch("orchestrator.cli_dispatch.subprocess.run", return_value=fail_resp):
            d = CLIDispatcher(work_dir=work_dir, campaign=campaign)
            with pytest.raises(RuntimeError, match="Pre-flight.*exited with code 1"):
                d.preflight_check()
