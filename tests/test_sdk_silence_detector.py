"""Behavioral tests for the SDK silence detector (#201).

After each SDK turn the dispatcher walks the streaming executor_log.jsonl,
finds the longest gap between consecutive events, and (if the gap
exceeds ``campaign.sdk_timeouts.silence_threshold_seconds``) writes a
``failure_type: "sdk_silence"`` entry to retry_log.jsonl.

Observation-only today — doesn't interrupt or fail the turn. The hard-kill
on prolonged silence is a future addition (issue body's stretch goal).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─── summarize_silence_gaps helper ─────────────────────────────────────


class TestSummarizeSilenceGaps:
    def test_no_log_returns_zero(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import summarize_silence_gaps
        out = summarize_silence_gaps(tmp_path / "missing.jsonl")
        assert out == {"max_gap_seconds": 0.0, "event_count": 0}

    def test_empty_log_returns_zero(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import summarize_silence_gaps
        log = tmp_path / "events.jsonl"
        log.write_text("")
        out = summarize_silence_gaps(log)
        assert out == {"max_gap_seconds": 0.0, "event_count": 0}

    def test_single_event_no_gap(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import summarize_silence_gaps
        log = tmp_path / "events.jsonl"
        log.write_text(json.dumps({"type": "X", "ts": 100.0}) + "\n")
        out = summarize_silence_gaps(log)
        assert out == {"max_gap_seconds": 0.0, "event_count": 1}

    def test_finds_longest_gap_across_events(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import summarize_silence_gaps
        log = tmp_path / "events.jsonl"
        # Timestamps with deltas: 5s, 1200s (gap), 2s, 3s — max = 1200s
        log.write_text("\n".join(json.dumps({"type": "X", "ts": t}) for t in [
            100.0, 105.0, 1305.0, 1307.0, 1310.0,
        ]) + "\n")
        out = summarize_silence_gaps(log)
        assert out["event_count"] == 5
        assert out["max_gap_seconds"] == pytest.approx(1200.0)

    def test_skips_corrupt_lines(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import summarize_silence_gaps
        log = tmp_path / "events.jsonl"
        log.write_text(
            json.dumps({"type": "X", "ts": 100.0}) + "\n"
            "not valid json\n"
            + json.dumps({"type": "X", "ts": 110.0}) + "\n"
        )
        out = summarize_silence_gaps(log)
        # Two valid events; gap = 10s.
        assert out == {"max_gap_seconds": 10.0, "event_count": 2}

    def test_skips_events_without_timestamps(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import summarize_silence_gaps
        log = tmp_path / "events.jsonl"
        log.write_text(
            json.dumps({"type": "X", "ts": 100.0}) + "\n"
            + json.dumps({"type": "Y"}) + "\n"  # missing ts
            + json.dumps({"type": "X", "ts": 105.0}) + "\n"
        )
        out = summarize_silence_gaps(log)
        # Two timestamped events; gap = 5s.
        assert out["max_gap_seconds"] == pytest.approx(5.0)
        assert out["event_count"] == 2


# ─── End-to-end: silence triggers retry_log entry ─────────────────────


class _StaticRunner:
    """Runner that pre-stages the streaming log so the silence detector
    has something to scan. Returns a minimal SDKResult."""

    def __init__(self, gap_seconds: float):
        self.gap_seconds = gap_seconds

    def __call__(self, **kwargs):
        from orchestrator.sdk_dispatch import SDKResult
        log_path = kwargs.get("event_log_path")
        if log_path is not None:
            t0 = 1_000_000.0
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("\n".join(
                json.dumps({"type": "AssistantMessage", "ts": t})
                for t in [t0, t0 + self.gap_seconds, t0 + self.gap_seconds + 1]
            ) + "\n")
        return SDKResult(text="ok")


def _campaign(repo_path: Path, **extra) -> dict:
    return {
        "research_question": "?",
        "target_system": {
            "name": "t",
            "description": "d",
            "repo_path": str(repo_path),
        },
        **extra,
    }


class TestSilenceTriggersRetryLog:
    def test_gap_above_threshold_writes_retry_entry(self, tmp_path: Path) -> None:
        """#201: a streaming log with a silence > threshold leaves a
        ``failure_type: sdk_silence`` row in retry_log.jsonl."""
        from orchestrator.sdk_dispatch import SDKDispatcher

        runner = _StaticRunner(gap_seconds=900)  # 15-min gap
        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign(
                tmp_path,
                sdk_timeouts={"silence_threshold_seconds": 600},
            ),
            sdk_runner=runner,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )

        retry_log = tmp_path / "retry_log.jsonl"
        assert retry_log.exists()
        rows = [
            json.loads(line) for line in retry_log.read_text().splitlines() if line
        ]
        silence_rows = [r for r in rows if r.get("failure_type") == "sdk_silence"]
        assert len(silence_rows) == 1
        row = silence_rows[0]
        assert row["max_gap_seconds"] == pytest.approx(900.0)
        assert row["threshold_seconds"] == 600
        assert row["phase"] == "design"
        assert row["iteration"] == 1
        assert row["event_count"] == 3

    def test_gap_below_threshold_no_retry_entry(self, tmp_path: Path) -> None:
        from orchestrator.sdk_dispatch import SDKDispatcher

        runner = _StaticRunner(gap_seconds=10)  # well under 600
        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign(tmp_path),  # default 600s threshold
            sdk_runner=runner,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        retry_log = tmp_path / "retry_log.jsonl"
        if retry_log.exists():
            rows = [
                json.loads(line) for line in retry_log.read_text().splitlines() if line
            ]
            assert not any(r.get("failure_type") == "sdk_silence" for r in rows)

    def test_threshold_zero_disables_detector(self, tmp_path: Path) -> None:
        """campaign.sdk_timeouts.silence_threshold_seconds=0 opts out."""
        from orchestrator.sdk_dispatch import SDKDispatcher

        runner = _StaticRunner(gap_seconds=10000)  # huge gap
        d = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_campaign(
                tmp_path,
                sdk_timeouts={"silence_threshold_seconds": 0},
            ),
            sdk_runner=runner,
        )
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )
        retry_log = tmp_path / "retry_log.jsonl"
        if retry_log.exists():
            rows = [
                json.loads(line) for line in retry_log.read_text().splitlines() if line
            ]
            assert not any(r.get("failure_type") == "sdk_silence" for r in rows)


# ─── Schema accepts the sdk_timeouts block ────────────────────────────


class TestSdkTimeoutsSchema:
    def test_accepts_silence_threshold(self) -> None:
        import jsonschema, yaml
        SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
        campaign = {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "sdk_timeouts": {"silence_threshold_seconds": 1200},
        }
        jsonschema.validate(campaign, schema)

    def test_rejects_negative_threshold(self) -> None:
        import jsonschema, yaml
        SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        schema = yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())
        campaign = {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
            "sdk_timeouts": {"silence_threshold_seconds": -1},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, schema)
