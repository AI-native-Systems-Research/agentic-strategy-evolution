"""Fast-fail rules for the Nous orchestrator.

Pure functions: take findings, return recommended action for the orchestrator.
The caller is responsible for acting on the returned FastFailAction.

Rules (in priority order):
1. H-main refuted -> caller should skip remaining arms, proceed to findings gate
2. H-control-negative fails AND h-main also not confirmed -> REDESIGN
   (If h-main is confirmed but control-negative refuted, the mechanism works
   but is broader than hypothesized — that's a learning, not a confound.)
3. Single dominant component (>80% of total effect) -> caller should SIMPLIFY
4. Otherwise -> CONTINUE normally

Callers must validate findings against findings.schema.json before calling.
"""
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class FastFailAction(Enum):
    CONTINUE = "continue"
    SKIP_TO_MERGE = "skip_to_merge"
    REDESIGN = "redesign"
    SIMPLIFY = "simplify"


def check_fast_fail(findings: dict) -> FastFailAction:
    if "arms" not in findings:
        raise ValueError("findings dict missing required 'arms' key")

    # Index arms by type.  h-main and h-control-negative must be unique
    # (fast-fail rules key on them).  Other types (h-robustness, h-ablation)
    # can appear multiple times; we keep only the first for indexing purposes
    # since fast-fail rules don't inspect them individually.
    _UNIQUE_ARMS = {"h-main", "h-control-negative"}
    arms = {}
    for a in findings["arms"]:
        arm_type = a.get("arm_type")
        if arm_type is None:
            raise ValueError(f"arm entry missing required 'arm_type' key: {a}")
        if arm_type in arms and arm_type in _UNIQUE_ARMS:
            raise ValueError(
                f"Duplicate arm_type '{arm_type}' in findings. "
                f"h-main and h-control-negative must appear exactly once."
            )
        if arm_type not in arms:
            arms[arm_type] = a

    # Validate h-main arm exists — fast-fail cannot work without it
    if "h-main" not in arms:
        raise ValueError(
            "findings missing required 'h-main' arm. "
            "Cannot evaluate fast-fail rules without h-main results. "
            f"Arms present: {list(arms.keys())}"
        )

    _KNOWN_STATUSES = {"CONFIRMED", "REFUTED", "PARTIALLY_CONFIRMED"}

    h_main_status = arms["h-main"].get("status")
    if h_main_status is None:
        raise ValueError("h-main arm missing required 'status' field")
    if h_main_status not in _KNOWN_STATUSES:
        logger.warning(
            "Unrecognized h-main status %r — no fast-fail rules will match. "
            "Known statuses: %s", h_main_status, sorted(_KNOWN_STATUSES)
        )

    # Rule 1: H-main refuted -> skip to principle merge (highest priority)
    if h_main_status == "REFUTED":
        logger.info("Fast-fail: h-main REFUTED -> skip to principle merge, proceed to findings gate")
        return FastFailAction.SKIP_TO_MERGE

    # Rule 2: H-control-negative fails -> redesign ONLY if h-main is not confirmed.
    # If h-main is confirmed but control-negative refuted, the mechanism is real
    # but broader than hypothesized (a discovery, not a confound).
    h_control = arms.get("h-control-negative")
    if h_control is None:
        logger.warning(
            "No h-control-negative arm in findings; "
            "confound detection fast-fail rule cannot be evaluated"
        )
    elif h_control.get("status") == "REFUTED":
        if h_main_status != "CONFIRMED":
            logger.info("Fast-fail: h-control-negative REFUTED (h-main not confirmed) -> REDESIGN")
            return FastFailAction.REDESIGN
        logger.info(
            "Fast-fail: h-control-negative REFUTED but h-main CONFIRMED "
            "-> mechanism broader than hypothesized, CONTINUE"
        )

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
