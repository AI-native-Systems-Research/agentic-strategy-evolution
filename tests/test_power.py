"""Behavioral tests for the design-time power analysis (issue #163).

Power analysis right-sizes per-arm seed counts from an effect size,
desired power, and alpha. Pure deterministic Python — no LLM, no
randomness.

The test contract is *behavioral*: assert what `required_seeds`
returns and what shape the schema accepts. We don't assert which
internal scipy function was called — the seam is the function
signature, not the implementation.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.power import required_seeds


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _arm(*, seeds_rationale: dict | None = None) -> dict:
    arm: dict = {
        "type": "h-main",
        "prediction": "p", "mechanism": "m", "diagnostic": "d",
    }
    if seeds_rationale is not None:
        arm["seeds_rationale"] = seeds_rationale
    return arm


def _bundle(arms: list[dict]) -> dict:
    return {
        "metadata": {"iteration": 1, "family": "test", "research_question": "q?"},
        "arms": arms,
    }


# ─── Cohen-table reference values ─────────────────────────────────────────
#
# These values are pinned to Cohen (1988) two-sample t-test tables,
# computed via the closed-form normal approximation:
#   N = 2 * ((z_{1-α/2} + z_{1-β}) / d)^2
# Tolerances are tight (±1) because the formula is deterministic.


class TestRequiredSeedsTwoSampleT:
    def test_small_effect_yields_large_n(self) -> None:
        """Cohen's small effect (d=0.2) needs ~393 seeds/arm at conventional power."""
        n = required_seeds(effect_size=0.2, power=0.8, alpha=0.05, kind="t")
        assert 380 <= n <= 405

    def test_medium_effect_yields_moderate_n(self) -> None:
        """Cohen's medium effect (d=0.5) needs ~63 seeds/arm."""
        n = required_seeds(effect_size=0.5, power=0.8, alpha=0.05, kind="t")
        assert 60 <= n <= 70

    def test_large_effect_yields_small_n(self) -> None:
        """Cohen's large effect (d=0.8) needs ~25 seeds/arm."""
        n = required_seeds(effect_size=0.8, power=0.8, alpha=0.05, kind="t")
        assert 22 <= n <= 28

    def test_higher_power_requires_more_seeds(self) -> None:
        """Monotonicity: power=0.9 needs strictly more seeds than power=0.8."""
        n_80 = required_seeds(effect_size=0.5, power=0.8, alpha=0.05, kind="t")
        n_90 = required_seeds(effect_size=0.5, power=0.9, alpha=0.05, kind="t")
        assert n_90 > n_80

    def test_stricter_alpha_requires_more_seeds(self) -> None:
        """Monotonicity: alpha=0.01 needs strictly more seeds than alpha=0.05."""
        n_05 = required_seeds(effect_size=0.5, power=0.8, alpha=0.05, kind="t")
        n_01 = required_seeds(effect_size=0.5, power=0.8, alpha=0.01, kind="t")
        assert n_01 > n_05

    def test_default_power_is_eighty_percent(self) -> None:
        """Convention: power defaults to 0.8 if not specified."""
        explicit = required_seeds(effect_size=0.5, power=0.8, alpha=0.05, kind="t")
        implicit = required_seeds(effect_size=0.5)
        assert explicit == implicit


class TestRequiredSeedsProportions:
    def test_proportions_kind_returns_positive_int(self) -> None:
        """Cohen's h for proportions test produces a sensible N."""
        n = required_seeds(effect_size=0.5, power=0.8, alpha=0.05, kind="proportions")
        assert isinstance(n, int)
        assert n > 0

    def test_proportions_small_effect_larger_than_large(self) -> None:
        """Same monotonicity property as the t-test path."""
        small = required_seeds(effect_size=0.2, kind="proportions")
        large = required_seeds(effect_size=0.8, kind="proportions")
        assert small > large


class TestRequiredSeedsValidation:
    def test_zero_effect_size_rejected(self) -> None:
        """Effect size 0 is undefined for sample-size calc; raise rather than div-by-zero."""
        with pytest.raises(ValueError, match="effect_size"):
            required_seeds(effect_size=0.0)

    def test_negative_effect_size_rejected(self) -> None:
        """Effect size is a magnitude; sign is captured by the hypothesis direction, not here."""
        with pytest.raises(ValueError, match="effect_size"):
            required_seeds(effect_size=-0.5)

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="kind"):
            required_seeds(effect_size=0.5, kind="anova")

    def test_power_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="power"):
            required_seeds(effect_size=0.5, power=1.5)

    def test_alpha_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="alpha"):
            required_seeds(effect_size=0.5, alpha=0.0)


# ─── Schema additive: bundle.schema.yaml accepts arms[].seeds_rationale ────


class TestSchemaAcceptsSeedsRationale:
    def test_arm_with_seeds_rationale_validates(self) -> None:
        bundle = _bundle([_arm(seeds_rationale={
            "effect_size": 0.5, "power": 0.8, "alpha": 0.05, "kind": "t",
        })])
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_arm_without_seeds_rationale_still_validates(self) -> None:
        """Backward-compat: legacy bundles validate unchanged."""
        bundle = _bundle([_arm()])
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_arm_with_minimal_seeds_rationale_validates(self) -> None:
        """Only effect_size is required; other fields default at compute time."""
        bundle = _bundle([_arm(seeds_rationale={"effect_size": 0.5})])
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_arm_with_missing_effect_size_rejected(self) -> None:
        bundle = _bundle([_arm(seeds_rationale={"power": 0.8})])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())

    def test_arm_with_invalid_kind_rejected(self) -> None:
        bundle = _bundle([_arm(seeds_rationale={
            "effect_size": 0.5, "kind": "anova",
        })])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())

    def test_existing_campaign_yaml_still_validates(self) -> None:
        """Real-world bundle without seeds_rationale must still pass."""
        # Mirror examples/campaign.yaml shape — minimal h-main + h-control-negative.
        bundle = _bundle([
            _arm(),
            {
                "type": "h-control-negative",
                "prediction": "p", "mechanism": "m", "diagnostic": "d",
            },
        ])
        jsonschema.validate(bundle, _load_bundle_schema())
