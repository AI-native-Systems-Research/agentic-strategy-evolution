"""Test correctness and benchmark the full C npartitions implementation."""
import ctypes
import os
import timeit

# Load the .so
so_path = '/testbed/sympy/ntheory/_npartitions_c.so'
lib = ctypes.CDLL(so_path)

c_npartitions = lib.npartitions_c
c_npartitions.restype = ctypes.c_int
c_npartitions.argtypes = [
    ctypes.c_long,       # n
    ctypes.c_char_p,     # out_str
    ctypes.c_int,        # out_str_size
]

def npartitions_c(n):
    buf = ctypes.create_string_buffer(8192)
    c_npartitions(n, buf, 8192)
    return int(buf.value.decode())

# Correctness tests
from sympy import npartitions as np_sympy

print("=== Correctness Tests ===")
test_values = [0, 1, 2, 3, 4, 5, 10, 25, 50, 100, 200, 500, 1000, 5000, 10000, 100000, 1000000]
all_ok = True
for n in test_values:
    expected = np_sympy(n)
    got = npartitions_c(n)
    ok = "OK" if expected == got else "FAIL"
    if expected != got:
        all_ok = False
        print(f"  n={n}: expected={expected}, got={got} {ok}")
    else:
        print(f"  n={n}: {got} {ok}")

if all_ok:
    print("\nAll correctness tests passed!")
else:
    print("\nSOME TESTS FAILED!")

# Benchmark
print("\n=== Benchmark (n=10^6) ===")

# Warm up
npartitions_c(10**6)

# C version
times_c = timeit.repeat(lambda: npartitions_c(10**6), number=1, repeat=20)
import statistics
print(f"C npartitions:     Mean={statistics.mean(times_c)*1000:.2f}ms, Median={statistics.median(times_c)*1000:.2f}ms, Min={min(times_c)*1000:.2f}ms")

# Current Python version (warm cache)
np_sympy(10**6)  # warm
times_py = timeit.repeat(lambda: np_sympy(10**6), number=1, repeat=20)
print(f"Python npartitions: Mean={statistics.mean(times_py)*1000:.2f}ms, Median={statistics.median(times_py)*1000:.2f}ms, Min={min(times_py)*1000:.2f}ms")

print(f"\nSpeedup: {statistics.mean(times_py)/statistics.mean(times_c):.2f}x")
