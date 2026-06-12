"""Prompt template loading and rendering for the Nous orchestrator.

Loads markdown prompt templates from disk and renders them by replacing
``{{placeholder}}`` markers with context values.

When a campaign-level CLAUDE.md is in scope (issue #131), the loader
prefers ``<template>_thin.md`` over the full ``<template>.md`` for any
template that ships a thin variant. The thin variant carries only the
per-iteration context and refers the agent to CLAUDE.md for the
methodology — that's the token-shrink win.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptLoader:
    """Load and render prompt templates with ``{{variable}}`` substitution."""

    def __init__(
        self,
        prompts_dir: Path,
        *,
        claude_md_at: Path | None = None,
    ) -> None:
        self.prompts_dir = Path(prompts_dir)
        self._claude_md_at = Path(claude_md_at) if claude_md_at else None

    def _resolve_template_path(self, template_name: str) -> Path:
        """Pick thin or full variant based on whether CLAUDE.md is in scope."""
        if self._claude_md_at is not None and self._claude_md_at.exists():
            thin = self.prompts_dir / f"{template_name}_thin.md"
            if thin.is_file():
                return thin
        return self.prompts_dir / f"{template_name}.md"

    def load(self, template_name: str, context: dict[str, str]) -> str:
        """Load *template_name*.md and replace ``{{key}}`` with *context[key]*.

        Returns the rendered prompt string.

        Raises:
            FileNotFoundError: Template file does not exist.
            ValueError: Template contains unreplaced ``{{placeholders}}``
                after rendering (i.e. required context keys were not provided).
        """
        path = self._resolve_template_path(template_name)
        if not path.is_file():
            raise FileNotFoundError(
                f"Prompt template not found: {path}"
            )

        text = path.read_text()
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", value)

        remaining = _PLACEHOLDER_RE.findall(text)
        if remaining:
            missing = sorted(set(remaining))
            # #232: forensic logging on the resume-time placeholder bug.
            # The error message names the missing placeholders; we add
            # what keys WERE present in the context so the next
            # occurrence produces evidence pointing at the actual cause
            # (phase string mismatch, stale loader, resume-path field
            # uninitialized, ...).
            logger.error(
                "prompt render failed: template=%s resolved_path=%s "
                "missing_placeholders=%s context_keys=%s",
                template_name, path, missing, sorted(context.keys()),
            )
            raise ValueError(
                f"Unreplaced placeholders in {template_name}.md: "
                f"{', '.join(missing)}"
            )

        logger.debug("Loaded prompt %s (%d chars)", template_name, len(text))
        return text
