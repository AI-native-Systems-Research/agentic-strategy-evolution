# Problem Framing — Iteration 2: Further Optimization of HRR Inner Sum

## Research Question

Given that iteration 1 established the frac_table precomputation approach (RP-1) yielding ~2.8x speedup on npartitions(10^6), can we achieve further speedup by: (a) replacing big-integer inner-loop arithmetic with small-integer operations, (b) exploiting the h/j-h cosine symmetry to halve evaluations, and (c) using NumPy vectorized batch computation for the small-integer sums?

The mechanism is implemented in `sympy/ntheory/partitions_.py:12` (the `_a()` function), which computes the Kloosterman-like inner sum of the Hardy-Ramanujan-Rademacher formula.

## System Interface

- **Build command:** None (pure Python). Dependencies: `mpmath`, `pytest`, `numpy`.
- **CLI flags:** `PYTHONPATH=$PWD python /tmp/workload.py` — prints `Mean:` and `Std Dev:`.
- **Test command:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`
- **Code evidence:**
  - `sympy/ntheory/partitions_.py:12` — `_a(n, j, prec)`: inner sum function (optimization target)
  - `sympy/ntheory/partitions_.py:23` — `frac_table` listcomp (iter-1 optimization, to be replaced)
  - `sympy/ntheory/partitions_.py:27-33` — inner k-loop with big-int `k * frac_table[(h*k) % j]`
  - `sympy/ntheory/partitions_.py:35-36` — `from_man_exp` + `mpf_cos` call per coprime h
  - `sympy/ntheory/partitions_.py:56` — `npartitions(n)` outer loop calling `_a` 243 times for n=10^6
  - `sympy/ntheory/partitions_.py:95` — dynamic precision reduction `p = bitcount(abs(to_int(d))) + 50`
- **Output:** `Mean: <seconds>` on stdout (lower is better). Speedup = 1.3901 / mean.

## Baseline Command

```bash
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

Ran the workload with the iter-1 optimized code (frac_table + math.gcd):
- **Exit code:** 0
- **Mean:** 0.465s (on this machine)
- **Speedup vs reference:** 1.3901 / 0.465 ≈ 2.99x
- **Tests:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py` → 1 passed

Profiling breakdown of `_a()` at baseline (0.967s total profile time):
- `_a` self-time: 0.561s (inner k-loop big-int arithmetic: `k * frac_table[...]`)
- `mpf_cos`: 0.273s (18,055 calls across all coprime h values)
- `from_man_exp`: 0.096s
- `mpf_add`: 0.064s
- `frac_table` listcomp: 0.004s

## Experimental Conditions

### h-main: Small-Int Sum + Symmetry Halving + NumPy Vectorization

Three combined optimizations to the `_a()` function:

1. **Small-integer inner sum**: Replace big-integer arithmetic `k * frac_table[(h*k) % j]` (where frac_table entries are ~4148-bit numbers) with small-integer arithmetic `T += k * ((h*k) % j)` (all values < 243^2 = 59049). One big-int multiply `T * one // j` at the end per coprime h replaces O(j) big-int multiplies in the inner loop. Error analysis confirms the approximation error is negligible: max ~15 bits out of 4148-bit precision, verified experimentally to produce bit-identical npartitions results.

2. **h/j-h cosine symmetry**: For gcd(h,j)=1, the cosine argument angle(j-h) = -(angle(h) + 2nπ). Since n is integer, cos(angle(j-h)) = cos(angle(h)). Proof verified experimentally for j=7,13 and mathematically via: frac((j-h)k/j) = 1-frac(hk/j), leading to g_raw(j-h) = -g_raw(h), then angle(j-h) = -(angle(h) + 2nπ). This halves the number of mpf_cos calls (from 18,055 to ~9,028) and inner loop iterations.

3. **NumPy batch computation**: For j > 50, compute all T values for all coprime h simultaneously using a 2D array operation: `residues = (hs[:, None] * ks[None, :]) % j; Ts = (residues * ks).sum(axis=1)`. This eliminates Python loop overhead for the ~1.46M small-int inner loop iterations. For j ≤ 50, Python loop is used (numpy overhead exceeds benefit).

Probe result: 0.142-0.168s (speedup 8.3-9.8x over reference baseline). Bit-identical results for all test values (n=0..10^6).

### h-ablation: Small-Int Sum + Symmetry Halving (Pure Python, No NumPy)

Same as h-main but without the NumPy vectorization (optimization 3). Pure Python inner loop for all j values.

Probe result: 0.212s (speedup 6.56x over reference baseline).

Purpose: Isolate the contribution of NumPy vectorization. The difference between h-main and h-ablation quantifies the NumPy benefit.

## Success Criteria

- **h-main:** Speedup > 5x over reference baseline (1.3901s) with tests passing and identical results. Probed at ~8-10x.
- **h-ablation:** Speedup > 4x over reference baseline with tests passing. Probed at ~6.5x.
- **h-main > h-ablation:** NumPy vectorization provides measurable additional speedup (probed at ~1.3x).

## Constraints

- Must not edit `/tmp/workload.py` or any test files.
- All covering tests must pass: `python -m pytest -q sympy/ntheory/tests/test_partitions.py`.
- Results must be bit-identical to original (verified for n=0..100000 and n=10^6).
- Python 3.11 compatibility patches must be applied (4 files with deprecated imports).

## Prior Knowledge

- **RP-1:** Frac_table precomputation gives 2-3x speedup. This iteration builds on RP-1 by replacing the frac_table approach entirely with small-int arithmetic.
- **RP-2:** math.gcd is 9x faster than igcd. Already applied in iter-1, retained in iter-2.
- **Iter-1 dead ends:** Weight-grouping (building `weights[r]` array) was slower. Incremental modular tracking (hk += h; if hk >= j: hk -= j) had similar performance. These are not retried.
