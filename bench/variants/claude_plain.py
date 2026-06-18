"""claude_plain variant — single headless Claude Code session, no methodology.

The L0 baseline. The user prompt is the campaign's research question +
"Investigate this and report your findings." — what an ad-hoc engineer
would paste into Claude in a single session.
"""
from __future__ import annotations

from pathlib import Path

# Re-export DEFAULT_MODEL so existing imports keep working.
from bench.variants._claude_common import (  # noqa: F401
    DEFAULT_MODEL,
    ClaudeInvocation,
    invoke_claude,
    variant_result_from,
)
from bench.variants.base import Budget, Campaign, VariantResult


def _build_l0_prompt(research_question: str) -> str:
    """L0 user prompt: research question + a generic 'investigate' instruction."""
    return f"{research_question}\n\nInvestigate this and report your findings."


class ClaudePlainVariant:
    name = "claude_plain"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        inv = ClaudeInvocation(
            question=_build_l0_prompt(campaign.research_question),
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
