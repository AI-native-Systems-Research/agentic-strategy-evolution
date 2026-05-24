"""`/goal`-driven campaign mode (issue #124).

Two modes Nous can run in:

  Mode A — fully /goal-driven: spawn one ``claude`` session for the
    whole campaign with a /goal directive that says "iteration N has
    a valid findings.json and a principle_updates.json file, OR stop
    after the campaign timeout." The Haiku evaluator that fires after
    every turn decides when the goal is met. No Python state machine
    in the inner loop.

  Mode B — /goal-bounded inner loop: keep the engine.py state machine
    for control flow but use /goal *within* EXECUTE_ANALYZE so the
    executor terminates as soon as validation passes. Cheaper than
    Python-driven retry loops.

Phase A ships the prompt builders for both modes (deterministic Python).
Wire-up into the dispatcher and the run_campaign code path lands in
Phase B once the team picks which mode is the default.

Why deterministic prompt builders ship first: criterion #2 of the issue
("hybrid mode is the default for nous run after one release of soak")
implies the team will run both modes side by side on real campaigns
and compare. Behavioral testing of the prompt assembly — does it
include the campaign brief, does it spell out the goal predicate
exactly — is what makes those soak runs comparable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


_DEFAULT_GOAL_DRIVEN_TIMEOUT_HOURS = 24


def build_full_goal_directive(
    campaign: dict,
    *,
    iteration: int,
    timeout_hours: int = _DEFAULT_GOAL_DRIVEN_TIMEOUT_HOURS,
) -> str:
    """Build the /goal text for Mode A (whole-campaign goal).

    The text is what gets sent as ``/goal "<...>"`` to a Claude Code
    session. Predicate: iteration N has a valid findings.json AND a
    principle_updates.json file, OR the elapsed time exceeds
    timeout_hours.
    """
    return (
        f"iteration {iteration} has produced runs/iter-{iteration}/findings.json "
        f"with a non-empty arms list AND runs/iter-{iteration}/principle_updates.json "
        f"with a list (possibly empty), OR more than {timeout_hours} hours have elapsed "
        f"since this session started"
    )


def build_inner_loop_goal_directive(
    iteration: int,
    *,
    extra_predicates: list[str] | None = None,
) -> str:
    """Build the /goal text for Mode B (EXECUTE_ANALYZE-bounded goal).

    Predicate: validate execution passes AND principle_updates.json
    exists. The deterministic Stop hook (#129) also enforces this; the
    /goal evaluator is the probabilistic backup that catches edge cases
    the schema check doesn't.
    """
    parts = [
        f"runs/iter-{iteration}/findings.json validates against findings.schema.json",
        f"runs/iter-{iteration}/principle_updates.json exists and parses as a list",
    ]
    if extra_predicates:
        parts.extend(extra_predicates)
    return " AND ".join(parts)


def build_goal_driven_session_prompt(
    campaign: dict,
    *,
    iteration: int,
    timeout_hours: int = _DEFAULT_GOAL_DRIVEN_TIMEOUT_HOURS,
    work_dir: Path | None = None,
) -> str:
    """Build the full prompt body for a Mode A session.

    The prompt asks the agent to drive iteration N of the Nous loop
    end-to-end inside the session, printing artifact paths so the Haiku
    /goal evaluator can see them.
    """
    target = campaign.get("target_system", {})
    rq = campaign.get("research_question", "(not set)")

    sections = [
        "# Goal-driven Nous campaign",
        "",
        "You are running iteration {iter} of a Nous hypothesis-driven experiment.",
        "Drive the full DESIGN → EXECUTE_ANALYZE → DONE flow inside this session.",
        "",
        "## Campaign brief",
        f"- Research question: {rq}",
        f"- Target system: {target.get('name', '?')}",
        f"- Description: {target.get('description', '(no description)')}",
    ]
    metrics = target.get("observable_metrics")
    if metrics:
        sections.append(f"- Observable metrics: {', '.join(metrics)}")
    knobs = target.get("controllable_knobs")
    if knobs:
        sections.append(f"- Controllable knobs: {', '.join(knobs)}")

    sections.extend([
        "",
        "## Required artifacts (iteration {iter})",
        f"- runs/iter-{iteration}/problem.md",
        f"- runs/iter-{iteration}/bundle.yaml",
        f"- runs/iter-{iteration}/experiment_plan.yaml",
        f"- runs/iter-{iteration}/findings.json",
        f"- runs/iter-{iteration}/principle_updates.json",
        "",
        "**Print every artifact path to stdout when you write it.** The /goal "
        "evaluator only sees what's been surfaced in the conversation; "
        "silent file writes won't trip the goal predicate.",
        "",
        "Run `nous validate execution --dir runs/iter-{iter}/` before claiming done.",
        "",
        "## Goal predicate",
        f"/goal {build_full_goal_directive(campaign, iteration=iteration, timeout_hours=timeout_hours)!r}",
    ])

    text = "\n".join(sections)
    return text.replace("{iter}", str(iteration))


# ─── Phase B: dispatcher wire-up ────────────────────────────────────────────


def run_goal_driven_iteration(
    *,
    dispatcher,
    campaign: dict,
    iteration: int,
    work_dir: Path,
    timeout_hours: int = _DEFAULT_GOAL_DRIVEN_TIMEOUT_HOURS,
) -> Path:
    """Mode A — drive iteration N entirely inside a single SDK session.

    Bypasses the engine.py phase machine. The agent receives the
    goal-driven prompt (with its embedded ``/goal`` directive) and
    drives DESIGN → EXECUTE_ANALYZE → DONE itself. The orchestrator
    persists the conversation transcript as ``design_log.md``; the
    artifacts (problem.md, bundle.yaml, findings.json, etc.) are
    written by the agent's own tool calls inside the session.

    Args:
      dispatcher: any object exposing ``_call_claude(prompt) -> str``.
        ``SDKDispatcher`` is the canonical caller; tests inject a fake.
      campaign: parsed campaign config.
      iteration: iteration number to drive.
      work_dir: campaign work-dir.
      timeout_hours: bound on the goal predicate's OR clause.

    Returns:
      Path to the conversation log on disk.
    """
    iter_dir = Path(work_dir) / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    prompt = build_goal_driven_session_prompt(
        campaign, iteration=iteration, timeout_hours=timeout_hours,
    )
    transcript = dispatcher._call_claude(prompt)
    log_path = iter_dir / "design_log.md"
    log_path.write_text(transcript)
    return log_path
