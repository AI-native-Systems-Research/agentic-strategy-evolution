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


class TestGroundTruthRendersIntoDesignContext:
    """The DESIGN-phase context exposes ground_truth content as Markdown
    so the agent sees it verbatim alongside target_system.description.
    """

    def test_format_helper_returns_markdown_with_fields(self) -> None:
        from orchestrator.llm_dispatch import _format_campaign_ground_truth
        text = _format_campaign_ground_truth({
            "pre_registered": True,
            "primary_metric": "P95(latency)",
            "direction_claim": "X < Y under condition Z",
            "pass_condition": "median direction holds across seeds",
        })
        # Headline + each populated field surfaces.
        assert "Pre-registered ground truth" in text
        assert "P95(latency)" in text
        assert "X < Y under condition Z" in text
        assert "median direction holds across seeds" in text

    def test_format_helper_empty_when_block_absent(self) -> None:
        from orchestrator.llm_dispatch import _format_campaign_ground_truth
        assert _format_campaign_ground_truth(None) == ""
        assert _format_campaign_ground_truth({}) == ""

    def test_normalize_theory_references_widens_strings(self) -> None:
        from orchestrator.llm_dispatch import _normalize_theory_references
        out = _normalize_theory_references([
            "Little's Law",
            {"name": "M/G/K", "statement": "K servers, ..."},
        ])
        assert out == [
            {"name": "Little's Law"},
            {"name": "M/G/K", "statement": "K servers, ..."},
        ]

    def test_normalize_theory_references_handles_empty(self) -> None:
        from orchestrator.llm_dispatch import _normalize_theory_references
        assert _normalize_theory_references(None) == []
        assert _normalize_theory_references([]) == []
