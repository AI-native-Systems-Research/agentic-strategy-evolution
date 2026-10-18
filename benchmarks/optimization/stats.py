"""Interval estimates for the benchmark tables (pure Python, no numpy).

* ``bootstrap_mean_ci`` -- percentile bootstrap of a mean, over whatever unit
  the caller passes (the benchmark passes one value per SEED, so the seed is
  the resampling unit). Seeded: the same values and seed give the same
  interval, and the seed is recorded in every JSON this benchmark writes.
* ``t_mean_ci`` -- the Student t interval of a mean, reported beside the
  bootstrap because with 8 seeds a percentile bootstrap is coarse.
* ``wilson_ci`` -- the Wilson score interval of a binomial proportion (Wilson
  1927), for the head-to-head win and loss proportions.

All three return ``(estimate, lo, hi)``; an empty input returns NaNs.
"""
from __future__ import annotations

import math
import random
import statistics

#: Resamples and seed of every bootstrap in the benchmark (recorded in meta).
BOOT_RESAMPLES = 10_000
BOOT_SEED = 20261018

NAN = float("nan")


def bootstrap_mean_ci(values, *, level: float = 0.95, resamples: int = BOOT_RESAMPLES,
                      seed: int = BOOT_SEED) -> tuple[float, float, float]:
    v = [float(x) for x in values]
    if not v:
        return NAN, NAN, NAN
    est = statistics.fmean(v)
    if len(v) == 1 or max(v) == min(v):
        return est, est, est
    rng = random.Random(seed)
    n = len(v)
    means = sorted(statistics.fmean(rng.choices(v, k=n)) for _ in range(resamples))
    a = (1.0 - level) / 2.0
    lo = means[max(0, int(math.floor(a * resamples)))]
    hi = means[min(resamples - 1, int(math.ceil((1.0 - a) * resamples)) - 1)]
    return est, lo, hi


def t_mean_ci(values, *, level: float = 0.95) -> tuple[float, float, float]:
    v = [float(x) for x in values]
    if not v:
        return NAN, NAN, NAN
    est = statistics.fmean(v)
    if len(v) == 1:
        return est, NAN, NAN
    from scipy.stats import t as _t

    half = _t.ppf(0.5 + level / 2.0, len(v) - 1) * statistics.stdev(v) / math.sqrt(len(v))
    return est, est - half, est + half


def wilson_ci(k: int, n: int, *, level: float = 0.95) -> tuple[float, float, float]:
    if n <= 0:
        return NAN, NAN, NAN
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.5 + level / 2.0)
    p = k / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, centre - half), min(1.0, centre + half)
