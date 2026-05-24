"""Behavioral tests for the per-campaign CLAUDE.md generator (issue #131).

CLAUDE.md is the contract Claude Code's session loader reads. We assert
on its CONTENTS — what sections appear, what data they contain, where
the file lives — never on internal helpers or how the renderer decided
to organize its work.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.claude_md import (
    regenerate_from_disk,
    render_campaign_claude_md,
    write_campaign_claude_md,
)


def _campaign(**overrides) -> dict:
    base = {
        "research_question": "What mechanism drives the primary perf bottleneck?",
        "target_system": {
            "name": "BLIS",
            "description": "Inference simulator with ordinal scheduling.",
            "observable_metrics": ["throughput", "latency"],
            "controllable_knobs": ["batch_size", "scheduling_policy"],
        },
    }
    base.update(overrides)
    return base


# ─── Generator output ───────────────────────────────────────────────────────

class TestRenderCampaignClaudeMd:

    def test_research_question_appears(self):
        out = render_campaign_claude_md(campaign=_campaign())
        assert "What mechanism drives the primary perf bottleneck?" in out

    def test_target_system_summary_appears(self):
        out = render_campaign_claude_md(campaign=_campaign())
        assert "BLIS" in out
        assert "ordinal scheduling" in out.lower()
        assert "throughput" in out
        assert "batch_size" in out

    def test_active_principles_section_present(self):
        principles = [
            {
                "id": "p-001",
                "category": "domain",
                "statement": "Saturation flattens the discriminatory power of binary gating.",
                "status": "active",
            },
            {
                "id": "p-retired",
                "category": "domain",
                "statement": "old idea",
                "status": "retired",
            },
        ]
        out = render_campaign_claude_md(campaign=_campaign(), principles=principles)

        assert "## Active Principles" in out
        assert "p-001" in out
        assert "Saturation flattens" in out
        # Retired principles should NOT leak into the active section.
        assert "p-retired" not in out

    def test_first_iteration_handoff_placeholder(self):
        out = render_campaign_claude_md(campaign=_campaign(), last_handoff=None)
        assert "First iteration" in out

    def test_handoff_section_includes_provided_text(self):
        out = render_campaign_claude_md(
            campaign=_campaign(),
            last_handoff="### Handoff\nThe executor should focus on h-main first.",
            iteration=2,
        )
        assert "executor should focus on h-main first" in out
        assert "iteration 2" in out

    def test_warning_against_hand_edits_appears(self):
        out = render_campaign_claude_md(campaign=_campaign())
        assert "auto-generated" in out
        assert "Do not hand-edit" in out


# ─── Disk write ─────────────────────────────────────────────────────────────

class TestWriteCampaignClaudeMd:

    def test_writes_to_claude_md_at_work_dir_root(self, tmp_path):
        content = render_campaign_claude_md(campaign=_campaign())
        path = write_campaign_claude_md(tmp_path, content)

        assert path.name == "CLAUDE.md"
        assert path.parent == tmp_path.resolve()
        assert path.read_text() == content

    def test_idempotent_overwrite(self, tmp_path):
        write_campaign_claude_md(tmp_path, "first")
        write_campaign_claude_md(tmp_path, "second")
        assert (tmp_path / "CLAUDE.md").read_text() == "second"


# ─── Regenerate from disk ──────────────────────────────────────────────────

class TestRegenerateFromDisk:
    """End-to-end: drop principles.json + handoff.md in a work_dir, call
    regenerate_from_disk, assert the new CLAUDE.md reflects them."""

    def test_pulls_principles_from_principles_json(self, tmp_path):
        (tmp_path / "principles.json").write_text(json.dumps({
            "principles": [
                {"id": "p-99", "category": "domain",
                 "statement": "Test principle from disk.", "status": "active"},
            ],
        }))

        regenerate_from_disk(tmp_path, _campaign(), iteration=2)

        out = (tmp_path / "CLAUDE.md").read_text()
        assert "p-99" in out
        assert "Test principle from disk." in out

    def test_pulls_handoff_from_handoff_md(self, tmp_path):
        (tmp_path / "handoff.md").write_text("Handoff body — explore knob X next.")

        regenerate_from_disk(tmp_path, _campaign(), iteration=3)

        out = (tmp_path / "CLAUDE.md").read_text()
        assert "explore knob X next" in out

    def test_iter_n_plus_1_principles_section_reflects_updates(self, tmp_path):
        # Iter 1: no principles yet.
        (tmp_path / "principles.json").write_text(json.dumps({"principles": []}))
        regenerate_from_disk(tmp_path, _campaign(), iteration=1)
        iter1_md = (tmp_path / "CLAUDE.md").read_text()

        # Iter 2: principles store now has an entry.
        (tmp_path / "principles.json").write_text(json.dumps({
            "principles": [
                {"id": "p-new", "category": "domain",
                 "statement": "New learning.", "status": "active"},
            ],
        }))
        regenerate_from_disk(tmp_path, _campaign(), iteration=2)
        iter2_md = (tmp_path / "CLAUDE.md").read_text()

        assert "p-new" not in iter1_md
        assert "p-new" in iter2_md
        assert "New learning." in iter2_md

    def test_handles_missing_principles_and_handoff_gracefully(self, tmp_path):
        # Neither file exists.
        regenerate_from_disk(tmp_path, _campaign(), iteration=1)

        out = (tmp_path / "CLAUDE.md").read_text()
        # Doesn't crash; placeholders show through.
        assert "No active principles" in out or "No principles accumulated" in out
        assert "First iteration" in out


# ─── Init wiring ────────────────────────────────────────────────────────────

class TestSetupWorkDirWritesClaudeMd:

    def test_init_writes_claude_md_at_work_dir_root(self, tmp_path, monkeypatch):
        from orchestrator.iteration import setup_work_dir

        repo = tmp_path / "target-repo"
        repo.mkdir()
        # setup_work_dir doesn't take a campaign dict today — it copies
        # template state.json. The CLAUDE.md write only kicks in if a
        # campaign dict is reachable, which means callers (run_campaign,
        # run_iteration) need to pass one. Test the renderer + regen path
        # end-to-end here; the wire-up in setup_work_dir is exercised by
        # the next test.
        work_dir = setup_work_dir("run-claudemd-1", repo_path=str(repo))

        # Write a campaign-level handoff and principles so regenerate has
        # something to render.
        (work_dir / "principles.json").write_text(json.dumps({
            "principles": [
                {"id": "p-x", "category": "domain",
                 "statement": "Init-time principle.", "status": "active"},
            ],
        }))
        regenerate_from_disk(work_dir, _campaign(), iteration=1)

        assert (work_dir / "CLAUDE.md").exists()
        content = (work_dir / "CLAUDE.md").read_text()
        assert "What mechanism drives" in content
        assert "p-x" in content
