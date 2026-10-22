"""Campaign configuration parsing (spec 3.1)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_KNOWN_KEYS = frozenset({
    "research_question", "target_system", "run_id", "max_iterations", "models",
    "locked_parameters", "locked_workload", "effort", "human_gates", "secrets",
    "min_improvement", "stall_iterations", "task_type", "session_scope",
    "experiment_commands", "task_limits", "objective", "rerun_repro",
})

_REQUIRED_KEYS = ("research_question", "target_system")


@dataclass
class CampaignConfig:
    research_question: str
    run_id: str
    max_iterations: int
    target_system: dict
    model: str | None = None
    locked_parameters: dict | None = None
    locked_workload: dict | None = None
    effort: str | None = None
    human_gates: bool = False
    secrets: list[str] = field(default_factory=list)
    min_improvement: float = 0
    stall_iterations: int = 2
    task_type: str | None = None
    session_scope: str = "campaign"
    experiment_commands: list[str] = field(default_factory=list)
    task_limits: dict | None = None
    objective: dict | None = None
    rerun_repro: bool = False


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
        model=models.get("session") or models.get("design"),
        locked_parameters=raw.get("locked_parameters"),
        locked_workload=raw.get("locked_workload"),
        effort=raw.get("effort"),
        human_gates=raw.get("human_gates", False),
        secrets=raw.get("secrets", []),
        min_improvement=raw.get("min_improvement", 0),
        stall_iterations=raw.get("stall_iterations", 2),
        task_type=raw.get("task_type"),
        session_scope=raw.get("session_scope", "campaign"),
        experiment_commands=raw.get("experiment_commands", []),
        task_limits=raw.get("task_limits"),
        objective=raw.get("objective"),
        rerun_repro=raw.get("rerun_repro", False),
    )


def validator_limits(cfg: CampaignConfig, work_dir: Path) -> dict:
    """Campaign limits every ValidatorContext needs (spec 3.4, 3.14)."""
    return {"locked_parameters": cfg.locked_parameters, "locked_workload": cfg.locked_workload,
            "task_limits": cfg.task_limits, "runs_jsonl": work_dir / "runs.jsonl",
            "secrets": {k: os.environ.get(k, "") for k in cfg.secrets}}
