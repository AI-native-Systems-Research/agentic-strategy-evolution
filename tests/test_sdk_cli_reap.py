"""A session that stops early must not leave the claude CLI (or its children) running.

The fake SDK below spawns a real dummy "CLI" process that ignores SIGTERM and has a long-lived child
of its own (standing in for a tool subprocess). Its transport's close() does nothing, like a CLI that
keeps working after the SDK stops listening. No network, no LLM.
"""
import os
import subprocess
import sys
import time
import types

import pytest

from orchestrator.sdk_dispatch import SDKTransientError, _default_sdk_runner_factory

_DUMMY_CLI = r"""
import signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(sys.argv[1], "w") as f:
    f.write(f"{child.pid}\n")
time.sleep(60)
"""


# A CLI that finishes normally: it writes its last transcript line about 1 s after the final result.
_FLUSHING_CLI = r"""
import sys, time
time.sleep(1.0)
with open(sys.argv[1], "w") as f:
    f.write("flushed\n")
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    return bool(stat.strip()) and not stat.strip().startswith("Z")


def _fake_sdk(tmp_path, spawned, *, messages=10, hang_after=None, finish=False):
    import anyio

    class ResultMessage:
        def __init__(self):
            self.usage = {"output_tokens": 10}
            self.total_cost_usd = 0.0
            self.duration_ms = 1
            self.num_turns = 1
            self.session_id = "sess-1"
            self.is_error = False
            self.subtype = "success"
            self.result = "done"

    class _Opts:
        def __init__(self, **kw):
            self.kw = kw

    class AssistantMessage:
        def __init__(self, i):
            self.content = []
            self.usage = {"output_tokens": 10_000}  # $0.75 per reply at $75/M
            self.message_id = f"m{i}"
            self.session_id = "sess-1"

    class SubprocessCLITransport:
        def __init__(self, prompt, options):  # noqa: ARG002
            self._process = None

        async def connect(self):
            if finish:
                self._process = await anyio.open_process(
                    [sys.executable, "-c", _FLUSHING_CLI, str(tmp_path / "transcript.done")])
                spawned["cli"] = self._process.pid
                return
            pid_file = tmp_path / "child.pid"
            self._process = await anyio.open_process([sys.executable, "-c", _DUMMY_CLI, str(pid_file)])
            for _ in range(200):
                if pid_file.exists() and pid_file.read_text().endswith("\n"):
                    break
                await anyio.sleep(0.05)
            spawned["cli"] = self._process.pid
            spawned["child"] = int(pid_file.read_text())

        async def close(self):  # a CLI that keeps going after the SDK stops listening
            return None

    async def _query(*, prompt, options, transport=None):  # noqa: ARG001
        await transport.connect()
        for i in range(messages):
            if hang_after is not None and i == hang_after:
                await anyio.sleep(60)
            yield AssistantMessage(i)
        if finish:
            yield ResultMessage()

    m = types.ModuleType("claude_agent_sdk")
    m.ClaudeAgentOptions = _Opts
    m.query = _query
    m.SubprocessCLITransport = SubprocessCLITransport
    return m


@pytest.fixture
def cleanup():
    pids = []
    yield pids
    for pid in pids:
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, TypeError):
            pass


def _run(monkeypatch, tmp_path, spawned, sdk_kw=None, **kw):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", _fake_sdk(tmp_path, spawned, **(sdk_kw or {})))
    return _default_sdk_runner_factory()(prompt="p", model="m", cwd=tmp_path, max_turns=5, **kw)


def test_cap_stop_kills_the_cli_and_its_children(monkeypatch, tmp_path, cleanup):
    spawned = {}
    try:
        res = _run(monkeypatch, tmp_path, spawned, max_cost_usd=2.0)
    finally:
        cleanup.extend(spawned.values())
    assert res.is_error and res.subtype == "error_max_budget_usd"
    assert spawned["cli"] and spawned["child"]
    assert not _alive(spawned["cli"]), "claude CLI still running after a cap stop"
    assert not _alive(spawned["child"]), "a CLI child process survived the cap stop"


def test_silence_watchdog_abort_kills_the_cli(monkeypatch, tmp_path, cleanup):
    spawned = {}
    try:
        with pytest.raises(SDKTransientError):
            _run(monkeypatch, tmp_path, spawned, sdk_kw={"hang_after": 1}, turn_silence_threshold=0.5)
    finally:
        cleanup.extend(spawned.values())
    assert not _alive(spawned["cli"]) and not _alive(spawned["child"])


def test_normal_finish_lets_the_cli_flush_its_transcript(monkeypatch, tmp_path, cleanup):
    spawned = {}
    try:
        res = _run(monkeypatch, tmp_path, spawned, sdk_kw={"messages": 1, "finish": True})
    finally:
        cleanup.extend(spawned.values())
    assert not res.is_error
    assert (tmp_path / "transcript.done").exists(), "CLI was killed before writing its last transcript line"
    assert not _alive(spawned["cli"])


def test_stop_returns_promptly(monkeypatch, tmp_path, cleanup):
    spawned = {}
    t0 = time.time()
    try:
        _run(monkeypatch, tmp_path, spawned, max_cost_usd=1.0)
    finally:
        cleanup.extend(spawned.values())
    assert time.time() - t0 < 20
