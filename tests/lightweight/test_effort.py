"""Tests for orchestrator/lightweight/effort.py — effort ladder and output cut-offs."""

from __future__ import annotations

import json as _json

from orchestrator.lightweight.config import parse_campaign_config
from orchestrator.lightweight.effort import EffortManager
from orchestrator.lightweight.loop import Campaign
from tests.fakes.sdk_client import FakeAssistantMessage, FakeClient, FakeResultMessage


# ── EffortManager unit tests ─────────────────────────────────────────────


class TestEffortLadder:
    def test_default_starts_at_high(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager()
        assert em.current == "high"

    def test_configured_effort_respected(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager(configured_effort="max")
        assert em.current == "max"

    def test_cut_lowers_one_step(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager(configured_effort="high")
        new = em.on_cut()
        assert new == "medium"
        assert em.current == "medium"

    def test_two_consecutive_cuts_reach_low(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager(configured_effort="high")
        em.on_cut()  # high -> medium
        new = em.on_cut()  # medium -> low (2 consecutive)
        assert new == "low"

    def test_single_cut_cannot_reach_low(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager(configured_effort="medium")
        new = em.on_cut()
        # Only 1 consecutive cut — should stay at medium (can't go to low)
        assert new == "medium"

    def test_success_resets_consecutive_counter(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager(configured_effort="high")
        em.on_cut()  # high -> medium, consecutive=1
        em.on_success()  # consecutive=0
        new = em.on_cut()  # medium -> medium (only 1 consecutive, already at medium)
        # Still medium because only 1 consecutive cut since reset
        assert new == "medium"

    def test_phase_reset_restores_configured(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager(configured_effort="xhigh")
        em.on_cut()  # xhigh -> high
        em.on_cut()  # high -> medium (2 consecutive -> can go to low, but next is medium)
        em.reset()
        assert em.current == "xhigh"

    def test_total_cuts_tracked(self):
        from orchestrator.lightweight.effort import EffortManager

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
        from orchestrator.lightweight.effort import EFFORT_LADDER

        assert EFFORT_LADDER == ["max", "xhigh", "high", "medium", "low"]

    def test_already_at_low_stays_at_low(self):
        from orchestrator.lightweight.effort import EffortManager

        em = EffortManager(configured_effort="low")
        em.on_cut()
        em.on_cut()
        assert em.current == "low"

    def test_cut_from_max_walks_down(self):
        from orchestrator.lightweight.effort import EffortManager

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
        from orchestrator.lightweight.effort import EffortManager
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
        from orchestrator.lightweight.effort import EffortManager
        import json

        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"session_id": "ses-1"}))

        em = EffortManager()
        em.on_cut()
        em.persist_cut_offs(state_path)

        state = json.loads(state_path.read_text())
        assert state["session_id"] == "ses-1"
        assert state["cut_offs"] == 1


# ── Campaign integration ────────────────────────────────────────────────


def _cut():
    return [FakeAssistantMessage(stop_reason="max_tokens"), FakeResultMessage()]


def _ok():
    return [FakeResultMessage()]


def _answer_files(work_dir):
    return {str(work_dir / "r.json"): '{"p99": 40}',
            str(work_dir / "answer.json"): _json.dumps({
                "answer": "a", "deliverable": "d", "repro": "python bench.py",
                "claims": [{"id": "C1", "metric": "p99", "value": 40, "condition": "c",
                            "evidence": {"path": "r.json", "key": "/p99", "value": 40}}]})}


async def _run_with(tmp_path, script, cuts, effort="high"):
    """Run a campaign whose task turn is cut `cuts` times; the reply after the last cut writes
    the answer. The reviewer finds no gap."""
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    files = [{}] * cuts + [_answer_files(work_dir)]
    built: list = []

    def factory(opts):
        if opts.disallowed_tools:  # the challenger
            msg = FakeResultMessage(session_id="rev")
            msg.result = '{"gap": false, "why": "x"}'
            return FakeClient(script=[msg])
        built.append(opts)
        if len(built) == 1:
            factory.client = FakeClient(script=script, per_turn_files=files)
        else:  # reconnect continues the same scripted conversation
            factory.client._connected = False
        return factory.client

    raw = {"research_question": "q", "max_iterations": 1, "effort": effort,
           "target_system": {"name": "t", "repo_path": str(tmp_path / "none")}}
    result = await Campaign(parse_campaign_config(raw), work_dir, client_factory=factory).run()
    return result, built, factory.client, work_dir


class TestCutOffInCampaign:
    async def test_cut_reconnects_once_at_lower_effort(self, tmp_path):
        result, built, client, work_dir = await _run_with(tmp_path, _cut() + _ok(), cuts=1)
        assert result["stop_reason"] == "answered"
        assert [o.effort for o in built] == ["high", "medium"]  # exactly one cut reconnect
        assert built[1].resume is not None
        assert "cut at the output limit" in client.queries[1]
        assert _json.loads((work_dir / "state.json").read_text())["cut_offs"] == 1

    async def test_two_cuts_in_a_row_reach_low(self, tmp_path):
        result, built, _, work_dir = await _run_with(tmp_path, _cut() + _cut() + _ok(), cuts=2)
        assert result["stop_reason"] == "answered"
        assert [o.effort for o in built] == ["high", "medium", "low"]
        assert _json.loads((work_dir / "state.json").read_text())["cut_offs"] == 2

    async def test_always_cut_is_bounded(self, tmp_path):
        result, built, _, _ = await _run_with(tmp_path, _cut() * 6 + _ok() * 3, cuts=5)
        assert result["stop_reason"] in ("answered", "partial")
        assert len([o for o in built if o.effort == "low"]) <= 4


class TestCutDetection:
    async def test_subagent_cut_is_not_a_cut(self, tmp_path):
        sub = FakeAssistantMessage(stop_reason="max_tokens", parent_tool_use_id="tu-1")
        _, built, _, work_dir = await _run_with(
            tmp_path, [sub, FakeAssistantMessage(), FakeResultMessage()], cuts=0)
        assert [o.effort for o in built] == ["high"]
        assert "cut_offs" not in _json.loads((work_dir / "state.json").read_text())

    async def test_result_stop_reason_max_tokens_is_a_cut(self, tmp_path):
        _, built, _, _ = await _run_with(tmp_path, [FakeResultMessage(stop_reason="max_tokens")] + _ok(), cuts=1)
        assert [o.effort for o in built][:2] == ["high", "medium"]

    async def test_default_effort_steps_down_from_high(self, tmp_path):
        _, built, _, _ = await _run_with(tmp_path, _cut() + _ok(), cuts=1, effort=None)
        assert [o.effort for o in built] == [None, "medium"]

    def test_cut_offs_count_continues_from_state(self, tmp_path):
        m = EffortManager(None, total_cuts=3)
        m.on_cut()
        m.persist_cut_offs(tmp_path / "state.json")
        assert _json.loads((tmp_path / "state.json").read_text())["cut_offs"] == 4
