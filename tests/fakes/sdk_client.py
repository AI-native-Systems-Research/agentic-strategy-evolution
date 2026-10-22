"""FakeClient — scriptable stand-in for ``ClaudeSDKClient``.

Usage::

    script = [
        AssistantMessage(content=[...], model="claude-opus-4-6", ...),
        ResultMessage(session_id="ses-1", ...),
    ]
    client = FakeClient(script=script)
    await client.connect()
    await client.query("do something")
    async for msg in client.receive_response():
        result = msg
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any


@dataclasses.dataclass
class FakeAssistantMessage:
    """Minimal stand-in for ``claude_agent_sdk.types.AssistantMessage``."""

    content: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    model: str = "claude-opus-4-6"
    session_id: str = "fake-session-1"
    stop_reason: str = "end_turn"
    message_id: str = "msg-fake-1"
    usage: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"input_tokens": 100, "output_tokens": 50}
    )
    parent_tool_use_id: str | None = None
    error: str | None = None
    uuid: str = "uuid-fake-1"


@dataclasses.dataclass
class FakeResultMessage:
    """Minimal stand-in for ``claude_agent_sdk.types.ResultMessage``."""

    session_id: str = "fake-session-1"
    total_cost_usd: float = 0.01
    stop_reason: str = "end_turn"
    duration_ms: int = 1000
    duration_api_ms: int = 800
    is_error: bool = False
    num_turns: int = 1
    subtype: str = "result"
    usage: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"input_tokens": 100, "output_tokens": 50}
    )
    result: str = ""
    uuid: str = "uuid-result-1"


@dataclasses.dataclass
class FakeToolUse:
    """Describes a tool use that FakeClient should simulate."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_response: str = ""
    tool_use_id: str = "tu-fake-1"


class FakeClient:
    """Scriptable replacement for ``ClaudeSDKClient``.

    Parameters
    ----------
    script:
        Ordered sequence of messages the client will yield.  The final
        element should be a ``FakeResultMessage``.  Any ``FakeAssistantMessage``
        whose ``content`` contains tool-use dicts will trigger registered
        hook callbacks.
    files_to_write:
        Dict of ``{path: content}`` that ``connect()`` writes to disk,
        simulating agent file creation.
    hooks:
        Dict of ``{event_name: list[callback]}`` that FakeClient invokes
        when it encounters matching tool uses in the script.
    """

    def __init__(
        self,
        script: list[Any] | None = None,
        files_to_write: dict[str | Path, str] | None = None,
        hooks: dict[str, list[Callable[..., Any]]] | None = None,
    ) -> None:
        self._script = list(script or [FakeResultMessage()])
        self._files_to_write = files_to_write or {}
        self._hooks = hooks or {}
        self._connected = False
        self._queries: list[str] = []
        self._response_index = 0

    # ── ClaudeSDKClient interface ─────────────────────────────────────

    async def connect(self) -> None:
        self._connected = True
        for path, content in self._files_to_write.items():
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    async def query(self, prompt: str) -> None:
        if not self._connected:
            raise RuntimeError("FakeClient.connect() not called")
        self._queries.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        """Async generator that yields each scripted message in order."""
        if self._response_index >= len(self._script):
            raise RuntimeError("FakeClient script exhausted — add more messages to the script")

        while self._response_index < len(self._script):
            msg = self._script[self._response_index]
            self._response_index += 1

            if hasattr(msg, "content") and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        await self._invoke_hooks(msg, block)

            yield msg

    async def interrupt(self) -> None:
        pass

    async def disconnect(self) -> None:
        self._connected = False

    # ── Hook invocation ───────────────────────────────────────────────

    async def _invoke_hooks(
        self, msg: Any, tool_block: dict[str, Any]
    ) -> None:
        tool_name = tool_block.get("name", "")
        callbacks = self._hooks.get("PostToolUse", [])
        for cb in callbacks:
            hook_input = {
                "session_id": getattr(msg, "session_id", "fake-session-1"),
                "hook_event_name": "PostToolUse",
                "tool_name": tool_name,
                "tool_input": tool_block.get("input", {}),
                "tool_response": tool_block.get("response", ""),
                "tool_use_id": tool_block.get("id", "tu-fake"),
            }
            result = cb(hook_input, None, None)
            if isinstance(result, Awaitable):
                await result

    # ── Inspection helpers ────────────────────────────────────────────

    @property
    def queries(self) -> list[str]:
        return list(self._queries)

    @property
    def connected(self) -> bool:
        return self._connected
