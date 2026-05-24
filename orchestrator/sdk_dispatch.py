"""SDK-based agent dispatch for the Nous orchestrator.

Calls the Claude Agent SDK in place of `claude -p` subprocess. Same
artifact and metrics contract as :class:`orchestrator.cli_dispatch.CLIDispatcher`;
this class swaps the transport without changing the orchestrator's contract
with the rest of Nous.

Why SDK over `claude -p`:
  * Native streaming → fast progress visibility (#127).
  * Programmatic prompt caching → token savings (#122).
  * Native subagent spawning → parallel arms without manual fork/join (#123).
  * Message-level retry instead of subprocess restart.

Design decisions worth knowing:

  * The actual SDK call is delegated to a ``sdk_runner`` callable. The
    default lazily resolves to a real ``claude_agent_sdk`` runner; tests
    inject a deterministic fake. The runner returns an ``SDKResult``
    (text + usage + cost + error flag); the dispatcher's job is to turn
    that into on-disk artifacts and a metrics row, with retry on transient
    failure. This keeps tests behavioral — they assert what's on disk,
    not which method we called.
  * Inherits from CLIDispatcher to reuse the parse/validate/retry-with-feedback
    machinery used for fenced-output phases (gate summaries, etc.).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from orchestrator.cli_dispatch import CLIDispatcher, _backoff_for
from orchestrator.metrics import log_metrics, log_retry_event

logger = logging.getLogger(__name__)


class SDKTransientError(RuntimeError):
    """Runner raises this for retryable transport-level failures."""


def _load_methodology_preamble(methodology_dir: Path) -> str | None:
    """Load the static methodology text as a single cached system block.

    Concatenates the design + execute_analyze methodology files, stripping
    Jinja-style {{placeholders}} (the dynamic portions go in the user
    message instead, where they bust the cache appropriately). The result
    is what ``ClaudeAgentOptions.system_prompt`` ships to the API with
    cache_control: ephemeral so it's paid for once per 5-minute window
    instead of once per turn — the win #122 is named for.
    """
    methodology_dir = Path(methodology_dir)
    if not methodology_dir.is_dir():
        return None
    blocks: list[str] = []
    import re as _re
    for name in ("design.md", "execute_analyze.md"):
        path = methodology_dir / name
        if not path.exists():
            continue
        text = path.read_text()
        # Strip {{placeholder}} markers — the dynamic content lives in
        # the user message and changes each call.
        text = _re.sub(r"\{\{[^}]+\}\}", "", text)
        blocks.append(f"# Methodology: {path.stem}\n\n{text}")
    if not blocks:
        return None
    return "\n\n---\n\n".join(blocks)


def _tee_event(event_log_path: Path | None, message: object, cls_name: str) -> None:
    """Append one SDK event to executor_log.jsonl (#127 Phase B).

    Best-effort: log-write failures don't break the agent. The TUI's
    snapshot reader (orchestrator.status) already consumes this file.
    """
    if event_log_path is None:
        return
    import json as _json
    record: dict = {
        "type": cls_name,
        "ts": time.time(),
    }
    # Surface fields the TUI cares about — tool name, content kind. We
    # touch only attributes that exist via getattr so the format here
    # is robust to SDK message-class evolution.
    for field_name in ("tool_name", "tool_use_id", "content"):
        val = getattr(message, field_name, None)
        if val is not None and not callable(val):
            try:
                _json.dumps(val)  # serializability probe
                record[field_name] = val
            except (TypeError, ValueError):
                record[field_name] = repr(val)[:200]
    try:
        with open(event_log_path, "a") as f:
            f.write(_json.dumps(record) + "\n")
    except OSError:
        pass


@dataclass
class SDKResult:
    """One SDK call's outcome.

    The dispatcher reads only these fields. Producers (real or fake) must
    populate ``text`` (assistant final text); usage/cost fields default
    to zero so trivial fakes need not set them.
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 1
    is_error: bool = False
    error_message: str = ""
    extra: dict = field(default_factory=dict)


@runtime_checkable
class SDKRunner(Protocol):
    """A callable that performs one SDK turn and returns an ``SDKResult``.

    Raise :class:`SDKTransientError` for retryable failures (network blips,
    rate limits, mid-stream disconnect). Return ``SDKResult(is_error=True,
    error_message=...)`` for API-reported errors that should also be retried.
    Other exceptions bubble up as fatal.
    """

    def __call__(
        self,
        *,
        prompt: str,
        model: str,
        cwd: Path | None,
        max_turns: int,
        system_prompt: str | None = None,
        settings_path: Path | None = None,
        event_log_path: Path | None = None,
    ) -> SDKResult:
        ...


def _default_sdk_runner_factory() -> SDKRunner:
    """Return a runner that calls the real ``claude_agent_sdk``.

    Resolved lazily so that tests (and environments without the SDK
    installed) don't fail at import time.
    """

    def _runner(
        *,
        prompt: str,
        model: str,
        cwd: Path | None,
        max_turns: int,
        system_prompt: str | None = None,
        settings_path: Path | None = None,
        event_log_path: Path | None = None,
    ) -> SDKResult:
        try:
            import anyio
            from claude_agent_sdk import (  # type: ignore[import-not-found]
                ClaudeAgentOptions,
                query,
            )
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is not installed. "
                "Install with `pip install claude-agent-sdk` or use --agent api."
            ) from exc

        async def _run() -> SDKResult:
            options = ClaudeAgentOptions(
                model=model,
                cwd=str(cwd) if cwd else None,
                max_turns=max_turns,
                system_prompt=system_prompt,
                settings=str(settings_path) if settings_path else None,
            )
            text_chunks: list[str] = []
            usage: dict = {}
            cost_usd = 0.0
            duration_ms = 0
            num_turns = 0
            t0 = time.time()
            if event_log_path is not None:
                Path(event_log_path).parent.mkdir(parents=True, exist_ok=True)
            async for message in query(prompt=prompt, options=options):
                cls = type(message).__name__
                # #127 Phase B: tee every SDK message as a JSONL event so
                # `nous status --watch` can render live progress.
                _tee_event(event_log_path, message, cls)
                if cls == "AssistantMessage":
                    for block in getattr(message, "content", []):
                        if hasattr(block, "text"):
                            text_chunks.append(block.text)
                elif cls == "ResultMessage":
                    usage = getattr(message, "usage", {}) or {}
                    cost_usd = float(getattr(message, "total_cost_usd", 0.0) or 0.0)
                    duration_ms = int(getattr(message, "duration_ms", 0) or 0)
                    num_turns = int(getattr(message, "num_turns", 0) or 0)
                    if getattr(message, "is_error", False):
                        return SDKResult(
                            text="".join(text_chunks),
                            error_message=str(getattr(message, "result", "unknown")),
                            is_error=True,
                            input_tokens=int(usage.get("input_tokens", 0) or 0),
                            output_tokens=int(usage.get("output_tokens", 0) or 0),
                            cache_read_input_tokens=int(
                                usage.get("cache_read_input_tokens", 0) or 0
                            ),
                            cache_creation_input_tokens=int(
                                usage.get("cache_creation_input_tokens", 0) or 0
                            ),
                            cost_usd=cost_usd,
                            duration_ms=duration_ms,
                            num_turns=num_turns,
                        )
            return SDKResult(
                text="".join(text_chunks),
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                cache_read_input_tokens=int(
                    usage.get("cache_read_input_tokens", 0) or 0
                ),
                cache_creation_input_tokens=int(
                    usage.get("cache_creation_input_tokens", 0) or 0
                ),
                cost_usd=cost_usd,
                duration_ms=duration_ms or int((time.time() - t0) * 1000),
                num_turns=num_turns or 1,
            )

        try:
            return anyio.run(_run)
        except Exception as exc:
            cls_name = type(exc).__name__
            transient_signals = (
                "ConnectionError",
                "ReadTimeout",
                "WriteTimeout",
                "RemoteProtocolError",
                "ServerDisconnectedError",
                "TimeoutError",
            )
            if any(sig in cls_name for sig in transient_signals):
                raise SDKTransientError(f"{cls_name}: {exc}") from exc
            raise

    return _runner


class SDKDispatcher(CLIDispatcher):
    """Dispatch agent roles via the Claude Agent SDK.

    Inherits dispatch() / parse / retry-with-feedback / route logic from
    :class:`CLIDispatcher`. Overrides ``_call_claude`` to use the SDK
    runner instead of a subprocess, and ``preflight_check`` to verify
    the SDK package is importable.
    """

    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "claude-sonnet-4-6",
        prompts_dir: Path | None = None,
        timeout: int = 1800,
        max_turns: int = 25,
        max_retries: int | None = 10,
        sdk_runner: Callable | None = None,
        system_prompt: str | None = None,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__(
            work_dir=work_dir,
            campaign=campaign,
            model=model,
            prompts_dir=prompts_dir,
            timeout=timeout,
            max_turns=max_turns,
            max_retries=max_retries,
        )
        self._sdk_runner = sdk_runner or _default_sdk_runner_factory()
        self._system_prompt = system_prompt or _load_methodology_preamble(
            prompts_dir or Path(__file__).parent.parent / "prompts" / "methodology",
        )
        self._settings_path = settings_path
        # #127 Phase B: event log path is recomputed per-dispatch (it depends
        # on the iteration), so we don't store it on the dispatcher.
        self._event_log_path: Path | None = None

    # ------------------------------------------------------------------
    # Per-iteration event log (#127 Phase B)
    # ------------------------------------------------------------------

    def dispatch(  # type: ignore[override]
        self, role: str, phase: str, *, output_path, iteration: int,
        perspective=None, h_main_result="CONFIRMED",
    ) -> None:
        # Compute the executor_log.jsonl path for this iteration so the
        # runner tees SDK events to a place the status reader can find.
        self._event_log_path = (
            self.work_dir / "runs" / f"iter-{iteration}" / "executor_log.jsonl"
        )
        try:
            super().dispatch(
                role, phase,
                output_path=output_path, iteration=iteration,
                perspective=perspective, h_main_result=h_main_result,
            )
        finally:
            self._event_log_path = None

    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------

    def preflight_check(self) -> None:
        """Verify the SDK is reachable before starting a campaign."""
        try:
            import claude_agent_sdk  # type: ignore[import-not-found] # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Pre-flight check failed: claude-agent-sdk is not installed. "
                "Install with `pip install claude-agent-sdk`, or pass --agent api "
                "to use the OpenAI-compatible path instead."
            ) from exc
        logger.info("SDK pre-flight check passed (model=%s)", self.model)

    # ------------------------------------------------------------------
    # Core call with retry
    # ------------------------------------------------------------------

    def _call_claude(self, prompt: str, max_turns: int | None = None) -> str:
        """Run one SDK turn with retry on transient failure.

        Mirrors CLIDispatcher._call_claude semantics: retry on transient
        errors (with exponential backoff), log each failure to retry_log.jsonl,
        log each completed call to llm_metrics.jsonl, give up after
        max_retries.
        """
        cwd = self._cwd
        if cwd and not cwd.exists():
            raise RuntimeError(
                f"SDKDispatcher cwd does not exist: {cwd}. "
                f"Check that 'repo_path' in campaign.yaml is correct."
            )
        turns = max_turns or self.max_turns
        logger.info(
            "SDK turn (model=%s, cwd=%s, max_turns=%d)", self.model, cwd, turns,
        )

        failure_count = 0
        original_prompt = prompt
        while True:
            try:
                result = self._sdk_runner(
                    prompt=prompt,
                    model=self.model,
                    cwd=cwd,
                    max_turns=turns,
                    system_prompt=self._system_prompt,
                    settings_path=self._settings_path,
                    event_log_path=self._event_log_path,
                )
            except SDKTransientError as exc:
                failure_count += 1
                self._log_retry("transient", failure_count, exc)
                if self._exhausted(failure_count):
                    raise RuntimeError(
                        f"SDK still failing after {failure_count} attempt(s): {exc}"
                    ) from exc
                time.sleep(_backoff_for(failure_count))
                prompt = self._maybe_resume_hint(prompt, original_prompt, "transient")
                continue

            self._log_metrics_row(result)

            if result.is_error:
                failure_count += 1
                self._log_retry(
                    "api_error", failure_count, RuntimeError(result.error_message),
                )
                if self._exhausted(failure_count):
                    raise RuntimeError(
                        f"SDK returned error after {failure_count} attempt(s): "
                        f"{result.error_message}"
                    )
                time.sleep(_backoff_for(failure_count))
                prompt = self._maybe_resume_hint(prompt, original_prompt, "api_error")
                continue

            return result.text

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _exhausted(self, failure_count: int) -> bool:
        return self.max_retries is not None and failure_count > self.max_retries

    def _log_retry(self, kind: str, attempt: int, exc: BaseException) -> None:
        log_retry_event(self._metrics_path, {
            "role": self._current_role,
            "phase": self._current_phase,
            "failure_type": kind,
            "attempt": attempt,
            "error": str(exc)[:500],
        })

    def _log_metrics_row(self, result: SDKResult) -> None:
        log_metrics(self._metrics_path, {
            "dispatcher": "sdk",
            "role": self._current_role,
            "phase": self._current_phase,
            "model": self.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cache_creation_input_tokens": result.cache_creation_input_tokens,
            "cache_read_input_tokens": result.cache_read_input_tokens,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "num_turns": result.num_turns,
        })

    @staticmethod
    def _maybe_resume_hint(prompt: str, original_prompt: str, kind: str) -> str:
        """If the prompt has not yet been annotated with a resume hint, add one.

        Mirrors CLIDispatcher: tells the agent that the prior attempt was
        interrupted so it picks up from existing artifacts rather than
        starting fresh.
        """
        marker = "\nNote: Your previous attempt was interrupted"
        if marker in prompt:
            return prompt
        return (
            f"{original_prompt}\n\n---\n"
            f"Note: Your previous attempt was interrupted ({kind}). "
            f"Check the working directory for artifacts from your prior "
            f"attempt and continue from where you left off."
        )
