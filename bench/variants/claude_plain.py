"""claude_plain variant — single headless Claude Code session, no methodology.

Thin wrapper over bench/variants/_claude_common.py since sub-issue #293's
refactor. The L0 baseline.
"""
from __future__ import annotations

from pathlib import Path

# Re-export DEFAULT_MODEL so existing imports (`from bench.variants.claude_plain
# import DEFAULT_MODEL`) keep working.
from bench.variants._claude_common import (  # noqa: F401
    DEFAULT_MODEL,
    ClaudeInvocation,
    invoke_claude,
    variant_result_from,
)
from bench.variants.base import Budget, Campaign, VariantResult


class ClaudePlainVariant:
    name = "claude_plain"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        inv = ClaudeInvocation(
            question=campaign.research_question,
            workspace=workspace,
            budget=budget,
            log_path=workspace / ".bench-claude-plain.log",
        )
        result = invoke_claude(inv)
        return variant_result_from(
            [result],
            variant_name=self.name,
            campaign_id=campaign.id,
            workspace=workspace,
            budget=budget,
        )
