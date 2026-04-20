"""Tests for the prompt template loader."""
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
