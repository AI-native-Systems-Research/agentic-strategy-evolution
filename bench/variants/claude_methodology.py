"""claude_methodology variant — single Claude session with methodology.md as
system prompt.

The L1 baseline. Tests whether nous's methodology delivered as a prompt
produces the same outcomes as nous's methodology delivered through
orchestration. If this scores close to ``nous``, the orchestrator is "just
prompt engineering"; if it underperforms — especially on artifact validity —
nous's structural guarantees (schema enforcement, deterministic phases, etc.)
are doing real work.
"""
from __future__ import annotations

from pathlib import Path

from bench.variants._claude_common import (
    ClaudeInvocation,
    ClaudeRunResult,
    invoke_claude,
    variant_result_from,
)
from bench.variants.base import Budget, Campaign, VariantResult

METHODOLOGY_PATH = Path(__file__).parent.parent / "methodology" / "methodology.md"


class ClaudeMethodologyVariant:
    name = "claude_methodology"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        log_path = workspace / ".bench-claude-methodology.log"

        if not METHODOLOGY_PATH.exists():
            log_path.write_text(
                f"methodology.md not found at {METHODOLOGY_PATH}"
            )
            crashed_run = ClaudeRunResult(
                final_answer="",
                tokens_in=0,
                tokens_out=0,
                dollars=0.0,
                wall_seconds=0.0,
                crashed=True,
                error=f"methodology.md not found at {METHODOLOGY_PATH}",
                log_path=log_path,
            )
            return variant_result_from(
                [crashed_run],
                variant_name=self.name,
                campaign_id=campaign.id,
                workspace=workspace,
                budget=budget,
            )

        methodology = METHODOLOGY_PATH.read_text()
        inv = ClaudeInvocation(
            question=campaign.research_question,
            workspace=workspace,
            budget=budget,
            log_path=log_path,
            system_prompt=methodology,
        )
        result = invoke_claude(inv)
        return variant_result_from(
            [result],
            variant_name=self.name,
            campaign_id=campaign.id,
            workspace=workspace,
            budget=budget,
        )
