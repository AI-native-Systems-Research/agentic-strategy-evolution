"""Tests for tests.fakes.sdk_client.FakeClient."""

from __future__ import annotations

import inspect

import pytest

from tests.fakes.sdk_client import (
    FakeAssistantMessage,
    FakeClient,
    FakeResultMessage,
)


class TestFakeClientBasics:
    async def test_connect_disconnect(self):
        client = FakeClient()
        assert not client.connected
        await client.connect()
        assert client.connected
        await client.disconnect()
        assert not client.connected

    async def test_query_before_connect_raises(self):
        client = FakeClient()
        with pytest.raises(RuntimeError, match="connect"):
            await client.query("hello")

    async def test_query_records_prompts(self):
        client = FakeClient()
        await client.connect()
        await client.query("first")
        await client.query("second")
        assert client.queries == ["first", "second"]

    async def test_receive_response_yields_messages(self):
        result = FakeResultMessage(session_id="ses-1", total_cost_usd=0.05)
        client = FakeClient(script=[result])
        await client.connect()
        await client.query("go")
        msgs = [msg async for msg in client.receive_response()]
        assert len(msgs) == 1
        assert msgs[0].session_id == "ses-1"
        assert msgs[0].total_cost_usd == 0.05


class TestFakeClientScript:
    async def test_assistant_then_result(self):
        assistant = FakeAssistantMessage(
            content=[{"type": "text", "text": "Hello!"}],
            session_id="ses-2",
        )
        result = FakeResultMessage(session_id="ses-2")
        client = FakeClient(script=[assistant, result])
        await client.connect()
        await client.query("hi")
        msgs = [msg async for msg in client.receive_response()]
        assert len(msgs) == 2
        assert msgs[-1].session_id == "ses-2"
        assert msgs[-1].subtype == "result"

    async def test_tool_use_invokes_hooks(self):
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
        await client.connect()
        await client.query("list files")
        async for _ in client.receive_response():
            pass

        assert len(hook_calls) == 1
        assert hook_calls[0]["tool_name"] == "Bash"
        assert hook_calls[0]["tool_input"] == {"command": "ls"}
        assert hook_calls[0]["hook_event_name"] == "PostToolUse"

    async def test_multiple_tool_uses_invoke_hooks(self):
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
        await client.connect()
        await client.query("do things")
        async for _ in client.receive_response():
            pass

        assert hook_calls == ["Bash", "Read"]


class TestFakeClientFilesWritten:
    async def test_connect_writes_files(self, tmp_path):
        client = FakeClient(
            files_to_write={
                str(tmp_path / "out" / "result.json"): '{"ok": true}',
            }
        )
        await client.connect()
        assert (tmp_path / "out" / "result.json").exists()
        assert '"ok"' in (tmp_path / "out" / "result.json").read_text()


class TestFakeClientSignatures:
    """FakeClient methods must match ClaudeSDKClient's async signatures."""

    def test_async_methods_are_coroutines(self):
        for method_name in ("connect", "query", "interrupt", "disconnect"):
            fake = getattr(FakeClient, method_name)
            assert inspect.iscoroutinefunction(fake), (
                f"FakeClient.{method_name} must be async def"
            )

    def test_receive_response_is_async_generator(self):
        assert inspect.isasyncgenfunction(FakeClient.receive_response), (
            "FakeClient.receive_response must be an async generator"
        )
