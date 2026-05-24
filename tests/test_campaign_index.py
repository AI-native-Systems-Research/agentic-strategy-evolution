"""Behavioral tests for the campaign index (#126 Phase A).

Each function under test takes a search/campaign root on disk and returns
JSON-friendly summaries. Tests synthesize realistic on-disk shapes and
assert on the returned data — never on internal helpers or which files
the function happened to read in what order.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.campaign_index import (
    compare_iterations,
    get_arm_results,
    list_campaigns,
    search_principles,
)


def _make_campaign(
    root: Path, run_id: str,
    *, phase: str = "DONE", iteration: int = 3, completed: int = 3,
    principles: list[dict] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps({
        "run_id": run_id, "phase": phase, "iteration": iteration,
    }))
    rows = [{"iteration": i + 1, "outcome": "experiment_valid"}
            for i in range(completed)]
    (root / "ledger.json").write_text(json.dumps({"iterations": rows}))
    (root / "principles.json").write_text(json.dumps({
        "principles": principles or [],
    }))
    return root


# ─── list_campaigns ─────────────────────────────────────────────────────────

class TestListCampaigns:

    def test_returns_three_synthesized_campaigns(self, tmp_path):
        repo = tmp_path / "repo"
        nous = repo / ".nous"
        for rid, phase in [("alpha", "DONE"), ("beta", "EXECUTE_ANALYZE"), ("gamma", "DONE")]:
            _make_campaign(nous / rid, rid, phase=phase, iteration=2, completed=2)

        out = list_campaigns(tmp_path)

        assert [c["run_id"] for c in out] == ["alpha", "beta", "gamma"]
        assert all(c["completed_iterations"] == 2 for c in out)
        assert {c["phase"] for c in out} == {"DONE", "EXECUTE_ANALYZE"}

    def test_query_filters_by_run_id_substring(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "saturation-detect", "saturation-detect")
        _make_campaign(nous / "throughput-bench", "throughput-bench")

        out = list_campaigns(tmp_path, query="saturation")
        assert [c["run_id"] for c in out] == ["saturation-detect"]

    def test_status_filters_phase(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "a", "a", phase="DONE")
        _make_campaign(nous / "b", "b", phase="EXECUTE_ANALYZE")

        out = list_campaigns(tmp_path, status="DONE")
        assert [c["run_id"] for c in out] == ["a"]

    def test_active_principle_count_filters_retired(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "x", "x", principles=[
            {"id": "p1", "status": "active", "statement": "A"},
            {"id": "p2", "status": "retired", "statement": "B"},
            {"id": "p3", "status": "active", "statement": "C"},
        ])

        out = list_campaigns(tmp_path)
        assert out[0]["active_principles"] == 2

    def test_results_are_sorted_for_determinism(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        for rid in ["zeta", "alpha", "mu"]:
            _make_campaign(nous / rid, rid)

        out = list_campaigns(tmp_path)
        assert [c["run_id"] for c in out] == ["alpha", "mu", "zeta"]

    def test_empty_search_root_returns_empty_list(self, tmp_path):
        assert list_campaigns(tmp_path) == []

    def test_repo_path_is_resolved_when_under_dot_nous(self, tmp_path):
        repo = tmp_path / "myrepo"
        nous = repo / ".nous"
        _make_campaign(nous / "x", "x")

        out = list_campaigns(tmp_path)
        assert out[0]["repo"] == str(repo.resolve())


# ─── search_principles ────────────────────────────────────────────────────

class TestSearchPrinciples:

    def test_finds_principle_by_substring_in_statement(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "x", "x", principles=[
            {"id": "p1", "status": "active",
             "statement": "Saturation flattens discriminatory power of binary gating."},
            {"id": "p2", "status": "active", "statement": "unrelated."},
        ])

        out = search_principles(tmp_path, "ordinal scheduling")
        assert out == []

        out = search_principles(tmp_path, "saturation")
        assert len(out) == 1
        assert out[0]["principle"]["id"] == "p1"
        assert out[0]["run_id"] == "x"

    def test_case_insensitive_match(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "x", "x", principles=[
            {"id": "p1", "status": "active",
             "statement": "Saturation flattens discriminatory power."},
        ])

        out = search_principles(tmp_path, "SATURATION")
        assert len(out) == 1

    def test_skips_retired_by_default(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "x", "x", principles=[
            {"id": "p1", "status": "retired",
             "statement": "Old saturation thinking."},
            {"id": "p2", "status": "active",
             "statement": "Saturation is the new black."},
        ])

        out = search_principles(tmp_path, "saturation")
        assert [h["principle"]["id"] for h in out] == ["p2"]

    def test_only_active_false_includes_retired(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "x", "x", principles=[
            {"id": "p1", "status": "retired",
             "statement": "Old saturation thinking."},
        ])

        out = search_principles(tmp_path, "saturation", only_active=False)
        assert len(out) == 1

    def test_results_are_sorted_for_determinism(self, tmp_path):
        nous = tmp_path / "repo" / ".nous"
        _make_campaign(nous / "z", "z", principles=[
            {"id": "p9", "status": "active", "statement": "saturation thing."},
        ])
        _make_campaign(nous / "a", "a", principles=[
            {"id": "p1", "status": "active", "statement": "saturation thing."},
        ])

        out = search_principles(tmp_path, "saturation")
        assert [h["run_id"] for h in out] == ["a", "z"]


# ─── get_arm_results ──────────────────────────────────────────────────────

class TestGetArmResults:

    def test_aggregates_seeds_under_arm(self, tmp_path):
        camp = tmp_path / "campaign"
        results = camp / "runs" / "iter-2" / "results" / "h-main"
        (results / "seed-1").mkdir(parents=True)
        (results / "seed-1" / "out.json").write_text("{}")
        (results / "seed-2").mkdir()
        (results / "seed-2" / "out.json").write_text("{}")
        (results / "seed-2" / "log.txt").write_text("...")

        out = get_arm_results(camp, iteration=2, arm="h-main")
        assert out["arm"] == "h-main"
        assert out["iteration"] == 2
        assert [s["seed"] for s in out["seeds"]] == ["seed-1", "seed-2"]
        # File listing is relative to campaign_root, sorted.
        seed2_files = out["seeds"][1]["files"]
        assert all(f.startswith("runs/iter-2/results/h-main/seed-2/") for f in seed2_files)

    def test_missing_arm_returns_empty_seeds(self, tmp_path):
        camp = tmp_path / "campaign"
        camp.mkdir()
        out = get_arm_results(camp, iteration=1, arm="nonexistent")
        assert out == {"arm": "nonexistent", "iteration": 1, "seeds": []}


# ─── compare_iterations ────────────────────────────────────────────────────

class TestCompareIterations:

    def _write_findings(self, root: Path, n: int, arms: list[dict]):
        d = root / "runs" / f"iter-{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "findings.json").write_text(json.dumps({"arms": arms}))

    def test_arm_status_change_appears_in_delta(self, tmp_path):
        self._write_findings(tmp_path, 1, [
            {"arm_id": "h-main", "status": "CONFIRMED"},
            {"arm_id": "h-ablation", "status": "CONFIRMED"},
        ])
        self._write_findings(tmp_path, 2, [
            {"arm_id": "h-main", "status": "REFUTED"},
            {"arm_id": "h-ablation", "status": "CONFIRMED"},
        ])

        out = compare_iterations(tmp_path, 1, 2)
        changes = out["delta"]["arm_status_changes"]
        assert {"arm_id": "h-main", "from": "CONFIRMED", "to": "REFUTED"} in changes
        # Unchanged arm should NOT appear.
        assert all(c["arm_id"] != "h-ablation" for c in changes)

    def test_principles_added_diff_is_set_difference(self, tmp_path):
        # Iter 1 had {p1}. Iter 2 has {p1, p2, p3}.
        d1 = tmp_path / "runs" / "iter-1"
        d1.mkdir(parents=True)
        (d1 / "principle_updates.json").write_text(json.dumps([
            {"id": "p1", "statement": "A"},
        ]))
        d2 = tmp_path / "runs" / "iter-2"
        d2.mkdir(parents=True)
        (d2 / "principle_updates.json").write_text(json.dumps([
            {"id": "p1", "statement": "A"},
            {"id": "p2", "statement": "B"},
            {"id": "p3", "statement": "C"},
        ]))
        # Findings can be empty for this assertion.
        self._write_findings(tmp_path, 1, [])
        self._write_findings(tmp_path, 2, [])

        out = compare_iterations(tmp_path, 1, 2)
        assert out["delta"]["principles_added"] == ["p2", "p3"]

    def test_repeated_calls_return_byte_equal_output(self, tmp_path):
        self._write_findings(tmp_path, 1, [{"arm_id": "h-main", "status": "CONFIRMED"}])
        self._write_findings(tmp_path, 2, [{"arm_id": "h-main", "status": "REFUTED"}])

        a = json.dumps(compare_iterations(tmp_path, 1, 2), sort_keys=True)
        b = json.dumps(compare_iterations(tmp_path, 1, 2), sort_keys=True)
        assert a == b
