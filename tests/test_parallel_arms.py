"""Behavioral tests for the parallel-arm orchestration (#123 Phase A)."""
from __future__ import annotations

import json

import pytest

from orchestrator.parallel_arms import (
    ArmUnit,
    ArmUnitResult,
    failed_units,
    merge_unit_results,
    partition_plan,
    run_units,
)


# ─── Plan partitioning ─────────────────────────────────────────────────────

class TestPartitionPlan:

    def test_single_arm_single_condition_default_seed(self):
        plan = {"arms": [{
            "arm_id": "h-main",
            "conditions": [{"name": "baseline", "command": "./blis run"}],
        }]}
        units = partition_plan(plan)
        assert len(units) == 1
        assert units[0].arm_id == "h-main"
        assert units[0].seed == "seed-1"
        assert units[0].condition_name == "baseline"
        assert units[0].command == "./blis run"

    def test_multi_seed_condition_fans_out(self):
        plan = {"arms": [{
            "arm_id": "h-main",
            "conditions": [{
                "name": "x", "command": "./run",
                "seeds": ["s1", "s2", "s3"],
            }],
        }]}
        units = partition_plan(plan)
        assert len(units) == 3
        assert sorted(u.seed for u in units) == ["s1", "s2", "s3"]

    def test_multiple_arms_and_conditions(self):
        plan = {"arms": [
            {"arm_id": "h-main", "conditions": [
                {"name": "a", "command": "./a"},
                {"name": "b", "command": "./b"},
            ]},
            {"arm_id": "h-ablation", "conditions": [
                {"name": "c", "command": "./c"},
            ]},
        ]}
        units = partition_plan(plan)
        assert len(units) == 3
        ids = sorted((u.arm_id, u.condition_name) for u in units)
        assert ids == [("h-ablation", "c"), ("h-main", "a"), ("h-main", "b")]

    def test_relative_results_dir_does_not_overlap(self):
        plan = {"arms": [{
            "arm_id": "h-main",
            "conditions": [{
                "name": "x", "command": "./run", "seeds": ["s1", "s2"],
            }],
        }]}
        units = partition_plan(plan)
        dirs = {u.relative_results_dir for u in units}
        assert len(dirs) == 2  # s1 and s2 land in different paths

    def test_skips_arms_without_command(self):
        plan = {"arms": [{
            "arm_id": "h-main",
            "conditions": [{"name": "no-cmd"}],
        }]}
        assert partition_plan(plan) == []


# ─── Run units ─────────────────────────────────────────────────────────────

class _RecordingRunner:
    def __init__(self, statuses: dict[str, str] | None = None):
        self.calls: list[ArmUnit] = []
        self.statuses = statuses or {}

    def __call__(self, unit: ArmUnit) -> ArmUnitResult:
        self.calls.append(unit)
        status = self.statuses.get(unit.arm_id, "complete")
        return ArmUnitResult(
            unit=unit, status=status, duration_ms=100,
            output_files=[f"{unit.relative_results_dir}/out.json"],
        )


class TestRunUnits:

    def test_results_returned_in_input_order(self):
        units = [
            ArmUnit("h-main", "s1", "x", "./a"),
            ArmUnit("h-main", "s2", "x", "./a"),
            ArmUnit("h-ablation", "s1", "y", "./b"),
        ]
        runner = _RecordingRunner()
        results = run_units(units, runner=runner)
        assert [r.unit.seed for r in results] == ["s1", "s2", "s1"]

    def test_runner_exception_becomes_failed_unit(self):
        units = [ArmUnit("h-main", "s1", "x", "./a")]

        def crash(_):
            raise RuntimeError("boom")

        results = run_units(units, runner=crash)
        assert results[0].status == "failed"
        assert "boom" in results[0].error
        assert "RuntimeError" in results[0].error

    def test_max_parallel_must_be_positive(self):
        with pytest.raises(ValueError):
            run_units([], runner=_RecordingRunner(), max_parallel=0)


# ─── Merge ─────────────────────────────────────────────────────────────────

class TestMergeUnitResults:

    def _results(self) -> list[ArmUnitResult]:
        return [
            ArmUnitResult(
                unit=ArmUnit("h-main", "s1", "x", "./a"),
                status="complete", duration_ms=100,
                output_files=["results/h-main/s1/out.json"],
            ),
            ArmUnitResult(
                unit=ArmUnit("h-main", "s2", "x", "./a"),
                status="complete", duration_ms=120,
                output_files=["results/h-main/s2/out.json"],
            ),
            ArmUnitResult(
                unit=ArmUnit("h-ablation", "s1", "y", "./b"),
                status="failed", error="exit 1",
            ),
        ]

    def test_arms_grouped_by_arm_id(self):
        out = merge_unit_results(self._results())
        ids = [a["arm_id"] for a in out["arms"]]
        # Sorted for determinism.
        assert ids == ["h-ablation", "h-main"]

    def test_arm_status_failed_when_any_unit_failed(self):
        out = merge_unit_results(self._results())
        by_id = {a["arm_id"]: a for a in out["arms"]}
        assert by_id["h-ablation"]["status"] == "failed"
        assert by_id["h-main"]["status"] == "complete"

    def test_failed_count_correct(self):
        out = merge_unit_results(self._results())
        assert out["failed_unit_count"] == 1
        assert out["total_unit_count"] == 3

    def test_byte_equal_across_repeated_calls(self):
        a = json.dumps(merge_unit_results(self._results()), sort_keys=True)
        b = json.dumps(merge_unit_results(self._results()), sort_keys=True)
        assert a == b

    def test_units_within_arm_sorted_by_seed_and_condition(self):
        results = [
            ArmUnitResult(unit=ArmUnit("h-main", "s2", "b", "./x"), status="complete"),
            ArmUnitResult(unit=ArmUnit("h-main", "s1", "a", "./x"), status="complete"),
            ArmUnitResult(unit=ArmUnit("h-main", "s1", "b", "./x"), status="complete"),
        ]
        out = merge_unit_results(results)
        seeds = [u["seed"] for u in out["arms"][0]["units"]]
        conds = [u["condition"] for u in out["arms"][0]["units"]]
        assert list(zip(seeds, conds)) == [("s1", "a"), ("s1", "b"), ("s2", "b")]


# ─── Partial-retry helper ──────────────────────────────────────────────────

class TestFailedUnits:

    def test_returns_only_failed_units(self):
        results = [
            ArmUnitResult(unit=ArmUnit("h-main", "s1", "x", "./a"), status="complete"),
            ArmUnitResult(unit=ArmUnit("h-main", "s2", "x", "./a"), status="failed"),
            ArmUnitResult(unit=ArmUnit("h-ablation", "s1", "y", "./b"), status="failed"),
        ]
        failed = failed_units(results)
        assert len(failed) == 2
        assert all(r.arm_id != "h-main" or r.seed == "s2" for r in failed)
