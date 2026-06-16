"""Tests for bench/variants/claude_plain.py — variant class.

JSON parsing is tested in test_bench_metrics.py (LLMMeter and parse_claude_json).
Live `claude --print` subprocess invocation is exercised by the Phase 2.6
smoke test, not here.
"""
from __future__ import annotations

from bench.variants.claude_plain import DEFAULT_MODEL, ClaudePlainVariant


def test_variant_name_is_claude_plain():
    assert ClaudePlainVariant.name == "claude_plain"


def test_default_model_is_sonnet_4_6():
    assert DEFAULT_MODEL == "claude-sonnet-4-6"
