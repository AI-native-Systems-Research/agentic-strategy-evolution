"""Nous v2 session: builds SDK options and manages session lifecycle.

Spec reference: R1 / spec 3.1.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import SystemPromptPreset

# ── Model → max output token map ─────────────────────────────────────────

MODEL_MAX_OUTPUT: dict[str, int] = {
    "claude-opus-4-6": 128_000,
    "claude-opus-4-5-20250514": 128_000,
    "claude-sonnet-4-5-20250514": 128_000,
    "claude-sonnet-4-20250514": 64_000,
}

_DEFAULT_MAX_OUTPUT = 128_000

# ── SDK / CLI version stamps ──────────────────────────────────────────────

SDK_VERSION = "0.2.172"

try:
    from claude_agent_sdk._cli_version import __cli_version__ as CLI_VERSION
except ImportError:  # pragma: no cover
    CLI_VERSION = "unknown"

# ── Default configuration ─────────────────────────────────────────────────

DEFAULT_MODEL = "claude-opus-4-6"
DEFAULT_MAX_BUFFER_SIZE = 32 * 1024 * 1024  # 32 MB (fixes B7)


class Session:
    """Wraps a ``ClaudeSDKClient`` with Nous-specific options.

    Parameters
    ----------
    client_factory:
        Callable that returns a client object with the same interface as
        ``ClaudeSDKClient`` (connect, query, receive_response, interrupt,
        disconnect).  In production this is ``ClaudeSDKClient``; in tests
        it is ``FakeClient``.
    options:
        Campaign configuration dict.  Recognised keys:

        - ``model`` (str): model id, default ``claude-opus-4-6``
        - ``effort`` (str | None): reasoning effort level
        - ``method_text`` (str): methodology text appended to system prompt
        - ``hooks`` (dict): event-name → list[HookMatcher] mapping
        - ``cwd`` (str | Path): campaign worktree path
        - ``work_dir`` (str | Path): campaign work-dir for state.json
        - ``resume`` (str | None): session_id to resume
        - ``env`` (dict[str, str]): extra env vars
    """

    def __init__(
        self,
        client_factory: Callable[..., Any],
        options: dict[str, Any],
    ) -> None:
        self._client_factory = client_factory
        self._options = dict(options)
        self._client: Any | None = None
        self._session_id: str | None = options.get("resume")

    # ── Option building ───────────────────────────────────────────────

    def build_agent_options(self) -> ClaudeAgentOptions:
        """Construct ``ClaudeAgentOptions`` from campaign config."""
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

    async def connect(self) -> Any:
        """Create and connect the SDK client."""
        opts = self.build_agent_options()
        self._client = self._client_factory(opts)
        await self._client.connect()
        return self._client

    async def turn(
        self, prompt: str, on_message: Callable[..., Any] | None = None,
    ) -> Any:
        """Send a single turn and persist session state afterward.

        Returns the ``ResultMessage`` from ``receive_response()``.
        """
        if self._client is None:
            raise RuntimeError("Session.connect() must be called first")

        await self._client.query(prompt)

        result = None
        async for msg in self._client.receive_response():
            if on_message is not None:
                on_message(msg)
            result = msg

        if result is not None and hasattr(result, "session_id") and result.session_id:
            self._session_id = result.session_id
            self._persist_session_id()

        return result

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    # ── State persistence ─────────────────────────────────────────────

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def _state_path(self) -> Path | None:
        work_dir = self._options.get("work_dir")
        if work_dir is None:
            return None
        return Path(work_dir) / "state.json"

    def _persist_session_id(self) -> None:
        """Atomically write session_id (and version stamps) to state.json.

        Uses write-to-tmp + rename for crash safety.
        """
        state_path = self._state_path()
        if state_path is None:
            return

        state_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing state if present
        existing: dict[str, Any] = {}
        if state_path.exists():
            try:
                existing = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        existing["session_id"] = self._session_id
        existing["sdk_version"] = SDK_VERSION
        existing["cli_version"] = CLI_VERSION

        # Atomic write: tmp file in same dir, then rename
        fd, tmp = tempfile.mkstemp(
            dir=str(state_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(existing, f, indent=2)
                f.write("\n")
            os.replace(tmp, str(state_path))
        except BaseException:
            # Clean up the tmp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
