"""Tests for tests.fakes.sdk_client.FakeClient."""

from __future__ import annotations

import anyio
import pytest

from tests.fakes.sdk_client import (
    FakeAssistantMessage,
    FakeClient,
    FakeResultMessage,
)


class TestFakeClientBasics:
    def test_connect_disconnect(self):
        client = FakeClient()
        assert not client.connected
        client.connect()
        assert client.connected
        client.disconnect()
        assert not client.connected

    def test_query_before_connect_raises(self):
        client = FakeClient()
        with pytest.raises(RuntimeError, match="connect"):
            client.query("hello")

    def test_query_records_prompts(self):
        client = FakeClient()
        client.connect()
        client.query("first")
        client.query("second")
        assert client.queries == ["first", "second"]

    def test_receive_response_returns_result(self):
        result = FakeResultMessage(session_id="ses-1", total_cost_usd=0.05)
        client = FakeClient(script=[result])
        client.connect()
        client.query("go")
        got = anyio.run(client.receive_response)
        assert got.session_id == "ses-1"
        assert got.total_cost_usd == 0.05


class TestFakeClientScript:
    def test_assistant_then_result(self):
        assistant = FakeAssistantMessage(
            content=[{"type": "text", "text": "Hello!"}],
            session_id="ses-2",
        )
        result = FakeResultMessage(session_id="ses-2")
        client = FakeClient(script=[assistant, result])
        client.connect()
        client.query("hi")
        got = anyio.run(client.receive_response)
        # The last message in the script is returned
        assert got.session_id == "ses-2"
        assert got.subtype == "result"

    def test_tool_use_invokes_hooks(self):
        hook_calls: list[dict] = []

        def hook_cb(hook_input, _signal, _ctx):
            hook_calls.append(hook_input)

        assistant = FakeAssistantMessage(
            content=[
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "tu-1",
                    "input": {"command": "ls"},
                    "response": "file.txt",
                }
            ],
        )
        result = FakeResultMessage()
        client = FakeClient(
            script=[assistant, result],
            hooks={"PostToolUse": [hook_cb]},
        )
        client.connect()
        client.query("list files")
        anyio.run(client.receive_response)

        assert len(hook_calls) == 1
        assert hook_calls[0]["tool_name"] == "Bash"
        assert hook_calls[0]["tool_input"] == {"command": "ls"}
        assert hook_calls[0]["hook_event_name"] == "PostToolUse"

    def test_multiple_tool_uses_invoke_hooks(self):
        hook_calls: list[str] = []

        def hook_cb(hook_input, _signal, _ctx):
            hook_calls.append(hook_input["tool_name"])

        assistant = FakeAssistantMessage(
            content=[
                {"type": "tool_use", "name": "Bash", "id": "tu-1", "input": {}},
                {"type": "tool_use", "name": "Read", "id": "tu-2", "input": {}},
            ],
        )
        result = FakeResultMessage()
        client = FakeClient(
            script=[assistant, result],
            hooks={"PostToolUse": [hook_cb]},
        )
        client.connect()
        client.query("do things")
        anyio.run(client.receive_response)

        assert hook_calls == ["Bash", "Read"]


class TestFakeClientFilesWritten:
    def test_connect_writes_files(self, tmp_path):
        client = FakeClient(
            files_to_write={
                str(tmp_path / "out" / "result.json"): '{"ok": true}',
            }
        )
        client.connect()
        assert (tmp_path / "out" / "result.json").exists()
        assert '"ok"' in (tmp_path / "out" / "result.json").read_text()
