"""claude_arm_structured_loop variant — L2 with full Nous methodology prompts
injected per iter, but no orchestrator machinery (no schema validation, no
ledger, no principles persistence, no worktree isolation).

This is the methodology-vs-machinery isolation cell. It tests:
  - Does forcing the hypothesis-bundle / arm structure (h-main / h-control /
    h-robust) into the prompt itself recover most of Nous's gain?

Difference from L2 (claude_methodology_loop):
  - L2 uses bench/methodology/methodology_loop.md (a thin 4-bullet preamble).
  - This variant uses the FULL prompts/methodology/{design,execute_analyze,report}.md
    files — same content the orchestrator would dispatch — with placeholder
    substitution performed mechanically (no orchestrator state to fill them).

Difference from full Nous:
  - No schema validation of bundles
  - No ledger.json / principles.json persistence between iters
  - No critique gate
  - No worktree isolation per arm
  - prior context = paste prior iters' final answers (same as L2)
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

NOUS_METHODOLOGY_DIR = (
    Path(__file__).parent.parent.parent / "prompts" / "methodology"
)
DESIGN_PATH = NOUS_METHODOLOGY_DIR / "design.md"
EXECUTE_ANALYZE_PATH = NOUS_METHODOLOGY_DIR / "execute_analyze.md"
REPORT_PATH = NOUS_METHODOLOGY_DIR / "report.md"


def _iter_mode(n: int) -> tuple[str, str]:
    """Return (iteration_mode, mode_guidance) for iter n.

    Nous picks iteration_mode dynamically via its mode picker (driven by
    graded-complexity-tier discipline, issue #159). That picker is part
    of the orchestrator machinery we're isolating against. To avoid
    smuggling its output in via the prompt, we substitute neutral '(none)'
    here. The LLM sees `This iteration's mode is: **(none)**` and
    proceeds without orchestrator-provided mode framing.
    """
    return ("(none)", "(none)")


def _substitute(template: str, subs: dict[str, str]) -> str:
    """Replace {{key}} placeholders. Unknown placeholders are kept verbatim
    (so if a methodology file references a placeholder we didn't anticipate,
    the LLM sees the literal token rather than mysteriously empty text)."""
    def repl(m: re.Match) -> str:
        key = m.group(1).strip()
        return subs.get(key, m.group(0))
    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", repl, template)


def _build_methodology_block(
    campaign: Campaign,
    workspace: Path,
    iter_num: int,
    total_iters: int,
    prior_outputs: list[str],
) -> str:
    """Build the full methodology block (design + execute + report prompts,
    placeholders substituted). Returned as a single string the iter prompt
    will prepend before the per-iter framing."""
    iter_dir_rel = f"runs/iter-{iter_num}"
    workspace.joinpath(iter_dir_rel, "inputs").mkdir(parents=True, exist_ok=True)
    workspace.joinpath(iter_dir_rel, "results").mkdir(parents=True, exist_ok=True)
    workspace.joinpath(iter_dir_rel, "patches").mkdir(parents=True, exist_ok=True)

    mode, mode_guidance = _iter_mode(iter_num)

    if iter_num == 1:
        previous_handoff = "(none — this is the first iteration)"
        previous_findings = "(none — this is the first iteration)"
    else:
        previous_handoff = "\n\n".join(
            f"### Iteration {i + 1} output\n\n{out}".strip()
            for i, out in enumerate(prior_outputs)
        )
        previous_findings = previous_handoff  # paste-forward: same content

    # All placeholder substitutions are NEUTRAL fills — equivalent to what
    # nous would inject if its orchestrator state was empty (no principles
    # persisted yet, no ledger, etc.). Crucially, we do NOT add any
    # instructions beyond what's already in nous's methodology .md files.
    # The whole point is to isolate "machinery" — adding prompt instructions
    # the methodology doesn't have would smuggle in extra guidance.
    subs = {
        "research_question": campaign.research_question,
        "iteration": str(iter_num),
        "iteration_mode": mode,
        "mode_guidance": mode_guidance,
        "iter_dir": iter_dir_rel,
        "nous_dir": str(workspace),
        "target_system": campaign.id,
        "system_description": "(none)",
        "observable_metrics": "(none)",
        "controllable_knobs": "(none)",
        "active_principles": "(none)",
        "previous_handoff": previous_handoff,
        "previous_findings": previous_findings,
        "execution_environment": "(none)",
        "max_turns": "60",
        # report.md placeholders
        "ledger_summary": "(none)",
        "final_principles": "(none)",
        "results_summary": "(none)",
        "retry_log_summary": "(none)",
        "bundle_amendments_summary": "(none)",
        "brief_amendments_summary": "(none)",
        # Optional / contextual placeholders elsewhere in the methodology.
        # Neutral fills only — no extra guidance.
        "problem_md": "(none)",
        "worktree_constraint": "(none)",
        "repo_context": "(none)",
        "condition_reset": "(none)",
        "design_handoff": "(none)",
        "human_feedback": "(none)",
        "bundle_yaml": "(none)",
    }

    design = _substitute(DESIGN_PATH.read_text(), subs)
    execute = _substitute(EXECUTE_ANALYZE_PATH.read_text(), subs)
    report = _substitute(REPORT_PATH.read_text(), subs)

    return (
        "## METHODOLOGY — DESIGN PHASE INSTRUCTIONS\n\n"
        f"{design.rstrip()}\n\n"
        "---\n\n"
        "## METHODOLOGY — EXECUTE & ANALYZE PHASE INSTRUCTIONS\n\n"
        f"{execute.rstrip()}\n\n"
        "---\n\n"
        "## METHODOLOGY — REPORT PHASE INSTRUCTIONS\n\n"
        f"{report.rstrip()}\n"
    )


def _build_iter_prompt(
    campaign: Campaign,
    workspace: Path,
    iter_num: int,
    total_iters: int,
    prior_outputs: list[str],
) -> str:
    methodology_block = _build_methodology_block(
        campaign=campaign,
        workspace=workspace,
        iter_num=iter_num,
        total_iters=total_iters,
        prior_outputs=prior_outputs,
    )

    if iter_num == 1:
        prior_section = ""
    else:
        prior_block = "\n\n".join(
            f"### Iteration {i + 1}\n\n{out}".strip()
            for i, out in enumerate(prior_outputs)
        )
        prior_section = (
            "## Prior iterations' output (paste-forward)\n\n"
            "--- BEGIN PRIOR ITERS ---\n"
            f"{prior_block}\n"
            "--- END PRIOR ITERS ---\n\n"
        )

    # Minimal framing: same shape as L2's `_build_iter_n_prompt`, just with
    # the methodology block prepended. We do NOT add extra instructions
    # ("MUST include Principles", "do not leave empty", etc.) — those would
    # be smuggling guidance beyond what nous's methodology actually contains.
    return (
        f"# Research question\n\n"
        f"{campaign.research_question.rstrip()}\n\n"
        f"---\n\n"
        f"{methodology_block}\n"
        f"---\n\n"
        f"{prior_section}"
        f"This is iteration {iter_num} of {total_iters}. Report your "
        f"findings and what you would investigate next."
    )


class ClaudeArmStructuredLoopVariant:
    name = "claude_arm_structured_loop"

    def run(
        self,
        campaign: Campaign,
        workspace: Path,
        budget: Budget,
    ) -> VariantResult:
        log_path = workspace / ".bench-claude-arm-structured-loop.log"

        for path in (DESIGN_PATH, EXECUTE_ANALYZE_PATH, REPORT_PATH):
            if not path.exists():
                log_path.write_text(f"required prompt missing: {path}")
                crashed_run = ClaudeRunResult(
                    final_answer="",
                    tokens_in=0,
                    tokens_out=0,
                    dollars=0.0,
                    wall_seconds=0.0,
                    crashed=True,
                    error=f"required prompt missing: {path}",
                    log_path=log_path,
                )
                return variant_result_from(
                    [crashed_run],
                    variant_name=self.name,
                    campaign_id=campaign.id,
                    workspace=workspace,
                    budget=budget,
                )

        total_iters = budget.max_iterations
        runs: list[ClaudeRunResult] = []
        prior_outputs: list[str] = []

        for n in range(1, total_iters + 1):
            question = _build_iter_prompt(
                campaign=campaign,
                workspace=workspace,
                iter_num=n,
                total_iters=total_iters,
                prior_outputs=prior_outputs,
            )
            inv = ClaudeInvocation(
                question=question,
                workspace=workspace,
                budget=budget,
                log_path=workspace / f".bench-claude-arm-structured-loop-iter-{n}.log",
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
