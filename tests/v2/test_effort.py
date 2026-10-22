"""Tests for orchestrator/v2/effort.py — effort ladder and output cut-offs."""

from __future__ import annotations

import pytest


# ── EffortManager unit tests ─────────────────────────────────────────────


class TestEffortLadder:
    def test_default_starts_at_high(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager()
        assert em.current == "high"

    def test_configured_effort_respected(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="max")
        assert em.current == "max"

    def test_cut_lowers_one_step(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="high")
        new = em.on_cut()
        assert new == "medium"
        assert em.current == "medium"

    def test_two_consecutive_cuts_reach_low(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="high")
        em.on_cut()  # high -> medium
        new = em.on_cut()  # medium -> low (2 consecutive)
        assert new == "low"

    def test_single_cut_cannot_reach_low(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="medium")
        new = em.on_cut()
        # Only 1 consecutive cut — should stay at medium (can't go to low)
        assert new == "medium"

    def test_success_resets_consecutive_counter(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="high")
        em.on_cut()  # high -> medium, consecutive=1
        em.on_success()  # consecutive=0
        new = em.on_cut()  # medium -> medium (only 1 consecutive, already at medium)
        # Still medium because only 1 consecutive cut since reset
        assert new == "medium"

    def test_phase_reset_restores_configured(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="xhigh")
        em.on_cut()  # xhigh -> high
        em.on_cut()  # high -> medium (2 consecutive -> can go to low, but next is medium)
        em.reset()
        assert em.current == "xhigh"

    def test_total_cuts_tracked(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager()
        assert em.total_cuts == 0
        em.on_cut()
        em.on_cut()
        assert em.total_cuts == 2
        em.reset()  # reset does not clear total_cuts
        assert em.total_cuts == 2
        em.on_cut()
        assert em.total_cuts == 3

    def test_ladder_ordering(self):
        from orchestrator.v2.effort import EFFORT_LADDER

        assert EFFORT_LADDER == ["max", "xhigh", "high", "medium", "low"]

    def test_already_at_low_stays_at_low(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="low")
        em.on_cut()
        em.on_cut()
        assert em.current == "low"

    def test_cut_from_max_walks_down(self):
        from orchestrator.v2.effort import EffortManager

        em = EffortManager(configured_effort="max")
        assert em.on_cut() == "xhigh"
        assert em.on_cut() == "high"
        assert em.on_cut() == "medium"
        # 4th consecutive cut -> low allowed (consecutive >= 2)
        assert em.on_cut() == "low"
        assert em.on_cut() == "low"  # stays at low


class TestEffortStateJson:
    def test_persist_and_read_cut_offs(self, tmp_path):
        """state.json records cut_offs count."""
        from orchestrator.v2.effort import EffortManager
        import json

        em = EffortManager()
        em.on_cut()
        em.on_cut()

        state_path = tmp_path / "state.json"
        em.persist_cut_offs(state_path)

        state = json.loads(state_path.read_text())
        assert state["cut_offs"] == 2

    def test_persist_merges_with_existing(self, tmp_path):
        """persist_cut_offs merges into existing state.json."""
        from orchestrator.v2.effort import EffortManager
        import json

        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"session_id": "ses-1"}))

        em = EffortManager()
        em.on_cut()
        em.persist_cut_offs(state_path)

        state = json.loads(state_path.read_text())
        assert state["session_id"] == "ses-1"
        assert state["cut_offs"] == 1
