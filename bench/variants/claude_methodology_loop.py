"""claude_methodology_loop variant — N sequential methodology sessions with
full-prior-output carry-forward.

The L2 baseline. Tests whether multiple iterations with unstructured memory
(full text of prior iterations pasted into each next prompt) plus the
methodology guidance produces better outcomes than a single methodology
session (L1).

This is intentionally weaker than nous's structured carry-forward:
- No schema validation
- No regime / mechanism / applicability_bounds / confidence fields
- No takeaway extraction or structured principle store
- Just paste prior iterations' full output as-is into the next iter's prompt

That absence is exactly what we measure: how much of nous's value comes
from structured cross-iteration memory vs. how much can be matched by
plain text accumulation, given the same methodology guidance and same iter
budget.
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

# L2 uses a SEPARATE methodology file from L1. The L2 form has the same
# four scientific bullets, but the last bullet ("Track what you learn.")
# carries an extra clause: "Build on prior findings rather than starting
# from scratch each time." That sentence is meaningful only across
# iterations, so it lives in the loop variant's methodology, not L1's.
METHODOLOGY_LOOP_PATH = (
    Path(__file__).parent.parent / "methodology" / "methodology_loop.md"
)


def _build_iter_1_prompt(
    research_question: str, methodology: str, total_iters: int
) -> str:
    """L2 iter-1 user prompt. Same as L1's prompt structure but with iter
    framing replacing the generic 'report your findings' closing."""
    return (
        f"{research_question}\n\n"
        f"{methodology.rstrip()}\n\n"
        f"This is iteration 1 of {total_iters}. Report your findings and what "
        f"you would investigate next."
    )


def _build_iter_n_prompt(
    research_question: str,
    methodology: str,
    current_iter: int,
    total_iters: int,
    prior_outputs: list[str],
) -> str:
    """L2 iter-K (K>1) user prompt. Includes all prior iterations' full
    output as-is, unstructured."""
    prior_block = "\n\n".join(
        f"### Iteration {i + 1}\n\n{out}".strip()
        for i, out in enumerate(prior_outputs)
    )
    return (
        f"{research_question}\n\n"
        f"{methodology.rstrip()}\n\n"
        f"This is iteration {current_iter} of {total_iters}. Here is what you "
        f"found in prior iterations:\n\n"
        f"--- Prior findings ---\n"
        f"{prior_block}\n"
        f"---\n\n"
        f"Continue your investigation. Build on what you found before. "
        f"Report your findings and what you would investigate next."
    )


class ClaudeMethodologyLoopVariant:
    name = "claude_methodology_loop"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        log_path = workspace / ".bench-claude-methodology-loop.log"

        if not METHODOLOGY_LOOP_PATH.exists():
            log_path.write_text(
                f"methodology_loop.md not found at {METHODOLOGY_LOOP_PATH}"
            )
            crashed_run = ClaudeRunResult(
                final_answer="",
                tokens_in=0,
                tokens_out=0,
                dollars=0.0,
                wall_seconds=0.0,
                crashed=True,
                error=f"methodology_loop.md not found at {METHODOLOGY_LOOP_PATH}",
                log_path=log_path,
            )
            return variant_result_from(
                [crashed_run],
                variant_name=self.name,
                campaign_id=campaign.id,
                workspace=workspace,
                budget=budget,
            )

        methodology = METHODOLOGY_LOOP_PATH.read_text()
        total_iters = budget.max_iterations

        runs: list[ClaudeRunResult] = []
        prior_outputs: list[str] = []

        for n in range(1, total_iters + 1):
            if n == 1:
                question = _build_iter_1_prompt(
                    campaign.research_question, methodology, total_iters
                )
            else:
                question = _build_iter_n_prompt(
                    campaign.research_question,
                    methodology,
                    current_iter=n,
                    total_iters=total_iters,
                    prior_outputs=prior_outputs,
                )

            inv = ClaudeInvocation(
                question=question,
                workspace=workspace,
                budget=budget,
                log_path=workspace / f".bench-claude-methodology-loop-iter-{n}.log",
            )
            result = invoke_claude(inv)
            runs.append(result)

            if result.crashed:
                break

            prior_outputs.append(result.final_answer)

        return variant_result_from(
            runs,
            variant_name=self.name,
            campaign_id=campaign.id,
            workspace=workspace,
            budget=budget,
        )
