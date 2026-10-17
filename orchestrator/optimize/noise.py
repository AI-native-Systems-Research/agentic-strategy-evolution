"""Noise and data-quality diagnostics for ``kind: optimization`` (#321 P3).

Pure arithmetic, no numpy, zero LLM tokens. Each function states its method,
its citation and the assumption it tests or relies on. Every check here is a
VETO: it can withhold a certificate and never grants one, so it spends no part
of the stated error budget (``Pr(certified and wrong)`` can only fall when a
certificate is removed). What a veto cannot do is restore the assumption it
tests; its value is measured, not proved, and the measurements are in the spec
(``docs/superpowers/specs/2026-10-17-certification-soundness.md`` §7) and the
guide's documented limits.
"""
from __future__ import annotations

import math
from statistics import mean, median

from scipy.stats import f as fisher_f

HETEROSCEDASTICITY_METHOD = "brown_forsythe_median_structural_zeros_removed"


def _abs_dev_from_median(g: list[float]) -> list[float]:
    """``|y - median|`` with the structural zeros removed.

    Odd ``n``: the median IS an observation, so one deviation is exactly zero
    whatever the data; it carries no information and drags the group's mean
    deviation down, which costs the test almost all its power at the group
    sizes confirm uses (n = 3). Hines & O'Hara Hines (2000, Biometrics 56,
    451-454) remove it. Even ``n``: the two central deviations are equal by
    construction (``(y_(m+1) - y_(m)) / 2`` each), so one is a structural
    duplicate and one of them is removed. Measured size and power of this
    variant are in the spec (§7); plain Brown-Forsythe at n = 3 rejected 0.0%
    of a 10x sd ratio in 4000 trials.
    """
    m = median(g)
    z = sorted(abs(y - m) for y in g)
    if len(g) >= 2:
        z = z[1:]
    return z


def brown_forsythe(groups) -> dict:
    """Brown & Forsythe (1974, JASA 69, 364-367): Levene's ANOVA on absolute
    deviations from each group's MEDIAN, with the structural zeros removed
    (``_abs_dev_from_median``). ``W ~ F(k - 1, N - k)`` approximately under
    equal variances, where ``N`` counts the deviations kept.

    Groups with fewer than two observations carry no spread and are skipped.
    Returns ``{"p", "w", "df", "groups", "reason"}``; ``p`` is ``None`` with a
    named ``reason`` when the test cannot be computed: fewer than two usable
    groups (``fewer_than_two_groups``), no within-group df
    (``no_within_group_df``), or zero within-group spread of the deviations
    (``zero_spread``).
    """
    use = [list(map(float, g)) for g in groups if len(g) >= 2]
    out = {"method": HETEROSCEDASTICITY_METHOD, "groups": len(use),
           "sizes": [len(g) for g in use], "p": None, "w": None, "df": None,
           "reason": None}
    if len(use) < 2:
        out["reason"] = "fewer_than_two_groups"
        return out
    zs = [_abs_dev_from_median(g) for g in use]
    k = len(zs)
    n = sum(len(z) for z in zs)
    if n - k <= 0:
        out["reason"] = "no_within_group_df"
        return out
    grand = sum(sum(z) for z in zs) / n
    ssb = sum(len(z) * (mean(z) - grand) ** 2 for z in zs)
    ssw = sum((v - mean(z)) ** 2 for z in zs for v in z)
    out["df"] = [k - 1, n - k]
    if not ssw > 0.0:
        out["reason"] = "zero_spread"
        return out
    w = (ssb / (k - 1)) / (ssw / (n - k))
    out["w"] = w
    out["p"] = float(fisher_f.sf(w, k - 1, n - k))
    return out
