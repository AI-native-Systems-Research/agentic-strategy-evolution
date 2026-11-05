"""campaign.yaml parsing."""

from __future__ import annotations

import logging

import pytest

from orchestrator.lightweight.config import parse_campaign_config


def _campaign_yaml(
    *,
    research_question: str = "Is the bug fixable?",
    run_id: str = "test-run",
    max_iterations: int = 3,
    target_name: str = "test-project",
    repo_path: str = "/tmp/repo",
) -> dict:
    return {
        "research_question": research_question,
        "run_id": run_id,
        "max_iterations": max_iterations,
        "target_system": {
            "name": target_name,
            "description": "A test project",
            "repo_path": repo_path,
        },
    }


# ── parse_campaign_config tests ──────────────────────────────────────────


class TestParseCampaignConfig:
    def test_minimal_valid(self):
        raw = _campaign_yaml()
        cfg = parse_campaign_config(raw)
        assert cfg.research_question == "Is the bug fixable?"
        assert cfg.run_id == "test-run"
        assert cfg.max_iterations == 3
        assert cfg.effort is None and cfg.secrets == [] and cfg.task_type is None

    def test_all_optional_fields(self):
        raw = _campaign_yaml()
        raw["effort"] = "high"
        raw["secrets"] = ["API_KEY"]
        raw["task_type"] = "debug"
        raw["experiment_commands"] = ["make perf"]
        cfg = parse_campaign_config(raw)
        assert cfg.effort == "high"
        assert cfg.secrets == ["API_KEY"]
        assert cfg.task_type == "debug"
        assert cfg.experiment_commands == ["make perf"]

    def test_missing_research_question_raises(self):
        raw = _campaign_yaml()
        del raw["research_question"]
        with pytest.raises(ValueError, match="research_question"):
            parse_campaign_config(raw)

    def test_missing_target_system_raises(self):
        raw = _campaign_yaml()
        del raw["target_system"]
        with pytest.raises(ValueError, match="target_system"):
            parse_campaign_config(raw)

    def test_missing_repo_path_raises(self):
        raw = _campaign_yaml()
        del raw["target_system"]["repo_path"]
        with pytest.raises(ValueError, match="repo_path"):
            parse_campaign_config(raw)

    def test_target_system_not_dict_raises(self):
        raw = _campaign_yaml()
        raw["target_system"] = "just-a-string"
        with pytest.raises(ValueError, match="repo_path"):
            parse_campaign_config(raw)

    def test_legacy_keys_warn(self, caplog):
        raw = _campaign_yaml()
        raw["critic"] = True
        raw["arm_sweep"] = True
        with caplog.at_level(logging.WARNING):
            cfg = parse_campaign_config(raw)
        assert any("critic" in r.message for r in caplog.records)
        assert cfg.research_question == "Is the bug fixable?"

    def test_default_max_iterations(self):
        raw = _campaign_yaml()
        del raw["max_iterations"]
        cfg = parse_campaign_config(raw)
        assert cfg.max_iterations == 5
