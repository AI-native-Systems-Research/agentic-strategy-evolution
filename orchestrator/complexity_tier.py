"""Graded-complexity tier discipline (issue #159).

A bundle declares a ``complexity_tier`` (1..4) at the top level. The
discipline is:

  Tier 1: single mechanism, single knob, treatment vs control.
  Tier 2: single mechanism, multi-knob OR ablation OR dose-response on one knob.
  Tier 3: multi-mechanism interactions, super-additivity, dose-response across knobs.
  Tier 4: cross-system / cross-workload generalization, robustness across regimes.

  Iteration N may use any tier <= N. So iter 1 is forced to tier 1;
  iter 2 may use tier 1 or 2; etc.

This module is pure Python — zero LLM tokens. It surfaces tier and
flags suspicious jumps (>1 across iterations) at the design gate so a
human can probe whether the simpler tier was actually skipped for a
defensible reason. We do **not** hard-reject tier overruns; the
discipline is enforced through visibility, not refusal — so an
agent that has good cause to escalate (e.g. iter 1's hypothesis was
already refuted) is not blocked.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

TIER_NAMES: dict[int, str] = {
    1: "single mechanism, single knob, treatment vs control",
    2: "single mechanism + multi-knob OR ablation OR dose-response on one knob",
    3: "multi-mechanism interactions, super-additivity, dose-response across knobs",
    4: "cross-system / cross-workload generalization, robustness across regimes",
}


def _read_bundle_tier(path: Path) -> int | None:
    """Read complexity_tier from a bundle.yaml. None if missing or malformed.

    Looks under ``metadata`` first, then falls back to the legacy top-level
    location (#206). When both are populated, the metadata value wins so
    ``metadata`` is the canonical place to put it going forward.
    """
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        tier = metadata.get("complexity_tier")
        if isinstance(tier, int) and 1 <= tier <= 4:
            return tier
    tier = data.get("complexity_tier")
    if isinstance(tier, int) and 1 <= tier <= 4:
        return tier
    return None


def _read_bundle_justification(bundle: object) -> str | None:
    """Pull tier_justification from metadata, falling back to root (#206)."""
    if not isinstance(bundle, dict):
        return None
    metadata = bundle.get("metadata")
    if isinstance(metadata, dict):
        j = metadata.get("tier_justification")
        if isinstance(j, str) and j.strip():
            return j
    j = bundle.get("tier_justification")
    if isinstance(j, str) and j.strip():
        return j
    return None


def prior_iteration_tiers(work_dir: Path, *, up_to: int) -> dict[int, int]:
    """Return {iteration: tier} for completed prior iterations.

    Looks at ``<work_dir>/runs/iter-N/bundle.yaml`` for N < ``up_to``.
    Iterations whose bundle lacks ``complexity_tier`` are omitted.
    """
    out: dict[int, int] = {}
    runs_dir = Path(work_dir) / "runs"
    if not runs_dir.is_dir():
        return out
    for entry in runs_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("iter-"):
            continue
        try:
            n = int(entry.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        if n >= up_to:
            continue
        tier = _read_bundle_tier(entry / "bundle.yaml")
        if tier is not None:
            out[n] = tier
    return out


def detect_jump(
    *,
    iteration: int,
    current_tier: int | None,
    prior_tiers: dict[int, int],
) -> str | None:
    """Return a human-readable warning string if tier escalates abruptly.

    Conditions:
      * iter 1 + current_tier > 1 → "iter 1 should start at tier 1"
      * current_tier > max(prior_tiers) + 1 → "skipped tier(s)"

    Returns None when no jump is detected, or when current_tier is
    missing (we don't pressure callers to declare it for legacy bundles).
    """
    if current_tier is None:
        return None
    if iteration <= 1 and current_tier > 1:
        return (
            f"Iteration 1 declared tier {current_tier} — the methodology "
            f"asks iter 1 to start at tier 1 ('{TIER_NAMES[1]}'). "
            f"Confirm this leap is justified by external evidence."
        )
    if not prior_tiers:
        return None
    prior_max = max(prior_tiers.values())
    if current_tier > prior_max + 1:
        skipped = list(range(prior_max + 1, current_tier))
        return (
            f"Tier jumped from {prior_max} (prior max) to {current_tier} — "
            f"skipped tier(s) {skipped}. Confirm earlier tier(s) were "
            f"refuted before escalating."
        )
    return None


def format_tier_summary(
    *,
    iteration: int,
    bundle_path: Path,
    work_dir: Path | None = None,
) -> str:
    """Render the tier panel that gates.py prints before the design gate.

    Always returns a non-empty string for a bundle that declares a
    tier. For a bundle without ``complexity_tier``, returns an empty
    string so the gate display is unaffected (additive).
    """
    tier = _read_bundle_tier(bundle_path)
    if tier is None:
        return ""

    lines = [
        "─" * 60,
        f"  COMPLEXITY TIER (issue #159)",
        "─" * 60,
        f"  Iteration {iteration} declared tier {tier}: {TIER_NAMES.get(tier, '(unknown)')}",
    ]

    # Show justification if present.
    try:
        bundle = yaml.safe_load(Path(bundle_path).read_text())
        justification = _read_bundle_justification(bundle)
    except (OSError, yaml.YAMLError):
        justification = None
    if justification:
        lines.append(f"  Justification: {justification}")

    if work_dir is not None:
        priors = prior_iteration_tiers(work_dir, up_to=iteration)
        if priors:
            prior_str = ", ".join(f"iter-{n}=tier{t}" for n, t in sorted(priors.items()))
            lines.append(f"  Prior tiers: {prior_str}")
        warning = detect_jump(
            iteration=iteration, current_tier=tier, prior_tiers=priors,
        )
        if warning:
            lines.append("")
            lines.append(f"  ⚠ TIER ESCALATION FLAGGED: {warning}")

    lines.append("─" * 60)
    return "\n".join(lines)


def collect_tier_warnings(
    iteration: int,
    bundle_path: Path,
    work_dir: Path,
) -> list[str]:
    """Pure-data version of format_tier_summary for tests / programmatic use."""
    tier = _read_bundle_tier(bundle_path)
    priors = prior_iteration_tiers(work_dir, up_to=iteration)
    warning = detect_jump(
        iteration=iteration, current_tier=tier, prior_tiers=priors,
    )
    return [warning] if warning else []
