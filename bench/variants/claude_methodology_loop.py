"""claude_methodology_loop variant — N sequential methodology sessions with
text-based takeaway carry-forward.

Tests "memory + methodology without structural enforcement" — the L2 layer
in the L0/L1/L2/L3 ablation. The agent runs N sessions; between sessions, a
permissive regex extracts a "takeaways" section the methodology system
prompt encourages the agent to write. Those bullets are prepended to the
next session's user prompt.

This is intentionally weaker than nous's structured principle store:
- No schema validation
- No regime / mechanism / applicability_bounds / confidence fields
- No status tracking (active / superseded / retired)
- No deterministic merge or conflict detection
- Free-form bullets — whatever shape the agent emits

When extraction returns nothing (agent didn't emit a recognisable takeaways
section), the variant falls back to passing the full previous-iter answer
forward — same mechanism as ``claude_loop``. So claude_methodology_loop ≥
claude_loop on memory richness, by construction.
"""
from __future__ import annotations

import re
from pathlib import Path

from bench.variants._claude_common import (
    ClaudeInvocation,
    ClaudeRunResult,
    invoke_claude,
    variant_result_from,
)
from bench.variants.base import Budget, Campaign, VariantResult
from bench.variants.claude_methodology import METHODOLOGY_PATH

# Header regex: matches a markdown header containing any of the soft-prompt
# words. Examples that match:
#   ## Key takeaways
#   ### Takeaways:
#   ## What I learned this iteration
#   ## Lessons Learned
#   ## Key Findings
#   ## Summary
#   ## Principles  (backward compat with the old strict-format methodology)
_TAKEAWAYS_HEADER = re.compile(
    r"^#{1,6}\s+\*{0,2}\s*"
    r"(?:key\s+)?(?:takeaway|takeaways|learned|"
    r"what\s+i\s+learned|lessons\s+learned|key\s+findings|"
    r"summary|principle|principles)"
    r"[\s:\w]*\*{0,2}\s*$",
    re.IGNORECASE,
)
_ANY_HEADER = re.compile(r"^#{1,6}\s+\S")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+)$")
# Strip a leading [P1] / [T1] / [1] style ID prefix from the start of a bullet.
_ID_PREFIX = re.compile(r"^\[[A-Z]?\-?\d+\]\s*", re.IGNORECASE)
_CODE_FENCE = re.compile(r"^\s*```")


def _strip_code_blocks(text: str) -> str:
    """Drop fenced code blocks so regex matches don't false-positive
    inside ```` ``` ```` samples."""
    out: list[str] = []
    in_block = False
    for line in text.split("\n"):
        if _CODE_FENCE.match(line):
            in_block = not in_block
            continue
        if not in_block:
            out.append(line)
    return "\n".join(out)


def _extract_takeaways(text: str) -> list[str]:
    """Pull free-form takeaway bullets from the agent's reply.

    Permissive on heading: matches any markdown header containing one of
    {key takeaways, takeaways, what I learned, lessons learned,
    key findings, summary, principles}.

    Each bullet becomes one takeaway string; sub-indented lines (and any
    non-bullet lines under a bullet) are concatenated onto the current
    takeaway. Stops at the next markdown header.

    Returns ``[]`` if no recognisable takeaways section. Caller should
    fall back to passing the full prior answer forward in that case.
    """
    text = _strip_code_blocks(text)
    lines = text.split("\n")

    # Find the takeaways section
    start_idx: int | None = None
    for i, line in enumerate(lines):
        if _TAKEAWAYS_HEADER.match(line.strip()):
            start_idx = i + 1
            break
    if start_idx is None:
        return []

    takeaways: list[str] = []
    current: str | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None and current.strip():
            takeaways.append(current.strip())
        current = None

    for line in lines[start_idx:]:
        stripped = line.strip()

        # Stop at next header (bounds the section)
        if _ANY_HEADER.match(stripped):
            break

        if not stripped:
            # Blank line — keep current open in case more sub-fields follow
            continue

        bullet_match = _BULLET.match(line)
        if bullet_match:
            indent = len(line) - len(line.lstrip())
            content = _ID_PREFIX.sub("", bullet_match.group(1)).strip()
            if indent == 0:
                # New top-level takeaway
                _flush()
                current = content
            else:
                # Sub-bullet — append to current takeaway
                if current is None:
                    current = content
                else:
                    current += " " + content
        elif current is not None:
            # Non-bullet text under the current takeaway
            current += " " + stripped

    _flush()
    return takeaways


# Back-compat alias for callers that still imported the old name.
# (Internal callers all migrated; kept until any external pinning is updated.)
_extract_principles = _extract_takeaways


def _build_next_question(
    research_question: str,
    accumulated_takeaways: list[str],
    previous_full_answer: str,
) -> str:
    """Build iter-N+1's user prompt.

    Priority order:
      1. If we extracted takeaways from previous iters, prepend those.
      2. Otherwise (extraction empty), prepend the full previous answer
         text — same fallback ``claude_loop`` uses.
      3. Always end with the original research question.
    """
    if accumulated_takeaways:
        bullets = "\n".join(f"- {t}" for t in accumulated_takeaways)
        return (
            f"Key takeaways from previous iterations:\n\n"
            f"{bullets}\n\n"
            f"---\n\n"
            f"{research_question}\n\n"
            f"Build on these takeaways in your investigation. At the end "
            f"of your reply, include a 'Key takeaways from this iteration' "
            f"section listing what you learned this round."
        )
    if previous_full_answer.strip():
        return (
            f"Previous attempt:\n\n"
            f"{previous_full_answer}\n\n"
            f"---\n\n"
            f"Continue refining your answer to: {research_question}\n\n"
            f"At the end of your reply, include a 'Key takeaways from "
            f"this iteration' section listing what you learned."
        )
    return (
        f"{research_question}\n\n"
        f"At the end of your reply, include a 'Key takeaways from this "
        f"iteration' section listing what you learned."
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

        runs: list[ClaudeRunResult] = []
        accumulated_takeaways: list[str] = []
        question = campaign.research_question

        for n in range(1, budget.max_iterations + 1):
            inv = ClaudeInvocation(
                question=question,
                workspace=workspace,
                budget=budget,
                log_path=workspace / f".bench-claude-methodology-loop-iter-{n}.log",
                system_prompt=methodology,
            )
            result = invoke_claude(inv)
            runs.append(result)

            if result.crashed:
                break

            new_takeaways = _extract_takeaways(result.final_answer)
            # Append (no dedup, no validation — that's the experimental signal)
            accumulated_takeaways.extend(new_takeaways)

            # Build next iter's user prompt. Falls back to full answer
            # carry-forward if no takeaways extracted from any iter so far.
            question = _build_next_question(
                research_question=campaign.research_question,
                accumulated_takeaways=accumulated_takeaways,
                previous_full_answer=result.final_answer,
            )

        return variant_result_from(
            runs,
            variant_name=self.name,
            campaign_id=campaign.id,
            workspace=workspace,
            budget=budget,
        )
