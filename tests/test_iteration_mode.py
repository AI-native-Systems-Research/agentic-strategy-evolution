"""Tests for per-iteration mode resolution (#212).

The campaign's optional ``iterations: [...]`` list lets operators schedule
rehearsal vs real iterations. The DESIGN methodology reads the mode and
adapts. Tests below assert: (1) the resolver returns the right mode for
each iteration index, (2) the resolver defaults to ``real`` for missing
or malformed config, (3) the design context includes both ``iteration_mode``
and ``mode_guidance`` keys, and (4) the schema accepts the new block.

No live LLM calls — pure helpers + LLMDispatcher seam injection.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from orchestrator.iteration_mode import (
    DEFAULT_MODE,
    REAL_GUIDANCE,
    REHEARSAL_GUIDANCE,
    VALID_MODES,
    iteration_mode_for,
    mode_guidance_for,
)
from orchestrator.llm_dispatch import LLMDispatcher


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_campaign_schema() -> dict:
    return yaml.safe_load((SCHEMAS_DIR / "campaign.schema.yaml").read_text())


def _make_completion(responses: list[str]):
    """Mock completion fn that records call kwargs."""
    call_log: list[dict] = []
    idx = {"n": 0}

    def _fn(**kwargs):
        call_log.append(kwargs)
        resp = MagicMock()
        resp.choices = [
            MagicMock(message=MagicMock(content=responses[idx["n"]])),
        ]
        idx["n"] += 1
        return resp

    _fn.call_log = call_log  # type: ignore[attr-defined]
    return _fn


def _make_campaign(*, iterations=None) -> dict:
    c = {
        "research_question": "Does X work?",
        "target_system": {
            "name": "X",
            "description": "test target",
            "observable_metrics": ["m"],
            "controllable_knobs": ["k"],
        },
        "prompts": {
            "methodology_layer": "prompts/methodology",
            "domain_adapter_layer": None,
        },
    }
    if iterations is not None:
        c["iterations"] = iterations
    return c


# ─── iteration_mode_for resolver ─────────────────────────────────────────


class TestIterationModeFor:
    def test_no_iterations_block_returns_real(self):
        assert iteration_mode_for({}, 1) == "real"
        assert iteration_mode_for(_make_campaign(), 1) == "real"

    def test_empty_iterations_list_returns_real(self):
        assert iteration_mode_for(_make_campaign(iterations=[]), 1) == "real"

    def test_explicit_rehearsal_for_iter_1(self):
        c = _make_campaign(iterations=[{"mode": "rehearsal"}])
        assert iteration_mode_for(c, 1) == "rehearsal"

    def test_per_index_lookup(self):
        c = _make_campaign(iterations=[
            {"mode": "rehearsal"},
            {"mode": "real"},
            {"mode": "real"},
        ])
        assert iteration_mode_for(c, 1) == "rehearsal"
        assert iteration_mode_for(c, 2) == "real"
        assert iteration_mode_for(c, 3) == "real"

    def test_out_of_range_iteration_returns_default(self):
        c = _make_campaign(iterations=[{"mode": "rehearsal"}])
        # Only 1 entry; iter-2 falls back to real.
        assert iteration_mode_for(c, 2) == "real"
        assert iteration_mode_for(c, 99) == "real"

    def test_zero_or_negative_iteration_returns_default(self):
        c = _make_campaign(iterations=[{"mode": "rehearsal"}])
        assert iteration_mode_for(c, 0) == "real"
        assert iteration_mode_for(c, -1) == "real"

    def test_malformed_entry_returns_default(self):
        # Entry isn't a dict
        c = _make_campaign(iterations=["rehearsal"])
        assert iteration_mode_for(c, 1) == "real"
        # Entry has no mode field
        c = _make_campaign(iterations=[{"other": "x"}])
        assert iteration_mode_for(c, 1) == "real"
        # Entry has invalid mode
        c = _make_campaign(iterations=[{"mode": "fast"}])
        assert iteration_mode_for(c, 1) == "real"

    def test_default_mode_constant(self):
        assert DEFAULT_MODE == "real"
        assert "rehearsal" in VALID_MODES
        assert "real" in VALID_MODES


# ─── mode_guidance_for renders the right text ────────────────────────────


class TestModeGuidance:
    def test_rehearsal_guidance_mentions_apparatus_and_feasibility(self):
        text = mode_guidance_for("rehearsal")
        assert text == REHEARSAL_GUIDANCE
        assert "Apparatus check" in text
        assert "Feasibility check" in text
        assert "brief_amendments" in text
        assert "ONE seed" in text

    def test_real_guidance_mentions_full_scope(self):
        text = mode_guidance_for("real")
        assert text == REAL_GUIDANCE
        assert "full scope" in text.lower() or "full bundle" in text.lower()
        assert "brief_amendments" in text

    def test_unknown_mode_falls_back_to_real(self):
        assert mode_guidance_for("turbo") == REAL_GUIDANCE


# ─── Schema accepts the new iterations block ─────────────────────────────


class TestSchemaIterationsBlock:
    def test_no_iterations_block_validates(self):
        c = _make_campaign()
        jsonschema.validate(c, _load_campaign_schema())

    def test_iterations_block_validates(self):
        c = _make_campaign(iterations=[
            {"mode": "rehearsal"},
            {"mode": "real"},
        ])
        jsonschema.validate(c, _load_campaign_schema())

    def test_invalid_mode_value_rejected(self):
        c = _make_campaign(iterations=[{"mode": "fast"}])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(c, _load_campaign_schema())

    def test_unknown_field_rejected(self):
        c = _make_campaign(iterations=[
            {"mode": "rehearsal", "unknown_field": "x"},
        ])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(c, _load_campaign_schema())

    def test_missing_mode_rejected(self):
        c = _make_campaign(iterations=[{}])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(c, _load_campaign_schema())


# ─── Design phase prompt includes the mode block ─────────────────────────


class TestDesignPromptIncludesMode:
    """The DESIGN extractor's prompt must include both placeholders so the
    methodology template can render mode-specific guidance."""

    def test_rehearsal_iteration_renders_rehearsal_guidance_in_prompt(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Provide a stub API key so LLMDispatcher initialises a completion fn
        # — we'll override via completion_fn anyway.
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        c = _make_campaign(iterations=[{"mode": "rehearsal"}])
        d = LLMDispatcher(
            work_dir=tmp_path,
            campaign=c,
            completion_fn=_make_completion(["# stub design output"]),
        )
        # Pre-create iter dir so the dispatcher can write into it.
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)

        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )

        # The first call's user message should contain rehearsal guidance.
        all_prompt = ""
        for call in d._completion.call_log:  # type: ignore[attr-defined]
            for msg in call.get("messages", []):
                all_prompt += msg.get("content", "") + "\n"

        assert "REHEARSAL" in all_prompt, (
            "#212: rehearsal iteration's prompt should announce the mode."
        )
        assert "Apparatus check" in all_prompt, (
            "#212: rehearsal guidance must include the apparatus-check goal."
        )
        assert "Feasibility check" in all_prompt
        # Default mode would put REAL guidance here — verify rehearsal won.
        assert "ONE seed" in all_prompt

    def test_real_iteration_renders_real_guidance_in_prompt(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        c = _make_campaign()  # no iterations block — defaults to real
        d = LLMDispatcher(
            work_dir=tmp_path,
            campaign=c,
            completion_fn=_make_completion(["# stub"]),
        )
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )

        all_prompt = ""
        for call in d._completion.call_log:  # type: ignore[attr-defined]
            for msg in call.get("messages", []):
                all_prompt += msg.get("content", "") + "\n"

        # No rehearsal-specific guidance leaked into a real-mode iter.
        assert "REHEARSAL" not in all_prompt or all_prompt.count("REHEARSAL") <= 1
        # The real-mode guidance phrase is present.
        assert "full scope" in all_prompt.lower() or "full bundle" in all_prompt.lower()
