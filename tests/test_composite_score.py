"""Behavioral tests for composite scoring + best_found.json (issue #168).

Replaces single-metric campaign success with a weighted composite over
multiple deployability dimensions. Each campaign declares weights via
an optional `objective:` block (or a named preset); `best_found.json`
tracks the top-K candidates ranked by score across all iterations.

Test contract:
  - compute_score is pure deterministic math: hand-computed reference matches.
  - ObjectiveSpec rejects malformed weight sums and negative weights.
  - Named presets resolve to known weight maps; unknown names raise.
  - update_best_found scans runs/iter-N/findings.json deterministically
    and writes a schema-valid best_found.json.
  - Legacy campaigns without `objective:` fall back to ranking by
    prediction_accuracy (the existing cross-arm metric).
  - Schema additions are additive; legacy campaigns validate.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.composite_score import (
    PRESETS,
    ObjectiveSpec,
    compute_score,
    get_preset,
    update_best_found,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(path.read_text())
    return json.loads(path.read_text())


def _write_iter_findings(work_dir: Path, iteration: int, arms: list[dict]) -> None:
    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    findings = {
        "iteration": iteration,
        "bundle_ref": f"runs/iter-{iteration}/bundle.yaml",
        "arms": arms,
        "experiment_valid": True,
        "discrepancy_analysis": "",
    }
    (iter_dir / "findings.json").write_text(json.dumps(findings))


def _arm(arm_type: str, status: str, metadata: dict | None = None) -> dict:
    return {
        "arm_type": arm_type,
        "predicted": "p", "observed": "o",
        "status": status, "error_type": None, "diagnostic_note": "n",
        "metadata": metadata or {},
    }


# ─── compute_score: deterministic math ────────────────────────────────────


class TestComputeScore:
    def test_three_components_match_hand_computed_reference(self) -> None:
        spec = ObjectiveSpec(weights={"a": 0.5, "b": 0.3, "c": 0.2})
        score = compute_score({"a": 1.0, "b": 0.5, "c": 0.0}, spec)
        assert score == pytest.approx(0.5 * 1.0 + 0.3 * 0.5 + 0.2 * 0.0)

    def test_missing_metric_defaults_to_zero(self) -> None:
        """A weight pointing at a metric not present in observed_metrics
        contributes zero — campaigns evolve their metric vocabulary across
        iterations and we don't want a missing column to crash scoring."""
        spec = ObjectiveSpec(weights={"a": 0.5, "b": 0.5})
        score = compute_score({"a": 1.0}, spec)  # b missing
        assert score == pytest.approx(0.5)

    def test_score_is_deterministic(self) -> None:
        spec = ObjectiveSpec(weights={"a": 1.0})
        m = {"a": 0.7}
        assert compute_score(m, spec) == compute_score(m, spec)

    def test_negative_metric_value_is_propagated(self) -> None:
        """compute_score does no clamping; negative observations (e.g.
        regression vs baseline) flow through. Direction is the caller's
        responsibility."""
        spec = ObjectiveSpec(weights={"a": 1.0})
        assert compute_score({"a": -0.3}, spec) == pytest.approx(-0.3)


# ─── ObjectiveSpec validation ─────────────────────────────────────────────


class TestObjectiveSpecValidation:
    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="weights"):
            ObjectiveSpec(weights={"a": 0.5, "b": 0.3})  # 0.8

    def test_negative_weight_rejected(self) -> None:
        with pytest.raises(ValueError, match="weight"):
            ObjectiveSpec(weights={"a": 1.5, "b": -0.5})  # sums to 1 but b<0

    def test_empty_weights_rejected(self) -> None:
        with pytest.raises(ValueError, match="weights"):
            ObjectiveSpec(weights={})

    def test_floating_point_tolerance(self) -> None:
        """0.1 * 10 isn't exactly 1.0 in float; allow small tolerance."""
        weights = {f"m{i}": 0.1 for i in range(10)}
        spec = ObjectiveSpec(weights=weights)
        assert sum(spec.weights.values()) == pytest.approx(1.0)


# ─── Named presets ────────────────────────────────────────────────────────


class TestPresets:
    def test_compound_return_preset_resolves(self) -> None:
        spec = get_preset("compound-return-style")
        assert "compound_return" in spec.weights
        assert sum(spec.weights.values()) == pytest.approx(1.0)

    def test_latency_preset_resolves(self) -> None:
        spec = get_preset("latency-style")
        assert sum(spec.weights.values()) == pytest.approx(1.0)

    def test_unknown_preset_rejected(self) -> None:
        with pytest.raises(ValueError, match="preset"):
            get_preset("nonsense")

    def test_presets_dict_is_immutable(self) -> None:
        """A caller who mutates PRESETS shouldn't break other callers."""
        spec = get_preset("compound-return-style")
        spec.weights["compound_return"] = 999  # local mutation
        spec2 = get_preset("compound-return-style")
        assert spec2.weights["compound_return"] != 999


# ─── update_best_found: scans iters, writes best_found.json ───────────────


class TestUpdateBestFound:
    def test_ranks_arms_by_composite_score(self, tmp_path: Path) -> None:
        objective = ObjectiveSpec(weights={"compound_return": 1.0})
        # Two arms in iter-1 with different metadata.compound_return values.
        _write_iter_findings(tmp_path, 1, [
            _arm("h-main", "CONFIRMED", {"compound_return": 0.5,
                                          "candidate_id": "A"}),
            _arm("h-main", "CONFIRMED", {"compound_return": 0.9,
                                          "candidate_id": "B"}),
        ])
        result = update_best_found(tmp_path, objective=objective, top_k=5)
        assert result["k"] == 5
        # Best-first ordering
        assert result["top_k"][0]["score"] == pytest.approx(0.9)
        assert result["top_k"][1]["score"] == pytest.approx(0.5)

    def test_merges_across_iterations(self, tmp_path: Path) -> None:
        objective = ObjectiveSpec(weights={"compound_return": 1.0})
        _write_iter_findings(tmp_path, 1, [
            _arm("h-main", "CONFIRMED", {"compound_return": 0.4,
                                          "candidate_id": "A"}),
        ])
        _write_iter_findings(tmp_path, 2, [
            _arm("h-main", "CONFIRMED", {"compound_return": 0.8,
                                          "candidate_id": "B"}),
        ])
        result = update_best_found(tmp_path, objective=objective, top_k=5)
        # Iter-2's arm scored higher
        assert result["top_k"][0]["iteration"] == 2
        assert len(result["top_k"]) == 2
        # Both candidates surface in candidate_id (which embeds metadata.candidate_id)
        candidate_ids = [t["candidate_id"] for t in result["top_k"]]
        assert any("/A" in cid for cid in candidate_ids)
        assert any("/B" in cid for cid in candidate_ids)

    def test_top_k_truncates(self, tmp_path: Path) -> None:
        objective = ObjectiveSpec(weights={"x": 1.0})
        for i in range(1, 6):  # 5 iterations × 1 arm each = 5 candidates
            _write_iter_findings(tmp_path, i, [
                _arm("h-main", "CONFIRMED", {"x": float(i),
                                              "candidate_id": f"C{i}"}),
            ])
        result = update_best_found(tmp_path, objective=objective, top_k=3)
        assert result["k"] == 3
        assert len(result["top_k"]) == 3
        # Ordered descending by score
        scores = [t["score"] for t in result["top_k"]]
        assert scores == sorted(scores, reverse=True)

    def test_writes_atomic_best_found_json(self, tmp_path: Path) -> None:
        objective = ObjectiveSpec(weights={"x": 1.0})
        _write_iter_findings(tmp_path, 1, [
            _arm("h-main", "CONFIRMED", {"x": 1.0, "candidate_id": "A"}),
        ])
        update_best_found(tmp_path, objective=objective, top_k=5)
        path = tmp_path / "best_found.json"
        assert path.exists()
        loaded = json.loads(path.read_text())
        jsonschema.validate(loaded, _load_schema("best_found.schema.json"))

    def test_legacy_no_objective_falls_back_to_prediction_accuracy(
        self, tmp_path: Path,
    ) -> None:
        """Without an objective, ranks by 1.0 if CONFIRMED, 0.5 if PARTIALLY,
        0.0 if REFUTED. Provides a sensible fallback so #169's engine-
        continues-past-REFUTE still gets a populated best_found.json."""
        _write_iter_findings(tmp_path, 1, [
            _arm("h-main", "CONFIRMED"),
            _arm("h-main", "PARTIALLY_CONFIRMED"),
            _arm("h-main", "REFUTED"),
        ])
        result = update_best_found(tmp_path, objective=None, top_k=5)
        scores = [t["score"] for t in result["top_k"]]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 1.0    # CONFIRMED
        assert scores[1] == 0.5    # PARTIALLY_CONFIRMED
        assert scores[2] == 0.0    # REFUTED

    def test_no_findings_produces_empty_top_k(self, tmp_path: Path) -> None:
        result = update_best_found(tmp_path, objective=None, top_k=5)
        assert result["top_k"] == []
        assert result["k"] == 5


# ─── Schema additions ─────────────────────────────────────────────────────


class TestCampaignSchemaAcceptsObjective:
    def _base_campaign(self) -> dict:
        return {
            "research_question": "q?",
            "run_id": "demo",
            "max_iterations": 1,
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
        }

    def test_objective_block_validates(self) -> None:
        c = self._base_campaign()
        c["objective"] = {
            "weights": {"a": 0.5, "b": 0.5},
            "metric_extractors": {"a": "metadata.a"},
            "deploy_threshold": 0.15,
        }
        jsonschema.validate(c, _load_schema("campaign.schema.yaml"))

    def test_objective_preset_validates(self) -> None:
        c = self._base_campaign()
        c["objective_preset"] = "compound-return-style"
        jsonschema.validate(c, _load_schema("campaign.schema.yaml"))

    def test_legacy_no_objective_validates(self) -> None:
        jsonschema.validate(self._base_campaign(),
                            _load_schema("campaign.schema.yaml"))

    def test_unknown_preset_name_rejected_by_schema(self) -> None:
        c = self._base_campaign()
        c["objective_preset"] = "unknown-preset"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(c, _load_schema("campaign.schema.yaml"))


class TestBestFoundSchema:
    def test_empty_best_found_validates(self) -> None:
        payload = {"top_k": [], "k": 5, "updated_at": "2026-05-25T00:00:00Z"}
        jsonschema.validate(payload, _load_schema("best_found.schema.json"))

    def test_full_best_found_validates(self) -> None:
        payload = {
            "top_k": [
                {
                    "candidate_id": "iter-1/h-main/A",
                    "score": 0.85,
                    "components": {"compound_return": 0.85},
                    "iteration": 1,
                    "arm_id": "h-main",
                },
            ],
            "k": 5,
            "updated_at": "2026-05-25T00:00:00Z",
        }
        jsonschema.validate(payload, _load_schema("best_found.schema.json"))

    def test_unknown_top_level_field_rejected(self) -> None:
        payload = {"top_k": [], "k": 5, "updated_at": "2026-05-25T00:00:00Z",
                   "surprise": "no"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(payload, _load_schema("best_found.schema.json"))
