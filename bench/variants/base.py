"""Variant contract for nous-bench. See plan §5."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml


@dataclass
class Campaign:
    id: str
    research_question: str
    target_repo: str
    target_ref: str

    @classmethod
    def from_yaml(cls, path: Path) -> Campaign:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            id=data["id"],
            research_question=data["research_question"],
            target_repo=data["target_repo"],
            target_ref=data["target_ref"],
        )


@dataclass
class Budget:
    max_tokens: int
    max_iterations: int
    max_wall_seconds: int | None = None


@dataclass
class Experiment:
    id: str
    campaign: Campaign
    variants: list[str]
    budget: Budget

    @classmethod
    def from_yaml(cls, path: Path) -> Experiment:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)
        campaign_path = (path.parent / data["campaign"]).resolve()
        if not campaign_path.exists():
            campaign_path = (path.parent.parent / data["campaign"]).resolve()
        campaign = Campaign.from_yaml(campaign_path)
        b = data["budget"]
        budget = Budget(
            max_tokens=int(b["max_tokens"]),
            max_iterations=int(b["max_iterations"]),
            max_wall_seconds=int(b["max_wall_seconds"]) if b.get("max_wall_seconds") is not None else None,
        )
        return cls(
            id=data["id"],
            campaign=campaign,
            variants=list(data["variants"]),
            budget=budget,
        )


@dataclass
class VariantResult:
    variant: str
    campaign_id: str
    tokens_in: int
    tokens_out: int
    dollars: float
    wall_seconds: float
    final_answer: str
    artifacts_dir: Path
    raw_log_path: Path
    crashed: bool = False
    hit_cap: bool = False
    error: str | None = None


class Variant(Protocol):
    name: str

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult: ...
