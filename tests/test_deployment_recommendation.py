"""Behavioral tests for deployment recommendation in meta_findings (issue #170).

Closes the search-oriented loop (#166): pre-work seeds (#167), composite
score ranks (#168), engine continues past REFUTE (#169), and now every
campaign emits a shippable verdict — `deploy | deploy_with_caveats |
fall_back_to_baseline` — with concrete citations.

Decision rule:
  * deploy  if best_score > baseline + deploy_threshold AND
            walk_forward_consistency component > 0.7 (when present)
  * fall_back_to_baseline  if best_score <= baseline OR best_found empty
  * deploy_with_caveats    otherwise

Test contract:
  - All three verdicts produced on the right inputs.
  - Citations resolve to real iteration/arm pairs in the on-disk fixture.
  - Validator floor rejects vague caveats; caveats must cite a concrete
    iter-N or arm marker.
  - Schema additive: meta_findings.json with deployment_recommendation
    validates; legacy without it is rejected (it's required-on-emit).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.composite_score import ObjectiveSpec, update_best_found
from orchestrator.deployment_recommendation import (
    DeploymentRecommendation,
    make_deployment_recommendation,
)
from orchestrator.meta_findings import (
    emit_meta_findings,
    validate_caveat,
    validate_evidence,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _arm(arm_type: str, status: str, metadata: dict | None = None) -> dict:
    return {
        "arm_type": arm_type,
        "predicted": "p", "observed": "o",
        "status": status, "error_type": None, "diagnostic_note": "n",
        "metadata": metadata or {},
    }


def _seed_workdir(
    work_dir: Path,
    *,
    arms: list[dict],
    objective: ObjectiveSpec | None,
    pre_work_baseline: dict | None = None,
) -> None:
    """Set up runs/iter-1/findings.json + best_found.json + pre_work.json."""
    iter_dir = work_dir / "runs" / "iter-1"
    iter_dir.mkdir(parents=True, exist_ok=True)
    findings = {
        "iteration": 1,
        "bundle_ref": "runs/iter-1/bundle.yaml",
        "arms": arms,
        "experiment_valid": True,
        "discrepancy_analysis": "",
    }
    (iter_dir / "findings.json").write_text(json.dumps(findings))

    update_best_found(work_dir, objective=objective, top_k=5)

    if pre_work_baseline is not None:
        (work_dir / "pre_work.json").write_text(
            json.dumps({"baseline_metrics": pre_work_baseline}),
        )


def _campaign(
    *,
    objective: dict | None = None,
    objective_preset: str | None = None,
) -> dict:
    c: dict = {
        "research_question": "q?",
        "run_id": "demo",
        "max_iterations": 1,
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
    }
    if objective is not None:
        c["objective"] = objective
    if objective_preset is not None:
        c["objective_preset"] = objective_preset
    return c


# ─── Verdict logic ────────────────────────────────────────────────────────


class TestVerdictDeploy:
    def test_high_score_with_high_consistency_yields_deploy(
        self, tmp_path: Path,
    ) -> None:
        objective = ObjectiveSpec(weights={
            "compound_return": 0.7, "walk_forward_consistency": 0.3,
        })
        _seed_workdir(
            tmp_path,
            arms=[_arm("h-main", "CONFIRMED", {
                "compound_return": 0.9,
                "walk_forward_consistency": 0.85,
                "candidate_id": "winner",
            })],
            objective=objective,
            pre_work_baseline={
                "compound_return": 0.5,
                "walk_forward_consistency": 0.5,
            },
        )

        rec = make_deployment_recommendation(
            tmp_path,
            campaign=_campaign(objective={
                "weights": {
                    "compound_return": 0.7,
                    "walk_forward_consistency": 0.3,
                },
                "deploy_threshold": 0.1,
            }),
        )
        assert rec.verdict == "deploy"
        assert rec.top_candidate_id is not None
        assert "winner" in rec.top_candidate_id


class TestVerdictFallback:
    def test_score_below_baseline_yields_fall_back(self, tmp_path: Path) -> None:
        objective = ObjectiveSpec(weights={"compound_return": 1.0})
        _seed_workdir(
            tmp_path,
            arms=[_arm("h-main", "CONFIRMED", {
                "compound_return": 0.3, "candidate_id": "loser",
            })],
            objective=objective,
            pre_work_baseline={"compound_return": 0.5},
        )

        rec = make_deployment_recommendation(
            tmp_path,
            campaign=_campaign(objective={
                "weights": {"compound_return": 1.0},
                "deploy_threshold": 0.1,
            }),
        )
        assert rec.verdict == "fall_back_to_baseline"

    def test_empty_best_found_yields_fall_back(self, tmp_path: Path) -> None:
        """No iterations completed yet → no candidate, fall back."""
        # Don't seed anything; update_best_found writes empty top_k.
        update_best_found(tmp_path, objective=None, top_k=5)
        rec = make_deployment_recommendation(
            tmp_path, campaign=_campaign(),
        )
        assert rec.verdict == "fall_back_to_baseline"


# ─── #178: missing vs empty best_found.json must be distinguishable ───────


class TestFallbackDistinguishesMissingVsEmpty:
    """Regression for the sort_bench dry-run failure: a 100%-CONFIRMED
    campaign reported `fall_back_to_baseline` with empty caveats because
    best_found.json was missing (cascade from #177). Even when #177 is
    fixed, the deployment recommender should distinguish "missing" from
    "empty" with concrete caveats so the operator knows what happened."""

    def test_missing_best_found_caveat_cites_filename_and_issue(
        self, tmp_path: Path,
    ) -> None:
        # No best_found.json on disk — the case from the sort_bench run.
        rec = make_deployment_recommendation(tmp_path, campaign=_campaign())
        assert rec.verdict == "fall_back_to_baseline"
        assert rec.caveats, (
            "missing best_found must produce at least one caveat — "
            "silent fall_back is the bug from #178"
        )
        c0 = rec.caveats[0]
        assert "best_found.json" in c0
        assert "#177" in c0 or "update_best_found" in c0, (
            "caveat must point at the upstream wiring root cause"
        )

    def test_missing_best_found_caveat_passes_validator_floor(
        self, tmp_path: Path,
    ) -> None:
        """The caveat must pass meta_findings.validate_caveat (#170 floor).
        Validator floor rejects vague aspirations regardless of source."""
        from orchestrator.meta_findings import validate_caveat

        rec = make_deployment_recommendation(tmp_path, campaign=_campaign())
        for caveat in rec.caveats:
            assert validate_caveat(caveat) is None, (
                f"auto-generated caveat fails validator floor: {caveat!r}"
            )

    def test_empty_top_k_caveat_distinguishable_from_missing(
        self, tmp_path: Path,
    ) -> None:
        """File present but top_k=[] is a different condition: search
        ran, no candidate beat baseline. Caveat text must reflect that."""
        update_best_found(tmp_path, objective=None, top_k=5)  # writes empty
        rec = make_deployment_recommendation(tmp_path, campaign=_campaign())
        assert rec.verdict == "fall_back_to_baseline"
        assert rec.caveats
        # Empty case mentions empty / k= rather than the missing path
        c0 = rec.caveats[0]
        assert ("empty" in c0 or "no candidate" in c0.lower()
                or "top_k" in c0)

    def test_empty_top_k_caveat_passes_validator_floor(
        self, tmp_path: Path,
    ) -> None:
        from orchestrator.meta_findings import validate_caveat

        update_best_found(tmp_path, objective=None, top_k=5)
        rec = make_deployment_recommendation(tmp_path, campaign=_campaign())
        for caveat in rec.caveats:
            assert validate_caveat(caveat) is None


class TestVerdictWithCaveats:
    def test_high_score_low_consistency_yields_caveats(
        self, tmp_path: Path,
    ) -> None:
        """Score beats baseline + threshold but consistency component
        is below the 0.7 walk-forward bar — needs caveats."""
        objective = ObjectiveSpec(weights={
            "compound_return": 0.7, "walk_forward_consistency": 0.3,
        })
        _seed_workdir(
            tmp_path,
            arms=[_arm("h-main", "CONFIRMED", {
                "compound_return": 0.9,
                "walk_forward_consistency": 0.4,  # below 0.7 threshold
                "candidate_id": "shaky",
            })],
            objective=objective,
            pre_work_baseline={
                "compound_return": 0.5,
                "walk_forward_consistency": 0.5,
            },
        )
        rec = make_deployment_recommendation(
            tmp_path,
            campaign=_campaign(objective={
                "weights": {
                    "compound_return": 0.7,
                    "walk_forward_consistency": 0.3,
                },
                "deploy_threshold": 0.1,
            }),
        )
        assert rec.verdict == "deploy_with_caveats"
        assert rec.caveats, "verdict_with_caveats must produce at least one caveat"
        # All caveats must cite a concrete marker (validator floor).
        for caveat in rec.caveats:
            assert validate_caveat(caveat) is None, (
                f"caveat failed validator floor: {caveat!r}"
            )

    def test_marginal_score_above_baseline_yields_caveats(
        self, tmp_path: Path,
    ) -> None:
        """Score beats baseline but only by less than deploy_threshold."""
        objective = ObjectiveSpec(weights={"compound_return": 1.0})
        _seed_workdir(
            tmp_path,
            arms=[_arm("h-main", "CONFIRMED", {
                "compound_return": 0.55,  # baseline 0.5 + 0.05 < threshold 0.1
                "candidate_id": "marginal",
            })],
            objective=objective,
            pre_work_baseline={"compound_return": 0.5},
        )
        rec = make_deployment_recommendation(
            tmp_path,
            campaign=_campaign(objective={
                "weights": {"compound_return": 1.0},
                "deploy_threshold": 0.1,
            }),
        )
        assert rec.verdict == "deploy_with_caveats"


# ─── Citations point at real iteration/arm pairs ──────────────────────────


class TestCitations:
    def test_top_candidate_resolves_to_real_arm(self, tmp_path: Path) -> None:
        objective = ObjectiveSpec(weights={"compound_return": 1.0})
        _seed_workdir(
            tmp_path,
            arms=[_arm("h-main", "CONFIRMED", {
                "compound_return": 0.9, "candidate_id": "winner",
            })],
            objective=objective,
            pre_work_baseline={"compound_return": 0.0},
        )
        rec = make_deployment_recommendation(
            tmp_path,
            campaign=_campaign(objective={
                "weights": {"compound_return": 1.0}, "deploy_threshold": 0.1,
            }),
        )
        assert rec.citations
        for c in rec.citations:
            assert c["iteration"] == 1
            assert c["arm_id"] == "h-main"
            assert validate_evidence(c["evidence_snippet"]) is None


# ─── Validator floor on caveats ───────────────────────────────────────────


class TestValidatorFloor:
    def test_vague_caveat_rejected(self) -> None:
        err = validate_caveat("things looked promising")
        assert err is not None
        assert "vague" in err.lower() or "concrete" in err.lower()

    def test_concrete_caveat_passes(self) -> None:
        text = "iter-2 arm h-main: walk_forward_consistency = 0.4 (< 0.7)"
        assert validate_caveat(text) is None

    def test_short_caveat_rejected(self) -> None:
        err = validate_caveat("ok")
        assert err is not None


# ─── meta_findings.emit emits deployment_recommendation ───────────────────


class TestMetaFindingsIntegration:
    def test_emit_includes_deployment_recommendation(
        self, tmp_path: Path,
    ) -> None:
        objective = ObjectiveSpec(weights={"compound_return": 1.0})
        _seed_workdir(
            tmp_path,
            arms=[_arm("h-main", "CONFIRMED", {
                "compound_return": 0.9, "candidate_id": "winner",
            })],
            objective=objective,
            pre_work_baseline={"compound_return": 0.0},
        )
        # Set up minimal state.json
        (tmp_path / "state.json").write_text(json.dumps({
            "phase": "DONE", "iteration": 1, "run_id": "demo",
            "family": None, "timestamp": "2026-05-25T00:00:00Z",
        }))

        payload = emit_meta_findings(
            tmp_path,
            campaign=_campaign(objective={
                "weights": {"compound_return": 1.0}, "deploy_threshold": 0.1,
            }),
        )
        assert "deployment_recommendation" in payload
        assert payload["deployment_recommendation"]["verdict"] == "deploy"

        # Schema accepts the new required field.
        jsonschema.validate(payload, _load_schema("meta_findings.schema.json"))

    def test_legacy_payload_without_deployment_recommendation_rejected(
        self,
    ) -> None:
        """The field is required-on-emit. Schema enforces it."""
        legacy = {
            "schema_version": "1",
            "campaign_design_lessons": [],
            "target_system_asks": [],
            "nous_asks": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(legacy, _load_schema("meta_findings.schema.json"))


# ─── Schema acceptance ────────────────────────────────────────────────────


class TestDeploymentRecommendationSchema:
    def test_full_recommendation_validates(self) -> None:
        payload = {
            "schema_version": "1",
            "campaign_design_lessons": [],
            "target_system_asks": [],
            "nous_asks": [],
            "deployment_recommendation": {
                "verdict": "deploy",
                "top_candidate_id": "iter-1/h-main/winner",
                "score": 0.9,
                "citations": [
                    {
                        "iteration": 1,
                        "arm_id": "h-main",
                        "evidence_snippet": "iter-1 arm h-main score=0.9",
                    },
                ],
                "caveats": [],
            },
        }
        jsonschema.validate(payload, _load_schema("meta_findings.schema.json"))

    def test_invalid_verdict_rejected(self) -> None:
        payload = {
            "schema_version": "1",
            "campaign_design_lessons": [],
            "target_system_asks": [],
            "nous_asks": [],
            "deployment_recommendation": {
                "verdict": "ship_it_yolo",
                "top_candidate_id": None,
                "score": None,
                "citations": [],
                "caveats": [],
            },
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(payload, _load_schema("meta_findings.schema.json"))

    def test_fall_back_with_null_candidate_validates(self) -> None:
        payload = {
            "schema_version": "1",
            "campaign_design_lessons": [],
            "target_system_asks": [],
            "nous_asks": [],
            "deployment_recommendation": {
                "verdict": "fall_back_to_baseline",
                "top_candidate_id": None,
                "score": None,
                "citations": [],
                "caveats": [],
            },
        }
        jsonschema.validate(payload, _load_schema("meta_findings.schema.json"))


# ─── DeploymentRecommendation result shape ────────────────────────────────


class TestResultShape:
    def test_result_carries_typed_fields(self, tmp_path: Path) -> None:
        update_best_found(tmp_path, objective=None, top_k=5)
        rec = make_deployment_recommendation(
            tmp_path, campaign=_campaign(),
        )
        assert isinstance(rec, DeploymentRecommendation)
        assert rec.verdict in {
            "deploy", "deploy_with_caveats", "fall_back_to_baseline",
        }
        assert isinstance(rec.citations, list)
        assert isinstance(rec.caveats, list)
