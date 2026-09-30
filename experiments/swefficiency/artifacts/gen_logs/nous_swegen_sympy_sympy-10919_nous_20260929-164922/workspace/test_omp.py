"""Test correctness and benchmark OpenMP npartitions."""
import ctypes
import timeit
import statistics

so_path = '/testbed/sympy/ntheory/_npartitions_omp.so'
lib = ctypes.CDLL(so_path)

c_npartitions = lib.npartitions_c
c_npartitions.restype = ctypes.c_int
c_npartitions.argtypes = [ctypes.c_long, ctypes.c_char_p, ctypes.c_int]

def npartitions_omp(n):
    buf = ctypes.create_string_buffer(8192)
    c_npartitions(n, buf, 8192)
    return int(buf.value.decode())

from sympy import npartitions as np_sympy

# Correctness
print("=== Correctness ===")
test_values = [0, 1, 5, 10, 25, 100, 1000, 10000, 100000, 1000000]
all_ok = True
for n in test_values:
    expected = np_sympy(n)
    got = npartitions_omp(n)
    ok = "OK" if expected == got else "FAIL"
    if expected != got:
        all_ok = False
        print(f"  n={n}: FAIL (expected={expected}, got={got})")
    else:
        print(f"  n={n}: {ok}")
print(f"\n{'All passed!' if all_ok else 'FAILURES!'}")

# Benchmark
print("\n=== Benchmark n=10^6 (20 reps) ===")

# OMP warm-up
npartitions_omp(10**6)
times_omp = timeit.repeat(lambda: npartitions_omp(10**6), number=1, repeat=20)
print(f"OMP C:    Mean={statistics.mean(times_omp)*1000:.2f}ms, Median={statistics.median(times_omp)*1000:.2f}ms, Min={min(times_omp)*1000:.2f}ms")

# Python warm-up
np_sympy(10**6)
times_py = timeit.repeat(lambda: np_sympy(10**6), number=1, repeat=20)
print(f"Python:   Mean={statistics.mean(times_py)*1000:.2f}ms, Median={statistics.median(times_py)*1000:.2f}ms, Min={min(times_py)*1000:.2f}ms")

print(f"\nSpeedup: {statistics.mean(times_py)/statistics.mean(times_omp):.2f}x")

# Try different thread counts
print("\n=== Thread scaling ===")
import os
for nthreads in [1, 2, 4, 8]:
    os.environ['OMP_NUM_THREADS'] = str(nthreads)
    # Need to reload the library to pick up thread count
    # Actually, OMP reads env at parallel region entry
    npartitions_omp(10**6)  # warm
    times = timeit.repeat(lambda: npartitions_omp(10**6), number=1, repeat=10)
    print(f"  {nthreads} threads: Mean={statistics.mean(times)*1000:.2f}ms, Median={statistics.median(times)*1000:.2f}ms")
