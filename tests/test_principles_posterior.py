"""Behavioral tests for the Bayesian principle-posterior (issue #164).

Replaces the heuristic confidence ("low"/"medium"/"high") and ad-hoc
PRUNE/UPDATE decisions with a calibrated Beta-Binomial posterior over
"k of N citing arms produced outcomes consistent with this principle."

Test contract:
  - Assert the recommendation enum + CI bounds for known evidence shapes.
  - Assert the schema additively accepts confidence_posterior.
  - Assert injected `posterior_fn=` is honored — no scipy call when the
    test supplies its own.
  - No PyMC, no MCMC, no live calls. The conftest extension hard-fails
    any test that tries to invoke pymc.sample.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.principles_posterior import (
    PosteriorResult,
    PrincipleEvidence,
    posterior,
)


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_principles_schema() -> dict:
    return json.loads((SCHEMAS_DIR / "principles.schema.json").read_text())


def _principle(*, confidence_posterior: dict | None = None) -> dict:
    p: dict = {
        "id": "RP-1",
        "statement": "x",
        "confidence": "medium",
        "regime": "",
        "evidence": [],
        "contradicts": [],
        "extraction_iteration": 1,
        "mechanism": "",
        "applicability_bounds": "",
        "superseded_by": None,
        "status": "active",
    }
    if confidence_posterior is not None:
        p["confidence_posterior"] = confidence_posterior
    return p


# ─── Recommendation enum + CI behavior on known evidence ──────────────────


class TestPosteriorRecommendation:
    def test_no_evidence_yields_update_with_wide_ci(self) -> None:
        """Beta(1,1) prior + zero observations ⇒ posterior == prior; CI ≈ [0.025, 0.975]."""
        result = posterior(PrincipleEvidence("RP-1", n_citations=0, n_consistent=0))
        assert result.recommendation == "update"
        assert result.ci_low < 0.05
        assert result.ci_high > 0.95
        assert result.mean == pytest.approx(0.5, abs=0.01)

    def test_strong_confirmation_yields_keep(self) -> None:
        """9/10 consistent ⇒ recommendation=keep, mean > 0.7."""
        result = posterior(PrincipleEvidence("RP-1", n_citations=10, n_consistent=9))
        assert result.recommendation == "keep"
        assert result.mean > 0.7
        assert result.ci_low > 0.5

    def test_strong_refutation_yields_prune(self) -> None:
        """1/10 consistent ⇒ recommendation=prune, ci_high < 0.5."""
        result = posterior(PrincipleEvidence("RP-1", n_citations=10, n_consistent=1))
        assert result.recommendation == "prune"
        assert result.ci_high < 0.5
        assert result.mean < 0.3

    def test_borderline_evidence_yields_update(self) -> None:
        """5/10 consistent ⇒ recommendation=update (CI straddles 0.5)."""
        result = posterior(PrincipleEvidence("RP-1", n_citations=10, n_consistent=5))
        assert result.recommendation == "update"
        assert result.ci_low < 0.5 < result.ci_high

    def test_decision_boundaries_are_monotone(self) -> None:
        """As n_consistent grows holding n_citations fixed, mean increases monotonically."""
        means = [
            posterior(PrincipleEvidence("RP-1", 10, k)).mean
            for k in range(11)
        ]
        assert means == sorted(means)

    def test_wider_evidence_tightens_ci(self) -> None:
        """Same proportion with more samples ⇒ tighter CI."""
        narrow = posterior(PrincipleEvidence("RP-1", n_citations=10, n_consistent=8))
        wide = posterior(PrincipleEvidence("RP-1", n_citations=100, n_consistent=80))
        narrow_width = narrow.ci_high - narrow.ci_low
        wide_width = wide.ci_high - wide.ci_low
        assert wide_width < narrow_width


# ─── Custom prior ──────────────────────────────────────────────────────────


class TestPosteriorPrior:
    def test_strong_skeptical_prior_resists_weak_evidence(self) -> None:
        """Beta(1,9) prior + 1/2 observations ⇒ still leaning low."""
        weak = PrincipleEvidence("RP-1", n_citations=2, n_consistent=1)
        result = posterior(weak, prior=(1.0, 9.0))
        assert result.mean < 0.3

    def test_strong_optimistic_prior_resists_weak_evidence(self) -> None:
        """Beta(9,1) prior + 1/2 observations ⇒ still leaning high."""
        weak = PrincipleEvidence("RP-1", n_citations=2, n_consistent=1)
        result = posterior(weak, prior=(9.0, 1.0))
        assert result.mean > 0.7


# ─── Injection seam: posterior_fn replaces the default ────────────────────


class TestPosteriorFnInjection:
    def test_injected_fn_replaces_scipy(self) -> None:
        """When posterior_fn= is supplied, default scipy path is not taken."""
        sentinel_calls: list[tuple] = []

        def fake_fn(a: float, b: float) -> tuple[float, float, float]:
            sentinel_calls.append((a, b))
            return (0.42, 0.30, 0.55)  # mean, ci_low, ci_high

        result = posterior(
            PrincipleEvidence("RP-1", n_citations=5, n_consistent=3),
            posterior_fn=fake_fn,
        )

        assert result.mean == 0.42
        assert result.ci_low == 0.30
        assert result.ci_high == 0.55
        assert len(sentinel_calls) == 1
        # Beta(1+3, 1+2) per conjugate-update math
        a, b = sentinel_calls[0]
        assert a == pytest.approx(4.0)
        assert b == pytest.approx(3.0)

    def test_result_carries_evidence_id_and_citations(self) -> None:
        """Result links back to the principle for downstream consumption."""
        result = posterior(PrincipleEvidence("RP-42", n_citations=7, n_consistent=4))
        assert result.principle_id == "RP-42"
        assert result.n_citations == 7
        assert isinstance(result, PosteriorResult)


# ─── Input validation ──────────────────────────────────────────────────────


class TestPosteriorValidation:
    def test_n_consistent_above_n_citations_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_consistent"):
            posterior(PrincipleEvidence("RP-1", n_citations=5, n_consistent=10))

    def test_negative_counts_rejected(self) -> None:
        with pytest.raises(ValueError):
            posterior(PrincipleEvidence("RP-1", n_citations=-1, n_consistent=0))

    def test_invalid_prior_rejected(self) -> None:
        with pytest.raises(ValueError, match="prior"):
            posterior(
                PrincipleEvidence("RP-1", 5, 3),
                prior=(0.0, 1.0),
            )


# ─── Schema additive: principles.schema.json accepts confidence_posterior ──


class TestSchemaAcceptsConfidencePosterior:
    def test_principle_with_confidence_posterior_validates(self) -> None:
        store = {"principles": [_principle(confidence_posterior={
            "mean": 0.7, "ci_low": 0.5, "ci_high": 0.9, "n_citations": 10,
        })]}
        jsonschema.validate(store, _load_principles_schema())

    def test_principle_without_confidence_posterior_still_validates(self) -> None:
        """Backward compat: legacy entries pass."""
        store = {"principles": [_principle()]}
        jsonschema.validate(store, _load_principles_schema())

    def test_principle_with_invalid_confidence_posterior_rejected(self) -> None:
        """Mean outside [0,1] is invalid."""
        store = {"principles": [_principle(confidence_posterior={
            "mean": 1.5, "ci_low": 0.5, "ci_high": 0.9, "n_citations": 10,
        })]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(store, _load_principles_schema())


# ─── PyMC guard regression: confirm conftest blocks live MCMC sampling ────


class TestPyMCBlocked:
    def test_pymc_sample_is_blocked_in_tests(self) -> None:
        """Conftest hard-fails any attempt to invoke pymc.sample.

        Importing pymc at module load is allowed (it's a heavy import
        but pure Python), but actually sampling is not.
        """
        try:
            import pymc  # type: ignore[import-not-found]
        except ImportError:
            pytest.skip("PyMC not installed in this environment")
        with pytest.raises(RuntimeError, match="pymc.sample"):
            pymc.sample()
