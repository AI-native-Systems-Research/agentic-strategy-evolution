"""Behavioral tests for the parallel-arm orchestration (#123 Phase A + B)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestrator.parallel_arms import (
    ArmUnit,
    ArmUnitResult,
    failed_units,
    merge_unit_results,
    partition_plan,
    run_units,
)


@dataclass
class _LocalSDKResult:
    """Local stand-in for SDKResult so this branch doesn't depend on
    sdk_dispatch.py landing first. The real SDKResult is duck-compatible."""
    text: str = ""
    duration_ms: int = 0
    is_error: bool = False
    error_message: str = ""


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


# ─── The bound is real, and ordering survives it ────────────────────────────
#
# `max_parallel` used to be validated and then ignored: `run_units` executed a
# plain sequential loop, so a caller asking for 8 got serial execution with no
# way to detect it. These tests are the ones that would have failed then, and
# they assert the three properties that make the parameter trustworthy rather
# than merely accepted: concurrency actually happens, the ceiling actually
# holds, and position i of the result list is still unit i even when the units
# finish in the opposite order from the one they were submitted in.

class TestRunUnitsConcurrency:

    @staticmethod
    def _units(n: int) -> list[ArmUnit]:
        return [ArmUnit("h-main", f"s{i}", "x", f"./cmd{i}") for i in range(n)]

    def test_bounded_concurrency_beats_the_serial_sum(self):
        """Wall clock, not a mock assertion: four 100ms units under a bound of
        four must finish in well under the 400ms a sequential loop would take."""
        import time

        def slow(unit: ArmUnit) -> ArmUnitResult:
            time.sleep(0.1)
            return ArmUnitResult(unit=unit, status="complete")

        units = self._units(4)
        started = time.monotonic()
        results = run_units(units, runner=slow, max_parallel=4)
        elapsed = time.monotonic() - started

        assert [r.status for r in results] == ["complete"] * 4
        assert elapsed < 0.3, (
            f"four 100ms units under max_parallel=4 took {elapsed:.3f}s; a "
            f"sequential loop would take ~0.4s, so the bound is being ignored"
        )

    def test_never_more_than_max_parallel_in_flight(self):
        """The ceiling is observed, not assumed: each runner call records the
        live count on entry and the peak must never exceed the bound."""
        import threading
        import time

        lock = threading.Lock()
        state = {"live": 0, "peak": 0}

        def tracking(unit: ArmUnit) -> ArmUnitResult:
            with lock:
                state["live"] += 1
                state["peak"] = max(state["peak"], state["live"])
            time.sleep(0.02)
            with lock:
                state["live"] -= 1
            return ArmUnitResult(unit=unit, status="complete")

        results = run_units(self._units(12), runner=tracking, max_parallel=3)

        assert len(results) == 12
        assert state["peak"] <= 3, f"observed {state['peak']} units in flight"
        # ... and the bound was actually exercised, otherwise a runner that
        # happened to serialize would pass the ceiling assertion trivially.
        assert state["peak"] > 1, "no concurrency was observed at all"

    def test_results_are_positional_under_reversed_completion(self):
        """Ordering is a CONTRACT, not a side effect of sequential execution.

        Completion order is scripted to be the exact REVERSE of submission
        order: unit 0 sleeps longest and finishes last. A list appended to by
        completing workers would come back reversed; `merge_unit_results` pairs
        each result with its own unit, so that would silently mis-attribute
        every seed rather than raise.
        """
        import time

        n = 5

        def reversed_completion(unit: ArmUnit) -> ArmUnitResult:
            # s0 sleeps 5 ticks, s4 sleeps 1 -- so s4 completes first.
            idx = int(unit.seed[1:])
            time.sleep(0.02 * (n - idx))
            return ArmUnitResult(unit=unit, status="complete", duration_ms=idx)

        units = self._units(n)
        results = run_units(units, runner=reversed_completion, max_parallel=n)

        assert [r.unit.seed for r in results] == [f"s{i}" for i in range(n)]
        assert [r.unit for r in results] == units
        assert [r.duration_ms for r in results] == list(range(n))

    def test_a_raising_runner_fails_only_its_own_unit_in_position(self):
        """One bad unit must not take down the batch or shift its neighbours."""

        def crash_on_two(unit: ArmUnit) -> ArmUnitResult:
            if unit.seed == "s2":
                raise RuntimeError("boom")
            return ArmUnitResult(unit=unit, status="complete")

        results = run_units(self._units(4), runner=crash_on_two, max_parallel=4)

        assert [r.status for r in results] == [
            "complete", "complete", "failed", "complete",
        ]
        assert results[2].unit.seed == "s2"
        assert "RuntimeError: boom" in results[2].error
        assert all(r.error == "" for i, r in enumerate(results) if i != 2)

    def test_default_is_sequential_and_still_ordered(self):
        """No bound given means the sequential path this function has always
        been -- the concurrent path is opt-in, never a silent default."""
        units = self._units(3)
        runner = _RecordingRunner()
        results = run_units(units, runner=runner)
        assert [r.unit for r in results] == units
        assert runner.calls == units


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


# ─── Phase B: end-to-end with the harness-isolated SDK runner ─────────────


class TestEndToEndWithIsolatedRunner:
    """The full chain: partition_plan -> make_isolated_arm_runner ->
    run_units -> merge_unit_results. The SDK side is injected via a
    fake; per the no-live-LLM policy (CLAUDE.md), no real subagent is
    spawned. The test asserts the orchestration contract — every unit
    is dispatched with isolation=worktree to a non-overlapping results
    dir, failures are isolated, and the merged output is deterministic.
    """

    def _plan(self):
        return {"arms": [
            {"arm_id": "h-main", "conditions": [
                {"name": "x", "command": "./run --arm main"},
            ]},
            {"arm_id": "h-ablation", "conditions": [
                {"name": "y", "command": "./run --arm ablation",
                 "seeds": ["s1", "s2"]},
            ]},
        ]}

    def _success_runner(self):
        SDKResult = _LocalSDKResult  # noqa: N806

        sdk_calls: list[dict] = []

        def sdk_runner(**kwargs):
            sdk_calls.append(kwargs)
            prompt = kwargs.get("prompt", "")
            # Simulate the subagent writing a file in its results dir.
            for line in prompt.splitlines():
                if line.startswith("Write all output files to:"):
                    target = line.split("`", 1)[1].rstrip("`")
                    Path(target).mkdir(parents=True, exist_ok=True)
                    (Path(target) / "out.json").write_text("{}")
            return SDKResult(text="done", duration_ms=120)

        return sdk_runner, sdk_calls

    def test_three_units_dispatched_with_isolation_kwarg(self, tmp_path):
        from orchestrator.worktree import make_isolated_arm_runner

        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir(parents=True)
        sdk_runner, sdk_calls = self._success_runner()

        runner = make_isolated_arm_runner(
            sdk_runner=sdk_runner, repo_path=tmp_path, iter_dir=iter_dir,
        )
        units = partition_plan(self._plan())
        assert len(units) == 3

        results = run_units(units, runner=runner)
        assert len(sdk_calls) == 3
        assert all(c.get("isolation") == "worktree" for c in sdk_calls)

        merged = merge_unit_results(results)
        assert [a["arm_id"] for a in merged["arms"]] == ["h-ablation", "h-main"]
        assert all(a["status"] == "complete" for a in merged["arms"])

    def test_partial_failure_isolated_to_one_arm(self, tmp_path):
        from orchestrator.worktree import make_isolated_arm_runner
        SDKResult = _LocalSDKResult  # noqa: N806

        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir(parents=True)

        def sdk_runner(**kwargs):
            prompt = kwargs.get("prompt", "")
            if "h-ablation" in prompt:
                return SDKResult(
                    text="", is_error=True, error_message="exit 1",
                )
            for line in prompt.splitlines():
                if line.startswith("Write all output files to:"):
                    target = line.split("`", 1)[1].rstrip("`")
                    Path(target).mkdir(parents=True, exist_ok=True)
                    (Path(target) / "out.json").write_text("{}")
            return SDKResult(text="ok")

        runner = make_isolated_arm_runner(
            sdk_runner=sdk_runner, repo_path=tmp_path, iter_dir=iter_dir,
        )
        merged = merge_unit_results(
            run_units(partition_plan(self._plan()), runner=runner)
        )
        by_arm = {a["arm_id"]: a for a in merged["arms"]}
        assert by_arm["h-main"]["status"] == "complete"
        assert by_arm["h-ablation"]["status"] == "failed"
        assert merged["failed_unit_count"] == 2
        assert merged["total_unit_count"] == 3

    def test_no_two_units_share_results_dir(self, tmp_path):
        from orchestrator.worktree import make_isolated_arm_runner

        iter_dir = tmp_path / "iter-1"
        iter_dir.mkdir(parents=True)
        sdk_runner, _ = self._success_runner()
        seen_dirs: list[str] = []

        def capturing(**kwargs):
            for line in kwargs.get("prompt", "").splitlines():
                if line.startswith("Write all output files to:"):
                    seen_dirs.append(line.split("`", 1)[1].rstrip("`"))
            return sdk_runner(**kwargs)

        runner = make_isolated_arm_runner(
            sdk_runner=capturing, repo_path=tmp_path, iter_dir=iter_dir,
        )
        run_units(partition_plan(self._plan()), runner=runner)

        # Acceptance criterion: no two subagents ever write to the same
        # results path.
        assert len(seen_dirs) == 3
        assert len(set(seen_dirs)) == 3
