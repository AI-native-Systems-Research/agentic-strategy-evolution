"""Tests for wait_for polling (spec 3.2 step 4)."""

from __future__ import annotations

import json

import pytest

from orchestrator.v2.hooks import HookState, build_hooks
from orchestrator.v2.loop import Campaign, CampaignConfig, iter_dir, _write_json
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


class TestWaitForPolling:
    """Spec 3.2 step 4: a pending wait_for is not a validation failure."""

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
        target_system={"repo_path": "/nonexistent"},
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
        "claims_needed": [{"id": "c1", "description": "score improves", "test_method": "compare scores"}],
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
    return {"updates": [{"id": "p1", "action": "add", "text": "Fast is better", "finding_ref": "h1",
                         "scope": "default load"}]}


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


# ── Review fixes: relative wait_for, Stop gating during polling ─────────


class TestWaitForRepoCwd:
    def test_relative_file_resolves_against_repo(self, tmp_path):
        from orchestrator.v2.robustness import check_wait_condition

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "done.txt").write_text("x")
        assert check_wait_condition("done.txt", cwd=str(repo)) is True
        assert check_wait_condition("cmd:test -f done.txt", cwd=str(repo)) is True

    async def test_stop_hook_uses_repo_cwd(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "done_rel_wait.txt").write_text("x")
        state = HookState(work_dir=tmp_path, phase="EXECUTE", iteration=1,
                          pending_wait_for=["done_rel_wait.txt"], cwd=str(repo))
        cb = build_hooks(state)["Stop"][0].hooks[0]
        result = await cb({"stop_reason": "end_turn"}, None, {"signal": None})
        assert result.get("decision") == "block"  # wait met -> artifacts validated


class _StopProbingClient(FakeClient):
    """Runs the Stop hook at the end of each turn and records its decision."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.stop_decisions: list[str | None] = []

    async def receive_response(self):
        async for msg in super().receive_response():
            yield msg
        out = await self._run_event_hooks("Stop", {"hook_event_name": "Stop"})
        self.stop_decisions.append((out or {}).get("decision"))


class TestStopGateDuringPolling:
    async def test_intermediate_resume_turn_not_blocked(self, tmp_path, monkeypatch):
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)
        done1, done2 = tmp_path / "d1.txt", tmp_path / "d2.txt"
        plan = {"runs": [
            {"id": "r1", "hypothesis_id": "h1", "role": "treatment", "command": "a.sh",
             "parameters": {}, "seeds": [1], "wait_for": str(done1)},
            {"id": "r2", "hypothesis_id": "h2", "role": "treatment", "command": "b.sh",
             "parameters": {}, "seeds": [1], "wait_for": str(done2)},
        ]}
        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {str(idir / "problem.json"): json.dumps(_problem()),
             str(idir / "bundle.json"): json.dumps(_bundle()),
             str(idir / "plan.json"): json.dumps(plan)},
            {},  # EXECUTE
            {},  # "Runs r1 finished; still pending r2"
            {str(idir / "findings.json"): json.dumps(_findings()),
             str(idir / "principle_updates.json"): json.dumps(_principle_updates())},
            {str(work_dir / "answer.json"): json.dumps(_answer())},
        ]
        done1.write_text("x")
        monkeypatch.setattr("orchestrator.v2.robustness.time.sleep", lambda _s: done2.write_text("x"))
        holder = {}

        def factory(opts):
            holder["c"] = _StopProbingClient(script=[FakeResultMessage()] * 6,
                                             per_turn_files=per_turn, hooks=opts.hooks)
            return holder["c"]

        result = await Campaign(config=_config(), work_dir=work_dir, client_factory=factory).run()
        assert result["stop_reason"] == "answered"
        # turn index 3 is the intermediate resume turn
        assert holder["c"].stop_decisions[3] != "block"


class TestWaitForMisuse:
    """R13: an agent wrote wait_for: "R1" (its run id) and Nous polled for 4 hours."""

    def test_bare_word_wait_for_rejected(self, tmp_path):
        from orchestrator.v2.validators import ValidatorContext, validate_artifact
        plan = {"runs": [{"id": "R1", "hypothesis_id": "h1", "role": "treatment",
                          "command": "x", "parameters": {}, "seeds": [1], "wait_for": "R1"}]}
        errs = validate_artifact("plan", plan, ValidatorContext(work_dir=tmp_path))
        assert any("wait_for" in e and "cmd:" in e for e in errs)
        for ok in ("results/done.json", "cmd:test -f out", "done.flag"):
            plan["runs"][0]["wait_for"] = ok
            assert not any("wait_for" in e for e in validate_artifact(
                "plan", plan, ValidatorContext(work_dir=tmp_path)))

    async def test_no_polling_when_findings_already_valid(self, tmp_path, monkeypatch):
        import orchestrator.v2.robustness as rb
        polls: list = []
        monkeypatch.setattr(rb, "check_wait_condition", lambda *a, **k: polls.append(a) or False)
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)
        plan = {"runs": [{"id": "r1", "hypothesis_id": "h1", "role": "treatment", "command": "x",
                          "parameters": {}, "seeds": [1], "wait_for": str(tmp_path / "never.txt")}]}
        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {str(idir / "problem.json"): json.dumps(_problem()),
             str(idir / "bundle.json"): json.dumps(_bundle()),
             str(idir / "plan.json"): json.dumps(plan)},
            {str(idir / "findings.json"): json.dumps(_findings()),
             str(idir / "principle_updates.json"): json.dumps(_principle_updates())},
            {str(work_dir / "answer.json"): json.dumps(_answer())},
        ]
        client = FakeClient(script=[FakeResultMessage()] * 4, per_turn_files=per_turn)
        result = await Campaign(config=_config(), work_dir=work_dir,
                                client_factory=lambda _o: client).run()
        assert result["stop_reason"] == "answered"
        assert polls == []
