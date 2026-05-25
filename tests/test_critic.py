"""Behavioral tests for the Critic phase (issue #87).

Adds an opt-in CRITIC phase between DESIGN and HUMAN_DESIGN_GATE that
asks the most important scientific question: *"Can this experiment
fail?"* Composes with #85 (ground_truth independence), #86
(empirical_content), and #88 (theory_references) — together they
form the four-piece anti-tautology cluster from #84.

Test contract:
  - run_critic(bundle, critic_fn=) returns a CriticVerdict.
  - Default critic_fn is pure deterministic Python — no LLM, no
    randomness. It catches the obvious anti-tautology red flags.
  - Phase.CRITIC is in the engine enum + transition map; legacy
    DESIGN → HUMAN_DESIGN_GATE retained for opt-out.
  - state.schema.json accepts CRITIC as a phase value.
  - Critic prompt file prompts/methodology/critique.md exists
    (cached system block — LLM-based critic seam).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.critic import CriticVerdict, run_critic
from orchestrator.engine import Phase, TRANSITIONS


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_schema(name: str) -> dict:
    if name.endswith(".json"):
        return json.loads((SCHEMAS_DIR / name).read_text())
    import yaml
    return yaml.safe_load((SCHEMAS_DIR / name).read_text())


def _bundle(*, ground_truth=None, arms=None, theory_references=None) -> dict:
    bundle: dict = {
        "metadata": {"iteration": 1, "family": "test", "research_question": "q?"},
        "arms": arms or [{
            "type": "h-main",
            "prediction": "metric will exceed 0.7 across 10 seeds",
            "mechanism": "m", "diagnostic": "d",
        }],
    }
    if ground_truth is not None:
        bundle["ground_truth"] = ground_truth
    if theory_references is not None:
        bundle["theory_references"] = theory_references
    return bundle


# ─── Default critic — deterministic Python ────────────────────────────────


class TestDefaultCritic:
    def test_clean_bundle_can_fail(self) -> None:
        """Independent ground truth + falsifiable predictions ⇒ can_fail=True."""
        bundle = _bundle(ground_truth={
            "definition": "scheduling delay growing over time",
            "measurement_type": "trend",
            "detector_measurement_type": "flow",
            "independence_argument": "different physical signals",
            "shares_computation_with_detector": False,
        })
        verdict = run_critic(bundle)
        assert verdict.can_fail is True
        assert verdict.issues == []

    def test_self_declared_tautology_flagged(self) -> None:
        """shares_computation_with_detector=true is a hard tautology.
        Critic returns can_fail=False with the issue cited."""
        bundle = _bundle(ground_truth={
            "definition": "x",
            "shares_computation_with_detector": True,
        })
        verdict = run_critic(bundle)
        assert verdict.can_fail is False
        assert any("tautolog" in i.lower() or "shares_computation" in i
                   for i in verdict.issues)

    def test_missing_ground_truth_flagged_as_warning(self) -> None:
        """No ground_truth block on a bundle with detectors ⇒ warning,
        not a hard fail. The Critic asks the human to decide."""
        bundle = _bundle()  # no ground_truth
        verdict = run_critic(bundle)
        # Not a hard fail but the issues list mentions it
        assert any("ground_truth" in i.lower() for i in verdict.issues)

    def test_same_measurement_types_flagged(self) -> None:
        """Same measurement type on both sides ⇒ warning (not hard fail)."""
        bundle = _bundle(ground_truth={
            "definition": "x",
            "measurement_type": "flow",
            "detector_measurement_type": "flow",
            "independence_argument": "different windows",
            "shares_computation_with_detector": False,
        })
        verdict = run_critic(bundle)
        assert any("measurement_type" in i for i in verdict.issues)

    def test_verdict_carries_reasoning(self) -> None:
        """The verdict includes plain-English reasoning so the gate
        summary can render it for the human."""
        bundle = _bundle(ground_truth={
            "definition": "x", "shares_computation_with_detector": True,
        })
        verdict = run_critic(bundle)
        assert isinstance(verdict, CriticVerdict)
        assert isinstance(verdict.reasoning, str)
        assert len(verdict.reasoning) > 0


# ─── Injection seam ───────────────────────────────────────────────────────


class TestCriticFnInjection:
    def test_injected_fn_replaces_default(self) -> None:
        """Tests inject a deterministic stub via critic_fn=. The default
        path is never reached — confirmed by the stub being called."""
        invocations: list = []

        def fake_fn(bundle):
            invocations.append(bundle)
            return CriticVerdict(
                can_fail=False, issues=["fake issue"],
                reasoning="injected verdict",
            )

        verdict = run_critic({"x": 1}, critic_fn=fake_fn)
        assert verdict.reasoning == "injected verdict"
        assert verdict.issues == ["fake issue"]
        assert len(invocations) == 1


# ─── Engine state machine ─────────────────────────────────────────────────


class TestPhaseRegistration:
    def test_critic_is_in_phase_enum(self) -> None:
        assert Phase.CRITIC.value == "CRITIC"

    def test_design_can_transition_to_critic(self) -> None:
        """Opt-in: DESIGN may go to CRITIC instead of HUMAN_DESIGN_GATE."""
        assert "CRITIC" in TRANSITIONS["DESIGN"]

    def test_design_can_still_transition_to_human_gate(self) -> None:
        """Backward compat: legacy DESIGN → HUMAN_DESIGN_GATE retained."""
        assert "HUMAN_DESIGN_GATE" in TRANSITIONS["DESIGN"]

    def test_critic_transitions_to_human_design_gate(self) -> None:
        assert "HUMAN_DESIGN_GATE" in TRANSITIONS["CRITIC"]


# ─── Schemas ──────────────────────────────────────────────────────────────


class TestStateSchemaAcceptsCritic:
    def test_state_with_critic_phase_validates(self) -> None:
        state = {
            "phase": "CRITIC", "iteration": 1, "run_id": "demo",
            "family": None, "timestamp": "2026-05-25T00:00:00Z",
        }
        jsonschema.validate(state, _load_schema("state.schema.json"))


# ─── Methodology prompt for LLM-based critic ──────────────────────────────


class TestCritiquePromptExists:
    def test_critique_md_exists(self) -> None:
        prompt = (Path(__file__).resolve().parent.parent
                  / "prompts" / "methodology" / "critique.md")
        assert prompt.exists()
        text = prompt.read_text()
        # Should ask the canonical question and reference the related fields.
        assert "fail" in text.lower()
        assert "ground_truth" in text or "independence" in text.lower()
