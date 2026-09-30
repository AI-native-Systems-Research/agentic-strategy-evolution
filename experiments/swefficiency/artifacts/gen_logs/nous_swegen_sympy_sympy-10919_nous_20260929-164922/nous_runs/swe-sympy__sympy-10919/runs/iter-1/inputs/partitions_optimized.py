from __future__ import print_function, division

import math
from functools import lru_cache
import gmpy2
from mpmath.libmp import (fzero,
    from_man_exp, from_int, from_rational,
    fone, fhalf, bitcount, to_int, to_str, mpf_mul, mpf_div, mpf_sub,
    mpf_add, mpf_sqrt, mpf_pi, mpf_cosh_sinh, pi_fixed, mpf_cos)
from mpmath.libmp.libmpf import round_fast as rnd
from sympy.core.compatibility import range


@lru_cache(maxsize=None)
def _d_dedekind(h, k):
    """Compute D(h,k) = 12*k*s(h,k) where s is the Dedekind sum.
    Uses reciprocity for O(log k) instead of O(k)."""
    if k <= 2:
        return 0
    h = h % k
    if h == 0:
        return 0
    if h == 1:
        return (k - 1) * (k - 2)
    return (h*h + k*k + 1 - 3*h*k - k*_d_dedekind(k % h, h)) // h


def _a(n, j, prec):
    """Compute the inner sum in the HRR formula.

    Optimizations over original:
    1. Memoized Dedekind sum via reciprocity (O(log j) vs O(j))
    2. Kloosterman symmetry D(j-h,j)=-D(h,j) halves iterations
    3. gmpy2 MPFR cos for high precision (C-level, replaces pure Python)
    4. Float path with hardware cos when precision <= 53 bits
    """
    if j == 1:
        return fone

    if prec <= 53:
        # Float path: hardware cos with Kloosterman symmetry
        cos_sum = 0.0
        pi_val = math.pi
        if j == 2:
            D = _d_dedekind(1, 2)
            cos_sum = math.cos(pi_val * (D - 24 * n) / 24)
        else:
            half_j = (j - 1) // 2
            for h in range(1, half_j + 1):
                if math.gcd(h, j) != 1:
                    continue
                D = _d_dedekind(h, j)
                cos_sum += math.cos(pi_val * (D - 24 * h * n) / (12 * j))
            cos_sum *= 2
        return from_man_exp(int(cos_sum * (1 << prec)), -prec, prec, rnd)
    else:
        # Use gmpy2 MPFR for cos computation (C-level, faster than pure Python)
        wp = prec + 10
        ctx = gmpy2.get_context()
        ctx.precision = wp
        pi_val = gmpy2.const_pi()
        cos_sum = gmpy2.mpfr(0)
        twelve_j = 12 * j

        if j == 2:
            D = _d_dedekind(1, 2)
            angle = pi_val * (D - 24 * n) / 24
            cos_sum = gmpy2.cos(angle)
        else:
            half_j = (j - 1) // 2
            for h in range(1, half_j + 1):
                if math.gcd(h, j) != 1:
                    continue
                D = _d_dedekind(h, j)
                angle = pi_val * (D - 24 * h * n) / twelve_j
                cos_sum += gmpy2.cos(angle)
            cos_sum *= 2

        man = int(cos_sum * gmpy2.mpfr(1 << wp))
        return from_man_exp(man, -wp, prec, rnd)


def _d(n, j, prec, sq23pi, sqrt8):
    """
    Compute the sinh term in the outer sum of the HRR formula.
    The constants sqrt(2/3*pi) and sqrt(8) must be precomputed.
    """
    j = from_int(j)
    pi = mpf_pi(prec)
    a = mpf_div(sq23pi, j, prec)
    b = mpf_sub(from_int(n), from_rational(1, 24, prec), prec)
    c = mpf_sqrt(b, prec)
    ch, sh = mpf_cosh_sinh(mpf_mul(a, c), prec)
    D = mpf_div(mpf_sqrt(j, prec), mpf_mul(mpf_mul(sqrt8, b), pi), prec)
    E = mpf_sub(mpf_mul(a, ch), mpf_div(sh, c, prec), prec)
    return mpf_mul(D, E)


def npartitions(n, verbose=False):
    """
    Calculate the partition function P(n), i.e. the number of ways that
    n can be written as a sum of positive integers.

    P(n) is computed using the Hardy-Ramanujan-Rademacher formula,
    described e.g. at http://mathworld.wolfram.com/PartitionFunctionP.html

    The correctness of this implementation has been tested for 10**n
    up to n = 8.

    Examples
    ========

    >>> from sympy.ntheory import npartitions
    >>> npartitions(25)
    1958
    """
    n = int(n)
    if n < 0:
        return 0
    if n <= 5:
        return [1, 1, 2, 3, 5, 7][n]
    # Estimate number of bits in p(n). This formula could be tidied
    pbits = int((math.pi*(2*n/3.)**0.5 - math.log(4*n))/math.log(10) + 1) * \
        math.log(10, 2)
    prec = p = int(pbits*1.1 + 100)
    s = fzero
    M = max(6, int(0.24*n**0.5 + 4))
    sq23pi = mpf_mul(mpf_sqrt(from_rational(2, 3, p), p), mpf_pi(p), p)
    sqrt8 = mpf_sqrt(from_int(8), p)
    for q in range(1, M):
        a = _a(n, q, p)
        d = _d(n, q, p, sq23pi, sqrt8)
        s = mpf_add(s, mpf_mul(a, d), prec)
        if verbose:
            print("step", q, "of", M, to_str(a, 10), to_str(d, 10))
        # On average, the terms decrease rapidly in magnitude. Dynamically
        # reducing the precision greatly improves performance.
        p = bitcount(abs(to_int(d))) + 50
    return int(to_int(mpf_add(s, fhalf, prec)))

__all__ = ["npartitions"]
