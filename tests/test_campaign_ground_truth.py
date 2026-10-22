"""Behavioral tests for top-level campaign.ground_truth (issue #185).

The pre-registration use case: experimenters declare the immutable
direction claim and pass condition before any iteration runs, so the
agent can't silently move the goalposts. Before #185 this was rejected
by ``additionalProperties: false`` at the campaign top level and authors
had to bury the claim in ``target_system.description`` (losing structure
and diluting the cached system block).

Test contract:
  - Schema accepts top-level ``ground_truth`` as an optional object with
    optional pre_registered/workload/baselines/primary_metric/
    direction_claim/pass_condition/seeds fields.
  - Legacy campaigns without ``ground_truth`` validate unchanged.
  - The DESIGN-phase context surfaces ground_truth content as Markdown
    so the inner LLM sees it directly (not buried in target_system.description).
  - Same campaign yaml works whether theory_references are strings or
    objects (#185 also widens that).
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import yaml


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_campaign_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())


def _campaign(*, ground_truth=None) -> dict:
    c: dict = {
        "research_question": "q?",
        "run_id": "demo",
        "max_iterations": 1,
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
    }
    if ground_truth is not None:
        c["ground_truth"] = ground_truth
    return c


class TestSchemaAcceptsGroundTruth:
    def test_full_ground_truth_validates(self) -> None:
        """All optional fields populated — the kind of pre-registration
        a paper-reproduction campaign would author."""
        campaign = _campaign(ground_truth={
            "pre_registered": True,
            "workload": "fig7-burst",
            "baselines": ["wfq", "drr"],
            "primary_metric": "P95(latency)",
            "direction_claim": "P95(ea-wfq) < P95(wfq) for EARLY class",
            "pass_condition": (
                "direction holds in median across 10 seeds AND in "
                "≥7 of 10 seeds"
            ),
            "seeds": [42, 123, 7, 456, 789, 11, 2024, 31415, 271828, 8675309],
        })
        jsonschema.validate(campaign, _load_campaign_schema())

    def test_minimal_ground_truth_validates(self) -> None:
        """Empty object — author may pre-register incrementally."""
        jsonschema.validate(_campaign(ground_truth={}), _load_campaign_schema())

    def test_partial_ground_truth_validates(self) -> None:
        """Subset of fields — only the direction claim and pass condition."""
        campaign = _campaign(ground_truth={
            "direction_claim": "throughput improves under congestion",
            "pass_condition": "improvement holds across 5 of 5 seeds",
        })
        jsonschema.validate(campaign, _load_campaign_schema())

    def test_legacy_campaign_without_ground_truth_validates(self) -> None:
        jsonschema.validate(_campaign(), _load_campaign_schema())

    def test_unknown_property_rejected(self) -> None:
        """additionalProperties stays false on the ground_truth object."""
        campaign = _campaign(ground_truth={
            "direction_claim": "ok",
            "made_up_field": "should fail",
        })
        import pytest as _pytest
        with _pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, _load_campaign_schema())


