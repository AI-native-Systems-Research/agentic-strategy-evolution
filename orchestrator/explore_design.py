"""Explore-then-synthesize DESIGN phase (issue #132).

DESIGN today asks one Opus session to do two things at once:

  1. Read the codebase to map metrics, knobs, prior findings, principles.
  2. Synthesize a hypothesis bundle from what it found.

That's the canonical Claude-Code-pattern miss: broad exploration + small
synthesis is exactly what parallel Explore subagents are for. Phase A
of #132 ships the orchestration layer that makes the split possible
without changing what gets produced (problem.md + bundle.yaml).

Stage A — parallel Explore: ``run_explore_stage(campaign, scopes,
runner)`` fans out one read-only subagent per scope and collects their
reports.

Stage B — Opus synthesis: ``build_synthesis_prompt(reports, campaign,
iteration)`` produces the prompt body for the single Opus call that
turns the explorer reports + principles.json into problem.md +
bundle.yaml.

Phase A is the orchestration helpers + their behavioral tests. The
dispatcher integration (SDKDispatcher spawning Explore subagents,
threading reports back into a synthesis call) lands in Phase B once
#121 merges and the team picks injection points.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# Default exploration scopes — one Explore subagent per scope. The
# scopes are deliberately overlapping a little so synthesis has
# redundant signal where it matters.
DEFAULT_EXPLORE_SCOPES: tuple[str, ...] = (
    "metrics",        # observable metrics + how they're collected
    "knobs",          # controllable knobs + their value ranges
    "prior_findings", # findings.json from previous iterations
    "principles",     # principles.json across the campaign + others
)


@dataclass
class ExploreReport:
    scope: str
    text: str
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def as_dict(self) -> dict:
        return {
            "scope": self.scope,
            "text": self.text,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass
class ExploreStageResult:
    reports: list[ExploreReport] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.reports)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.reports)

    def by_scope(self, scope: str) -> ExploreReport | None:
        for r in self.reports:
            if r.scope == scope:
                return r
        return None


def build_explore_prompt(scope: str, campaign: dict) -> str:
    """Construct a read-only Explore subagent prompt for one scope.

    The subagent should be spawned with ``subagent_type="Explore"`` so
    it cannot mutate the worktree. The prompt is short and scope-tight
    on purpose; the synthesis call (Stage B) is where multi-aspect
    integration happens.
    """
    target = campaign.get("target_system", {})
    name = target.get("name", "the target system")
    repo = target.get("repo_path", "(repo not configured)")

    if scope == "metrics":
        focus = (
            "Map the observable metrics this system exposes and how they "
            "are collected. Include the file/function where each metric is "
            "computed."
        )
    elif scope == "knobs":
        focus = (
            "Map the controllable knobs / configuration parameters this "
            "system exposes. For each knob, note its declared range and the "
            "code path that consumes it."
        )
    elif scope == "prior_findings":
        focus = (
            "Read prior runs/iter-*/findings.json files in the campaign "
            "directory. Summarize confirmed/refuted hypotheses and any open "
            "questions surfaced by the most recent iteration."
        )
    elif scope == "principles":
        focus = (
            "Read principles.json in this campaign and any sibling campaigns "
            "(via the campaign_index module if available). Flag principles "
            "that touch the same mechanism we're about to design for."
        )
    else:
        focus = f"Investigate the '{scope}' aspect of the target system."

    return (
        f"# Explore: {scope}\n\n"
        f"You are a read-only Explore subagent. **Do not modify any files.**\n"
        f"Target: {name} (repo at {repo})\n\n"
        f"## Focus\n{focus}\n\n"
        f"## Output\n"
        f"Return a markdown report of <= 500 lines. Cite file paths and "
        f"line numbers. End with a one-paragraph summary the synthesizer "
        f"can read in isolation.\n"
    )


ExploreRunner = Callable[[str, str, dict], ExploreReport]
"""Callable signature for running one Explore subagent.

Takes (scope, prompt, campaign) and returns an ExploreReport. The
default real-world implementation spawns subagent_type="Explore" via
the SDK and reads the assistant's final text. Tests inject a deterministic
fake.
"""


def run_explore_stage(
    campaign: dict,
    *,
    scopes: Iterable[str] = DEFAULT_EXPLORE_SCOPES,
    runner: ExploreRunner,
) -> ExploreStageResult:
    """Run one Explore subagent per scope and collect their reports.

    Phase A executes synchronously over the runner. Real parallel
    fan-out (anyio gather over the SDK's async API) lands in Phase B
    when the SDK runner ships its async surface.
    """
    reports: list[ExploreReport] = []
    for scope in scopes:
        prompt = build_explore_prompt(scope, campaign)
        report = runner(scope, prompt, campaign)
        reports.append(report)
    return ExploreStageResult(reports=reports)


def make_sdk_explore_runner(
    *,
    sdk_runner: Callable,
    cwd: Path | None = None,
    model: str = "claude-haiku-4-5",
    max_turns: int = 8,
) -> ExploreRunner:
    """Build an ExploreRunner backed by an SDK subagent (#132 Phase B).

    Each scope spawns a read-only subagent (``subagent_type="Explore"``)
    so the orchestrator gets parallel mapping without a giant Opus
    session doing both walking and synthesis. Per the no-live-LLM
    project principle (CLAUDE.md), this factory takes an injected
    ``sdk_runner`` — production wiring constructs the real Anthropic
    SDK runner; tests inject a recording fake.

    Defaults model to Haiku because read-only mapping is cheap and
    benefits from speed over depth; deep synthesis happens in Stage B
    (the single Opus call), not in Stage A.
    """
    def _run(scope: str, prompt: str, campaign: dict) -> ExploreReport:
        try:
            result = sdk_runner(
                prompt=prompt,
                model=model,
                cwd=cwd,
                max_turns=max_turns,
                system_prompt=None,
                settings_path=None,
                event_log_path=None,
                subagent_type="Explore",
            )
        except TypeError:
            # Older runners without subagent_type — fall back to the
            # base signature so the factory stays compatible across
            # SDK API evolution.
            result = sdk_runner(
                prompt=prompt, model=model, cwd=cwd, max_turns=max_turns,
            )

        return ExploreReport(
            scope=scope,
            text=getattr(result, "text", "") or "",
            duration_ms=int(getattr(result, "duration_ms", 0) or 0),
            input_tokens=int(getattr(result, "input_tokens", 0) or 0),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
        )

    return _run


def build_synthesis_prompt(
    stage_a: ExploreStageResult,
    *,
    campaign: dict,
    iteration: int,
    iter_dir: Path,
) -> str:
    """Build the Opus synthesis prompt that turns Explore reports into
    problem.md + bundle.yaml.

    The synthesizer never reads the codebase directly — it consumes only
    the explorer reports + principles.json. That's the whole point of
    the split: Opus on integration, not on file walks.
    """
    target = campaign.get("target_system", {})
    rq = campaign.get("research_question", "(not set)")

    sections = [
        f"# Synthesize iteration {iteration}",
        "",
        "Four read-only Explore subagents have already mapped the system.",
        "**Do not re-read the codebase.** Synthesize from the reports below.",
        "",
        f"## Research question\n{rq}",
        "",
        f"## Target\n{target.get('name', '?')} — {target.get('description', '')}",
        "",
        "## Explorer reports",
    ]
    for report in stage_a.reports:
        sections.append("")
        sections.append(f"### {report.scope}\n")
        sections.append(report.text)

    sections.extend([
        "",
        "## Required outputs",
        f"- {iter_dir}/problem.md (markdown)",
        f"- {iter_dir}/bundle.yaml (YAML, must validate against bundle.schema.yaml)",
        "",
        "Cite explorer reports by their `### <scope>` heading when justifying "
        "design choices. The reports are the source of truth for this "
        "iteration's design.",
    ])
    return "\n".join(sections)
