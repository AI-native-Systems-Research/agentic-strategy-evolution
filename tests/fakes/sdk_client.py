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

import asyncio
import dataclasses
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from claude_agent_sdk.types import _hooks_to_internal_format
from claude_agent_sdk._internal.query import _convert_hook_output_for_cli


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
    api_error_status: int | None = None
    errors: list[str] | None = None


@dataclasses.dataclass
class FakePreCompact:
    """Script item: fire the PreCompact hooks here (not yielded)."""

    trigger: str = "auto"


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
        hook callbacks: ``PostToolUse``, or ``PostToolUseFailure`` when the
        block has ``"is_error": True`` (its ``"response"`` is the error text).
        A ``FakePreCompact`` item fires the PreCompact hooks.  Before each
        ``FakeResultMessage`` the Stop hooks fire (``stop_hook_active`` is
        True on a re-fire); a "block" decision drops that result, applies the
        next ``per_turn_files`` entry and runs the next scripted turn, as the
        CLI does when a Stop hook blocks.
    files_to_write:
        Dict of ``{path: content}`` that ``connect()`` writes to disk,
        simulating agent file creation.
    hooks:
        SDK-style hooks dict: ``{event_name: list[HookMatcher]}``.
        Passed through ``_hooks_to_internal_format`` exactly like the
        real SDK does, then each callback is awaited per the real contract.
    """

    def __init__(
        self,
        script: list[Any] | None = None,
        files_to_write: dict[str | Path, str] | None = None,
        hooks: dict[str, list[Any]] | None = None,
        per_turn_files: list[dict[str | Path, str]] | None = None,
    ) -> None:
        self._script = list(script or [FakeResultMessage()])
        self._files_to_write = files_to_write or {}
        self._per_turn_files = per_turn_files or []
        self._internal_hooks: dict[str, list[dict[str, Any]]] = {}
        if hooks:
            self._internal_hooks = _hooks_to_internal_format(hooks)
        self._connected = False
        self._queries: list[str] = []
        self._response_index = 0
        self._turn_count = 0
        self.stop_decisions: list[str | None] = []  # one per Stop firing

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
        self._write_turn_files()

    def _write_turn_files(self) -> None:
        if self._turn_count < len(self._per_turn_files):
            for path, content in self._per_turn_files[self._turn_count].items():
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
        self._turn_count += 1

    async def receive_response(self) -> AsyncIterator[Any]:
        """Async generator that yields each scripted message in order.

        Stops after yielding a ``FakeResultMessage``, so multiple
        ``query()`` / ``receive_response()`` rounds work naturally:
        each round consumes messages up to and including the next
        ``FakeResultMessage``.
        """
        if self._response_index >= len(self._script):
            raise RuntimeError("FakeClient script exhausted — add more messages to the script")

        stop_hook_active = False
        while self._response_index < len(self._script):
            msg = self._script[self._response_index]
            self._response_index += 1

            if isinstance(msg, FakePreCompact):
                await self._run_event_hooks("PreCompact", {
                    "hook_event_name": "PreCompact", "trigger": msg.trigger,
                    "session_id": "fake-session-1", "transcript_path": "", "cwd": "",
                })
                continue

            if hasattr(msg, "content") and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        await self._invoke_hooks(msg, block)

            if isinstance(msg, FakeResultMessage) and "Stop" in self._internal_hooks:
                out = await self._run_event_hooks("Stop", {
                    "hook_event_name": "Stop", "stop_hook_active": stop_hook_active,
                    "session_id": msg.session_id, "transcript_path": "", "cwd": "",
                })
                decision = (out or {}).get("decision")
                self.stop_decisions.append(decision)
                if decision == "block" and self._response_index < len(self._script):
                    stop_hook_active = True
                    self._write_turn_files()  # the agent's next turn answers the block
                    continue

            yield msg

            if isinstance(msg, FakeResultMessage):
                break

    async def interrupt(self) -> None:
        pass

    async def disconnect(self) -> None:
        self._connected = False

    # ── Hook invocation (mirrors real SDK contract) ───────────────────

    async def _invoke_hooks(
        self, msg: Any, tool_block: dict[str, Any]
    ) -> None:
        tool_name = tool_block.get("name", "")
        tool_use_id = tool_block.get("id", "tu-fake")
        response = tool_block.get("response", "")
        event = "PostToolUseFailure" if tool_block.get("is_error") else "PostToolUse"
        hook_input = {
            "session_id": getattr(msg, "session_id", "fake-session-1"),
            "hook_event_name": event,
            "tool_name": tool_name,
            "tool_input": tool_block.get("input", {}),
            "tool_use_id": tool_use_id,
            "transcript_path": "",
            "cwd": "",
        }
        if event == "PostToolUseFailure":
            hook_input["error"] = response
        else:
            hook_input["tool_response"] = response
        await self._run_event_hooks(event, hook_input, tool_use_id)

    async def _run_event_hooks(
        self,
        event: str,
        hook_input: dict[str, Any],
        tool_use_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Run all matching hooks for an event, following the real SDK contract."""
        matchers = self._internal_hooks.get(event, [])
        for matcher_dict in matchers:
            callbacks = matcher_dict.get("hooks", [])
            for cb in callbacks:
                if not inspect.iscoroutinefunction(cb):
                    raise TypeError(
                        f"Hook callback for {event} must be async def, "
                        f"got {type(cb).__name__}"
                    )
                hook_output = await cb(
                    hook_input,
                    tool_use_id,
                    {"signal": None},
                )
                converted = _convert_hook_output_for_cli(hook_output)
                if converted.get("decision") == "block":
                    return converted
        return None

    # ── Inspection helpers ────────────────────────────────────────────

    @property
    def queries(self) -> list[str]:
        return list(self._queries)

    @property
    def connected(self) -> bool:
        return self._connected
