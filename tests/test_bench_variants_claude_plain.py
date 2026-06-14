"""Tests for bench/variants/claude_plain.py — JSON parsing in isolation.

Live `claude --print` subprocess invocation is exercised by the Phase 2.6
smoke test, not here.
"""
from __future__ import annotations

import json

import pytest

from bench.variants.claude_plain import (
    DEFAULT_MODEL,
    ClaudePlainVariant,
    _parse_claude_output,
)


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


def test_parse_extracts_final_answer_and_billable_tokens():
    parsed = _parse_claude_output(_success_payload(
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
    parsed = _parse_claude_output(payload)
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
    parsed = _parse_claude_output(payload)
    assert parsed["is_error"] is True
    assert parsed["subtype"] == "error_max_turns"
    assert parsed["final_answer"] == ""


def test_parse_raises_on_malformed_json():
    with pytest.raises(json.JSONDecodeError):
        _parse_claude_output("not json at all")


def test_parse_handles_missing_usage_field():
    """Edge case: claude could emit JSON without `usage` (very early error)."""
    payload = json.dumps({
        "subtype": "error_init",
        "is_error": True,
        "result": "",
    })
    parsed = _parse_claude_output(payload)
    assert parsed["tokens_in"] == 0
    assert parsed["tokens_out"] == 0
    assert parsed["dollars"] == 0.0


def test_parse_handles_null_usage_field():
    """Edge case: explicit null in the usage field."""
    payload = json.dumps({
        "subtype": "success",
        "is_error": False,
        "result": "x",
        "total_cost_usd": 0.0,
        "usage": None,
    })
    parsed = _parse_claude_output(payload)
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
    parsed = _parse_claude_output(payload)
    assert parsed["final_answer"] == ""


def test_variant_name_is_claude_plain():
    assert ClaudePlainVariant.name == "claude_plain"


def test_default_model_is_sonnet_4_6():
    assert DEFAULT_MODEL == "claude-sonnet-4-6"
