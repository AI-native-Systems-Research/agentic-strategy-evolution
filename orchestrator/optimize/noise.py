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


# ── #321 P3 item 4: is the workload seed real? (CRN verification) ──────────

#: Seed base of the verify-time probe (distinct from the baseline oracle's 0
#: and from every iteration base, so its draws are fresh).
CRN_PROBE_SEED_BASE = 104729
#: Default number of distinct seeds the probe runs (each twice).
CRN_PROBE_SEEDS = 4
CRN_PROBE_ALPHA = 0.05


def crn_probe_verdict(pairs, *, alpha: float = CRN_PROBE_ALPHA) -> dict:
    """Does the workload seed change the measurement? ``pairs`` holds, per
    distinct seed, the two runs made at that seed (same configuration).

    1. Same seed, run twice, MUST AGREE: every pair identical is exact
       agreement (a deterministic seeded target).
    2. Different seeds MUST DIFFER (when ``paired: true`` is to mean anything).

    Decided as a one-way random-effects ANOVA with the seed as the random
    factor (Searle, Casella & McCulloch 1992, §3.5): under H0 (the seed is
    ignored) ``F = MS_between / MS_within ~ F(m - 1, m)``; the pairing is
    REAL iff H0 is rejected at ``alpha``. A deterministic target (every
    within-seed pair identical) is decided exactly: real iff the seed means
    are not all equal. ``verdict``: ``real`` | ``decorative`` |
    ``not_testable`` (fewer than 2 seeds, or no spread at all).
    """
    pairs = [(float(a), float(b)) for a, b in pairs]
    m = len(pairs)
    out = {"method": "one_way_random_effects_anova_seed", "alpha": alpha,
           "seeds": m, "f": None, "p": None, "df": [m - 1, m] if m >= 2 else None,
           "same_seed_identical": None, "verdict": "not_testable"}
    if m < 2:
        return out
    same = all(a == b for a, b in pairs)
    out["same_seed_identical"] = same
    means = [(a + b) / 2 for a, b in pairs]
    if same:
        out["verdict"] = "real" if len(set(means)) > 1 else "decorative"
        out["basis"] = "exact: every same-seed pair agreed"
        return out
    gm = sum(means) / m
    msb = 2.0 * sum((x - gm) ** 2 for x in means) / (m - 1)
    msw = sum((a - b) ** 2 / 2.0 for a, b in pairs) / m
    f = msb / msw
    p = float(fisher_f.sf(f, m - 1, m))
    out.update(f=f, p=p, verdict="real" if p < alpha else "decorative")
    return out


# ── #321 P3 item 5: oracle 2(c) as a formal equivalence test ────────────────

BASELINE_TOST_ALPHA = 0.05


def tost_ratio(pre, post, *, margin_frac: float, alpha: float = BASELINE_TOST_ALPHA,
               paired: bool) -> dict:
    """Equivalence of the control's mean across the build, RELATIVE margin.

    H0: ``|mu_post - mu_pre| >= m |mu_pre|`` against H1: inside. With ``s =
    sign(mean(pre))`` (orientation only), H1 is the intersection of
    ``s (mu_post - (1 + m) mu_pre) < 0`` and ``s (mu_post - (1 - m) mu_pre) >
    0``: two LINEAR contrasts with fixed coefficients, so each is an exact
    one-sided t test at ``alpha`` -- paired on ``d_i = post_i - c pre_i`` under
    CRN (replicate i of both sides shares a workload draw), Welch otherwise --
    and the intersection-union test has size ``alpha`` (Berger 1982). This is
    the ratio-of-means TOST (Hauschke, Kieser & Hothorn 1999, Stat. Med. 18,
    93-105; Schuirmann 1987 for TOST): the margin is a fraction of the TRUE
    pre-build mean, not of its estimate, so no data-dependent constant enters
    the test. ``equivalent`` is ``None`` with a named ``reason`` when it cannot
    be decided (fewer than 2 replicates, zero spread, a zero pre-build mean).
    """
    import statistics as st

    from scipy.stats import t as student_t

    pre = [float(v) for v in pre]
    post = [float(v) for v in post]
    out = {"method": ("tost_ratio_paired_t" if paired else "tost_ratio_welch_t"),
           "margin_frac": margin_frac, "alpha": alpha, "equivalent": None,
           "reason": None, "p_lower": None, "p_upper": None}
    if len(pre) < 2 or len(post) < 2 or (paired and len(pre) != len(post)):
        out["reason"] = "fewer_than_two_replicates" if min(len(pre), len(post)) < 2 \
            else "unequal_replicate_counts_for_pairing"
        return out
    mp = st.mean(pre)
    if mp == 0.0:
        out["reason"] = "zero_pre_build_mean"
        return out
    s = 1.0 if mp > 0 else -1.0
    if st.variance(pre) == 0.0 and st.variance(post) == 0.0:
        # A deterministic target: both sides measured exactly, so the
        # equivalence is decided exactly, not tested.
        out.update(method="exact_deterministic", p=None,
                   equivalent=bool(abs(st.mean(post) - mp) < margin_frac * abs(mp)),
                   ratio_estimate=st.mean(post) / mp)
        return out

    def one_sided(c: float, upper: bool) -> float | None:
        # t for H0: s (mu_post - c mu_pre) >= 0 (upper) / <= 0 (lower).
        if paired:
            d = [s * (b - c * a) for a, b in zip(pre, post)]
            v = st.variance(d)
            if not v > 0.0:
                return None
            t = st.mean(d) / math.sqrt(v / len(d))
            df = len(d) - 1
        else:
            vb = st.variance(post) / len(post)
            va = c * c * st.variance(pre) / len(pre)
            se = math.sqrt(va + vb)
            den = (vb ** 2 / (len(post) - 1) + va ** 2 / (len(pre) - 1))
            if not (se > 0.0 and den > 0.0):
                return None
            t = s * (st.mean(post) - c * mp) / se
            df = (va + vb) ** 2 / den
        return float(student_t.cdf(t, df) if upper else student_t.sf(t, df))

    pu = one_sided(1.0 + margin_frac, upper=True)
    pl = one_sided(1.0 - margin_frac, upper=False)
    if pu is None or pl is None:
        out["reason"] = "zero_spread"
        return out
    out.update(p_upper=pu, p_lower=pl, p=max(pu, pl),
               equivalent=bool(pu < alpha and pl < alpha),
               ratio_estimate=st.mean(post) / mp)
    return out


# ── #321 P3 item 3 (A6): outliers, censoring ────────────────────────────────

OUTLIER_ALPHA = 0.05


def studentized_outliers(cols, ys, *, alpha: float = OUTLIER_ALPHA) -> dict:
    """Externally studentized residuals of an OLS fit, Bonferroni-flagged.

    ``t_i = e_i / (s_(i) sqrt(1 - h_ii))`` with ``s_(i)^2 = (SSE - e_i^2 /
    (1 - h_ii)) / (n - p - 1)``; under the model with iid normal errors each
    ``t_i ~ t_{n - p - 1}`` exactly (Belsley, Kuh & Welsch 1980, §2.1; Cook &
    Weisberg 1982, §2.2). Row i is FLAGGED when ``|t_i| > t_{1 - alpha/(2n),
    n-p-1}``: Bonferroni over the n rows, so under the model the probability
    of flagging ANY row is <= alpha (the Bonferroni outlier test, Weisberg
    2005 §9.1). Flagging only: the caller never deletes a row; it records a
    sensitivity refit. ``None`` entries where a row's leverage is 1 (its
    deleted residual does not exist). ``reason`` names why nothing was
    computed (no residual df, singular design).
    """
    from scipy.stats import t as student_t

    from orchestrator.optimize.adequacy import _invert, _xtx
    from orchestrator.optimize.effects import _solve_normal_equations

    n, p = len(ys), len(cols)
    out = {"method": "externally_studentized_bonferroni", "alpha": alpha,
           "n": n, "p": p, "df": n - p - 1, "threshold": None, "rows": [],
           "flagged": [], "reason": None}
    if n - p - 1 <= 0:
        out["reason"] = "no_residual_df"
        return out
    try:
        inv = _invert(_xtx(cols))
    except ValueError:
        out["reason"] = "singular_design"
        return out
    b = _solve_normal_equations(cols, ys)
    hs, es = [], []
    for r in range(n):
        x = [cols[c][r] for c in range(p)]
        hs.append(sum(x[i] * inv[i][j] * x[j] for i in range(p) for j in range(p)))
        es.append(ys[r] - sum(b[c] * x[c] for c in range(p)))
    sse = sum(e * e for e in es)
    crit = float(student_t.ppf(1.0 - alpha / (2.0 * n), n - p - 1))
    out["threshold"] = crit
    scale = 1.0 + sum(abs(y) for y in ys) / n
    for r in range(n):
        h, e = hs[r], es[r]
        if h >= 1.0 - 1e-9:
            out["rows"].append(None)
            continue
        s2 = (sse - e * e / (1.0 - h)) / (n - p - 1)
        if not s2 > (1e-24 * scale * scale):
            out["rows"].append(None)
            continue
        t = e / math.sqrt(s2 * (1.0 - h))
        out["rows"].append(t)
        if abs(t) > crit:
            out["flagged"].append(r)
    return out


def censored_bound(direction: str, run_timeout_sec: float | int | None) -> dict:
    """What a run killed at ``run_timeout_sec`` says about its response: it is
    RIGHT-CENSORED in run time, never a value. When the primary metric is the
    run's own wall-clock (a minimisation of time), the run's response is at
    least ``run_timeout_sec`` -- a lower bound, which can only make the
    configuration worse. Any other metric is censored with no bound on its
    value. The caller records the bound and never imputes it."""
    return {"censored": "right", "at_sec": run_timeout_sec,
            "implies": ("response >= run_timeout_sec when the metric is the run's "
                        "own wall-clock; otherwise no bound on the metric"),
            "imputed": False, "direction": direction}


# ── #321 P3 item 3 (A6): constraint semantics ───────────────────────────────

CONSTRAINT_SEMANTICS = ("every_replicate", "mean", "chance")


def parse_semantics(constraint: dict) -> tuple[str, float | None]:
    """``(kind, alpha)`` of ``constraints[].semantics``: ``every_replicate``
    (default; every replicate must pass), ``mean`` (the configuration's MEAN
    must satisfy the comparison), ``chance:<alpha>`` (the probability that one
    replicate violates it must be at most alpha). Raises ``ValueError`` on
    anything else."""
    raw = (constraint or {}).get("semantics", "every_replicate")
    if raw in ("every_replicate", "mean"):
        return raw, None
    if isinstance(raw, str) and raw.startswith("chance:"):
        a = float(raw.split(":", 1)[1])
        if not 0.0 < a < 1.0:
            raise ValueError(f"chance alpha {a!r} is not in (0, 1)")
        return "chance", a
    raise ValueError(f"semantics {raw!r}: use every_replicate | mean | chance:<alpha>")


def _violates(op: str, v: float, bound: float) -> bool:
    return not {"<": v < bound, "<=": v <= bound, ">": v > bound,
                ">=": v >= bound}[op]


def feasibility_shown(constraint: dict, values, *, level: float) -> dict:
    """Is a finalist SHOWN feasible under the constraint's semantics, at
    one-sided ``level``?

    * ``mean``: the one-sided ``1 - level`` t bound on the mean lies on the
      feasible side of the threshold (Student 1908; normal mean errors, M2).
    * ``chance:a``: the one-sided Clopper-Pearson (1934) ``1 - level`` upper
      bound on the violation probability, from ``k`` violating replicates of
      ``n``, ``Beta^-1(1 - level; k + 1, n - k)``, is at most ``a``. Exact
      (binomial, no normality). Shown only when ``n >= log(level)/log(1 - a)``
      even at k = 0 -- ``min_replicates`` says how many that is.

    ``shown`` is ``None`` with a reason when not computable (fewer than 2
    finite values, zero spread for ``mean``).
    """
    from scipy.stats import beta as beta_d
    from scipy.stats import t as student_t

    kind, a = parse_semantics(constraint)
    op, thr = constraint.get("op"), float(constraint.get("value"))
    vals = [float(v) for v in values if isinstance(v, (int, float)) and v == v]
    out = {"semantics": constraint.get("semantics", "every_replicate"), "n": len(vals),
           "level": level, "shown": None, "reason": None}
    if kind == "mean":
        if len(vals) < 2:
            out["reason"] = "fewer_than_two_values"
            return out
        m = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
        if not sd > 0.0:
            out.update(shown=not _violates(op, m, thr), mean=m, basis="zero_spread_exact")
            return out
        h = float(student_t.ppf(1.0 - level, len(vals) - 1)) * sd / math.sqrt(len(vals))
        worst = m + h if op in ("<", "<=") else m - h
        out.update(mean=m, bound=worst, method="one_sided_t_on_the_mean",
                   shown=not _violates(op, worst, thr))
        return out
    if kind == "chance":
        n = len(vals)
        if n < 1:
            out["reason"] = "no_values"
            return out
        k = sum(1 for v in vals if _violates(op, v, thr))
        ub = 1.0 if k >= n else float(beta_d.ppf(1.0 - level, k + 1, n - k))
        out.update(violations=k, upper=ub, alpha=a, method="clopper_pearson_one_sided",
                   min_replicates=math.ceil(math.log(level) / math.log(1.0 - a)),
                   shown=ub <= a)
        return out
    out["reason"] = "every_replicate_is_judged_per_row"
    return out


def replicate_outliers(groups: dict, *, alpha: float = OUTLIER_ALPHA) -> dict:
    """Outlying confirm replicates, per finalist, FLAG ONLY.

    Within a finalist of n replicates, replicate i's externally studentized
    residual is ``(x_i - mean_(i)) / (s_(i) sqrt(1 + 1/(n-1)))``, which is
    ``t_{n-2}`` under iid normal replicates (the deleted-residual test for one
    normal sample; Grubbs 1969 in its studentized form). Measured family-wise
    rate under the null, 3 heteroscedastic finalists, 4000 rounds: 0.052 /
    0.050 / 0.053 at n = 4 / 6 / 8 (SE 0.0034); Bonferroni is an upper bound
    on that FWER only approximately here because the n tests of one finalist
    are dependent; the measured rate is within 1 SE of alpha. Each finalist uses
    its OWN deleted variance, so heteroscedastic finalists do not flag each
    other. Bonferroni over every replicate of the round tested:
    ``|t| > t_{1 - alpha/(2N), n-2}``. Finalists with n < 4 are not tested
    (named in ``untested``)."""
    from scipy.stats import t as student_t

    tested = {k: [float(v) for v in xs] for k, xs in groups.items() if len(xs) >= 4}
    out = {"method": "deleted_residual_t_within_finalist_bonferroni", "alpha": alpha,
           "untested": sorted(k for k in groups if k not in tested),
           "flagged": {}, "studentized": {}}
    total = sum(len(v) for v in tested.values())
    if not total:
        return out
    for k, xs in tested.items():
        n = len(xs)
        crit = float(student_t.ppf(1.0 - alpha / (2.0 * total), n - 2))
        ts = []
        for i, x in enumerate(xs):
            rest = xs[:i] + xs[i + 1:]
            m = sum(rest) / (n - 1)
            s = math.sqrt(sum((v - m) ** 2 for v in rest) / (n - 2))
            t = None if not s > 0.0 else (x - m) / (s * math.sqrt(1.0 + 1.0 / (n - 1)))
            ts.append(t)
            if t is not None and abs(t) > crit:
                out["flagged"].setdefault(k, []).append(i)
        out["studentized"][k] = ts
        out.setdefault("threshold", {})[k] = crit
    return out
