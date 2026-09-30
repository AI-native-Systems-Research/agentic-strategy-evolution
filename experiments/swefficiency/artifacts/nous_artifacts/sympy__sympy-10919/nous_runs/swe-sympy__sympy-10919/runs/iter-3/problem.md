# Problem Framing — Iteration 3

## Research Question

How can we further reduce the runtime of `npartitions(10^6)` in `sympy/ntheory/partitions_.py` beyond the iter-1/iter-2 optimizations (frac_table precomputation, math.gcd, small-int inner sum, h/j-h cosine symmetry, NumPy vectorization), while preserving bit-identical results and keeping the covering tests green?

Key source files:
- `sympy/ntheory/partitions_.py:43` — `_a(n, j, prec)`: the inner sum function (dominant bottleneck).
- `sympy/ntheory/partitions_.py:122` — `npartitions(n)`: the outer HRR loop with dynamic precision reduction.

## System Interface

- **Build command:** None (pure Python library). Requires: `pip install mpmath pytest`.
- **CLI flags:** `PYTHONPATH=$PWD python /tmp/workload.py` to run the benchmark.
- **Tests:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`
- **Code evidence:**
  - `sympy/ntheory/partitions_.py:43` — `_a()` definition (optimization target)
  - `sympy/ntheory/partitions_.py:122` — `npartitions()` outer loop
  - `sympy/ntheory/partitions_.py:148` — dynamic precision: `p = bitcount(abs(to_int(d))) + 50`
  - Python 3.11 compat patches needed: `sympy/core/basic.py:3`, `sympy/core/function.py:107`, `sympy/ntheory/egyptian_fraction.py:6`, `sympy/plotting/plot.py:27-28`

## Baseline Command

```bash
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

With iter-1 code (frac_table + math.gcd, already in worktree):
- Exit code: 0
- Output: `Mean: 0.496s`, `Std Dev: 0.009s`
- Reference baseline: 1.3901s
- Speedup vs reference: 1.3901 / 0.496 ≈ 2.80x

## Experimental Conditions

### h-main: Dedekind sum O(log j) + cosine symmetry + float64 fast path

Three combined optimizations to `_a()` and `npartitions()`:

1. **Dedekind sum O(log j) for T(h,j)**: Replace the O(j) inner k-loop with `_T(h,j)` computed via the Dedekind sum reciprocity law. The identity `T(h,j) = j^2 * s(h,j) + j^2*(j-1)/4` where `s(h,j)` is the Dedekind sum computable in O(log j) via continued-fraction-like recursion. This reduces 2.9M inner loop iterations to O(log j) per coprime h.

2. **h/j-h cosine symmetry** (from iter-2): `cos(angle(h)) = cos(angle(j-h))` halves the number of `mpf_cos` evaluations from 18,055 to ~9,028.

3. **Float64 fast path**: For outer-loop terms q where dynamic precision p ≤ 64 bits (q ≥ ~94 for n=10^6), compute both `_a` and `_d` entirely in hardware float64. This eliminates ~73% of `mpf_cos` calls (6,612 out of 9,028) and 62% of `_d` mpf computations (150 out of 243). The accumulated float sum is converted to mpf once and added to the precision sum.

**Measured:** Mean 0.0613s → speedup = 22.7x over reference.

### h-ablation: Dedekind + symmetry only (no float64 path)

Same as h-main but without optimization #3 (float64 fast path). The `npartitions()` function is unchanged from the original; only `_a()` is modified with Dedekind sum and symmetry.

**Purpose:** Isolate the contribution of the float64 fast path.

**Measured:** Mean 0.1278s → speedup = 10.9x over reference.

## Success Criteria

- h-main achieves > 15x speedup over reference baseline (1.3901s)
- h-ablation achieves > 8x speedup over reference baseline
- Both produce bit-identical results to the original for all test cases
- Covering tests pass: `python -m pytest -q sympy/ntheory/tests/test_partitions.py`

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files
- Covering tests must remain green
- Results must be bit-identical to the original algorithm
- No external dependencies beyond what's already available (mpmath, math)

## Prior Knowledge

- **RP-1** (iter-1): frac_table precomputation gives 2-3x. Superseded by Dedekind sum.
- **RP-2** (iter-1): math.gcd 9x faster than igcd. Still applied.
- **RP-3** (iter-2): Small-int accumulation + cosine symmetry gives 6-8x. Dedekind sum replaces the small-int accumulation with an even faster O(log j) computation.
- **RP-4** (iter-2): NumPy batch gives ~1.2x additional. No longer needed — Dedekind sum is faster than NumPy for all j values (24ms vs 25ms for q=94..243).
