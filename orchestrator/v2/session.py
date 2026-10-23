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

from .resume import update_state

logger = logging.getLogger(__name__)

RETRY_DELAYS_S = (5.0, 30.0)  # 3 tries in all (spec 3.5 / B9)
_API_5XX = re.compile(r"\b5\d\d\b|overloaded", re.IGNORECASE)
_API_429 = re.compile(r"\b429\b|rate.?limit", re.IGNORECASE)
_CONTEXT_FULL = re.compile(
    r"prompt is too long|context (window|length|limit)|context_length_exceeded", re.IGNORECASE)


class APIServerError(Exception):
    """An API 5xx / overloaded / 429 reply surfaced as ResultMessage.is_error."""

    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        super().__init__(f"API returned {status_code}: {body}")


class ContextOverflowError(Exception):
    """The session context is full (spec 3.10): continue in a fresh session from the digest."""


class SessionResultError(Exception):
    """Any other ResultMessage.is_error (auth, max turns, ...): a phase failure."""


def is_transient(exc: BaseException) -> bool:
    """Spec 3.5 / B9: exit 143, 'Fatal error in message reader', timeouts, API 5xx."""
    if isinstance(exc, OSError) and "timed out" in str(exc).lower():
        return True
    if getattr(exc, "exit_code", None) == 143 or "Fatal error in message reader" in str(exc):
        return True
    code = getattr(exc, "status_code", None)
    return isinstance(code, int) and (code == 429 or 500 <= code < 600)


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
        self.cut = False  # last turn ended at the output cap (B12)

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
        last_main_stop = None
        async for msg in self._client.receive_response():
            if on_message is not None:
                on_message(msg)
            result = msg
            if hasattr(msg, "content") and getattr(msg, "parent_tool_use_id", None) is None:
                last_main_stop = getattr(msg, "stop_reason", None)
        # B12: the turn ended at the output cap (subagent cut-offs do not count)
        self.cut = "max_tokens" in (getattr(result, "stop_reason", None), last_main_stop)

        if result is not None and hasattr(result, "session_id") and result.session_id:
            self._session_id = result.session_id
            self._persist_session_id()

        if getattr(result, "is_error", False):
            text = str(getattr(result, "result", "") or "") + " " + " ".join(
                getattr(result, "errors", None) or [])
            status = getattr(result, "api_error_status", None)
            if isinstance(status, int) and (status == 429 or 500 <= status < 600):
                raise APIServerError(status, text)
            if _CONTEXT_FULL.search(text):
                raise ContextOverflowError(text)
            if _API_5XX.search(text):
                raise APIServerError(500, text)
            if _API_429.search(text):
                raise APIServerError(429, text)
            raise SessionResultError(f"session returned an error result: {text.strip()}")
        return result

    @property
    def effort(self) -> str | None:
        return self._options.get("effort")

    async def reconnect(self, effort: str | None) -> None:
        """Resume the same session with a new effort level (spec 3.10)."""
        self._options["effort"] = effort
        await self._retry(self._connect_once)

    async def restart_fresh(self) -> None:
        """Drop the session id and connect a new session (spec 3.10 context-full fallback)."""
        self._session_id = None
        self._options.pop("resume", None)
        await self._retry(self._connect_once)

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
