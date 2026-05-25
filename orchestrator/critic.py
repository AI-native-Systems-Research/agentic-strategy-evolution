"""Critic phase — \"can this experiment fail?\" check (issue #87).

Adds a structured falsifiability check between DESIGN and
HUMAN_DESIGN_GATE that catches the four-tautology-campaigns failure
mode from #84. Composes with:
  * #85 (ground_truth.shares_computation_with_detector)
  * #86 (empirical_content / derivation_type on principles)
  * #88 (theory_references on campaign.yaml)

Default critic: pure deterministic Python that flags the obvious
red flags — author self-declared tautology, missing ground truth,
identical measurement types. No LLM, no randomness, no live calls.

Injection seam ``critic_fn=`` reserves the path for an LLM-based
critic (future Phase B): the prompt for that lives in
``prompts/methodology/critique.md``. Today's tests inject deterministic
stubs through the same seam.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class CriticVerdict:
    """Outcome of running the critic on a bundle.

    Attributes:
        can_fail: True iff the critic believes the experiment can
            falsify the hypothesis. False ⇒ tautological by
            construction; the campaign should not proceed without
            human override.
        issues: List of human-readable concerns. Each is concrete
            (cites a specific bundle field). Empty when the bundle
            passes cleanly.
        reasoning: One-paragraph plain-English summary for the human
            gate. Always non-empty so gate_summary has something to
            render.
    """
    can_fail: bool
    issues: list[str] = field(default_factory=list)
    reasoning: str = ""


CriticFn = Callable[[dict], CriticVerdict]
"""Critic protocol: takes a bundle dict, returns a CriticVerdict."""


def _default_critic(bundle: dict) -> CriticVerdict:
    """Deterministic falsifiability check.

    Hard fail (can_fail=False) when the author self-declares
    ``ground_truth.shares_computation_with_detector=true``. All other
    concerns are advisory issues that don't block — the human gate
    decides what to do with them.
    """
    issues: list[str] = []
    can_fail = True

    gt = bundle.get("ground_truth") if isinstance(bundle, dict) else None
    if isinstance(gt, dict):
        if gt.get("shares_computation_with_detector") is True:
            can_fail = False
            issues.append(
                "ground_truth.shares_computation_with_detector=true: the "
                "experiment is tautological by construction (the ground "
                "truth uses the same computation as the detector under "
                "test). Cannot fail. See issue #84."
            )
        else:
            mt = gt.get("measurement_type")
            dmt = gt.get("detector_measurement_type")
            if mt and dmt and mt == dmt:
                issues.append(
                    f"ground_truth.measurement_type ({mt!r}) equals "
                    f"detector_measurement_type ({dmt!r}); they may "
                    f"secretly measure the same physical signal. "
                    f"Re-check independence_argument."
                )
            if not gt.get("independence_argument"):
                issues.append(
                    "ground_truth.independence_argument is missing — "
                    "provide a plain-English justification that the "
                    "ground truth can disagree with the detector."
                )
    else:
        # No ground_truth block. Advisory only — schema doesn't yet
        # require it (would break legacy bundles).
        issues.append(
            "no ground_truth block declared — for quantitative-detector "
            "tests, document how 'correct' is defined via the ground_truth "
            "field on the bundle (issue #85). Without it, the experiment "
            "is at risk of being tautological. See issue #84 case studies."
        )

    if can_fail:
        reasoning = (
            "Bundle passes the deterministic falsifiability checks. "
            f"Issues surfaced for the human gate: {len(issues)}."
        )
    else:
        reasoning = (
            "Bundle FAILS the falsifiability check by author's own "
            "declaration. Redesign with an independent ground truth "
            "before proceeding."
        )
    return CriticVerdict(can_fail=can_fail, issues=issues, reasoning=reasoning)


def run_critic(
    bundle: dict,
    *,
    critic_fn: CriticFn | None = None,
) -> CriticVerdict:
    """Run the critic on a bundle.

    Args:
        bundle: Parsed bundle.yaml dict.
        critic_fn: Optional injected critic. When None, uses the
            module's deterministic Python default. The seam reserves
            the path for an LLM-based critic later — tests inject
            deterministic stubs and never touch the LLM path.

    Returns:
        CriticVerdict.
    """
    return (critic_fn or _default_critic)(bundle)
