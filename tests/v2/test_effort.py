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


# ── Loop integration (spec 3.10 / B12) ──────────────────────────────────


import json as _json

from orchestrator.v2.effort import EffortManager
from orchestrator.v2.loop import Campaign, parse_campaign_config
from tests.fakes.sdk_client import FakeAssistantMessage, FakeClient, FakeResultMessage
from tests.v2.test_loop import _build_per_turn_files, _campaign_yaml


def _cut():
    return [FakeAssistantMessage(stop_reason="max_tokens"), FakeResultMessage()]


def _ok():
    return [FakeResultMessage()]


async def _run_with(tmp_path, script, cut_turns, effort="high"):
    """Run a 1-iteration campaign; each turn index in cut_turns is cut once and
    re-asked, so per-turn files shift by one for the resumed query."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    files = _build_per_turn_files(work_dir)
    for i in sorted(cut_turns, reverse=True):
        files.insert(i, {})  # cut query writes nothing; the resume query writes the files
    built: list = []

    def factory(opts):
        built.append(opts)
        if len(built) == 1:
            factory.client = FakeClient(script=script, per_turn_files=files)
        else:  # reconnect continues the same scripted conversation
            factory.client._connected = False
        return factory.client

    raw = {**_campaign_yaml(max_iterations=1), "effort": effort}
    result = await Campaign(parse_campaign_config(raw), work_dir, client_factory=factory).run()
    return result, built, factory.client, work_dir


class TestCutOffInLoop:
    async def test_cut_reconnects_once_at_lower_effort(self, tmp_path):
        script = _ok() + _cut() + _ok() + _ok() + _ok()  # DESIGN turn is cut once
        result, built, client, work_dir = await _run_with(tmp_path, script, cut_turns=[1])
        assert result["stop_reason"] == "answered"
        assert [o.effort for o in built][:2] == ["high", "medium"]  # exactly one cut reconnect
        assert sum(o.effort == "medium" for o in built) == 1
        assert built[1].resume is not None
        assert "cut at the output limit" in client.queries[2]
        assert _json.loads((work_dir / "state.json").read_text())["cut_offs"] == 1

    async def test_effort_resets_at_next_phase(self, tmp_path):
        script = _ok() + _cut() + _ok() + _ok() + _ok()
        _, built, _, _ = await _run_with(tmp_path, script, cut_turns=[1])
        # EXECUTE starts a new phase: reconnect back at the configured effort
        assert [o.effort for o in built] == ["high", "medium", "high"]

    async def test_two_cuts_in_a_row_reach_low(self, tmp_path):
        script = _ok() + _cut() + _cut() + _ok() + _ok() + _ok()
        result, built, _, work_dir = await _run_with(tmp_path, script, cut_turns=[1, 1])
        assert result["stop_reason"] == "answered"
        assert [o.effort for o in built][:3] == ["high", "medium", "low"]
        assert _json.loads((work_dir / "state.json").read_text())["cut_offs"] == 2

    async def test_always_cut_is_bounded(self, tmp_path):
        script = _ok() + _cut() * 5 + _ok() + _ok() + _ok() + _ok()
        result, built, _, _ = await _run_with(tmp_path, script, cut_turns=[1] * 5)
        assert result["stop_reason"] in ("answered", "max_iterations")
        assert len([o for o in built if o.effort == "low"]) <= 4


class TestCutDetection:
    async def test_subagent_cut_is_not_a_cut(self, tmp_path):
        sub = FakeAssistantMessage(stop_reason="max_tokens", parent_tool_use_id="tu-1")
        script = _ok() + [sub, FakeAssistantMessage(), FakeResultMessage()] + _ok() + _ok() + _ok()
        _, built, _, work_dir = await _run_with(tmp_path, script, cut_turns=[])
        assert [o.effort for o in built] == ["high"]
        assert "cut_offs" not in _json.loads((work_dir / "state.json").read_text())

    async def test_result_stop_reason_max_tokens_is_a_cut(self, tmp_path):
        script = _ok() + [FakeResultMessage(stop_reason="max_tokens")] + _ok() + _ok() + _ok()
        _, built, _, _ = await _run_with(tmp_path, script, cut_turns=[1])
        assert [o.effort for o in built][:2] == ["high", "medium"]

    async def test_default_effort_returns_to_model_default_next_phase(self, tmp_path):
        script = _ok() + _cut() + _ok() + _ok() + _ok()
        _, built, _, _ = await _run_with(tmp_path, script, cut_turns=[1], effort=None)
        assert [o.effort for o in built] == [None, "medium", None]

    def test_cut_offs_count_continues_from_state(self, tmp_path):
        m = EffortManager(None, total_cuts=3)
        m.on_cut()
        m.persist_cut_offs(tmp_path / "state.json")
        assert _json.loads((tmp_path / "state.json").read_text())["cut_offs"] == 4
