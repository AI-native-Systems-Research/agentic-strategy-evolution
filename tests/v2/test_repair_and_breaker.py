"""Tests for repair loop and failure breaker (spec 3.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.v2.loop import Campaign, CampaignConfig, iter_dir, _write_json
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


# ── Helpers ──────────────────────────────────────────────────────────────


def _config(**overrides) -> CampaignConfig:
    defaults = dict(
        research_question="Does X improve Y?",
        run_id="test-repair",
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
                "id": "h1",
                "role": "main",
                "family": "f1",
                "mechanism": "m1",
                "prediction": {"metric": "score", "direction": "increase"},
                "control": "baseline",
                "falsified_if": "score <= baseline",
                "claim_ids": ["c1"],
            },
            {
                "id": "h2",
                "role": "alt",
                "family": "f2",
                "mechanism": "m2",
                "prediction": {"metric": "score", "direction": "increase"},
                "control": "baseline",
                "falsified_if": "score <= baseline",
                "claim_ids": ["c1"],
            },
        ],
    }


def _plan() -> dict:
    return {
        "runs": [
            {
                "id": "r1",
                "hypothesis_id": "h1",
                "role": "treatment",
                "command": "run.sh --fast",
                "parameters": {},
                "seeds": [1],
            },
        ],
    }


def _findings(*, answered: bool = True) -> dict:
    return {
        "hypotheses": [
            {
                "id": "h1",
                "status": "CONFIRMED",
                "error_type": "none",
                "evidence": [],
                "noise_unmeasured": True,
                "noise_reason": "deterministic baseline",
                "claims": [
                    {"claim_id": "c1", "metric": "score", "condition": "fast", "value": 50},
                ],
            },
        ],
        "best": {"metric": "score", "value": 50},
        "question_answered": answered,
        "reason": "confirmed by experiment" if answered else "not yet",
    }


def _principle_updates() -> dict:
    return {"updates": [{"id": "p1", "action": "add", "text": "Fast is better", "finding_ref": "h1",
                         "scope": "default load"}]}


def _answer() -> dict:
    return {
        "answer": "Yes, X improves Y",
        "deliverable": "optimized config",
        "repro": "run.sh --fast",
        "claims": [],
    }


def _build_per_turn_files_valid(work_dir: Path) -> list[dict]:
    """Per-turn files for a single-iteration campaign that validates."""
    idir = iter_dir(work_dir, 1)
    return [
        {str(work_dir / "baseline.json"): json.dumps(_baseline())},
        {
            str(idir / "problem.json"): json.dumps(_problem()),
            str(idir / "bundle.json"): json.dumps(_bundle()),
            str(idir / "plan.json"): json.dumps(_plan()),
        },
        {
            str(idir / "findings.json"): json.dumps(_findings()),
            str(idir / "principle_updates.json"): json.dumps(_principle_updates()),
        },
        {str(work_dir / "answer.json"): json.dumps(_answer())},
    ]


# ── Repair loop tests ───────────────────────────────────────────────────


class TestRepairLoop:
    """Spec 3.5: up to 2 repair messages, then status: partial."""

    async def test_repair_succeeds_on_second_try(self, tmp_path):
        """Stop hook blocks once, repair message fixes it, campaign completes."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)

        # Turn 1 (BASELINE): good
        # Turn 2 (DESIGN): good
        # Turn 3 (EXECUTE): first attempt writes bad findings (missing question_answered)
        # Turn 4 (repair): writes correct findings
        # Turn 5 (REPORT): good
        bad_findings = {"hypotheses": []}  # missing required fields
        good_findings = _findings()

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(idir / "problem.json"): json.dumps(_problem()),
                str(idir / "bundle.json"): json.dumps(_bundle()),
                str(idir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(idir / "findings.json"): json.dumps(bad_findings),
                str(idir / "principle_updates.json"): json.dumps(_principle_updates()),
            },
            {
                str(idir / "findings.json"): json.dumps(good_findings),
            },
            {str(work_dir / "answer.json"): json.dumps(_answer())},
        ]

        script = [FakeResultMessage()] * 5
        client = FakeClient(
            script=script,
            per_turn_files=per_turn,
        )
        campaign = Campaign(
            config=_config(),
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.run()
        assert result["stop_reason"] == "answered"
        # The repair message should mention the error
        assert any("repair" in q.lower() or "validation" in q.lower() or "error" in q.lower()
                    for q in client.queries[2:])

    async def test_design_repaired_before_execute(self, tmp_path):
        """Spec 3.5 applies to every phase: an invalid plan.json gets a repair turn
        before EXECUTE, and the locked bundle is the repaired one."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)
        per_turn = _build_per_turn_files_valid(work_dir)
        per_turn[1] = {**per_turn[1], str(idir / "plan.json"): json.dumps({"runs": "bad"})}
        per_turn.insert(2, {str(idir / "plan.json"): json.dumps(_plan())})
        client = FakeClient(script=[FakeResultMessage()] * 5, per_turn_files=per_turn)
        campaign = Campaign(config=_config(), work_dir=work_dir, client_factory=lambda _o: client)
        result = await campaign.run()
        assert result["stop_reason"] == "answered"
        assert "plan" in client.queries[2] and "EXECUTE" not in client.queries[2]
        assert "EXECUTE" in client.queries[3]

    async def test_repair_exhausted_yields_partial(self, tmp_path):
        """After 2 repair tries, ledger gets status: partial, campaign moves on."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)

        bad_findings = {"hypotheses": []}

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(idir / "problem.json"): json.dumps(_problem()),
                str(idir / "bundle.json"): json.dumps(_bundle()),
                str(idir / "plan.json"): json.dumps(_plan()),
            },
            # EXECUTE writes bad findings
            {
                str(idir / "findings.json"): json.dumps(bad_findings),
                str(idir / "principle_updates.json"): json.dumps(_principle_updates()),
            },
            # repair 1: still bad
            {str(idir / "findings.json"): json.dumps(bad_findings)},
            # repair 2: still bad
            {str(idir / "findings.json"): json.dumps(bad_findings)},
            # REPORT
            {str(work_dir / "answer.json"): json.dumps(_answer())},
        ]

        script = [FakeResultMessage()] * 6
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=_config(),
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.run()
        # Campaign should still reach REPORT (not crash)
        assert "stop_reason" in result
        # Ledger should have status: partial
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert any(e.get("status") == "partial" for e in ledger)

    async def test_repair_never_drops_valid_content(self, tmp_path):
        """Even after repair exhaustion, valid content is kept on disk."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        idir = iter_dir(work_dir, 1)

        partial_findings = {
            "hypotheses": [
                {
                    "id": "h1",
                    "status": "CONFIRMED",
                    "error_type": "none",
                    "evidence": [],
                    "noise_unmeasured": True,
                    "noise_reason": "deterministic",
                    "claims": [],
                },
            ],
            # missing question_answered and reason (top-level required)
        }

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(idir / "problem.json"): json.dumps(_problem()),
                str(idir / "bundle.json"): json.dumps(_bundle()),
                str(idir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(idir / "findings.json"): json.dumps(partial_findings),
                str(idir / "principle_updates.json"): json.dumps(_principle_updates()),
            },
            {str(idir / "findings.json"): json.dumps(partial_findings)},
            {str(idir / "findings.json"): json.dumps(partial_findings)},
            {str(work_dir / "answer.json"): json.dumps(_answer())},
        ]

        script = [FakeResultMessage()] * 6
        client = FakeClient(script=script, per_turn_files=per_turn)
        campaign = Campaign(
            config=_config(),
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        await campaign.run()
        # findings.json should still exist with the partial content
        assert (idir / "findings.json").exists()
        data = json.loads((idir / "findings.json").read_text())
        assert len(data["hypotheses"]) == 1


# ── Failure breaker tests ────────────────────────────────────────────────


class TestFailureBreaker:
    """Spec 3.5: 3 identical fingerprints → halt.json → REPORT."""

    async def test_breaker_writes_halt_and_reaches_report(self, tmp_path):
        """Three iterations with identical validation failures trigger halt.json and go to REPORT."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        bad_findings = {"hypotheses": []}  # fails validation

        # 3 iterations each producing bad findings that exhaust repair
        turns = [{str(work_dir / "baseline.json"): json.dumps(_baseline())}]
        for i in range(1, 4):
            idir = iter_dir(work_dir, i)
            turns.append({
                str(idir / "problem.json"): json.dumps(_problem()),
                str(idir / "bundle.json"): json.dumps(_bundle()),
                str(idir / "plan.json"): json.dumps(_plan()),
            })
            # EXECUTE + 2 repair attempts, all write bad findings
            turns.append({
                str(idir / "findings.json"): json.dumps(bad_findings),
                str(idir / "principle_updates.json"): json.dumps(_principle_updates()),
            })
            turns.append({str(idir / "findings.json"): json.dumps(bad_findings)})
            turns.append({str(idir / "findings.json"): json.dumps(bad_findings)})
        # REPORT turn
        turns.append({str(work_dir / "answer.json"): json.dumps(_answer())})

        script = [FakeResultMessage()] * len(turns)
        client = FakeClient(script=script, per_turn_files=turns)
        campaign = Campaign(
            config=_config(max_iterations=3),
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        result = await campaign.run()
        assert result["stop_reason"] == "halt"
        assert (work_dir / "halt.json").exists()
        halt = json.loads((work_dir / "halt.json").read_text())
        assert "fingerprint" in halt

    async def test_breaker_normalizes_fingerprint(self, tmp_path):
        """Numbers and paths are stripped from the fingerprint."""
        from orchestrator.v2.robustness import failure_fingerprint

        fp1 = failure_fingerprint("ValueError", "DESIGN", "file /tmp/abc123/run.py line 42: bad value 3.14")
        fp2 = failure_fingerprint("ValueError", "DESIGN", "file /tmp/xyz999/run.py line 99: bad value 7.28")
        assert fp1 == fp2

    async def test_different_fingerprints_dont_trigger(self, tmp_path):
        """Mixed exception types don't trigger the breaker."""
        from orchestrator.v2.robustness import failure_fingerprint

        fp1 = failure_fingerprint("ValueError", "DESIGN", "missing key")
        fp2 = failure_fingerprint("KeyError", "DESIGN", "missing key")
        assert fp1 != fp2


class TestBreakerReset:
    def test_success_between_failures_resets(self):
        from orchestrator.v2.robustness import FailureBreaker

        b = FailureBreaker()
        assert b.record("E", "EXECUTE", "boom") is None
        assert b.record("E", "EXECUTE", "boom") is None
        b.reset()
        assert b.record("E", "EXECUTE", "boom") is None
        assert b.record("E", "EXECUTE", "boom") is None
        assert b.record("E", "EXECUTE", "boom") is not None


def test_validate_phase_artifacts_loads_bundle_context(tmp_path):
    """R11e: repair path sees bundle hypotheses (finding_ref check runs)."""
    import json as _json
    from orchestrator.v2.validators import validate_phase_artifacts
    idir = tmp_path / "runs" / "iter-1"
    idir.mkdir(parents=True)
    (idir / "bundle.json").write_text(_json.dumps({"hypotheses": [{"id": "h1"}]}))
    (idir / "principle_updates.json").write_text(_json.dumps({"updates": [
        {"id": "p1", "text": "t", "finding_ref": "h9", "action": "add"},
    ]}))
    errors = validate_phase_artifacts(tmp_path, idir, ["principle_updates"])
    assert any("h9" in e for e in errors)
