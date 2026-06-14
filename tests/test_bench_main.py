"""Tests for bench/__main__.py — argparse + list command."""
from __future__ import annotations

import pytest

from bench.__main__ import build_parser, main


def test_run_subcommand_parses_experiment_arg():
    parser = build_parser()
    args = parser.parse_args(["run", "exp.yaml"])
    assert args.cmd == "run"
    assert args.experiment == "exp.yaml"
    assert args.variants is None
    assert args.max_tokens is None


def test_run_subcommand_parses_all_overrides():
    parser = build_parser()
    args = parser.parse_args([
        "run", "exp.yaml",
        "--variants", "nous,claude_plain",
        "--max-tokens", "1000",
        "--max-iterations", "5",
        "--max-wall-seconds", "600",
        "--run-id", "custom_id",
    ])
    assert args.variants == "nous,claude_plain"
    assert args.max_tokens == 1000
    assert args.max_iterations == 5
    assert args.max_wall_seconds == 600
    assert args.run_id == "custom_id"


def test_list_subcommand_parses():
    parser = build_parser()
    args = parser.parse_args(["list"])
    assert args.cmd == "list"


def test_run_subcommand_requires_experiment_arg():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])


def test_main_list_prints_variants_and_campaigns(capsys):
    rc = main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Variants:" in out
    assert "nous" in out
    assert "Campaigns:" in out
    assert "blis_prefix" in out


def test_main_no_subcommand_exits_with_error():
    with pytest.raises(SystemExit):
        main([])
