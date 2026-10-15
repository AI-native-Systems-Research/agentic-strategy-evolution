"""Methodology weight profiles (``campaign.design_profile``).

``standard`` (default) leaves every prompt and limit unchanged. ``lightweight`` trims the per-iteration
overhead that dominates spend on fast-feedback targets: a short, design-only DESIGN phase that builds on
the previous iteration's handoff, fewer and more focused arms, a small per-arm refine loop in EXECUTE,
an executor-written update for the next designer, and a wrap-up (not a restart) when a phase hits its
turn limit. The design model is not changed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

LIGHTWEIGHT = "lightweight"
# v4 = lightweight + scripted sweeps in EXECUTE, more refine cycles, and a measured gap analysis that the
# next design must target.
V4 = "v4"
# v5 = v4 + each iteration starts from the best solution so far (carry-forward), a capped EXECUTE phase so a
# small budget still gets several design->execute loops, incremental edits, sweeps only for tunable values,
# and re-measurement when the judge is noisy.
V5 = "v5"
# v6 = v5 without the EXECUTE turn cap: long uninterrupted executor sessions, still starting from the best.
V6 = "v6"
# v7 = v6 + competing mechanism arms (h-alternative) screened in fresh dollar-capped sessions, one long session
# for the winner, a local evaluator built in the first iteration, and a per-iteration dollar cap.
V7 = "v7"
# v8 = v7 + caps from the session transcripts, a judge profile learned from official measures (time limit,
# likely timeouts, local-evaluator trust), the screening winner continuing in its own session, exploit
# iterations while the best improves, a measured baseline, one repair pass per failed arm, hang recovery,
# and orchestrator-written artifacts after a cap stop.
V8 = "v8"
V7_FAMILY = (V7, V8)  # profiles that run the v7 multi-session EXECUTE machinery
CARRY_PROFILES = (V5, V6, V7, V8)
LIGHT_PROFILES = (LIGHTWEIGHT, V4, V5, V6, V7, V8)
V4_ARM_REFINE_CYCLES = 10
V5_EXECUTE_MAX_TURNS = 45
LIGHTWEIGHT_DESIGN_MAX_TURNS = 30
LIGHTWEIGHT_ARM_REFINE_CYCLES = 5
LIGHTWEIGHT_WRAP_UP_TURNS = 12
LIGHTWEIGHT_MAX_WRAP_UPS = 2
EXECUTOR_UPDATE_FILE = "handoff_update.md"

WRAP_UP_PROMPT = (
    "You reached this phase's turn limit. Stop exploring and do not run new experiments. Using only what "
    "you already know, write any required artifacts for this phase that are missing or incomplete now, run "
    "the phase's `nous validate` command, and fix only what the validator reports."
)

OUTPUT_LIMIT_PROMPT = (
    "Your last reply went over the output limit and was lost. Do not redo that reasoning in one reply. "
    "Write what you have now to this phase's files, then continue in short steps: a few paragraphs of "
    "reasoning, then write or run something, and repeat."
)


V4_DESIGN_EXTRA = (
    "- **Target the largest measured gap:** from the second iteration on, read the gap analysis in the "
    "executor update. `h-main` must attack the largest remaining loss it reports with a change that "
    "generalizes (never special-case specific inputs or test cases), and the hypothesis must state the mechanism by which the "
    "change recovers it and roughly how much it should recover. Name any tunable values (thresholds, weights, "
    "counts) and their plausible ranges so the executor can sweep them.\n"
)
V4_EXECUTE_EXTRA = (
    "- **Sweep tunable values with a script (deterministic measurements only):** when an arm has tunable "
    "values (thresholds, weights, counts, orderings), write one script that measures up to about 100 settings "
    "with the sanctioned measure command and keeps the best, instead of editing and measuring by hand. Stay "
    "within the arm's hypothesis and keep the solution general (never special-case specific inputs or test "
    "cases). A sweep counts as one refine cycle. Record the swept "
    "ranges and the best setting in the arm's `refine_cycles` history.\n"
    "- **Measured gap analysis:** in the update for the next designer, quantify where the remaining score is "
    "lost (for example, the score components or the inputs, cases, or code paths that cost the most), ranked "
    "from largest to smallest, with the measurement that shows it.\n"
)


V5_DESIGN_EXTRA = (
    "- **Build on the current best code:** the target already contains the best solution measured so far "
    "(carried forward from earlier iterations). Each arm is a change to that solution, not a rewrite from "
    "scratch.\n"
    "- **Target the largest measured gap:** from the second iteration on, `h-main` must attack the largest "
    "remaining loss in the executor update with a change that generalizes (never special-case specific inputs "
    "or test cases), and state the mechanism and roughly how much it should recover. Mark an arm as tunable "
    "only if it has real numeric knobs (thresholds, weights, counts), and give their plausible ranges.\n"
)
V5_EXECUTE_EXTRA = (
    "- **Start from the current best:** your worktree already contains the best solution so far. Measure it "
    "once as the baseline, then apply each arm as a change on top of it.\n"
    "- **Edit, don't rewrite:** change the solution with small targeted edits instead of rewriting the whole "
    "file; generate variants with a script when you need many.\n"
    "- **Sweep only tunable arms (deterministic measurements only):** when an arm has numeric knobs, one "
    "script may measure up to about 100 settings with the sanctioned measure command and keep the best; keep "
    "the solution general (never special-case specific inputs or test cases). For structural changes, think, "
    "make one well-reasoned change, and measure it. A sweep counts as one refine cycle.\n"
    "- **Noisy judge:** if the same solution can score differently between runs (time limits, randomness), "
    "re-measure your top candidates two or three times and keep the one with the best average.\n"
    "- **Measured gap analysis:** in the update for the next designer, quantify where the remaining score is "
    "lost, ranked from largest to smallest, with the measurement that shows it.\n"
    "- **Finish within your turn limit:** you have a limited number of turns; leave enough to write the "
    "required artifacts and validate.\n"
)


LIGHT_ARMS = (
    "- **Few, focused arms:** use 1-3 arms in total: `h-main` plus at most two more, each of a documented "
    "arm type and each type at most once, and only when the arm changes what you would do next. Skip "
    "`h-control-negative`, `h-ablation`, and robustness arms unless a finding genuinely needs causal "
    "attribution. For a pure optimization objective, prefer arms whose treatment is itself a plausible "
    "improvement over the current best rather than a deliberately weaker control. Describe each arm's "
    "intended change precisely enough that the executor can implement it without re-deriving it.\n"
)
V7_ARMS = (
    "- **Competing mechanisms:** write `h-main` plus one or two `h-alternative` arms, each from a genuinely "
    "different algorithm family (2-3 families in total), all measured against the same incumbent. Every "
    "mechanism arm sets `mechanism_family`; each `h-alternative` also sets `differs_from_main`, one line on "
    "why its family differs from `h-main`'s. If the problem allows only one sensible family, use `h-main` "
    "alone and say why in the bundle's top-level `single_family_reason`. Describe each arm in a few lines: "
    "the mechanism, why it should beat the incumbent, and its validity check.\n"
    "- **Validity check:** every mechanism arm sets `validity_check`: a cheap test on a tiny case showing the "
    "mechanism is correct (for example, the output is feasible), run before the executor builds on it.\n"
    "- **Arm roles:** `h-main` and `h-alternative` are the only arms with their own executor session: each is "
    "screened in a fresh session with a small budget, then the winner continues in one long session from "
    "its best version. `h-dose-response` is a scripted sweep on the winning arm. `h-control-negative` "
    "re-measures the unchanged incumbent (noise test); a noise claim may enter the handoff or a principle "
    "only if this re-measure supports it. `h-robustness` and `h-tradeoff` are not sessions: report them as "
    "evaluator columns (per size group, largest sizes, CPU time). `h-ablation` and `h-super-additivity` only "
    "after a multi-part win (tier 2 or higher).\n"
)
V7_DESIGN_EXTRA = (
    "- **Target per-instance gaps:** from the second iteration on, pick mechanisms that attack the largest "
    "loss per instance and size group in the executor's gap analysis (score lost, CPU time against the time "
    "limit, timeouts), not just the aggregate score.\n"
    "- **Iteration 1:** name 2-3 algorithm families in a few lines each with a validity check; do not "
    "derive, prove, or fully specify them; the executor works the details out by building and measuring.\n"
    "- **Short steps:** write `bundle.yaml` early. Keep each reasoning step short (a few paragraphs). If "
    "you need more, write code or notes to a file, run them, and continue from the result.\n"
)
V7_EXECUTE_EXTRA = (
    "- **Short steps:** keep a runnable version at all times and measure after each change. Keep each "
    "reasoning step short (a few paragraphs). If you need more, write code or notes to a file, run them, "
    "and continue from the result. If a tooling problem (compiler, environment) is not fixed after 2-3 "
    "tries, measure with the official measure command instead.\n"
    "- **Winner session:** the mechanism arms were screened in separate sessions (results below). Your "
    "worktree holds the winning arm's best version. Deepen it: sweeps of its tunable values, refinement, "
    "measurement. Regenerate the winner's patch as `patches/<winner key>.patch` from the version you keep.\n"
    "- **findings.json:** one entry for the winner (set `metadata.candidate_id` to its key and the "
    "objective's metric keys to the kept values) and one `h-control-negative` entry that re-measures the "
    "unchanged incumbent. Losing screened arms are added from their result files by the orchestrator.\n"
    "- **Gap analysis per instance and size group:** with the local evaluator, report where score is lost "
    "per size group (mean score, worst instances, CPU time against the time limit, timeouts), largest "
    "first, in the update for the next designer and as `gap_analysis` entries in findings.json. Call a "
    "difference noise only if the `h-control-negative` re-measure shows that spread.\n"
)

V7_DEFAULT_ARM_BUDGET_USD = 4.0
V7_DEFAULT_ITERATION_BUDGET_USD = 12.0
V7_DEFAULT_DESIGN_BUDGET_USD = 4.0
V7_DEFAULT_WINNER_MIN_USD = 2.0
EVALUATOR_DIR = "evaluator"


@dataclass(frozen=True)
class V7Settings:
    arm_budget_usd: float = V7_DEFAULT_ARM_BUDGET_USD
    iteration_budget_usd: float = V7_DEFAULT_ITERATION_BUDGET_USD
    design_budget_usd: float = V7_DEFAULT_DESIGN_BUDGET_USD
    winner_min_usd: float = V7_DEFAULT_WINNER_MIN_USD
    cost_rates: dict = field(default_factory=dict)


def is_v7(campaign: dict) -> bool:
    return profile_for(campaign) == V7


def is_v7_family(campaign: dict) -> bool:
    """True for v7 and v8, which share the screening machinery."""
    return profile_for(campaign) in V7_FAMILY


def is_v8(campaign: dict) -> bool:
    return profile_for(campaign) == V8


def _settings_block(campaign: dict) -> dict:
    """The profile's settings block: ``v8`` (falling back to ``v7``) for v8, else ``v7``."""
    if is_v8(campaign):
        return campaign.get("v8") or campaign.get("v7") or {}
    return campaign.get("v7") or {}


def v7_settings(campaign: dict) -> V7Settings:
    cfg = _settings_block(campaign)
    return V7Settings(
        arm_budget_usd=float(cfg.get("arm_budget_usd", V7_DEFAULT_ARM_BUDGET_USD)),
        iteration_budget_usd=float(cfg.get("iteration_budget_usd", V7_DEFAULT_ITERATION_BUDGET_USD)),
        design_budget_usd=float(cfg.get("design_budget_usd", V7_DEFAULT_DESIGN_BUDGET_USD)),
        winner_min_usd=float(cfg.get("winner_min_usd", V7_DEFAULT_WINNER_MIN_USD)),
        cost_rates=dict(cfg.get("cost_rates_per_mtok") or {}),
    )


V8_DEFAULT_WINNER_SHARE = 0.4
V8_DEFAULT_REPAIR_BUDGET_USD = 1.0
V8_DEFAULT_HANG_MINUTES = 15.0
V8_DEFAULT_ASSUMED_TIME_LIMIT_S = 1.0
V8_NOISE_UNKNOWN = 0.5  # improvement threshold when the judge's noise is unknown


@dataclass(frozen=True)
class V8Settings:
    winner_share: float = V8_DEFAULT_WINNER_SHARE
    repair_budget_usd: float = V8_DEFAULT_REPAIR_BUDGET_USD
    hang_minutes: float = V8_DEFAULT_HANG_MINUTES
    assumed_time_limit_s: float = V8_DEFAULT_ASSUMED_TIME_LIMIT_S
    official_log: str | None = None  # JSONL of official measures; default <work_dir>/official_measures.jsonl


def v8_settings(campaign: dict) -> V8Settings:
    cfg = campaign.get("v8") or {}
    return V8Settings(
        winner_share=float(cfg.get("winner_share", V8_DEFAULT_WINNER_SHARE)),
        repair_budget_usd=float(cfg.get("repair_budget_usd", V8_DEFAULT_REPAIR_BUDGET_USD)),
        hang_minutes=float(cfg.get("hang_minutes", V8_DEFAULT_HANG_MINUTES)),
        assumed_time_limit_s=float(cfg.get("assumed_time_limit_s", V8_DEFAULT_ASSUMED_TIME_LIMIT_S)),
        official_log=cfg.get("official_log") or None,
    )


def v7_design_context(campaign: dict, work_dir: Path, iteration: int | None = None) -> str:
    """v7 DESIGN note on the local evaluator: plan it while missing, otherwise point at its README.

    Once an instrument.json exists, its summary follows unless the campaign handoff already carries it.
    When this iteration's evaluator ran before the design (iteration 1), the baseline score follows too.
    """
    if not is_v7_family(campaign):
        return ""
    if is_v8(campaign):
        from orchestrator.v8_execute import v8_design_note
        extra = v8_design_note(campaign, work_dir, iteration)
    else:
        extra = ""
    return _v7_evaluator_note(campaign, work_dir, iteration) + extra


def _v7_evaluator_note(campaign: dict, work_dir: Path, iteration: int | None) -> str:
    ev = Path(work_dir).resolve() / EVALUATOR_DIR
    readme = ev / "README.md"
    if readme.is_file() and readme.read_text().strip():
        from orchestrator.instrument import HEADING, instrument_summary
        handoff = Path(work_dir) / "handoff.md"
        checks = "" if handoff.is_file() and HEADING in handoff.read_text() else instrument_summary(
            campaign, work_dir, iteration)
        from orchestrator.instrument import baseline_note
        base = baseline_note(work_dir, iteration)
        return (f"\n\n## Local evaluator (v7)\n\nIt lives in `{ev}`. Its README:\n\n"
                + readme.read_text().strip()[:3000] + "\n" + ("\n" + checks if checks else "")
                + ("\n" + base if base else ""))
    return (
        "\n\n## Local evaluator (v7)\n\n"
        f"None exists yet. Before the arms run, an executor session builds a local evaluator in `{ev}` from "
        "the problem statement: an instance generator that includes the largest allowed sizes, a "
        "per-instance score, and per-instance CPU time against the time limit, grouped by size. In "
        "`problem.md`, state what it must cover (sizes, time limit, scoring) so it can be built without "
        "re-deriving them.\n"
    )


def profile_for(campaign: dict) -> str:
    return campaign.get("design_profile") or "standard"


def is_light(campaign: dict) -> bool:
    return profile_for(campaign) in LIGHT_PROFILES


def refine_cycles(campaign: dict) -> int:
    return V4_ARM_REFINE_CYCLES if profile_for(campaign) in (V4,) + CARRY_PROFILES else LIGHTWEIGHT_ARM_REFINE_CYCLES


def carry_forward_enabled(campaign: dict) -> bool:
    return profile_for(campaign) in CARRY_PROFILES


def design_max_turns_override(campaign: dict) -> int | None:
    """DESIGN max_turns implied by the profile, or None to use the normal resolution."""
    return LIGHTWEIGHT_DESIGN_MAX_TURNS if is_light(campaign) else None


def resolve_max_turns(campaign: dict, phase_key: str, default_max_turns: dict) -> int:
    """Single resolver for per-phase max_turns: campaign.max_turns > design_profile > defaults > 25."""
    v = (campaign.get("max_turns") or {}).get(phase_key)
    if v is not None:
        return int(v)
    if phase_key == "design":
        v = design_max_turns_override(campaign)
        if v is not None:
            return v
    if phase_key == "execute_analyze" and profile_for(campaign) == V5:
        return V5_EXECUTE_MAX_TURNS
    v = (default_max_turns or {}).get(phase_key)
    if v is not None:
        return int(v)
    return 25


def max_wrap_ups(campaign: dict) -> int:
    """How many times a turn-limited SDK session is resumed with WRAP_UP_PROMPT (0 = restart as before)."""
    return LIGHTWEIGHT_MAX_WRAP_UPS if is_light(campaign) else 0


def wrap_up_max_turns(campaign: dict) -> int:
    return LIGHTWEIGHT_WRAP_UP_TURNS


BUDGET_WRAP_UP_USD = 1.0
# A resumed wrap-up re-reads the whole (cached) context on every turn; leave room for this many turns.
BUDGET_WRAP_UP_TURNS = 3


def budget_wrap_up_usd(cap: float | None, last_turn_usd: float = 0.0) -> float:
    """Cap for a wrap-up after a session reaches its dollar cap or turn limit.

    Floor: a quarter of the cap, between $0.25 and $1. With a large context one turn can cost more than
    that, so the wrap-up gets ``BUDGET_WRAP_UP_TURNS`` times the last turn's cost, at most the cap itself.
    """
    floor = min(BUDGET_WRAP_UP_USD, max(0.25, 0.25 * (cap or 0)))
    sized = min(BUDGET_WRAP_UP_TURNS * max(0.0, float(last_turn_usd or 0)), float(cap or 0))
    return round(max(floor, sized), 2)


def design_guidance(campaign: dict, max_turns: int, mode: str = "real") -> str:
    """Extra DESIGN guidance for the profile (none in rehearsal mode, which has its own scope rules).

    `max_turns` is the resolved DESIGN turn limit.
    """
    if not is_light(campaign) or mode == "rehearsal":
        return ""
    half = max(1, max_turns // 2)
    return (
        "\n\n## Lightweight profile (this campaign)\n\n"
        "This phase is design only: use the scientific method to decide the next hypothesis and arms from "
        "what is already known, and write it down. The executor implements, runs, and measures. These rules "
        "take precedence over the methodology's Phase 1 steps.\n\n"
        f"- **Turn limit:** you have at most {max_turns} turns. Count them. Write `problem.md`, `bundle.yaml`, "
        f"and `handoff_snapshot.md` by about turn {half}, run `nous validate design`, and use the remaining "
        "turns only to fix validator errors or sharpen the design.\n"
        "- **Build on what is known:** start from the previous handoff, the executor's update from the last "
        "iteration, and the active principles. They describe the system, the measurement command, the current "
        "best, and the open gaps. Do not re-read source files the handoff already summarizes.\n"
        "- **Explore only what the next hypothesis needs:** if it depends on a detail the handoff lacks, look "
        "up just that detail (grep, or read a specific line range), not whole files. In the first iteration, "
        "explore only enough to frame the problem and a first hypothesis.\n"
        "- **Do not implement or measure:** do not edit the target or solution files and do not run candidate "
        "solutions. In the first iteration you may run the baseline command once to confirm it works; later, "
        "cite the last measured score from the handoff or executor update as the baseline validation.\n"
        + (V7_ARMS if profile_for(campaign) in V7_FAMILY else LIGHT_ARMS)
        + "- **Seeds:** use a single seed when the measurement is deterministic.\n"
        + (V4_DESIGN_EXTRA if profile_for(campaign) == V4 else "")
        + (V5_DESIGN_EXTRA if profile_for(campaign) in CARRY_PROFILES else "")
        + (V7_DESIGN_EXTRA if profile_for(campaign) in V7_FAMILY else "")
        + "\n"
    )


def execute_guidance(campaign: dict, mode: str = "real") -> str:
    """Extra EXECUTE_ANALYZE guidance for the profile (none in rehearsal mode)."""
    if not is_light(campaign) or mode == "rehearsal":
        return ""
    return (
        "\n\n## Lightweight profile (this campaign)\n\n"
        "These rules take precedence over the methodology where they differ.\n\n"
        f"- **Per-arm refinement (deterministic measurements only):** after an arm's first measurement you "
        f"may improve that arm's implementation, staying within its hypothesis, for up to "
        f"{refine_cycles(campaign) - 1} more measure-edit cycles, keeping the best version. When done, "
        "regenerate the arm's patch and `experiment_plan.yaml` entry from the version you kept, so they "
        "reproduce the reported result. Report the kept score in `observed`; in the arm's `metadata`, set the "
        "objective's metric keys to the kept values and put the per-cycle history under a separate "
        "`refine_cycles` key (do not add other keys to the arm result).\n"
        + ("- If the measurement is noisy, do not refine: run the planned conditions as usual.\n"
           if profile_for(campaign) not in CARRY_PROFILES else
           "- If the measurement is noisy, refine only by re-measuring: keep the version with the best average "
           "over two or three measurements (see below).\n")
        + "- Do not spend measurements re-running unchanged conditions when the measurement is deterministic.\n"
        f"- **Update for the next designer:** before validating, write `{EXECUTOR_UPDATE_FILE}` in the "
        "iteration directory, next to `findings.json` (it is a protocol artifact in this profile; at most about 60 lines). Include: the best score this iteration and which arm and "
        "version produced it (point to its patch under `patches/`); what each arm changed and what the "
        "measurements showed; the concrete open gaps you observed (for example, specific code paths still "
        "not exercised, failing cases, or the largest remaining loss terms); and the most promising next "
        "step. The next designer starts from this file instead of re-exploring the system.\n"
        + (V4_EXECUTE_EXTRA if profile_for(campaign) == V4 else "")
        + (V5_EXECUTE_EXTRA if profile_for(campaign) in CARRY_PROFILES else "")
        + (V7_EXECUTE_EXTRA if profile_for(campaign) in V7_FAMILY else "")
        + "\n"
    )


def executor_update_for_design(campaign: dict, work_dir: Path, iteration: int) -> str:
    """Text appended to the DESIGN prompt's previous handoff: the last iteration's measured outcome.

    The campaign handoff is written during DESIGN, before anything is measured, so on its own it never
    reflects what the executor found. Empty for the standard profile and for the first iteration.
    """
    if not is_light(campaign) or iteration <= 1:
        return ""
    prev = Path(work_dir) / "runs" / f"iter-{iteration - 1}"
    parts: list[str] = []
    best = _best_found_line(Path(work_dir) / "best_found.json")
    if best:
        parts.append(best)
    update = prev / EXECUTOR_UPDATE_FILE
    findings = prev / "findings.json"
    if update.is_file() and update.read_text().strip():
        parts.append(update.read_text().strip())
    elif findings.is_file():
        parts.append("No executor update was written; previous `findings.json`:\n\n```json\n"
                     + findings.read_text().strip() + "\n```")
    if not parts:
        return ""
    return (f"\n\n## Executor update from iteration {iteration - 1} (measured results; newer than the "
            "handoff above)\n\n" + "\n\n".join(parts) + "\n")


def _best_found_line(path: Path) -> str:
    try:
        top = (json.loads(path.read_text()).get("top_k") or [])[0]
    except (OSError, ValueError, IndexError, AttributeError):
        return ""
    return (f"Best measured so far: score {top.get('score')} from `{top.get('candidate_id')}` "
            f"(iteration {top.get('iteration')}, arm `{top.get('arm_id')}`).")
