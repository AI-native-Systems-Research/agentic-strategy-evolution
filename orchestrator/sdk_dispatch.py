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

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol, runtime_checkable

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


def build_error_message(message, *, message_class_counts: dict | None = None) -> str:
    """Construct a useful error_message from an SDK ResultMessage with is_error=True.

    #216: when ``message.result`` is missing, ``None``, or empty string,
    the dispatcher would otherwise log ``error: "None"`` to retry_log
    — useless for diagnosing what broke. This helper falls back to
    a structured summary built from whatever attributes ARE available
    (``stop_reason``, ``num_turns``, ``subtype``, message-class counts
    seen during the turn).

    Pure Python — testable without ``claude_agent_sdk``. Tests construct
    a duck-typed object with the fields they want to exercise.
    """
    raw = getattr(message, "result", None)
    if isinstance(raw, str) and raw.strip() and raw.strip().lower() != "none":
        return raw

    fields: list[str] = []
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason:
        fields.append(f"stop_reason={stop_reason}")
    subtype = getattr(message, "subtype", None)
    if subtype:
        fields.append(f"subtype={subtype}")
    num_turns = getattr(message, "num_turns", None)
    if isinstance(num_turns, int) and num_turns > 0:
        fields.append(f"num_turns={num_turns}")
    duration_ms = getattr(message, "duration_ms", None)
    if isinstance(duration_ms, int) and duration_ms > 0:
        fields.append(f"duration_ms={duration_ms}")
    if message_class_counts:
        seen = ",".join(
            f"{k}={v}" for k, v in sorted(message_class_counts.items()) if v
        )
        if seen:
            fields.append(f"messages_seen={seen}")

    if fields:
        return (
            "SDK reported is_error=True with no result text; "
            "captured context: " + " ".join(fields)
        )
    return (
        "SDK reported is_error=True with no result text and no diagnostic "
        "context (no stop_reason, subtype, num_turns, or message stream). "
        "See executor_log.jsonl for the SDK message types observed in this turn."
    )


async def aiter_with_silence_watchdog(aiter, threshold: float | None):
    """Yield messages from ``aiter``, raising SDKTransientError on silence.

    Per-message live watchdog (#205): when ``threshold`` is positive,
    each ``__anext__`` is wrapped in ``anyio.fail_after``. If no message
    arrives within ``threshold`` seconds, raise
    :class:`SDKTransientError` so the existing retry machinery can
    recover instead of blocking indefinitely.

    ``threshold=None`` or ``<= 0`` disables the watchdog (yields the
    underlying iterator transparently).

    Resource hygiene: when raising on timeout (or any other exception),
    we explicitly call ``aiter.aclose()`` if it's an async generator,
    so the underlying SDK stream's tasks/sockets get released instead
    of being orphaned for GC. A test asserts this contract.

    Pulled out as a standalone async helper so it's testable without
    ``claude_agent_sdk`` (which the test guard hard-fails). Tests inject
    a tiny async iterator that controls when (or whether) values arrive.
    """
    import anyio  # local import — keep top-level import-time clean
    wd = float(threshold) if threshold and threshold > 0 else None
    try:
        while True:
            try:
                if wd is not None:
                    with anyio.fail_after(wd):
                        message = await aiter.__anext__()
                else:
                    message = await aiter.__anext__()
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                raise SDKTransientError(
                    f"SDK turn observed >{wd:.0f}s silence between events; "
                    f"aborting turn so the dispatcher can retry."
                ) from exc
            yield message
    finally:
        # Release the underlying SDK stream's resources. Only async
        # generators have ``aclose``; plain async iterators don't, so
        # guard with ``hasattr``. Best-effort: if aclose itself raises,
        # we don't mask the original exception we're already unwinding.
        #
        # #257 (F12): wrap in a short timeout so we don't deadlock when
        # the consumer was mid-iteration on abort (the
        # ``RuntimeError: aclose(): asynchronous generator is already
        # running`` race), and explicitly catch the documented exception
        # set so the asyncio default "loud cleanup error" doesn't
        # spam the abort report's stderr.
        aclose = getattr(aiter, "aclose", None)
        if callable(aclose):
            try:
                coro = aclose()
                if hasattr(coro, "__await__"):
                    await asyncio.wait_for(coro, timeout=5.0)  # type: ignore[arg-type]
            except (asyncio.TimeoutError, asyncio.CancelledError, RuntimeError, GeneratorExit):
                pass  # already running / racing — let the loop tear down naturally
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass


def summarize_silence_gaps(event_log_path: Path) -> dict:
    """Walk an executor_log.jsonl and report the longest silence gap (#201).

    Returns ``{"max_gap_seconds": float, "event_count": int}`` — both 0
    when the log doesn't exist, has fewer than 2 events, or can't be
    parsed. The max-gap is the largest delta between consecutive event
    timestamps, in seconds. Useful for post-turn diagnostics: a multi-
    minute gap between events typically signals a hung tool call (BLIS
    subprocess, long-running build, polling-loop on a stuck signal).
    """
    if not event_log_path.exists():
        return {"max_gap_seconds": 0.0, "event_count": 0}
    try:
        lines = event_log_path.read_text().splitlines()
    except OSError:
        return {"max_gap_seconds": 0.0, "event_count": 0}
    import json as _json
    timestamps: list[float] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = _json.loads(line)
        except (ValueError, TypeError):
            continue
        ts = rec.get("ts")
        if isinstance(ts, (int, float)):
            timestamps.append(float(ts))
    if len(timestamps) < 2:
        return {"max_gap_seconds": 0.0, "event_count": len(timestamps)}
    max_gap = 0.0
    for prev, cur in zip(timestamps, timestamps[1:]):
        gap = cur - prev
        if gap > max_gap:
            max_gap = gap
    return {
        "max_gap_seconds": max_gap,
        "event_count": len(timestamps),
    }


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
    # #195: AssistantMessage.tool_name is empty; the actual tool name lives
    # on ToolUseBlock instances inside `content` (a list of TextBlock /
    # ThinkingBlock / ToolUseBlock objects). Walk the list and surface the
    # last tool name so `nous status` can render `last=Bash` etc.
    if "tool_name" not in record:
        content = getattr(message, "content", None)
        if isinstance(content, (list, tuple)):
            for block in reversed(content):
                name = getattr(block, "name", None)
                if name and not callable(name):
                    try:
                        _json.dumps(name)
                        record["tool_name"] = name
                        break
                    except (TypeError, ValueError):
                        pass
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

    Invariant: ``is_error=True`` requires a non-empty ``error_message``.
    Locked in ``__post_init__`` so producers (real or fake) can't ship
    an unactionable error path the way the friction-test rerun did
    (retry_log row recorded ``error: "None"``). ``build_error_message``
    is the canonical producer when SDK reports is_error with empty
    result text.
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

    def __post_init__(self) -> None:
        if self.is_error and not self.error_message.strip():
            raise ValueError(
                "SDKResult(is_error=True) requires a non-empty "
                "error_message — see build_error_message() for the "
                "canonical producer when the SDK returns is_error with "
                "no result text."
            )


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
        permission_mode: Literal["bypassPermissions"] | None = None,
        turn_silence_threshold: float | None = None,
    ) -> SDKResult:
        """One SDK turn.

        ``permission_mode``: ``"bypassPermissions"`` disables the Claude
        Code SDK's filesystem sandbox (the default for nous campaigns;
        see #193). ``None`` means: don't pass the flag — let the SDK
        apply its own default permission gating. The dispatcher
        translates ``campaign.sandbox`` to one of these two values.

        ``turn_silence_threshold``: per-message live watchdog (#205).
        If more than ``turn_silence_threshold`` seconds elapse between
        SDK events while the agent is mid-turn, raise
        :class:`SDKTransientError` so the existing retry machinery can
        recover the campaign instead of blocking indefinitely. ``None``
        or ``<= 0`` disables the watchdog. Different from
        ``campaign.sdk_timeouts.silence_threshold_seconds`` (which is
        post-mortem; this one is live).
        """
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
        permission_mode: Literal["bypassPermissions"] | None = "bypassPermissions",
        turn_silence_threshold: float | None = None,
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
                "Install with `pip install claude-agent-sdk` (or reinstall "
                "nous, which now lists it as a required dependency — see #183)."
            ) from exc

        async def _run() -> SDKResult:
            # #193: ``permission_mode`` controls the Claude Code SDK
            # filesystem sandbox. Default is "bypassPermissions" because
            # nous campaigns routinely need writes outside cwd (the
            # orchestrator launches with cwd=worktree but BLIS / build /
            # test subprocess outputs land at <main-repo>/.nous/<run>/
            # runs/iter-N/results/, which the default sandbox rejects).
            # Operators can opt out via campaign.sandbox="default" or
            # `nous run --sandbox default` if they want the SDK's default
            # permission gating.
            if permission_mode:
                options = ClaudeAgentOptions(
                    model=model,
                    cwd=str(cwd) if cwd else None,
                    max_turns=max_turns,
                    system_prompt=system_prompt,
                    settings=str(settings_path) if settings_path else None,
                    permission_mode=permission_mode,  # type: ignore[arg-type]
                )
            else:
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
            # #216: track message-class counts so a downstream is_error
            # path can synthesize a useful diagnostic when result text is
            # missing (instead of recording the literal string "None").
            message_class_counts: dict[str, int] = {}
            if event_log_path is not None:
                Path(event_log_path).parent.mkdir(parents=True, exist_ok=True)
            # #205: per-message live watchdog. When a positive
            # ``turn_silence_threshold`` is set, ``aiter_with_silence_watchdog``
            # wraps each ``__anext__`` in ``anyio.fail_after`` so a
            # model-side hang surfaces as ``SDKTransientError``. The
            # existing transient-retry machinery (lines below) catches
            # it and retries instead of blocking the campaign forever.
            aiter = query(prompt=prompt, options=options).__aiter__()
            # #250 (F5): event-boundary STOP. Resolve the work_dir once
            # per-turn from the event_log_path (which lives at
            # ``<work_dir>/runs/iter-N/inputs/executor_log.jsonl``) so
            # the loop can check for STOP_IMMEDIATE at each message
            # boundary without re-walking the filesystem every event.
            stop_immediate_path: Path | None = None
            if event_log_path is not None:
                # walk up to work_dir: inputs/.. = iter-N; iter-N/.. = runs; runs/.. = work_dir
                try:
                    stop_immediate_path = (
                        Path(event_log_path).parent.parent.parent.parent / "STOP_IMMEDIATE"
                    )
                except (IndexError, ValueError):
                    stop_immediate_path = None
            async for message in aiter_with_silence_watchdog(
                aiter, turn_silence_threshold,
            ):
                if stop_immediate_path is not None and stop_immediate_path.exists():
                    raise SDKTransientError(
                        "STOP_IMMEDIATE sentinel detected; aborting SDK turn "
                        "at event boundary (#250 / F5)."
                    )
                cls = type(message).__name__
                message_class_counts[cls] = message_class_counts.get(cls, 0) + 1
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
                            # #216: build a diagnostic-rich error_message
                            # so retry_log rows aren't literally "None".
                            error_message=build_error_message(
                                message,
                                message_class_counts=message_class_counts,
                            ),
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
        sandbox: str | None = None,
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
        # #193: resolve sandbox mode. Order: explicit kwarg > campaign.sandbox
        # > "bypass" default (which maps to permission_mode="bypassPermissions").
        # Pass "default" to keep the SDK's default permission gating.
        resolved = sandbox if sandbox is not None else campaign.get("sandbox", "bypass")
        if resolved not in ("bypass", "default"):
            raise ValueError(
                f"campaign.sandbox must be 'bypass' or 'default', got {resolved!r}"
            )
        self._permission_mode: Literal["bypassPermissions"] | None = (
            "bypassPermissions" if resolved == "bypass" else None
        )
        # #201: silence threshold (seconds) for post-turn diagnostics.
        # Default 600s; opt out by setting to 0. Configured per-campaign
        # via campaign.sdk_timeouts.silence_threshold_seconds.
        timeouts = campaign.get("sdk_timeouts") or {}
        raw_threshold = timeouts.get("silence_threshold_seconds", 600)
        try:
            self._silence_threshold = float(raw_threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"campaign.sdk_timeouts.silence_threshold_seconds must be "
                f"a non-negative number, got {raw_threshold!r}"
            ) from exc
        # Defensive Python-side validation. The schema enforces
        # ``minimum: 0`` but ad-hoc dict callers (programmatic entry
        # points, tests) bypass schema validation; mirror the
        # ``sandbox`` enum check for consistency.
        if self._silence_threshold < 0:
            raise ValueError(
                f"campaign.sdk_timeouts.silence_threshold_seconds must be "
                f">= 0, got {self._silence_threshold}"
            )
        # #205: live mid-turn watchdog. Defaults to the post-mortem
        # threshold (so by default the live watchdog catches what the
        # post-mortem would otherwise only diagnose after the fact).
        # Operators can split the two by setting
        # ``campaign.sdk_timeouts.turn_silence_threshold_seconds`` to a
        # different value, or to 0 to disable the live watchdog while
        # keeping the post-mortem analyzer.
        raw_turn_threshold = timeouts.get(
            "turn_silence_threshold_seconds",
            self._silence_threshold,
        )
        # #264 (F19): scalar (legacy) OR per-phase map. Per-phase
        # defaults — DESIGN's heavy reasoning between tool calls
        # earns 600s; EXECUTE_ANALYZE's frequent simulator calls
        # earns 120s; REPORT sits in between at 240s. These match
        # the friction-report's recommended values.
        self._phase_silence_thresholds: dict[str, float] = {
            "design": 600.0,
            "execute_analyze": 120.0,
            "report": 240.0,
        }
        if isinstance(raw_turn_threshold, dict):
            for phase_key in ("design", "execute_analyze", "report"):
                if phase_key in raw_turn_threshold:
                    try:
                        v = float(raw_turn_threshold[phase_key])
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"campaign.sdk_timeouts.turn_silence_threshold_seconds.{phase_key} "
                            f"must be a non-negative number, got "
                            f"{raw_turn_threshold[phase_key]!r}"
                        ) from exc
                    if v < 0:
                        raise ValueError(
                            f"campaign.sdk_timeouts.turn_silence_threshold_seconds.{phase_key} "
                            f"must be >= 0, got {v}"
                        )
                    self._phase_silence_thresholds[phase_key] = v
            # Legacy scalar attribute: use the largest phase value as
            # the "global default" the rest of the dispatcher reads.
            # In practice every code path now goes through
            # _resolve_turn_silence_threshold(phase), so this is
            # transitional plumbing that backward-compat callers
            # (older tests) can still reach.
            self._turn_silence_threshold = max(
                self._phase_silence_thresholds.values()
            )
        else:
            try:
                self._turn_silence_threshold = float(raw_turn_threshold)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"campaign.sdk_timeouts.turn_silence_threshold_seconds must be "
                    f"a non-negative number or per-phase map, got {raw_turn_threshold!r}"
                ) from exc
            if self._turn_silence_threshold < 0:
                raise ValueError(
                    f"campaign.sdk_timeouts.turn_silence_threshold_seconds must be "
                    f">= 0, got {self._turn_silence_threshold}"
                )
            # Scalar form applies to every phase (backward compat).
            self._phase_silence_thresholds = {
                k: self._turn_silence_threshold
                for k in self._phase_silence_thresholds
            }
        # #127 Phase B: event log path is recomputed per-dispatch (it depends
        # on the iteration), so we don't store it on the dispatcher.
        self._event_log_path: Path | None = None
        # #264 (F19): bundle-side per-iter silence threshold side-effect
        # state. Populated by ``_bundle_recommended_turn_silence_threshold``
        # at dispatch start; consumed by ``_resolve_turn_silence_threshold``.
        self._bundle_silence_phase_overrides: dict[str, float] = {}
        self._bundle_silence_scalar_override: float | None = None

    # ------------------------------------------------------------------
    # Per-iteration event log (#127 Phase B)
    # ------------------------------------------------------------------

    def _maybe_log_silence(self, iteration: int, phase: str) -> None:
        """#201: post-turn diagnostic — if the streaming log shows a gap
        between events larger than the configured threshold, append a
        ``failure_type: "sdk_silence"`` entry to retry_log.jsonl. Purely
        observational; doesn't interrupt or fail the turn.

        ``campaign.sdk_timeouts.silence_threshold_seconds == 0`` (or
        unset and ``< 0`` after Python-side validation) disables the
        diagnostic entirely.
        """
        if self._silence_threshold <= 0 or self._event_log_path is None:
            return
        summary = summarize_silence_gaps(self._event_log_path)
        if summary["max_gap_seconds"] > self._silence_threshold:
            log_retry_event(self._metrics_path, {
                "iteration": iteration,
                "phase": phase,
                "failure_type": "sdk_silence",
                "max_gap_seconds": round(summary["max_gap_seconds"], 1),
                "threshold_seconds": self._silence_threshold,
                "event_count": summary["event_count"],
            })
            logger.warning(
                "SDK turn observed a %.1fs silence gap (threshold=%.0fs); "
                "see retry_log.jsonl for details.",
                summary["max_gap_seconds"], self._silence_threshold,
            )

    def _resolve_turn_silence_threshold(self, phase: str) -> float:
        """#264 (F19): the live watchdog threshold for THIS phase.

        Resolution chain (highest priority first):
          1. Bundle-side per-phase override (rehearsal-recorded).
          2. Bundle-side scalar override (rehearsal-recorded, legacy).
          3. Campaign-side per-phase value (set in __init__).
          4. Phase default (design=600, execute_analyze=120, report=240).
        Returns 0 only if every layer evaluated to 0 (operator opted out).
        """
        bundle_per_phase = self._bundle_silence_phase_overrides
        if bundle_per_phase and phase in bundle_per_phase:
            return bundle_per_phase[phase]
        bundle_scalar = self._bundle_silence_scalar_override
        if bundle_scalar is not None:
            return bundle_scalar
        return self._phase_silence_thresholds.get(phase, self._turn_silence_threshold)

    def _bundle_recommended_turn_silence_threshold(
            self, iteration: int) -> float | None:
        """Read the rehearsal-recorded watchdog threshold override from the
        prior iter's bundle.experiment_spec.timing_observations.

        Returns ``None`` for: iter-1 (no prior bundle), missing bundle file,
        unparseable YAML, or absent/malformed
        ``recommended_turn_silence_threshold_seconds``. On parse failures
        (corrupt YAML, missing PyYAML), logs a warning so operators see
        why the override didn't apply — silently falling back to the
        campaign default would be the silent-failure pattern PR #218
        was specifically meant to kill.

        Side effect: also populates
        ``self._bundle_silence_phase_overrides`` (for the per-phase map
        form, #264/F19). Callers that want phase-aware resolution
        should use ``_resolve_turn_silence_threshold(phase)`` instead
        of this scalar return value.
        """
        # Reset side-effect state.
        self._bundle_silence_phase_overrides = {}
        self._bundle_silence_scalar_override: float | None = None
        if iteration < 2:
            return None
        prior_iter_dir = self.work_dir / "runs" / f"iter-{iteration - 1}"
        bundle_path = prior_iter_dir / "bundle.yaml"
        if not bundle_path.exists():
            return None
        # Import yaml outside the try/except: an ImportError here is
        # an environmental defect that should propagate, not a
        # silent fallback to the campaign default.
        import yaml as _yaml
        try:
            text = bundle_path.read_text()
            data = _yaml.safe_load(text)
        except OSError as exc:
            logger.warning(
                "iter-%d bundle unreadable; skipping timing-override "
                "(%s: %s)",
                iteration - 1, type(exc).__name__, exc,
            )
            return None
        except _yaml.YAMLError as exc:
            logger.warning(
                "iter-%d bundle YAML invalid; skipping timing-override "
                "(falling back to campaign default %.0fs): %s",
                iteration - 1, self._turn_silence_threshold, exc,
            )
            return None
        if not isinstance(data, dict):
            return None
        spec = data.get("experiment_spec") or {}
        if not isinstance(spec, dict):
            return None
        timing = spec.get("timing_observations") or {}
        if not isinstance(timing, dict):
            return None
        val = timing.get("recommended_turn_silence_threshold_seconds")
        # #264 (F19): per-phase map form. Populate the side-effect dict
        # so _resolve_turn_silence_threshold() can use it.
        if isinstance(val, dict):
            for phase_key in ("design", "execute_analyze", "report"):
                if phase_key in val:
                    try:
                        v = float(val[phase_key])
                    except (TypeError, ValueError):
                        continue
                    if v < 0:
                        continue
                    self._bundle_silence_phase_overrides[phase_key] = v
            # Legacy callers that use the scalar return value get the
            # max — preserves "iter-2 watchdog at least catches what the
            # rehearsal saw" semantics.
            if self._bundle_silence_phase_overrides:
                return max(self._bundle_silence_phase_overrides.values())
            return None
        try:
            v = float(val) if val is not None else None
        except (TypeError, ValueError):
            return None
        if v is None or v < 0:
            return None
        self._bundle_silence_scalar_override = v
        return v

    def dispatch(  # type: ignore[override]
        self, role: str, phase: str, *, output_path, iteration: int,
        perspective=None, h_main_result="CONFIRMED",
    ) -> None:
        # Compute the executor_log.jsonl path for this iteration so the
        # runner tees SDK events to a place the status reader can find.
        # #190: live under inputs/ so the design-phase validator's iter-root
        # whitelist (problem.md, bundle.yaml, handoff_snapshot.md, design_log.md)
        # is preserved. The streaming log is dispatcher telemetry, not a
        # design artifact, and inputs/ is where non-artifact context lives.
        inputs_dir = self.work_dir / "runs" / f"iter-{iteration}" / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        self._event_log_path = inputs_dir / "executor_log.jsonl"
        # #226: per-iter watchdog threshold override. Resolution chain:
        # bundle.experiment_spec.timing_observations.recommended_turn_silence_threshold_seconds
        # > campaign.sdk_timeouts.turn_silence_threshold_seconds (set in
        # __init__) > 600s default. Resolve here so the runner sees the
        # right value for THIS iter; reset after to avoid leaking state
        # to subsequent dispatches in long-running campaigns.
        original_threshold = self._turn_silence_threshold
        # Calling this populates the per-phase override side-effect dict
        # used by _resolve_turn_silence_threshold().
        self._bundle_recommended_turn_silence_threshold(iteration)
        # #264 (F19): resolve phase-aware threshold for THIS phase.
        # Mapping is loose — phase strings vary across the codebase
        # ("design"/"execute_analyze"/"report" are the canonical
        # buckets; phases like "summarize-gate" fall back to the
        # nearest match or the legacy global).
        phase_key = self._normalize_phase(phase)
        resolved = self._resolve_turn_silence_threshold(phase_key)
        self._turn_silence_threshold = resolved
        try:
            super().dispatch(
                role, phase,
                output_path=output_path, iteration=iteration,
                perspective=perspective, h_main_result=h_main_result,
            )
        finally:
            self._turn_silence_threshold = original_threshold
            # #201: post-turn silence diagnostic. Read the streaming log
            # we just produced and surface excessive event gaps to
            # retry_log.jsonl. Best-effort — never raise from the finally.
            try:
                self._maybe_log_silence(iteration=iteration, phase=phase)
            except Exception as exc:  # noqa: BLE001 — never break the turn
                # warning, not debug: if the diagnostic crashes every
                # turn, debug-only logs would never surface that.
                logger.warning("silence diagnostic skipped: %s", exc)
            self._event_log_path = None

    # ------------------------------------------------------------------
    # Pre-flight
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_phase(phase: str) -> str:
        """#264 (F19): map dispatcher phase strings to the per-phase
        threshold keys (design/execute_analyze/report).

        Phases the codebase emits include ``design``, ``execute-analyze``,
        ``execute_analyze``, ``summarize-gate`` (LLM-only summarizer,
        not a code phase), ``critique``, etc. We normalize the
        canonical three and fall back to ``execute_analyze`` for
        anything code-flavored.
        """
        if phase in ("design",):
            return "design"
        if phase in ("execute-analyze", "execute_analyze"):
            return "execute_analyze"
        if phase in ("report", "summarize-gate", "summarize_gate"):
            return "report"
        return "execute_analyze"

    def preflight_check(self) -> None:
        """Verify the SDK is reachable before starting a campaign."""
        try:
            import claude_agent_sdk  # type: ignore[import-not-found] # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Pre-flight check failed: claude-agent-sdk is not installed. "
                "Install with `pip install claude-agent-sdk` (or reinstall "
                "nous, which now lists it as a required dependency — see #183)."
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
                    permission_mode=self._permission_mode,
                    turn_silence_threshold=self._turn_silence_threshold,
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
