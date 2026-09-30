"""Detailed profiling of npartitions components."""
import timeit
import math
import gmpy2
from mpmath.libmp import (fzero, from_man_exp, from_int, from_rational,
    fone, fhalf, bitcount, to_int, mpf_mul, mpf_div, mpf_sub,
    mpf_add, mpf_sqrt, mpf_pi, mpf_cosh_sinh, mpf_cos)
from mpmath.libmp.libmpf import round_fast as rnd
from sympy.ntheory.partitions_ import _precompute_coprimes, _d, _d_dedekind

n = 10**6
pbits = int((math.pi*(2*n/3.)**0.5 - math.log(4*n))/math.log(10) + 1) * math.log(10, 2)
prec = p_init = int(pbits*1.1 + 100)
M = max(6, int(0.24*n**0.5 + 4))

# Precompute
coprime_data = _precompute_coprimes(M)
_guard = 50
gmpy2.get_context().precision = prec + _guard
_gpi = gmpy2.const_pi()
_gsq23pi = gmpy2.sqrt(gmpy2.mpfr(2)/gmpy2.mpfr(3)) * _gpi
_gsqrt8 = gmpy2.sqrt(gmpy2.mpfr(8))
_gb = gmpy2.mpfr(n) - gmpy2.mpfr(1)/gmpy2.mpfr(24)
sq23pi = mpf_mul(mpf_sqrt(from_rational(2, 3, prec), prec), mpf_pi(prec), prec)
sqrt8 = mpf_sqrt(from_int(8), prec)

_math_cos = math.cos
_math_pi = math.pi
_gmpy2_cos = gmpy2.cos
_gmpy2_mpfr = gmpy2.mpfr
_mpf_add = mpf_add
_mpf_mul = mpf_mul
_from_man_exp = from_man_exp
_to_int = to_int
_bitcount = bitcount
_gc = gmpy2.sqrt(_gb)

# Simulate the loop, timing each component
import time

total_a_float = 0
total_a_gmpy2 = 0
total_d_gmpy2 = 0
total_d_mpmath = 0
total_accum = 0
total_prec_reduce = 0

p = prec
s = fzero
neg24n_int = -24 * n

for q in range(1, M):
    # _a timing
    t0 = time.perf_counter()
    if q == 1:
        a = fone
    else:
        paired, unpaired, c_h_arr, c_D_arr, c_count = coprime_data[q]
        if p <= 53:
            factor = _math_pi / (12.0 * q)
            cos_sum = 0.0
            neg24n_f = -24.0 * n
            for h, D in paired:
                cos_sum += _math_cos(factor * (D + neg24n_f * h))
            cos_sum *= 2
            if unpaired is not None:
                h, D = unpaired
                cos_sum += _math_cos(factor * (D + neg24n_f * h))
            if cos_sum == 0.0:
                a = fzero
            else:
                a = _from_man_exp(int(cos_sum * (1 << p)), -p, p, rnd)
            total_a_float += time.perf_counter() - t0
        else:
            wp = p + 10
            ctx = gmpy2.get_context()
            ctx.precision = wp
            pi_val = gmpy2.const_pi()
            cos_sum_g = _gmpy2_mpfr(0)
            factor = pi_val / (12 * q)
            neg24n_v = -24 * n
            for h, D in paired:
                cos_sum_g += _gmpy2_cos(factor * (D + neg24n_v * h))
            cos_sum_g *= 2
            if unpaired is not None:
                h, D = unpaired
                cos_sum_g += _gmpy2_cos(factor * (D + neg24n_v * h))
            m, e = cos_sum_g.as_mantissa_exp()
            a = _from_man_exp(int(m), int(e), p, rnd)
            total_a_gmpy2 += time.perf_counter() - t0

    # _d timing
    t0 = time.perf_counter()
    if p <= 1000:
        wp = p + _guard
        ctx = gmpy2.get_context()
        ctx.precision = wp
        j_mpfr = _gmpy2_mpfr(q)
        a_d = _gsq23pi / j_mpfr
        ac = a_d * _gc
        ch_d = gmpy2.cosh(ac)
        sh_d = gmpy2.sinh(ac)
        D_d = gmpy2.sqrt(j_mpfr) / (_gsqrt8 * _gb * _gpi)
        E_d = a_d * ch_d - sh_d / _gc
        result_d = D_d * E_d
        m, e = result_d.as_mantissa_exp()
        d = _from_man_exp(int(m), int(e), p, rnd)
        total_d_gmpy2 += time.perf_counter() - t0
    else:
        d = _d(n, q, p, sq23pi, sqrt8)
        total_d_mpmath += time.perf_counter() - t0

    # Accumulation timing
    t0 = time.perf_counter()
    s = _mpf_add(s, _mpf_mul(a, d), prec)
    total_accum += time.perf_counter() - t0

    # Precision reduction
    t0 = time.perf_counter()
    p = _bitcount(abs(_to_int(d))) + 50
    total_prec_reduce += time.perf_counter() - t0

total = total_a_float + total_a_gmpy2 + total_d_gmpy2 + total_d_mpmath + total_accum + total_prec_reduce

print(f"Component breakdown for npartitions({n}):")
print(f"  _a float path:    {total_a_float*1000:6.2f}ms ({total_a_float/total*100:5.1f}%)")
print(f"  _a gmpy2 path:    {total_a_gmpy2*1000:6.2f}ms ({total_a_gmpy2/total*100:5.1f}%)")
print(f"  _d gmpy2 path:    {total_d_gmpy2*1000:6.2f}ms ({total_d_gmpy2/total*100:5.1f}%)")
print(f"  _d mpmath path:   {total_d_mpmath*1000:6.2f}ms ({total_d_mpmath/total*100:5.1f}%)")
print(f"  accumulation:     {total_accum*1000:6.2f}ms ({total_accum/total*100:5.1f}%)")
print(f"  prec reduction:   {total_prec_reduce*1000:6.2f}ms ({total_prec_reduce/total*100:5.1f}%)")
print(f"  TOTAL:            {total*1000:6.2f}ms")
print(f"\n  _a total:         {(total_a_float+total_a_gmpy2)*1000:6.2f}ms ({(total_a_float+total_a_gmpy2)/total*100:5.1f}%)")
print(f"  _d total:         {(total_d_gmpy2+total_d_mpmath)*1000:6.2f}ms ({(total_d_gmpy2+total_d_mpmath)/total*100:5.1f}%)")
