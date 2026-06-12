"""Tests for load_llm_metrics in scripts/visualize_campaign.py."""
import json
import sys
from pathlib import Path

import pytest

# scripts/ has no __init__.py; add to path for import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from visualize_campaign import load_llm_metrics


def _write_metrics(path, entries):
    with open(path / "llm_metrics.jsonl", "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestNormalCase:
    """Normal campaign with 1 design + 1 execute per iteration."""

    def test_three_iterations_no_retries(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
            {"iteration": 2, "timestamp": "2026-01-01T02:00:00+00:00", "h_main_result": "REFUTED"},
            {"iteration": 3, "timestamp": "2026-01-01T03:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 1000, "output_tokens": 200},
            {"timestamp": "2026-01-01T00:50:00+00:00", "role": "executor", "cost_usd": 2.0, "duration_ms": 8000, "num_turns": 3, "input_tokens": 2000, "output_tokens": 500},
            {"timestamp": "2026-01-01T01:30:00+00:00", "role": "planner", "cost_usd": 1.5, "duration_ms": 6000, "num_turns": 2, "input_tokens": 1100, "output_tokens": 210},
            {"timestamp": "2026-01-01T01:50:00+00:00", "role": "executor", "cost_usd": 2.5, "duration_ms": 9000, "num_turns": 4, "input_tokens": 2200, "output_tokens": 600},
            {"timestamp": "2026-01-01T02:30:00+00:00", "role": "planner", "cost_usd": 1.2, "duration_ms": 7000, "num_turns": 2, "input_tokens": 1200, "output_tokens": 220},
            {"timestamp": "2026-01-01T02:50:00+00:00", "role": "executor", "cost_usd": 2.8, "duration_ms": 10000, "num_turns": 5, "input_tokens": 2400, "output_tokens": 700},
        ])
        result = load_llm_metrics(tmp_path, ledger)

        assert set(result.keys()) == {"iter-1", "iter-2", "iter-3"}
        assert result["iter-1"]["design"]["cost_usd"] == 1.0
        assert result["iter-1"]["execute"]["cost_usd"] == 2.0
        assert result["iter-1"]["total_cost"] == 3.0
        assert result["iter-2"]["total_cost"] == 4.0
        assert result["iter-3"]["total_cost"] == 4.0

    def test_total_cost_matches_sum_of_entries(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:20:00+00:00", "role": "planner", "cost_usd": 3.5, "duration_ms": 5000, "num_turns": 2, "input_tokens": 1000, "output_tokens": 200},
            {"timestamp": "2026-01-01T00:40:00+00:00", "role": "executor", "cost_usd": 4.5, "duration_ms": 8000, "num_turns": 3, "input_tokens": 2000, "output_tokens": 500},
        ])
        result = load_llm_metrics(tmp_path, ledger)
        assert result["iter-1"]["total_cost"] == pytest.approx(8.0)


class TestRetries:
    """Campaigns with retries produce multiple entries per phase per iteration."""

    def test_multiple_design_retries_summed(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:10:00+00:00", "role": "planner", "cost_usd": 2.0, "duration_ms": 5000, "num_turns": 10, "input_tokens": 1000, "output_tokens": 200},
            {"timestamp": "2026-01-01T00:20:00+00:00", "role": "planner", "cost_usd": 2.0, "duration_ms": 5000, "num_turns": 10, "input_tokens": 1000, "output_tokens": 200},
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 2.0, "duration_ms": 5000, "num_turns": 10, "input_tokens": 1000, "output_tokens": 200},
            {"timestamp": "2026-01-01T00:45:00+00:00", "role": "executor", "cost_usd": 3.0, "duration_ms": 8000, "num_turns": 5, "input_tokens": 2000, "output_tokens": 500},
        ])
        result = load_llm_metrics(tmp_path, ledger)

        assert result["iter-1"]["design"]["cost_usd"] == 6.0
        assert result["iter-1"]["design"]["num_turns"] == 30
        assert result["iter-1"]["design"]["duration_ms"] == 15000
        assert result["iter-1"]["execute"]["cost_usd"] == 3.0
        assert result["iter-1"]["total_cost"] == 9.0

    def test_retries_dont_bleed_into_next_iteration(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
            {"iteration": 2, "timestamp": "2026-01-01T02:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            # 3 retries for iter-1 design, all before iter-1's boundary
            {"timestamp": "2026-01-01T00:10:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 3000, "num_turns": 5, "input_tokens": 500, "output_tokens": 100},
            {"timestamp": "2026-01-01T00:20:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 3000, "num_turns": 5, "input_tokens": 500, "output_tokens": 100},
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 3000, "num_turns": 5, "input_tokens": 500, "output_tokens": 100},
            {"timestamp": "2026-01-01T00:50:00+00:00", "role": "executor", "cost_usd": 2.0, "duration_ms": 8000, "num_turns": 3, "input_tokens": 2000, "output_tokens": 500},
            # iter-2: single design + execute
            {"timestamp": "2026-01-01T01:30:00+00:00", "role": "planner", "cost_usd": 1.5, "duration_ms": 4000, "num_turns": 6, "input_tokens": 600, "output_tokens": 120},
            {"timestamp": "2026-01-01T01:50:00+00:00", "role": "executor", "cost_usd": 2.5, "duration_ms": 9000, "num_turns": 4, "input_tokens": 2200, "output_tokens": 600},
        ])
        result = load_llm_metrics(tmp_path, ledger)

        # iter-1 gets all 3 retries + executor
        assert result["iter-1"]["design"]["cost_usd"] == 3.0
        assert result["iter-1"]["total_cost"] == 5.0
        # iter-2 is clean
        assert result["iter-2"]["design"]["cost_usd"] == 1.5
        assert result["iter-2"]["total_cost"] == 4.0


class TestFailedIterations:
    """FAILED iterations should act as time boundaries for cost attribution."""

    def test_failed_iter_captures_own_costs(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
            {"iteration": 2, "timestamp": "2026-01-01T02:00:00+00:00", "h_main_result": None, "status": "FAILED", "error": "Broken pipe"},
            {"iteration": 3, "timestamp": "2026-01-01T03:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
            {"timestamp": "2026-01-01T00:50:00+00:00", "role": "executor", "cost_usd": 2.0, "duration_ms": 8000, "num_turns": 3, "input_tokens": 1000, "output_tokens": 200},
            # These belong to the FAILED iter-2
            {"timestamp": "2026-01-01T01:30:00+00:00", "role": "planner", "cost_usd": 3.0, "duration_ms": 7000, "num_turns": 4, "input_tokens": 800, "output_tokens": 150},
            {"timestamp": "2026-01-01T01:50:00+00:00", "role": "executor", "cost_usd": 1.5, "duration_ms": 6000, "num_turns": 2, "input_tokens": 700, "output_tokens": 130},
            # These belong to iter-3
            {"timestamp": "2026-01-01T02:30:00+00:00", "role": "planner", "cost_usd": 1.2, "duration_ms": 5500, "num_turns": 2, "input_tokens": 550, "output_tokens": 110},
            {"timestamp": "2026-01-01T02:50:00+00:00", "role": "executor", "cost_usd": 2.2, "duration_ms": 8500, "num_turns": 3, "input_tokens": 1100, "output_tokens": 220},
        ])
        result = load_llm_metrics(tmp_path, ledger)

        # FAILED iter-2 captures its own costs, doesn't leak into iter-1 or iter-3
        assert "iter-2" in result
        assert result["iter-2"]["design"]["cost_usd"] == 3.0
        assert result["iter-2"]["execute"]["cost_usd"] == 1.5
        assert result["iter-2"]["total_cost"] == 4.5
        # iter-1 and iter-3 are unaffected
        assert result["iter-1"]["total_cost"] == 3.0
        assert result["iter-3"]["total_cost"] == pytest.approx(3.4)

    def test_consecutive_failures_each_capture_own_costs(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
            {"iteration": 2, "timestamp": "2026-01-01T02:00:00+00:00", "h_main_result": None, "status": "FAILED"},
            {"iteration": 3, "timestamp": "2026-01-01T03:00:00+00:00", "h_main_result": None, "status": "FAILED"},
            {"iteration": 4, "timestamp": "2026-01-01T04:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
            {"timestamp": "2026-01-01T01:30:00+00:00", "role": "planner", "cost_usd": 2.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
            {"timestamp": "2026-01-01T02:30:00+00:00", "role": "planner", "cost_usd": 3.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
            {"timestamp": "2026-01-01T03:30:00+00:00", "role": "planner", "cost_usd": 4.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
        ])
        result = load_llm_metrics(tmp_path, ledger)

        assert result["iter-1"]["total_cost"] == 1.0
        assert result["iter-2"]["total_cost"] == 2.0
        assert result["iter-3"]["total_cost"] == 3.0
        assert result["iter-4"]["total_cost"] == 4.0


class TestTimezoneHandling:
    """Naive and aware timestamps must compare without raising TypeError."""

    def test_naive_entry_vs_aware_boundary(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        # Entry timestamp has NO timezone offset
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00", "role": "planner", "cost_usd": 5.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 1000, "output_tokens": 200},
        ])
        result = load_llm_metrics(tmp_path, ledger)

        assert "iter-1" in result
        assert result["iter-1"]["design"]["cost_usd"] == 5.0

    def test_aware_entry_vs_naive_boundary(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            # Boundary has no explicit timezone
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "executor", "cost_usd": 7.0, "duration_ms": 8000, "num_turns": 3, "input_tokens": 2000, "output_tokens": 500},
        ])
        result = load_llm_metrics(tmp_path, ledger)

        assert "iter-1" in result
        assert result["iter-1"]["execute"]["cost_usd"] == 7.0


class TestEdgeCases:
    """Empty inputs, corrupt data, and boundary conditions."""

    def test_missing_metrics_file_returns_empty(self, tmp_path):
        ledger = {"iterations": [{"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"}]}
        assert load_llm_metrics(tmp_path, ledger) == {}

    def test_empty_metrics_file_returns_empty(self, tmp_path):
        (tmp_path / "llm_metrics.jsonl").write_text("")
        ledger = {"iterations": [{"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"}]}
        assert load_llm_metrics(tmp_path, ledger) == {}

    def test_only_baseline_returns_empty(self, tmp_path):
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
        ])
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
        ]}
        assert load_llm_metrics(tmp_path, ledger) == {}

    def test_corrupt_jsonl_line_skipped(self, tmp_path):
        (tmp_path / "llm_metrics.jsonl").write_text(
            '{"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 5.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 1000, "output_tokens": 200}\n'
            '{this is not valid json\n'
            '{"timestamp": "2026-01-01T00:50:00+00:00", "role": "executor", "cost_usd": 3.0, "duration_ms": 8000, "num_turns": 3, "input_tokens": 2000, "output_tokens": 500}\n'
        )
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        result = load_llm_metrics(tmp_path, ledger)
        assert result["iter-1"]["design"]["cost_usd"] == 5.0
        assert result["iter-1"]["execute"]["cost_usd"] == 3.0

    def test_entry_after_last_boundary_assigned_to_last(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T05:00:00+00:00", "role": "executor", "cost_usd": 10.0, "duration_ms": 8000, "num_turns": 3, "input_tokens": 2000, "output_tokens": 500},
        ])
        result = load_llm_metrics(tmp_path, ledger)
        assert result["iter-1"]["execute"]["cost_usd"] == 10.0

    def test_entry_with_missing_timestamp_skipped(self, tmp_path):
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 2.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
            {"role": "executor", "cost_usd": 99.0, "duration_ms": 8000, "num_turns": 3, "input_tokens": 2000, "output_tokens": 500},
        ])
        result = load_llm_metrics(tmp_path, ledger)
        # Entry without timestamp is skipped, only the planner entry counts
        assert result["iter-1"]["design"]["cost_usd"] == 2.0
        assert result["iter-1"]["execute"] is None
        assert result["iter-1"]["total_cost"] == 2.0

    def test_null_iteration_in_ledger_skipped(self, tmp_path):
        """Iteration with null value doesn't crash the filter."""
        ledger = {"iterations": [
            {"iteration": 0, "family": "baseline", "timestamp": "1970-01-01T00:00:00Z", "h_main_result": None},
            {"iteration": None, "timestamp": "2026-01-01T00:30:00+00:00"},
            {"iteration": 1, "timestamp": "2026-01-01T01:00:00+00:00", "h_main_result": "CONFIRMED"},
        ]}
        _write_metrics(tmp_path, [
            {"timestamp": "2026-01-01T00:30:00+00:00", "role": "planner", "cost_usd": 1.0, "duration_ms": 5000, "num_turns": 2, "input_tokens": 500, "output_tokens": 100},
        ])
        result = load_llm_metrics(tmp_path, ledger)
        assert "iter-1" in result
        assert result["iter-1"]["design"]["cost_usd"] == 1.0
