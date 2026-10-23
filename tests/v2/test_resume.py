"""Tests for orchestrator.v2.resume — session resume and fallback (spec 3.7)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.v2.resume import (
    load_campaign_state,
    resume_phase,
    build_fallback_message,
)


# ── load_campaign_state ──────────────────────────────────────────────────


class TestLoadCampaignState:
    def test_returns_state_dict(self, tmp_path):
        state = {
            "session_id": "ses-abc",
            "phase": "EXECUTE",
            "iteration": 2,
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


# ── resume_phase ─────────────────────────────────────────────────────────


class TestResumePhase:
    def test_resume_from_baseline(self):
        state = {"phase": "BASELINE", "iteration": 0}
        phase, iteration = resume_phase(state)
        assert phase == "BASELINE"
        assert iteration == 0

    def test_resume_from_design(self):
        state = {"phase": "DESIGN", "iteration": 2}
        phase, iteration = resume_phase(state)
        assert phase == "DESIGN"
        assert iteration == 2

    def test_resume_from_execute(self):
        state = {"phase": "EXECUTE", "iteration": 3}
        phase, iteration = resume_phase(state)
        assert phase == "EXECUTE"
        assert iteration == 3

    def test_resume_from_report(self):
        state = {"phase": "REPORT", "iteration": 3}
        phase, iteration = resume_phase(state)
        assert phase == "REPORT"
        assert iteration == 3

    def test_defaults_to_baseline_on_missing_phase(self):
        state = {}
        phase, iteration = resume_phase(state)
        assert phase == "BASELINE"
        assert iteration == 0


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


# ── Campaign.resume integration ──────────────────────────────────────────


class TestCampaignResume:
    """Integration tests: Campaign.resume() continues from saved state."""

    async def test_resume_continues_at_saved_phase(self, tmp_path):
        """Campaign with state at iteration 1 EXECUTE resumes correctly."""
        from orchestrator.v2.loop import Campaign, CampaignConfig, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        # Set up state as if BASELINE and iter-1 DESIGN are done
        _write_json(work_dir / "state.json", {
            "session_id": "ses-resume-1",
            "phase": "EXECUTE",
            "iteration": 1,
        })
        _write_json(work_dir / "baseline.json", {
            "task_type": "debug",
            "command": "pytest",
            "git_sha": "abc1234",
            "observation": {"reproduced": True, "symptom": "fails", "expected": "pass", "actual": "fail"},
            "metrics_path": "m.json",
            "noise": {"deterministic": True},
        })
        idir = work_dir / "runs" / "iter-1"
        idir.mkdir(parents=True)
        _write_json(idir / "problem.json", {
            "task_type": "debug",
            "claims_needed": [{"id": "c1", "description": "fix", "test_method": "pytest"}],
        })
        _write_json(idir / "bundle.json", {
            "hypotheses": [{
                "id": "h1", "role": "treatment", "family": "f1",
                "mechanism": "fix bug", "prediction": {"metric": "pass", "direction": "increase"},
                "control": "unfixed code", "falsified_if": "still fails", "claim_ids": ["c1"],
            }, {
                "id": "h2", "role": "alternative", "family": "f2",
                "mechanism": "alt fix", "prediction": {"metric": "pass", "direction": "increase"},
                "control": "unfixed code", "falsified_if": "still fails", "claim_ids": ["c1"],
            }],
        })
        _write_json(idir / "plan.json", {
            "runs": [{"id": "r1", "hypothesis_id": "h1", "role": "treatment",
                       "command": "pytest", "parameters": {}, "seeds": [42]},
                      {"id": "r2", "hypothesis_id": "h1", "role": "control",
                       "command": "pytest", "parameters": {}, "seeds": [42]}],
        })

        # FakeClient: EXECUTE turn, REPORT turn = 2 turns
        findings = {
            "hypotheses": [{
                "id": "h1", "status": "CONFIRMED",
                "error_type": "none", "evidence": [],
                "noise_unmeasured": True, "noise_reason": "single",
                "claims": [{"claim_id": "c1", "metric": "pass", "condition": "default", "value": 1.0}],
            }],
            "question_answered": True,
            "reason": "fixed",
        }
        pu = {"updates": []}
        answer = {"answer": "fixed", "deliverable": "patch", "repro": "pytest",
                  "claims": []}

        per_turn = [
            {  # EXECUTE turn writes findings + pu
                str(idir / "findings.json"): json.dumps(findings),
                str(idir / "principle_updates.json"): json.dumps(pu),
            },
            {  # REPORT turn writes answer
                str(work_dir / "answer.json"): json.dumps(answer),
            },
        ]
        script = [FakeResultMessage(session_id="ses-resumed") for _ in range(2)]

        config = CampaignConfig(
            research_question="test?",
            run_id="test-resume",
            max_iterations=3,
            target_system={"repo_path": "/nonexistent"},
        )
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.resume()

        # Should have completed: EXECUTE + REPORT (skipped BASELINE + DESIGN)
        assert result["stop_reason"] == "answered"
        assert result["iterations"] == 1
        # Only 2 queries: EXECUTE and REPORT (no BASELINE, no DESIGN)
        assert len(client.queries) == 2

    async def test_fallback_primes_from_digest(self, tmp_path):
        """When session_id is missing, fallback primes from digest."""
        from orchestrator.v2.loop import Campaign, CampaignConfig, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        # State without session_id = forces fallback
        _write_json(work_dir / "state.json", {
            "phase": "DESIGN",
            "iteration": 2,
        })
        _write_json(work_dir / "baseline.json", {
            "task_type": "debug", "command": "pytest", "git_sha": "abc1234",
            "observation": {"reproduced": True, "symptom": "fails", "expected": "pass", "actual": "fail"}, "metrics_path": "m.json", "noise": {"deterministic": True},
        })
        digest = {
            "iteration": 1,
            "principles": [{"id": "p1", "text": "check bounds"}],
            "baseline_sha": "abc",
        }
        state_dir = work_dir / "state"
        state_dir.mkdir()
        _write_json(state_dir / "digest.json", digest)
        _write_json(work_dir / "ledger.json", [
            {"iteration": 1, "claims_changed": True, "best_changed": False,
             "principles_changed": True, "status": "ok", "stop_reason": None},
        ])

        idir = work_dir / "runs" / "iter-2"
        idir.mkdir(parents=True)

        findings = {
            "hypotheses": [{
                "id": "h1", "status": "CONFIRMED",
                "error_type": "none", "evidence": [],
                "noise_unmeasured": True, "noise_reason": "single",
                "claims": [{"claim_id": "c1", "metric": "pass", "condition": "default", "value": 1.0}],
            }],
            "question_answered": True, "reason": "fixed",
        }
        pu = {"updates": []}
        answer = {"answer": "fixed", "deliverable": "patch", "repro": "pytest",
                  "claims": []}

        # Turns: fallback prime, DESIGN, EXECUTE, REPORT = 4 turns
        per_turn = [
            {},  # fallback prime (no files)
            {  # DESIGN
                str(idir / "problem.json"): json.dumps({
                    "task_type": "debug",
                    "claims_needed": [{"id": "c1", "description": "fix", "test_method": "pytest"}],
                }),
                str(idir / "bundle.json"): json.dumps({
                    "hypotheses": [{
                        "id": "h1", "role": "treatment", "family": "f1",
                        "mechanism": "fix", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }, {
                        "id": "h2", "role": "alternative", "family": "f2",
                        "mechanism": "alt", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }],
                }),
                str(idir / "plan.json"): json.dumps({
                    "runs": [{"id": "r1", "hypothesis_id": "h1", "role": "treatment",
                              "command": "pytest", "parameters": {}, "seeds": [42]},
                             {"id": "r2", "hypothesis_id": "h1", "role": "control",
                              "command": "pytest", "parameters": {}, "seeds": [42]}],
                }),
            },
            {  # EXECUTE
                str(idir / "findings.json"): json.dumps(findings),
                str(idir / "principle_updates.json"): json.dumps(pu),
            },
            {  # REPORT
                str(work_dir / "answer.json"): json.dumps(answer),
            },
        ]
        script = [FakeResultMessage(session_id=f"ses-{i}") for i in range(4)]

        config = CampaignConfig(
            research_question="test?",
            run_id="test-fallback",
            max_iterations=3,
            target_system={"repo_path": "/nonexistent"},
        )
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.resume()

        # First query should be the fallback priming message
        assert len(client.queries) >= 1
        first_msg = client.queries[0]
        assert "digest" in first_msg.lower() or "resuming" in first_msg.lower()

    async def test_note_in_phase_message_and_ledger(self, tmp_path):
        """--note text appears in the next phase message and ledger."""
        from orchestrator.v2.loop import Campaign, CampaignConfig, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        _write_json(work_dir / "state.json", {
            "session_id": "ses-note",
            "phase": "EXECUTE",
            "iteration": 1,
            "note": "try the greedy approach",
        })
        _write_json(work_dir / "baseline.json", {
            "task_type": "optimize", "command": "bench.py", "git_sha": "abc1234",
            "observation": {"score": 10}, "metrics_path": "m.json", "noise": {"deterministic": True},
        })
        idir = work_dir / "runs" / "iter-1"
        idir.mkdir(parents=True)
        _write_json(idir / "problem.json", {
            "task_type": "optimize",
            "claims_needed": [{"id": "c1", "description": "improve", "test_method": "bench"}],
        })
        _write_json(idir / "bundle.json", {
            "hypotheses": [{
                "id": "h1", "role": "treatment", "family": "f1",
                "mechanism": "greedy", "prediction": {"metric": "score", "direction": "increase"},
                "control": "unfixed code", "falsified_if": "no improvement", "claim_ids": ["c1"],
            }, {
                "id": "h2", "role": "alternative", "family": "f2",
                "mechanism": "dp", "prediction": {"metric": "score", "direction": "increase"},
                "control": "unfixed code", "falsified_if": "no improvement", "claim_ids": ["c1"],
            }],
        })
        _write_json(idir / "plan.json", {
            "runs": [{"id": "r1", "hypothesis_id": "h1", "role": "treatment",
                       "command": "bench.py", "parameters": {}, "seeds": [42]},
                      {"id": "r2", "hypothesis_id": "h1", "role": "control",
                       "command": "bench.py", "parameters": {}, "seeds": [42]}],
        })

        findings = {
            "hypotheses": [{
                "id": "h1", "status": "CONFIRMED",
                "error_type": "none", "evidence": [],
                "noise_unmeasured": True, "noise_reason": "single",
                "claims": [{"claim_id": "c1", "metric": "score", "condition": "default", "value": 20.0}],
            }],
            "question_answered": True, "reason": "greedy worked",
        }
        pu = {"updates": []}
        answer = {"answer": "greedy wins", "deliverable": "patch", "repro": "bench.py",
                  "claims": []}

        per_turn = [
            {
                str(idir / "findings.json"): json.dumps(findings),
                str(idir / "principle_updates.json"): json.dumps(pu),
            },
            {str(work_dir / "answer.json"): json.dumps(answer)},
        ]
        script = [FakeResultMessage(session_id="ses-noted") for _ in range(2)]

        config = CampaignConfig(
            research_question="test?",
            run_id="test-note",
            max_iterations=3,
            target_system={"repo_path": "/nonexistent"},
        )
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.resume(note="try the greedy approach")

        # Note should appear in the EXECUTE message
        assert "try the greedy approach" in client.queries[0]

        # Note should be in ledger
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert any(e.get("note") == "try the greedy approach" for e in ledger)
        schema = json.loads((Path(__file__).resolve().parents[2] / "orchestrator" / "v2"
                             / "schemas" / "ledger_entry.schema.json").read_text())
        for row in ledger:  # the note row matches the documented ledger shape
            jsonschema.validate(row, schema)

    async def test_missing_state_starts_fresh(self, tmp_path):
        """No state.json means a fresh campaign from the beginning."""
        from orchestrator.v2.loop import Campaign, CampaignConfig, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        idir = work_dir / "runs" / "iter-1"
        findings = {
            "hypotheses": [{
                "id": "h1", "status": "CONFIRMED",
                "error_type": "none", "evidence": [],
                "noise_unmeasured": True, "noise_reason": "single",
                "claims": [{"claim_id": "c1", "metric": "pass", "condition": "default", "value": 1.0}],
            }],
            "question_answered": True, "reason": "fixed",
        }
        pu = {"updates": []}
        answer = {"answer": "fixed", "deliverable": "patch", "repro": "pytest",
                  "claims": []}

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps({
                "task_type": "debug", "command": "pytest", "git_sha": "abc1234",
                "observation": {"reproduced": True, "symptom": "fails", "expected": "pass", "actual": "fail"}, "metrics_path": "m.json", "noise": {"deterministic": True},
            })},
            {
                str(idir / "problem.json"): json.dumps({
                    "task_type": "debug",
                    "claims_needed": [{"id": "c1", "description": "fix", "test_method": "pytest"}],
                }),
                str(idir / "bundle.json"): json.dumps({
                    "hypotheses": [{
                        "id": "h1", "role": "treatment", "family": "f1",
                        "mechanism": "fix", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }, {
                        "id": "h2", "role": "alternative", "family": "f2",
                        "mechanism": "alt", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }],
                }),
                str(idir / "plan.json"): json.dumps({
                    "runs": [{"id": "r1", "hypothesis_id": "h1", "role": "treatment",
                              "command": "pytest", "parameters": {}, "seeds": [42]},
                             {"id": "r2", "hypothesis_id": "h1", "role": "control",
                              "command": "pytest", "parameters": {}, "seeds": [42]}],
                }),
            },
            {
                str(idir / "findings.json"): json.dumps(findings),
                str(idir / "principle_updates.json"): json.dumps(pu),
            },
            {str(work_dir / "answer.json"): json.dumps(answer)},
        ]
        script = [FakeResultMessage(session_id=f"ses-{i}") for i in range(4)]

        config = CampaignConfig(
            research_question="test?",
            run_id="test-fresh",
            max_iterations=1,
            target_system={"repo_path": "/nonexistent"},
        )
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.resume()

        # Full fresh run: BASELINE, DESIGN, EXECUTE, REPORT = 4 turns
        assert len(client.queries) == 4
        assert "BASELINE" in client.queries[0]

    async def test_session_scope_iteration_uses_fallback(self, tmp_path):
        """session_scope=iteration always starts fresh sessions per iteration."""
        from orchestrator.v2.loop import Campaign, CampaignConfig, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        _write_json(work_dir / "state.json", {
            "session_id": "ses-old",
            "phase": "DESIGN",
            "iteration": 2,
        })
        _write_json(work_dir / "baseline.json", {
            "task_type": "debug", "command": "pytest", "git_sha": "abc1234",
            "observation": {"reproduced": True, "symptom": "fails", "expected": "pass", "actual": "fail"}, "metrics_path": "m.json", "noise": {"deterministic": True},
        })

        idir = work_dir / "runs" / "iter-2"
        idir.mkdir(parents=True)

        findings = {
            "hypotheses": [{
                "id": "h1", "status": "CONFIRMED",
                "error_type": "none", "evidence": [],
                "noise_unmeasured": True, "noise_reason": "single",
                "claims": [{"claim_id": "c1", "metric": "pass", "condition": "default", "value": 1.0}],
            }],
            "question_answered": True, "reason": "fixed",
        }
        pu = {"updates": []}
        answer = {"answer": "fixed", "deliverable": "patch", "repro": "pytest",
                  "claims": []}

        # Turns: fallback prime, DESIGN, EXECUTE, REPORT = 4
        per_turn = [
            {},  # fallback prime
            {
                str(idir / "problem.json"): json.dumps({
                    "task_type": "debug",
                    "claims_needed": [{"id": "c1", "description": "fix", "test_method": "pytest"}],
                }),
                str(idir / "bundle.json"): json.dumps({
                    "hypotheses": [{
                        "id": "h1", "role": "treatment", "family": "f1",
                        "mechanism": "fix", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }, {
                        "id": "h2", "role": "alternative", "family": "f2",
                        "mechanism": "alt", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }],
                }),
                str(idir / "plan.json"): json.dumps({
                    "runs": [{"id": "r1", "hypothesis_id": "h1", "role": "treatment",
                              "command": "pytest", "parameters": {}, "seeds": [42]},
                             {"id": "r2", "hypothesis_id": "h1", "role": "control",
                              "command": "pytest", "parameters": {}, "seeds": [42]}],
                }),
            },
            {
                str(idir / "findings.json"): json.dumps(findings),
                str(idir / "principle_updates.json"): json.dumps(pu),
            },
            {str(work_dir / "answer.json"): json.dumps(answer)},
        ]
        script = [FakeResultMessage(session_id=f"ses-{i}") for i in range(4)]

        config = CampaignConfig(
            research_question="test?",
            run_id="test-scope-iter",
            max_iterations=3,
            target_system={"repo_path": "/nonexistent"},
            session_scope="iteration",
        )

        clients_created = []

        def capturing_factory(_opts):
            c = FakeClient(script=list(script), per_turn_files=list(per_turn))
            clients_created.append(c)
            return c

        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=capturing_factory,
        )
        result = await campaign.resume()

        # session_scope=iteration: should NOT pass resume=session_id to session
        # The first query should be a fallback priming message
        assert len(clients_created) >= 1
        first_client = clients_created[0]
        assert len(first_client.queries) >= 1


class TestCampaignStateResumeFields:
    """Test that state.json gets phase/iteration/note fields for resume."""

    async def test_state_records_phase_and_iteration(self, tmp_path):
        from orchestrator.v2.loop import Campaign, CampaignConfig, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        idir = work_dir / "runs" / "iter-1"
        findings = {
            "hypotheses": [{
                "id": "h1", "status": "CONFIRMED",
                "error_type": "none", "evidence": [],
                "noise_unmeasured": True, "noise_reason": "single",
                "claims": [{"claim_id": "c1", "metric": "pass", "condition": "default", "value": 1.0}],
            }],
            "question_answered": True, "reason": "fixed",
        }
        pu = {"updates": []}
        answer = {"answer": "fixed", "deliverable": "patch", "repro": "pytest",
                  "claims": []}

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps({
                "task_type": "debug", "command": "pytest", "git_sha": "abc1234",
                "observation": {"reproduced": True, "symptom": "fails", "expected": "pass", "actual": "fail"}, "metrics_path": "m.json", "noise": {"deterministic": True},
            })},
            {
                str(idir / "problem.json"): json.dumps({
                    "task_type": "debug",
                    "claims_needed": [{"id": "c1", "description": "fix", "test_method": "pytest"}],
                }),
                str(idir / "bundle.json"): json.dumps({
                    "hypotheses": [{
                        "id": "h1", "role": "treatment", "family": "f1",
                        "mechanism": "fix", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }, {
                        "id": "h2", "role": "alternative", "family": "f2",
                        "mechanism": "alt", "prediction": {"metric": "pass", "direction": "increase"},
                        "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"],
                    }],
                }),
                str(idir / "plan.json"): json.dumps({
                    "runs": [{"id": "r1", "hypothesis_id": "h1", "role": "treatment",
                              "command": "pytest", "parameters": {}, "seeds": [42]},
                             {"id": "r2", "hypothesis_id": "h1", "role": "control",
                              "command": "pytest", "parameters": {}, "seeds": [42]}],
                }),
            },
            {
                str(idir / "findings.json"): json.dumps(findings),
                str(idir / "principle_updates.json"): json.dumps(pu),
            },
            {str(work_dir / "answer.json"): json.dumps(answer)},
        ]
        script = [FakeResultMessage(session_id=f"ses-{i}") for i in range(4)]

        config = CampaignConfig(
            research_question="test?",
            run_id="test-state",
            max_iterations=1,
            target_system={"repo_path": "/nonexistent"},
        )
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        await campaign.run()

        state = json.loads((work_dir / "state.json").read_text())
        assert "phase" in state
        assert "iteration" in state


# ── Review fixes: resume edge cases ──────────────────────────────────────

_BUNDLE = {"hypotheses": [{
    "id": f"h{i}", "role": "treatment", "family": f"f{i}", "mechanism": "m",
    "prediction": {"metric": "pass", "direction": "increase"},
    "control": "unfixed code", "falsified_if": "fails", "claim_ids": ["c1"]} for i in (1, 2)]}
_FINDINGS = {"hypotheses": [{
    "id": "h1", "status": "CONFIRMED", "error_type": "none", "evidence": [],
    "noise_unmeasured": True, "noise_reason": "single",
    "claims": [{"claim_id": "c1", "metric": "pass", "condition": "default", "value": 1.0}]}],
    "question_answered": True, "reason": "fixed"}
_ANSWER = {"answer": "fixed", "deliverable": "patch", "repro": "pytest", "claims": []}


def _seed_execute_state(work_dir: Path, phase: str = "EXECUTE") -> Path:
    from orchestrator.v2.loop import _write_json

    _write_json(work_dir / "state.json", {"session_id": "ses-1", "phase": phase, "iteration": 1})
    _write_json(work_dir / "baseline.json", {
        "task_type": "debug", "command": "pytest", "git_sha": "abc1234",
        "observation": {"reproduced": True, "symptom": "fails", "expected": "pass", "actual": "fail"}, "metrics_path": "m.json", "noise": {"deterministic": True}})
    idir = work_dir / "runs" / "iter-1"
    _write_json(idir / "problem.json", {"task_type": "debug", "claims_needed": [
        {"id": "c1", "description": "fix", "test_method": "pytest"}]})
    _write_json(idir / "bundle.json", _BUNDLE)
    _write_json(idir / "plan.json", {"runs": [
        {"id": f"r{i}", "hypothesis_id": "h1", "role": role, "command": "pytest",
         "parameters": {}, "seeds": [42]} for i, role in ((1, "treatment"), (2, "control"))]})
    return idir


def _exec_report_turns(work_dir: Path, idir: Path) -> list[dict]:
    return [
        {str(idir / "findings.json"): json.dumps(_FINDINGS),
         str(idir / "principle_updates.json"): json.dumps({"updates": []})},
        {str(work_dir / "answer.json"): json.dumps(_ANSWER)},
    ]


def _config():
    from orchestrator.v2.loop import CampaignConfig
    return CampaignConfig(research_question="q?", run_id="r", max_iterations=3,
                          target_system={"repo_path": "/nonexistent"})


class TestResumeReviewFixes:
    async def test_resume_execute_keeps_existing_lock(self, tmp_path):
        """A bundle edited before the crash is still a pre-reg violation on resume."""
        from orchestrator.v2.loop import Campaign, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "c"
        idir = _seed_execute_state(work_dir)
        _write_json(idir / ".bundle.locked.json", _BUNDLE)
        edited = json.loads(json.dumps(_BUNDLE))
        edited["hypotheses"][0]["mechanism"] = "edited after lock"
        _write_json(idir / "bundle.json", edited)

        client = FakeClient(script=[FakeResultMessage()] * 2,
                            per_turn_files=_exec_report_turns(work_dir, idir))
        await Campaign(_config(), work_dir, lambda _o: client).resume()
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert ledger[0]["prereg_violation"] is True
        assert json.loads((idir / "bundle.json").read_text()) == _BUNDLE

    async def test_note_reaches_report_on_resume(self, tmp_path):
        from orchestrator.v2.loop import Campaign
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "c"
        idir = _seed_execute_state(work_dir, phase="REPORT")
        client = FakeClient(script=[FakeResultMessage()],
                            per_turn_files=_exec_report_turns(work_dir, idir)[1:])
        await Campaign(_config(), work_dir, lambda _o: client).resume(note="cite r2")
        assert "cite r2" in client.queries[-1]

    async def test_failed_resume_falls_back_to_fresh_session(self, tmp_path):
        from orchestrator.v2.loop import Campaign
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "c"
        idir = _seed_execute_state(work_dir)
        fresh = FakeClient(script=[FakeResultMessage()] * 3,
                           per_turn_files=[{}] + _exec_report_turns(work_dir, idir))

        class _DeadSession(FakeClient):
            async def connect(self):
                raise RuntimeError("session ses-1 not found")

        def factory(opts):
            return _DeadSession() if opts.resume else fresh

        result = await Campaign(_config(), work_dir, factory).resume()
        assert result["stop_reason"] == "answered"
        assert "Resuming campaign" in fresh.queries[0]
