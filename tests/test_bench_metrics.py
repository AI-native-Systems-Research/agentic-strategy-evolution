"""Tests for bench/metrics.py — Claude Code JSON parsing + LLMMeter."""
from __future__ import annotations

import json

import pytest

from bench.metrics import LLMMeter, parse_claude_json


def _success_payload(
    result: str = "ok",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost: float = 0.123,
) -> str:
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result,
        "total_cost_usd": cost,
        "num_turns": 3,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": 9999,
            "cache_read_input_tokens": 8888,
        },
    })


# --- parse_claude_json ---


def test_parse_extracts_final_answer_and_billable_tokens():
    parsed = parse_claude_json(_success_payload(
        result="The answer is 42.",
        input_tokens=100,
        output_tokens=50,
        cost=1.5,
    ))
    assert parsed["final_answer"] == "The answer is 42."
    assert parsed["tokens_in"] == 100
    assert parsed["tokens_out"] == 50
    assert parsed["dollars"] == 1.5
    assert parsed["is_error"] is False
    assert parsed["subtype"] == "success"
    assert parsed["num_turns"] == 3


def test_parse_excludes_cache_fields_from_tokens_in():
    """Mirror of the Phase 1.7.1 fix: cache reads/writes are billed differently
    and would unfairly inflate tokens_in for variants that benefit from
    caching."""
    payload = json.dumps({
        "subtype": "success",
        "is_error": False,
        "result": "x",
        "total_cost_usd": 0.5,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_creation_input_tokens": 50000,
            "cache_read_input_tokens": 100000,
        },
    })
    parsed = parse_claude_json(payload)
    assert parsed["tokens_in"] == 10
    assert parsed["tokens_out"] == 5


def test_parse_handles_error_subtype():
    payload = json.dumps({
        "subtype": "error_max_turns",
        "is_error": True,
        "result": "",
        "total_cost_usd": 0.0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    })
    parsed = parse_claude_json(payload)
    assert parsed["is_error"] is True
    assert parsed["subtype"] == "error_max_turns"
    assert parsed["final_answer"] == ""


def test_parse_raises_on_malformed_json():
    with pytest.raises(json.JSONDecodeError):
        parse_claude_json("not json at all")


def test_parse_handles_missing_usage_field():
    """Edge case: claude could emit JSON without `usage` (very early error)."""
    payload = json.dumps({
        "subtype": "error_init",
        "is_error": True,
        "result": "",
    })
    parsed = parse_claude_json(payload)
    assert parsed["tokens_in"] == 0
    assert parsed["tokens_out"] == 0
    assert parsed["dollars"] == 0.0


def test_parse_handles_null_usage_field():
    payload = json.dumps({
        "subtype": "success",
        "is_error": False,
        "result": "x",
        "total_cost_usd": 0.0,
        "usage": None,
    })
    parsed = parse_claude_json(payload)
    assert parsed["tokens_in"] == 0
    assert parsed["tokens_out"] == 0


def test_parse_coerces_null_result_to_empty_string():
    payload = json.dumps({
        "subtype": "success",
        "is_error": False,
        "result": None,
        "total_cost_usd": 0.0,
        "usage": {},
    })
    parsed = parse_claude_json(payload)
    assert parsed["final_answer"] == ""


# --- LLMMeter ---


def test_meter_starts_at_zero():
    meter = LLMMeter()
    assert (meter.tokens_in, meter.tokens_out, meter.dollars) == (0, 0, 0.0)


def test_meter_add_accumulates_across_calls():
    meter = LLMMeter()
    meter.add({"tokens_in": 100, "tokens_out": 20, "dollars": 0.5})
    meter.add({"tokens_in": 50, "tokens_out": 10, "dollars": 0.25})
    assert meter.tokens_in == 150
    assert meter.tokens_out == 30
    assert meter.dollars == pytest.approx(0.75)


def test_meter_add_handles_missing_keys():
    """A parsed dict that's missing one of the metric fields shouldn't crash."""
    meter = LLMMeter()
    meter.add({"tokens_in": 5})
    assert meter.tokens_in == 5
    assert meter.tokens_out == 0
    assert meter.dollars == 0.0


def test_meter_record_claude_output_parses_and_accumulates():
    meter = LLMMeter()
    parsed = meter.record_claude_output(_success_payload(
        input_tokens=80, output_tokens=40, cost=0.9,
    ))
    assert parsed["tokens_in"] == 80
    assert meter.tokens_in == 80
    assert meter.tokens_out == 40
    assert meter.dollars == pytest.approx(0.9)


def test_meter_record_across_multiple_claude_outputs():
    """The pattern future loop variants will use: one meter, many calls."""
    meter = LLMMeter()
    meter.record_claude_output(_success_payload(input_tokens=100, output_tokens=50, cost=1.0))
    meter.record_claude_output(_success_payload(input_tokens=200, output_tokens=75, cost=2.0))
    meter.record_claude_output(_success_payload(input_tokens=50, output_tokens=10, cost=0.5))

    assert meter.tokens_in == 350
    assert meter.tokens_out == 135
    assert meter.dollars == pytest.approx(3.5)
