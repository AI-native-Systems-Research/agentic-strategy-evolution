"""claude_loop variant — N sequential plain Claude sessions with answer
carry-forward between sessions.

Tests "iteration alone": does running the agent more times help, or does
it drift / contradict itself without methodology + structural enforcement?
By keeping the loop and stripping methodology, principle accumulation, and
git isolation, this variant isolates the value of nous's *non-iteration*
contributions.
"""
from __future__ import annotations

from pathlib import Path

from bench.variants._claude_common import (
    ClaudeInvocation,
    invoke_claude,
    variant_result_from,
)
from bench.variants.base import Budget, Campaign, VariantResult


class ClaudeLoopVariant:
    name = "claude_loop"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        runs = []
        question = campaign.research_question

        for n in range(1, budget.max_iterations + 1):
            inv = ClaudeInvocation(
                question=question,
                workspace=workspace,
                budget=budget,
                log_path=workspace / f".bench-claude-loop-iter-{n}.log",
            )
            result = invoke_claude(inv)
            runs.append(result)

            if result.crashed:
                break

            # Prepend the previous answer to the next iter's question.
            # No summarization — let the agent see the full prior reply,
            # because anything else is another LLM call's worth of overhead.
            question = (
                f"Previous session's answer:\n\n{result.final_answer}\n\n"
                f"---\n\n"
                f"{campaign.research_question}\n\n"
                f"Continue refining or extend the analysis."
            )

        return variant_result_from(
            runs,
            variant_name=self.name,
            campaign_id=campaign.id,
            workspace=workspace,
            budget=budget,
        )
