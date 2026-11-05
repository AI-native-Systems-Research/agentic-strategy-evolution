"""Task-type checklists appended to the method note."""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "lightweight"


def load_checklist(task_type: str) -> str | None:
    if task_type == "other":
        return None
    path = _PROMPTS_DIR / "checklists" / f"{task_type}.md"
    if not path.is_file():
        return None
    return path.read_text()
