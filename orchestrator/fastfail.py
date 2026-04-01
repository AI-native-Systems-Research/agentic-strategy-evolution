"""Fast-fail rules for the Nous orchestrator.

Pure functions: take findings, return action. No side effects.

Rules (in priority order):
1. H-main refuted -> skip remaining arms, go to EXTRACTION
2. H-control-negative fails -> mechanism confounded, return to DESIGN
3. Single dominant component (>80% of total effect) -> SIMPLIFY
4. Otherwise -> CONTINUE normally
"""
from enum import Enum


class FastFailAction(Enum):
    CONTINUE = "continue"
    SKIP_TO_EXTRACTION = "skip_to_extraction"
    REDESIGN = "redesign"
    SIMPLIFY = "simplify"


def check_fast_fail(findings: dict) -> FastFailAction:
    arms = {a["arm_type"]: a for a in findings["arms"]}

    # Rule 1: H-main refuted -> skip to extraction (highest priority)
    if arms.get("h-main", {}).get("status") == "REFUTED":
        return FastFailAction.SKIP_TO_EXTRACTION

    # Rule 2: H-control-negative fails -> redesign
    if arms.get("h-control-negative", {}).get("status") == "REFUTED":
        return FastFailAction.REDESIGN

    # Rule 3: Single dominant component (>80%) -> simplify
    if findings.get("dominant_component_pct") is not None:
        if findings["dominant_component_pct"] > 80:
            return FastFailAction.SIMPLIFY

    return FastFailAction.CONTINUE
