"""A standard Gaussian-process regressor for the GP-BO baseline (numpy/scipy).

Configuration (chosen to match a widely used default, BoTorch's legacy
``SingleTaskGP``, rather than tuned to this suite):

* inputs coded to [0, 1] per dimension (log coding for ``scale: log``
  factors, one-hot for choices with more than two levels);
* outputs standardized (zero mean, unit variance) before fitting;
* kernel ``outputscale * Matern-5/2`` with one lengthscale per input
  dimension (ARD), plus a homoscedastic Gaussian noise term;
* hyperparameters fitted by MAP: the log marginal likelihood plus the
  BoTorch priors -- lengthscale ~ Gamma(3, 6), outputscale ~ Gamma(2, 0.15),
  noise variance ~ Gamma(1.1, 0.05) -- maximized by L-BFGS-B with analytic
  gradients from a warm start plus random restarts, within box bounds.

Nothing here is specific to any surface.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
from scipy.stats import norm

SQRT5 = math.sqrt(5.0)

#: (shape, rate) Gamma priors on the natural-scale parameter.
LS_PRIOR = (3.0, 6.0)
OS_PRIOR = (2.0, 0.15)
NOISE_PRIOR = (1.1, 0.05)

LOG_LS_BOUNDS = (math.log(0.01), math.log(20.0))
LOG_OS_BOUNDS = (math.log(0.01), math.log(50.0))
LOG_NOISE_BOUNDS = (math.log(1e-6), math.log(4.0))


def _sqdist_per_dim(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """``D[j, a, b] = (A[a, j] - B[b, j])**2``."""
    return (A.T[:, :, None] - B.T[:, None, :]) ** 2


def matern52(A, B, ls, os_):
    a, b = A / ls, B / ls  # scaled inputs: no n x m x d tensor
    r2 = (a * a).sum(1)[:, None] + (b * b).sum(1)[None, :] - 2.0 * a @ b.T
    r = np.sqrt(np.maximum(r2, 0.0))
    return os_ * (1.0 + SQRT5 * r + 5.0 / 3.0 * r * r) * np.exp(-SQRT5 * r)


def _gamma_logpdf_in_log_space(logp: float, a: float, b: float) -> tuple[float, float]:
    """log density of ``log p`` when ``p ~ Gamma(a, b)`` (up to a constant),
    and its derivative with respect to ``log p``."""
    p = math.exp(logp)
    return a * logp - b * p, a - b * p


class GP:
    """Fit once with ``fit(X, y)``; then ``predict(Xs) -> (mean, sd)`` in the
    ORIGINAL output units. ``theta`` (log lengthscales, log outputscale, log
    noise) can be passed back in as a warm start."""

    def __init__(self, *, restarts: int = 2, seed: int = 0):
        self.restarts, self.rs = restarts, np.random.RandomState(seed)
        self.theta: np.ndarray | None = None

    # ── objective ──────────────────────────────────────────────────────────
    def _neg_log_post(self, theta, X, y):
        d = X.shape[1]
        ls, os_, nz = np.exp(theta[:d]), math.exp(theta[d]), math.exp(theta[d + 1])
        d2 = _sqdist_per_dim(X, X)
        r = np.sqrt(np.maximum((d2 / (ls[:, None, None] ** 2)).sum(0), 0.0))
        e = np.exp(-SQRT5 * r)
        K0 = os_ * (1.0 + SQRT5 * r + 5.0 / 3.0 * r * r) * e
        n = len(y)
        K = K0 + (nz + 1e-8) * np.eye(n)
        try:
            c = cho_factor(K, lower=True, check_finite=False)
        except np.linalg.LinAlgError:
            return 1e10, np.zeros_like(theta)
        alpha = cho_solve(c, y, check_finite=False)
        logdet = 2.0 * np.log(np.diag(c[0])).sum()
        nll = 0.5 * y @ alpha + 0.5 * logdet + 0.5 * n * math.log(2 * math.pi)
        W = cho_solve(c, np.eye(n), check_finite=False) - np.outer(alpha, alpha)
        g = np.empty_like(theta)
        common = os_ * (5.0 / 3.0) * (1.0 + SQRT5 * r) * e
        for j in range(d):
            dK = common * d2[j] / ls[j] ** 2
            g[j] = 0.5 * (W * dK).sum()
        g[d] = 0.5 * (W * K0).sum()
        g[d + 1] = 0.5 * np.trace(W) * nz
        # MAP: subtract the log priors (in log-parameter space).
        for j in range(d):
            lp, dlp = _gamma_logpdf_in_log_space(theta[j], *LS_PRIOR)
            nll -= lp
            g[j] -= dlp
        lp, dlp = _gamma_logpdf_in_log_space(theta[d], *OS_PRIOR)
        nll, g[d] = nll - lp, g[d] - dlp
        lp, dlp = _gamma_logpdf_in_log_space(theta[d + 1], *NOISE_PRIOR)
        nll, g[d + 1] = nll - lp, g[d + 1] - dlp
        return float(nll), g

    def _bounds(self, d):
        return [LOG_LS_BOUNDS] * d + [LOG_OS_BOUNDS, LOG_NOISE_BOUNDS]

    def _random_theta(self, d):
        return np.array([self.rs.uniform(lo, hi) for lo, hi in self._bounds(d)])

    def fit(self, X: np.ndarray, y: np.ndarray, *, theta0: np.ndarray | None = None,
            optimize: bool = True, restarts: int | None = None) -> "GP":
        """MAP-fit the hyperparameters (``optimize``) from ``theta0`` (warm
        start), a default start and ``restarts`` random starts; or, with
        ``optimize=False``, reuse ``theta0`` and only refactorize."""
        X = np.asarray(X, float)
        y = np.asarray(y, float)
        d = X.shape[1]
        self.ym = float(y.mean())
        self.ys = float(y.std()) or 1.0
        yn = (y - self.ym) / self.ys
        if theta0 is None or len(theta0) != d + 2:
            theta0, optimize = None, True
        if optimize:
            starts = [] if theta0 is None else [np.asarray(theta0, float)]
            n_rand = self.restarts if restarts is None else restarts
            if theta0 is None:
                starts.append(np.array([math.log(1 / 3)] * d + [0.0, math.log(0.1)]))
                n_rand = max(n_rand, 1)
            starts += [self._random_theta(d) for _ in range(n_rand)]
            best = None
            for t0 in starts:
                res = minimize(self._neg_log_post, t0, args=(X, yn), jac=True,
                               method="L-BFGS-B", bounds=self._bounds(d),
                               options={"maxiter": 200})
                if best is None or res.fun < best[0]:
                    best = (res.fun, res.x)
            theta = best[1]
        else:
            theta = np.asarray(theta0, float)
        self.theta = theta
        ls, os_, nz = np.exp(theta[:d]), math.exp(theta[d]), math.exp(theta[d + 1])
        self.ls, self.os, self.noise = ls, os_, nz
        K = matern52(X, X, ls, os_) + (nz + 1e-8) * np.eye(len(X))
        self._c = cho_factor(K, lower=True, check_finite=False)
        self._alpha = cho_solve(self._c, yn, check_finite=False)
        self.X = X
        return self

    def predict(self, Xs: np.ndarray, chunk: int = 2048) -> tuple[np.ndarray, np.ndarray]:
        """Posterior mean and sd of the LATENT function (noise excluded)."""
        Xs = np.asarray(Xs, float)
        mus, sds = [], []
        for i in range(0, len(Xs), chunk):
            Ks = matern52(self.X, Xs[i:i + chunk], self.ls, self.os)
            mu = Ks.T @ self._alpha
            v = cho_solve(self._c, Ks, check_finite=False)
            var = np.maximum(self.os - (Ks * v).sum(0), 1e-12)
            mus.append(mu * self.ys + self.ym)
            sds.append(np.sqrt(var) * self.ys)
        return np.concatenate(mus), np.concatenate(sds)


def expected_improvement(mu: np.ndarray, sd: np.ndarray, incumbent: float) -> np.ndarray:
    """EI for MAXIMIZATION over the latent posterior."""
    sd = np.maximum(sd, 1e-12)
    z = (mu - incumbent) / sd
    return (mu - incumbent) * norm.cdf(z) + sd * norm.pdf(z)


# ── the audit's crude GP, kept only to reproduce its head-to-head ──────────
def crude_posterior(X, y, Xs, ls=0.3, nug=1e-2, chunk=1024):
    """Fixed-hyperparameter isotropic RBF GP exactly as ``probe_q6.gp_post``:
    lengthscale 0.3 on [0,1] coding, nugget 0.01, no fitting. Evaluated over
    ``Xs`` in chunks: an unchunked n x m x d difference tensor is GBs at the
    many-knob budgets."""
    def k(a, b):
        d = (a * a).sum(1)[:, None] + (b * b).sum(1)[None, :] - 2.0 * a @ b.T
        return np.exp(-0.5 * np.maximum(d, 0.0) / ls ** 2)
    ym, ys = y.mean(), y.std() or 1.0
    yn = (y - ym) / ys
    K = k(X, X) + nug * np.eye(len(X))
    L = np.linalg.cholesky(K)
    a = np.linalg.solve(L.T, np.linalg.solve(L, yn))
    mus, sds = [], []
    for i in range(0, len(Xs), chunk):
        Ks = k(X, Xs[i:i + chunk])
        v = np.linalg.solve(L, Ks)
        mus.append(Ks.T @ a)
        sds.append(np.sqrt(np.clip(1.0 - (v ** 2).sum(0), 1e-12, None)))
    return np.concatenate(mus) * ys + ym, np.concatenate(sds) * ys
