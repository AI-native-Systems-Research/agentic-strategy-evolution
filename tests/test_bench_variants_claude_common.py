"""Tests for bench/variants/_claude_common.py — shared helpers.

invoke_claude tests patch `bench.variants._claude_common.subprocess.run`.
variant_result_from tests construct ClaudeRunResult objects directly.

Live `claude --print` is exercised by the Phase 4 smoke run, not here.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bench.variants._claude_common import (
    DEFAULT_MODEL,
    ClaudeInvocation,
    ClaudeRunResult,
    invoke_claude,
    variant_result_from,
)
from bench.variants.base import Budget


def _budget(max_tokens: int = 200_000, max_wall_seconds: int = 1800) -> Budget:
    return Budget(
        max_tokens=max_tokens,
        max_iterations=3,
        max_wall_seconds=max_wall_seconds,
    )


def _success_payload(
    result: str = "ok",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost: float = 0.123,
) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result,
            "total_cost_usd": cost,
            "num_turns": 3,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }
    )


def _fake_run_factory(stdout: str = "", stderr: str = "", returncode: int = 0):
    def _fake(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout=stdout, stderr=stderr
        )
    return _fake


# --- invoke_claude ---


def test_invoke_claude_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bench.variants._claude_common.subprocess.run",
        _fake_run_factory(stdout=_success_payload(
            result="42", input_tokens=10, output_tokens=5, cost=0.5
        )),
    )
    inv = ClaudeInvocation(
        question="what is 6*7?",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
    )
    result = invoke_claude(inv)

    assert result.crashed is False
    assert result.error is None
    assert result.final_answer == "42"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.dollars == 0.5
    assert result.wall_seconds >= 0
    assert (tmp_path / "log").exists()


def test_invoke_claude_threads_system_prompt(monkeypatch, tmp_path):
    captured: dict = {}

    def _fake(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=_success_payload(), stderr=""
        )

    monkeypatch.setattr("bench.variants._claude_common.subprocess.run", _fake)
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
        system_prompt="be a scientist",
    )
    invoke_claude(inv)

    assert "--append-system-prompt" in captured["cmd"]
    idx = captured["cmd"].index("--append-system-prompt")
    assert captured["cmd"][idx + 1] == "be a scientist"


def test_invoke_claude_omits_system_prompt_when_none(monkeypatch, tmp_path):
    captured: dict = {}

    def _fake(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=_success_payload(), stderr=""
        )

    monkeypatch.setattr("bench.variants._claude_common.subprocess.run", _fake)
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
    )
    invoke_claude(inv)

    assert "--append-system-prompt" not in captured["cmd"]


def test_invoke_claude_crashes_on_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bench.variants._claude_common.subprocess.run",
        _fake_run_factory(stdout="", stderr="oops", returncode=1),
    )
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
    )
    result = invoke_claude(inv)

    assert result.crashed is True
    assert "exited with code 1" in result.error
    assert "oops" in result.error


def test_invoke_claude_crashes_on_malformed_json(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bench.variants._claude_common.subprocess.run",
        _fake_run_factory(stdout="not json"),
    )
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
    )
    result = invoke_claude(inv)

    assert result.crashed is True
    assert "malformed claude json output" in result.error


def test_invoke_claude_crashes_on_is_error_in_response(monkeypatch, tmp_path):
    payload = json.dumps(
        {
            "subtype": "error_max_turns",
            "is_error": True,
            "result": "",
            "total_cost_usd": 0.0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
    )
    monkeypatch.setattr(
        "bench.variants._claude_common.subprocess.run",
        _fake_run_factory(stdout=payload),
    )
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
    )
    result = invoke_claude(inv)

    assert result.crashed is True
    assert "error_max_turns" in result.error


def test_invoke_claude_crashes_on_timeout(monkeypatch, tmp_path):
    def _fake(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1800)

    monkeypatch.setattr("bench.variants._claude_common.subprocess.run", _fake)
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(max_wall_seconds=1800),
        log_path=tmp_path / "log",
    )
    result = invoke_claude(inv)

    assert result.crashed is True
    assert "timeout after 1800s" in result.error


def test_invoke_claude_crashes_when_cli_missing(monkeypatch, tmp_path):
    def _fake(cmd, **kwargs):
        raise FileNotFoundError("[Errno 2] no claude")

    monkeypatch.setattr("bench.variants._claude_common.subprocess.run", _fake)
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
    )
    result = invoke_claude(inv)

    assert result.crashed is True
    assert "claude CLI not found on PATH" in result.error


def test_invoke_claude_uses_default_model_when_unspecified(monkeypatch, tmp_path):
    captured: dict = {}

    def _fake(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=_success_payload(), stderr=""
        )

    monkeypatch.setattr("bench.variants._claude_common.subprocess.run", _fake)
    # Make sure no env override leaks in from parent test runs
    monkeypatch.delenv("BENCH_VARIANT_MODEL", raising=False)
    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
    )
    invoke_claude(inv)

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == DEFAULT_MODEL


def test_bench_variant_model_env_var_overrides_invocation_model(monkeypatch, tmp_path):
    """When BENCH_VARIANT_MODEL is set, it overrides whatever model the
    Invocation specifies. This is how --variant-model gets propagated to
    subprocess calls without changing every variant call site."""
    captured: dict = {}

    def _fake(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=_success_payload(), stderr=""
        )

    monkeypatch.setattr("bench.variants._claude_common.subprocess.run", _fake)
    monkeypatch.setenv("BENCH_VARIANT_MODEL", "claude-opus-4-7")

    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
        # Even with an explicit model on the Invocation, env var wins
        model="claude-sonnet-4-6",
    )
    invoke_claude(inv)

    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "claude-opus-4-7"


def test_bench_variant_model_env_var_unset_uses_invocation_model(monkeypatch, tmp_path):
    """When BENCH_VARIANT_MODEL is unset, the Invocation's model field is
    used (which itself defaults to DEFAULT_MODEL)."""
    captured: dict = {}

    def _fake(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=_success_payload(), stderr=""
        )

    monkeypatch.setattr("bench.variants._claude_common.subprocess.run", _fake)
    monkeypatch.delenv("BENCH_VARIANT_MODEL", raising=False)

    inv = ClaudeInvocation(
        question="q",
        workspace=tmp_path,
        budget=_budget(),
        log_path=tmp_path / "log",
        model="claude-haiku-4-5",
    )
    invoke_claude(inv)

    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "claude-haiku-4-5"


# --- variant_result_from ---


def _run(
    final_answer: str = "ok",
    tokens_in: int = 10,
    tokens_out: int = 5,
    dollars: float = 0.1,
    wall: float = 1.0,
    crashed: bool = False,
    error: str | None = None,
    log_path: Path | None = None,
) -> ClaudeRunResult:
    return ClaudeRunResult(
        final_answer=final_answer,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        dollars=dollars,
        wall_seconds=wall,
        crashed=crashed,
        error=error,
        log_path=log_path or Path("/tmp/log"),
    )


def test_variant_result_from_single_run_passes_through(tmp_path):
    log_path = tmp_path / "claude.log"
    log_path.write_text("hello")
    runs = [_run(
        final_answer="hi", tokens_in=100, tokens_out=50, dollars=0.5,
        log_path=log_path,
    )]

    result = variant_result_from(
        runs, variant_name="claude_plain", campaign_id="c1",
        workspace=tmp_path, budget=_budget(),
    )

    assert result.variant == "claude_plain"
    assert result.campaign_id == "c1"
    assert result.tokens_in == 100
    assert result.tokens_out == 50
    assert result.dollars == 0.5
    assert result.final_answer == "hi"
    assert result.crashed is False
    assert result.raw_log_path == log_path


def test_variant_result_from_multi_run_sums_metrics(tmp_path):
    log1 = tmp_path / "iter-1.log"
    log1.write_text("iter1 content")
    log2 = tmp_path / "iter-2.log"
    log2.write_text("iter2 content")
    runs = [
        _run(tokens_in=100, tokens_out=50, dollars=0.5, wall=10.0, log_path=log1),
        _run(tokens_in=200, tokens_out=75, dollars=1.0, wall=15.0, log_path=log2),
    ]

    result = variant_result_from(
        runs, variant_name="claude_loop", campaign_id="c1",
        workspace=tmp_path, budget=_budget(),
    )

    assert result.tokens_in == 300
    assert result.tokens_out == 125
    assert result.dollars == pytest.approx(1.5)
    assert result.wall_seconds == pytest.approx(25.0)


def test_variant_result_from_multi_run_concatenates_logs(tmp_path):
    log1 = tmp_path / "iter-1.log"
    log1.write_text("iter1 content")
    log2 = tmp_path / "iter-2.log"
    log2.write_text("iter2 content")
    runs = [_run(log_path=log1), _run(log_path=log2)]

    result = variant_result_from(
        runs, variant_name="claude_loop", campaign_id="c1",
        workspace=tmp_path, budget=_budget(),
    )

    expected_combined = tmp_path / ".bench-claude_loop.log"
    assert result.raw_log_path == expected_combined
    contents = expected_combined.read_text()
    assert "=== iter-1 ===" in contents
    assert "iter1 content" in contents
    assert "=== iter-2 ===" in contents
    assert "iter2 content" in contents


def test_variant_result_from_takes_last_non_crashed_answer(tmp_path):
    runs = [
        _run(final_answer="first answer"),
        _run(final_answer="second answer"),
        _run(final_answer="", crashed=True, error="boom"),
    ]

    result = variant_result_from(
        runs, variant_name="claude_loop", campaign_id="c1",
        workspace=tmp_path, budget=_budget(),
    )

    assert result.final_answer == "second answer"
    assert result.crashed is True
    assert result.error == "boom"


def test_variant_result_from_marks_crashed_if_any_run_crashed(tmp_path):
    runs = [
        _run(crashed=False),
        _run(crashed=True, error="iter-2 boom"),
        _run(crashed=False),
    ]

    result = variant_result_from(
        runs, variant_name="claude_loop", campaign_id="c1",
        workspace=tmp_path, budget=_budget(),
    )

    assert result.crashed is True
    assert result.error == "iter-2 boom"


def test_variant_result_from_falls_back_to_last_when_all_crashed(tmp_path):
    runs = [
        _run(final_answer="", crashed=True, error="iter-1 boom"),
        _run(final_answer="", crashed=True, error="iter-2 boom"),
    ]

    result = variant_result_from(
        runs, variant_name="claude_loop", campaign_id="c1",
        workspace=tmp_path, budget=_budget(),
    )

    assert result.final_answer == ""
    assert result.crashed is True
    assert result.error == "iter-1 boom"


def test_variant_result_from_hit_cap_on_summed_totals(tmp_path):
    runs = [
        _run(tokens_in=80_000, tokens_out=20_000),
        _run(tokens_in=80_000, tokens_out=30_000),
    ]
    result = variant_result_from(
        runs, variant_name="claude_loop", campaign_id="c1",
        workspace=tmp_path, budget=_budget(max_tokens=200_000),
    )
    assert result.hit_cap is True


def test_variant_result_from_no_hit_cap_when_under(tmp_path):
    runs = [_run(tokens_in=10, tokens_out=5)]
    result = variant_result_from(
        runs, variant_name="claude_plain", campaign_id="c1",
        workspace=tmp_path, budget=_budget(max_tokens=200_000),
    )
    assert result.hit_cap is False


def test_variant_result_from_workspace_is_artifacts_dir(tmp_path):
    runs = [_run()]
    result = variant_result_from(
        runs, variant_name="claude_plain", campaign_id="c1",
        workspace=tmp_path, budget=_budget(),
    )
    assert result.artifacts_dir == tmp_path
