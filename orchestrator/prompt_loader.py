"""Prompt template loading and rendering for the Nous orchestrator.

Loads markdown prompt templates from disk and renders them by replacing
``{{placeholder}}`` markers with context values.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptLoader:
    """Load and render prompt templates with ``{{variable}}`` substitution."""

    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = Path(prompts_dir)

    def load(self, template_name: str, context: dict[str, str]) -> str:
        """Load *template_name*.md and replace ``{{key}}`` with *context[key]*.

        Returns the rendered prompt string.

        Raises:
            FileNotFoundError: Template file does not exist.
            ValueError: Template contains unreplaced ``{{placeholders}}``
                after rendering (i.e. required context keys were not provided).
        """
        path = self.prompts_dir / f"{template_name}.md"
        if not path.is_file():
            raise FileNotFoundError(
                f"Prompt template not found: {path}"
            )

        text = path.read_text()
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", value)

        remaining = _PLACEHOLDER_RE.findall(text)
        if remaining:
            raise ValueError(
                f"Unreplaced placeholders in {template_name}.md: "
                f"{', '.join(sorted(set(remaining)))}"
            )

        logger.debug("Loaded prompt %s (%d chars)", template_name, len(text))
        return text
