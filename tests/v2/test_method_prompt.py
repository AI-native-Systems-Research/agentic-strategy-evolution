"""Tests for the light method prompt and task-type checklists (R8, spec 3.12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.v2.prompts import (
    build_system_prompt,
    load_checklist,
    load_method_prompt,
)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "v2"

# ── method.md constraints ────────────────────────────────────────────────


class TestMethodPrompt:
    def test_file_exists(self):
        assert (PROMPTS_DIR / "method.md").is_file()

    def test_size_limit(self):
        text = (PROMPTS_DIR / "method.md").read_text()
        assert len(text.encode()) <= 6144, (
            f"method.md is {len(text.encode())} bytes, limit is 6144"
        )

    def test_load_returns_nonempty_string(self):
        prompt = load_method_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_required_field_names_present(self):
        prompt = load_method_prompt()
        required = [
            "family",
            "prediction",
            "control",
            "falsified_if",
            "status",
            "error_type",
            "evidence",
            "question_answered",
            "finding_ref",
        ]
        for field in required:
            assert field in prompt, f"required field name {field!r} not in method prompt"

    def test_required_artifact_names_present(self):
        prompt = load_method_prompt()
        artifacts = [
            "baseline.json",
            "bundle.json",
            "plan.json",
            "findings.json",
            "principle_updates.json",
            "answer.json",
            "report.md",
            "problem.json",
        ]
        for name in artifacts:
            assert name in prompt, f"artifact {name!r} not in method prompt"

    def test_no_arm_menu(self):
        prompt = load_method_prompt()
        assert "arm menu" not in prompt.lower()
        assert "required arm" not in prompt.lower()

    def test_no_complexity_tier_prose(self):
        prompt = load_method_prompt()
        assert "complexity_tier" not in prompt
        assert "complexity tier" not in prompt.lower()


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


# ── build_system_prompt ──────────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_no_task_type_returns_method_only(self):
        prompt = build_system_prompt()
        method = load_method_prompt()
        assert prompt == method

    def test_other_returns_method_only(self):
        prompt = build_system_prompt("other")
        method = load_method_prompt()
        assert prompt == method

    @pytest.mark.parametrize("task_type", TASK_TYPES)
    def test_known_type_appends_checklist(self, task_type):
        prompt = build_system_prompt(task_type)
        method = load_method_prompt()
        checklist = load_checklist(task_type)
        assert prompt.startswith(method)
        assert checklist in prompt
        assert len(prompt) > len(method)

    def test_combined_still_under_limit(self):
        for task_type in TASK_TYPES:
            prompt = build_system_prompt(task_type)
            size = len(prompt.encode())
            assert size <= 8192, (
                f"combined prompt for {task_type} is {size} bytes"
            )
