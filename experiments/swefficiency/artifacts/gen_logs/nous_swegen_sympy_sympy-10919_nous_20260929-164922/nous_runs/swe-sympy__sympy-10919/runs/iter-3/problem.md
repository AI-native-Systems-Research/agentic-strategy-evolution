# Problem Framing: npartitions Loop Overhead Elimination (Iteration 3)

## Research Question

After iter-1's 54.5x algorithmic speedup (Dedekind reciprocity) and iter-2's 1.6x overhead reduction (coprime precomputation + gmpy2 _d dispatch), what further micro-optimizations can reduce npartitions(10^6) runtime by eliminating Python interpreter overhead in the main HRR loop?

Key source files:
- `sympy/ntheory/partitions_.py:58-106` — `_a(n, j, prec, coprime_data)`: inner sum with gmpy2 cos path and float path
- `sympy/ntheory/partitions_.py:108-121` — `_d(n, j, prec, sq23pi, sqrt8)`: sinh term (mpmath path for prec > 1000)
- `sympy/ntheory/partitions_.py:124-177` — `npartitions(n)`: main HRR loop with gmpy2 _d for prec <= 1000

## System Interface

- **Build command:** None (pure Python, except C helper compiled via gcc)
- **CLI flags:** `python /tmp/workload.py` — runs npartitions(10^6) 10 times, prints Mean/Std
- **Correctness gate:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`
- **Code evidence:**
  - `partitions_.py:63` — `if prec <= 53:` float path threshold
  - `partitions_.py:81` — `wp = prec + 10` gmpy2 working precision
  - `partitions_.py:88` — `man = int(cos_sum * gmpy2.mpfr(1 << wp))` mpfr→mpf conversion
  - `partitions_.py:148` — `if p <= 1000:` gmpy2 _d dispatch threshold
  - `partitions_.py:138` — `p = bitcount(abs(to_int(d))) + 50` dynamic precision reduction
- **Output:** Workload prints `Mean: <float>` and `Std Dev: <float>` to stdout.

## Baseline Command

```bash
docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"
```

## Baseline Validation

Ran the baseline (iter-2 optimized code): **Mean: 0.0141s, Std Dev: 0.0044s**. Covering tests pass (1/1). Exit code 0.

Profiling (5 warm calls, 11.6ms/call average):
- gmpy2.cos: 4.8ms (41%) — 2479 calls in gmpy2 _a path, irreducible MPFR computation
- npartitions body: 3.6ms (31%) — Python loop overhead, mpfr multiply/add, context switches
- gmpy2 cosh/sinh: 1.4ms (12%) — 239 iterations of gmpy2 _d
- mpf_add + mpf_mul: 0.8ms (7%) — mpmath accumulation
- mpmath high-prec: 0.4ms (3%) — 4 iterations with prec > 1000
- Other: 0.6ms (5%)

## Experimental Conditions

### h-main: Full optimization (C float path + inlined loop + micro-optimizations)

Six changes combined:

1. **C float-path helper:** Write a small C function `kloosterman_sum_float()` that computes the entire cos summation for the hardware-float path (prec <= 53). Compile with `gcc -O3 -shared -fPIC -lm`. The C function receives pre-allocated ctypes long arrays of h and D values plus the factor and neg24n, eliminating all Python loop overhead. Measured: 5x speedup on float path (2.1ms → 0.33ms for j=128..243).

2. **Inline _a into main loop:** Eliminate 243 Python function calls per npartitions invocation and share the gmpy2 context across _a and _d computation.

3. **Precompute per-j division factor:** Replace `pi_val * (D + neg24n * h) / twelve_j` with `factor * (D + neg24n * h)` where `factor = pi / (12*j)` is computed once per j. Saves one mpfr division per gmpy2.cos call. Measured: ~0.23μs saved per call × 2479 calls = 0.57ms.

4. **Precompute _d constants:** Compute `_gc = gmpy2.sqrt(_gb)` and `_d_base_denom = _gsqrt8 * _gb * _gpi` once instead of per-iteration, saving 239 sqrt and 3 multiply operations.

5. **Use `as_mantissa_exp()` for mpfr→mpf conversion:** Replace `int(result * gmpy2.mpfr(1 << wp))` + `from_man_exp(man, -wp, p, rnd)` with `m, e = result.as_mantissa_exp()` + `from_man_exp(int(m), int(e), p, rnd)`. Avoids creating a temporary mpfr(2^wp) and the large multiplication.

6. **Cache local attribute references:** Store `gmpy2.cos`, `gmpy2.cosh`, `gmpy2.sinh`, `gmpy2.sqrt`, `gmpy2.mpfr`, `math.cos`, `math.pi`, `mpf_add`, `mpf_mul`, `from_man_exp`, `to_int`, `bitcount`, `abs` as local variables to avoid module-level attribute lookups in the hot loop.

Combined measured result: **11.3ms mean** (vs 14ms baseline) = **1.24x speedup, 19% reduction**.

### h-ablation: Pure-Python optimizations only (no C helper)

Same as h-main changes 2-6 (inline, precompute, as_mantissa_exp, local refs) but WITHOUT the C float-path helper. Uses the existing Python `math.cos` loop for the float path.

This isolates whether the C helper is necessary or whether the Python-level optimizations account for most of the gain.

Measured in prototype: **12.0ms mean** = **1.14x speedup, 14% reduction**.

## Success Criteria

- **h-main:** workload_mean_runtime decreases consistently across all seeds vs baseline. Expected magnitude: ~20% reduction. All covering tests pass.
- **h-ablation:** workload_mean_runtime decreases vs baseline but less than h-main. All covering tests pass.
- **Directional:** h-main mean < h-ablation mean < baseline mean, consistently across seeds.

## Constraints

- Do NOT edit `/tmp/workload.py` or test files.
- Do NOT cache npartitions results or intermediate _a/_d values across calls.
- Covering tests must pass: `sympy/ntheory/tests/test_partitions.py`.
- M formula `max(6, int(0.24*sqrt(n)+4))` must be preserved (RP-2).
- j=2 unpaired term must not be doubled (RP-3).
- gmpy2 _d guard bits must be 50 (RP-4).
- All edits confined to library source under `/testbed`.

## Prior Knowledge

- **RP-1:** Dedekind reciprocity + memoization + Kloosterman symmetry + gmpy2 cos + hardware float fast path = 54.5x speedup. Applied in iter-1, currently active in container.
- **RP-2:** M cannot be reduced; early termination is unsafe. Constraint respected.
- **RP-3:** Coprime precomputation eliminates 37% of _a overhead. Applied in iter-2.
- **RP-4:** gmpy2 _d is 2x faster at prec <= 1000 with 50 guard bits. Applied in iter-2.
- No refuted mechanisms from prior iterations.

## What I Explored But Excluded

1. **CRT Kloosterman factorization:** Tested the multiplicative property A_{q1*q2}(n) = A_{q1}(n·bar_q2²)·A_{q2}(n·bar_q1²). Formula failed verification — relative errors >100% for most composite j. The HRR sum's Dedekind-weighted exponentials don't have the simple CRT decomposition of standard Kloosterman sums. Would have saved ~40% of gmpy2.cos calls for composite j.

2. **C MPFR inner loop for gmpy2 path:** Compiled C function calling system libmpfr.so directly via ctypes. Only 7% faster than gmpy2 Python wrapper because MPFR cos computation itself dominates — the Python wrapper adds minimal overhead per C call.

3. **Extending float path beyond prec=53:** Computed that using 53-bit hardware cos for 54≤prec≤100 accumulates error ~30 in the final integer (over 78 terms). This corrupts the exact result.

4. **NumPy vectorized float path:** 1.85x speedup vs C helper's 5x. NumPy per-call overhead exceeds the vectorization benefit for the array sizes involved (~60 elements per j).

5. **Double-double arithmetic for 53<prec≤100:** CPython interpreter overhead per double operation (~0.05μs) kills the advantage over gmpy2.cos (~1.2μs).
