"""claude_methodology_loop variant — N sequential methodology sessions with
deterministic principle carry-forward.

Tests "memory + methodology without structural enforcement" — does
methodology + cumulative memory match nous-like outcomes if you strip
nous's deterministic principle merge, schema validation, and per-experiment
git isolation?

Between sessions, a deterministic Python step extracts principles from the
agent's reply via regex (the methodology system prompt instructs the agent
to emit them in a labeled section). Principles ACCUMULATE across iterations
— same shape as nous's principles.json — but with **no** dedup, validation,
schema check, or conflict detection. That absence is exactly what we
measure.
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

# Header regex: matches "## Principles", "### Principles:", "## **Principles**",
# "## PRINCIPLES", etc. Requires at least one '#'.
_PRINCIPLES_HEADER = re.compile(
    r"^#{1,6}\s+\*{0,2}\s*principles?\s*\*{0,2}\s*:?\s*\*{0,2}\s*$",
    re.IGNORECASE,
)
_ANY_HEADER = re.compile(r"^#{1,6}\s+\S")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+)$")
# Strip a leading [P1] / [P-1] style ID from the first line of a principle.
_PRINCIPLE_ID_PREFIX = re.compile(r"^\[P\-?\d+\]\s*", re.IGNORECASE)
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


def _extract_principles(text: str) -> list[str]:
    """Pull principles out of an agent reply. Each principle is one string
    that bundles the bullet's first line + any indented sub-fields the
    methodology asked the agent to include (Regime/Mechanism/etc.).

    Best-effort: returns ``[]`` if no recognisable principles section.
    Format expected (set by methodology.md):

        ## Principles

        - [P1] Statement
          Regime: ...
          Mechanism: ...

        - [P2] ...
    """
    text = _strip_code_blocks(text)
    lines = text.split("\n")

    # Find the principles section
    start_idx: int | None = None
    for i, line in enumerate(lines):
        if _PRINCIPLES_HEADER.match(line.strip()):
            start_idx = i + 1
            break
    if start_idx is None:
        return []

    principles: list[str] = []
    current: str | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None and current.strip():
            principles.append(current.strip())
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
            content = _PRINCIPLE_ID_PREFIX.sub("", bullet_match.group(1)).strip()
            if indent == 0:
                # New top-level principle
                _flush()
                current = content
            else:
                # Sub-bullet — append to current principle
                if current is None:
                    current = content
                else:
                    current += " " + content
        elif current is not None:
            # Non-bullet text under the current principle (e.g. "Regime: X")
            current += " " + stripped

    _flush()
    return principles


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
        accumulated_principles: list[str] = []
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

            new_principles = _extract_principles(result.final_answer)
            # Append (no dedup, no validation — that's the experimental signal)
            accumulated_principles.extend(new_principles)

            # Build next iter's question
            if accumulated_principles:
                principles_block = "\n".join(
                    f"- {p}" for p in accumulated_principles
                )
                question = (
                    f"Principles from previous sessions:\n\n"
                    f"{principles_block}\n\n"
                    f"---\n\n"
                    f"{campaign.research_question}\n\n"
                    f"Apply or extend these principles in your investigation. "
                    f"At the end of your reply, include a `## Principles` "
                    f"section with any new principles you derived (using the "
                    f"format from the system prompt)."
                )
            else:
                # Agent didn't emit recognisable principles last round; ask again
                question = (
                    f"{campaign.research_question}\n\n"
                    f"At the end of your reply, include a `## Principles` "
                    f"section with any principles you derived."
                )

        return variant_result_from(
            runs,
            variant_name=self.name,
            campaign_id=campaign.id,
            workspace=workspace,
            budget=budget,
        )
