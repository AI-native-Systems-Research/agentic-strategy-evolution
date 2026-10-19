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
import contextlib
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol, runtime_checkable

from orchestrator.cli_dispatch import CLIDispatcher, _backoff_for
from orchestrator.metrics import log_metrics, log_retry_event, usage_cost

logger = logging.getLogger(__name__)

# #279 review: absolute backstop for "unbounded" retry mode
# (max_retries=None, opt-in via --max-cli-retries -1). Without a cap, a
# permanently-erroring API response (model misconfiguration, billing
# issue) would loop forever at the max backoff. 1000 attempts at the
# capped backoff is roughly a week of wall-clock — unmistakably a stuck
# system, not a transient blip — while preserving the intent of letting
# unattended campaigns ride out long provider outages.
_UNBOUNDED_RETRY_SAFETY_CAP = 1000


# A capped session with less than this left is not retried (nothing useful fits in it).
_MIN_ATTEMPT_USD = 0.01
_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _usage_of(result: "SDKResult") -> dict:
    return {k: getattr(result, k, 0) for k in _USAGE_KEYS}


class SDKTransientError(RuntimeError):
    """Runner raises this for retryable transport-level failures.

    ``usage``: token counts the aborted turn had already streamed (SDK usage keys), so a dollar-capped
    session can charge them to its cap. Empty when unknown.
    """

    usage: dict = {}


class SDKHangError(RuntimeError):
    """A session sent no assistant reply for too long while only API errors arrived (v8 hang watchdog).

    Not retried by the dispatcher: the caller restarts the work from its last saved state in a fresh
    session. ``usage``: what the killed session had spent (transcript); ``session_id``: the hung session.
    """

    usage: dict = {}
    session_id: str | None = None


# ─── v8: session cost and liveness from the Claude Code transcript ────────────────────────────

_TRANSCRIPT_POLL_S = 10.0
HANG_MIN_API_ERRORS = 3  # v7 had 17- and 58-minute gaps behind one or two timeouts that still ended in a reply


def project_key(cwd) -> str:
    """Claude Code's project directory name for ``cwd`` (every non-alphanumeric character becomes ``-``)."""
    import re as _re
    return _re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(cwd)))


def default_transcript_paths(cwd, session_ids, config_dir=None) -> list[Path]:
    """Transcript files of ``session_ids`` (with their subagent files) under ``<config>/projects``.

    Tries the exact project directory for ``cwd`` first: a sandbox may allow reading it but not
    listing ``projects/``. Then globs project directories that start with that name, then all of
    them (Claude Code shortens very long project names, and session ids are unique).
    """
    import glob as _glob
    import re as _re
    root = Path(config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    keys = list(dict.fromkeys([project_key(cwd), _re.sub(r"[^A-Za-z0-9]", "-", str(cwd))])) if cwd else []
    out: list[Path] = []
    for sid in sorted(s for s in session_ids if s):
        found: list[Path] = []
        for key in keys:
            main, sub = root / key / f"{sid}.jsonl", root / key / sid
            if main.is_file():
                found.append(main)
            if sub.is_dir():
                found += [Path(f) for f in _glob.glob(str(sub / "**" / "*.jsonl"), recursive=True)]
            if found:
                break
        sid_g = _glob.escape(sid)
        for proj in ([_glob.escape(k) + "*" for k in keys] + ["*"]) if not found else []:
            found = [Path(f) for f in (_glob.glob(str(root / proj / f"{sid_g}.jsonl"))
                                       + _glob.glob(str(root / proj / sid_g / "**" / "*.jsonl"), recursive=True))]
            if found:
                break
        out += found
    return out


def _iso_ts(value) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class TranscriptMeter:
    """Incremental reader of a session's transcript files: true usage per reply, and liveness.

    One reply is written as several lines repeating its usage, so each message id counts once, with
    its largest usage (same rule as ``gen/cost_meter.py``). Lines older than ``since`` (copied history
    of a resumed session) are ignored. Thread-safe.
    """

    def __init__(self, locator, cwd, since: float, rates: dict | None = None):
        self._locator, self._cwd, self._since = locator, cwd, float(since)
        self._rates = rates
        self._offsets: dict[str, int] = {}
        self._per_msg: dict[str, dict] = {}
        self.session_ids: set[str] = set()
        self.last_assistant_ts: float | None = None
        self.last_api_error_ts: float | None = None
        self.api_errors_since_reply = 0
        self._truncated: set[str] = set()  # ids of replies that stopped at the output-token limit
        self.cut_reasoning: list[str] = []  # thinking text of each cut reply, in order
        self._lock = threading.Lock()
        self._paths: list = []
        self._located: tuple[frozenset, float] | None = None

    _RELOCATE_S = 5.0  # known files are read on every poll; new ones (subagents) are looked for this often

    def skip_existing(self) -> None:
        """Start reading every transcript the session already has at its current end (resumed sessions):
        replies written before the resume are never counted again, however close their timestamps."""
        with self._lock:
            for path in self._locate():
                try:
                    self._offsets[str(path)] = Path(path).stat().st_size
                except OSError:
                    pass

    def _locate(self) -> list:
        ids = frozenset(self.session_ids)
        last = self._located
        if self._paths and last is not None and last[0] == ids and time.time() - last[1] < self._RELOCATE_S:
            return self._paths
        try:
            found = list(self._locator(self._cwd, set(ids)))
        except Exception as exc:  # noqa: BLE001 - a locator failure must not stop the session
            logger.debug("transcript locator failed: %s", exc)
            return self._paths
        self._paths = list(dict.fromkeys([*self._paths, *found]))
        self._located = (ids, time.time())
        return self._paths

    def poll(self) -> None:
        import json as _json
        with self._lock:
            for path in self._locate():
                key = str(path)
                try:
                    with open(path, "rb") as f:
                        f.seek(self._offsets.get(key, 0))
                        chunk = f.read()
                except OSError:
                    continue
                end = chunk.rfind(b"\n")
                if end < 0:
                    continue
                self._offsets[key] = self._offsets.get(key, 0) + end + 1
                for raw in chunk[:end].splitlines():
                    try:
                        d = _json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(d, dict):
                        self._take(d, key)

    def _take(self, d: dict, path: str) -> None:
        ts = _iso_ts(d.get("timestamp"))
        if ts is not None and ts < self._since - 1.0:
            return
        now = ts if ts is not None else time.time()
        kind = d.get("type")
        if kind == "system" and (d.get("subtype") == "api_error" or d.get("level") == "error"):
            self.last_api_error_ts = max(self.last_api_error_ts or 0.0, now)
            self.api_errors_since_reply += 1
        msg = d.get("message") if isinstance(d.get("message"), dict) else None
        if kind == "assistant":
            self.last_assistant_ts = max(self.last_assistant_ts or 0.0, now)
            self.api_errors_since_reply = 0
            if msg and msg.get("stop_reason") == "max_tokens":
                rid = str(msg.get("id") or d.get("uuid"))
                if rid not in self._truncated:
                    self._truncated.add(rid)
                    self.cut_reasoning.append("")
                blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
                text = "\n".join(str(b.get("thinking") or b.get("text") or "") for b in blocks
                                 if isinstance(b, dict) and b.get("type") in ("thinking", "text"))
                if len(text) > len(self.cut_reasoning[-1]):
                    self.cut_reasoning[-1] = text
        usage = msg.get("usage") if msg else None
        if not isinstance(usage, dict):
            return
        mid = msg.get("id") or f"{path}:{d.get('uuid')}"
        prev = self._per_msg.get(mid)
        if prev is None or usage_cost(usage, self._rates) > usage_cost(prev, self._rates):
            self._per_msg[mid] = usage

    def totals(self) -> dict:
        with self._lock:
            return {k: sum(int(u.get(k, 0) or 0) for u in self._per_msg.values()) for k in _USAGE_KEYS}

    def cost(self) -> float:
        return usage_cost(self.totals(), self._rates)

    @property
    def output_limit_hits(self) -> int:
        with self._lock:
            return len(self._truncated)

    def max_reply_cost(self) -> float:
        with self._lock:
            return max((usage_cost(u, self._rates) for u in self._per_msg.values()), default=0.0)


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


CUT_RESUME_USD = 2.0  # allowance for the one resume after a cap that tripped on a cut reply


def _is_output_limit(result) -> bool:
    """True when the CLI ended because a reply exceeded its output-token maximum."""
    text = f"{getattr(result, 'error_message', '') or ''} {getattr(result, 'text', '') or ''}"
    return "max_output_tokens" in text or "output token maximum" in text


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
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                # An unexpected exception here (SDK teardown bug, version
                # mismatch raising AttributeError, etc.) must not mask the
                # exception we may already be unwinding — but for a system
                # that runs unsupervised for hours, swallowing it silently
                # makes post-mortem impossible. Log at debug so it's
                # recoverable without adding noise to the abort report.
                logger.debug("aiter cleanup raised (non-fatal): %s", exc)


# Seconds a stopped claude CLI process tree gets between SIGTERM and SIGKILL.
_CLI_KILL_GRACE_S = 3.0


def _ps_table() -> dict[int, tuple[int, str]] | None:
    """``{pid: (ppid, stat)}`` for every process (POSIX ``ps``), or None when ``ps`` is unavailable."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,stat="], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    table: dict[int, tuple[int, str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    return table


def _live_tree(roots: list[int], table: dict[int, tuple[int, str]] | None) -> list[int]:
    """``roots`` plus their descendants, minus processes that already exited (zombies count as exited)."""
    if table is None:
        alive = []
        for pid in roots:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
            except PermissionError:
                alive.append(pid)
        return alive
    children: dict[int, list[int]] = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    seen: list[int] = []
    todo = list(roots)
    while todo:
        pid = todo.pop()
        if pid in seen or pid not in table:
            continue
        seen.append(pid)
        todo.extend(children.get(pid, []))
    return [p for p in seen if not table[p][1].startswith("Z")]


def kill_process_tree(root: int, grace_s: float = _CLI_KILL_GRACE_S) -> None:
    """SIGTERM ``root`` and every descendant, then SIGKILL whatever is left after ``grace_s``.

    Descendants are found before any signal is sent, while they are still attached to ``root``.
    Synchronous on purpose: it must finish even while the event loop is being cancelled.
    """
    tree = _live_tree([root], _ps_table())
    if not tree:
        return
    for pid in tree:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.time() + grace_s
    while True:
        tree = _live_tree(tree, _ps_table())  # survivors plus anything they spawned meanwhile
        if not tree or time.time() >= deadline:
            break
        time.sleep(0.1)
    for pid in tree:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    if tree:
        logger.warning("claude CLI process tree ignored SIGTERM; killed %s", tree)


def _cli_transport(sdk, prompt, options):
    """A SubprocessCLITransport we hold a handle on, or None when this SDK cannot take one.

    Passing our own transport to ``query()`` lets the runner kill the CLI it spawned. ``query()`` alone
    cannot: closing it does not close the SDK's inner generator (PEP 533), so on an early stop the CLI
    keeps working, and spending, until garbage collection. Nous never sets ``can_use_tool`` or a
    ``session_store``, the only options ``query()`` applies to its own transport and not to ours.
    """
    import inspect
    cls = getattr(sdk, "SubprocessCLITransport", None)
    if cls is None:
        try:
            from claude_agent_sdk._internal.transport.subprocess_cli import (  # type: ignore[import-not-found]
                SubprocessCLITransport as cls,
            )
        except ImportError:
            return None
    try:
        if "transport" not in inspect.signature(sdk.query).parameters:
            return None
    except (TypeError, ValueError):
        return None
    return cls(prompt=prompt, options=options)


async def _stop_cli(transport, exit_wait_s: float = 0.0) -> None:
    """Make sure the CLI behind ``transport`` and its children are gone (no-op once the SDK closed it).

    ``exit_wait_s``: after a final result the CLI is still flushing its session transcript (which the
    cost ruler and session resume read), so let it exit on its own for that long before killing it.
    """
    proc = getattr(transport, "_process", None)
    pid = getattr(proc, "pid", None)
    if pid is None or getattr(proc, "returncode", None) is not None:
        return
    deadline = time.time() + exit_wait_s
    while time.time() < deadline and _live_tree([pid], _ps_table()):
        await asyncio.sleep(0.2)
    kill_process_tree(pid)
    # The SDK's own close (run when its generator is finalized) now finds the process dead and only
    # tidies up; calling transport.close() here as well would race it.


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
    # #279 review (early-termination observability): capture the
    # ResultMessage diagnostic fields. When a session ends unexpectedly
    # (e.g. the model emits end_turn after context disruption with
    # artifacts unwritten), executor_log.jsonl will now show stop_reason
    # and num_turns directly, instead of forcing forensic analysis.
    if cls_name == "ResultMessage":
        for field_name in (
            "stop_reason", "num_turns", "is_error", "subtype", "duration_ms",
        ):
            val = getattr(message, field_name, None)
            if val is not None and not callable(val):
                try:
                    _json.dumps(val)
                    record[field_name] = val
                except (TypeError, ValueError):
                    record[field_name] = repr(val)[:200]
    try:
        with open(event_log_path, "a") as f:
            f.write(_json.dumps(record) + "\n")
    except OSError as exc:
        # The event log is the only observability channel for multi-hour
        # SDK turns, and ``nous status``' stuck-detector reads timestamps
        # from it — so a silent failure here makes a healthy agent look
        # hung. Still best-effort (a log-write error must not break the
        # turn), but warn once so the operator knows visibility is lost.
        # Dedup guard keeps a persistent failure (disk full, NFS stale
        # handle) from spamming the log on every event.
        if not getattr(_tee_event, "_warned", False):
            logger.warning(
                "event log write failed (future writes silent): %s", exc
            )
            _tee_event._warned = True


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
    session_id: str | None = None
    subtype: str | None = None
    # Token-ruler cost of the last model reply (measured only for dollar-capped sessions); sizes wrap-ups.
    last_turn_cost_usd: float = 0.0
    # Token-ruler cost of the session's most expensive single reply (v8, from its transcript).
    max_reply_usd: float = 0.0
    # v8: replies in this session that stopped at the output-token limit (from its transcript).
    output_limit_hits: int = 0
    # v8: thinking text of the session's last cut reply (empty when none or not readable).
    cut_reasoning: str = ""

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
        effort: str | None = None,
        resume: str | None = None,
        max_cost_usd: float | None = None,
        cost_rates: dict | None = None,
    ) -> SDKResult:
        """One SDK turn.

        ``max_cost_usd``: stop the session once its token-ruler cost (``cost_rates``, see
        ``orchestrator.metrics.usage_cost``) reaches this many dollars, returning ``is_error=True`` with
        ``subtype="error_max_budget_usd"`` and the session id so it can be resumed. Only passed when set.

        ``resume``: continue an earlier SDK session (by session id) instead of
        starting a fresh one. Only passed when the dispatcher resumes a turn.

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


def _default_sdk_runner_factory(transcript_locator: Callable | None = None,
                                poll_s: float | None = None) -> SDKRunner:
    """Return a runner that calls the real ``claude_agent_sdk``.

    Resolved lazily so that tests (and environments without the SDK
    installed) don't fail at import time.

    ``transcript_locator(cwd, session_ids) -> [paths]`` finds a session's Claude Code transcript files
    (default ``default_transcript_paths``); ``poll_s`` is how often a v8 session's transcript is read
    in the background. Both are seams for tests.
    """
    locate = transcript_locator or default_transcript_paths
    poll_every = _TRANSCRIPT_POLL_S if poll_s is None else float(poll_s)

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
        effort: str | None = None,
        resume: str | None = None,
        max_cost_usd: float | None = None,
        cost_rates: dict | None = None,
        transcript_caps: bool = False,
        hang_after_s: float | None = None,
        stop_on_output_limit: bool = False,
    ) -> SDKResult:
        try:
            import anyio
            import claude_agent_sdk as _sdk  # type: ignore[import-not-found]
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

        cli: dict = {}  # the transport whose CLI process _run must not leave running
        # v8: the transcript is the cost truth (the stream reports a few output tokens per reply), and
        # its system/api_error lines show a session stuck in gateway timeouts.
        meter = (TranscriptMeter(locate, cwd, since=time.time(), rates=cost_rates)
                 if transcript_caps or hang_after_s or stop_on_output_limit else None)
        if meter is not None and resume:
            meter.session_ids.add(resume)
            # Live p58 smoke s4: the cut reply ended 1 s before the resume and was charged twice.
            meter.skip_existing()
        live = {"reply": time.time(), "api_error": 0.0, "stream_usd": 0.0}
        stop: dict = {}  # {"why": "cap" | "hang"} once the watcher decided to end the session
        watcher_done = threading.Event()

        t_start = time.time()

        def _check() -> str | None:
            if meter is None:
                return None
            meter.poll()
            if (transcript_caps and not stop.get("warned_no_transcript") and live["stream_usd"] > 0
                    and time.time() - t_start > 90 and not meter._paths):
                stop["warned_no_transcript"] = True
                logger.warning("v8: no Claude Code transcript found for session(s) %s under cwd %s; the dollar "
                               "cap falls back to stream usage, which undercounts output tokens",
                               sorted(meter.session_ids), cwd)
            if transcript_caps and max_cost_usd is not None:
                if max(meter.cost(), live["stream_usd"]) >= max_cost_usd:
                    return "cap"
            if stop_on_output_limit and meter.output_limit_hits:
                # The CLI would retry at the same effort and redo the lost reasoning; stop so the
                # dispatcher can resume this session at a lower effort.
                return "output_limit"
            if hang_after_s:
                # A long legitimate reply can sit behind one or two timeouts and still arrive; only
                # repeated timeouts with no reply for the whole window count as a hang.
                last_reply = max(live["reply"], meter.last_assistant_ts or 0.0)
                last_err = max(live["api_error"], meter.last_api_error_ts or 0.0)
                if (time.time() - last_reply > hang_after_s and last_err > last_reply
                        and meter.api_errors_since_reply >= HANG_MIN_API_ERRORS):
                    return "hang"
            return None

        def _kill_cli() -> None:
            pid = getattr(getattr(cli.get("transport"), "_process", None), "pid", None)
            if pid is not None:
                kill_process_tree(pid)

        def _watch() -> None:
            while not watcher_done.wait(poll_every):
                why = _check()
                if why:
                    stop.setdefault("why", why)
                    logger.warning("v8: stopping session (%s) from its transcript", why)
                    _kill_cli()
                    return

        def _best_usage(stream_usage: dict) -> dict:
            """The larger (on the ruler) of the stream's usage and the transcript's."""
            if meter is None or not transcript_caps:
                return stream_usage
            meter.poll()
            tu = meter.totals()
            return tu if usage_cost(tu, cost_rates) > usage_cost(stream_usage, cost_rates) else stream_usage

        def _with_transcript_usage(res: SDKResult) -> SDKResult:
            if meter is None:
                return res
            import dataclasses as _dc
            meter.poll()
            res = _dc.replace(res, max_reply_usd=max(res.max_reply_usd, meter.max_reply_cost()),
                              output_limit_hits=max(res.output_limit_hits, meter.output_limit_hits),
                              cut_reasoning=res.cut_reasoning or (meter.cut_reasoning[-1]
                                                                  if meter.cut_reasoning else ""))
            if not transcript_caps:
                return res
            best = _best_usage(_usage_of(res))
            if usage_cost(best, cost_rates) <= usage_cost(_usage_of(res), cost_rates):
                return res
            return _dc.replace(res, cost_usd=usage_cost(best, cost_rates),
                               **{k: int(best.get(k, 0) or 0) for k in _USAGE_KEYS})

        async def _run() -> SDKResult:
            # Every exit (cap stop, error result, watchdog, STOP_IMMEDIATE, exception) kills the CLI
            # tree; otherwise it keeps working unattended, editing worktrees and spending.
            watcher = None
            if meter is not None:
                watcher = threading.Thread(target=_watch, daemon=True, name="nous-transcript-watch")
                watcher.start()
            try:
                res = await _session()
            finally:
                watcher_done.set()
                if cli.get("transport") is not None:
                    await _stop_cli(cli["transport"], exit_wait_s=5.0 if cli.get("result_seen") else 0.0)
                if watcher is not None:
                    watcher.join(timeout=5)
            return _with_transcript_usage(res)

        def _stopped_result(text: str, session_id: str | None, t0: float, n: int) -> SDKResult:
            """The cap or hang outcome after the watcher (or the loop) ended the session."""
            totals = _best_usage(_partial_totals())
            spent = usage_cost(totals, cost_rates)
            if stop.get("why") == "output_limit":
                return SDKResult(text=text, is_error=True,
                                 error_message="a reply hit the CLI's max_output_tokens limit; session stopped",
                                 subtype="error_output_limit", cost_usd=spent,
                                 duration_ms=int((time.time() - t0) * 1000), num_turns=n, session_id=session_id,
                                 max_reply_usd=meter.max_reply_cost() if meter is not None else 0.0,
                                 output_limit_hits=meter.output_limit_hits if meter is not None else 0,
                                 cut_reasoning=(meter.cut_reasoning[-1] if meter is not None and meter.cut_reasoning else ""),
                                 **{k: int(totals.get(k, 0) or 0) for k in _USAGE_KEYS})
            if stop.get("why") == "hang":
                err = SDKHangError(f"no assistant reply for over {hang_after_s:.0f}s while only API errors "
                                   "arrived; session killed")
                err.usage, err.session_id = totals, session_id
                raise err
            return SDKResult(text=text, is_error=True,
                             error_message=f"session cost ${spent:.2f} reached the ${max_cost_usd:.2f} cap",
                             subtype="error_max_budget_usd", cost_usd=spent,
                             duration_ms=int((time.time() - t0) * 1000), num_turns=n, session_id=session_id,
                             max_reply_usd=meter.max_reply_cost() if meter is not None else 0.0,
                             output_limit_hits=meter.output_limit_hits if meter is not None else 0,
                             cut_reasoning=(meter.cut_reasoning[-1] if meter is not None and meter.cut_reasoning else ""),
                             **{k: int(totals.get(k, 0) or 0) for k in _USAGE_KEYS})

        async def _session() -> SDKResult:
            # #193: ``permission_mode`` controls the Claude Code SDK
            # filesystem sandbox. Default is "bypassPermissions" because
            # nous campaigns routinely need writes outside cwd (the
            # orchestrator launches with cwd=worktree but BLIS / build /
            # test subprocess outputs land at <main-repo>/.nous/<run>/
            # runs/iter-N/results/, which the default sandbox rejects).
            # Operators can opt out via campaign.sandbox="default" or
            # `nous run --sandbox default` if they want the SDK's default
            # permission gating.
            #
            # CLAUDE_CLI_PATH lets operators (and the s390x QEMU container)
            # substitute an alternative Claude executable without patching
            # the SDK installation.  When unset the SDK's own discovery
            # logic applies (shutil.which("claude"), bundled binary, etc.).
            import os as _os
            _cli_path: str | None = _os.environ.get("CLAUDE_CLI_PATH") or None

            # Advertising WebSearch/WebFetch forces the Bedrock request
            # non-streaming (hardcoded 600s timeout + 2 retries ~= 30min
            # churn on long turns). Nous never needs them, so disable them
            # to keep every turn on the streaming path.
            _disallowed = ["WebSearch", "WebFetch"]

            if permission_mode:
                options = ClaudeAgentOptions(
                    model=model,
                    cwd=str(cwd) if cwd else None,
                    max_turns=max_turns,
                    system_prompt=system_prompt,
                    settings=str(settings_path) if settings_path else None,
                    permission_mode=permission_mode,  # type: ignore[arg-type]
                    effort=effort,
                    disallowed_tools=_disallowed,
                    **({"cli_path": _cli_path} if _cli_path else {}),
                    **({"resume": resume} if resume else {}),
                )
            else:
                options = ClaudeAgentOptions(
                    model=model,
                    cwd=str(cwd) if cwd else None,
                    max_turns=max_turns,
                    system_prompt=system_prompt,
                    settings=str(settings_path) if settings_path else None,
                    effort=effort,
                    disallowed_tools=_disallowed,
                    **({"cli_path": _cli_path} if _cli_path else {}),
                    **({"resume": resume} if resume else {}),
                )
            text_chunks: list[str] = []
            usage: dict = {}
            cost_usd = 0.0
            duration_ms = 0
            num_turns = 0
            session_id: str | None = None
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
            cli["transport"] = _cli_transport(_sdk, prompt, options)
            q_kw = {"transport": cli["transport"]} if cli["transport"] is not None else {}
            aiter = query(prompt=prompt, options=options, **q_kw).__aiter__()
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
            reply_usage = partial_usage  # per-reply usage, kept for a transient abort (capped sessions)
            last_mid: str | None = None
            stream_session_id: str | None = None
            stream = aiter_with_silence_watchdog(aiter, turn_silence_threshold)
            try:
                async for message in stream:
                    if stop.get("why"):
                        break
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
                        live["reply"] = time.time()
                        for block in getattr(message, "content", []):
                            if hasattr(block, "text"):
                                text_chunks.append(block.text)
                        stream_session_id = getattr(message, "session_id", None) or stream_session_id
                        if meter is not None and stream_session_id:
                            meter.session_ids.add(stream_session_id)
                        if max_cost_usd is not None and isinstance(getattr(message, "usage", None), dict):
                            # One reply streams as several messages repeating its usage: count it once.
                            mid = getattr(message, "message_id", None) or f"#{len(reply_usage)}"
                            prev = reply_usage.get(mid)
                            if prev is None or usage_cost(message.usage, cost_rates) >= usage_cost(prev, cost_rates):
                                reply_usage[mid] = message.usage
                            last_mid = mid
                            spent = sum(usage_cost(u, cost_rates) for u in reply_usage.values())
                            live["stream_usd"] = spent
                            if spent >= max_cost_usd:
                                with contextlib.suppress(Exception):
                                    await stream.aclose()
                                totals = {k: sum(int(u.get(k, 0) or 0) for u in reply_usage.values())
                                          for k in ("input_tokens", "output_tokens",
                                                    "cache_read_input_tokens", "cache_creation_input_tokens")}
                                return SDKResult(
                                    text="".join(text_chunks),
                                    is_error=True,
                                    error_message=(f"session cost ${spent:.2f} reached the "
                                                   f"${max_cost_usd:.2f} cap"),
                                    subtype="error_max_budget_usd",
                                    cost_usd=spent,
                                    duration_ms=int((time.time() - t0) * 1000),
                                    num_turns=len(reply_usage),
                                    session_id=stream_session_id,
                                    last_turn_cost_usd=usage_cost(reply_usage[last_mid], cost_rates),
                                    **totals,
                                )
                    elif cls == "SystemMessage":
                        data = getattr(message, "data", None)
                        if isinstance(data, dict) and data.get("session_id"):
                            stream_session_id = stream_session_id or data["session_id"]
                            if meter is not None:
                                meter.session_ids.add(stream_session_id)
                        sub = str(getattr(message, "subtype", "") or "").lower()
                        if "error" in sub or "retry" in sub:
                            live["api_error"] = time.time()
                    elif cls == "ResultMessage":
                        cli["result_seen"] = True
                        usage = getattr(message, "usage", {}) or {}
                        cost_usd = float(getattr(message, "total_cost_usd", 0.0) or 0.0)
                        duration_ms = int(getattr(message, "duration_ms", 0) or 0)
                        num_turns = int(getattr(message, "num_turns", 0) or 0)
                        session_id = getattr(message, "session_id", None) or None
                        if meter is not None and session_id:
                            meter.session_ids.add(session_id)
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
                                session_id=session_id,
                                subtype=getattr(message, "subtype", None),
                                last_turn_cost_usd=(usage_cost(reply_usage[last_mid], cost_rates)
                                                    if last_mid else 0.0),
                            )
                    if meter is not None and not stop.get("why"):
                        why = _check()  # also at every stream message, not only every poll interval
                        if why:
                            stop.setdefault("why", why)
                            _kill_cli()
                            break
            except Exception:
                if not stop.get("why"):
                    raise
                # the watcher killed the CLI, which ends its stream with an error: that is the stop
            if stop.get("why"):
                with contextlib.suppress(Exception):
                    await stream.aclose()
                return _stopped_result("".join(text_chunks), stream_session_id or session_id, t0,
                                       len(reply_usage))
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
                session_id=session_id,
                last_turn_cost_usd=usage_cost(reply_usage[last_mid], cost_rates) if last_mid else 0.0,
            )

        partial_usage: dict[str, dict] = {}

        def _partial_totals() -> dict:
            return {k: sum(int(u.get(k, 0) or 0) for u in partial_usage.values())
                    for k in ("input_tokens", "output_tokens",
                              "cache_read_input_tokens", "cache_creation_input_tokens")}

        try:
            return anyio.run(_run)
        except SDKTransientError as exc:
            exc.usage = _best_usage(_partial_totals())  # what the aborted turn already spent, for caps
            raise
        except SDKHangError:
            raise
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
                err = SDKTransientError(f"{cls_name}: {exc}")
                err.usage = _best_usage(_partial_totals())
                raise err from exc
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
        effort: str | None = None,
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
        # #282: per-phase SDK effort. None means "don't pass effort" — the
        # SDK applies its own default ("high"), so behaviour is unchanged.
        self._effort = effort
        self._last_effort: str | None = None  # v8: the effort the current session runs at
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
        # Optional per-session dollar cap (design_profile v7); None leaves sessions uncapped.
        self.budget_usd: float | None = None
        # Budget the session is told to aim for; the hard cap (budget_usd) may be looser.
        self.target_usd: float | None = None
        self._session_label: str | None = None
        # Session id of the last SDK result (or hang); v8 resumes a screened arm's session from it.
        self.last_session_id: str | None = None
        self._initial_resume: str | None = None

    @contextlib.contextmanager
    def resume_session(self, session_id: str | None):
        """The first SDK turn of the next dispatch inside the block continues ``session_id``.

        If that resume fails, the normal retry starts a fresh session with the same prompt.
        """
        old = self._initial_resume
        self._initial_resume = session_id or None
        try:
            yield
        finally:
            self._initial_resume = old

    @contextlib.contextmanager
    def session_budget(self, usd: float | None, label: str | None = None, target_usd: float | None = None):
        """Cap every SDK session started inside the block at ``usd`` (token ruler)."""
        old = (self.budget_usd, self._session_label, self.target_usd)
        self.budget_usd, self._session_label, self.target_usd = usd, label, target_usd
        try:
            yield
        finally:
            self.budget_usd, self._session_label, self.target_usd = old

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
        """Return the live watchdog threshold for THIS phase.

        Uses the campaign-configured per-phase value (set in __init__),
        falling back to the legacy scalar. Bundle-written overrides were
        removed in #305 — the LLM has no basis to set watchdog ceilings
        for phases it didn't run.
        """
        return self._phase_silence_thresholds.get(phase, self._turn_silence_threshold)


    def dispatch(  # type: ignore[override]
        self, role: str, phase: str, *, output_path, iteration: int,
        perspective=None, h_main_result="CONFIRMED",
    ) -> None:
        inputs_dir = self.work_dir / "runs" / f"iter-{iteration}" / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        self._event_log_path = inputs_dir / "executor_log.jsonl"
        phase_key = self._normalize_phase(phase)
        original_threshold = self._turn_silence_threshold
        self._turn_silence_threshold = self._resolve_turn_silence_threshold(phase_key)
        try:
            super().dispatch(
                role, phase,
                output_path=output_path, iteration=iteration,
                perspective=perspective, h_main_result=h_main_result,
            )
        finally:
            self._turn_silence_threshold = original_threshold
            try:
                self._maybe_log_silence(iteration=iteration, phase=phase)
            except Exception as exc:  # noqa: BLE001
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

        from orchestrator.design_profile import (
            OUTPUT_LIMIT_PROMPT, WRAP_UP_PROMPT, budget_wrap_up_usd, max_wrap_ups, wrap_up_max_turns,
        )
        failure_count = 0
        original_prompt = prompt
        wrap_ups_left = max_wrap_ups(self.campaign)
        from orchestrator.design_profile import is_v7_family, is_v8, v8_settings
        output_limit_resumes_left = 2 if is_v7_family(self.campaign or {}) else 0
        v8 = is_v8(self.campaign or {})
        # v8: a capped session's spend comes from its transcript, and a hung session is stopped.
        v8_kw: dict = {}
        effort = self._effort
        limit_prompt = OUTPUT_LIMIT_PROMPT
        if v8:
            from orchestrator.design_profile import V8_OUTPUT_LIMIT_PROMPT
            from orchestrator.effort import session_effort
            v8_kw["hang_after_s"] = v8_settings(self.campaign).hang_minutes * 60.0
            v8_kw["stop_on_output_limit"] = True
            effort = session_effort(self.work_dir, self.model, label=self._session_label, explicit=self._effort)
            output_limit_resumes_left = 3
            limit_prompt = V8_OUTPUT_LIMIT_PROMPT
        self._last_effort = effort
        # v8: after a dollar cap the orchestrator writes the artifacts from disk; only the design
        # session (whose bundle nothing else can write) keeps its wrap-up.
        cap_wrap_up = not (v8 and self._session_label != "design")
        resume_id: str | None = self._initial_resume
        self._initial_resume = None
        # Dollar cap (v7): ``limit`` is what this whole dispatch may spend on the token ruler, across
        # retries; ``spent`` counts every attempt, including the partial usage of transient aborts.
        # Retries only get ``limit - spent``. The only extension is a wrap-up after a cap or turn limit.
        cap = self.budget_usd
        limit, spent = cap, 0.0
        next_budget: float | None = None  # smaller per-attempt cap for a wrap-up turn
        budget_wrap_up_done = False
        cut_resume_done = False  # v8: one resume after a cap that tripped on a cut reply
        last_text = ""
        budget: float | None = None
        while True:
            if cap is not None:
                left = limit - spent
                if left < _MIN_ATTEMPT_USD:
                    self._log_retry("max_budget_stop", failure_count + 1, RuntimeError(
                        f"session spent ${spent:.2f} of its ${limit:.2f} cap; no retry"))
                    return last_text
                budget = round(min(left, next_budget) if next_budget is not None else left, 4)
                next_budget = None
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
                    # v8 has its own hang watchdog (API errors + no reply); the per-message silence guard
                    # killed 64k thinking replies at 10 min, before they ended (live p58 smoke s1).
                    turn_silence_threshold=None if v8 else self._turn_silence_threshold,
                    effort=effort,
                    **({"resume": resume_id} if resume_id else {}),
                    **({"max_cost_usd": budget, "cost_rates": self._cost_rates()}
                       if cap is not None else {}),
                    **({"transcript_caps": True} if v8 and cap is not None else {}),
                    **v8_kw,
                )
            except SDKHangError as exc:
                # Not retried here: a resumed or fresh retry would replay the request that hangs. The
                # caller restarts the work from its last saved state.
                self._log_retry("hang", failure_count + 1, exc)
                if cap is not None:
                    self._charge_partial(exc, budget)
                if getattr(exc, "session_id", None):
                    self.last_session_id = exc.session_id
                raise
            except SDKTransientError as exc:
                failure_count += 1
                self._log_retry("transient", failure_count, exc)
                if cap is not None:
                    spent += self._charge_partial(exc, budget)
                if self._exhausted(failure_count):
                    raise RuntimeError(
                        f"SDK still failing after {failure_count} attempt(s): {exc}"
                    ) from exc
                time.sleep(_backoff_for(failure_count))
                if resume_id is None:
                    prompt = self._maybe_resume_hint(prompt, original_prompt, "transient")
                continue

            self._log_metrics_row(result, budget if cap is not None else None)
            if result.session_id:
                self.last_session_id = result.session_id
            cut = _is_output_limit(result) or result.output_limit_hits > 0
            if v8 and cut:
                # Recorded whichever check ended the session (a cap can trip on the same reply).
                from orchestrator.effort import lower, record_output_limit
                for _ in range(max(1, result.output_limit_hits)):
                    record_output_limit(self.work_dir)
                effort = lower(effort or "high")
                self._last_effort = effort
                if result.cut_reasoning:
                    limit_prompt = self._save_cut_reasoning(result.cut_reasoning)
            if cap is not None:
                spent += usage_cost(_usage_of(result), self._cost_rates())
                last_text = result.text or last_text

            # Dollar cap hit: never restart (that would spend the cap again). Resume once with a
            # wrap-up sized from the last turn so the session writes its artifacts, then stop.
            if result.is_error and (result.subtype == "error_max_budget_usd"
                                    or "error_max_budget_usd" in result.error_message):
                # v8: the reply that crossed the cap was cut at the output limit, so the session paid for
                # reasoning it never acted on. One short resume turns the saved reasoning into code.
                if (v8 and result.session_id and result.output_limit_hits > 0 and result.cut_reasoning
                        and not cut_resume_done and cap is not None):
                    cut_resume_done = True
                    self._log_retry("cut_reasoning_resume", failure_count + 1,
                                    RuntimeError(result.error_message))
                    resume_id, prompt = result.session_id, limit_prompt
                    next_budget = CUT_RESUME_USD
                    limit = max(limit, spent + next_budget)
                    continue
                if result.session_id and not budget_wrap_up_done and cap_wrap_up:
                    budget_wrap_up_done = True
                    self._log_retry("max_budget_wrap_up", failure_count + 1,
                                    RuntimeError(result.error_message))
                    resume_id, prompt = result.session_id, WRAP_UP_PROMPT
                    turns = wrap_up_max_turns(self.campaign)
                    if cap is not None:
                        next_budget = budget_wrap_up_usd(cap, result.last_turn_cost_usd)
                        limit = max(limit, spent + next_budget)
                    continue
                self._log_retry("max_budget_stop", failure_count + 1, RuntimeError(result.error_message))
                return result.text

            # Turn limit hit: continue the same session with a short wrap-up instead of restarting
            # from scratch, which would redo the exploration and hit the same limit again.
            if (result.is_error
                    and (result.subtype == "error_max_turns" or "error_max_turns" in result.error_message)
                    and result.session_id and wrap_ups_left > 0):
                wrap_ups_left -= 1
                self._log_retry("max_turns_wrap_up", failure_count + 1,
                                RuntimeError(result.error_message))
                resume_id = result.session_id
                prompt = WRAP_UP_PROMPT
                turns = wrap_up_max_turns(self.campaign)
                if cap is not None:
                    next_budget = budget_wrap_up_usd(cap, result.last_turn_cost_usd)
                    limit = max(limit, spent + next_budget)
                continue
            # A reply over the CLI's output-token maximum is lost, and the CLI gives up after a few in a
            # row. A fresh restart would redo the same long reasoning, so resume this session instead
            # (its files and earlier turns survive) and ask for the work in short steps.
            if result.is_error and _is_output_limit(result) and result.session_id \
                    and output_limit_resumes_left > 0:
                output_limit_resumes_left -= 1
                self._log_retry("output_limit_resume", failure_count + 1, RuntimeError(result.error_message))
                resume_id, prompt = result.session_id, limit_prompt
                if v8:
                    logger.warning("v8: a reply hit the output limit; resuming at effort %s", effort)
                continue
            if resume_id is not None:
                if budget_wrap_up_done:
                    # The cap was reached and its one wrap-up failed: stop rather than restart fresh.
                    self._log_retry("max_budget_stop", failure_count + 1, RuntimeError(
                        f"wrap-up after the dollar cap failed: {result.error_message or 'no error text'}"))
                    return result.text or last_text
                # A failed wrap-up falls back to the normal fresh-session retry (on what is left of the cap).
                resume_id, prompt, turns = None, original_prompt, max_turns or self.max_turns

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
        if self.max_retries is None:
            # Unbounded mode still honours an absolute safety cap so a
            # permanent error can't loop forever (#279 review).
            return failure_count > _UNBOUNDED_RETRY_SAFETY_CAP
        return failure_count > self.max_retries

    def _log_retry(self, kind: str, attempt: int, exc: BaseException) -> None:
        log_retry_event(self._metrics_path, {
            "role": self._current_role,
            "phase": self._current_phase,
            "failure_type": kind,
            "attempt": attempt,
            "error": str(exc)[:500],
        })

    def _save_cut_reasoning(self, text: str) -> str:
        """Keep a cut reply's reasoning on disk and return the resume prompt that builds on its ending."""
        from orchestrator.design_profile import CUT_REASONING_TAIL_CHARS, cut_resume_prompt
        from orchestrator.util import atomic_write
        d = Path(self.work_dir) / "cut_reasoning"
        d.mkdir(parents=True, exist_ok=True)
        stem = self._session_label or "session"
        path = d / f"{stem}-{len(list(d.glob(stem + '-*.md'))) + 1}.md"
        atomic_write(path, text)
        return cut_resume_prompt(text[-CUT_REASONING_TAIL_CHARS:], path)

    def _charge_partial(self, exc: BaseException, budget: float | None) -> float:
        """Log the usage a transient abort had already streamed (capped sessions); return its cost."""
        usage = {k: int(v or 0) for k, v in (getattr(exc, "usage", None) or {}).items()
                 if k in _USAGE_KEYS}
        if not any(usage.values()):
            return 0.0
        cost = usage_cost(usage, self._cost_rates())
        kind = "hang" if isinstance(exc, SDKHangError) else "transient abort"
        self._log_metrics_row(SDKResult(text="", cost_usd=cost, num_turns=0, is_error=True,
                                        error_message=f"{kind}: {exc}"[:200], **usage), budget)
        return cost

    def _cost_rates(self) -> dict:
        from orchestrator.design_profile import v7_settings
        return v7_settings(self.campaign).cost_rates

    def _log_metrics_row(self, result: SDKResult, budget: float | None = None) -> None:
        extra = {} if budget is None else {"budget_usd": budget, "session_label": self._session_label}
        if getattr(result, "max_reply_usd", 0.0):
            extra["max_reply_usd"] = round(float(result.max_reply_usd), 4)
        if self._last_effort:
            extra["effort"] = self._last_effort
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
            **extra,
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
