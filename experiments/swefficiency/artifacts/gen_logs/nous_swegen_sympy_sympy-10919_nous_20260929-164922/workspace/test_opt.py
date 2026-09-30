"""Test correctness and benchmark optimized C npartitions."""
import ctypes
import timeit
import statistics

so_path = '/testbed/sympy/ntheory/_npartitions_opt.so'
lib = ctypes.CDLL(so_path)

c_npartitions = lib.npartitions_c
c_npartitions.restype = ctypes.c_int
c_npartitions.argtypes = [ctypes.c_long, ctypes.c_char_p, ctypes.c_int]

def npartitions_c(n):
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
    got = npartitions_c(n)
    ok = "OK" if expected == got else "FAIL"
    if expected != got:
        all_ok = False
        print(f"  n={n}: FAIL (expected={expected}, got={got})")
    else:
        print(f"  n={n}: {ok}")
print(f"\n{'All passed!' if all_ok else 'FAILURES!'}")

# Benchmark
print("\n=== Benchmark n=10^6 ===")
npartitions_c(10**6)
times_c = timeit.repeat(lambda: npartitions_c(10**6), number=1, repeat=30)
print(f"Opt C:    Mean={statistics.mean(times_c)*1000:.2f}ms, Median={statistics.median(times_c)*1000:.2f}ms, Min={min(times_c)*1000:.2f}ms, Stdev={statistics.stdev(times_c)*1000:.2f}ms")

np_sympy(10**6)
times_py = timeit.repeat(lambda: np_sympy(10**6), number=1, repeat=30)
print(f"Python:   Mean={statistics.mean(times_py)*1000:.2f}ms, Median={statistics.median(times_py)*1000:.2f}ms, Min={min(times_py)*1000:.2f}ms, Stdev={statistics.stdev(times_py)*1000:.2f}ms")

print(f"\nSpeedup: {statistics.mean(times_py)/statistics.mean(times_c):.2f}x")
print(f"Speedup (median): {statistics.median(times_py)/statistics.median(times_c):.2f}x")

# Also test workload.py style: 10 repeats, cold start
print("\n=== Workload-style (10 reps, includes cold start) ===")
import importlib
import sympy.ntheory.partitions_
importlib.reload(sympy.ntheory.partitions_)
runtimes = timeit.repeat(lambda: np_sympy(10**6), number=1, repeat=10)
print(f"Python workload: Mean={statistics.mean(runtimes)*1000:.2f}ms, Stdev={statistics.stdev(runtimes)*1000:.2f}ms")

runtimes_c = timeit.repeat(lambda: npartitions_c(10**6), number=1, repeat=10)
print(f"C workload: Mean={statistics.mean(runtimes_c)*1000:.2f}ms, Stdev={statistics.stdev(runtimes_c)*1000:.2f}ms")
