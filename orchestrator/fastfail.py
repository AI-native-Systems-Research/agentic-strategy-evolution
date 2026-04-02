"""Fast-fail rules for the Nous orchestrator.

Pure functions: take findings, return recommended action for the orchestrator.
The caller is responsible for acting on the returned FastFailAction.

Rules (in priority order):
1. H-main refuted -> caller should skip remaining arms, go to EXTRACTION
2. H-control-negative fails -> caller should return to DESIGN (mechanism confounded)
3. Single dominant component (>80% of total effect) -> caller should SIMPLIFY
4. Otherwise -> CONTINUE normally

Callers must validate findings against findings.schema.json before calling.
"""
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class FastFailAction(Enum):
    CONTINUE = "continue"
    SKIP_TO_EXTRACTION = "skip_to_extraction"
    REDESIGN = "redesign"
    SIMPLIFY = "simplify"


def check_fast_fail(findings: dict) -> FastFailAction:
    if "arms" not in findings:
        raise ValueError("findings dict missing required 'arms' key")

    arms = {}
    for a in findings["arms"]:
        arm_type = a.get("arm_type")
        if arm_type is None:
            raise ValueError(f"arm entry missing required 'arm_type' key: {a}")
        if arm_type in arms:
            raise ValueError(
                f"Duplicate arm_type '{arm_type}' in findings. "
                f"Each arm type must appear exactly once."
            )
        arms[arm_type] = a

    # Validate h-main arm exists — fast-fail cannot work without it
    if "h-main" not in arms:
        raise ValueError(
            "findings missing required 'h-main' arm. "
            "Cannot evaluate fast-fail rules without h-main results. "
            f"Arms present: {list(arms.keys())}"
        )

    h_main_status = arms["h-main"].get("status")
    if h_main_status is None:
        raise ValueError("h-main arm missing required 'status' field")

    # Rule 1: H-main refuted -> skip to extraction (highest priority)
    if h_main_status == "REFUTED":
        logger.info("Fast-fail: h-main REFUTED -> SKIP_TO_EXTRACTION")
        return FastFailAction.SKIP_TO_EXTRACTION

    # Rule 2: H-control-negative fails -> redesign
    h_control = arms.get("h-control-negative")
    if h_control is None:
        logger.warning(
            "No h-control-negative arm in findings; "
            "confound detection fast-fail rule cannot be evaluated"
        )
    elif h_control.get("status") == "REFUTED":
        logger.info("Fast-fail: h-control-negative REFUTED -> REDESIGN")
        return FastFailAction.REDESIGN

    # Rule 3: Single dominant component (>80%) -> simplify
    pct = findings.get("dominant_component_pct")
    if pct is not None:
        if not isinstance(pct, (int, float)):
            raise TypeError(
                f"dominant_component_pct must be numeric, "
                f"got {type(pct).__name__}: {pct!r}"
            )
        if pct > 80:
            logger.info("Fast-fail: dominant_component_pct=%.1f%% -> SIMPLIFY", pct)
            return FastFailAction.SIMPLIFY

    logger.info("Fast-fail: no rules triggered -> CONTINUE")
    return FastFailAction.CONTINUE
