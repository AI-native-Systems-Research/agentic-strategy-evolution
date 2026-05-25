"""Deterministic classifiers for findings.json arm verdicts (issues #157, #158).

These are pure-Python rules that turn raw observed data into a categorical
verdict. They are the deterministic floor under the executor agent's
narrative ``observed`` / ``status`` fields — when the agent emits
structured numeric data alongside, the classifier checks whether the
agent's verdict is consistent with the data.

  * H-dose-response: shape (monotone, u-shape, saturating, flat).
  * H-tradeoff:      verdict (confirmed / primary_failed / cost_too_high / both_failed).

No LLM is consulted — the rules operate on numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# ─── Dose-response shape classification (#157) ────────────────────────────


VALID_SHAPES = (
    "monotone_decreasing",
    "monotone_increasing",
    "u_shaped",
    "inverted_u",
    "saturating",
    "flat",
)


def _signed_diff_signs(metrics: Sequence[float]) -> list[int]:
    """Sign of consecutive differences. +1, -1, or 0 (within tolerance)."""
    signs: list[int] = []
    for a, b in zip(metrics, metrics[1:]):
        d = b - a
        # Tolerance: 1% of mean magnitude (or absolute 1e-9 floor) — protects
        # against floating-point noise reading as a real direction.
        tolerance = max(abs((a + b) / 2) * 0.01, 1e-9)
        if d > tolerance:
            signs.append(1)
        elif d < -tolerance:
            signs.append(-1)
        else:
            signs.append(0)
    return signs


def classify_dose_shape(
    metrics: Sequence[float], *,
    saturation_ratio: float = 0.20,
    flat_threshold: float = 0.05,
) -> str:
    """Return the observed shape from a sequence of metric values.

    The shape is classified from the sequence's signed differences:

      * All non-decreasing (with at least one +1): monotone_increasing
        — UNLESS the late differences shrink to <saturation_ratio of
        the early differences, in which case ``saturating``.
      * All non-increasing (with at least one -1): monotone_decreasing.
      * Sign flips from - to +: u_shaped.
      * Sign flips from + to -: inverted_u.
      * Total relative range < flat_threshold: flat.
      * None of the above: noisy.

    Args:
      metrics: ordered metric values, one per increasing knob value.
      saturation_ratio: threshold below which late slope counts as flat.
      flat_threshold: max relative spread for the whole series to be "flat".

    The returned string is always a valid value of the
    findings.schema.json ``observed_shape`` enum (or ``"noisy"``).
    """
    if not metrics or len(metrics) < 3:
        return "noisy"

    spread = max(metrics) - min(metrics)
    mean = sum(metrics) / len(metrics)
    if mean and abs(spread / mean) < flat_threshold:
        return "flat"

    signs = _signed_diff_signs(metrics)

    # Pure monotonicity (allowing zeros).
    if all(s >= 0 for s in signs) and any(s > 0 for s in signs):
        # Saturating: late slope much smaller than early slope.
        diffs = [b - a for a, b in zip(metrics, metrics[1:])]
        if len(diffs) >= 2 and abs(diffs[0]) > 0:
            late_avg = sum(abs(d) for d in diffs[len(diffs) // 2:]) / (len(diffs) - len(diffs) // 2)
            early = abs(diffs[0])
            if early > 0 and late_avg / early < saturation_ratio:
                return "saturating"
        return "monotone_increasing"

    if all(s <= 0 for s in signs) and any(s < 0 for s in signs):
        diffs = [b - a for a, b in zip(metrics, metrics[1:])]
        if len(diffs) >= 2 and abs(diffs[0]) > 0:
            late_avg = sum(abs(d) for d in diffs[len(diffs) // 2:]) / (len(diffs) - len(diffs) // 2)
            early = abs(diffs[0])
            if early > 0 and late_avg / early < saturation_ratio:
                return "saturating"
        return "monotone_decreasing"

    # Look for a single sign flip — indicates a turning point.
    nonzero = [s for s in signs if s != 0]
    if len(nonzero) >= 2:
        flips = sum(1 for a, b in zip(nonzero, nonzero[1:]) if a != b)
        if flips == 1:
            if nonzero[0] < 0 and nonzero[-1] > 0:
                return "u_shaped"
            if nonzero[0] > 0 and nonzero[-1] < 0:
                return "inverted_u"

    return "noisy"


def shape_matches(expected: str | None, observed: str | None) -> bool:
    """True iff the expected and observed shapes are compatible.

    Some shapes have looser equivalents — saturating is an acceptable
    realisation of monotone, since saturation is monotone with declining
    slope. ``noisy`` never matches.
    """
    if not expected or not observed or observed == "noisy":
        return False
    if expected == observed:
        return True
    if expected == "monotone_decreasing" and observed == "saturating":
        return True
    if expected == "monotone_increasing" and observed == "saturating":
        return True
    return False


# ─── Tradeoff verdict classification (#158) ───────────────────────────────


@dataclass
class TradeoffVerdict:
    """Outcome of an H-tradeoff arm given measured deltas and budgets."""

    primary_predicate_met: bool
    secondary_predicate_met: bool
    verdict: str   # "confirmed" | "primary_failed" | "cost_too_high" | "both_failed"


def classify_tradeoff(
    *,
    primary_change_observed: float,
    primary_change_predicted: float,
    secondary_change_observed: float,
    secondary_budget: float,
    secondary_direction: str,
) -> TradeoffVerdict:
    """Apply the predicate truth table to determine the verdict.

    Primary predicate: the observed primary change is consistent with
    the prediction direction and meets its magnitude (>= predicted if
    predicted is positive, <= predicted if predicted is negative).

    Secondary predicate: the observed secondary change is within budget
    in the named "worse" direction. ``secondary_direction`` is "increase"
    (worse means going up) or "decrease" (worse means going down). The
    budget is positive; secondary changes in the *better* direction
    always pass.
    """
    if primary_change_predicted == 0:
        primary_ok = abs(primary_change_observed) >= 0
    elif primary_change_predicted > 0:
        primary_ok = primary_change_observed >= primary_change_predicted
    else:
        primary_ok = primary_change_observed <= primary_change_predicted

    if secondary_direction not in {"increase", "decrease"}:
        raise ValueError(f"invalid secondary_direction: {secondary_direction!r}")
    if secondary_budget < 0:
        raise ValueError(f"secondary_budget must be >= 0, got {secondary_budget}")

    if secondary_direction == "increase":
        # Worse is up — observation must be at most +budget.
        secondary_ok = secondary_change_observed <= secondary_budget
    else:
        # Worse is down — observation must be at least -budget.
        secondary_ok = secondary_change_observed >= -secondary_budget

    if primary_ok and secondary_ok:
        verdict = "confirmed"
    elif not primary_ok and secondary_ok:
        verdict = "primary_failed"
    elif primary_ok and not secondary_ok:
        verdict = "cost_too_high"
    else:
        verdict = "both_failed"

    return TradeoffVerdict(
        primary_predicate_met=primary_ok,
        secondary_predicate_met=secondary_ok,
        verdict=verdict,
    )
