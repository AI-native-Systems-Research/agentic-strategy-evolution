"""Behavioral tests for adaptive sub-arm sweeps (issue #165).

Replaces hand-rolled parameter grids with sampler-driven adaptive
search when an arm declares a scalar `sweep:` block. Default sampler
lazily resolves to Optuna; tests inject deterministic fakes.

Test contract:
  - Assert convergence behavior for known evaluator surfaces
    (decisive boundary, flat metric, monotone).
  - Assert the schema additively accepts arms[].sweep.
  - Assert partition_plan + extract_sweep_specs cleanly partition
    a mixed plan with no overlap.
  - Assert injected sampler= replaces the default — no `import optuna`
    in the import path of the test.
  - Conftest hard-fails any test that invokes Study.optimize.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.arm_sweep import (
    SweepResult,
    SweepSpec,
    SweepTrial,
    run_sweep,
)
from orchestrator.parallel_arms import (
    extract_sweep_specs,
    partition_plan,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _arm(*, arm_type: str = "h-main", sweep: dict | None = None) -> dict:
    arm: dict = {
        "type": arm_type,
        "prediction": "p", "mechanism": "m", "diagnostic": "d",
    }
    if sweep is not None:
        arm["sweep"] = sweep
    return arm


def _bundle(arms: list[dict]) -> dict:
    return {
        "metadata": {"iteration": 1, "family": "test", "research_question": "q?"},
        "arms": arms,
    }


# ─── Deterministic test samplers (the seam exists for exactly this) ──────


def _grid_sampler(history: list[SweepTrial], spec: SweepSpec) -> dict[str, float]:
    """Evenly partition the domain over the budget."""
    step = (spec.high - spec.low) / max(spec.budget - 1, 1)
    next_x = spec.low + step * len(history)
    return {spec.param: next_x}


def _bisection_sampler(history: list[SweepTrial], spec: SweepSpec) -> dict[str, float]:
    """Binary-search-by-objective. For minimization with a step-function
    objective, this converges to the boundary in log(domain/precision) steps."""
    lo, hi = spec.low, spec.high
    for trial in history:
        x = trial.params[spec.param]
        if trial.objective_value > 0:  # too high — boundary is below
            hi = min(hi, x)
        else:                          # too low — boundary is above
            lo = max(lo, x)
    return {spec.param: (lo + hi) / 2}


# ─── Convergence on known evaluator surfaces ──────────────────────────────


class TestRunSweepConvergence:
    def test_decisive_boundary_converges_within_budget(self) -> None:
        """Step function: f(x) = 1 if x < 5 else 0. Bisection finds boundary in ~log2(10)≈4 trials."""
        spec = SweepSpec(param="rate", low=0.0, high=10.0, budget=8)

        def evaluator(params: dict[str, float]) -> float:
            # Distance from boundary at x=5; minimization target.
            return abs(params["rate"] - 5.0)

        result = run_sweep(spec, evaluator, sampler=_bisection_sampler)
        assert result.best_value < 0.5  # within 5% of the domain
        assert abs(result.best_params["rate"] - 5.0) < 0.5
        assert len(result.trials) == spec.budget

    def test_flat_metric_samples_cover_domain(self) -> None:
        """Constant evaluator: best is the first trial; grid sampler still spans the domain."""
        spec = SweepSpec(param="rate", low=0.0, high=10.0, budget=5)

        def evaluator(params: dict[str, float]) -> float:
            return 0.42

        result = run_sweep(spec, evaluator, sampler=_grid_sampler)
        rates = sorted(t.params["rate"] for t in result.trials)
        assert rates[0] == pytest.approx(0.0)
        assert rates[-1] == pytest.approx(10.0)
        assert all(t.objective_value == 0.42 for t in result.trials)

    def test_returns_best_trial(self) -> None:
        """best_params/best_value are the argmin/min over observed trials."""
        spec = SweepSpec(param="x", low=0.0, high=4.0, budget=5)

        def evaluator(params: dict[str, float]) -> float:
            x = params["x"]
            return (x - 2.0) ** 2  # minimum at x=2

        result = run_sweep(spec, evaluator, sampler=_grid_sampler)
        # Grid passes through x=2.0 exactly at trial index 2 of 5.
        assert result.best_value == pytest.approx(0.0)
        assert result.best_params["x"] == pytest.approx(2.0)


# ─── Maximization works the same way ──────────────────────────────────────


class TestRunSweepDirection:
    def test_maximize_returns_largest_value(self) -> None:
        spec = SweepSpec(
            param="x", low=0.0, high=4.0, budget=5, direction="maximize",
        )

        def evaluator(params: dict[str, float]) -> float:
            return -((params["x"] - 3.0) ** 2)  # maximum at x=3

        result = run_sweep(spec, evaluator, sampler=_grid_sampler)
        assert result.best_params["x"] == pytest.approx(3.0)


# ─── Sampler injection: default never imports optuna at test time ─────────


class TestSamplerInjection:
    def test_injected_sampler_replaces_default(self) -> None:
        spec = SweepSpec(param="x", low=0.0, high=1.0, budget=3)
        invocations: list[int] = []

        def fake_sampler(history, spec):
            invocations.append(len(history))
            return {"x": 0.5}

        run_sweep(spec, lambda p: 1.0, sampler=fake_sampler)
        assert invocations == [0, 1, 2]

    def test_invalid_spec_rejected(self) -> None:
        with pytest.raises(ValueError, match="budget"):
            SweepSpec(param="x", low=0.0, high=1.0, budget=0)
        with pytest.raises(ValueError, match="domain"):
            SweepSpec(param="x", low=1.0, high=0.0, budget=3)
        with pytest.raises(ValueError, match="direction"):
            SweepSpec(param="x", low=0.0, high=1.0, budget=3, direction="diagonal")


# ─── partition_plan and extract_sweep_specs cooperate cleanly ─────────────


class TestPartitionPlanWithSweep:
    def test_sweep_arm_excluded_from_partition_plan(self) -> None:
        """Sweep arms don't become ArmUnits — they're partitioned separately."""
        plan = {
            "arms": [
                {"arm_id": "h-main", "sweep": {
                    "param": "rate", "low": 0.0, "high": 10.0, "budget": 5,
                }, "conditions": []},
            ],
        }
        units = partition_plan(plan)
        assert units == []

    def test_non_sweep_arms_partition_unchanged(self) -> None:
        """Legacy non-sweep arms produce ArmUnits as today."""
        plan = {
            "arms": [
                {"arm_id": "h-main", "conditions": [
                    {"name": "baseline", "command": "echo a", "seeds": ["s1", "s2"]},
                ]},
            ],
        }
        units = partition_plan(plan)
        assert len(units) == 2
        assert {u.seed for u in units} == {"s1", "s2"}

    def test_mixed_plan_partitions_correctly(self) -> None:
        """Sweep arms surface via extract_sweep_specs; others via partition_plan."""
        plan = {
            "arms": [
                {"arm_id": "h-main-classic", "conditions": [
                    {"name": "baseline", "command": "echo a", "seeds": ["s1"]},
                ]},
                {"arm_id": "h-main-swept", "sweep": {
                    "param": "rate", "low": 0.0, "high": 10.0, "budget": 5,
                }, "conditions": []},
            ],
        }
        units = partition_plan(plan)
        specs = extract_sweep_specs(plan)
        assert [u.arm_id for u in units] == ["h-main-classic"]
        assert [(arm_id, s.param) for arm_id, s in specs] == [
            ("h-main-swept", "rate"),
        ]

    def test_extract_sweep_specs_parses_optional_fields(self) -> None:
        plan = {
            "arms": [
                {"arm_id": "a1", "sweep": {
                    "param": "rate", "low": 0.0, "high": 10.0, "budget": 12,
                    "direction": "maximize", "sampler_name": "tpe",
                }, "conditions": []},
            ],
        }
        specs = extract_sweep_specs(plan)
        assert len(specs) == 1
        arm_id, spec = specs[0]
        assert spec.budget == 12
        assert spec.direction == "maximize"
        assert spec.sampler_name == "tpe"


# ─── Schema additive: bundle.schema.yaml accepts arms[].sweep ─────────────


class TestSchemaAcceptsSweep:
    def test_arm_with_sweep_validates(self) -> None:
        bundle = _bundle([_arm(sweep={
            "param": "rate", "low": 0.0, "high": 10.0, "budget": 12,
        })])
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_arm_without_sweep_still_validates(self) -> None:
        bundle = _bundle([_arm()])
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_arm_with_invalid_budget_rejected(self) -> None:
        bundle = _bundle([_arm(sweep={
            "param": "rate", "low": 0.0, "high": 10.0, "budget": 0,
        })])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())

    def test_arm_with_inverted_domain_rejected(self) -> None:
        bundle = _bundle([_arm(sweep={
            "param": "rate", "low": 10.0, "high": 0.0, "budget": 5,
        })])
        # JSON Schema can't express low<high cross-field; ValueError comes
        # from SweepSpec construction during extract_sweep_specs.
        with pytest.raises(ValueError, match="domain"):
            extract_sweep_specs({"arms": [
                {"arm_id": "a", "sweep": bundle["arms"][0]["sweep"]},
            ]})

    def test_arm_with_unknown_direction_rejected(self) -> None:
        bundle = _bundle([_arm(sweep={
            "param": "rate", "low": 0.0, "high": 10.0, "budget": 5,
            "direction": "diagonal",
        })])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())


# ─── Optuna trial-running guard regression ────────────────────────────────


class TestOptunaBlocked:
    def test_optuna_optimize_is_blocked_in_tests(self) -> None:
        """Conftest hard-fails any attempt to run Study.optimize."""
        try:
            import optuna  # type: ignore[import-not-found]
        except ImportError:
            pytest.skip("Optuna not installed in this environment")
        study = optuna.create_study()
        with pytest.raises(RuntimeError, match="Study.optimize"):
            study.optimize(lambda t: 0.0, n_trials=1)


# ─── Result shape ─────────────────────────────────────────────────────────


class TestSweepResultShape:
    def test_result_carries_full_history(self) -> None:
        spec = SweepSpec(param="x", low=0.0, high=4.0, budget=5)
        result = run_sweep(spec, lambda p: p["x"] ** 2, sampler=_grid_sampler)
        assert isinstance(result, SweepResult)
        assert len(result.trials) == 5
        assert all(isinstance(t, SweepTrial) for t in result.trials)
        for i, trial in enumerate(result.trials):
            assert trial.trial_index == i
