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

from orchestrator.sdk_dispatch import SDKDispatcher, SDKResult, SDKTransientError


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
