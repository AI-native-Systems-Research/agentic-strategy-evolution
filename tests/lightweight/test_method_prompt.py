"""The method note (prompts/lightweight/method.md) and the task-type checklists."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.lightweight.loop import method_text
from orchestrator.lightweight.prompts import load_checklist

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "lightweight"
METHOD = (PROMPTS_DIR / "method.md").read_text()

# ── method.md constraints ────────────────────────────────────────────────


class TestMethodPrompt:
    def test_size_limit(self):
        assert len(METHOD.encode()) <= 6144, f"method.md is {len(METHOD.encode())} bytes, limit is 6144"

    def test_names_the_files_and_fields_nous_checks(self):
        for name in ("notebook.jsonl", "answer.json", "$NOUS_WORK_DIR", "hypothesis", "result",
                     "predict", "evidence", "repro", "claims", "deliverable"):
            assert name in METHOD, f"{name!r} not in method note"

    def test_no_phase_artifacts(self):
        for name in ("baseline.json", "bundle.json", "plan.json", "findings.json", "principle_updates"):
            assert name not in METHOD


# ── checklists ───────────────────────────────────────────────────────────


TASK_TYPES = ["debug", "verify", "optimize", "policy", "explain"]


class TestChecklists:
    @pytest.mark.parametrize("task_type", TASK_TYPES)
    def test_checklist_file_exists(self, task_type):
        path = PROMPTS_DIR / "checklists" / f"{task_type}.md"
        assert path.is_file(), f"checklist missing: {path}"

    @pytest.mark.parametrize("task_type", TASK_TYPES)
    def test_checklist_size_limit(self, task_type):
        text = (PROMPTS_DIR / "checklists" / f"{task_type}.md").read_text()
        assert len(text.encode()) <= 800, (
            f"{task_type}.md is {len(text.encode())} bytes, soft limit ~600"
        )

    @pytest.mark.parametrize("task_type", TASK_TYPES)
    def test_load_checklist_returns_string(self, task_type):
        result = load_checklist(task_type)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_other_returns_none(self):
        assert load_checklist("other") is None

    def test_unknown_returns_none(self):
        assert load_checklist("nonexistent_type_xyz") is None


# ── method_text: the system-prompt append ────────────────────────────────


class TestMethodText:
    @pytest.mark.parametrize("task_type", [None, "other", "nonexistent_type_xyz"])
    def test_no_checklist_returns_method_only(self, task_type):
        assert method_text(task_type) == METHOD

    @pytest.mark.parametrize("task_type", TASK_TYPES)
    def test_known_type_appends_checklist(self, task_type):
        assert method_text(task_type) == METHOD + "\n\n" + load_checklist(task_type)

    def test_combined_still_under_limit(self):
        for task_type in TASK_TYPES:
            size = len(method_text(task_type).encode())
            assert size <= 8192, f"combined prompt for {task_type} is {size} bytes"
