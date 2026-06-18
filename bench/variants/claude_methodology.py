"""claude_methodology variant — single Claude session with scientific
methodology guidance inlined in the user prompt.

The L1 baseline. Tests whether telling the agent to be scientific (form
hypotheses, run controlled experiments, etc.) — delivered as part of the
single user message, the way an engineer would paste it — produces
better outcomes than no guidance at all (L0).

Methodology guidance lives in `bench/methodology/methodology.md` and is
read at run time. We inline it in the user prompt rather than passing it
as `--append-system-prompt`: the methodology references the research
question contextually, and the agent reads it the same way an engineer
would receive it (one message, problem + how-to-think-about-it).
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


def _build_l1_prompt(research_question: str, methodology: str) -> str:
    """L1 user prompt: research question + methodology bullets + closing
    'report your findings' instruction."""
    return (
        f"{research_question}\n\n"
        f"{methodology.rstrip()}\n\n"
        f"Report your findings with the evidence that supports them."
    )


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
            question=_build_l1_prompt(campaign.research_question, methodology),
            workspace=workspace,
            budget=budget,
            log_path=log_path,
        )
        result = invoke_claude(inv)
        return variant_result_from(
            [result],
            variant_name=self.name,
            campaign_id=campaign.id,
            workspace=workspace,
            budget=budget,
        )
