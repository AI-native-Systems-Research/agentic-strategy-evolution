"""Behavioral tests for the graded-complexity tier system (issue #159).

Tests assert what's on disk (bundle.yaml) and what shows up in the
gate panel string. The discipline is enforced through visibility,
not refusal — these tests exercise the panel output, jump detection,
and additive-only schema compatibility. No live LLM calls.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema
import yaml

from orchestrator.complexity_tier import (
    TIER_NAMES,
    collect_tier_warnings,
    detect_jump,
    format_tier_summary,
    prior_iteration_tiers,
)
from orchestrator.validate import validate_design


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_bundle_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "bundle.schema.yaml").read_text())


def _make_bundle(*, iteration: int, tier: int | None = None,
                 justification: str | None = None) -> dict:
    bundle: dict = {
        "metadata": {
            "iteration": iteration, "family": "test",
            "research_question": "q?",
        },
        "arms": [
            {"type": "h-main", "prediction": "p", "mechanism": "m",
             "diagnostic": "d"},
        ],
    }
    if tier is not None:
        bundle["complexity_tier"] = tier
    if justification is not None:
        bundle["tier_justification"] = justification
    return bundle


def _setup_iter(work_dir: Path, iteration: int, bundle: dict) -> Path:
    iter_dir = work_dir / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "problem.md").write_text("## RQ\nq?\n")
    (iter_dir / "bundle.yaml").write_text(yaml.safe_dump(bundle))
    (iter_dir / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nx\n")
    return iter_dir


# ─── Schema accepts complexity_tier as additive optional field ────────────


class TestSchemaAcceptsTier:
    def test_bundle_with_tier_validates(self) -> None:
        bundle = _make_bundle(iteration=1, tier=1, justification="simplest")
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_bundle_without_tier_still_validates(self) -> None:
        """Backward compat: bundles without complexity_tier still pass."""
        bundle = _make_bundle(iteration=1)
        jsonschema.validate(bundle, _load_bundle_schema())

    def test_bundle_with_invalid_tier_rejected(self) -> None:
        bundle = _make_bundle(iteration=1, tier=5)
        with self_assertions_raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())

    def test_bundle_with_tier_zero_rejected(self) -> None:
        bundle = _make_bundle(iteration=1, tier=0)
        with self_assertions_raises(jsonschema.ValidationError):
            jsonschema.validate(bundle, _load_bundle_schema())


# Helper since pytest's raises has different ergonomics
import pytest

def self_assertions_raises(exc):
    return pytest.raises(exc)


# ─── prior_iteration_tiers reads sibling iter-N/bundle.yaml ───────────────


class TestPriorTiersDiscovery:
    def test_finds_tiers_from_prior_iters(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _setup_iter(work_dir, 1, _make_bundle(iteration=1, tier=1))
        _setup_iter(work_dir, 2, _make_bundle(iteration=2, tier=2))
        _setup_iter(work_dir, 3, _make_bundle(iteration=3))  # no tier

        priors = prior_iteration_tiers(work_dir, up_to=3)
        assert priors == {1: 1, 2: 2}

    def test_excludes_self_iteration(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _setup_iter(work_dir, 1, _make_bundle(iteration=1, tier=1))
        _setup_iter(work_dir, 2, _make_bundle(iteration=2, tier=3))
        # Asking for priors of iter 2 should exclude iter 2 itself.
        priors = prior_iteration_tiers(work_dir, up_to=2)
        assert priors == {1: 1}

    def test_empty_work_dir(self, tmp_path: Path) -> None:
        assert prior_iteration_tiers(tmp_path / "nothing", up_to=1) == {}


# ─── detect_jump rules ────────────────────────────────────────────────────


class TestDetectJump:
    def test_iter_1_must_be_tier_1(self) -> None:
        warning = detect_jump(iteration=1, current_tier=2, prior_tiers={})
        assert warning is not None
        assert "iter 1" in warning.lower() or "iteration 1" in warning.lower()

    def test_iter_1_tier_1_no_warning(self) -> None:
        assert detect_jump(iteration=1, current_tier=1, prior_tiers={}) is None

    def test_one_step_escalation_no_warning(self) -> None:
        # iter 2, prior max = 1, current = 2 → fine.
        assert detect_jump(
            iteration=2, current_tier=2, prior_tiers={1: 1},
        ) is None

    def test_two_step_escalation_warns(self) -> None:
        # iter 2, prior max = 1, current = 3 → flagged.
        warning = detect_jump(
            iteration=2, current_tier=3, prior_tiers={1: 1},
        )
        assert warning is not None
        assert "tier" in warning.lower()
        assert "1" in warning  # prior max
        assert "3" in warning  # current

    def test_descent_no_warning(self) -> None:
        # iter 3, prior max = 2, current = 1 → tier dropped, fine.
        assert detect_jump(
            iteration=3, current_tier=1, prior_tiers={1: 2, 2: 2},
        ) is None

    def test_missing_tier_no_warning(self) -> None:
        # Legacy bundles without tier should not trigger.
        assert detect_jump(
            iteration=2, current_tier=None, prior_tiers={1: 1},
        ) is None


# ─── format_tier_summary renders the human-facing panel ───────────────────


class TestFormatTierSummary:
    def test_includes_tier_and_name(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        bundle = _make_bundle(iteration=1, tier=1, justification="simplest start")
        iter_dir = _setup_iter(work_dir, 1, bundle)

        out = format_tier_summary(
            iteration=1,
            bundle_path=iter_dir / "bundle.yaml",
            work_dir=work_dir,
        )
        assert "tier 1" in out.lower()
        assert TIER_NAMES[1] in out
        assert "simplest start" in out  # justification

    def test_iter_2_tier_3_panel_contains_warning(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _setup_iter(work_dir, 1, _make_bundle(iteration=1, tier=1))
        bundle = _make_bundle(
            iteration=2, tier=3,
            justification="iter-1 H-main was refuted, escalating to multi-mechanism",
        )
        iter_dir = _setup_iter(work_dir, 2, bundle)

        out = format_tier_summary(
            iteration=2, bundle_path=iter_dir / "bundle.yaml", work_dir=work_dir,
        )
        assert "tier 3" in out.lower()
        assert "TIER ESCALATION FLAGGED" in out
        assert "iter-1=tier1" in out  # prior summary

    def test_no_tier_returns_empty(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        bundle = _make_bundle(iteration=1)  # no complexity_tier
        iter_dir = _setup_iter(work_dir, 1, bundle)

        out = format_tier_summary(
            iteration=1, bundle_path=iter_dir / "bundle.yaml", work_dir=work_dir,
        )
        assert out == ""


# ─── Validate-design still passes for tier-tagged bundles ─────────────────


class TestValidateDesignAcceptsTier:
    def test_tier_1_iter_1_bundle_validates(self, tmp_path: Path) -> None:
        d = tmp_path / "iter-1"
        bundle = _make_bundle(iteration=1, tier=1, justification="x")
        d.mkdir()
        (d / "problem.md").write_text("## RQ\nq?\n")
        (d / "bundle.yaml").write_text(yaml.safe_dump(bundle))
        (d / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nx\n")
        result = validate_design(d)
        assert result["status"] == "pass", result.get("errors")

    def test_legacy_bundle_without_tier_validates(self, tmp_path: Path) -> None:
        """Backward compat: pre-#159 bundles still validate."""
        d = tmp_path / "iter-1"
        bundle = _make_bundle(iteration=1)
        d.mkdir()
        (d / "problem.md").write_text("## RQ\nq?\n")
        (d / "bundle.yaml").write_text(yaml.safe_dump(bundle))
        (d / "handoff_snapshot.md").write_text("## Handoff\n### Goal\nx\n")
        result = validate_design(d)
        assert result["status"] == "pass", result.get("errors")


# ─── Programmatic warnings list (for tests / CI) ──────────────────────────


class TestCollectTierWarnings:
    def test_clean_progression_yields_no_warnings(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _setup_iter(work_dir, 1, _make_bundle(iteration=1, tier=1))
        bundle_path = _setup_iter(
            work_dir, 2, _make_bundle(iteration=2, tier=2),
        ) / "bundle.yaml"
        assert collect_tier_warnings(2, bundle_path, work_dir) == []

    def test_jump_warns(self, tmp_path: Path) -> None:
        work_dir = tmp_path / "campaign"
        _setup_iter(work_dir, 1, _make_bundle(iteration=1, tier=1))
        bundle_path = _setup_iter(
            work_dir, 2, _make_bundle(iteration=2, tier=4),
        ) / "bundle.yaml"
        warnings = collect_tier_warnings(2, bundle_path, work_dir)
        assert len(warnings) == 1
        assert "tier" in warnings[0].lower()
