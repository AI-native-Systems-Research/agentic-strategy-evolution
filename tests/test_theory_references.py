"""Behavioral tests for theory_references in campaign.yaml (issue #88).

Gives campaigns a structured place to declare external, established
theory (e.g., Little's Law, M/G/K stability bound) that the ground
truth should derive from. This is the *external grounding* angle of
the anti-tautology cluster (#84) — instead of testing a thermometer
against itself, declare which independent thermometer to compare
against.

Test contract:
  - Schema accepts theory_references as an optional array of theory
    declarations.
  - Each entry requires {name, statement} and may include
    independent_of_detector, use_as (enum), how.
  - Legacy campaigns without theory_references validate unchanged.
  - examples/campaign.yaml still validates against the updated schema.
  - Designer prompt (design.md, cached system block) describes how to
    use theory_references.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest
import yaml


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_campaign_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())


def _campaign(*, theory_references=None) -> dict:
    c: dict = {
        "research_question": "q?",
        "run_id": "demo",
        "max_iterations": 1,
        "target_system": {"name": "x", "description": "d"},
        "prompts": {"methodology_layer": "p"},
    }
    if theory_references is not None:
        c["theory_references"] = theory_references
    return c


# ─── Schema accepts theory_references ─────────────────────────────────────


class TestSchemaAcceptsTheoryReferences:
    def test_full_theory_references_validates(self) -> None:
        campaign = _campaign(theory_references=[
            {
                "name": "Little's Law",
                "statement": "L = λ × W (mean queue length = arrival rate × mean wait time)",
                "independent_of_detector": True,
                "use_as": "ground_truth",
                "how": "Compute W_predicted from observed arrival rate and queue depth; compare against detector estimate.",
            },
            {
                "name": "M/G/K stability bound",
                "statement": "A queue with K servers is stable iff λ × E[S] / K < 1",
                "independent_of_detector": True,
                "use_as": "ground_truth",
                "how": "Compute μ_analytical = K / E[S] and compare against measured throughput.",
            },
        ])
        jsonschema.validate(campaign, _load_campaign_schema())

    def test_minimal_theory_references_validates(self) -> None:
        """Only `name` and `statement` are required."""
        campaign = _campaign(theory_references=[
            {"name": "PASTA", "statement": "Poisson arrivals see time averages"},
        ])
        jsonschema.validate(campaign, _load_campaign_schema())

    def test_empty_theory_references_validates(self) -> None:
        campaign = _campaign(theory_references=[])
        jsonschema.validate(campaign, _load_campaign_schema())

    def test_legacy_campaign_without_theory_references_validates(self) -> None:
        jsonschema.validate(_campaign(), _load_campaign_schema())

    def test_string_form_theory_references_validates(self) -> None:
        """#185: items may be strings (short-name only)."""
        campaign = _campaign(theory_references=[
            "Little's Law",
            "M/G/K stability bound",
        ])
        jsonschema.validate(campaign, _load_campaign_schema())

    def test_mixed_string_and_object_theory_references_validates(self) -> None:
        """#185: a campaign can mix string and object items freely."""
        campaign = _campaign(theory_references=[
            "PASTA",
            {"name": "Little's Law", "statement": "L = λ × W"},
            "Wald's identity",
        ])
        jsonschema.validate(campaign, _load_campaign_schema())

    def test_examples_campaign_yaml_still_validates(self) -> None:
        """The committed example must keep validating."""
        examples = (Path(__file__).resolve().parent.parent
                    / "examples" / "campaign.yaml")
        if not examples.exists():
            pytest.skip("examples/campaign.yaml not present")
        loaded = yaml.safe_load(examples.read_text())
        jsonschema.validate(loaded, _load_campaign_schema())


# ─── Schema rejects malformed entries ─────────────────────────────────────


class TestSchemaRejectsMalformed:
    def test_missing_name_rejected(self) -> None:
        campaign = _campaign(theory_references=[{"statement": "x"}])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, _load_campaign_schema())

    def test_missing_statement_rejected(self) -> None:
        campaign = _campaign(theory_references=[{"name": "x"}])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, _load_campaign_schema())

    def test_unknown_use_as_value_rejected(self) -> None:
        campaign = _campaign(theory_references=[{
            "name": "x", "statement": "y", "use_as": "vibes",
        }])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, _load_campaign_schema())


# ─── Methodology prompt mentions theory_references ────────────────────────


class TestMethodologyDocumentsTheoryReferences:
    def test_design_md_describes_theory_references(self) -> None:
        prompt = (Path(__file__).resolve().parent.parent
                  / "prompts" / "methodology" / "design.md")
        text = prompt.read_text()
        assert "theory_references" in text
        # The prompt should explain *how* to use them, not just mention them.
        assert "ground" in text.lower() or "external" in text.lower()
