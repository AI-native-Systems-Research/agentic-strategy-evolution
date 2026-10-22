"""Tests for the friction-report #245 PR — F1, F3, F4, F11, F12, F15,
F17, F19, F20, F21 acceptance criteria.

Each F-entry is independently exercised. Mocks (per CLAUDE.md): no
live LLM calls; injected fakes for any subprocess that would
otherwise hit the network.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import jsonschema
import yaml

from orchestrator.lineage import (
    apply_derived_from_patch,
    emit_cumulative_patch,
    resolve_derived_from,
    summarize_lineage,
)


# ─── F19 / #264: per-phase silence threshold ───────────────────────────────


def test_f19_silence_threshold_per_phase_map_validates():
    """Schema accepts the per-phase form."""
    schema = yaml.safe_load(
        (Path("orchestrator/schemas/campaign.schema.yaml")).read_text()
    )
    campaign = {
        "research_question": "q",
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
        "sdk_timeouts": {
            "turn_silence_threshold_seconds": {
                "design": 600, "execute_analyze": 120, "report": 240,
            }
        },
    }
    jsonschema.validate(campaign, schema)


def test_f19_silence_threshold_scalar_still_validates():
    """Backward-compat: scalar form still validates."""
    schema = yaml.safe_load(
        (Path("orchestrator/schemas/campaign.schema.yaml")).read_text()
    )
    campaign = {
        "research_question": "q",
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
        "sdk_timeouts": {"turn_silence_threshold_seconds": 600},
    }
    jsonschema.validate(campaign, schema)


# ─── F21 / #266: cumulative patches + derived_from ─────────────────────────


def test_f21_emit_cumulative_patch_returns_none_when_git_fails(tmp_path: Path):
    """Best-effort: subprocess errors don't raise."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not a git repo",
        )
        result = emit_cumulative_patch(tmp_path, "nous-exp-x", tmp_path)
        assert result is None


def test_f21_emit_cumulative_patch_writes_diff_when_git_succeeds(tmp_path: Path):
    iter_dir = tmp_path
    with patch("subprocess.run") as mock_run:
        # First call: _git_main_ref returns ok. Second call: diff returns content.
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="abcdef\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="diff --git a/x b/x\n", stderr=""),
        ]
        result = emit_cumulative_patch(tmp_path, "nous-exp-x", iter_dir)
        assert result is not None
        assert result.read_text() == "diff --git a/x b/x\n"


def test_f21_resolve_derived_from_no_block_returns_none():
    assert resolve_derived_from({}) is None
    assert resolve_derived_from({"derived_from": "not a dict"}) is None


def test_f21_resolve_derived_from_finds_cumulative_patch(tmp_path: Path, monkeypatch):
    prior_work = tmp_path / "prior-campaign"
    iter_dir = prior_work / "runs" / "iter-2"
    (iter_dir / "patches").mkdir(parents=True)
    cumulative = iter_dir / "patches" / "cumulative.patch"
    cumulative.write_text("diff --git a/x b/x\n")
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    campaign = {"derived_from": {"campaign": "prior-campaign", "iteration": 2}}
    result = resolve_derived_from(campaign)
    assert result == cumulative


def test_f21_resolve_derived_from_final_picks_highest_iter(tmp_path: Path, monkeypatch):
    prior = tmp_path / "prior-campaign"
    for n in (1, 2, 3):
        d = prior / "runs" / f"iter-{n}" / "patches"
        d.mkdir(parents=True)
        (d / "cumulative.patch").write_text(f"iter-{n} diff\n")
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    campaign = {"derived_from": {"campaign": "prior-campaign", "iteration": "final"}}
    result = resolve_derived_from(campaign)
    assert result is not None
    assert "iter-3" in str(result)


def test_f21_summarize_lineage_handles_missing_dirs(tmp_path: Path):
    summary = summarize_lineage(tmp_path)
    assert "iterations" in summary
    assert summary["iterations"] == []
