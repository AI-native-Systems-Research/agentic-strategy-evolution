"""Tests for orchestrator.v2.session — option building and state persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from claude_agent_sdk import ProcessError

from orchestrator.v2.session import (
    DEFAULT_MAX_BUFFER_SIZE,
    DEFAULT_MODEL,
    MODEL_MAX_OUTPUT,
    SDK_VERSION,
    CLI_VERSION,
    Session,
)
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


async def _make_session(
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
    await session.connect()
    client = captured_client[0]
    return session, client


# ── Option building ───────────────────────────────────────────────────


class TestBuildAgentOptions:
    async def test_default_model(self, tmp_path):
        session, client = await _make_session(tmp_path)
        opts = client._agent_options
        assert opts.model == DEFAULT_MODEL
        await session.disconnect()

    async def test_custom_model(self, tmp_path):
        session, client = await _make_session(tmp_path, model="claude-sonnet-4-20250514")
        opts = client._agent_options
        assert opts.model == "claude-sonnet-4-20250514"
        await session.disconnect()

    async def test_system_prompt_preset(self, tmp_path):
        session, client = await _make_session(tmp_path)
        sp = client._agent_options.system_prompt
        assert sp["type"] == "preset"
        assert sp["preset"] == "claude_code"
        assert sp["snapshot"] is True
        assert "Test methodology text." in sp["append"]
        await session.disconnect()

    async def test_max_buffer_size(self, tmp_path):
        session, client = await _make_session(tmp_path)
        assert client._agent_options.max_buffer_size == DEFAULT_MAX_BUFFER_SIZE
        assert DEFAULT_MAX_BUFFER_SIZE == 32 * 1024 * 1024
        await session.disconnect()

    async def test_env_includes_max_output_tokens(self, tmp_path):
        session, client = await _make_session(tmp_path)
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "128000"
        await session.disconnect()

    async def test_env_includes_work_dir(self, tmp_path):
        session, client = await _make_session(tmp_path)
        env = client._agent_options.env
        assert env["NOUS_WORK_DIR"] == str(tmp_path / "campaign")
        await session.disconnect()

    async def test_env_max_output_for_sonnet(self, tmp_path):
        session, client = await _make_session(tmp_path, model="claude-sonnet-4-20250514")
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "64000"
        await session.disconnect()

    async def test_env_max_output_unknown_model_defaults(self, tmp_path):
        session, client = await _make_session(tmp_path, model="claude-future-99")
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "128000"
        await session.disconnect()

    async def test_effort_omitted_by_default(self, tmp_path):
        session, client = await _make_session(tmp_path)
        assert client._agent_options.effort is None
        await session.disconnect()

    async def test_effort_set_when_configured(self, tmp_path):
        session, client = await _make_session(tmp_path, effort="high")
        assert client._agent_options.effort == "high"
        await session.disconnect()

    async def test_cwd_set(self, tmp_path):
        session, client = await _make_session(tmp_path)
        assert client._agent_options.cwd == str(tmp_path / "worktree")
        await session.disconnect()

    async def test_resume_set_when_session_id_provided(self, tmp_path):
        session, client = await _make_session(tmp_path, resume="ses-old-123")
        assert client._agent_options.resume == "ses-old-123"
        await session.disconnect()

    async def test_resume_omitted_by_default(self, tmp_path):
        session, client = await _make_session(tmp_path)
        assert client._agent_options.resume is None
        await session.disconnect()

    async def test_hooks_passed_through(self, tmp_path):
        hooks = {"PostToolUse": [{"matcher": "Bash", "hooks": [], "timeout": 30.0}]}
        session, client = await _make_session(tmp_path, hooks=hooks)
        assert client._agent_options.hooks == hooks
        await session.disconnect()

    async def test_extra_env_merged(self, tmp_path):
        session, client = await _make_session(tmp_path, env={"MY_VAR": "hello"})
        env = client._agent_options.env
        assert env["MY_VAR"] == "hello"
        assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" in env
        await session.disconnect()

    async def test_extra_env_overrides_defaults(self, tmp_path):
        session, client = await _make_session(
            tmp_path, env={"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "999"}
        )
        env = client._agent_options.env
        assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "999"
        await session.disconnect()


# ── Session lifecycle & state persistence ─────────────────────────────


class TestSessionLifecycle:
    async def test_turn_persists_session_id(self, tmp_path):
        session, _client = await _make_session(tmp_path)
        await session.turn("hello")

        state_path = tmp_path / "campaign" / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["session_id"] == "ses-abc-123"
        await session.disconnect()

    async def test_state_includes_version_stamps(self, tmp_path):
        session, _client = await _make_session(tmp_path)
        await session.turn("hello")

        state = json.loads((tmp_path / "campaign" / "state.json").read_text())
        assert state["sdk_version"] == SDK_VERSION
        assert state["cli_version"] == CLI_VERSION
        await session.disconnect()

    async def test_state_preserves_existing_fields(self, tmp_path):
        campaign_dir = tmp_path / "campaign"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "state.json").write_text(
            json.dumps({"repo_path": "/some/repo", "run_id": "run-42"})
        )

        session, _client = await _make_session(tmp_path)
        await session.turn("hello")

        state = json.loads((campaign_dir / "state.json").read_text())
        assert state["repo_path"] == "/some/repo"
        assert state["run_id"] == "run-42"
        assert state["session_id"] == "ses-abc-123"
        await session.disconnect()

    async def test_session_id_property(self, tmp_path):
        session, _client = await _make_session(tmp_path)
        assert session.session_id is None
        await session.turn("hello")
        assert session.session_id == "ses-abc-123"
        await session.disconnect()

    async def test_turn_without_connect_raises(self, tmp_path):
        opts = {"work_dir": str(tmp_path), "method_text": "x"}
        session = Session(client_factory=FakeClient, options=opts)
        with pytest.raises(RuntimeError, match="connect"):
            await session.turn("hello")

    async def test_disconnect(self, tmp_path):
        session, client = await _make_session(tmp_path)
        assert client.connected
        await session.disconnect()
        assert not client.connected

    async def test_atomic_write_creates_parent_dirs(self, tmp_path):
        opts = {
            "work_dir": str(tmp_path / "deep" / "nested" / "campaign"),
            "method_text": "x",
        }
        result_msg = FakeResultMessage(session_id="ses-new")

        def factory(agent_options):
            return FakeClient(script=[result_msg])

        session = Session(client_factory=factory, options=opts)
        await session.connect()
        await session.turn("hello")

        state_path = tmp_path / "deep" / "nested" / "campaign" / "state.json"
        assert state_path.exists()
        assert json.loads(state_path.read_text())["session_id"] == "ses-new"
        await session.disconnect()


# ── Transient error classification ───────────────────────────────────


class TestTransientErrors:
    def test_process_error_143_is_transient(self):
        from orchestrator.v2.session import is_transient
        assert is_transient(ProcessError("killed", exit_code=143))

    def test_process_error_1_is_not_transient(self):
        from orchestrator.v2.session import is_transient
        assert not is_transient(ProcessError("failed", exit_code=1))

    def test_fatal_message_reader_is_transient(self):
        from orchestrator.v2.session import is_transient
        assert is_transient(RuntimeError("Fatal error in message reader"))

    def test_api_5xx_is_transient(self):
        from orchestrator.v2.session import APIServerError, is_transient
        assert is_transient(APIServerError(502))

    def test_generic_exc_with_status_code_500(self):
        from orchestrator.v2.session import is_transient
        exc = RuntimeError("oops")
        exc.status_code = 500  # type: ignore[attr-defined]
        assert is_transient(exc)

    def test_generic_runtime_error_is_not_transient(self):
        from orchestrator.v2.session import is_transient
        assert not is_transient(RuntimeError("something broke"))

    def test_exit_143_on_generic_exc(self):
        from orchestrator.v2.session import is_transient
        exc = RuntimeError("process died")
        exc.exit_code = 143  # type: ignore[attr-defined]
        assert is_transient(exc)

    def test_stdlib_timeout_is_transient(self):
        from orchestrator.v2.session import is_transient
        assert is_transient(TimeoutError("connection timed out"))

    def test_os_error_timed_out_is_transient(self):
        from orchestrator.v2.session import is_transient
        assert is_transient(OSError("Operation timed out"))


# ── Transient retry (spec 3.5 / B9) ──────────────────────────────────


class _FlakyClient(FakeClient):
    """FakeClient whose query() raises the queued errors before succeeding."""

    def __init__(self, errors: list[BaseException], **kw):
        super().__init__(**kw)
        self.errors = errors

    async def query(self, prompt: str) -> None:
        if self.errors:
            raise self.errors.pop(0)
        await super().query(prompt)


def _flaky_session(tmp_path, errors, script, sleeps, connect_errors=None):
    seen_opts: list = []
    client = _FlakyClient(errors, script=script)
    connect_errors = connect_errors if connect_errors is not None else []

    def factory(opts):
        seen_opts.append(opts)
        if connect_errors:
            raise connect_errors.pop(0)
        return client

    async def fake_sleep(s):
        sleeps.append(s)

    session = Session(
        client_factory=factory,
        options={"work_dir": str(tmp_path / "campaign"), "method_text": "x"},
        sleep=fake_sleep,
    )
    return session, client, seen_opts


class TestTransientRetry:
    async def test_process_error_143_retried_then_succeeds(self, tmp_path):
        sleeps: list = []
        session, client, _ = _flaky_session(
            tmp_path, [ProcessError("killed", exit_code=143)], [FakeResultMessage(session_id="s1")], sleeps,
        )
        await session.connect()
        result = await session.turn("hello")
        assert result.session_id == "s1"
        assert client.queries == ["hello"]
        assert len(sleeps) == 1

    async def test_retry_reconnects_with_resume(self, tmp_path):
        script = [FakeResultMessage(session_id="s1"), FakeResultMessage(session_id="s1")]
        session, _client, seen = _flaky_session(tmp_path, [], script, [])
        await session.connect()
        await session.turn("first")
        _client.errors.append(ProcessError("killed", exit_code=143))
        await session.turn("second")
        assert seen[-1].resume == "s1"

    async def test_non_transient_not_retried(self, tmp_path):
        sleeps: list = []
        session, _c, _ = _flaky_session(
            tmp_path, [ValueError("bad")], [FakeResultMessage()], sleeps,
        )
        await session.connect()
        with pytest.raises(ValueError):
            await session.turn("hello")
        assert sleeps == []

    async def test_gives_up_after_three_tries(self, tmp_path):
        sleeps: list = []
        errs = [ProcessError("killed", exit_code=143), ProcessError("killed", exit_code=143), ProcessError("killed", exit_code=143)]
        session, _c, _ = _flaky_session(tmp_path, errs, [FakeResultMessage()], sleeps)
        await session.connect()
        with pytest.raises(ProcessError):
            await session.turn("hello")
        assert len(sleeps) == 2

    async def test_result_is_error_5xx_retried(self, tmp_path):
        sleeps: list = []
        script = [
            FakeResultMessage(is_error=True, result="API Error: 529 Overloaded"),
            FakeResultMessage(session_id="ok"),
        ]
        session, _c, _ = _flaky_session(tmp_path, [], script, sleeps)
        await session.connect()
        result = await session.turn("hello")
        assert result.session_id == "ok"
        assert len(sleeps) == 1

    async def test_result_is_error_non_api_not_retried(self, tmp_path):
        sleeps: list = []
        script = [FakeResultMessage(is_error=True, result="max turns", session_id="x")]
        session, _c, _ = _flaky_session(tmp_path, [], script, sleeps)
        await session.connect()
        result = await session.turn("hello")
        assert result.is_error and sleeps == []

    async def test_connect_retried_on_transient(self, tmp_path):
        sleeps: list = []
        session, client, _ = _flaky_session(
            tmp_path, [], [FakeResultMessage()], sleeps,
            connect_errors=[ProcessError("Fatal error in message reader", exit_code=143)],
        )
        await session.connect()
        assert client.connected and len(sleeps) == 1
