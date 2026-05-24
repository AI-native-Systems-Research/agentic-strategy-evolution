"""Behavioral tests for the cache-stats aggregation (#122).

The aggregation reads ``llm_metrics.jsonl`` and produces a hit-rate
summary that drives ``nous cost --cache-stats``. Tests synthesize
realistic metrics rows on disk and assert on the returned numbers —
never on which iteration order the function used or how it organized
the by-phase grouping internally.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.cache_stats import cache_stats, format_cache_stats


def _write_metrics(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


# ─── No data ────────────────────────────────────────────────────────────────

class TestEmpty:

    def test_missing_file_returns_zeroed_summary(self, tmp_path):
        out = cache_stats(tmp_path / "no-such.jsonl")
        assert out["total_calls"] == 0
        assert out["hit_rate"] == 0.0

    def test_empty_file_returns_zeroed_summary(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        path.write_text("")
        assert cache_stats(path)["total_calls"] == 0


# ─── Hit-rate math ──────────────────────────────────────────────────────────

class TestHitRate:

    def test_first_call_is_all_creation_then_read_dominates(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        _write_metrics(path, [
            # Call 1: cold — pays creation, no read.
            {
                "phase": "design",
                "input_tokens": 50,
                "cache_creation_input_tokens": 1500,
                "cache_read_input_tokens": 0,
            },
            # Call 2: warm — read dominates.
            {
                "phase": "design",
                "input_tokens": 70,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1500,
            },
        ])

        out = cache_stats(path)
        assert out["total_calls"] == 2
        assert out["cache_creation_input_tokens"] == 1500
        assert out["cache_read_input_tokens"] == 1500
        assert out["input_tokens_uncached"] == 120

        # hit_rate = read / (uncached + creation + read) = 1500 / 3120 ≈ 0.4808.
        assert 0.48 <= out["hit_rate"] <= 0.49

    def test_zero_total_returns_zero_hit_rate_no_division_error(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        _write_metrics(path, [{"phase": "design"}])  # all token fields 0

        out = cache_stats(path)
        assert out["hit_rate"] == 0.0


# ─── Per-phase breakdown ───────────────────────────────────────────────────

class TestByPhase:

    def test_separate_phase_buckets(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        _write_metrics(path, [
            {"phase": "design", "input_tokens": 100, "cache_read_input_tokens": 200},
            {"phase": "design", "input_tokens": 100, "cache_read_input_tokens": 200},
            {"phase": "execute-analyze", "input_tokens": 1000, "cache_read_input_tokens": 0},
        ])

        out = cache_stats(path)
        assert "design" in out["by_phase"]
        assert "execute-analyze" in out["by_phase"]
        assert out["by_phase"]["design"]["calls"] == 2
        assert out["by_phase"]["execute-analyze"]["calls"] == 1
        # design has cache reads, execute-analyze does not.
        assert out["by_phase"]["design"]["hit_rate"] > 0
        assert out["by_phase"]["execute-analyze"]["hit_rate"] == 0.0


# ─── Robustness ─────────────────────────────────────────────────────────────

class TestRobustness:

    def test_corrupt_lines_are_skipped(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        path.write_text(
            json.dumps({"phase": "design", "input_tokens": 10}) + "\n"
            "this is not json\n"
            + json.dumps({"phase": "design", "input_tokens": 5}) + "\n"
        )
        out = cache_stats(path)
        assert out["total_calls"] == 2
        assert out["input_tokens_uncached"] == 15

    def test_missing_token_fields_treated_as_zero(self, tmp_path):
        path = tmp_path / "metrics.jsonl"
        _write_metrics(path, [{"phase": "design"}, {"phase": "design"}])

        out = cache_stats(path)
        assert out["total_calls"] == 2
        assert out["cache_read_input_tokens"] == 0


# ─── Human formatting ──────────────────────────────────────────────────────

class TestFormatCacheStats:

    def test_format_includes_hit_rate_and_phase_breakdown(self):
        stats = {
            "total_calls": 3,
            "input_tokens_uncached": 100,
            "cache_creation_input_tokens": 1500,
            "cache_read_input_tokens": 3000,
            "hit_rate": 0.65,
            "by_phase": {
                "design": {
                    "calls": 2,
                    "input_tokens_uncached": 50,
                    "cache_creation_input_tokens": 1500,
                    "cache_read_input_tokens": 3000,
                    "hit_rate": 0.66,
                },
            },
        }
        text = format_cache_stats(stats)
        assert "Hit rate:" in text
        assert "65.0%" in text or "65%" in text
        assert "design" in text
