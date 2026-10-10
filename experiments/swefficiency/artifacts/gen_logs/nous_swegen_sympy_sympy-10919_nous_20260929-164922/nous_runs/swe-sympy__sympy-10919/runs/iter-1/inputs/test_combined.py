"""Combined optimizations: gmpy2 cos + early termination."""
import math
import timeit
import statistics
from functools import lru_cache

import gmpy2
from mpmath.libmp import (fzero, from_man_exp, from_int, from_rational,
    fone, fhalf, bitcount, to_int, mpf_mul, mpf_div, mpf_sub,
    mpf_add, mpf_sqrt, mpf_pi, mpf_cosh_sinh)
from mpmath.libmp.libmpf import round_fast as rnd

@lru_cache(maxsize=None)
def _d_dedekind(h, k):
    if k <= 2: return 0
    h = h % k
    if h == 0: return 0
    if h == 1: return (k - 1) * (k - 2)
    return (h*h + k*k + 1 - 3*h*k - k*_d_dedekind(k % h, h)) // h

def _a_opt(n, j, prec):
    if j == 1:
        return fone
    if prec <= 53:
        cos_sum = 0.0
        pi_val = math.pi
        if j == 2:
            D = _d_dedekind(1, 2)
            cos_sum = math.cos(pi_val * (D - 24*n) / 24)
        else:
            half_j = (j-1) // 2
            for h in range(1, half_j + 1):
                if math.gcd(h, j) != 1:
                    continue
                D = _d_dedekind(h, j)
                cos_sum += math.cos(pi_val * (D - 24*h*n) / (12*j))
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
            angle = pi_val * (D - 24*n) / 24
            cos_sum = gmpy2.cos(angle)
        else:
            half_j = (j-1) // 2
            for h in range(1, half_j + 1):
                if math.gcd(h, j) != 1:
                    continue
                D = _d_dedekind(h, j)
                angle = pi_val * (D - 24*h*n) / twelve_j
                cos_sum += gmpy2.cos(angle)
            cos_sum *= 2
        man = int(cos_sum * gmpy2.mpfr(1 << wp))
        return from_man_exp(man, -wp, prec, rnd)

def _d_opt(n, j, prec, sq23pi, sqrt8):
    j = from_int(j)
    pi = mpf_pi(prec)
    a = mpf_div(sq23pi, j, prec)
    b = mpf_sub(from_int(n), from_rational(1, 24, prec), prec)
    c = mpf_sqrt(b, prec)
    ch, sh = mpf_cosh_sinh(mpf_mul(a, c), prec)
    D = mpf_div(mpf_sqrt(j, prec), mpf_mul(mpf_mul(sqrt8, b), pi), prec)
    E = mpf_sub(mpf_mul(a, ch), mpf_div(sh, c, prec), prec)
    return mpf_mul(D, E)

def npartitions_opt(n, verbose=False):
    n = int(n)
    if n < 0: return 0
    if n <= 5: return [1, 1, 2, 3, 5, 7][n]
    pbits = int((math.pi*(2*n/3.)**0.5 - math.log(4*n))/math.log(10) + 1) * \
        math.log(10, 2)
    prec = p = int(pbits*1.1 + 100)
    s = fzero
    M = max(6, int(0.24*n**0.5 + 4))
    sq23pi = mpf_mul(mpf_sqrt(from_rational(2, 3, p), p), mpf_pi(p), p)
    sqrt8 = mpf_sqrt(from_int(8), p)
    for q in range(1, M):
        a = _a_opt(n, q, p)
        d = _d_opt(n, q, p, sq23pi, sqrt8)
        s = mpf_add(s, mpf_mul(a, d), prec)
        # On average, the terms decrease rapidly in magnitude.
        p = bitcount(abs(to_int(d))) + 50
        # Early termination: if d rounds to zero, remaining terms are negligible
        if not to_int(d):
            break
    return int(to_int(mpf_add(s, fhalf, prec)))

# Verify correctness
from sympy import npartitions
for test_n in [25, 100, 1000, 2000, 10000, 100000]:
    result = npartitions_opt(test_n)
    expected = npartitions(test_n)
    status = "PASS" if result == expected else "FAIL"
    print(f"P({test_n}): {status} (got={result}, expected={expected})")

# Benchmark current
a = 10**6
runtimes_current = timeit.repeat(lambda: npartitions(a), number=1, repeat=10)
print(f"\nCURRENT: mean={statistics.mean(runtimes_current):.4f}, std={statistics.stdev(runtimes_current):.4f}")

# Benchmark optimized
npartitions_opt(10**6)  # warmup
runtimes_opt = timeit.repeat(lambda: npartitions_opt(a), number=1, repeat=10)
print(f"OPTIMIZED: mean={statistics.mean(runtimes_opt):.4f}, std={statistics.stdev(runtimes_opt):.4f}")
print(f"Speedup: {statistics.mean(runtimes_current)/statistics.mean(runtimes_opt):.2f}x")
