"""Tests for orchestrator/v2/cost.py — transcript cost meter."""

from __future__ import annotations

import pytest
from pathlib import Path

from tests.fakes.sdk_client import FakeAssistantMessage, FakeResultMessage


PRICES = {
    "claude-opus-4-6": {"input_tokens": 15.0, "output_tokens": 75.0},
    "claude-sonnet-4-6": {"input_tokens": 3.0, "output_tokens": 15.0},
    "claude-haiku-4-5": {"input_tokens": 0.80, "output_tokens": 4.0},
}


class TestCostMeter:
    def test_known_total_from_fixture(self):
        """A fixture transcript of 3 messages reproduces a known cost."""
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        meter.set_phase("BASELINE")

        # opus: 1000 input @ $15/M + 500 output @ $75/M = $0.015 + $0.0375 = $0.0525
        meter.record(FakeAssistantMessage(
            message_id="msg-1", model="claude-opus-4-6",
            usage={"input_tokens": 1000, "output_tokens": 500},
        ))
        # sonnet: 2000 input @ $3/M + 1000 output @ $15/M = $0.006 + $0.015 = $0.021
        meter.record(FakeAssistantMessage(
            message_id="msg-2", model="claude-sonnet-4-6",
            usage={"input_tokens": 2000, "output_tokens": 1000},
        ))
        # haiku: 5000 input @ $0.80/M + 2000 output @ $4/M = $0.004 + $0.008 = $0.012
        meter.record(FakeAssistantMessage(
            message_id="msg-3", model="claude-haiku-4-5",
            usage={"input_tokens": 5000, "output_tokens": 2000},
        ))

        total = meter.total()
        assert total["input_tokens"] == 8000
        assert total["output_tokens"] == 3500
        assert abs(total["cost_usd"] - 0.0855) < 1e-9

    def test_duplicate_message_id_counted_once(self):
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        msg = FakeAssistantMessage(
            message_id="msg-dup", model="claude-opus-4-6",
            usage={"input_tokens": 1000, "output_tokens": 500},
        )
        meter.record(msg)
        meter.record(msg)
        meter.record(msg)

        total = meter.total()
        assert total["input_tokens"] == 1000
        assert total["output_tokens"] == 500

    def test_unknown_model_costs_zero(self):
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        meter.record(FakeAssistantMessage(
            message_id="msg-unknown", model="gpt-99-turbo",
            usage={"input_tokens": 10000, "output_tokens": 5000},
        ))

        total = meter.total()
        assert total["input_tokens"] == 10000
        assert total["output_tokens"] == 5000
        assert total["cost_usd"] == 0.0

    def test_phase_tracking(self):
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)

        meter.set_phase("BASELINE")
        meter.record(FakeAssistantMessage(
            message_id="msg-b1", model="claude-opus-4-6",
            usage={"input_tokens": 1000, "output_tokens": 200},
        ))

        meter.set_phase("DESIGN")
        meter.record(FakeAssistantMessage(
            message_id="msg-d1", model="claude-opus-4-6",
            usage={"input_tokens": 2000, "output_tokens": 400},
        ))
        meter.record(FakeAssistantMessage(
            message_id="msg-d2", model="claude-opus-4-6",
            usage={"input_tokens": 3000, "output_tokens": 600},
        ))

        baseline = meter.phase_summary("BASELINE")
        assert baseline["input_tokens"] == 1000
        assert baseline["output_tokens"] == 200

        design = meter.phase_summary("DESIGN")
        assert design["input_tokens"] == 5000
        assert design["output_tokens"] == 1000

        total = meter.total()
        assert total["input_tokens"] == 6000
        assert total["output_tokens"] == 1200

    def test_empty_phase_summary(self):
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        s = meter.phase_summary("EXECUTE")
        assert s == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def test_message_without_usage_skipped(self):
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        msg = FakeAssistantMessage(message_id="msg-no-usage", model="claude-opus-4-6")
        msg.usage = {}
        meter.record(msg)
        total = meter.total()
        assert total["input_tokens"] == 0
        assert total["output_tokens"] == 0

    def test_result_message_not_double_counted(self):
        """ResultMessage usage is a session total that repeats the assistant messages; not counted."""
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        # ResultMessage has no model and repeats per-message usage: skipped
        result = FakeResultMessage(
            usage={"input_tokens": 500, "output_tokens": 100},
        )
        meter.record(result)
        meter.record(result)

        total = meter.total()
        assert total["input_tokens"] == 0
        assert total["output_tokens"] == 0

    def test_subagent_messages_included(self):
        """Messages with parent_tool_use_id (subagent) are counted normally."""
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        meter.record(FakeAssistantMessage(
            message_id="msg-main", model="claude-opus-4-6",
            usage={"input_tokens": 1000, "output_tokens": 500},
        ))
        meter.record(FakeAssistantMessage(
            message_id="msg-sub", model="claude-opus-4-6",
            usage={"input_tokens": 800, "output_tokens": 300},
            parent_tool_use_id="tu-agent-1",
        ))

        total = meter.total()
        assert total["input_tokens"] == 1800
        assert total["output_tokens"] == 800


class TestLoadPrices:
    def test_load_from_defaults(self):
        from orchestrator.v2.cost import load_prices

        defaults_path = Path(__file__).resolve().parents[2] / "orchestrator" / "defaults.yaml"
        prices = load_prices(defaults_path)
        assert "claude-opus-4-6" in prices
        assert "input_tokens" in prices["claude-opus-4-6"]
        assert "output_tokens" in prices["claude-opus-4-6"]
        assert prices["claude-opus-4-6"]["input_tokens"] == 15.0

    def test_missing_file_returns_empty(self, tmp_path):
        from orchestrator.v2.cost import load_prices

        prices = load_prices(tmp_path / "nonexistent.yaml")
        assert prices == {}

    def test_no_prices_key_returns_empty(self, tmp_path):
        from orchestrator.v2.cost import load_prices

        f = tmp_path / "defaults.yaml"
        f.write_text("models:\n  design: opus\n")
        prices = load_prices(f)
        assert prices == {}


class TestCacheAndResult:
    def test_cache_tokens_priced(self):
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        # opus input $15/M: cache read 0.1x, cache write 1.25x
        meter.record(FakeAssistantMessage(
            message_id="msg-c", model="claude-opus-4-6",
            usage={"input_tokens": 0, "output_tokens": 0,
                   "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 1000},
        ))
        assert abs(meter.total()["cost_usd"] - (0.0015 + 0.01875)) < 1e-9

    def test_result_message_usage_not_added_to_assistant_usage(self):
        from orchestrator.v2.cost import CostMeter

        meter = CostMeter(PRICES)
        meter.record(FakeAssistantMessage(
            message_id="msg-a", model="claude-opus-4-6",
            usage={"input_tokens": 1000, "output_tokens": 500},
        ))
        meter.record(FakeResultMessage(usage={"input_tokens": 1000, "output_tokens": 500}))
        assert meter.total()["input_tokens"] == 1000
        assert meter.total()["output_tokens"] == 500
