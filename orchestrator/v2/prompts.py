"""Light method prompt and task-type checklists (spec 3.12)."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "v2"


def load_method_prompt() -> str:
    return (_PROMPTS_DIR / "method.md").read_text()


def load_checklist(task_type: str) -> str | None:
    if task_type == "other":
        return None
    path = _PROMPTS_DIR / "checklists" / f"{task_type}.md"
    if not path.is_file():
        return None
    return path.read_text()


def build_system_prompt(task_type: str | None = None) -> str:
    prompt = load_method_prompt()
    if task_type:
        checklist = load_checklist(task_type)
        if checklist:
            prompt += "\n\n" + checklist
    return prompt
