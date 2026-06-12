"""Integration tests for the iteration-finalize seam (issue #177, #179).

The sort_bench dry-run on 2026-05-25 surfaced a Phase-A-without-Phase-B
gap: `update_best_found` shipped in PR #172 with passing unit tests, but
no production code path called it after `findings.json` was finalized,
so `best_found.json` was never written during a real `nous run`.

`principles_classifier.classify_principles` (issue #179) has the same
shape: shipping the function alone wouldn't help unless the iteration
loop calls it before merging principle_updates into principles.json.

Test contract:
  - `finalize_iteration(work_dir, iter_dir, iteration, campaign)` is the
    public seam. After it runs:
      * `best_found.json` exists at work_dir root with non-empty `top_k`
      * `principles.json` reflects merged principles
      * (#179) merged principles have `empirical_content` /
        `derivation_type` set when the statement is classifiable
  - Driving with fixture findings (no LLM, no live calls) catches the
    same gap that ~205 unit tests missed.
  - Backward-compat: a campaign without an `objective:` block still
    produces `best_found.json` via the legacy status-based ranking.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.iteration import finalize_iteration


def _write_state(work_dir: Path, *, phase: str = "HUMAN_FINDINGS_GATE") -> None:
    (work_dir / "state.json").write_text(json.dumps({
        "phase": phase, "iteration": 1, "run_id": "demo",
        "family": "test", "timestamp": "2026-05-25T00:00:00Z",
    }))


def _write_principles_template(work_dir: Path, principles: list | None = None) -> None:
    (work_dir / "principles.json").write_text(json.dumps({
        "principles": principles or [],
    }))


def _arm_result(arm_type: str, status: str, metadata: dict | None = None) -> dict:
    return {
        "arm_type": arm_type,
        "predicted": "p", "observed": "o",
        "status": status, "error_type": None, "diagnostic_note": "n",
        "metadata": metadata or {},
    }


def _write_findings(iter_dir: Path, *, arms: list[dict]) -> None:
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "findings.json").write_text(json.dumps({
        "iteration": 1,
        "bundle_ref": "runs/iter-1/bundle.yaml",
        "arms": arms,
        "experiment_valid": True,
        "discrepancy_analysis": "",
    }))


def _write_principle_updates(iter_dir: Path, updates: list[dict]) -> None:
    (iter_dir / "principle_updates.json").write_text(json.dumps(updates))


def _principle(*, pid: str, statement: str, **extra) -> dict:
    p = {
        "id": pid, "statement": statement, "confidence": "medium",
        "regime": "", "evidence": [], "contradicts": [],
        "extraction_iteration": 1, "mechanism": "",
        "applicability_bounds": "", "superseded_by": None,
        "status": "active", "category": "domain",
    }
    p.update(extra)
    return p


def _campaign(objective: dict | None = None) -> dict:
    c: dict = {
        "research_question": "q?",
        "run_id": "demo",
        "max_iterations": 1,
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
    }
    if objective is not None:
        c["objective"] = objective
    return c


# ─── #177: best_found.json is written during finalize ─────────────────────


class TestFinalizeWritesBestFound:
    def test_finalize_writes_best_found_json(self, tmp_path: Path) -> None:
        """The bug from the sort_bench run: this file was missing after
        a real iteration. After fix, it exists with non-empty top_k."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        _write_state(work_dir)
        _write_principles_template(work_dir)
        _write_findings(iter_dir, arms=[
            _arm_result("h-main", "CONFIRMED",
                        {"compound_return": 0.85, "candidate_id": "winner"}),
            _arm_result("h-control-negative", "CONFIRMED"),
        ])
        _write_principle_updates(iter_dir, [])

        finalize_iteration(
            work_dir=work_dir, iter_dir=iter_dir, iteration=1,
            campaign=_campaign(objective={
                "weights": {"compound_return": 1.0},
                "deploy_threshold": 0.05,
            }),
        )

        bf_path = work_dir / "best_found.json"
        assert bf_path.exists(), (
            "best_found.json must exist after finalize (regression for #177)"
        )
        payload = json.loads(bf_path.read_text())
        assert payload["top_k"], "top_k must be non-empty for a CONFIRMED iteration"
        assert payload["top_k"][0]["score"] > 0

    def test_finalize_uses_legacy_fallback_when_no_objective(
        self, tmp_path: Path,
    ) -> None:
        """A campaign without `objective:` still gets best_found.json via
        the legacy status-based ranking (CONFIRMED=1.0, etc.). This
        means the sort_bench-style campaign — which didn't declare an
        objective — would have had a populated best_found.json on day
        one if the wire-up had been there."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        _write_state(work_dir)
        _write_principles_template(work_dir)
        _write_findings(iter_dir, arms=[
            _arm_result("h-main", "CONFIRMED"),
            _arm_result("h-main", "REFUTED"),
        ])
        _write_principle_updates(iter_dir, [])

        finalize_iteration(
            work_dir=work_dir, iter_dir=iter_dir, iteration=1,
            campaign=_campaign(),  # no objective
        )

        payload = json.loads((work_dir / "best_found.json").read_text())
        assert payload["top_k"], "legacy fallback must still populate top_k"
        # Scores: CONFIRMED=1.0, REFUTED=0.0, ordered descending
        assert payload["top_k"][0]["score"] == 1.0
        assert payload["top_k"][-1]["score"] == 0.0

    def test_finalize_uses_objective_preset(self, tmp_path: Path) -> None:
        """Campaigns can declare a preset instead of an explicit objective."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        _write_state(work_dir)
        _write_principles_template(work_dir)
        _write_findings(iter_dir, arms=[
            _arm_result("h-main", "CONFIRMED", {
                "compound_return": 0.9,
                "walk_forward_consistency": 0.8,
                "interpretability": 0.7,
                "operational_simplicity": 0.6,
                "candidate_id": "preset-winner",
            }),
        ])
        _write_principle_updates(iter_dir, [])

        c = _campaign()
        c["objective_preset"] = "compound-return-style"
        finalize_iteration(
            work_dir=work_dir, iter_dir=iter_dir, iteration=1, campaign=c,
        )

        payload = json.loads((work_dir / "best_found.json").read_text())
        assert payload["top_k"][0]["candidate_id"].endswith("preset-winner")
        # compound-return-style weights: 0.5*0.9 + 0.3*0.8 + 0.1*0.7 + 0.1*0.6
        assert payload["top_k"][0]["score"] == pytest.approx(0.82)


# ─── Tolerance for missing/empty fixtures ────────────────────────────────


class TestFinalizeToleratesPartialFixtures:
    def test_finalize_no_findings_no_crash(self, tmp_path: Path) -> None:
        """Defensive: if findings.json doesn't exist (caller error),
        finalize should not crash. update_best_found returns empty
        top_k in that case."""
        work_dir = tmp_path / "campaign"
        work_dir.mkdir()
        iter_dir = work_dir / "runs" / "iter-1"
        iter_dir.mkdir(parents=True)
        _write_state(work_dir)
        _write_principles_template(work_dir)

        # No findings.json, no principle_updates.json — finalize still runs.
        finalize_iteration(
            work_dir=work_dir, iter_dir=iter_dir, iteration=1,
            campaign=_campaign(),
        )
        # best_found.json IS still written (with empty top_k); that's what
        # the deployment recommendation (#178) reads to decide its caveat.
        assert (work_dir / "best_found.json").exists()
        payload = json.loads((work_dir / "best_found.json").read_text())
        assert payload["top_k"] == []
