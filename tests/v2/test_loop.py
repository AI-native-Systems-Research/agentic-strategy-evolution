"""Tests for orchestrator.v2.loop — campaign lifecycle (spec 3.2)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from orchestrator.v2.loop import Campaign, parse_campaign_config, CampaignConfig
from tests.fakes.sdk_client import FakeClient, FakeResultMessage


# ── Minimal valid artifacts ──────────────────────────────────────────────


def _baseline(*, task_type: str = "debug") -> dict:
    return {
        "task_type": task_type,
        "command": "pytest test_bug.py",
        "git_sha": "abc1234",
        "observation": {
            "reproduced": True,
            "symptom": "AssertionError",
            "expected": "pass",
            "actual": "fail",
        },
        "metrics_path": "metrics.csv",
        "noise": {"deterministic": True},
    }


def _problem() -> dict:
    return {
        "task_type": "debug",
        "claims_needed": [
            {"id": "c1", "description": "bug is fixed", "test_method": "pytest"},
        ],
    }


def _bundle() -> dict:
    return {
        "hypotheses": [
            {
                "id": "h1",
                "role": "treatment",
                "family": "f1",
                "mechanism": "fix the off-by-one",
                "prediction": {"metric": "pass_rate", "direction": "increase"},
                "control": "unfixed code",
                "falsified_if": "test still fails",
                "claim_ids": ["c1"],
            },
            {
                "id": "h2",
                "role": "alternative",
                "family": "f2",
                "mechanism": "rewrite the function",
                "prediction": {"metric": "pass_rate", "direction": "increase"},
                "control": "unfixed code",
                "falsified_if": "test still fails",
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
                "command": "pytest test_bug.py",
                "parameters": {},
                "seeds": [42],
            },
            {
                "id": "r2",
                "hypothesis_id": "h1",
                "role": "control",
                "command": "pytest test_bug.py",
                "parameters": {},
                "seeds": [42],
            },
        ],
    }


def _findings(
    *,
    answered: bool = True,
    status: str = "CONFIRMED",
    with_claims: bool = True,
) -> dict:
    claims = []
    if with_claims:
        claims = [
            {
                "claim_id": "c1",
                "metric": "pass_rate",
                "condition": "default",
                "value": 1.0,
            },
        ]
    return {
        "hypotheses": [
            {
                "id": "h1",
                "status": status,
                "error_type": "none",
                "evidence": [],
                "noise_unmeasured": True,
                "noise_reason": "single run",
                "claims": claims,
            },
        ],
        "question_answered": answered,
        "reason": "test passes now",
    }


def _principle_updates(*, count: int = 0) -> dict:
    return {
        "updates": [
            {
                "id": f"p{i}",
                "text": f"principle {i}",
                "finding_ref": "h1",
                "action": "add",
            }
            for i in range(count)
        ],
    }


def _answer() -> dict:
    return {
        "answer": "Fixed the off-by-one bug",
        "deliverable": "patch applied",
        "repro": "pytest test_bug.py",
        "claims": [
            {
                "id": "c1",
                "metric": "pass_rate",
                "value": 1.0,
                "condition": "default",
                "evidence": {"path": "runs/iter-1/results.json", "key": "/pass_rate", "value": 1.0},
            },
        ],
    }


def _answer_turn(work_dir: Path) -> dict:
    """REPORT turn files: answer.json plus the evidence file its claim cites."""
    return {
        str(work_dir / "runs" / "iter-1" / "results.json"): json.dumps({"pass_rate": 1.0}),
        str(work_dir / "answer.json"): json.dumps(_answer()),
    }


def _campaign_yaml(
    *,
    research_question: str = "Is the bug fixable?",
    run_id: str = "test-run",
    max_iterations: int = 3,
    target_name: str = "test-project",
    repo_path: str = "/tmp/repo",
) -> dict:
    return {
        "research_question": research_question,
        "run_id": run_id,
        "max_iterations": max_iterations,
        "target_system": {
            "name": target_name,
            "description": "A test project",
            "repo_path": repo_path,
        },
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _write_artifact(work_dir: Path, relative: str, data: dict) -> str:
    """Write artifact JSON and return the full path as a string."""
    p = work_dir / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return str(p)


def _build_per_turn_files(work_dir: Path, *, answered: bool = True) -> list[dict]:
    """Build per-turn file dicts for a single-iteration campaign.

    Turn order: BASELINE, DESIGN, EXECUTE, REPORT.
    """
    iter_dir = work_dir / "runs" / "iter-1"
    return [
        {
            str(work_dir / "baseline.json"): json.dumps(_baseline()),
        },
        {
            str(iter_dir / "problem.json"): json.dumps(_problem()),
            str(iter_dir / "bundle.json"): json.dumps(_bundle()),
            str(iter_dir / "plan.json"): json.dumps(_plan()),
        },
        {
            str(iter_dir / "findings.json"): json.dumps(
                _findings(answered=answered)
            ),
            str(iter_dir / "principle_updates.json"): json.dumps(
                _principle_updates()
            ),
            str(iter_dir / "results.json"): json.dumps({"pass_rate": 1.0}),  # the answer's evidence
        },
        {
            str(work_dir / "answer.json"): json.dumps(_answer()),
        },
    ]


def _make_script(num_turns: int) -> list[FakeResultMessage]:
    """Build a flat script of N result messages (one per turn)."""
    return [FakeResultMessage(session_id=f"ses-{i}") for i in range(num_turns)]


# ── parse_campaign_config tests ──────────────────────────────────────────


class TestParseCampaignConfig:
    def test_minimal_valid(self):
        raw = _campaign_yaml()
        cfg = parse_campaign_config(raw)
        assert cfg.research_question == "Is the bug fixable?"
        assert cfg.run_id == "test-run"
        assert cfg.max_iterations == 3
        assert cfg.stall_iterations == 2
        assert cfg.min_improvement == 0
        assert cfg.human_gates is False

    def test_all_optional_fields(self):
        raw = _campaign_yaml()
        raw["effort"] = "high"
        raw["stall_iterations"] = 3
        raw["min_improvement"] = 5.0
        raw["human_gates"] = True
        raw["secrets"] = ["API_KEY"]
        raw["task_type"] = "debug"
        cfg = parse_campaign_config(raw)
        assert cfg.effort == "high"
        assert cfg.stall_iterations == 3
        assert cfg.min_improvement == 5.0
        assert cfg.human_gates is True
        assert cfg.secrets == ["API_KEY"]
        assert cfg.task_type == "debug"

    def test_missing_research_question_raises(self):
        raw = _campaign_yaml()
        del raw["research_question"]
        with pytest.raises(ValueError, match="research_question"):
            parse_campaign_config(raw)

    def test_missing_target_system_raises(self):
        raw = _campaign_yaml()
        del raw["target_system"]
        with pytest.raises(ValueError, match="target_system"):
            parse_campaign_config(raw)

    def test_missing_repo_path_raises(self):
        raw = _campaign_yaml()
        del raw["target_system"]["repo_path"]
        with pytest.raises(ValueError, match="repo_path"):
            parse_campaign_config(raw)

    def test_target_system_not_dict_raises(self):
        raw = _campaign_yaml()
        raw["target_system"] = "just-a-string"
        with pytest.raises(ValueError, match="repo_path"):
            parse_campaign_config(raw)

    def test_legacy_keys_warn(self, caplog):
        raw = _campaign_yaml()
        raw["critic"] = True
        raw["arm_sweep"] = True
        with caplog.at_level(logging.WARNING):
            cfg = parse_campaign_config(raw)
        assert any("critic" in r.message for r in caplog.records)
        assert cfg.research_question == "Is the bug fixable?"

    def test_default_max_iterations(self):
        raw = _campaign_yaml()
        del raw["max_iterations"]
        cfg = parse_campaign_config(raw)
        assert cfg.max_iterations == 5


# ── Campaign lifecycle tests ─────────────────────────────────────────────


class TestCampaignLifecycle:
    async def test_single_iteration_answered(self, tmp_path):
        """BASELINE → DESIGN → EXECUTE (answered) → REPORT."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(_campaign_yaml())
        per_turn = _build_per_turn_files(work_dir, answered=True)
        script = _make_script(4)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        campaign = Campaign(config=config, work_dir=work_dir, client_factory=factory)
        result = await campaign.run()

        assert result["stop_reason"] == "answered"
        assert (work_dir / "ledger.json").exists()
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert len(ledger) == 1
        assert ledger[0]["status"] == "ok"
        assert (work_dir / "answer.json").exists()

    async def test_max_iterations(self, tmp_path):
        """Loop runs max_iterations then stops."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(
            _campaign_yaml(max_iterations=2)
        )

        iter1_dir = work_dir / "runs" / "iter-1"
        iter2_dir = work_dir / "runs" / "iter-2"

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(iter1_dir / "problem.json"): json.dumps(_problem()),
                str(iter1_dir / "bundle.json"): json.dumps(_bundle()),
                str(iter1_dir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(iter1_dir / "findings.json"): json.dumps(
                    _findings(answered=False, status="INCONCLUSIVE")
                ),
                str(iter1_dir / "principle_updates.json"): json.dumps(
                    _principle_updates(count=1)
                ),
            },
            {
                str(iter2_dir / "problem.json"): json.dumps(_problem()),
                str(iter2_dir / "bundle.json"): json.dumps(_bundle()),
                str(iter2_dir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(iter2_dir / "findings.json"): json.dumps(
                    _findings(answered=False, status="INCONCLUSIVE")
                ),
                str(iter2_dir / "principle_updates.json"): json.dumps(
                    _principle_updates()
                ),
            },
            _answer_turn(work_dir),
        ]
        # Turns: BASELINE, DESIGN1, EXECUTE1, DESIGN2, EXECUTE2, REPORT
        script = _make_script(6)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        campaign = Campaign(config=config, work_dir=work_dir, client_factory=factory)
        result = await campaign.run()

        assert result["stop_reason"] == "max_iterations"
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert len(ledger) == 2

    async def test_stall_stops(self, tmp_path):
        """Two quiet iterations (no claims, no best, no principles) → stall."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(
            _campaign_yaml(max_iterations=5)
        )

        iter1_dir = work_dir / "runs" / "iter-1"
        iter2_dir = work_dir / "runs" / "iter-2"

        quiet_findings = _findings(
            answered=False, status="INCONCLUSIVE", with_claims=False
        )

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(iter1_dir / "problem.json"): json.dumps(_problem()),
                str(iter1_dir / "bundle.json"): json.dumps(_bundle()),
                str(iter1_dir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(iter1_dir / "findings.json"): json.dumps(quiet_findings),
                str(iter1_dir / "principle_updates.json"): json.dumps(
                    _principle_updates()
                ),
            },
            {
                str(iter2_dir / "problem.json"): json.dumps(_problem()),
                str(iter2_dir / "bundle.json"): json.dumps(_bundle()),
                str(iter2_dir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(iter2_dir / "findings.json"): json.dumps(quiet_findings),
                str(iter2_dir / "principle_updates.json"): json.dumps(
                    _principle_updates()
                ),
            },
            _answer_turn(work_dir),
        ]
        script = _make_script(6)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        campaign = Campaign(config=config, work_dir=work_dir, client_factory=factory)
        result = await campaign.run()

        assert result["stop_reason"] == "stall"
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert len(ledger) == 2


class TestBundleHashLock:
    async def test_hash_match_no_violation(self, tmp_path):
        """Bundle unchanged after EXECUTE → no prereg_violation."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(_campaign_yaml())
        per_turn = _build_per_turn_files(work_dir, answered=True)
        script = _make_script(4)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        campaign = Campaign(config=config, work_dir=work_dir, client_factory=factory)
        await campaign.run()

        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert ledger[0].get("prereg_violation") is False

    async def test_hash_mismatch_records_violation(self, tmp_path):
        """Bundle modified during EXECUTE → prereg_violation recorded."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(_campaign_yaml())
        iter_dir = work_dir / "runs" / "iter-1"

        modified_bundle = _bundle()
        modified_bundle["hypotheses"][0]["mechanism"] = "CHANGED during execute"

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(iter_dir / "problem.json"): json.dumps(_problem()),
                str(iter_dir / "bundle.json"): json.dumps(_bundle()),
                str(iter_dir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(iter_dir / "findings.json"): json.dumps(_findings()),
                str(iter_dir / "principle_updates.json"): json.dumps(
                    _principle_updates()
                ),
                str(iter_dir / "bundle.json"): json.dumps(modified_bundle),
            },
            _answer_turn(work_dir),
        ]
        script = _make_script(4)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        campaign = Campaign(config=config, work_dir=work_dir, client_factory=factory)
        await campaign.run()

        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert ledger[0]["prereg_violation"] is True
        locked = json.loads(
            (iter_dir / ".bundle.locked.json").read_text()
        )
        restored = json.loads((iter_dir / "bundle.json").read_text())
        assert locked == restored


class TestLedger:
    async def test_ledger_fields(self, tmp_path):
        """Ledger entry has required fields per spec."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(_campaign_yaml())
        per_turn = _build_per_turn_files(work_dir, answered=True)
        script = _make_script(4)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        campaign = Campaign(config=config, work_dir=work_dir, client_factory=factory)
        await campaign.run()

        ledger = json.loads((work_dir / "ledger.json").read_text())
        entry = ledger[0]
        assert "iteration" in entry
        assert "bundle_hash" in entry
        assert "claims_changed" in entry
        assert "best_changed" in entry
        assert "principles_changed" in entry
        assert "status" in entry
        assert "stop_reason" in entry

    async def test_ledger_rows_match_schema(self, tmp_path):
        """Rows loop.py writes (incl. the REPORT fields) validate against ledger_entry.schema.json."""
        import jsonschema

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(_campaign_yaml())
        per_turn = _build_per_turn_files(work_dir, answered=True)

        def factory(_opts):
            return FakeClient(script=_make_script(4), per_turn_files=per_turn)

        await Campaign(config=config, work_dir=work_dir, client_factory=factory).run()

        schema_path = Path(__file__).resolve().parents[2] / "orchestrator" / "v2" / "schemas" / "ledger_entry.schema.json"
        schema = json.loads(schema_path.read_text())
        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert {"report_cost_usd", "repro_recorded", "claims_matched_fraction"} <= set(ledger[-1])
        for row in ledger:
            jsonschema.validate(row, schema)


    async def test_final_check_recorded_from_runs_jsonl(self, tmp_path):
        """Spec 3.8: REPORT ends with the final check; repro is proven from runs.jsonl, not re-run."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        (work_dir / "runs.jsonl").write_text(
            json.dumps({"phase": "EXECUTE", "iter": 1, "command": "pytest test_bug.py", "exit_code": 0}) + "\n"
        )
        (work_dir / "runs" / "iter-1").mkdir(parents=True)
        (work_dir / "runs" / "iter-1" / "results.json").write_text(json.dumps({"pass_rate": 1.0}))
        config = parse_campaign_config(_campaign_yaml())
        per_turn = _build_per_turn_files(work_dir, answered=True)
        script = _make_script(4)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        await Campaign(config=config, work_dir=work_dir, client_factory=factory).run()

        entry = json.loads((work_dir / "ledger.json").read_text())[-1]
        assert entry["repro_recorded"] is True
        assert "claims_matched_fraction" in entry
        assert (work_dir / "final_check.json").exists()

    async def test_final_check_repro_missing_from_record(self, tmp_path):
        """A repro command never run in the session is reported as not recorded."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(_campaign_yaml())
        per_turn = _build_per_turn_files(work_dir, answered=True)
        script = _make_script(4)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        await Campaign(config=config, work_dir=work_dir, client_factory=factory).run()

        entry = json.loads((work_dir / "ledger.json").read_text())[-1]
        assert entry["repro_recorded"] is False

class TestPrinciples:
    async def test_principles_accumulate(self, tmp_path):
        """Principles from iteration 1 are saved for iteration 2."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(
            _campaign_yaml(max_iterations=2)
        )

        iter1_dir = work_dir / "runs" / "iter-1"
        iter2_dir = work_dir / "runs" / "iter-2"

        per_turn = [
            {str(work_dir / "baseline.json"): json.dumps(_baseline())},
            {
                str(iter1_dir / "problem.json"): json.dumps(_problem()),
                str(iter1_dir / "bundle.json"): json.dumps(_bundle()),
                str(iter1_dir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(iter1_dir / "findings.json"): json.dumps(
                    _findings(answered=False, status="INCONCLUSIVE")
                ),
                str(iter1_dir / "principle_updates.json"): json.dumps(
                    _principle_updates(count=2)
                ),
            },
            {
                str(iter2_dir / "problem.json"): json.dumps(_problem()),
                str(iter2_dir / "bundle.json"): json.dumps(_bundle()),
                str(iter2_dir / "plan.json"): json.dumps(_plan()),
            },
            {
                str(iter2_dir / "findings.json"): json.dumps(
                    _findings(answered=False, status="INCONCLUSIVE")
                ),
                str(iter2_dir / "principle_updates.json"): json.dumps(
                    _principle_updates()
                ),
            },
            _answer_turn(work_dir),
        ]
        script = _make_script(6)

        def factory(_opts):
            return FakeClient(script=script, per_turn_files=per_turn)

        campaign = Campaign(config=config, work_dir=work_dir, client_factory=factory)
        await campaign.run()

        principles = json.loads(
            (work_dir / "principles.json").read_text()
        )
        assert len(principles) == 2
        assert principles[0]["id"] == "p0"
        assert principles[1]["id"] == "p1"


class TestFakeClientMultiTurn:
    """Verify FakeClient multi-turn support (ResultMessage boundary)."""

    async def test_two_turns(self):
        script = [
            FakeResultMessage(session_id="s1"),
            FakeResultMessage(session_id="s2"),
        ]
        client = FakeClient(script=script)
        await client.connect()

        await client.query("turn-1")
        msgs1 = [m async for m in client.receive_response()]
        assert len(msgs1) == 1
        assert msgs1[0].session_id == "s1"

        await client.query("turn-2")
        msgs2 = [m async for m in client.receive_response()]
        assert len(msgs2) == 1
        assert msgs2[0].session_id == "s2"

    async def test_per_turn_files(self, tmp_path):
        script = [FakeResultMessage(), FakeResultMessage()]
        per_turn = [
            {str(tmp_path / "a.txt"): "hello"},
            {str(tmp_path / "b.txt"): "world"},
        ]
        client = FakeClient(script=script, per_turn_files=per_turn)
        await client.connect()

        await client.query("turn-1")
        assert (tmp_path / "a.txt").read_text() == "hello"
        assert not (tmp_path / "b.txt").exists()

        async for _ in client.receive_response():
            pass

        await client.query("turn-2")
        assert (tmp_path / "b.txt").read_text() == "world"


class TestBaselineValidation:
    async def test_design_rejects_missing_baseline(self, tmp_path):
        """DESIGN must reject when baseline.json is missing."""
        from orchestrator.v2.loop import Campaign, CampaignConfig
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        config = CampaignConfig(
            research_question="test?",
            run_id="test-run",
            max_iterations=1,
            target_system={"repo_path": "/tmp/target"},
        )
        # FakeClient produces results but no baseline.json is written
        script = [FakeResultMessage()] * 5
        client = FakeClient(script=script)
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        with pytest.raises(ValueError, match="baseline.json"):
            await campaign.run()


class TestLedgerPerIteration:
    async def test_ledger_written_after_each_iteration(self, tmp_path):
        """Ledger must be written after each iteration, not just at the end."""
        from orchestrator.v2.loop import Campaign, CampaignConfig, _write_json
        from tests.fakes.sdk_client import FakeClient, FakeResultMessage

        work_dir = tmp_path / "campaign"
        work_dir.mkdir()

        baseline = {
            "task_type": "debug", "command": "test", "git_sha": "abc1234",
            "observation": {"reproduced": True, "symptom": "crash",
                            "expected": 0, "actual": 1},
            "metrics_path": "m.json", "noise": {"deterministic": True},
        }
        iter1 = work_dir / "runs" / "iter-1"
        iter1.mkdir(parents=True)
        findings = {
            "hypotheses": [{
                "id": "h1", "status": "CONFIRMED", "error_type": "none",
                "evidence": [],
                "noise_unmeasured": True, "noise_reason": "n/a",
                "claims": [{"claim_id": "c1", "metric": "m",
                            "condition": "a", "value": 1}],
            }],
            "question_answered": True,
            "reason": "done",
        }

        def write_files_on_turn(turn_idx):
            if turn_idx == 0:
                return {str(work_dir / "baseline.json"): json.dumps(baseline)}
            elif turn_idx == 1:
                return {
                    str(iter1 / "problem.json"): json.dumps(_problem()),
                    str(iter1 / "bundle.json"): json.dumps(_bundle()),
                    str(iter1 / "plan.json"): json.dumps(_plan()),
                }
            elif turn_idx == 2:
                return {
                    str(iter1 / "findings.json"): json.dumps(findings),
                    str(iter1 / "principle_updates.json"): json.dumps({"updates": []}),
                }
            return _answer_turn(work_dir)

        per_turn = [write_files_on_turn(i) for i in range(4)]
        # 4 turns: BASELINE, DESIGN, EXECUTE, REPORT
        script = [FakeResultMessage()] * 4
        client = FakeClient(script=script, per_turn_files=per_turn)

        config = CampaignConfig(
            research_question="test?",
            run_id="test-run",
            max_iterations=1,
            target_system={"repo_path": "/tmp/target"},
        )
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=lambda _opts: client,
        )
        await campaign.run()

        ledger = json.loads((work_dir / "ledger.json").read_text())
        assert len(ledger) == 1
        assert ledger[0]["iteration"] == 1


class TestCwdPassedToSession:
    """Spec 3.1: Campaign passes cwd=<campaign worktree> to Session."""

    async def test_cwd_from_target_system_path(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        target_path = str(tmp_path / "target_repo")

        captured_opts: list = []

        def capturing_factory(opts):
            captured_opts.append(opts)
            return FakeClient(
                script=_make_script(4),
                per_turn_files=_build_per_turn_files(work_dir, answered=True),
            )

        config = CampaignConfig(
            research_question="test?",
            run_id="test-cwd",
            max_iterations=1,
            target_system={"repo_path": target_path},
        )
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=capturing_factory,
        )
        await campaign.run()

        assert len(captured_opts) >= 1
        assert captured_opts[0].cwd == target_path

    async def test_cwd_none_when_no_path(self, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        captured_opts: list = []

        def capturing_factory(opts):
            captured_opts.append(opts)
            return FakeClient(
                script=_make_script(4),
                per_turn_files=_build_per_turn_files(work_dir, answered=True),
            )

        config = CampaignConfig(
            research_question="test?",
            run_id="test-cwd-none",
            max_iterations=1,
            target_system={"repo_path": None},
        )
        campaign = Campaign(
            config=config,
            work_dir=work_dir,
            client_factory=capturing_factory,
        )
        await campaign.run()

        assert getattr(captured_opts[0], "cwd", None) is None


class TestMergePrinciples:
    def test_revise_after_remove(self):
        from orchestrator.v2.loop import _merge_principles

        existing = [{"id": "p1", "text": "a"}, {"id": "p2", "text": "b"}]
        out = _merge_principles(existing, {"updates": [
            {"id": "p1", "action": "remove"},
            {"id": "p2", "action": "revise", "text": "b2"},
        ]})
        assert out == [{"id": "p2", "text": "b2"}]


class TestExperimentCommandsDefault:
    async def test_unset_uses_default_patterns(self, tmp_path):
        config = parse_campaign_config(_campaign_yaml())
        campaign = Campaign(config=config, work_dir=tmp_path, client_factory=lambda _o: None)
        _state, hooks, _opts = campaign._build_hooks_and_session_opts()
        cb = hooks["PostToolUse"][0].hooks[0]
        await cb({"tool_name": "Bash", "tool_input": {"command": "blis run --x"}}, None, {})
        row = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])
        assert row["experiment"] is True


# ── R11e: transient retry inside a campaign ─────────────────────────────


class TestTransientRetryInCampaign:
    async def test_exit_143_on_turn_retried_and_campaign_continues(self, tmp_path, monkeypatch):
        from orchestrator.v2 import session as session_mod
        from claude_agent_sdk import ProcessError

        monkeypatch.setattr(session_mod, "RETRY_DELAYS_S", (0.0, 0.0))
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        config = parse_campaign_config(_campaign_yaml())
        per_turn = _build_per_turn_files(work_dir, answered=True)

        class Flaky(FakeClient):
            calls = 0

            async def query(self, prompt):
                Flaky.calls += 1
                if Flaky.calls == 2:  # DESIGN turn dies once with SIGTERM
                    raise ProcessError("killed", exit_code=143)
                await super().query(prompt)

        client = Flaky(script=_make_script(4), per_turn_files=per_turn)
        campaign = Campaign(config=config, work_dir=work_dir, client_factory=lambda _o: client)
        result = await campaign.run()

        assert result["stop_reason"] == "answered"
        assert (work_dir / "answer.json").exists()


# ── R11e: phase commits on the target checkout ──────────────────────────


def _git(repo: Path, *args: str) -> str:
    import subprocess
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README").write_text("x\n")
    _git(repo, "add", "README")
    _git(repo, "commit", "-qm", "init")
    return repo


def _repo_campaign(repo: Path) -> tuple[Campaign, Path]:
    work_dir = repo / ".nous" / "run-1"
    work_dir.mkdir(parents=True)
    config = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    per_turn = _build_per_turn_files(work_dir, answered=True)
    per_turn[1][str(repo / "src.py")] = "print('fix')\n"  # agent edits code in DESIGN
    client = FakeClient(script=_make_script(4), per_turn_files=per_turn)
    return Campaign(config=config, work_dir=work_dir, client_factory=lambda _o: client), work_dir


class TestCommitPhase:
    async def test_campaign_work_dir_inside_repo_not_committed(self, tmp_path):
        repo = _init_repo(tmp_path)
        campaign, _wd = _repo_campaign(repo)
        await campaign.run()
        tracked = _git(repo, "ls-files").split()
        assert "src.py" in tracked
        assert not any(p.startswith(".nous/") for p in tracked)
        assert "nous: iter-1 DESIGN" in _git(repo, "log", "--format=%s")

    async def test_failed_commit_is_logged_not_raised(self, tmp_path, caplog):
        repo = _init_repo(tmp_path)
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        campaign, _wd = _repo_campaign(repo)
        with caplog.at_level(logging.WARNING):
            result = await campaign.run()
        assert result["stop_reason"] == "answered"
        assert any("commit" in r.message for r in caplog.records)


class TestAnswerEvidenceInRepo:
    async def test_report_copies_evidence_into_repo(self, tmp_path):
        """answer.json is the deliverable: its evidence must resolve from the target repo root too."""
        repo, work_dir = tmp_path / "repo", tmp_path / "work"
        repo.mkdir(); work_dir.mkdir()
        (work_dir / "runs.jsonl").write_text(
            json.dumps({"command": "pytest test_bug.py", "exit_code": 0}) + "\n")
        (work_dir / "runs" / "iter-1").mkdir(parents=True)
        (work_dir / "runs" / "iter-1" / "results.json").write_text(json.dumps({"pass_rate": 1.0}))
        config = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
        per_turn = _build_per_turn_files(work_dir, answered=True)
        client = FakeClient(script=_make_script(4), per_turn_files=per_turn)
        await Campaign(config=config, work_dir=work_dir, client_factory=lambda _o: client).run()

        answer = json.loads((work_dir / "answer.json").read_text())
        claim = answer["claims"][0]
        # Output contract: evidence is a repo-relative path string; the {path,key,value} record is kept
        path = claim["evidence"]
        assert path == "nous_evidence/runs/iter-1/results.json"
        assert claim["evidence_detail"] == {"path": path, "key": "/pass_rate", "value": 1.0}
        assert json.loads((repo / path).read_text()) == {"pass_rate": 1.0}
        assert (work_dir / path).exists()
        check = json.loads((work_dir / "final_check.json").read_text())
        assert check["answer_valid"] is True and check["evidence_errors"] == []


def test_answer_string_evidence_must_exist(tmp_path):
    from orchestrator.v2.validators import ValidatorContext, validate_artifact
    ans = {**_answer(), "claims": [{**_answer()["claims"][0], "evidence": "nous_evidence/missing.json"}]}
    errs = validate_artifact("answer", ans, ValidatorContext(work_dir=tmp_path))
    assert any("missing.json" in e for e in errs)
    (tmp_path / "nous_evidence").mkdir()
    (tmp_path / "nous_evidence" / "missing.json").write_text('{"pass_rate": 1.0}')
    assert validate_artifact("answer", ans, ValidatorContext(work_dir=tmp_path)) == []


def test_export_handles_mixed_and_pre_prefixed_evidence(tmp_path):
    """dbg rep1 (R13): claims mixed {path,key,value} already under nous_evidence/ and bare path strings."""
    repo, work = tmp_path / "ws", tmp_path / "work"
    repo.mkdir(); (work / "nous_evidence").mkdir(parents=True)
    (work / "R1.json").write_text('{"n": 5}')
    (work / "nous_evidence" / "R1.json").write_text('{"n": 5}')
    (work / "answer.json").write_text(json.dumps({**_answer(), "claims": [
        {"id": "C1", "metric": "n", "value": 5, "condition": "c",
         "evidence": {"path": "nous_evidence/R1.json", "key": "/n", "value": 5}},
        {"id": "C2", "metric": "n", "value": 5, "condition": "c", "evidence": "R1.json"},
    ]}))
    cfg = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    Campaign(cfg, work, client_factory=None)._export_evidence()
    claims = json.loads((work / "answer.json").read_text())["claims"]
    assert [c["evidence"] for c in claims] == ["nous_evidence/R1.json"] * 2
    assert claims[0]["evidence_detail"]["key"] == "/n"
    assert (repo / "nous_evidence" / "R1.json").is_file()
    from orchestrator.v2.final_check import check_answer
    assert check_answer(work)["evidence_errors"] == []


async def test_report_repairs_invalid_answer_before_export(tmp_path):
    """Spec 3.5 at REPORT: an invalid answer.json gets a repair turn; the repaired one is exported."""
    repo, work_dir = tmp_path / "repo", tmp_path / "work"
    repo.mkdir(); work_dir.mkdir()
    (work_dir / "runs" / "iter-1").mkdir(parents=True)
    (work_dir / "runs" / "iter-1" / "results.json").write_text(json.dumps({"pass_rate": 1.0}))
    bad = _answer()
    bad["claims"][0]["evidence_ref"] = bad["claims"][0].pop("evidence")
    per_turn = _build_per_turn_files(work_dir, answered=True)
    per_turn[3] = {str(work_dir / "answer.json"): json.dumps(bad)}
    per_turn.append({str(work_dir / "answer.json"): json.dumps(_answer())})
    client = FakeClient(script=_make_script(5), per_turn_files=per_turn)
    cfg = parse_campaign_config(_campaign_yaml(repo_path=str(repo)))
    await Campaign(cfg, work_dir, client_factory=lambda _o: client).run()

    assert "Repair" in client.queries[4] and "answer" in client.queries[4]
    answer = json.loads((work_dir / "answer.json").read_text())
    assert answer["claims"][0]["evidence"] == "nous_evidence/runs/iter-1/results.json"
    assert (repo / "nous_evidence" / "runs" / "iter-1" / "results.json").is_file()


async def test_phase_messages_name_absolute_paths(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "runs" / "iter-1").mkdir(parents=True)
    (work_dir / "runs" / "iter-1" / "results.json").write_text(json.dumps({"pass_rate": 1.0}))
    client = FakeClient(script=_make_script(4), per_turn_files=_build_per_turn_files(work_dir))
    await Campaign(parse_campaign_config(_campaign_yaml()), work_dir,
                   client_factory=lambda _o: client).run()
    q = client.queries
    idir = work_dir / "runs" / "iter-1"
    assert str(work_dir / "baseline.json") in q[0]
    for name in ("problem.json", "bundle.json", "plan.json"):
        assert str(idir / name) in q[1]
    for name in ("findings.json", "principle_updates.json"):
        assert str(idir / name) in q[2]
    assert str(work_dir / "answer.json") in q[3] and str(work_dir / "report.md") in q[3]
    assert "repository root" in q[3]


def test_export_coerces_numeric_string_claim_values(tmp_path):
    """Output contract: claim value is a number. R13 round 3: "114630" passed Nous but not the contract reader."""
    repo, work = tmp_path / "ws", tmp_path / "work"
    repo.mkdir(); work.mkdir()
    (work / "out.txt").write_text("total: 114630 rate: 1.5")
    (work / "answer.json").write_text(json.dumps({**_answer(), "claims": [
        {"id": "C1", "metric": "n", "value": "114630", "condition": "c", "evidence": "out.txt"},
        {"id": "C2", "metric": "r", "value": "1.5", "condition": "c", "evidence": "out.txt"},
        {"id": "C3", "metric": "s", "value": "PASS", "condition": "c", "evidence": "out.txt"},
    ]}))
    Campaign(parse_campaign_config(_campaign_yaml(repo_path=str(repo))), work, client_factory=None)._export_evidence()
    vals = [c["value"] for c in json.loads((work / "answer.json").read_text())["claims"]]
    assert vals == [114630, 1.5, "PASS"]
