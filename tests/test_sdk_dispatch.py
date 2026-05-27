"""Behavioral tests for the SDK-based dispatcher.

These tests do NOT mock the Claude Agent SDK directly. They inject a
``sdk_runner`` callable that returns a ``SDKResult`` — same contract the
real dispatcher uses internally — and assert what the dispatcher does
with that result: artifacts on disk, metrics rows, retry behavior.

That is the contract the rest of Nous depends on. Tests below should
keep passing across SDK API churn as long as the dispatcher's responsibility
to write artifacts and emit metrics holds.

No assertions about argv shape, internal helper calls, or which methods
the dispatcher invoked on the runner. That's structural — out of scope.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.sdk_dispatch import (
    SDKDispatcher,
    SDKResult,
    SDKTransientError,
    aiter_with_silence_watchdog,
    build_error_message,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


def _make_campaign(repo_path: Path | None = None) -> dict:
    target = {
        "name": "test-system",
        "description": "A small test system used by behavioral tests.",
        "observable_metrics": ["latency", "throughput"],
        "controllable_knobs": ["batch_size", "concurrency"],
    }
    if repo_path is not None:
        target["repo_path"] = str(repo_path)
    return {
        "research_question": "What drives latency?",
        "target_system": target,
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class _ScriptedRunner:
    """A runner that returns a queue of pre-staged results.

    Each call pops the next entry. Entries can be SDKResult objects (returned)
    or BaseException instances (raised). When the queue is exhausted, raises
    AssertionError — a test-only failure mode that signals the dispatcher
    called the runner more times than expected.
    """

    def __init__(self, scripted: list):
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> SDKResult:
        self.calls.append(kwargs)
        if not self._scripted:
            raise AssertionError(
                f"Runner exhausted; dispatcher called it {len(self.calls)} times "
                f"but only {len(self.calls) - 1} responses were scripted."
            )
        nxt = self._scripted.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


# ─── Text-output phase (design): dispatcher writes assistant text to log ───

class TestSDKDispatchTextPhase:
    """For design/execute-analyze, the SDK runs an agent that writes
    artifacts via tool calls; the dispatcher persists the assistant's
    final text message as a log."""

    def test_writes_assistant_text_to_output_path(self, tmp_path):
        runner = _ScriptedRunner([
            SDKResult(text="design log content here", input_tokens=100, output_tokens=50),
        ])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
        )

        out = tmp_path / "runs" / "iter-1" / "design_log.md"
        dispatcher.dispatch("planner", "design", output_path=out, iteration=1)

        assert out.exists()
        assert "design log content here" in out.read_text()

    def test_emits_one_metrics_row_per_call(self, tmp_path):
        runner = _ScriptedRunner([
            SDKResult(
                text="ok",
                input_tokens=400,
                output_tokens=120,
                cache_read_input_tokens=300,
                cache_creation_input_tokens=0,
                cost_usd=0.021,
                duration_ms=4500,
                num_turns=3,
            ),
        ])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
        )

        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )

        rows = _read_jsonl(tmp_path / "llm_metrics.jsonl")
        assert len(rows) == 1
        row = rows[0]
        assert row["dispatcher"] == "sdk"
        assert row["role"] == "planner"
        assert row["phase"] == "design"
        assert row["input_tokens"] == 400
        assert row["output_tokens"] == 120
        assert row["cache_read_input_tokens"] == 300
        assert row["cost_usd"] == pytest.approx(0.021)
        assert row["num_turns"] == 3


# ─── Structured-output phase: dispatcher parses + validates + writes JSON ──

class TestSDKDispatchStructuredPhase:
    """Gate-summary phase: SDK returns a fenced JSON; dispatcher parses,
    validates against gate_summary.schema.json, writes JSON output."""

    _SUMMARY = {
        "gate_type": "design",
        "summary": "Hypothesis bundle is well-formed and consistent with active principles.",
        "key_points": [
            "Hypothesis bundle covers the four arms.",
            "Methodology aligns with prior principles.",
        ],
    }

    def test_writes_valid_json_when_runner_returns_fenced_payload(self, tmp_path):
        fenced = "```json\n" + json.dumps(self._SUMMARY) + "\n```"
        runner = _ScriptedRunner([SDKResult(text=fenced)])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(),
            sdk_runner=runner,
        )

        out = tmp_path / "runs" / "iter-1" / "gate_summary.json"
        dispatcher.dispatch(
            "summarizer", "summarize-gate",
            output_path=out, iteration=1, perspective="design",
        )

        assert out.exists()
        parsed = json.loads(out.read_text())
        jsonschema.validate(parsed, _load_schema("gate_summary.schema.json"))
        assert parsed["gate_type"] == "design"


# ─── Transient retry behavior ───────────────────────────────────────────────

class TestSDKDispatchTransientRetry:

    def test_retries_after_transient_error_then_succeeds(self, tmp_path, monkeypatch):
        # Disable backoff sleep to keep the test fast.
        monkeypatch.setattr(
            "orchestrator.sdk_dispatch.time.sleep", lambda _s: None,
        )
        runner = _ScriptedRunner([
            SDKTransientError("network blip"),
            SDKResult(text="recovered text", input_tokens=10, output_tokens=5),
        ])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
            max_retries=3,
        )

        out = tmp_path / "runs" / "iter-1" / "design_log.md"
        dispatcher.dispatch("planner", "design", output_path=out, iteration=1)

        assert "recovered text" in out.read_text()

        retry_log = _read_jsonl(tmp_path / "retry_log.jsonl")
        assert len(retry_log) == 1
        assert retry_log[0]["role"] == "planner"
        assert retry_log[0]["phase"] == "design"
        assert "network blip" in retry_log[0]["error"]

    def test_raises_after_retries_exhausted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "orchestrator.sdk_dispatch.time.sleep", lambda _s: None,
        )
        runner = _ScriptedRunner([
            SDKTransientError("persistent failure"),
            SDKTransientError("persistent failure"),
            SDKTransientError("persistent failure"),
        ])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
            max_retries=2,
        )

        with pytest.raises(RuntimeError, match="still failing"):
            dispatcher.dispatch(
                "planner", "design",
                output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
                iteration=1,
            )

        retry_log = _read_jsonl(tmp_path / "retry_log.jsonl")
        # Three failures = three retry-log rows.
        assert len(retry_log) == 3


# ─── #122 Phase B: methodology preamble cached as system_prompt ────────────

class TestMethodologyPreambleCached:
    """When the methodology files are on disk, SDKDispatcher loads them as
    a single ``system_prompt`` so the Anthropic API marks them cached.
    Tests assert the wiring contract: same system_prompt across calls,
    placeholders stripped (otherwise dynamic content in system_prompt
    would bust the cache)."""

    def test_runner_receives_preamble_in_system_prompt(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        # Use a placeholder that IS in the dispatcher's context so the
        # regular template-load path doesn't reject it; the preamble
        # loader still strips them before placing in system_prompt.
        (prompts_dir / "design.md").write_text(
            "# Design methodology\n\nStable text for {{target_system}}.\n"
        )
        (prompts_dir / "execute_analyze.md").write_text(
            "# Execute methodology\n\nMore stable text for {{target_system}}.\n"
        )

        captured: list[dict] = []

        def runner(**kwargs):
            captured.append(kwargs)
            return SDKResult(text="ok")

        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
            prompts_dir=prompts_dir,
        )
        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )

        assert len(captured) == 1
        sp = captured[0]["system_prompt"]
        assert sp is not None
        assert "Design methodology" in sp
        assert "Execute methodology" in sp
        # Placeholders are stripped — dynamic content lives in the user
        # message; otherwise the cache would never hit.
        assert "{{target_system}}" not in sp
        assert "{{" not in sp

    def test_two_calls_reuse_same_system_prompt(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "design.md").write_text(
            "# Design methodology\n\nText for {{target_system}}.\n"
        )

        captured: list[dict] = []

        def runner(**kwargs):
            captured.append(kwargs)
            return SDKResult(text="ok")

        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
            prompts_dir=prompts_dir,
        )
        for i in range(1, 3):
            dispatcher.dispatch(
                "planner", "design",
                output_path=tmp_path / "runs" / f"iter-{i}" / "design_log.md",
                iteration=i,
            )

        # Same system_prompt across both calls — the property the cache
        # relies on.
        assert captured[0]["system_prompt"] == captured[1]["system_prompt"]


# ─── Error result path ──────────────────────────────────────────────────────

class TestSDKDispatchErrorResult:
    """When the SDK returns is_error=True (e.g. API rejected the request),
    the dispatcher treats it as transient unless explicitly fatal."""

    def test_is_error_treated_as_transient_and_retried(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "orchestrator.sdk_dispatch.time.sleep", lambda _s: None,
        )
        runner = _ScriptedRunner([
            SDKResult(text="", is_error=True, error_message="rate limit exceeded"),
            SDKResult(text="finally got through", input_tokens=10, output_tokens=5),
        ])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
            max_retries=3,
        )

        out = tmp_path / "runs" / "iter-1" / "design_log.md"
        dispatcher.dispatch("planner", "design", output_path=out, iteration=1)

        assert "finally got through" in out.read_text()

        retry_log = _read_jsonl(tmp_path / "retry_log.jsonl")
        assert len(retry_log) == 1
        assert "rate limit exceeded" in retry_log[0]["error"]


# ─── _tee_event extraction (#195) ─────────────────────────────────────────


class _FakeToolUseBlock:
    def __init__(self, name: str):
        self.name = name


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeAssistantMessage:
    """Mimics SDK message shape: tool_name not at top level; lives on
    ToolUseBlock instances inside the content list."""
    def __init__(self, content: list):
        self.content = content


class TestTeeEventToolNameExtraction:
    """#195: _tee_event must extract tool_name from ToolUseBlock entries
    inside content, not from the message top-level (which is empty)."""

    def test_extracts_tool_name_from_tool_use_block(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import _tee_event
        log = tmp_path / "executor_log.jsonl"
        msg = _FakeAssistantMessage(content=[
            _FakeTextBlock("thinking..."),
            _FakeToolUseBlock(name="Bash"),
        ])
        _tee_event(log, msg, "AssistantMessage")
        rows = [json.loads(l) for l in log.read_text().splitlines() if l]
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "Bash"

    def test_picks_last_tool_block_when_multiple(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import _tee_event
        log = tmp_path / "executor_log.jsonl"
        msg = _FakeAssistantMessage(content=[
            _FakeToolUseBlock(name="Read"),
            _FakeToolUseBlock(name="Bash"),
            _FakeToolUseBlock(name="Edit"),
        ])
        _tee_event(log, msg, "AssistantMessage")
        rows = [json.loads(l) for l in log.read_text().splitlines() if l]
        # Last tool wins — most recent action.
        assert rows[0]["tool_name"] == "Edit"

    def test_no_tool_block_means_no_tool_name(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import _tee_event
        log = tmp_path / "executor_log.jsonl"
        msg = _FakeAssistantMessage(content=[_FakeTextBlock("just text")])
        _tee_event(log, msg, "AssistantMessage")
        rows = [json.loads(l) for l in log.read_text().splitlines() if l]
        assert "tool_name" not in rows[0]

    def test_top_level_tool_name_still_wins_when_present(self, tmp_path: Path) -> None:
        """Forward-compat: if a future SDK release puts tool_name at
        message top-level, prefer that over the content-walk fallback."""
        from orchestrator.sdk_dispatch import _tee_event
        log = tmp_path / "executor_log.jsonl"

        class _MsgWithTopLevelToolName:
            tool_name = "TopLevelTool"
            content = [_FakeToolUseBlock(name="Bash")]

        _tee_event(log, _MsgWithTopLevelToolName(), "AssistantMessage")
        rows = [json.loads(l) for l in log.read_text().splitlines() if l]
        assert rows[0]["tool_name"] == "TopLevelTool"



# ─── #205: live mid-turn silence watchdog ─────────────────────────────────


class _ImmediateAsyncIter:
    """An async iterator that yields a fixed list of values immediately."""

    def __init__(self, values: list):
        self._values = list(values)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._values:
            raise StopAsyncIteration
        return self._values.pop(0)


class _StallingAsyncIter:
    """An async iterator that yields one value, then stalls forever.

    Used to simulate a model-side mid-turn hang. The watchdog under test
    must abort the second ``__anext__`` after the configured threshold.
    """

    def __init__(self, first_value):
        self._first = first_value
        self._yielded = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._yielded:
            self._yielded = True
            return self._first
        # Stall — wait far longer than any test threshold; the watchdog
        # should cancel us before this completes.
        import anyio
        await anyio.sleep(3600)
        raise StopAsyncIteration  # pragma: no cover — unreachable


class TestSilenceWatchdog:
    """#205: aiter_with_silence_watchdog raises SDKTransientError when the
    underlying async iterator stalls longer than the configured threshold,
    instead of blocking indefinitely. Pure asyncio test — no SDK imports."""

    def test_passthrough_when_threshold_disabled(self):
        """threshold=None means no watchdog: every value flows through."""
        import anyio

        async def _go():
            collected = []
            aiter = _ImmediateAsyncIter(["a", "b", "c"])
            async for m in aiter_with_silence_watchdog(aiter, threshold=None):
                collected.append(m)
            return collected

        assert anyio.run(_go) == ["a", "b", "c"]

    def test_passthrough_when_threshold_zero(self):
        """threshold=0 (or negative) also disables the watchdog."""
        import anyio

        async def _go():
            collected = []
            aiter = _ImmediateAsyncIter(["x", "y"])
            async for m in aiter_with_silence_watchdog(aiter, threshold=0):
                collected.append(m)
            return collected

        assert anyio.run(_go) == ["x", "y"]

    def test_raises_transient_on_silence(self):
        """When the iterator stalls past the threshold, the helper raises
        SDKTransientError (not TimeoutError) so the dispatcher's existing
        retry path catches it."""
        import anyio

        async def _go():
            aiter = _StallingAsyncIter(first_value="hello")
            collected = []
            async for m in aiter_with_silence_watchdog(aiter, threshold=0.05):
                collected.append(m)
            return collected

        with pytest.raises(SDKTransientError, match=r"silence between events"):
            anyio.run(_go)

    def test_no_raise_when_messages_arrive_within_threshold(self):
        """If every message arrives within threshold, no transient is raised."""
        import anyio

        async def _go():
            collected = []
            aiter = _ImmediateAsyncIter([1, 2, 3])
            async for m in aiter_with_silence_watchdog(aiter, threshold=5.0):
                collected.append(m)
            return collected

        assert anyio.run(_go) == [1, 2, 3]


class TestTurnSilenceThresholdWiring:
    """#205: SDKDispatcher reads campaign.sdk_timeouts.turn_silence_threshold_seconds
    and passes it through to the runner. The threshold defaults to the
    post-mortem silence_threshold_seconds when unset."""

    def test_default_threshold_matches_silence_threshold(self, tmp_path):
        """Default behaviour: turn_silence_threshold == silence_threshold."""
        runner = _ScriptedRunner([SDKResult(text="ok")])
        campaign = _make_campaign(tmp_path)
        # silence_threshold defaults to 600 in the dispatcher
        dispatcher = SDKDispatcher(
            work_dir=tmp_path, campaign=campaign, sdk_runner=runner,
        )
        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        assert runner.calls[0]["turn_silence_threshold"] == 600.0

    def test_explicit_threshold_passed_to_runner(self, tmp_path):
        """campaign.sdk_timeouts.turn_silence_threshold_seconds = 30 → 30
        flows to the runner."""
        runner = _ScriptedRunner([SDKResult(text="ok")])
        campaign = _make_campaign(tmp_path)
        campaign.setdefault("sdk_timeouts", {})["turn_silence_threshold_seconds"] = 30
        dispatcher = SDKDispatcher(
            work_dir=tmp_path, campaign=campaign, sdk_runner=runner,
        )
        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        assert runner.calls[0]["turn_silence_threshold"] == 30.0

    def test_zero_disables_live_watchdog(self, tmp_path):
        """Setting turn_silence_threshold_seconds=0 keeps the post-mortem
        analyzer (silence_threshold_seconds) but disables the live watchdog."""
        runner = _ScriptedRunner([SDKResult(text="ok")])
        campaign = _make_campaign(tmp_path)
        campaign.setdefault("sdk_timeouts", {})["turn_silence_threshold_seconds"] = 0
        dispatcher = SDKDispatcher(
            work_dir=tmp_path, campaign=campaign, sdk_runner=runner,
        )
        dispatcher.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        assert runner.calls[0]["turn_silence_threshold"] == 0.0

    def test_negative_threshold_rejected(self, tmp_path):
        """Defensive: a negative threshold raises ValueError at init."""
        campaign = _make_campaign(tmp_path)
        campaign.setdefault("sdk_timeouts", {})["turn_silence_threshold_seconds"] = -1
        with pytest.raises(ValueError, match=r"turn_silence_threshold_seconds"):
            SDKDispatcher(
                work_dir=tmp_path, campaign=campaign,
                sdk_runner=_ScriptedRunner([]),
            )


# ─── #216: build_error_message synthesizes useful diagnostics ─────────────


class _FakeResultMessage:
    """Duck-typed stand-in for the real SDK ResultMessage."""

    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)


class TestBuildErrorMessage:
    """#216: build_error_message must never produce the literal string
    'None' or '' when the SDK returns is_error=True. Operators reading
    retry_log.jsonl after a failure should always have something to act on."""

    def test_passes_through_substantive_result(self):
        m = _FakeResultMessage(result="rate limit exceeded for tenant X")
        assert build_error_message(m) == "rate limit exceeded for tenant X"

    def test_none_result_falls_back_to_diagnostic(self):
        """The friction-test failure: result=None produced 'None' in retry_log."""
        m = _FakeResultMessage(
            result=None,
            stop_reason="end_turn",
            num_turns=14,
            duration_ms=125000,
        )
        msg = build_error_message(m, message_class_counts={
            "AssistantMessage": 28, "UserMessage": 14, "ResultMessage": 1,
        })
        assert "None" not in msg or "no result text" in msg
        assert "stop_reason=end_turn" in msg
        assert "num_turns=14" in msg
        assert "duration_ms=125000" in msg
        assert "AssistantMessage=28" in msg

    def test_empty_string_result_falls_back(self):
        m = _FakeResultMessage(result="", stop_reason="max_turns_reached")
        msg = build_error_message(m)
        assert "stop_reason=max_turns_reached" in msg

    def test_literal_none_string_treated_as_missing(self):
        """If the SDK literally puts 'None' in the result, treat as missing
        so the operator gets the diagnostic context, not a useless 'None'."""
        m = _FakeResultMessage(result="None", stop_reason="end_turn")
        msg = build_error_message(m)
        assert "stop_reason=end_turn" in msg

    def test_no_attributes_at_all_produces_actionable_pointer(self):
        """Worst case: nothing useful on the message. The error must still
        point the operator somewhere they can dig (executor_log.jsonl)."""
        m = _FakeResultMessage(result=None)
        msg = build_error_message(m, message_class_counts={})
        assert "executor_log" in msg

    def test_subtype_surfaces(self):
        """Some failure paths populate ``subtype`` instead of ``stop_reason``."""
        m = _FakeResultMessage(result="", subtype="error_during_execution")
        msg = build_error_message(m)
        assert "subtype=error_during_execution" in msg

    def test_zero_num_turns_omitted(self):
        """A num_turns=0 isn't useful; only positive counts are reported."""
        m = _FakeResultMessage(result=None, num_turns=0, stop_reason="x")
        msg = build_error_message(m)
        assert "num_turns" not in msg
        assert "stop_reason=x" in msg
