"""Second-order fits carry the exact (X'X)^-1 (final expert audit H1).

The certificate's model regret bound is gated on contrasts between candidates,
which on a refine (composite) fit involve the correlated pure quadratics. The
per-column SE understated those contrasts by 1.3-1.5x, so the model half's
union bound sat near 0.11 against its stated 0.05. Checked against numpy.
"""

from __future__ import annotations

import numpy as np
import pytest

from orchestrator.optimize.design import central_composite
from orchestrator.optimize.effects import fit_effects, prediction_variance


@pytest.mark.parametrize("k", [2, 3])
def test_a_second_order_fit_uses_the_exact_covariance(k):
    ids = tuple("ABC"[:k])
    d = central_composite(list(ids), center_points=3)
    rng = np.random.default_rng(0)
    ys = [float(rng.normal()) for _ in d.points]
    fit = fit_effects(d, ys, factor_ids=ids)
    assert fit.covariance is not None, "a composite fit must keep (X'X)^-1"
    X = np.array([[1.0] + [np.prod([p.coded[ids.index(t)] for t in ts])
                           for ts in fit.term_terms[1:]] for p in d.points])
    exact = np.linalg.inv(X.T @ X)
    assert np.allclose(np.array(fit.covariance), exact, atol=1e-9)
    # A contrast between two points involving the quadratics: the reported
    # variance equals s^2 d'(X'X)^-1 d -- the quantity the certificate uses.
    xa = {t: 1.0 for t in ids}
    xb = {t: 0.0 for t in ids}
    row = lambda x: np.array([1.0] + [np.prod([x[t] for t in ts])
                                      for ts in fit.term_terms[1:]])
    dvec = row(xa) - row(xb)
    want = fit.pure_error_var * float(dvec @ exact @ dvec)
    assert prediction_variance(fit, xa, xb) == pytest.approx(want, rel=1e-9)


def test_a_first_order_fit_is_unchanged():
    from orchestrator.optimize.design import fractional_factorial, with_center_points

    d = with_center_points(fractional_factorial(list("ABCDE"), 5), 4)
    rng = np.random.default_rng(1)
    fit = fit_effects(d, [float(rng.normal()) for _ in d.points], factor_ids=tuple("ABCDE"))
    assert fit.covariance is None
