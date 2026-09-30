# Problem Framing — Iteration 5

## Research Question

How can we further reduce `npartitions(10^6)` runtime beyond iter-4's 25.7x speedup (memoized Dedekind sum + inline computation + float64 fast path), by optimizing the remaining bottleneck: `mpf_cos` calls in the high-precision path?

Profiling of iter-4 code reveals that `mpf_cos` consumes ~40% of the remaining computation time (1328 calls totalling ~18ms), with two specific inefficiencies:
1. The q=2 term computes `cos(-n*π)` at 3728-bit precision via `mpf_cos`, costing ~3.4ms, when the analytical result is simply `(-1)^n` (`partitions_.py:140-146`).
2. All mpf-path terms pass angles of magnitude ~10^6 radians to `mpf_cos`, which internally performs expensive `mod_pi2` reduction at arbitrary precision (`mpmath/libmp/libelefun.py:1288`). Pre-reducing angles mod 2π in integer arithmetic eliminates this overhead, saving ~38% of `mpf_cos` time.

Reference source files:
- `sympy/ntheory/partitions_.py:56` — `npartitions()` main function
- `sympy/ntheory/partitions_.py:14` — `_dedekind_sum()` with `@lru_cache`
- `sympy/ntheory/partitions_.py:40` — `_d()` sinh/cosh computation
- `mpmath/libmp/libelefun.py:1403` — `mpf_cos` entry point
- `mpmath/libmp/libelefun.py:1288` — `mod_pi2` angle reduction (the bottleneck)

## System Interface

- **Build command:** None (pure Python). Apply py3.11 compat patch before running tests.
- **CLI flags relevant to the experiment:**
  - `PYTHONPATH=$PWD python /tmp/workload.py` — measures npartitions(10^6) mean over 10 forked trials
  - `python -m pytest -q sympy/ntheory/tests/test_partitions.py` — covering test suite
- **Code evidence:**
  - `partitions_.py:140-146` — q=2 mpf path: computes `cos(-n*π)` via fixed-point arithmetic and `mpf_cos` at p=3728 bits
  - `partitions_.py:148-164` — mpf inner loop: computes angle `g` then calls `mpf_cos(from_man_exp(g, -p), p)`
  - `libelefun.py:1288-1322` — `mod_pi2`: reduces angle modulo π/2 using high-precision division, dominant cost for large angles
- **Native output:** stdout: `Mean: <seconds>`, `Std Dev: <seconds>`

## Baseline Command

```bash
cd /testbed && git apply /tmp/nous_runs/swe-sympy__sympy-10919/runs/iter-1/patches/py311-compat.patch 2>/dev/null; git apply /tmp/nous_runs/swe-sympy__sympy-10919/runs/iter-4/patches/h-main.patch && PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

Ran iter-4 h-main code (the current best): `PYTHONPATH=$PWD python /tmp/workload.py`
- Exit code: 0
- Output: `Mean: 0.05611` (25.9x vs 1.3901 reference), Std Dev: 0.006
- Tests: `1 passed, 72 warnings` (all green)
- Result: bit-identical to original `npartitions(10^6)` (last 20 digits: `15630003467104673818`)

## Experimental Conditions

### h-main: Combined mpf_cos optimization package
Changes from iter-4 baseline:
1. **Analytical q=2**: Replace the q=2 mpf-path computation (lines 140-146) with `a = fone if n % 2 == 0 else mpf_neg(fone)`. Since cos(-nπ) = (-1)^n exactly, this avoids a 3.4ms mpf_cos call at 3728-bit precision.
2. **Angle pre-reduction mod 2π**: Before each `mpf_cos` call in the inner loop (line 161), insert `g = g % two_pi` where `two_pi = pi_fixed(p) << 1`. This reduces ~10^6-radian angles to [0, 2π), eliminating the expensive `mod_pi2` reduction inside `mpf_cos`. Measured: saves 38% of mpf_cos time (17.6ms → 10.8ms).
3. **mpf_shift doubling**: Replace the two `mpf_add(a, cos_val, p)` calls per coprime h (lines 163-164) with `mpf_add(a, mpf_shift(cos_val, 1), p)`. mpf_shift is effectively free (tuple exponent increment). Measured: saves ~40% of accumulation time (1.63ms → 0.96ms).
4. **Local variable caching**: Cache mpf_cos, mpf_add, mpf_mul, mpf_shift, from_man_exp, pi_fixed, bitcount, to_int as local variables to avoid global lookups in the hot loop.
5. **Loop-invariant hoisting**: Precompute `q_sq = q*q` and `q_sq_qm1 = q_sq*(q-1)` outside the inner h-loop.

### h-ablation: Analytical q=2 only
Changes from iter-4 baseline:
- Apply only optimization (1) from above: analytical q=2 replacement.
- No angle pre-reduction, no mpf_shift, no local variable caching.
- This isolates the contribution of the single largest optimization.

## Success Criteria

- **h-main**: Speedup > 29x (improvement over iter-4's 25.7x) with all covering tests passing and bit-identical results. Expected: ~31x based on probes (0.045s workload mean).
- **h-ablation**: Speedup > 27x (measurable improvement from analytical q=2 alone), but less than h-main.
- **Correctness**: `npartitions(10^6)` returns the same integer for all conditions. Tests pass (`1 passed`).

## Constraints

- Do NOT edit `/tmp/workload.py` or test files.
- Edit only library source under `sympy/`.
- The py3.11 compat patch must be applied before running tests.
- The `mpf_neg` and `mpf_shift` imports must be added to the import line from `mpmath.libmp`.
- Angle pre-reduction introduces a tiny rounding difference (~10^-560) in intermediate mpf_cos values due to integer modular arithmetic vs. mpf's internal mod_pi2. This is negligible relative to the 0.5 rounding tolerance for the final integer result.

## Prior Knowledge

**Active principles that apply:**
- **RP-5**: Dedekind sum + float64 fast path provides the base 22.8x speedup. Iter-5 builds on this by optimizing the mpf_cos calls that remain in the high-precision path.
- **RP-6**: @lru_cache memoization + inline computation provides the 25.7x base. Iter-5 targets the mpf_cos bottleneck that RP-6's inline approach still uses.
- **RP-2**: math.gcd replacement is already active and contributes to the float-path speed.

**Dead ends from previous iterations** (not repeated):
- Fixed-point cos to replace mpf_cos: only 1.15x faster at specific precisions, slower elsewhere (iter-4).
- NumPy batch for T computation: array creation overhead dominates (iter-4).
- Fixed-point accumulation: tuple unpacking overhead negates gains (iter-4).
- Iterative Dedekind sum: can't share work across calls (iter-4).
