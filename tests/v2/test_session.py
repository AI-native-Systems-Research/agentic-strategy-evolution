"""Tests for orchestrator.v2.session — option building and state persistence."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest

from orchestrator.v2.session import (
    DEFAULT_MAX_BUFFER_SIZE,
    DEFAULT_MODEL,
    MODEL_MAX_OUTPUT,
    SDK_VERSION,
    CLI_VERSION,
    Session,
)
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


def _make_session(
    tmp_path: Path, **overrides: object
) -> tuple[Session, FakeClient]:
    """Helper: build a Session backed by FakeClient."""
    result_msg = overrides.pop("_result_msg", None) or FakeResultMessage(
        session_id="ses-abc-123"
    )
    script = overrides.pop("_script", None) or [result_msg]

    opts: dict = {
        "work_dir": str(tmp_path / "campaign"),
        "cwd": str(tmp_path / "worktree"),
        "method_text": "Test methodology text.",
        **overrides,
    }

    captured_client: list[FakeClient] = []

    def factory(agent_options):
        client = FakeClient(script=script)
        client._agent_options = agent_options  # stash for inspection
        captured_client.append(client)
        return client

    session = Session(client_factory=factory, options=opts)
    # Connect so we can inspect the built options
    session.connect()
    client = captured_client[0]
    return session, client


# ── Option building ───────────────────────────────────────────────────


class TestBuildAgentOptions:
    def test_default_model(self, tmp_path):
        session, client = _make_session(tmp_path)
        opts = client._agent_options
        assert opts.model == DEFAULT_MODEL
        session.disconnect()

    def test_custom_model(self, tmp_path):
        session, client = _make_session(tmp_path, model="claude-sonnet-4-20250514")
        opts = client._agent_options
        assert opts.model == "claude-sonnet-4-20250514"
        session.disconnect()

    def test_system_prompt_preset(self, tmp_path):
        session, client = _make_session(tmp_path)
        sp = client._agent_options.system_prompt
        assert sp["type"] == "preset"
        assert sp["preset"] == "claude_code"
        assert sp["snapshot"] is True
        assert "Test methodology text." in sp["append"]
        session.disconnect()

    def test_max_buffer_size(self, tmp_path):
        session, client = _make_session(tmp_path)
        assert client._agent_options.max_buffer_size == DEFAULT_MAX_BUFFER_SIZE
        assert DEFAULT_MAX_BUFFER_SIZE == 32 * 1024 * 1024
        session.disconnect()

    def test_env_includes_max_output_tokens(self, tmp_path):
        session, client = _make_session(tmp_path)
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "128000"
        session.disconnect()

    def test_env_includes_work_dir(self, tmp_path):
        session, client = _make_session(tmp_path)
        env = client._agent_options.env
        assert env["NOUS_WORK_DIR"] == str(tmp_path / "campaign")
        session.disconnect()

    def test_env_max_output_for_sonnet(self, tmp_path):
        session, client = _make_session(tmp_path, model="claude-sonnet-4-20250514")
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "64000"
        session.disconnect()

    def test_env_max_output_unknown_model_defaults(self, tmp_path):
        session, client = _make_session(tmp_path, model="claude-future-99")
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "128000"
        session.disconnect()

    def test_effort_omitted_by_default(self, tmp_path):
        session, client = _make_session(tmp_path)
        assert client._agent_options.effort is None
        session.disconnect()

    def test_effort_set_when_configured(self, tmp_path):
        session, client = _make_session(tmp_path, effort="high")
        assert client._agent_options.effort == "high"
        session.disconnect()

    def test_cwd_set(self, tmp_path):
        session, client = _make_session(tmp_path)
        assert client._agent_options.cwd == str(tmp_path / "worktree")
        session.disconnect()

    def test_resume_set_when_session_id_provided(self, tmp_path):
        session, client = _make_session(tmp_path, resume="ses-old-123")
        assert client._agent_options.resume == "ses-old-123"
        session.disconnect()

    def test_resume_omitted_by_default(self, tmp_path):
        session, client = _make_session(tmp_path)
        assert client._agent_options.resume is None
        session.disconnect()

    def test_hooks_passed_through(self, tmp_path):
        hooks = {"PostToolUse": [{"matcher": "Bash", "hooks": [], "timeout": 30.0}]}
        session, client = _make_session(tmp_path, hooks=hooks)
        assert client._agent_options.hooks == hooks
        session.disconnect()

    def test_extra_env_merged(self, tmp_path):
        session, client = _make_session(tmp_path, env={"MY_VAR": "hello"})
        env = client._agent_options.env
        assert env["MY_VAR"] == "hello"
        # defaults still present
        assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" in env
        session.disconnect()

    def test_extra_env_overrides_defaults(self, tmp_path):
        session, client = _make_session(
            tmp_path, env={"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "999"}
        )
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "999"
        session.disconnect()


# ── Session lifecycle & state persistence ─────────────────────────────


class TestSessionLifecycle:
    def test_turn_persists_session_id(self, tmp_path):
        session, _client = _make_session(tmp_path)
        anyio.run(session.turn, "hello")

        state_path = tmp_path / "campaign" / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["session_id"] == "ses-abc-123"
        session.disconnect()

    def test_state_includes_version_stamps(self, tmp_path):
        session, _client = _make_session(tmp_path)
        anyio.run(session.turn, "hello")

        state = json.loads((tmp_path / "campaign" / "state.json").read_text())
        assert state["sdk_version"] == SDK_VERSION
        assert state["cli_version"] == CLI_VERSION
        session.disconnect()

    def test_state_preserves_existing_fields(self, tmp_path):
        # Pre-populate state.json with extra fields
        campaign_dir = tmp_path / "campaign"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "state.json").write_text(
            json.dumps({"repo_path": "/some/repo", "run_id": "run-42"})
        )

        session, _client = _make_session(tmp_path)
        anyio.run(session.turn, "hello")

        state = json.loads((campaign_dir / "state.json").read_text())
        assert state["repo_path"] == "/some/repo"
        assert state["run_id"] == "run-42"
        assert state["session_id"] == "ses-abc-123"
        session.disconnect()

    def test_session_id_property(self, tmp_path):
        session, _client = _make_session(tmp_path)
        assert session.session_id is None  # no turn yet
        anyio.run(session.turn, "hello")
        assert session.session_id == "ses-abc-123"
        session.disconnect()

    def test_turn_without_connect_raises(self, tmp_path):
        opts = {"work_dir": str(tmp_path), "method_text": "x"}
        session = Session(client_factory=FakeClient, options=opts)
        with pytest.raises(RuntimeError, match="connect"):
            anyio.run(session.turn, "hello")

    def test_disconnect(self, tmp_path):
        session, client = _make_session(tmp_path)
        assert client.connected
        session.disconnect()
        assert not client.connected

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        # work_dir doesn't exist yet
        opts = {
            "work_dir": str(tmp_path / "deep" / "nested" / "campaign"),
            "method_text": "x",
        }
        result_msg = FakeResultMessage(session_id="ses-new")

        def factory(agent_options):
            return FakeClient(script=[result_msg])

        session = Session(client_factory=factory, options=opts)
        session.connect()
        anyio.run(session.turn, "hello")

        state_path = tmp_path / "deep" / "nested" / "campaign" / "state.json"
        assert state_path.exists()
        assert json.loads(state_path.read_text())["session_id"] == "ses-new"
        session.disconnect()


# ── Transient error classification ───────────────────────────────────


class TestTransientErrors:
    def test_process_error_143_is_transient(self):
        from orchestrator.v2.errors import ProcessError, is_transient
        assert is_transient(ProcessError(143))

    def test_process_error_1_is_transient_as_subclass(self):
        from orchestrator.v2.errors import ProcessError, is_transient
        assert is_transient(ProcessError(1))

    def test_fatal_message_reader_is_transient(self):
        from orchestrator.v2.errors import is_transient
        assert is_transient(RuntimeError("Fatal error in message reader"))

    def test_api_5xx_is_transient(self):
        from orchestrator.v2.errors import APIServerError, is_transient
        assert is_transient(APIServerError(502))

    def test_generic_exc_with_status_code_500(self):
        from orchestrator.v2.errors import is_transient
        exc = RuntimeError("oops")
        exc.status_code = 500  # type: ignore[attr-defined]
        assert is_transient(exc)

    def test_generic_runtime_error_is_not_transient(self):
        from orchestrator.v2.errors import is_transient
        assert not is_transient(RuntimeError("something broke"))

    def test_exit_143_on_generic_exc(self):
        from orchestrator.v2.errors import is_transient
        exc = RuntimeError("process died")
        exc.exit_code = 143  # type: ignore[attr-defined]
        assert is_transient(exc)

    def test_stdlib_timeout_is_transient(self):
        from orchestrator.v2.errors import is_transient
        assert is_transient(TimeoutError("connection timed out"))

    def test_os_error_timed_out_is_transient(self):
        from orchestrator.v2.errors import is_transient
        assert is_transient(OSError("Operation timed out"))
