# Problem Framing — Iteration 4

## Research Question

How can we further reduce the runtime of `npartitions(10^6)` in `sympy/ntheory/partitions_.py` beyond the iter-3 optimizations (Dedekind sum O(log j), cosine symmetry, float64 fast path — 22.1x local baseline speedup), by eliminating the separate precomputation pass and exploiting memoization of overlapping Dedekind sum subproblems?

Key source files:
- `sympy/ntheory/partitions_.py:15` — `_dedekind_sum(h, j)`: recursive O(log j) Dedekind sum, target for `@lru_cache`.
- `sympy/ntheory/partitions_.py:43` — `_d(n, j, prec, sq23pi, sqrt8)`: sinh term computation.
- `sympy/ntheory/partitions_.py:57` — `npartitions(n)`: outer HRR loop with float64 fast path dispatch.

## System Interface

- **Build command:** None (pure Python library). Requires: `pip install mpmath pytest`.
- **CLI flags:** `PYTHONPATH=$PWD python /tmp/workload.py` to run the benchmark.
- **Tests:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`
- **Code evidence:**
  - `sympy/ntheory/partitions_.py:15` — `_dedekind_sum()`: GCD-like recursion `_dedekind_sum(h,j) → _dedekind_sum(j%h, h)` produces overlapping subproblems; 37,715 total calls with only 10,230 unique pairs.
  - `sympy/ntheory/partitions_.py:57` — `npartitions()`: outer loop processes q=1..M-1 sequentially; processing small q first maximizes Dedekind cache hits for larger q.
  - Python 3.11 compat patches needed: `sympy/core/basic.py:3`, etc.
- **Output:** `Mean: <seconds>` and `Std Dev: <seconds>` on stdout.

## Baseline Command

```bash
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

With iter-3 code (Dedekind sum + float64 fast path):
- Exit code: 0
- Output: `Mean: 0.0628s` (average of 3 runs: 0.0594, 0.0644, 0.0647)
- Reference baseline: 1.3901s
- Speedup vs reference: 1.3901 / 0.0628 ≈ 22.1x

## Experimental Conditions

### h-main: Memoized Dedekind sum + inline T computation (eliminate precomputation)

Two combined optimizations building on iter-3:

1. **`@lru_cache(maxsize=None)` on `_dedekind_sum`**: The GCD-like recursion produces overlapping subproblems. Profiling shows 37,715 total calls but only 10,230 unique (h,j) pairs — **73% redundant**. Memoization converts redundant recursive calls from O(log j) to O(1) dict lookup.

2. **Eliminate separate precomputation pass**: Instead of precomputing T values for all j=3..M-1 in a separate loop (which spends ~15ms computing float-path values that don't benefit from precomputation), compute T values inline during the main loop. For the float path (q≥94), use the cached `_dedekind_sum` to compute T/j values on-the-fly. This eliminates 15ms of precomputation overhead while the memoization ensures subproblems are still shared across q iterations.

3. **Local variable caching**: Bind frequently-used builtins (gcd, cos, sqrt, etc.) to local variables to avoid module-level attribute lookups in tight loops.

**Measured:** Mean 0.0536s → 25.9x speedup over reference.

### h-ablation: Memoized Dedekind sum only (keep separate functions)

Only add `@lru_cache(maxsize=None)` to `_dedekind_sum`. Keep the existing `_T`, `_a`, `_a_float` functions and the `npartitions` outer loop unchanged from iter-3. This isolates the memoization contribution from the inlining/no-precomputation restructuring.

**Measured:** Mean 0.0565s → 24.6x speedup over reference.

## Success Criteria

- **h-main > iter-3 baseline**: Demonstrating improvement over prior iteration.
- **h-main > h-ablation**: Confirming inline computation adds value beyond memoization alone.
- All covering tests pass. Bit-identical results for all tested n values.

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Do NOT add external dependencies (lru_cache is from Python stdlib `functools`).
- All changes confined to `sympy/ntheory/partitions_.py`.
- Python 3.11 compatibility patches must be applied first.

## Prior Knowledge

- **RP-5** (iter-3, high confidence): Dedekind sum O(log j) + symmetry + float64 yields 22.8x. This is the starting point.
- **RP-2** (iter-1): `math.gcd` 9x faster than `igcd` — already applied.
- All previous optimizations (RP-1 through RP-5) are incorporated in the iter-3 baseline.
- Profiling of iter-3 code shows `_dedekind_sum` at 41ms tottime (37,715 calls), with 73% redundancy.
- Prior iter-4 attempt found precomputation with memoization gives no benefit over memoization alone — precomputation overhead negates any lookup savings.
