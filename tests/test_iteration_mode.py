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

    def test_unknown_mode_raises_value_error(self):
        """Behavioral: silently defaulting to REAL on unknown mode is the
        more dangerous default (an unintended typo could run a full
        experiment when scope-shrink was meant). Fail loudly instead.
        """
        with pytest.raises(ValueError, match=r"unknown iteration mode"):
            mode_guidance_for("turbo")  # type: ignore[arg-type]


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


def _collected_prompt_text(dispatcher) -> str:
    """Aggregate every message content the dispatcher sent to the LLM.

    Helper so tests don't reach into the private completion_fn structure
    individually — if the dispatcher's message-shape ever evolves, this
    is the single point of update.
    """
    text_blocks: list[str] = []
    for call in dispatcher._completion.call_log:  # type: ignore[attr-defined]
        for msg in call.get("messages", []):
            content = msg.get("content", "")
            if isinstance(content, str):
                text_blocks.append(content)
    return "\n".join(text_blocks)


class TestDesignPromptIncludesMode:
    """The DESIGN extractor's prompt must include both placeholders so the
    methodology template can render mode-specific guidance.

    Covers BOTH the full-template path (no work_dir CLAUDE.md, used by
    fresh installs and tests with bare tmp_path) AND the thin-template
    path (work_dir CLAUDE.md present, the production hot path —
    campaign.py writes one before iter 1). A regression that drops
    placeholders from EITHER template is caught here.
    """

    @pytest.mark.parametrize("with_claude_md", [False, True],
                             ids=["full_template", "thin_template"])
    def test_rehearsal_renders_in_both_template_paths(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
            with_claude_md: bool) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        if with_claude_md:
            # #212 production-path coverage: the loader prefers the THIN
            # template when work_dir/CLAUDE.md exists. Without writing
            # this file, the test would silently exercise design.md
            # (full) and miss a regression in design_thin.md.
            (tmp_path / "CLAUDE.md").write_text("# Per-campaign methodology\n")

        c = _make_campaign(iterations=[{"mode": "rehearsal"}])
        d = LLMDispatcher(
            work_dir=tmp_path,
            campaign=c,
            completion_fn=_make_completion(["# stub design output"]),
        )
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)
        d.dispatch(
            "planner", "design",
            output_path=tmp_path / "runs" / "iter-1" / "design_log.md",
            iteration=1,
        )

        prompt_text = _collected_prompt_text(d)
        # Mode header is rendered (placeholder substituted, no leak).
        assert "rehearsal" in prompt_text, (
            f"#212: rehearsal mode must surface in the prompt regardless "
            f"of which template path is taken (with_claude_md="
            f"{with_claude_md}). Got prompt: {prompt_text[:600]}"
        )
        # Specific rehearsal-mode guidance the agent needs to scope-shrink.
        assert "Apparatus check" in prompt_text
        assert "Feasibility check" in prompt_text
        assert "ONE seed" in prompt_text
        # Sanity: no unfilled placeholders leaked through.
        assert "{{mode_guidance}}" not in prompt_text
        assert "{{iteration_mode}}" not in prompt_text

    @pytest.mark.parametrize("with_claude_md", [False, True],
                             ids=["full_template", "thin_template"])
    def test_real_iteration_does_not_leak_rehearsal_guidance(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
            with_claude_md: bool) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        if with_claude_md:
            (tmp_path / "CLAUDE.md").write_text("# Per-campaign methodology\n")

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

        prompt_text = _collected_prompt_text(d)
        # The mode value flows through.
        assert "real" in prompt_text.lower()
        # Rehearsal-specific scope-shrink language is NOT present.
        assert "ONE seed" not in prompt_text, (
            "#212 regression: real-mode iter leaked rehearsal scope "
            "guidance (with_claude_md=" + str(with_claude_md) + ")."
        )
        assert "Apparatus check" not in prompt_text
        # No unfilled placeholders leaked.
        assert "{{mode_guidance}}" not in prompt_text
        assert "{{iteration_mode}}" not in prompt_text


# ─── #221: execute-phase mode guidance ───────────────────────────────────


from orchestrator.iteration_mode import (
    EXECUTE_REHEARSAL_GUIDANCE,
    EXECUTE_REAL_GUIDANCE,
    execute_mode_guidance_for,
)


def _valid_execute_analyze_response() -> str:
    """Schema-passing stub for executor/execute-analyze so the
    dispatcher's parse path doesn't crash — lets prompt-content
    assertions run. Mirrors the shape from tests/test_llm_dispatch.py.
    """
    payload = {
        "plan": {
            "metadata": {"iteration": 1, "bundle_ref": "runs/iter-1/bundle.yaml"},
            "arms": [{"arm_id": "h-main",
                      "conditions": [{"name": "baseline",
                                      "cmd": "echo test"}]}],
        },
        "findings": {
            "iteration": 1,
            "bundle_ref": "runs/iter-1/bundle.yaml",
            "experiment_valid": True,
            "arms": [{
                "arm_type": "h-main",
                "predicted": "stub",
                "observed": "stub",
                "status": "CONFIRMED",
                "error_type": None,
                "diagnostic_note": "stub",
            }],
        },
        "principle_updates": [],
    }
    return "```json\n" + json.dumps(payload) + "\n```"


class TestExecuteModeGuidance:
    """#221: execute_mode_guidance_for returns phase-appropriate text
    distinct from mode_guidance_for. Rehearsal-mode execute guidance
    must instruct the agent to honor rehearsal_subset, NOT fan out
    the full bundle."""

    def test_rehearsal_mentions_rehearsal_subset_and_scope(self):
        text = execute_mode_guidance_for("rehearsal")
        assert text == EXECUTE_REHEARSAL_GUIDANCE
        # Critical scope-shrink instructions
        assert "rehearsal_subset" in text, (
            "#221: rehearsal-mode execute guidance must mention the "
            "rehearsal_subset bundle field — that's the structural "
            "scope-shrink mechanism."
        )
        assert "Do NOT fan out the full" in text, (
            "#221: rehearsal-mode execute guidance must imperative-forbid "
            "full fan-out (the post-#212 paper-burst rerun observed the "
            "agent fanning out the full bundle anyway because it had "
            "no signal not to)."
        )
        # Cross-reference to companion mechanisms:
        assert "brief_amendments.jsonl" in text  # #223
        assert "bundle_amendments.jsonl" in text  # #211
        assert "timing_observations" in text  # #226

    def test_real_mentions_full_scope_and_promotion_gate(self):
        text = execute_mode_guidance_for("real")
        assert text == EXECUTE_REAL_GUIDANCE
        assert "full" in text.lower()
        # Promotion-gate intent (#224): real iter respects BLOCKING amendments.
        assert "BLOCKING" in text
        assert "brief_amendments" in text

    def test_unknown_mode_raises_value_error(self):
        """Same fail-loud discipline as design-phase mode_guidance_for."""
        with pytest.raises(ValueError, match=r"unknown iteration mode"):
            execute_mode_guidance_for("turbo")  # type: ignore[arg-type]

    def test_design_and_execute_guidance_are_distinct(self):
        """Sanity: the two helpers return different strings (otherwise
        the whole #221 split is moot — DESIGN and EXECUTE would be
        getting the same prompt block)."""
        assert mode_guidance_for("rehearsal") != execute_mode_guidance_for("rehearsal")
        assert mode_guidance_for("real") != execute_mode_guidance_for("real")


class TestExecuteAnalyzeContextIncludesMode:
    """#221: the EXECUTE_ANALYZE-phase context populates iteration_mode +
    mode_guidance with execute-phase text. Tests at the ``_build_context``
    seam (the dispatcher's actual contract for prompt content) rather
    than driving the full dispatch+parse+validate pipeline — keeps the
    test focused on what #221 actually changes."""

    def _build_executor_ctx(self, tmp_path: Path,
                            campaign: dict,
                            monkeypatch: pytest.MonkeyPatch) -> dict:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # Pre-create the DESIGN artifacts the executor's context-builder
        # reads (bundle.yaml, problem.md, campaign-level handoff.md).
        iter1 = tmp_path / "runs" / "iter-1"
        iter1.mkdir(parents=True)
        (iter1 / "bundle.yaml").write_text(yaml.safe_dump({
            "metadata": {"iteration": 1, "family": "test",
                         "research_question": "?"},
            "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m",
                      "diagnostic": "d"}],
        }))
        (iter1 / "problem.md").write_text("## problem\nbrief\n")
        (tmp_path / "handoff.md").write_text("## prior handoff\n")

        d = LLMDispatcher(
            work_dir=tmp_path, campaign=campaign,
            completion_fn=_make_completion(["unused"]),
        )
        return d._build_context("executor", "execute-analyze",
                                iteration=1, perspective=None)

    def test_rehearsal_ctx_carries_execute_rehearsal_guidance(
            self, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        c = _make_campaign(iterations=[{"mode": "rehearsal"},
                                       {"mode": "real"}])
        ctx = self._build_executor_ctx(tmp_path, c, monkeypatch)

        assert ctx["iteration_mode"] == "rehearsal", (
            f"#221: iter-1 (rehearsal) ctx must carry mode; got {ctx['iteration_mode']!r}"
        )
        guidance = ctx["mode_guidance"]
        assert "rehearsal_subset" in guidance, (
            "#221: execute-phase rehearsal guidance must mention "
            "rehearsal_subset (scope-shrink mechanism)."
        )
        assert "Do NOT fan out" in guidance, (
            "#221: rehearsal guidance must imperative-forbid full fan-out."
        )
        # Companion mechanisms cross-referenced:
        assert "brief_amendments.jsonl" in guidance
        assert "timing_observations" in guidance

    def test_real_ctx_carries_execute_real_guidance(
            self, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        c = _make_campaign()  # no iterations block → real default
        ctx = self._build_executor_ctx(tmp_path, c, monkeypatch)

        assert ctx["iteration_mode"] == "real"
        guidance = ctx["mode_guidance"]
        # Real-mode guidance must mention BLOCKING amendment handling
        # (the promotion-gate intent) and full scope.
        assert "BLOCKING" in guidance
        assert "full" in guidance.lower()
        # Rehearsal-specific scope language should NOT be foregrounded.
        assert "Do NOT fan out" not in guidance

    def test_executor_ctx_distinct_from_design_ctx(
            self, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        """Sanity: design-phase and execute-phase ctx populate
        mode_guidance with DIFFERENT text, not the same string."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        c = _make_campaign(iterations=[{"mode": "rehearsal"}])
        d = LLMDispatcher(
            work_dir=tmp_path, campaign=c,
            completion_fn=_make_completion(["unused"]),
        )
        # Pre-create iter dir
        (tmp_path / "runs" / "iter-1").mkdir(parents=True)

        design_ctx = d._build_context("planner", "design",
                                      iteration=1, perspective=None)

        # And execute ctx (with prerequisite artifacts)
        iter1 = tmp_path / "runs" / "iter-1"
        (iter1 / "bundle.yaml").write_text(yaml.safe_dump({
            "metadata": {"iteration": 1, "family": "test",
                         "research_question": "?"},
            "arms": [{"type": "h-main", "prediction": "p", "mechanism": "m",
                      "diagnostic": "d"}],
        }))
        (iter1 / "problem.md").write_text("brief")
        (tmp_path / "handoff.md").write_text("handoff")
        execute_ctx = d._build_context("executor", "execute-analyze",
                                       iteration=1, perspective=None)

        assert design_ctx["mode_guidance"] != execute_ctx["mode_guidance"], (
            "#221: design-phase and execute-phase mode_guidance must "
            "differ — otherwise the whole phase-aware split is moot."
        )
