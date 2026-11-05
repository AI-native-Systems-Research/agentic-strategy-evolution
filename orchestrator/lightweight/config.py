"""Campaign configuration parsing."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Keys accepted without a warning. Some are read only by older Nous versions and are ignored
# here (locked_parameters, locked_workload, human_gates, min_improvement, stall_iterations,
# session_scope, task_limits, objective, rerun_repro, nous_version).
_KNOWN_KEYS = frozenset({
    "research_question", "target_system", "run_id", "max_iterations", "models", "model",
    "locked_parameters", "locked_workload", "effort", "human_gates", "secrets",
    "min_improvement", "stall_iterations", "task_type", "session_scope",
    "experiment_commands", "task_limits", "objective", "rerun_repro", "nous_version",
})

_REQUIRED_KEYS = ("research_question", "target_system")


@dataclass
class CampaignConfig:
    research_question: str
    run_id: str
    max_iterations: int
    target_system: dict
    model: str | None = None
    effort: str | None = None
    secrets: list[str] = field(default_factory=list)
    task_type: str | None = None
    experiment_commands: list[str] | None = None  # None = hooks.DEFAULT_EXPERIMENT_COMMANDS


def parse_campaign_config(raw: dict) -> CampaignConfig:
    for key in _REQUIRED_KEYS:
        if key not in raw:
            raise ValueError(f"campaign.yaml missing required key: {key}")

    ts = raw["target_system"]
    if not isinstance(ts, dict) or "repo_path" not in ts:
        raise ValueError(
            "campaign.yaml: target_system must contain 'repo_path' "
            "(the path to the target git repo)"
        )

    for key in sorted(raw.keys() - _KNOWN_KEYS):
        logger.warning("campaign.yaml: ignoring unknown or legacy key %r", key)
    models = raw.get("models") or {}

    return CampaignConfig(
        research_question=raw["research_question"],
        run_id=raw.get("run_id", "unnamed"),
        max_iterations=raw.get("max_iterations", 5),
        target_system=raw["target_system"],
        model=models.get("session") or models.get("design") or raw.get("model"),
        effort=raw.get("effort"),
        secrets=raw.get("secrets", []),
        task_type=raw.get("task_type"),
        experiment_commands=raw.get("experiment_commands"),
    )


def validator_limits(cfg: CampaignConfig, work_dir: Path) -> dict:
    """What every ValidatorContext needs: secret values and the repo root for evidence paths."""
    return {"secrets": {k: os.environ.get(k, "") for k in cfg.secrets},
            "repo_dir": Path(cfg.target_system["repo_path"]) if cfg.target_system.get("repo_path") else None}
