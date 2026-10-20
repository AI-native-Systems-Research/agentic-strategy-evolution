"""Behavioral tests for the OpenHands backend (``--agent openhands``).

The OpenHands SDK is never invoked: ``OpenHandsDispatcher`` takes the same
``sdk_runner=`` seam as ``SDKDispatcher``. Scripted runners stand in for
the agent and mutate artifacts on disk the way an executor would; the
tests assert on disk state and ``retry_log.jsonl``.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import yaml

from orchestrator.dispatch import StubDispatcher
from orchestrator.openhands_dispatch import OpenHandsDispatcher
from orchestrator.sdk_dispatch import SDKResult
from orchestrator.validate import validate_design, validate_execution


_MODEL = "openrouter/test/model"  # provider-qualified, so the Claude-default guard passes


def _make_campaign(repo_path: Path) -> dict:
    return {
        "research_question": "What drives latency?",
        "target_system": {
            "name": "test-system",
            "description": "A small test system used by behavioral tests.",
            "observable_metrics": ["latency"],
            "controllable_knobs": ["batch_size"],
            "repo_path": str(repo_path),
        },
    }


def _seed_valid_iteration(work_dir: Path) -> Path:
    """Write a schema-valid iter-1 with StubDispatcher (no LLM)."""
    iter_dir = work_dir / "runs" / "iter-1"
    (iter_dir / "inputs").mkdir(parents=True)
    (iter_dir / "results").mkdir()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stub = StubDispatcher(work_dir=work_dir)
    stub.dispatch("planner", "design", output_path=iter_dir / "design_log.md", iteration=1)
    stub.dispatch("executor", "execute-analyze", output_path=iter_dir / "executor_log.md", iteration=1)
    return iter_dir


def _add_unexpected_field(iter_dir: Path) -> None:
    findings = json.loads((iter_dir / "findings.json").read_text())
    findings["summary"] = "free-form text the schema forbids"
    (iter_dir / "findings.json").write_text(json.dumps(findings))


def _drop_unexpected_field(iter_dir: Path) -> None:
    findings = json.loads((iter_dir / "findings.json").read_text())
    findings.pop("summary", None)
    (iter_dir / "findings.json").write_text(json.dumps(findings))


class _ArtifactRunner:
    """Each call runs the next scripted side effect, then returns a result.

    Records each call's kwargs; call N returns session id ``s<N>``.
    """

    def __init__(self, effects: list):
        self._effects = list(effects)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> SDKResult:
        self.calls.append(kwargs)
        effect = self._effects.pop(0)
        effect()
        return SDKResult(text="done", session_id=f"s{len(self.calls)}")


def _repair_rows(work_dir: Path) -> list[dict]:
    path = work_dir / "retry_log.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("kind") == "validation_repair"]


class TestExecuteAnalyzeValidationGate:
    def test_invalid_findings_are_repaired_before_dispatch_returns(self, tmp_path):
        iter_dir = _seed_valid_iteration(tmp_path)
        runner = _ArtifactRunner([
            lambda: _add_unexpected_field(iter_dir),   # executor turn: invalid output
            lambda: _drop_unexpected_field(iter_dir),  # repair turn: fixes it
        ])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path), sdk_runner=runner, model=_MODEL,
        )

        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir / "executor_log.md", iteration=1,
        )

        assert validate_execution(iter_dir)["status"] == "pass"
        rows = _repair_rows(tmp_path)
        assert len(rows) == 1
        assert any("summary" in e for e in rows[0]["errors"])

    def test_repairs_are_bounded(self, tmp_path):
        iter_dir = _seed_valid_iteration(tmp_path)
        noop = lambda: None  # noqa: E731
        runner = _ArtifactRunner([lambda: _add_unexpected_field(iter_dir), noop, noop])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path),
            sdk_runner=runner, repair_turns=2, model=_MODEL,
        )

        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir / "executor_log.md", iteration=1,
        )

        assert validate_execution(iter_dir)["status"] == "fail"
        assert len(_repair_rows(tmp_path)) == 2

    def test_valid_output_needs_no_repair(self, tmp_path):
        iter_dir = _seed_valid_iteration(tmp_path)
        runner = _ArtifactRunner([lambda: None])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path), sdk_runner=runner, model=_MODEL,
        )

        dispatcher.dispatch(
            "executor", "execute-analyze",
            output_path=iter_dir / "executor_log.md", iteration=1,
        )

        assert _repair_rows(tmp_path) == []

    def test_design_artifacts_are_not_checked_as_execution(self, tmp_path):
        """A planner turn must not be judged by the EXECUTE_ANALYZE validator."""
        iter_dir = _seed_valid_iteration(tmp_path)
        _make_design_valid(iter_dir)
        _add_unexpected_field(iter_dir)   # breaks findings.json only
        runner = _ArtifactRunner([lambda: None])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path), sdk_runner=runner, model=_MODEL,
        )

        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "design_log.md", iteration=1,
        )

        assert _repair_rows(tmp_path) == []


def _make_design_valid(iter_dir: Path) -> None:
    """Guarantee a schema-valid design (StubDispatcher's already is)."""
    bundle = yaml.safe_load((iter_dir / "bundle.yaml").read_text())
    bundle.setdefault("metadata", {
        "iteration": 1, "family": "test", "research_question": "What drives latency?",
    })
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump(bundle, sort_keys=False))
    assert validate_design(iter_dir)["status"] == "pass"


class TestDesignValidationGate:
    def test_invalid_bundle_is_repaired_before_dispatch_returns(self, tmp_path):
        iter_dir = _seed_valid_iteration(tmp_path)
        good_bundle = None

        def break_bundle():
            nonlocal good_bundle
            _make_design_valid(iter_dir)
            good_bundle = (iter_dir / "bundle.yaml").read_text()
            bundle = yaml.safe_load(good_bundle)
            del bundle["metadata"]
            (iter_dir / "bundle.yaml").write_text(yaml.safe_dump(bundle))

        def fix_bundle():
            (iter_dir / "bundle.yaml").write_text(good_bundle)

        runner = _ArtifactRunner([break_bundle, fix_bundle])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path), sdk_runner=runner, model=_MODEL,
        )

        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "design_log.md", iteration=1,
        )

        assert validate_design(iter_dir)["status"] == "pass"
        rows = _repair_rows(tmp_path)
        assert len(rows) == 1 and rows[0]["phase"] == "design"
        assert any("metadata" in e for e in rows[0]["errors"])

    def test_missing_design_files_trigger_repair(self, tmp_path):
        iter_dir = tmp_path / "runs" / "iter-1"
        (iter_dir / "inputs").mkdir(parents=True)
        runner = _ArtifactRunner([lambda: None, lambda: None])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path),
            sdk_runner=runner, repair_turns=1, model=_MODEL,
        )

        dispatcher.dispatch(
            "planner", "design", output_path=iter_dir / "design_log.md", iteration=1,
        )

        rows = _repair_rows(tmp_path)
        assert len(rows) == 1 and any("bundle.yaml not found" in e for e in rows[0]["errors"])


# ─── OpenHandsRunner against a fake driver (no OpenHands, no network) ───

import sys  # noqa: E402

import pytest  # noqa: E402

import orchestrator.openhands_dispatch as ohd  # noqa: E402
from orchestrator.openhands_dispatch import OpenHandsRunner  # noqa: E402

_FAKE_DRIVER = """
import json, sys
req = json.load(open(sys.argv[1]))
resp = json.loads(req["prompt"])          # tests script the response via the prompt
resp.setdefault("text", "done")
resp["echo_request_keys"] = sorted(req)
json.dump(resp, open(sys.argv[2], "w"))
"""


@pytest.fixture
def fake_driver(tmp_path, monkeypatch):
    driver = tmp_path / "fake-driver"
    driver.write_text(_FAKE_DRIVER)
    monkeypatch.setattr(ohd, "_DRIVER", driver)
    monkeypatch.setenv("NOUS_OPENHANDS_PYTHON", sys.executable)


def _run(tmp_path, response: dict, event_log: Path | None = None):
    return OpenHandsRunner()(
        prompt=json.dumps(response), model="openrouter/x/y", cwd=tmp_path,
        max_turns=5, event_log_path=event_log,
    )


class TestOpenHandsRunner:
    def test_tokens_and_cost_pass_through(self, tmp_path, fake_driver):
        result = _run(tmp_path, {
            "input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 7,
            "cost_usd": 0.25, "execution_status": "finished",
        })
        assert (result.input_tokens, result.output_tokens, result.cost_usd) == (10, 5, 0.25)
        assert result.is_error is False

    def test_fatal_error_is_not_retried(self, tmp_path, fake_driver):
        with pytest.raises(RuntimeError, match="not retryable"):
            _run(tmp_path, {"is_error": True, "fatal": True,
                            "error_message": "402 requires more credits"})

    def test_transient_error_is_returned_for_retry(self, tmp_path, fake_driver):
        result = _run(tmp_path, {"is_error": True, "error_message": "TimeoutError: read timed out"})
        assert result.is_error is True

    def test_turn_end_record_written_to_event_log(self, tmp_path, fake_driver):
        log = tmp_path / "runs" / "iter-1" / "inputs" / "executor_log.jsonl"
        log.parent.mkdir(parents=True)
        _run(tmp_path, {"execution_status": "stuck", "num_turns": 9}, event_log=log)
        records = [json.loads(line) for line in log.read_text().splitlines()]
        end = [r for r in records if r.get("type") == "OpenHandsTurnEnd"]
        assert end and end[-1]["execution_status"] == "stuck" and "ts" in end[-1]


class TestModelGuard:
    def test_bare_claude_default_is_refused(self, tmp_path):
        iter_dir = _seed_valid_iteration(tmp_path)
        runner = _ArtifactRunner([lambda: None])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path),
            model="claude-opus-4-6", sdk_runner=runner,
        )
        with pytest.raises(RuntimeError, match="Pin every code phase"):
            dispatcher.dispatch("planner", "design",
                                output_path=iter_dir / "design_log.md", iteration=1)

    def test_provider_qualified_claude_is_allowed(self, tmp_path):
        iter_dir = _seed_valid_iteration(tmp_path)
        runner = _ArtifactRunner([lambda: None])
        dispatcher = OpenHandsDispatcher(
            work_dir=tmp_path, campaign=_make_campaign(tmp_path),
            model="anthropic/claude-haiku-4-5", sdk_runner=runner,
        )
        dispatcher.dispatch("planner", "design",
                            output_path=iter_dir / "design_log.md", iteration=1)
        assert (iter_dir / "design_log.md").exists()


_RECORDING_DRIVER = """
import json, sys, pathlib
req = json.load(open(sys.argv[1]))
pathlib.Path(req["cwd"], "requests.jsonl").open("a").write(json.dumps(req) + "\\n")
json.dump({"text": "done", "session_id": "conv-1", "conversation_id": "conv-1",
           "execution_status": "finished"}, open(sys.argv[2], "w"))
"""


def test_runner_resume_and_budget_reach_the_driver(tmp_path, monkeypatch):
    driver = tmp_path / "recording-driver"
    driver.write_text(_RECORDING_DRIVER)
    monkeypatch.setattr(ohd, "_DRIVER", driver)
    monkeypatch.setenv("NOUS_OPENHANDS_PYTHON", sys.executable)
    log = tmp_path / "runs" / "iter-1" / "inputs" / "executor_log.jsonl"
    log.parent.mkdir(parents=True)
    runner = OpenHandsRunner()

    first = runner(prompt="turn", model="openrouter/x/y", cwd=tmp_path, max_turns=5, event_log_path=log)
    runner(prompt="again", model="openrouter/x/y", cwd=tmp_path, max_turns=5, event_log_path=log,
           resume="conv-1", max_cost_usd=2.5, cost_rates={"input": 1, "output": 2})

    a, b = [json.loads(l) for l in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert first.session_id == "conv-1"
    assert "resume_conversation_id" not in a and b["resume_conversation_id"] == "conv-1"
    assert b["persistence_dir"] == a["persistence_dir"]
    assert (b["max_cost_usd"], b["cost_rates"]) == (2.5, {"input": 1, "output": 2})


def test_cap_and_turn_limit_signals_pass_through(tmp_path, fake_driver):
    capped = _run(tmp_path, {"is_error": True, "subtype": "error_max_budget_usd",
                             "error_message": "error_max_budget_usd: cap", "session_id": "c1"})
    assert (capped.subtype, capped.session_id, capped.is_error) == ("error_max_budget_usd", "c1", True)
    limited = _run(tmp_path, {"is_error": True, "subtype": "error_max_turns",
                              "error_message": "error_max_turns: 5 actions", "session_id": "c2"})
    assert (limited.subtype, limited.session_id) == ("error_max_turns", "c2")


def test_repair_turn_resumes_the_phase_session(tmp_path):
    iter_dir = _seed_valid_iteration(tmp_path)
    runner = _ArtifactRunner([
        lambda: _add_unexpected_field(iter_dir),   # executor turn -> session s1, invalid output
        lambda: _drop_unexpected_field(iter_dir),  # repair turn
    ])
    dispatcher = OpenHandsDispatcher(
        work_dir=tmp_path, campaign=_make_campaign(tmp_path), sdk_runner=runner, model=_MODEL,
    )

    dispatcher.dispatch("executor", "execute-analyze",
                        output_path=iter_dir / "executor_log.md", iteration=1)

    assert runner.calls[0].get("resume") is None
    assert runner.calls[1].get("resume") == "s1"


def test_v8_campaigns_get_no_openhands_repair_loop(tmp_path):
    """v7/v8 run their own repair and fallback sessions; ours must stay out."""
    iter_dir = _seed_valid_iteration(tmp_path)
    runner = _ArtifactRunner([lambda: _add_unexpected_field(iter_dir)])
    campaign = {**_make_campaign(tmp_path), "design_profile": "v8"}
    dispatcher = OpenHandsDispatcher(
        work_dir=tmp_path, campaign=campaign, sdk_runner=runner, model=_MODEL,
    )

    dispatcher.dispatch("executor", "execute-analyze",
                        output_path=iter_dir / "executor_log.md", iteration=1)

    assert len(runner.calls) == 1 and _repair_rows(tmp_path) == []


# ─── Target-repo integrity (agents must stay in their worktree) ───

import subprocess  # noqa: E402


def _git_target(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "solution.cpp").write_text("int main(){}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "seed"], check=True)
    return repo


def _agent_commits_into(repo: Path):
    def effect():
        (repo / "solution.cpp").write_text("// changed outside the worktree\n")
        subprocess.run(["git", "-C", str(repo), "commit", "-qam", "agent edit"], check=True)
    return effect


class TestTargetRepoIntegrity:
    def test_commit_in_target_repo_is_recorded(self, tmp_path):
        work = tmp_path / "work"
        iter_dir = _seed_valid_iteration(work)
        repo = _git_target(tmp_path)
        runner = _ArtifactRunner([_agent_commits_into(repo)])
        dispatcher = OpenHandsDispatcher(
            work_dir=work, campaign=_make_campaign(repo), sdk_runner=runner, model=_MODEL,
        )

        dispatcher.dispatch(
            "executor", "execute-analyze", output_path=iter_dir / "executor_log.md", iteration=1,
        )

        record = json.loads((iter_dir / "inputs" / "target_repo_violation.json").read_text())
        assert record["phase"] == "execute_analyze"
        assert any("agent edit" in c for c in record["new_commits"])

    def test_untouched_target_repo_leaves_no_record(self, tmp_path):
        work = tmp_path / "work"
        iter_dir = _seed_valid_iteration(work)
        repo = _git_target(tmp_path)
        (repo / ".nous").mkdir()            # nous's own cache dir is ignored
        (repo / ".nous" / "cache").write_text("x")
        runner = _ArtifactRunner([lambda: None])
        dispatcher = OpenHandsDispatcher(
            work_dir=work, campaign=_make_campaign(repo), sdk_runner=runner, model=_MODEL,
        )

        dispatcher.dispatch(
            "executor", "execute-analyze", output_path=iter_dir / "executor_log.md", iteration=1,
        )

        assert not (iter_dir / "inputs" / "target_repo_violation.json").exists()


_HANGING_DRIVER = """
import json, sys, time
req = json.load(open(sys.argv[1]))
open(req["session_file"], "w").write("conv-hung")
time.sleep(60)
"""


def test_silent_session_raises_hang_error_with_session_id(tmp_path, monkeypatch):
    from orchestrator.sdk_dispatch import SDKHangError
    driver = tmp_path / "hanging-driver"
    driver.write_text(_HANGING_DRIVER)
    monkeypatch.setattr(ohd, "_DRIVER", driver)
    monkeypatch.setenv("NOUS_OPENHANDS_PYTHON", sys.executable)
    log = tmp_path / "runs" / "iter-1" / "inputs" / "executor_log.jsonl"
    log.parent.mkdir(parents=True)

    with pytest.raises(SDKHangError) as info:
        OpenHandsRunner()(prompt="x", model="ollama_chat/m", cwd=tmp_path, max_turns=3,
                          event_log_path=log, hang_after_s=1.0)
    assert info.value.session_id == "conv-hung"
