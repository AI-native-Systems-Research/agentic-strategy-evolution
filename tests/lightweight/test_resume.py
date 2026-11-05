"""Tests for orchestrator.lightweight.resume and Campaign.resume."""

from __future__ import annotations

import json

from orchestrator.lightweight.config import CampaignConfig
from orchestrator.lightweight.loop import Campaign
from orchestrator.lightweight.resume import build_fallback_message, load_campaign_state, update_state
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


# ── load_campaign_state ──────────────────────────────────────────────────


class TestLoadCampaignState:
    def test_returns_state_dict(self, tmp_path):
        state = {
            "session_id": "ses-abc",
            "phase": "INVESTIGATE",
            "iteration": 1,
            "effort": "high",
            "cut_offs": 1,
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        result = load_campaign_state(tmp_path)
        assert result == state

    def test_returns_none_when_missing(self, tmp_path):
        assert load_campaign_state(tmp_path) is None

    def test_returns_none_on_corrupt_json(self, tmp_path):
        (tmp_path / "state.json").write_text("{broken")
        assert load_campaign_state(tmp_path) is None


# ── build_fallback_message ───────────────────────────────────────────────


class TestBuildFallbackMessage:
    def test_includes_phase_and_iteration(self):
        msg = build_fallback_message(
            phase="DESIGN", iteration=2, digest=None, note=None,
        )
        assert "DESIGN" in msg
        assert "2" in msg

    def test_includes_digest_summary(self):
        digest = {
            "iteration": 1,
            "principles": [{"id": "p1", "text": "avoid off-by-one"}],
            "baseline_sha": "abc123",
        }
        msg = build_fallback_message(
            phase="EXECUTE", iteration=2, digest=digest, note=None,
        )
        assert "digest" in msg.lower() or "state" in msg.lower()
        assert "abc123" in msg or "p1" in msg

    def test_includes_note(self):
        msg = build_fallback_message(
            phase="EXECUTE", iteration=2, digest=None,
            note="try the other algorithm family",
        )
        assert "try the other algorithm family" in msg

    def test_note_and_digest_together(self):
        digest = {"iteration": 1, "principles": [], "baseline_sha": "abc"}
        msg = build_fallback_message(
            phase="DESIGN", iteration=3, digest=digest,
            note="focus on latency",
        )
        assert "focus on latency" in msg
        assert "DESIGN" in msg


# ── update_state ─────────────────────────────────────────────────────────


class TestUpdateState:
    def test_merges_fields(self, tmp_path):
        update_state(tmp_path, phase="INVESTIGATE", iteration=1)
        update_state(tmp_path, session_id="s1")
        assert load_campaign_state(tmp_path) == {"phase": "INVESTIGATE", "iteration": 1, "session_id": "s1"}

    def test_replaces_a_corrupt_file(self, tmp_path):
        (tmp_path / "state.json").write_text("{broken")
        update_state(tmp_path, phase="DONE")
        assert load_campaign_state(tmp_path) == {"phase": "DONE"}
        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]  # no tmp file left


# ── Campaign.resume ──────────────────────────────────────────────────────


_ANSWER = {"answer": "fixed", "deliverable": "patch", "repro": "pytest", "claims": []}


def _config():
    return CampaignConfig(research_question="q?", run_id="r", max_iterations=3,
                          target_system={"repo_path": "/nonexistent"})


def _no_gap(_opts):
    msg = FakeResultMessage(session_id="rev")
    msg.result = '{"gap": false, "why": "x"}'
    return FakeClient(script=[msg])


class TestCampaignResume:
    async def test_resume_reconnects_to_the_saved_session(self, tmp_path):
        work_dir = tmp_path / "c"
        update_state(work_dir, session_id="ses-1", phase="INVESTIGATE", iteration=1)
        seen: list = []
        client = FakeClient(script=[FakeResultMessage(session_id="ses-1")],
                            per_turn_files=[{str(work_dir / "answer.json"): json.dumps(_ANSWER)}])

        def factory(opts):
            seen.append(opts.resume)
            return client

        result = await Campaign(_config(), work_dir, factory, challenger_factory=_no_gap).resume(note="cite r2")
        assert result["stop_reason"] == "answered"
        assert seen == ["ses-1"]
        assert client.queries[0].startswith("Continue the investigation.")
        assert client.queries[0].endswith("Human note: cite r2")
        assert load_campaign_state(work_dir)["phase"] == "DONE"

    async def test_failed_connect_falls_back_to_fresh_session(self, tmp_path):
        work_dir = tmp_path / "c"
        update_state(work_dir, session_id="ses-1", phase="INVESTIGATE", iteration=1)
        fresh = FakeClient(script=[FakeResultMessage()],
                           per_turn_files=[{str(work_dir / "answer.json"): json.dumps(_ANSWER)}])

        class _DeadSession(FakeClient):
            async def connect(self):
                raise RuntimeError("session ses-1 not found")

        def factory(opts):
            return _DeadSession() if opts.resume else fresh

        result = await Campaign(_config(), work_dir, factory, challenger_factory=_no_gap).resume()
        assert result["stop_reason"] == "answered"
        assert fresh.queries[0].startswith("q?")
        assert "This is a resumed campaign" in fresh.queries[0]

    async def test_failure_after_a_successful_turn_is_raised(self, tmp_path):
        work_dir = tmp_path / "c"
        update_state(work_dir, session_id="ses-1", phase="INVESTIGATE", iteration=1)

        class _DiesLater(FakeClient):
            async def query(self, prompt):
                if self._queries:
                    raise RuntimeError("boom")
                await super().query(prompt)

        client = _DiesLater(script=[FakeResultMessage()] * 4)
        try:
            await Campaign(_config(), work_dir, lambda _o: client, challenger_factory=_no_gap).resume()
        except RuntimeError as exc:
            assert "boom" in str(exc)
        else:
            raise AssertionError("expected the error to be raised, not a fresh restart")
