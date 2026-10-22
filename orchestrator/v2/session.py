"""Nous v2 session: builds SDK options and manages session lifecycle.

Spec reference: R1 / spec 3.1.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import SystemPromptPreset

from .errors import APIServerError, is_transient
from .resume import update_state

logger = logging.getLogger(__name__)

RETRY_DELAYS_S = (5.0, 30.0)  # 3 tries in all (spec 3.5 / B9)
_API_5XX = re.compile(r"\b5\d\d\b|overloaded", re.IGNORECASE)


MODEL_MAX_OUTPUT: dict[str, int] = {
    "claude-opus-4-6": 128_000,
    "claude-opus-4-5-20250514": 128_000,
    "claude-sonnet-4-5-20250514": 128_000,
    "claude-sonnet-4-20250514": 64_000,
}

_DEFAULT_MAX_OUTPUT = 128_000


SDK_VERSION = "0.2.172"

try:
    from claude_agent_sdk._cli_version import __cli_version__ as CLI_VERSION
except ImportError:  # pragma: no cover
    CLI_VERSION = "unknown"


DEFAULT_MODEL = "claude-opus-4-6"
DEFAULT_MAX_BUFFER_SIZE = 32 * 1024 * 1024  # 32 MB (fixes B7)


class Session:
    """Wraps a ClaudeSDKClient with Nous-specific options."""

    def __init__(
        self,
        client_factory: Callable[..., Any],
        options: dict[str, Any],
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._sleep = sleep
        self._client_factory = client_factory
        self._options = dict(options)
        self._client: Any | None = None
        self._session_id: str | None = options.get("resume")

    # ── Option building ───────────────────────────────────────────────

    def build_agent_options(self) -> ClaudeAgentOptions:
        model = self._options.get("model", DEFAULT_MODEL)
        max_output = MODEL_MAX_OUTPUT.get(model, _DEFAULT_MAX_OUTPUT)

        method_text = self._options.get("method_text", "")
        system_prompt: SystemPromptPreset = {
            "type": "preset",
            "preset": "claude_code",
            "append": method_text,
            "snapshot": True,
        }

        env: dict[str, str] = {
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_output),
        }
        work_dir = self._options.get("work_dir")
        if work_dir is not None:
            env["NOUS_WORK_DIR"] = str(work_dir)
        # Merge caller-supplied env (overrides defaults on collision)
        env.update(self._options.get("env", {}))

        kwargs: dict[str, Any] = {
            "model": model,
            "system_prompt": system_prompt,
            "max_buffer_size": DEFAULT_MAX_BUFFER_SIZE,
            "env": env,
            "permission_mode": "bypassPermissions",
        }

        effort = self._options.get("effort")
        if effort is not None:
            kwargs["effort"] = effort

        hooks = self._options.get("hooks")
        if hooks is not None:
            kwargs["hooks"] = hooks

        cwd = self._options.get("cwd")
        if cwd is not None:
            kwargs["cwd"] = str(cwd)

        if self._session_id is not None:
            kwargs["resume"] = self._session_id

        return ClaudeAgentOptions(**kwargs)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def _retry(self, fn: Callable[[], Any]) -> Any:
        """Await fn(), retrying transient errors with backoff (spec 3.5)."""
        for delay in (*RETRY_DELAYS_S, None):
            try:
                return await fn()
            except Exception as exc:
                if delay is None or not is_transient(exc):
                    raise
                logger.warning("transient SDK error (%s); retrying in %.0fs", exc, delay)
                await self._sleep(delay)

    async def _connect_once(self) -> Any:
        if self._client is not None:  # drop a dead client; resume picks up session_id
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = self._client_factory(self.build_agent_options())
        await self._client.connect()
        return self._client

    async def connect(self) -> Any:
        """Create and connect the SDK client."""
        return await self._retry(self._connect_once)

    async def turn(
        self, prompt: str, on_message: Callable[..., Any] | None = None,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("Session.connect() must be called first")
        first = True

        async def attempt() -> Any:
            nonlocal first
            if not first:
                await self._connect_once()
            first = False
            return await self._turn_once(prompt, on_message)

        return await self._retry(attempt)

    async def _turn_once(self, prompt: str, on_message: Callable[..., Any] | None) -> Any:
        await self._client.query(prompt)

        result = None
        async for msg in self._client.receive_response():
            if on_message is not None:
                on_message(msg)
            result = msg

        if result is not None and hasattr(result, "session_id") and result.session_id:
            self._session_id = result.session_id
            self._persist_session_id()

        text = str(getattr(result, "result", "") or "")
        if getattr(result, "is_error", False) and _API_5XX.search(text):
            raise APIServerError(500, text)
        return result

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    # ── State persistence ─────────────────────────────────────────────

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def _persist_session_id(self) -> None:
        work_dir = self._options.get("work_dir")
        if work_dir is None:
            return
        update_state(
            Path(work_dir), session_id=self._session_id,
            sdk_version=SDK_VERSION, cli_version=CLI_VERSION,
        )
