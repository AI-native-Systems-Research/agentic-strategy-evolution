"""Tests for wait_for polling (spec 3.2 step 4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.v2.hooks import HookState, build_hooks
from orchestrator.v2.loop import Campaign, CampaignConfig, iter_dir, _write_json
from orchestrator.v2.robustness import poll_wait_for
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


class TestWaitForPolling:
    """Spec 3.2 step 4: poll wait_for every 60s with no model calls."""

    def test_file_wait_for_succeeds_immediately(self, tmp_path):
        """wait_for file that already exists returns immediately."""
        target = tmp_path / "done.txt"
        target.write_text("done")
        result = poll_wait_for(
            str(target), poll_interval=0.01, timeout=1.0
        )
        assert result is True

    def test_file_wait_for_waits_then_succeeds(self, tmp_path):
        """wait_for file that appears after a delay."""
        target = tmp_path / "done.txt"
        call_count = [0]
        original_exists = Path.exists

        def delayed_exists(self_path):
            if str(self_path) == str(target):
                call_count[0] += 1
                if call_count[0] >= 3:
                    target.write_text("done")
                    return True
                return False
            return original_exists(self_path)

        with patch.object(Path, "exists", delayed_exists):
            result = poll_wait_for(
                str(target), poll_interval=0.01, timeout=2.0
            )
        assert result is True

    def test_file_wait_for_times_out(self, tmp_path):
        """wait_for file that never appears returns False on timeout."""
        target = tmp_path / "never.txt"
        result = poll_wait_for(
            str(target), poll_interval=0.01, timeout=0.05
        )
        assert result is False

    def test_command_wait_for_succeeds(self, tmp_path):
        """wait_for command that exits 0."""
        result = poll_wait_for(
            "cmd:true", poll_interval=0.01, timeout=1.0
        )
        assert result is True

    def test_command_wait_for_fails_then_succeeds(self, tmp_path):
        """wait_for command that fails initially then succeeds."""
        counter_file = tmp_path / "counter"
        counter_file.write_text("0")
        # Command that succeeds on 3rd call
        cmd = f"cmd:python3 -c \"p=__import__('pathlib').Path('{counter_file}'); n=int(p.read_text())+1; p.write_text(str(n)); exit(0 if n>=3 else 1)\""
        result = poll_wait_for(
            cmd, poll_interval=0.01, timeout=2.0
        )
        assert result is True

    def test_command_wait_for_times_out(self, tmp_path):
        """wait_for command that never succeeds."""
        result = poll_wait_for(
            "cmd:false", poll_interval=0.01, timeout=0.05
        )
        assert result is False

    def test_no_model_calls_during_polling(self, tmp_path):
        """Polling must not invoke any SDK/LLM calls."""
        # This is structural by design: poll_wait_for is a pure function
        # that does file/subprocess checks only. Verify it doesn't import
        # or call any SDK module.
        target = tmp_path / "done.txt"
        target.write_text("done")
        # If poll_wait_for tried to use SDK, conftest guards would catch it
        result = poll_wait_for(
            str(target), poll_interval=0.01, timeout=1.0
        )
        assert result is True

    def test_pending_wait_for_not_validation_failure(self, tmp_path):
        """A plan entry with wait_for that hasn't completed is not a validation error."""
        plan = {
            "runs": [
                {
                    "id": "r1",
                    "hypothesis_id": "h1",
                    "role": "treatment",
                    "command": "long_job.sh",
                    "parameters": {},
                    "seeds": [1],
                    "wait_for": str(tmp_path / "not_yet.txt"),
                },
            ],
        }
        from orchestrator.v2.validators import validate_artifact, ValidatorContext
        ctx = ValidatorContext(work_dir=tmp_path)
        errors = validate_artifact("plan", plan, ctx)
        assert not any("wait_for" in e for e in errors)


# ── Helpers for integration tests ────────────────────────────────────────


def _config(**overrides) -> CampaignConfig:
    defaults = dict(
        research_question="Does X improve Y?",
        run_id="test-waitfor",
        max_iterations=1,
        target_system={"path": "/nonexistent"},
        experiment_commands=[],
    )
    defaults.update(overrides)
    return CampaignConfig(**defaults)


def _baseline() -> dict:
    return {
        "task_type": "optimize",
        "command": "run.sh",
        "git_sha": "a1b2c3d",
        "observation": {"score": 42},
        "metrics_path": "metrics.json",
        "noise": {"deterministic": True},
    }


def _problem() -> dict:
    return {
        "task_type": "optimize",
        "claims_needed": [{"id": "c1", "test": "compare scores"}],
    }


def _bundle() -> dict:
    return {
        "hypotheses": [
            {
                "id": "h1", "role": "main", "family": "f1",
                "mechanism": "m1",
                "prediction": {"metric": "score", "direction": "increase"},
                "control": "baseline", "falsified_if": "score <= baseline",
                "claim_ids": ["c1"],
            },
            {
                "id": "h2", "role": "alt", "family": "f2",
                "mechanism": "m2",
                "prediction": {"metric": "score", "direction": "increase"},
                "control": "baseline", "falsified_if": "score <= baseline",
                "claim_ids": ["c1"],
            },
        ],
    }


def _findings() -> dict:
    return {
        "hypotheses": [
            {
                "id": "h1", "status": "CONFIRMED", "error_type": "none",
                "evidence": [], "noise_unmeasured": True,
                "noise_reason": "deterministic baseline",
                "claims": [
                    {"claim_id": "c1", "metric": "score", "condition": "fast", "value": 50},
                ],
            },
        ],
        "best": {"metric": "score", "value": 50},
        "question_answered": True,
        "reason": "confirmed by experiment",
    }


def _principle_updates() -> dict:
    return {"updates": [{"id": "p1", "action": "add", "text": "Fast is better", "finding_ref": "h1"}]}


def _answer() -> dict:
    return {
        "answer": "Yes", "deliverable": "config",
        "repro": "run.sh --fast", "claims": [],
    }


# ── Integration tests: stop hook + poll + resume ─────────────────────────


class TestWaitForIntegration:
    """Integration: pending wait_for → stop allowed → poll → resume message."""

    async def test_stop_hook_allows_stop_with_pending_wait(self, tmp_path):
        """Stop hook does not block when pending_wait_for has unmet conditions."""
        missing = str(tmp_path / "not_yet.txt")
        state = HookState(work_dir=tmp_path, phase="EXECUTE", iteration=1, pending_wait_for=[missing])
        hooks = build_hooks(state)
        stop_matchers = hooks["Stop"]
        cb = stop_matchers[0].hooks[0]
        result = await cb({"stop_reason": "end_turn"}, None, {"signal": None})
        assert result == {} or result.get("decision") != "block"

    async def test_stop_hook_validates_when_all_waits_met(self, tmp_path):
        """Stop hook validates artifacts when all wait_for conditions are met."""
        done = tmp_path / "done.txt"
        done.write_text("done")
        state = HookState(work_dir=tmp_path, phase="EXECUTE", iteration=1, pending_wait_for=[str(done)])
        idir = iter_dir(tmp_path, 1)
        idir.mkdir(parents=True, exist_ok=True)
        hooks = build_hooks(state)
        cb = hooks["Stop"][0].hooks[0]
        result = await cb({"stop_reason": "end_turn"}, None, {"signal": None})
        assert result.get("decision") == "block"

    async def test_agent_receives_resume_after_wait(self, tmp_path):
        """After wait_for is satisfied, agent receives 'Runs X finished' message."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)

        done_file = tmp_path / "done.txt"

        plan_with_wait = {
            "runs": [
                {
                    "id": "r1", "hypothesis_id": "h1", "role": "treatment",
                    "command": "long_job.sh", "parameters": {}, "seeds": [1],
                    "wait_for": str(done_file),
                },
            ],
        }

        per_turn = [
            # BASELINE
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            # DESIGN
            {
                str(idir / "problem.json"): json.dumps(_problem()),
                str(idir / "bundle.json"): json.dumps(_bundle()),
                str(idir / "plan.json"): json.dumps(plan_with_wait),
            },
            # EXECUTE (agent starts job, ends turn without findings)
            {},
            # Resume after wait (agent writes findings)
            {
                str(idir / "findings.json"): json.dumps(_findings()),
                str(idir / "principle_updates.json"): json.dumps(_principle_updates()),
            },
            # REPORT
            {str(work_dir / "answer.json"): json.dumps(_answer())},
        ]

        # Create the done file so polling succeeds immediately
        done_file.write_text("done")

        script = [FakeResultMessage()] * 5
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=_config(),
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.run()
        assert result["stop_reason"] == "answered"
        # Check that the resume message was sent
        assert any("finished" in q and "continue EXECUTE" in q for q in client.queries)

    async def test_two_pending_runs_polled_together(self, tmp_path):
        """Multiple wait_for runs are polled in the same loop."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)

        done1 = tmp_path / "done1.txt"
        done2 = tmp_path / "done2.txt"

        plan_with_waits = {
            "runs": [
                {
                    "id": "r1", "hypothesis_id": "h1", "role": "treatment",
                    "command": "job1.sh", "parameters": {}, "seeds": [1],
                    "wait_for": str(done1),
                },
                {
                    "id": "r2", "hypothesis_id": "h2", "role": "treatment",
                    "command": "job2.sh", "parameters": {}, "seeds": [1],
                    "wait_for": str(done2),
                },
            ],
        }

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(idir / "problem.json"): json.dumps(_problem()),
                str(idir / "bundle.json"): json.dumps(_bundle()),
                str(idir / "plan.json"): json.dumps(plan_with_waits),
            },
            {},  # EXECUTE
            {},  # resume after first batch
            {   # resume after all done
                str(idir / "findings.json"): json.dumps(_findings()),
                str(idir / "principle_updates.json"): json.dumps(_principle_updates()),
            },
            {str(work_dir / "answer.json"): json.dumps(_answer())},
        ]

        # Both files exist immediately
        done1.write_text("done")
        done2.write_text("done")

        script = [FakeResultMessage()] * 6
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=_config(),
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.run()
        assert result["stop_reason"] == "answered"
        resume_msgs = [q for q in client.queries if "finished" in q]
        assert len(resume_msgs) >= 1
