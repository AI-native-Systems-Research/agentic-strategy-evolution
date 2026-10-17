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


# ── A5: small-n noise diagnostics and a robust terminal bound ───────────────

#: Monte-Carlo draws for the skewness test's null distribution, and its seed.
#: Constants (recorded in provenance): the null depends on the group sizes
#: only, never on the data, so a fixed seed makes the test reproducible.
SKEW_NULL_DRAWS = 20000
SKEW_NULL_SEED = 321

#: Bootstrap-t resamples (Hall 1988; Efron & Tibshirani 1993, §12.5) and seed.
BOOT_RESAMPLES = 999
BOOT_SEED = 3210

#: Exact sign-flip bound up to this many paired differences (2^16 subsets).
SIGN_FLIP_EXACT_MAX_N = 16

SKEW_METHOD = "studentized_third_moment_mc_null"


def sample_skewness(x) -> float | None:
    """Fisher's g1 = m3 / m2^(3/2) (moment estimator), ``None`` below n = 3
    or at zero spread."""
    x = [float(v) for v in x]
    n = len(x)
    if n < 3:
        return None
    m = sum(x) / n
    m2 = sum((v - m) ** 2 for v in x) / n
    if not m2 > 0.0:
        return None
    return (sum((v - m) ** 3 for v in x) / n) / m2 ** 1.5


def _studentized_third_moment(groups) -> float:
    zs: list[float] = []
    for g in groups:
        n = len(g)
        m = sum(g) / n
        s = math.sqrt(sum((v - m) ** 2 for v in g) / (n - 1))
        if s > 0.0:
            zs.extend(((v - m) / s) ** 3 for v in g)
    return abs(sum(zs) / len(zs)) if zs else 0.0


_NULL: dict = {}


def _null(sizes: tuple[int, ...]) -> list[float]:
    import random

    if sizes not in _NULL:
        rng = random.Random(SKEW_NULL_SEED)
        _NULL[sizes] = sorted(
            _studentized_third_moment([[rng.gauss(0.0, 1.0) for _ in range(n)]
                                       for n in sizes])
            for _ in range(SKEW_NULL_DRAWS))
    return _NULL[sizes]


def skewness_test(groups) -> dict:
    """Two-sided test of normal errors against skew, pooled over independent
    replicate groups.

    Statistic: ``T = |mean_ij z_ij^3|`` with ``z_ij = (y_ij - ybar_i) / s_i``.
    Under independent NORMAL errors, each group's studentized residual vector
    is ancillary -- its distribution is free of the group's mean and variance
    -- so the null of ``T`` depends on the group sizes alone, also under
    HETEROSCEDASTIC normal errors. The null is simulated (``SKEW_NULL_DRAWS``
    draws at a fixed seed; Barnard 1963's Monte-Carlo test), and
    ``p = (1 + #{T* >= T}) / (draws + 1)`` is a valid p-value. Groups with
    fewer than 3 observations carry no third-moment information and are
    skipped; ``p`` is ``None`` (``reason: no_group_of_three``) when none is
    left. The groups MUST be independent of each other (the caller tests
    correlated groups separately and corrects for multiplicity).
    """
    use = [[float(v) for v in g] for g in groups if len(g) >= 3]
    if not use:
        return {"method": SKEW_METHOD, "p": None, "stat": None, "sizes": [],
                "reason": "no_group_of_three"}
    import bisect

    sizes = tuple(sorted(len(g) for g in use))
    t = _studentized_third_moment(use)
    null = _null(sizes)
    ge = len(null) - bisect.bisect_left(null, t - 1e-12)
    return {"method": SKEW_METHOD, "p": (1 + ge) / (len(null) + 1), "stat": t,
            "sizes": list(sizes), "reason": None}


def sign_flip_floor(alpha: float) -> int:
    """The smallest n at which the exact sign-flip bound exists at level
    ``alpha``: Hartigan's subset-mean bound has coverage in steps of 2^-n, so
    it needs ``floor(alpha 2^n) >= 1``."""
    return max(1, math.ceil(math.log2(1.0 / alpha) - 1e-12))


def sign_flip_upper(d, alpha: float) -> float | None:
    """One-sided upper confidence bound for the centre of paired differences
    ``d``, valid at level ``1 - alpha`` when the differences are independent
    and SYMMETRIC about their centre (no normality).

    Hartigan (1969, JASA 64, 1303-1317): the ``2^n - 1`` non-empty subset
    means split the line into ``2^n`` intervals, each containing the centre
    with probability ``2^-n`` (continuous symmetric errors). So the k-th
    largest subset mean, ``k = floor(alpha 2^n)``, is exceeded by the centre
    with probability ``k 2^-n <= alpha`` -- the inversion of the exact
    sign-flip permutation test of the mean. ``None`` when ``k < 1`` (n below
    ``sign_flip_floor``) or n above ``SIGN_FLIP_EXACT_MAX_N`` (not computed).
    """
    d = [float(v) for v in d]
    n = len(d)
    k = math.floor(alpha * 2 ** n + 1e-12)
    if k < 1 or n > SIGN_FLIP_EXACT_MAX_N:
        return None
    sums = [(0.0, 0)]
    for v in d:
        sums += [(s + v, c + 1) for s, c in sums]
    means = sorted((s / c for s, c in sums[1:]), reverse=True)
    return means[k - 1]


def bootstrap_t_upper(xk, xb, alpha: float, *, seed: int = BOOT_SEED,
                      resamples: int = BOOT_RESAMPLES) -> float | None:
    """One-sided bootstrap-t upper bound on ``mean(k) - mean(b)`` for two
    INDEPENDENT samples (Hall 1988, Ann. Statist. 16, 927-953; Efron &
    Tibshirani 1993, §12.5): ``est - q_alpha * se`` with ``q_alpha`` the
    alpha-quantile of ``t* = (est* - est) / se*`` over within-sample
    resamples. Second-order accurate for skewed data, where Welch is only
    first-order; not exact at small n (the coverage is measured, spec §7).
    The seed is a constant, so the bound is reproducible from the record.
    ``None`` at zero spread or fewer than 2 observations per side."""
    import random

    xk = [float(v) for v in xk]
    xb = [float(v) for v in xb]
    nk, nb = len(xk), len(xb)
    if nk < 2 or nb < 2:
        return None

    def var(x):
        m = sum(x) / len(x)
        return sum((v - m) ** 2 for v in x) / (len(x) - 1)

    est = sum(xk) / nk - sum(xb) / nb
    se = math.sqrt(var(xk) / nk + var(xb) / nb)
    if not se > 0.0:
        return None
    rng = random.Random(seed)
    ts = []
    for _ in range(resamples):
        k = [xk[int(rng.random() * nk)] for _ in range(nk)]
        b = [xb[int(rng.random() * nb)] for _ in range(nb)]
        s = math.sqrt(var(k) / nk + var(b) / nb)
        ts.append(((sum(k) / nk - sum(b) / nb) - est) / s if s > 0.0 else -math.inf)
    ts.sort()
    j = math.floor(alpha * (resamples + 1))
    if j < 1:
        return None
    return est - ts[j - 1] * se


def brown_forsythe_contrast(cells, finalists) -> dict:
    """The DIRECTIONAL M3 test: do the finalists' replicates spread more than
    the pure-error cells?

    A planned one-sided contrast in Brown-Forsythe's ANOVA on absolute
    deviations from the median (structural zeros removed): ``L = mean of the
    finalist groups' mean deviations - mean of the cell groups' mean
    deviations``, ``t = L / sqrt(MSW sum c_i^2 / n_i)`` on the ANOVA's ``N - k``
    within df (Scheffe 1959, §3.5 planned contrasts; Brown & Forsythe 1974 for
    the deviation scale). One-sided because only one direction breaks the
    certificate: pure error UNDER-stating the variance where the finalists
    are makes the model bound anti-conservative; over-stating it makes the
    bound wider, which is safe. Measured (spec §7): size 0.01-0.05 under
    equal variances for normal, t3, exponential and lognormal noise at one
    centre cell of 4 and 3-4 finalists of 3-6; power at a 9x sd ratio 0.71
    (normal, finalists n = 6) against 0.14 for the omnibus F.
    """
    cells = [list(map(float, g)) for g in cells if len(g) >= 2]
    fins = [list(map(float, g)) for g in finalists if len(g) >= 2]
    out = {"method": "brown_forsythe_one_sided_contrast_finalists_vs_pure_error",
           "p": None, "t": None, "df": None, "reason": None}
    if not cells or not fins:
        out["reason"] = "no_pure_error_cells" if not cells else "fewer_than_two_groups"
        return out
    zs = [_abs_dev_from_median(g) for g in cells + fins]
    k = len(zs)
    n = sum(len(z) for z in zs)
    if n - k <= 0:
        out["reason"] = "no_within_group_df"
        return out
    msw = sum((v - mean(z)) ** 2 for z in zs for v in z) / (n - k)
    if not msw > 0.0:
        out["reason"] = "zero_spread"
        return out
    c = [-1.0 / len(cells)] * len(cells) + [1.0 / len(fins)] * len(fins)
    est = sum(ci * mean(z) for ci, z in zip(c, zs))
    se = math.sqrt(msw * sum(ci * ci / len(z) for ci, z in zip(c, zs)))
    from scipy.stats import t as student_t

    t = est / se
    out.update(t=t, df=n - k, p=float(student_t.sf(t, n - k)))
    return out
