"""Behavioral tests for empirical_content on principles (issue #86).

Distinguishes "I proved this with math" from "I discovered this from
data". Without the distinction, mathematical identities (which always
hold across all experiments — they're definitions) look like the
strongest principles, but they teach nothing about whether the system
works. See #84 (parent) and the `composite-sensitivity-boundary`
principle RP-9 case study.

Schema-additive: legacy principles validate unchanged; new principles
may declare:
  * `empirical_content`: bool — could the experiments have falsified this?
  * `derivation_type`: enum — empirical | algebraic | definitional

Test contract:
  - Schema accepts both fields when present.
  - Legacy entries without them validate unchanged.
  - Malformed forms (wrong type, unknown enum value) rejected.
  - The decision-rule blurb is present in design.md (LLM reads it).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_principles_schema() -> dict:
    return json.loads((SCHEMAS_DIR / "principles.schema.json").read_text())


def _principle(*, empirical_content=None, derivation_type=None,
               confidence_posterior=None) -> dict:
    p: dict = {
        "id": "RP-1", "statement": "x", "confidence": "medium",
        "regime": "", "evidence": [], "contradicts": [],
        "extraction_iteration": 1, "mechanism": "",
        "applicability_bounds": "", "superseded_by": None, "status": "active",
    }
    if empirical_content is not None:
        p["empirical_content"] = empirical_content
    if derivation_type is not None:
        p["derivation_type"] = derivation_type
    if confidence_posterior is not None:
        p["confidence_posterior"] = confidence_posterior
    return p


# ─── Schema accepts new fields ────────────────────────────────────────────


class TestSchemaAcceptsNewFields:
    def test_empirical_principle_validates(self) -> None:
        store = {"principles": [_principle(
            empirical_content=True, derivation_type="empirical",
        )]}
        jsonschema.validate(store, _load_principles_schema())

    def test_algebraic_principle_validates(self) -> None:
        """RP-9 case: 'CC_RD > 1.0 iff gt_saturated' — algebraic identity,
        not an empirical discovery."""
        store = {"principles": [_principle(
            empirical_content=False, derivation_type="algebraic",
        )]}
        jsonschema.validate(store, _load_principles_schema())

    def test_definitional_principle_validates(self) -> None:
        store = {"principles": [_principle(
            empirical_content=False, derivation_type="definitional",
        )]}
        jsonschema.validate(store, _load_principles_schema())

    def test_legacy_principle_without_new_fields_validates(self) -> None:
        """Backward compat: principles produced before #86 still pass."""
        store = {"principles": [_principle()]}
        jsonschema.validate(store, _load_principles_schema())

    def test_principle_with_only_empirical_content_validates(self) -> None:
        """Fields are independent — neither requires the other."""
        store = {"principles": [_principle(empirical_content=True)]}
        jsonschema.validate(store, _load_principles_schema())

    def test_composes_with_confidence_posterior(self) -> None:
        """Both #86 and #164 are schema-additive on the same principle;
        they compose without conflict."""
        store = {"principles": [_principle(
            empirical_content=True, derivation_type="empirical",
            confidence_posterior={
                "mean": 0.75, "ci_low": 0.5, "ci_high": 0.9,
                "n_citations": 8,
            },
        )]}
        jsonschema.validate(store, _load_principles_schema())


# ─── Schema rejects malformed values ──────────────────────────────────────


class TestSchemaRejectsMalformed:
    def test_empirical_content_string_rejected(self) -> None:
        store = {"principles": [_principle(
            empirical_content="yes",  # not a bool
        )]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(store, _load_principles_schema())

    def test_unknown_derivation_type_rejected(self) -> None:
        store = {"principles": [_principle(derivation_type="vibes")]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(store, _load_principles_schema())


# ─── Methodology prompt mentions the decision rule ────────────────────────


class TestMethodologyDocumentsRule:
    def test_design_md_describes_empirical_content(self) -> None:
        """The LLM produces principles via the executor / extractor, and
        relies on the methodology prompt to know when to set
        empirical_content=false. The prompt must surface the decision
        rule (cached system block, paid once per session)."""
        prompt = (Path(__file__).resolve().parent.parent
                  / "prompts" / "methodology" / "design.md")
        text = prompt.read_text()
        assert "empirical_content" in text
        assert "algebraic" in text or "definitional" in text
