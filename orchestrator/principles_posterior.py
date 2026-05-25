"""Calibrated Bayesian posterior over principles (issue #164).

Replaces the heuristic confidence string ("low"/"medium"/"high") and
ad-hoc PRUNE/UPDATE decisions with a Beta-Binomial posterior over
"k of N citing arms produced outcomes consistent with this principle."

Why:
  principles.json already carries `evidence` (citing arm IDs). The
  cross-iteration knowledge-compounding step today reads the
  qualitative `confidence` string. A calibrated posterior over the
  same evidence yields:
    * a probability + 95% CI that's directly interpretable
    * a deterministic recommendation (keep / update / prune) instead
      of an LLM judgement call

Approach:
  Beta-Binomial conjugate update. Given prior Beta(a, b) and k of n
  consistent observations, the posterior is Beta(a+k, b+n-k):
    * mean       = (a+k) / (a+b+n)
    * 95% CI     = scipy.stats.beta.ppf(0.025, ...), .ppf(0.975, ...)
    * recommend  = keep   if ci_low > 0.5      (CI strictly above 0.5)
                   prune  if ci_high < 0.5     (CI strictly below 0.5)
                   update otherwise            (CI straddles 0.5)

  Default prior is Beta(1, 1) — uniform, maximum uncertainty.

Injection seam:
  `posterior(evidence, posterior_fn=fake)` lets tests substitute a
  deterministic stub. The default `posterior_fn` is closed-form scipy
  Beta — no MCMC, no randomness. The `posterior_fn=` seam reserves
  the option to plug in a hierarchical PyMC model later (e.g. for
  cross-principle pooling) without changing the call sites.

The conftest live-call guard hard-fails any test that invokes
`pymc.sample()`. Tests must use the seam.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from scipy.stats import beta as _beta_dist


PosteriorFn = Callable[[float, float], tuple[float, float, float]]
"""Signature for posterior_fn: takes Beta(a, b) parameters, returns
(mean, ci_low, ci_high). The default uses scipy closed-form."""


@dataclass(frozen=True)
class PrincipleEvidence:
    """Evidence row for a single principle.

    Attributes:
        principle_id: The principle's id (e.g. "RP-1").
        n_citations: How many arms cited this principle.
        n_consistent: Of those, how many produced outcomes consistent
            with the principle. Must be <= n_citations.
    """
    principle_id: str
    n_citations: int
    n_consistent: int


@dataclass(frozen=True)
class PosteriorResult:
    """Posterior summary for a single principle.

    Attributes:
        principle_id: Echoed from the input evidence.
        mean: Posterior mean of P(principle holds).
        ci_low: 2.5th percentile of the posterior.
        ci_high: 97.5th percentile of the posterior.
        n_citations: Echoed from the input evidence.
        recommendation: One of "keep", "update", "prune".
    """
    principle_id: str
    mean: float
    ci_low: float
    ci_high: float
    n_citations: int
    recommendation: str


def _scipy_posterior(a: float, b: float) -> tuple[float, float, float]:
    """Default closed-form posterior using scipy. No randomness."""
    mean = a / (a + b)
    ci_low = float(_beta_dist.ppf(0.025, a, b))
    ci_high = float(_beta_dist.ppf(0.975, a, b))
    return mean, ci_low, ci_high


def _classify(ci_low: float, ci_high: float) -> str:
    if ci_low > 0.5:
        return "keep"
    if ci_high < 0.5:
        return "prune"
    return "update"


def posterior(
    evidence: PrincipleEvidence,
    *,
    prior: tuple[float, float] = (1.0, 1.0),
    posterior_fn: PosteriorFn | None = None,
) -> PosteriorResult:
    """Compute the Beta-Binomial posterior for a principle.

    Args:
        evidence: Citation counts.
        prior: Beta(a, b) parameters. Defaults to Beta(1, 1) (uniform).
            Both must be > 0.
        posterior_fn: Optional callable for tests / future PyMC. Takes
            (a, b) post-update Beta parameters and returns
            (mean, ci_low, ci_high). Defaults to scipy closed-form.

    Returns:
        PosteriorResult with mean, 95% CI, and recommendation.

    Raises:
        ValueError: For invalid evidence counts or prior parameters.
    """
    if evidence.n_citations < 0:
        raise ValueError(f"n_citations must be >= 0 (got {evidence.n_citations!r})")
    if evidence.n_consistent < 0:
        raise ValueError(f"n_consistent must be >= 0 (got {evidence.n_consistent!r})")
    if evidence.n_consistent > evidence.n_citations:
        raise ValueError(
            f"n_consistent ({evidence.n_consistent}) must be <= "
            f"n_citations ({evidence.n_citations})",
        )
    a_prior, b_prior = prior
    if a_prior <= 0 or b_prior <= 0:
        raise ValueError(f"prior Beta(a,b) must have a>0 and b>0 (got {prior!r})")

    a_post = a_prior + evidence.n_consistent
    b_post = b_prior + (evidence.n_citations - evidence.n_consistent)

    fn = posterior_fn or _scipy_posterior
    mean, ci_low, ci_high = fn(a_post, b_post)

    return PosteriorResult(
        principle_id=evidence.principle_id,
        mean=float(mean),
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        n_citations=evidence.n_citations,
        recommendation=_classify(ci_low, ci_high),
    )
