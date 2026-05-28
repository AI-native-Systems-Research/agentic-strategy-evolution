"""Tests for the prompt template loader."""
import logging
from pathlib import Path

import pytest

from orchestrator.prompt_loader import PromptLoader


@pytest.fixture()
def prompts_dir(tmp_path: Path) -> Path:
    """Create a temporary prompts directory with sample templates."""
    d = tmp_path / "prompts"
    d.mkdir()
    return d


def _write_template(prompts_dir: Path, name: str, content: str) -> None:
    (prompts_dir / f"{name}.md").write_text(content)


class TestPromptLoader:
    def test_load_and_render(self, prompts_dir: Path) -> None:
        _write_template(prompts_dir, "greet", "Hello, {{name}}!")
        loader = PromptLoader(prompts_dir)

        result = loader.load("greet", {"name": "Alice"})

        assert result == "Hello, Alice!"

    def test_missing_template_raises_file_not_found(self, prompts_dir: Path) -> None:
        loader = PromptLoader(prompts_dir)

        with pytest.raises(FileNotFoundError, match="no_such_template"):
            loader.load("no_such_template", {})

    def test_unreplaced_placeholder_raises_value_error(self, prompts_dir: Path) -> None:
        _write_template(prompts_dir, "needs_ctx", "Value: {{missing}}")
        loader = PromptLoader(prompts_dir)

        with pytest.raises(ValueError, match="missing"):
            loader.load("needs_ctx", {})

    def test_extra_context_keys_ignored(self, prompts_dir: Path) -> None:
        _write_template(prompts_dir, "simple", "Just text.")
        loader = PromptLoader(prompts_dir)

        result = loader.load("simple", {"unused_key": "whatever"})

        assert result == "Just text."

    def test_multiple_placeholders_replaced(self, prompts_dir: Path) -> None:
        _write_template(
            prompts_dir,
            "multi",
            "System: {{system}}\nMetric: {{metric}}\nKnob: {{knob}}",
        )
        loader = PromptLoader(prompts_dir)

        result = loader.load("multi", {
            "system": "BLIS",
            "metric": "TTFT",
            "knob": "batch_size",
        })

        assert result == "System: BLIS\nMetric: TTFT\nKnob: batch_size"

    def test_same_placeholder_multiple_times(self, prompts_dir: Path) -> None:
        _write_template(
            prompts_dir,
            "repeat",
            "{{name}} is great. We love {{name}}.",
        )
        loader = PromptLoader(prompts_dir)

        result = loader.load("repeat", {"name": "Nous"})

        assert result == "Nous is great. We love Nous."


class TestThinTemplateSelection:
    """#131 Phase B: when a CLAUDE.md exists at the configured path, the
    loader prefers ``<template>_thin.md`` so methodology is sourced from
    CLAUDE.md (auto-loaded) rather than re-shipped on every call."""

    def test_full_template_used_when_no_claude_md(self, prompts_dir, tmp_path):
        _write_template(prompts_dir, "design", "FULL methodology + {{name}}")
        _write_template(prompts_dir, "design_thin", "THIN: {{name}}")
        loader = PromptLoader(prompts_dir, claude_md_at=tmp_path / "no-such.md")

        result = loader.load("design", {"name": "BLIS"})
        assert "FULL methodology" in result

    def test_thin_template_picked_when_claude_md_exists(self, prompts_dir, tmp_path):
        _write_template(prompts_dir, "design", "FULL methodology + {{name}}")
        _write_template(prompts_dir, "design_thin", "THIN: {{name}}")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Methodology lives here.")

        loader = PromptLoader(prompts_dir, claude_md_at=claude_md)
        result = loader.load("design", {"name": "BLIS"})
        assert "FULL methodology" not in result
        assert "THIN: BLIS" == result

    def test_full_used_when_no_thin_variant_exists(self, prompts_dir, tmp_path):
        _write_template(prompts_dir, "report", "FULL report template {{x}}")
        # No report_thin.md.
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("...")

        loader = PromptLoader(prompts_dir, claude_md_at=claude_md)
        result = loader.load("report", {"x": "ok"})
        assert result == "FULL report template ok"

    def test_thin_template_strictly_smaller(self, prompts_dir, tmp_path):
        """Acceptance criterion #2: iter N+1 prompt is measurably smaller."""
        full_text = "Long methodology text. " * 200 + " Context: {{name}}"
        thin_text = "Refer to CLAUDE.md. Context: {{name}}"
        _write_template(prompts_dir, "design", full_text)
        _write_template(prompts_dir, "design_thin", thin_text)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("methodology")

        full_loader = PromptLoader(prompts_dir, claude_md_at=tmp_path / "no.md")
        thin_loader = PromptLoader(prompts_dir, claude_md_at=claude_md)

        full = full_loader.load("design", {"name": "x"})
        thin = thin_loader.load("design", {"name": "x"})
        # Thin must be ≥ 50% smaller — the issue's empirical criterion
        # for the token-shrink win.
        assert len(thin) < 0.5 * len(full)


class TestRealMethodologyThinTemplates:
    """The shipped design_thin.md / execute_analyze_thin.md must render
    against the same context shape the dispatcher already provides AND
    must be substantially smaller than their full counterparts."""

    REAL_PROMPTS_DIR = (
        Path(__file__).resolve().parent.parent / "prompts" / "methodology"
    )

    def _ctx_for_design(self) -> dict[str, str]:
        return {
            "iteration": "2",
            "target_system": "BLIS",
            "system_description": "Inference simulator.",
            "research_question": "What drives saturation?",
            "observable_metrics": "throughput, latency",
            "controllable_knobs": "batch_size, scheduling",
            "active_principles": "p1: ordinal scheduling helps.",
            "previous_handoff": "(none)",
            "previous_findings": "(none)",
            "human_feedback": "(none)",
            "iter_dir": "/tmp/iter-2",
            "nous_dir": "/path/to/nous",
            "repo_context": "(test)",
            "max_turns": "25",
            # #212: rehearsal/real mode rendered into the design prompt.
            "iteration_mode": "real",
            "mode_guidance": "(real-mode guidance text)",
        }

    def _ctx_for_execute(self) -> dict[str, str]:
        return {
            "iteration": "2",
            "target_system": "BLIS",
            "system_description": "Inference simulator.",
            "active_principles": "p1: ordinal scheduling helps.",
            "iter_dir": "/tmp/iter-2",
            "observable_metrics": "throughput, latency",
            "controllable_knobs": "batch_size, scheduling",
            # #221: rehearsal/real mode rendered into the execute prompt.
            "iteration_mode": "real",
            "mode_guidance": "(real-mode execute guidance)",
        }

    def test_design_thin_renders_and_is_smaller_than_full(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("methodology")
        full_loader = PromptLoader(self.REAL_PROMPTS_DIR)
        thin_loader = PromptLoader(self.REAL_PROMPTS_DIR, claude_md_at=claude_md)

        full = full_loader.load("design", self._ctx_for_design())
        thin = thin_loader.load("design", self._ctx_for_design())

        assert len(thin) < len(full)
        # The actual win is substantial — the full template is ~266 lines.
        assert len(thin) < 0.5 * len(full)

    def test_execute_analyze_thin_renders(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("...")
        loader = PromptLoader(self.REAL_PROMPTS_DIR, claude_md_at=claude_md)

        out = loader.load("execute_analyze", self._ctx_for_execute())
        assert "CLAUDE.md" in out
        assert "BLIS" in out


class TestWorktreeDisciplineGuidance:
    """#231 — both shipped EXECUTE_ANALYZE templates must carry the
    "Worktree discipline" guidance so the executor knows to stay in the
    worktree, reference parent assets via ``worktree_extras`` symlinks,
    and declare any new files via ``code_changes``.
    """

    REAL_PROMPTS_DIR = (
        Path(__file__).resolve().parent.parent / "prompts" / "methodology"
    )

    def test_full_template_carries_discipline_section(self):
        # Structural anchors only — match the *concepts* the section
        # must convey, not the exact prose. Editorial tweaks to the
        # surrounding language must not break this test.
        text = (self.REAL_PROMPTS_DIR / "execute_analyze.md").read_text()
        assert "Worktree discipline" in text
        assert "worktree_extras" in text
        assert "code_changes" in text

    def test_thin_template_carries_discipline_section(self):
        text = (self.REAL_PROMPTS_DIR / "execute_analyze_thin.md").read_text()
        assert "Worktree discipline" in text
        assert "worktree_extras" in text
        assert "code_changes" in text

    def test_thin_template_renders_with_existing_context(self, tmp_path):
        # The new section adds prose only — no new placeholders. Confirm
        # the existing dispatcher context still renders the template
        # without unreplaced-placeholder errors.
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("...")
        loader = PromptLoader(self.REAL_PROMPTS_DIR, claude_md_at=claude_md)
        ctx = {
            "iteration": "2",
            "target_system": "BLIS",
            "system_description": "Inference simulator.",
            "active_principles": "p1.",
            "iter_dir": "/tmp/iter-2",
            "observable_metrics": "throughput",
            "controllable_knobs": "batch_size",
            "iteration_mode": "real",
            "mode_guidance": "(guidance)",
        }
        out = loader.load("execute_analyze", ctx)
        assert "Worktree discipline" in out


class TestPlaceholderDiagnosticLogging:
    """#232 — when prompt rendering fails on unreplaced placeholders,
    the loader must emit a forensic log line listing both the missing
    placeholders AND the keys that were present in the context. The
    cross-account-signal-pooling campaign hit a non-deterministic
    `Unreplaced placeholders: iteration_mode, mode_guidance` on iter-2;
    the error message named what was missing, but operators had no way
    to tell whether the keys were absent or just spelled wrong.

    This issue does NOT fix the underlying bug — only ships diagnostics
    so the next occurrence produces actionable evidence.
    """

    def test_logs_missing_placeholders_and_context_keys(self, prompts_dir, caplog):
        _write_template(
            prompts_dir,
            "execute_analyze",
            "mode={{iteration_mode}}\nguide={{mode_guidance}}\nrest={{iter_dir}}",
        )
        loader = PromptLoader(prompts_dir)
        # Mimic the resume-bug shape: context has *some* keys but is
        # missing iteration_mode + mode_guidance.
        partial_context = {"iter_dir": "/tmp/iter-2", "target_system": "X"}

        with caplog.at_level(logging.ERROR, logger="orchestrator.prompt_loader"):
            with pytest.raises(ValueError, match="iteration_mode, mode_guidance"):
                loader.load("execute_analyze", partial_context)

        # The forensic log line must carry the two new fields. Match by
        # substring (not exact list-repr) so a future format swap (e.g.
        # comma-joined values, JSON, structured logging) doesn't break
        # the diagnostic intent — what matters is that a human reading
        # the log can see the missing names AND the present names.
        record = next(
            (r for r in caplog.records if r.levelname == "ERROR"
             and "prompt render failed" in r.getMessage()),
            None,
        )
        assert record is not None, "expected ERROR-level diagnostic log line"
        msg = record.getMessage()
        assert "missing_placeholders=" in msg
        assert "iteration_mode" in msg
        assert "mode_guidance" in msg
        assert "context_keys=" in msg
        assert "iter_dir" in msg
        assert "target_system" in msg
        assert "template=execute_analyze" in msg

    def test_no_log_on_successful_render(self, prompts_dir, caplog):
        _write_template(prompts_dir, "ok", "Hello {{name}}!")
        loader = PromptLoader(prompts_dir)
        with caplog.at_level(logging.ERROR, logger="orchestrator.prompt_loader"):
            loader.load("ok", {"name": "Nous"})
        assert not [
            r for r in caplog.records
            if "prompt render failed" in r.getMessage()
        ]
