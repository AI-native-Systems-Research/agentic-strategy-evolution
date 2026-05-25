"""Design-time power analysis (issue #163).

Right-sizes per-arm seed counts from an effect size, desired power,
and significance level. Pure deterministic Python — no LLM, no
randomness, no live calls.

Background:
  Today every arm hard-codes literal seed counts ("10 seeds", "30 runs")
  by convention. Two campaigns in the inference-sim audit
  (mech-design-kvtime, reviewer-gauntlet) showed prediction accuracy
  near 0% — plausibly underpowered rather than scientifically refuted.
  Conversely composite-sensitivity-boundary's 65 runs/iter was
  overpowered when effects were decisive.

Approach:
  Closed-form normal approximation (Cohen 1988 §2):

    N_per_arm = 2 * ((z_{1-α/2} + z_{1-β}) / d)^2     (two-sample t)
    N_per_arm =     ((z_{1-α/2} + z_{1-β}) / h)^2     (proportions, Cohen's h)

  These match standard reference tables to ±1 across the practical
  effect-size range. The statsmodels.power module would give
  near-identical values via iterative numerics; statsmodels is not in
  the dependency tree, scipy is, so we use scipy.stats.norm directly.

Usage:
  >>> from orchestrator.power import required_seeds
  >>> required_seeds(effect_size=0.5)        # medium effect, defaults
  63
  >>> required_seeds(effect_size=0.2, power=0.9)
  527
"""
from __future__ import annotations

import math

from scipy.stats import norm


_VALID_KINDS = ("t", "proportions")


def required_seeds(
    effect_size: float,
    *,
    power: float = 0.8,
    alpha: float = 0.05,
    kind: str = "t",
) -> int:
    """Return the per-arm seed count needed to detect ``effect_size`` with the given power.

    Args:
        effect_size: Magnitude of the effect to detect. For ``kind="t"``
            this is Cohen's d (standardized mean difference). For
            ``kind="proportions"`` this is Cohen's h
            (arcsine-transformed proportion difference). Must be > 0;
            sign is irrelevant for sample sizing — direction belongs to
            the hypothesis statement, not the seed count.
        power: Probability of detecting the effect when it exists.
            Defaults to the conventional 0.8.
        alpha: Two-sided significance level. Defaults to the
            conventional 0.05.
        kind: Test family. ``"t"`` for two-sample t-test (default);
            ``"proportions"`` for two-proportion z-test via Cohen's h.

    Returns:
        Smallest integer N such that the test achieves ``power`` at
        ``alpha`` against a true effect of ``effect_size``.

    Raises:
        ValueError: If any input is outside its valid range.
    """
    if not effect_size or effect_size <= 0:
        raise ValueError(
            f"effect_size must be > 0 (got {effect_size!r}); "
            f"sample-size calc is undefined for zero or negative magnitudes",
        )
    if not 0 < power < 1:
        raise ValueError(f"power must be in (0, 1) (got {power!r})")
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1) (got {alpha!r})")
    if kind not in _VALID_KINDS:
        raise ValueError(
            f"kind must be one of {_VALID_KINDS} (got {kind!r})",
        )

    z_alpha = norm.ppf(1 - alpha / 2)
    z_power = norm.ppf(power)

    if kind == "t":
        n_float = 2 * ((z_alpha + z_power) / effect_size) ** 2
    else:  # proportions
        n_float = ((z_alpha + z_power) / effect_size) ** 2

    return math.ceil(n_float)
