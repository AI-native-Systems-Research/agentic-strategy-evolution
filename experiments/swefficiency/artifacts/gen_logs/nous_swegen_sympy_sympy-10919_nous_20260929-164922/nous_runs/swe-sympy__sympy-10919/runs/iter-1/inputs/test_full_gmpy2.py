"""Full gmpy2-based npartitions with careful precision management."""
import gmpy2
import math
import timeit
from functools import lru_cache
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

def _a_gmpy2(n, j, prec):
    """Compute inner sum using gmpy2 for trig, hardware floats when prec<=53."""
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

        # Convert to mpmath mpf
        man = int(cos_sum * gmpy2.mpfr(1 << wp))
        return from_man_exp(man, -wp, prec, rnd)


def _d_gmpy2(n, j, prec, sq23pi_g, sqrt8_g):
    """Compute sinh term using gmpy2 mpfr."""
    ctx = gmpy2.get_context()
    ctx.precision = prec + 10
    jf = gmpy2.mpfr(j)
    pi_val = gmpy2.const_pi()
    a = sq23pi_g / jf
    b = gmpy2.mpfr(n) - gmpy2.mpfr(1) / 24
    c = gmpy2.sqrt(b)
    ac = a * c
    # Use sinh_cosh which computes both at once
    sh, ch = gmpy2.sinh_cosh(ac)
    D = gmpy2.sqrt(jf) / (sqrt8_g * b * pi_val)
    E = a * ch - sh / c
    return D * E


def npartitions_gmpy2_full(n, verbose=False):
    n = int(n)
    if n < 0: return 0
    if n <= 5: return [1, 1, 2, 3, 5, 7][n]

    pbits = int((math.pi*(2*n/3.)**0.5 - math.log(4*n))/math.log(10) + 1) * \
        math.log(10, 2)
    prec = p = int(pbits*1.1 + 100)

    # Use mpmath accumulator at full precision (handles precision correctly)
    s = fzero
    M = max(6, int(0.24*n**0.5 + 4))

    # Precompute constants for both mpmath and gmpy2
    sq23pi = mpf_mul(mpf_sqrt(from_rational(2, 3, prec), prec), mpf_pi(prec), prec)
    sqrt8 = mpf_sqrt(from_int(8), prec)

    ctx = gmpy2.get_context()
    ctx.precision = prec + 10
    sq23pi_g = gmpy2.sqrt(gmpy2.mpfr(2)/3) * gmpy2.const_pi()
    sqrt8_g = gmpy2.sqrt(gmpy2.mpfr(8))

    GMPY2_D_THRESHOLD = 2000  # Use gmpy2 _d below this precision

    for q in range(1, M):
        a = _a_gmpy2(n, q, p)

        if p < GMPY2_D_THRESHOLD:
            # Use gmpy2 for _d at lower precision (2-3x faster)
            d_g = _d_gmpy2(n, q, p, sq23pi_g, sqrt8_g)
            # Convert to mpmath mpf
            wp = p + 10
            d_man = int(d_g * gmpy2.mpfr(1 << wp))
            d = from_man_exp(d_man, -wp, p, rnd)
        else:
            # Use mpmath for _d at high precision (faster there)
            d = _d_mpmath(n, q, p, sq23pi, sqrt8)

        s = mpf_add(s, mpf_mul(a, d), prec)
        p = bitcount(abs(to_int(d))) + 50

    return int(to_int(mpf_add(s, fhalf, prec)))


def _d_mpmath(n, j, prec, sq23pi, sqrt8):
    j = from_int(j)
    pi = mpf_pi(prec)
    a = mpf_div(sq23pi, j, prec)
    b = mpf_sub(from_int(n), from_rational(1, 24, prec), prec)
    c = mpf_sqrt(b, prec)
    ch, sh = mpf_cosh_sinh(mpf_mul(a, c), prec)
    D = mpf_div(mpf_sqrt(j, prec), mpf_mul(mpf_mul(sqrt8, b), pi), prec)
    E = mpf_sub(mpf_mul(a, ch), mpf_div(sh, c, prec), prec)
    return mpf_mul(D, E)


# Test correctness
from sympy import npartitions as np_ref
for test_n in [100, 1000, 2000, 10000]:
    result = npartitions_gmpy2_full(test_n)
    expected = np_ref(test_n)
    status = "PASS" if result == expected else "FAIL"
    print(f"P({test_n}): {status} (got={result}, expected={expected})")

# Benchmark
npartitions_gmpy2_full(10**6)  # warmup
t = timeit.repeat(lambda: npartitions_gmpy2_full(10**6), number=1, repeat=5)
print(f"\nFull gmpy2 hybrid: mean={sum(t)/len(t):.4f}, min={min(t):.4f}")

# Also benchmark the current version
from sympy import npartitions
npartitions(10**6)  # warmup
t_cur = timeit.repeat(lambda: npartitions(10**6), number=1, repeat=5)
print(f"Current version:   mean={sum(t_cur)/len(t_cur):.4f}, min={min(t_cur):.4f}")
