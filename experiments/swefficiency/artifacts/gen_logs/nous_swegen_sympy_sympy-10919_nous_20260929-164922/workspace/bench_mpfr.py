"""Benchmark: MPFR batch C helper vs gmpy2 individual cos calls."""
import ctypes
import os
import timeit
import gmpy2
import math
from mpmath.libmp import from_man_exp
from mpmath.libmp.libmpf import round_fast as rnd

# Load the v2 .so
so_path = os.path.join('/testbed/sympy/ntheory', '_kloosterman_v2.so')
lib = ctypes.CDLL(so_path)

# Set up kloosterman_sum_mpfr
c_kloosterman_mpfr = lib.kloosterman_sum_mpfr
c_kloosterman_mpfr.restype = ctypes.c_int
c_kloosterman_mpfr.argtypes = [
    ctypes.POINTER(ctypes.c_long),  # h_vals
    ctypes.POINTER(ctypes.c_long),  # D_vals
    ctypes.c_int,                    # count
    ctypes.c_long,                   # neg24n
    ctypes.c_int,                    # j_val
    ctypes.c_int,                    # prec
    ctypes.c_long,                   # h_unpaired
    ctypes.c_long,                   # D_unpaired
    ctypes.c_int,                    # has_unpaired
    ctypes.c_char_p,                 # out_mantissa
    ctypes.c_int,                    # out_mantissa_size
    ctypes.POINTER(ctypes.c_long),   # out_exponent
]

# Set up compute_d_mpfr
c_compute_d = lib.compute_d_mpfr
c_compute_d.restype = ctypes.c_int
c_compute_d.argtypes = [
    ctypes.c_int,        # n
    ctypes.c_int,        # j_val
    ctypes.c_int,        # prec
    ctypes.c_char_p,     # out_mantissa
    ctypes.c_int,        # out_mantissa_size
    ctypes.POINTER(ctypes.c_long),  # out_exponent
]

# Set up test data: typical j=5, which has coprime h values 1,2,3,4 with gcd(h,5)=1
# For j=5, coprimes: 1, 2, 3, 4 all coprime. Paired: h=1,2 (half_j=2)
n = 10**6
neg24n = -24 * n

# Get actual coprime data from the existing module
from sympy.ntheory.partitions_ import _precompute_coprimes, _d_dedekind
M = 244
coprime_data = _precompute_coprimes(M)

# Let's test with j=10 which has a decent number of coprimes
test_j = 10
paired, unpaired, c_h_arr_old, c_D_arr_old, c_count = coprime_data[test_j]
print(f"j={test_j}: {len(paired)} paired items, unpaired={unpaired}")

# Build ctypes arrays for MPFR batch
h_vals = [p[0] for p in paired]
D_vals = [p[1] for p in paired]
count = len(paired)
c_h = (ctypes.c_long * count)(*h_vals)
c_D = (ctypes.c_long * count)(*D_vals)

# Benchmark MPFR batch for different precisions
for prec in [63, 100, 200, 500, 1000]:
    # MPFR batch
    buf = ctypes.create_string_buffer(4096)
    exp = ctypes.c_long(0)

    def run_mpfr_batch():
        c_kloosterman_mpfr(c_h, c_D, count, neg24n, test_j, prec,
                           0, 0, 0, buf, 4096, ctypes.byref(exp))

    t_batch = timeit.timeit(run_mpfr_batch, number=1000) / 1000

    # gmpy2 individual
    def run_gmpy2():
        ctx = gmpy2.get_context()
        ctx.precision = prec + 10
        pi_val = gmpy2.const_pi()
        factor = pi_val / (12 * test_j)
        cos_sum = gmpy2.mpfr(0)
        neg24n_v = -24 * n
        for h, D in paired:
            cos_sum += gmpy2.cos(factor * (D + neg24n_v * h))
        cos_sum *= 2
        m, e = cos_sum.as_mantissa_exp()
        return from_man_exp(int(m), int(e), prec, rnd)

    t_gmpy2 = timeit.timeit(run_gmpy2, number=1000) / 1000

    print(f"prec={prec:4d}: MPFR batch={t_batch*1e6:8.1f}us, gmpy2={t_gmpy2*1e6:8.1f}us, ratio={t_gmpy2/t_batch:.2f}x")

# Also benchmark _d computation
print("\n_d computation:")
for prec in [100, 500, 1000, 2000, 4000]:
    buf = ctypes.create_string_buffer(4096)
    exp = ctypes.c_long(0)

    def run_d_mpfr():
        c_compute_d(n, 5, prec, buf, 4096, ctypes.byref(exp))

    t_d = timeit.timeit(run_d_mpfr, number=1000) / 1000

    # Compare with gmpy2 _d
    def run_d_gmpy2():
        ctx = gmpy2.get_context()
        ctx.precision = prec + 50
        gpi = gmpy2.const_pi()
        gsq23pi = gmpy2.sqrt(gmpy2.mpfr(2)/gmpy2.mpfr(3)) * gpi
        gsqrt8 = gmpy2.sqrt(gmpy2.mpfr(8))
        gb = gmpy2.mpfr(n) - gmpy2.mpfr(1)/gmpy2.mpfr(24)
        j_m = gmpy2.mpfr(5)
        a_d = gsq23pi / j_m
        gc = gmpy2.sqrt(gb)
        ac = a_d * gc
        ch = gmpy2.cosh(ac)
        sh = gmpy2.sinh(ac)
        D_d = gmpy2.sqrt(j_m) / (gsqrt8 * gb * gpi)
        E_d = a_d * ch - sh / gc
        result = D_d * E_d
        m, e = result.as_mantissa_exp()
        return from_man_exp(int(m), int(e), prec, rnd)

    t_d_gmpy2 = timeit.timeit(run_d_gmpy2, number=1000) / 1000

    print(f"prec={prec:4d}: C _d={t_d*1e6:8.1f}us, gmpy2 _d={t_d_gmpy2*1e6:8.1f}us, ratio={t_d_gmpy2/t_d:.2f}x")

# Now test full npartitions timing breakdown
print("\n\nFull npartitions benchmark (warm cache, 20 runs):")
from sympy import npartitions as np_func
np_func(10**6)  # warm
times = timeit.repeat(lambda: np_func(10**6), number=1, repeat=20)
import statistics
print(f"Mean: {statistics.mean(times)*1000:.2f}ms, Median: {statistics.median(times)*1000:.2f}ms")
