"""Tests for orchestrator.v2.final_check (spec 3.8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _make_baseline(work_dir: Path, **overrides) -> dict:
    baseline = {
        "task_type": "debug",
        "command": "python run.py --test",
        "git_sha": "abc123",
        "observation": {"score": 42},
        "noise": {"deterministic": True},
    }
    baseline.update(overrides)
    _write_json(work_dir / "baseline.json", baseline)
    return baseline


def _make_answer(work_dir: Path, **overrides) -> dict:
    answer = {
        "answer": "The bug is in module X.",
        "deliverable": "patch.diff",
        "repro": "python run.py --test",
        "claims": [
            {
                "id": "c1",
                "metric": "score",
                "value": 100,
                "condition": "after fix",
                "evidence": {"path": "runs/iter-1/results.json", "key": "/score", "value": 100},
            }
        ],
    }
    answer.update(overrides)
    _write_json(work_dir / "answer.json", answer)
    return answer


def _make_runs_jsonl(work_dir: Path, entries: list[dict]) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in entries]
    (work_dir / "runs.jsonl").write_text("\n".join(lines) + "\n")


def _make_findings(work_dir: Path, hypotheses: list[dict] | None = None) -> dict:
    findings = {
        "hypotheses": hypotheses or [
            {
                "id": "h1",
                "status": "CONFIRMED",
                "error_type": "none",
                "evidence": [{"path": "results.json", "key": "/score", "value": 100}],
                "noise_sd": 0.0,
                "effect": {"value": 58.0},
            }
        ],
        "question_answered": True,
        "reason": "Bug fixed.",
    }
    idir = work_dir / "runs" / "iter-1"
    idir.mkdir(parents=True, exist_ok=True)
    _write_json(idir / "findings.json", findings)
    return findings


def _make_problem(work_dir: Path, claims_needed: list[dict] | None = None) -> dict:
    problem = {
        "task_type": "debug",
        "claims_needed": claims_needed or [
            {"id": "c1", "description": "score improves", "test_method": "compare"},
        ],
    }
    idir = work_dir / "runs" / "iter-1"
    idir.mkdir(parents=True, exist_ok=True)
    _write_json(idir / "problem.json", problem)
    return problem


class TestReproRecorded:
    def test_repro_true_when_command_in_runs(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path, command="python run.py --test")
        _make_answer(tmp_path)
        _make_findings(tmp_path)
        _make_problem(tmp_path)

        # runs.jsonl contains the baseline command
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        # Evidence file
        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert result["repro_recorded"] is True

    def test_repro_false_when_command_missing(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path, command="python run.py --test")
        _make_answer(tmp_path)
        _make_findings(tmp_path)
        _make_problem(tmp_path)

        # runs.jsonl has different command
        _make_runs_jsonl(tmp_path, [
            {"command": "echo hello", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert result["repro_recorded"] is False

    def test_repro_false_when_no_runs_jsonl(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path, command="python run.py --test")
        _make_answer(tmp_path)
        _make_findings(tmp_path)
        _make_problem(tmp_path)

        idir = tmp_path / "runs" / "iter-1"
        idir.mkdir(parents=True, exist_ok=True)
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert result["repro_recorded"] is False

    def test_repro_not_rerun_by_default(self, tmp_path):
        """check_answer never executes commands — repro check is from records."""
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path, command="python run.py --test")
        _make_answer(tmp_path)
        _make_findings(tmp_path)
        _make_problem(tmp_path)

        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert "rerun" not in result or result.get("rerun") is None


class TestClaimsMatchedFraction:
    def test_all_claims_matched(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_answer(tmp_path, claims=[
            {"id": "c1", "metric": "score", "value": 100, "condition": "after",
             "evidence": {"path": "runs/iter-1/results.json", "key": "/score", "value": 100}},
        ])
        _make_problem(tmp_path, claims_needed=[
            {"id": "c1", "description": "score improves", "test_method": "compare"},
        ])
        _make_findings(tmp_path, hypotheses=[
            {"id": "h1", "status": "CONFIRMED", "error_type": "none",
             "evidence": [{"path": "results.json", "key": "/score", "value": 100}],
             "noise_sd": 0.0, "effect": {"value": 58.0},
             "claims": [{"claim_id": "c1", "metric": "score", "condition": "after", "value": 100}]},
        ])
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert result["claims_matched_fraction"] == 1.0

    def test_partial_claims_matched(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_answer(tmp_path, claims=[
            {"id": "c1", "metric": "score", "value": 100, "condition": "after",
             "evidence": {"path": "runs/iter-1/results.json", "key": "/score", "value": 100}},
        ])
        _make_problem(tmp_path, claims_needed=[
            {"id": "c1", "description": "score improves", "test_method": "compare"},
            {"id": "c2", "description": "latency stable", "test_method": "compare"},
        ])
        # Only c1 has a claim in findings, c2 is not addressed
        _make_findings(tmp_path, hypotheses=[
            {"id": "h1", "status": "CONFIRMED", "error_type": "none",
             "evidence": [{"path": "results.json", "key": "/score", "value": 100}],
             "noise_sd": 0.0, "effect": {"value": 58.0},
             "claims": [{"claim_id": "c1", "metric": "score", "condition": "after", "value": 100}]},
        ])
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert result["claims_matched_fraction"] == 0.5

    def test_no_claims_needed(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_answer(tmp_path)
        _make_problem(tmp_path, claims_needed=[
            {"id": "c1", "description": "score", "test_method": "compare"},
        ])
        _make_findings(tmp_path)
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert 0 <= result["claims_matched_fraction"] <= 1.0


class TestUnmeasuredNoise:
    def test_flags_unmeasured_noise_findings(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_answer(tmp_path)
        _make_problem(tmp_path)
        _make_findings(tmp_path, hypotheses=[
            {
                "id": "h1",
                "status": "CONFIRMED",
                "error_type": "none",
                "evidence": [{"path": "results.json", "key": "/score", "value": 100}],
                "noise_unmeasured": True,
                "noise_reason": "time constraints",
                "effect": {"value": 58.0},
            },
        ])
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert "h1" in result["unmeasured_noise_findings"]

    def test_no_flag_for_measured_noise(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_answer(tmp_path)
        _make_problem(tmp_path)
        _make_findings(tmp_path, hypotheses=[
            {
                "id": "h1",
                "status": "CONFIRMED",
                "error_type": "none",
                "evidence": [{"path": "results.json", "key": "/score", "value": 100}],
                "noise_sd": 1.0,
                "effect": {"value": 58.0},
            },
        ])
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert result["unmeasured_noise_findings"] == []


class TestAnswerValidation:
    def test_valid_answer(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_answer(tmp_path)
        _make_findings(tmp_path)
        _make_problem(tmp_path)
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert result["answer_valid"] is True
        assert result["evidence_errors"] == []

    def test_missing_answer_json(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_findings(tmp_path)
        _make_problem(tmp_path)

        result = check_answer(tmp_path)
        assert result["answer_valid"] is False

    def test_evidence_mismatch_reported(self, tmp_path):
        from orchestrator.v2.final_check import check_answer

        _make_baseline(tmp_path)
        _make_answer(tmp_path, claims=[
            {"id": "c1", "metric": "score", "value": 100, "condition": "after",
             "evidence": {"path": "runs/iter-1/results.json", "key": "/score", "value": 999}},
        ])
        _make_findings(tmp_path)
        _make_problem(tmp_path)
        _make_runs_jsonl(tmp_path, [
            {"command": "python run.py --test", "exit_code": 0, "ts": "2026-01-01T00:00:00Z"},
        ])

        idir = tmp_path / "runs" / "iter-1"
        _write_json(idir / "results.json", {"score": 100})

        result = check_answer(tmp_path)
        assert len(result["evidence_errors"]) > 0


SMOKE2_REPRO = "./blis run --model qwen/qwen3-14b --rate 20 --num-requests 200 --seed 42 --total-kv-blocks 600"
SMOKE2_PREFIX = 'export PATH="$HOME/go-local/go/bin:$PATH"; cd /tmp/ws && '


class TestReproNormalized:
    """Smoke 2: the agent wraps the repro in env/cd prefixes and redirections."""

    def _check(self, tmp_path, rows):
        from orchestrator.v2.final_check import check_answer

        _make_answer(tmp_path, repro=SMOKE2_REPRO)
        _make_runs_jsonl(tmp_path, rows)
        return check_answer(tmp_path)["repro_recorded"]

    def test_smoke2_wrapped_command_matches(self, tmp_path):
        assert self._check(tmp_path, [
            {"command": SMOKE2_PREFIX + SMOKE2_REPRO + " 2>/dev/null", "exit_code": 134},
            {"command": SMOKE2_PREFIX + SMOKE2_REPRO + " 2>&1 | tail -30", "exit_code": 0},
        ]) is True

    def test_different_command_does_not_match(self, tmp_path):
        assert self._check(tmp_path, [
            {"command": SMOKE2_PREFIX + SMOKE2_REPRO.replace("600", "1200") + " 2>/dev/null",
             "exit_code": 0},
        ]) is False

    def test_failed_run_does_not_count(self, tmp_path):
        assert self._check(tmp_path, [
            {"command": SMOKE2_PREFIX + SMOKE2_REPRO + " 2>/dev/null", "exit_code": 134},
        ]) is False
