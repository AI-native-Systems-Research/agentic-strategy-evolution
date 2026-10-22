"""Campaign configuration parsing (spec 3.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_LEGACY_KEYS = frozenset({
    "critic", "pre_work", "arm_sweep", "parallel_arms",
    "complexity_tiers", "iteration_mode",
})

_REQUIRED_KEYS = ("research_question", "target_system")


@dataclass
class CampaignConfig:
    research_question: str
    run_id: str
    max_iterations: int
    target_system: dict
    prompts: dict = field(default_factory=dict)
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

    for key in _LEGACY_KEYS & raw.keys():
        logger.warning("campaign.yaml: ignoring legacy key %r", key)

    return CampaignConfig(
        research_question=raw["research_question"],
        run_id=raw.get("run_id", "unnamed"),
        max_iterations=raw.get("max_iterations", 5),
        target_system=raw["target_system"],
        prompts=raw.get("prompts", {}),
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
    )
