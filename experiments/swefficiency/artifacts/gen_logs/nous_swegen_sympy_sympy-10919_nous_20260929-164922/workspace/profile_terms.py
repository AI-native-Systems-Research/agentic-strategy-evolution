"""Profile term magnitudes and explore parallelism potential."""
import time
import math
import gmpy2
from mpmath.libmp import (fzero, from_man_exp, from_int, from_rational,
    fone, fhalf, bitcount, to_int, to_str, mpf_mul, mpf_div, mpf_sub,
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
_gc = gmpy2.sqrt(_gb)

# Run full computation, record d magnitudes and precision schedule
p = prec
s = fzero

prec_schedule = []
d_magnitudes = []

for q in range(1, M):
    prec_schedule.append(p)

    if q == 1:
        a = fone
    else:
        paired, unpaired, c_h_arr, c_D_arr, c_count = coprime_data[q]
        if p <= 53:
            factor = math.pi / (12.0 * q)
            cos_sum = 0.0
            neg24n_f = -24.0 * n
            for h, D in paired:
                cos_sum += math.cos(factor * (D + neg24n_f * h))
            cos_sum *= 2
            if unpaired is not None:
                h, D = unpaired
                cos_sum += math.cos(factor * (D + neg24n_f * h))
            if cos_sum == 0.0:
                a = fzero
            else:
                a = from_man_exp(int(cos_sum * (1 << p)), -p, p, rnd)
        else:
            wp = p + 10
            ctx = gmpy2.get_context()
            ctx.precision = wp
            pi_val = gmpy2.const_pi()
            cos_sum_g = gmpy2.mpfr(0)
            factor = pi_val / (12 * q)
            neg24n_v = -24 * n
            for h, D in paired:
                cos_sum_g += gmpy2.cos(factor * (D + neg24n_v * h))
            cos_sum_g *= 2
            if unpaired is not None:
                h, D = unpaired
                cos_sum_g += gmpy2.cos(factor * (D + neg24n_v * h))
            m, e = cos_sum_g.as_mantissa_exp()
            a = from_man_exp(int(m), int(e), p, rnd)

    if p <= 1000:
        wp = p + _guard
        ctx = gmpy2.get_context()
        ctx.precision = wp
        j_mpfr = gmpy2.mpfr(q)
        a_d = _gsq23pi / j_mpfr
        ac = a_d * _gc
        ch_d = gmpy2.cosh(ac)
        sh_d = gmpy2.sinh(ac)
        D_d = gmpy2.sqrt(j_mpfr) / (_gsqrt8 * _gb * _gpi)
        E_d = a_d * ch_d - sh_d / _gc
        result_d = D_d * E_d
        m, e = result_d.as_mantissa_exp()
        d = from_man_exp(int(m), int(e), p, rnd)
    else:
        d = _d(n, q, p, sq23pi, sqrt8)

    d_int = abs(to_int(d))
    d_mag = bitcount(d_int) if d_int else 0
    d_magnitudes.append(d_mag)

    term = mpf_mul(a, d)
    s = mpf_add(s, term, prec)
    p = d_mag + 50

print("Precision schedule (first 20, every 10th, last 10):")
for i in [0,1,2,3,4,5,10,20,30,40,50,60,80,100,120,150,200,230,235,240,242]:
    if i < len(prec_schedule):
        print(f"  q={i+1:3d}: p={prec_schedule[i]:5d}, |d|_bits={d_magnitudes[i]:5d}")

# Check where precision drops below 53
float_start = None
for i, p in enumerate(prec_schedule):
    if p <= 53:
        float_start = i + 1
        break
print(f"\nFloat path starts at q={float_start}")
print(f"Total iterations: {M-1}")

# Profile: time for d computation at different q values
print("\n_d computation times at different q:")
for q_test in [1, 5, 10, 50, 100, 150, 200, 243]:
    if q_test >= M:
        continue
    p_test = prec_schedule[q_test - 1]

    if p_test <= 1000:
        def run_d():
            wp = p_test + _guard
            ctx = gmpy2.get_context()
            ctx.precision = wp
            j_m = gmpy2.mpfr(q_test)
            a_d = _gsq23pi / j_m
            ac = a_d * _gc
            ch = gmpy2.cosh(ac)
            sh = gmpy2.sinh(ac)
            D_d = gmpy2.sqrt(j_m) / (_gsqrt8 * _gb * _gpi)
            E_d = a_d * ch - sh / _gc
            return D_d * E_d

        import timeit
        t = timeit.timeit(run_d, number=1000) / 1000
        print(f"  q={q_test:3d}, p={p_test:5d}: {t*1e6:.1f}us (gmpy2)")
    else:
        def run_d_m():
            return _d(n, q_test, p_test, sq23pi, sqrt8)
        t = timeit.timeit(run_d_m, number=100) / 100
        print(f"  q={q_test:3d}, p={p_test:5d}: {t*1e6:.1f}us (mpmath)")
