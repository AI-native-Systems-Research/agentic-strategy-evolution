# Problem Framing: Optimizing `npartitions` in SymPy

## Research Question

How can we reduce the runtime of `npartitions(10**6)` (the integer partition function via the Hardy-Ramanujan-Rademacher formula) without changing its behavior, while keeping the covering tests green?

The implementation lives in `sympy/ntheory/partitions_.py`. The main function `npartitions` (line 55) calls `_a` (line 12, inner Kloosterman-type sum) and `_d` (line 39, sinh term). Profiling shows `_a` dominates at ~90% of runtime due to an O(j) inner Dedekind sum and full-precision `mpf_cos` per coprime.

## System Interface

- **Build command:** No build step needed (pure Python library).
- **Run workload:** `docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"`
- **Run tests:** `docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python -m pytest -q sympy/ntheory/tests/test_partitions.py"`
- **Code evidence:**
  - `sympy/ntheory/partitions_.py:12` — `_a(n, j, prec)`: inner sum with O(j) Dedekind sum loop (lines 22-34) and `mpf_cos` (line 35).
  - `sympy/ntheory/partitions_.py:39` — `_d(n, j, prec, sq23pi, sqrt8)`: sinh/cosh term using mpmath mpf operations.
  - `sympy/ntheory/partitions_.py:55` — `npartitions(n)`: main loop iterates q=1..M where M=max(6, int(0.24*n^0.5+4))=244 for n=10^6.
  - `sympy/ntheory/partitions_.py:90` — Dynamic precision reduction: `p = bitcount(abs(to_int(d))) + 50`.
  - `sympy/core/numbers.py` — `igcd` used for coprimality check (slow compared to `math.gcd`).
- **Output format:** Workload prints `Mean:` and `Std Dev:` to stdout.

## Baseline Command

```bash
docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"
```

## Baseline Validation

- **Exit code:** 0
- **Output:** `Mean: 1.2888257565020467` / `Std Dev: 0.021976392279180204`
- **Tests:** 1 passed in 0.03s (`sympy/ntheory/tests/test_partitions.py`)

## Experimental Conditions

### Condition: Optimized `_a` function (h-main)

Replace the `_a` function in `sympy/ntheory/partitions_.py` with an optimized version incorporating four changes:

1. **Memoized Dedekind sum via reciprocity** (`_d_dedekind` function): Replace the O(j) inner loop that computes Dedekind sums inline (lines 22-34) with a recursive function using the reciprocity law of Dedekind sums, achieving O(log j) per call. Cache results with `@lru_cache(maxsize=None)`.

2. **Kloosterman symmetry**: Exploit the identity D(j-h, j) = -D(h, j) to iterate only h from 1 to (j-1)//2, halving the inner loop iterations. Multiply the sum by 2.

3. **Hardware float fast path**: When precision drops to ≤53 bits (which happens around q=127 for n=10^6), use `math.cos` (hardware float) and `math.gcd` instead of arbitrary-precision `mpf_cos` and sympy's `igcd`.

4. **gmpy2 MPFR cos for fixed-point path**: For precision >53 bits, use `gmpy2.cos` (C-level MPFR implementation) instead of mpmath's pure-Python `cos_sin_basecase`. This avoids manual range reduction overhead and leverages MPFR's optimized trig implementation.

Additionally, replace `igcd` with `math.gcd` throughout (C-level built-in, faster than sympy's Python implementation).

## Success Criteria

- **Runtime reduction:** The workload mean runtime must decrease relative to the 1.29s baseline. Predicted target: <0.05s (>25x speedup).
- **Correctness:** All covering tests pass: `sympy/ntheory/tests/test_partitions.py` (1 test).
- **Numerical accuracy:** `npartitions(n)` must return the exact correct integer for all test values (n=0..5, 25, 100, 200, 1000, 2000, 10000, 100000).

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Only modify library source under `/testbed`.
- All work happens inside the Docker container `swegen_sympy_sympy-10919_nous`.
- Must maintain backward compatibility (same function signatures, same `__all__` exports).

## Prior Knowledge

This is iteration 1. No prior principles exist. The optimization targets are derived from profiling:
- `_a` function: 90%+ of runtime (O(j^2) Dedekind sums, expensive `mpf_cos`)
- `_d` function: ~10% of runtime (mpmath mpf operations)
- Dynamic precision reduction already exists but `_a` doesn't benefit until prec drops below 53
- Precision drops from 4148 bits to 53 bits over 127 iterations; remaining 117 iterations already fast
- gmpy2 with MPFR is available and provides 1.5-2.2x speedup for cos at 100-2000 bit precision
