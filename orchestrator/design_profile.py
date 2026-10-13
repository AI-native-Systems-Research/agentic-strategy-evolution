"""Methodology weight profiles (``campaign.design_profile``).

``standard`` (default) leaves every prompt and limit unchanged. ``lightweight`` trims the per-iteration
overhead that dominates spend on fast-feedback targets: a shorter DESIGN phase, fewer and more focused
arms, and a small per-arm refine loop. The design model is not changed.
"""
from __future__ import annotations

LIGHTWEIGHT = "lightweight"
LIGHTWEIGHT_DESIGN_MAX_TURNS = 30
LIGHTWEIGHT_ARM_REFINE_CYCLES = 5


def profile_for(campaign: dict) -> str:
    return campaign.get("design_profile") or "standard"


def design_max_turns_override(campaign: dict) -> int | None:
    """DESIGN max_turns implied by the profile, or None to use the normal resolution."""
    return LIGHTWEIGHT_DESIGN_MAX_TURNS if profile_for(campaign) == LIGHTWEIGHT else None


def resolve_max_turns(campaign: dict, phase_key: str, default_max_turns: dict) -> int:
    """Single resolver for per-phase max_turns: campaign.max_turns > design_profile > defaults > 25."""
    v = (campaign.get("max_turns") or {}).get(phase_key)
    if v is not None:
        return int(v)
    if phase_key == "design":
        v = design_max_turns_override(campaign)
        if v is not None:
            return v
    v = (default_max_turns or {}).get(phase_key)
    if v is not None:
        return int(v)
    return 25


def design_guidance(campaign: dict, max_turns: int, mode: str = "real") -> str:
    """Extra DESIGN guidance for the profile (none in rehearsal mode, which has its own scope rules).

    `max_turns` is the resolved DESIGN turn limit.
    """
    if profile_for(campaign) != LIGHTWEIGHT or mode == "rehearsal":
        return ""
    return (
        "\n\n## Lightweight profile (this campaign)\n\n"
        f"- **Short design:** you have at most {max_turns} turns. Write `problem.md`, `bundle.yaml`, and "
        "`handoff_snapshot.md` early, run `nous validate design` well before the limit, then refine. Explore "
        "only what this iteration needs; reuse the previous handoff and findings instead of re-reading code "
        "you already summarized.\n"
        "- **Few, focused arms:** use 1-3 arms in total: `h-main` plus at most two more, each of a documented "
        "arm type and each type at most once, and only when the arm changes what you would do next. Skip "
        "`h-control-negative`, `h-ablation`, and robustness arms unless a finding genuinely needs causal "
        "attribution. For a pure optimization objective, prefer arms whose treatment is itself a plausible "
        "improvement over the current best rather than a deliberately weaker control.\n"
        "- **Seeds:** use a single seed when the measurement is deterministic.\n\n"
    )


def execute_guidance(campaign: dict, mode: str = "real") -> str:
    """Extra EXECUTE_ANALYZE guidance for the profile (none in rehearsal mode)."""
    if profile_for(campaign) != LIGHTWEIGHT or mode == "rehearsal":
        return ""
    return (
        "\n\n## Lightweight profile (this campaign)\n\n"
        f"- **Per-arm refinement (deterministic measurements only):** after an arm's first measurement you "
        f"may improve that arm's implementation, staying within its hypothesis, for up to "
        f"{LIGHTWEIGHT_ARM_REFINE_CYCLES - 1} more measure-edit cycles, keeping the best version. When done, "
        "regenerate the arm's patch and `experiment_plan.yaml` entry from the version you kept, so they "
        "reproduce the reported result. Report the kept score in `observed`; in the arm's `metadata`, set the "
        "objective's metric keys to the kept version's values and put the per-cycle history under a separate "
        "`refine_cycles` key (do not add other keys to the arm result).\n"
        "- If the measurement is noisy, do not refine: run the planned conditions as usual.\n"
        "- Do not spend measurements re-running unchanged conditions when the measurement is deterministic.\n\n"
    )
