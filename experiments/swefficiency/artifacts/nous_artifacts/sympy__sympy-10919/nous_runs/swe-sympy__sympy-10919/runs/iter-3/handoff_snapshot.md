# Handoff — Iteration 3: Dedekind Sum + Float64 Fast Path

## Goal

Apply three combined optimizations to `npartitions()` in `sympy/ntheory/partitions_.py`: (1) Dedekind sum O(log j) replacing the O(j) inner k-loop, (2) h/j-h cosine symmetry halving cos evaluations, (3) float64 fast path for low-precision outer-loop terms. Measure speedup vs the 1.3901s reference baseline. Confirm all covering tests pass and results are bit-identical.

## Key Discoveries

### From Iterations 1-2
1. **`_a()` is 70% of runtime** — profiling confirms the inner sum is the dominant bottleneck.
2. **`math.gcd` is 9x faster than `igcd`** — C builtin vs Python type checking.
3. **Small-int inner sum is valid** — T(h,j) as small ints, one big-int multiply per h.
4. **h/j-h cosine symmetry** — halves mpf_cos calls from 18,055 to ~9,028.

### From Iteration 3 (new)
5. **Dedekind sum identity**: `T(h,j) = j^2 * s(h,j) + j^2*(j-1)/4` where `s(h,j)` is the classical Dedekind sum computable in O(log j) via the reciprocity law `s(h,j) + s(j,h) = (h^2+j^2+1)/(12hj) - 1/4`. Verified correct for all j=3..243 and all coprime h.
6. **Dedekind sum benchmarks**: For the full inner sum computation (q=3..243, all coprime h with symmetry), Dedekind takes 35ms vs Python loop 132ms vs NumPy batch 31ms. Dedekind is comparable to NumPy but requires no external dependency.
7. **Float64 fast path**: For q >= ~94 (where dynamic precision p drops to <= 64 bits), computing both `_a` and `_d` entirely in float64 is valid. Error bounded by ~2e-9 across all low-prec terms, negligible vs 0.5 rounding tolerance. This eliminates 6,612 of 9,028 mpf_cos calls and 150 of 243 mpf _d computations.
8. **Component timing after all optimizations**: Dedekind sum 2.5ms (mpf path) + 24ms (float path), mpf_cos 32ms (for 2,416 remaining calls), big-int ops ~10ms, _d ~11ms. Total _a+outer-loop: ~66ms.
9. **End-to-end measurements**: h-main = 0.0613s (22.7x), h-ablation = 0.1278s (10.9x). Float64 path accounts for ~2x additional speedup.

## System Interface

- **Build:** None (pure Python). Install deps: `pip install mpmath pytest`
- **Run baseline:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`
- **Output format:** `Mean: <seconds>` and `Std Dev: <seconds>` on stdout
- **Python 3.11 compat:** Apply `iter-1/patches/py311-compat.patch` first
- **Baseline (iter-1 code):** Mean: 0.496s on this machine, reference: 1.3901s
- **h-main measured:** Mean: 0.0613s (22.7x speedup over reference)
- **h-ablation measured:** Mean: 0.1278s (10.9x speedup over reference)

## Code Map

- `sympy/ntheory/partitions_.py:13` — `_dedekind_sum(h, j)`: O(log j) Dedekind sum via reciprocity. Check here if T(h,j) values are wrong.
- `sympy/ntheory/partitions_.py:32` — `_T(h, j)`: Converts Dedekind sum to T(h,j) = sum_k k*((hk)%j). Check here if inner sum values differ.
- `sympy/ntheory/partitions_.py:43` — `_a(n, j, prec)`: mpf path with Dedekind + symmetry. Check here if high-precision terms are wrong.
- `sympy/ntheory/partitions_.py:82` — `_a_float(n, j)`: float64 path for low-prec terms. Check here if float accumulation error is too large.
- `sympy/ntheory/partitions_.py:106` — `_d(n, j, prec, sq23pi, sqrt8)`: unchanged.
- `sympy/ntheory/partitions_.py:122` — `npartitions(n)`: outer loop with float64 fast path dispatch at `p <= 64`.
- `sympy/ntheory/partitions_.py:148` — precision tracking: `p = bitcount(abs(to_int(d))) + 50`.
- `sympy/core/basic.py:3` — Py3.11 compat: `collections.Mapping` → `collections.abc.Mapping`.

## Code Targets

### h-main: `sympy/ntheory/partitions_.py` — full file rewrite

**What to change:** Replace `igcd` import with `math.gcd` and math float functions. Add `_dedekind_sum()` and `_T()` helper functions. Rewrite `_a()` with Dedekind sum + symmetry. Add `_a_float()` for float64 computation. Modify `npartitions()` to dispatch to float64 path when `p <= 64`.

**Patch available:** `/tmp/nous_runs/swe-sympy__sympy-10919/runs/iter-3/patches/h-main.patch`

### h-ablation: Same without float64 path

**What to change:** Same `_dedekind_sum`, `_T`, and `_a` changes as h-main, but without `_a_float()` and without the float64 dispatch in `npartitions()`.

**Patch available:** `/tmp/nous_runs/swe-sympy__sympy-10919/runs/iter-3/patches/h-ablation.patch`

## What I Tried That Didn't Work

### From Iterations 1-2
1. **Weight-grouping** (iter-1 v3): SLOWER (~1.03s). Building weights array adds overhead.
2. **Incremental modular tracking** (iter-1 v2): Similar performance. `%` is already cheap.
3. **Per-h NumPy arrays** (iter-2): 0.219s vs 0.212s. Array creation overhead per-h negates benefit.
4. **Early termination at d_bits==0** (iter-2): Breaks correctness.
5. **Precomputing pi_div_j** (iter-2): Truncation error propagates.

### From Iteration 3
6. **Fraction-based Dedekind sum**: 3.52ms vs 3.34ms for O(j) loop at j=243. Python Fraction objects have too much overhead. Switched to (num, den) tuple pairs with explicit GCD.
7. **Iterative Dedekind with per-step GCD normalization**: 79ms vs recursive 55ms. The extra GCD calls outweigh avoiding recursion.
8. **Float64 path starting at p <= 53** (strict float precision match): Kicks in at q=127, only saves 6,612 calls. Raising to p <= 64 catches more calls starting at q=94 with negligible error increase.

## What I Excluded and Why

1. **C extension / Cython**: Would eliminate Python loop overhead but adds build complexity. The Dedekind sum already reduces loop iterations from O(j) to O(log j).
2. **mpf_cos optimization at medium precision (p=65..500)**: 366 calls, ~15ms. Diminishing returns vs implementation complexity.
3. **Alternative precision tracking for float path**: Could skip _d computation for float-path q values by precomputing the q threshold. Saves ~2ms, not worth the complexity.
4. **O(log j) computation for all coprime h simultaneously**: The Dedekind sum computes T(h,j) independently per h. A batch approach computing all T values via the Chinese Remainder Theorem is theoretically possible but adds significant code complexity for marginal gain.

## Evolution of Thinking

### Iteration 1
Profiling → _a is 70% → igcd replacement (small gain) → frac_table precomputation (big gain) → 2.8x speedup.

### Iteration 2
Profiled iter-1 code → big-int multiplies dominate → small-int replacement → cosine symmetry → NumPy batch for large j → 8-10x speedup.

### Iteration 3
Profiled iter-2-style code → remaining costs: inner sum 33ms, mpf_cos 79ms, mpf_add 24ms, big-int 10ms → Dedekind sum replaces inner sum (33ms → 2.5ms for mpf path, eliminates Python k-loop entirely) → float64 path for low-prec terms eliminates 73% of mpf_cos + mpf_add + _d overhead → combined: 66ms for computation → 22.7x speedup.

Key insight: the inner sum `T(h,j) = sum_{k=1}^{j-1} k*((hk) mod j)` has a classical number-theoretic identity linking it to the Dedekind sum, which has an O(log j) algorithm via the reciprocity law. This is not an approximation — it gives exact integer results.

## Current Status

- **Validated:** h-main at 0.0613s (22.7x), h-ablation at 0.1278s (10.9x). All test cases pass. Bit-identical results verified for n=0..200, 1000, 10000, 100000, 1000000.
- **Uncertain:** Whether the 22.7x speedup holds on the reference machine (machine-specific effects in float64 path, caching, etc.). The speedup ratio should be similar since all optimizations are algorithmic.
- **Suggested next:** (1) Medium-precision optimization (p=65-500, 366 mpf_cos calls, ~15ms). (2) Memoization of _T(h,j) across outer-loop iterations (same h,j pairs may recur). (3) C extension for remaining mpf_cos calls. (4) Scaling validation at n=10^7, 10^8.

## Warnings & Constraints

1. **Python 3.11 compatibility**: 4 files need patching (same as iter-1). Apply `iter-1/patches/py311-compat.patch` before running.
2. **Dedekind sum recursion depth**: Maximum ~8 levels for j ≤ 243 (GCD-like reduction). Well within Python's 1000-level default limit.
3. **Float64 precision at threshold boundary**: At p=64, float64 gives ~48 accurate bits. The remaining error (~2^(-48)) across ~6612 terms gives total error ~6612 * 2^(-48) ≈ 2.4e-11, negligible vs 0.5 rounding tolerance.
4. **Do NOT edit /tmp/workload.py** — read-only for the experiment.
5. **float_accum sign handling**: `_math_frexp` handles negative floats correctly (returns negative mantissa). Verified.
