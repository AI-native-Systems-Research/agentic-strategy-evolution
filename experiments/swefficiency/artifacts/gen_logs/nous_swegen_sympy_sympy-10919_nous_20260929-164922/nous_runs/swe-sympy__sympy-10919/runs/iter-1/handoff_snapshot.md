# Handoff: npartitions HRR Optimization (Iteration 1)

## Goal

Optimize `npartitions(10**6)` in `sympy/ntheory/partitions_.py` from ~1.29s to <0.05s by rewriting the `_a` inner-sum function with four synergistic improvements: memoized Dedekind sums, Kloosterman symmetry, hardware float fast path, and gmpy2 MPFR cos.

## Key Discoveries

1. **Dominant bottleneck is `_a` (~90% of runtime)**: The original `_a` function uses an O(j) inner loop to compute Dedekind sums for each coprime h (O(j^2) total per outer iteration). For n=10^6 with M=244 outer iterations, this is extremely expensive.

2. **Dedekind sum reciprocity gives O(log k)**: The Dedekind sum s(h,k) satisfies a reciprocity law: 12k·s(h,k) can be computed recursively via `_d_dedekind(h,k) = (h²+k²+1-3hk - k·_d_dedekind(k%h,h)) / h`. With `@lru_cache`, repeated lookups across outer iterations are O(1).

3. **Precision drops from 4148 to 53 bits over 127 iterations**: At q=127, precision drops below 53, enabling hardware floats. The remaining 117 iterations (q=127-243) can use `math.cos` and `math.gcd` (C builtins) instead of arbitrary-precision functions.

4. **gmpy2 MPFR cos is 1.5-2.2x faster than mpmath cos_sin_basecase**: Benchmarked at precisions 100-2000 bits. gmpy2 is available in the conda environment. At prec=200 (a common level mid-computation), gmpy2.cos is 2.2x faster.

5. **Kloosterman symmetry halves the inner loop**: D(j-h,j) = -D(h,j) means we only need h from 1 to (j-1)//2 and multiply by 2.

6. **Early termination is NOT safe**: Terms become individually negligible around q=150 but can collectively shift the final integer. M=180 works for n=10^6 but M=160 fails (off by 1). The current M formula must be preserved.

7. **Verified final performance: 0.0227s mean** (57x speedup from 1.29s baseline). All correctness tests pass for n=0..5, 25, 100, 200, 1000, 2000, 10000, 100000.

## System Interface

- **Build:** No build step (pure Python).
- **Run baseline:** `docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python /tmp/workload.py"`
- **Run tests:** `docker exec swegen_sympy_sympy-10919_nous bash -lc "cd /testbed && source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && python -m pytest -q sympy/ntheory/tests/test_partitions.py"`
- **Output format:** Workload prints `Mean: <float>` and `Std Dev: <float>` to stdout.
- **Baseline result:** Mean: 1.2888s (original code), 0.0227s (optimized, verified in /tmp/verify_final.py).

## Code Map

- `sympy/ntheory/partitions_.py:12` — `_a(n, j, prec)`: Inner Kloosterman-type sum. THE optimization target. Original uses O(j) Dedekind sum inline loop + `mpf_cos` + `igcd`. Check here if correctness fails.
- `sympy/ntheory/partitions_.py:22-34` — The O(j) Dedekind sum loop inside `_a`. This is the specific code to replace with `_d_dedekind` calls.
- `sympy/ntheory/partitions_.py:35` — `mpf_cos` call. Replace with gmpy2.cos (high prec) or math.cos (low prec).
- `sympy/ntheory/partitions_.py:39` — `_d(n, j, prec, sq23pi, sqrt8)`: Sinh term. NOT modified in this iteration. Check here if _d contributes unexpected overhead.
- `sympy/ntheory/partitions_.py:55-95` — `npartitions(n)`: Main loop. Unchanged except that it calls the new `_a`.
- `sympy/ntheory/partitions_.py:90` — Dynamic precision reduction. Critical invariant: `p = bitcount(abs(to_int(d))) + 50`. Do not change.
- `sympy/core/numbers.py` — `igcd` function. Will be replaced by `math.gcd` in the import.

## Code Targets

### h-main: Rewrite `_a` function

**File:** `sympy/ntheory/partitions_.py`

**Changes to make:**

1. **Add imports** (top of file): `import math`, `from functools import lru_cache`, `import gmpy2`, `from mpmath.libmp.libmpf import round_fast as rnd`. Remove `from sympy.core.numbers import igcd`.

2. **Add `_d_dedekind` function** (before `_a`): Recursive Dedekind sum with `@lru_cache(maxsize=None)`. Base cases: k<=2 returns 0, h==0 returns 0, h==1 returns (k-1)*(k-2). Recursive case: `(h²+k²+1-3hk - k*_d_dedekind(k%h, h)) // h`.

3. **Replace `_a` body**: Three paths:
   - `j==1`: return `fone` (unchanged)
   - `prec<=53`: Float path using `math.cos`, `math.gcd`, Kloosterman symmetry (half range). Convert result via `from_man_exp`.
   - `prec>53`: gmpy2 MPFR path using `gmpy2.cos`, `math.gcd`, Kloosterman symmetry. Set `gmpy2.get_context().precision = prec + 10`. Convert result to mpmath mpf via `from_man_exp(int(cos_sum * gmpy2.mpfr(1 << wp)), -wp, prec, rnd)`.

**WHY this location:** The `_a` function is the dominant bottleneck (90%+ runtime). The four changes are synergistic and all apply to this single function.

**Reference implementation:** `/tmp/verify_final.py` in the container contains the complete verified implementation.

## What I Tried That Didn't Work

1. **Early loop termination** (`break` when `to_int(d)==0`): Breaks correctness. P(2000) off by 1, P(10000) off by 2, P(100000) off by 9. The individually-negligible late terms collectively shift the final integer.

2. **Reducing M factor**: M=180 works for n=10^6 but M=160 fails. The boundary varies with n. Not safe without a tighter theoretical bound. The 0.24 factor must be preserved.

3. **Full gmpy2 rewrite of `_d` function**: gmpy2 is SLOWER than mpmath at high precision (4000 bits: 0.7x speed). Only faster at low precision (<1000 bits). Since _d is only 10% of runtime and the high-precision iterations dominate, the conversion overhead isn't worth it.

4. **gmpy2 global context contamination**: Setting `gmpy2.get_context().precision` to low values can affect subsequent mpmath operations that use gmpy2 internally. Must be careful about context management. The proposed code sets precision per-call in `_a`.

## What I Excluded and Why

1. **`_d` function optimization**: Only ~10% of runtime. gmpy2 is slower than mpmath at high precision. Would add complexity for small gain. Save for iteration 2 if needed.

2. **Precomputed coprime lists**: The 14641 `math.gcd` calls cost ~0.003s (12% of optimized time). Replacing with precomputed Euler totient sieve could save ~0.002s. Marginal gain; save for iteration 2.

3. **Caching `npartitions` results**: Would game the benchmark (10 repeated calls) but isn't a genuine algorithmic improvement.

4. **Reducing initial precision**: The `prec = int(pbits*1.1 + 100)` safety margin is conservative but changing it risks correctness for edge cases.

## Evolution of Thinking

Started by exploring the profiling data. Initially thought the bottleneck was cos computation (cos_sin_basecase). Realized the REAL bottleneck was the O(j) Dedekind sum computed inline for each coprime h, creating O(j^2) work. The Dedekind reciprocity + caching was the transformative change (reducing O(j^2) to O(j log j) amortized). The float path and gmpy2 cos are complementary optimizations that address the remaining trig computation cost.

Discovered early termination is unsafe through empirical testing — a subtle point that a purely theoretical analysis might miss. The HRR formula terms are individually negligible but collectively significant for exact integer arithmetic.

## Current Status

- **Validated:** Complete optimized implementation passes all correctness tests (n=0-100000). Performance: 0.0227s mean (57x speedup). Covering tests pass.
- **Uncertain:** Whether gmpy2 context management has side effects on other sympy modules. The proposed code sets precision per-call, which should be safe.
- **Suggested next:** (1) Ablation study to quantify individual contribution of each optimization. (2) Precomputed coprime lists to eliminate remaining gcd overhead. (3) _d function optimization at low precision using gmpy2.

## Warnings & Constraints

1. **gmpy2 context is global**: `gmpy2.get_context().precision = wp` affects ALL subsequent gmpy2/MPFR operations in the process. The `_a` function sets this per-call, which is correct since the outer loop calls `_a` with decreasing precision. But if other code runs concurrently, there could be interference.

2. **Python 3.6 environment**: The container uses Python 3.6. `math.gcd` exists in 3.6. `@lru_cache(maxsize=None)` exists. `gmpy2` is installed. All proposed code is 3.6-compatible.

3. **`from_man_exp` conversion**: The gmpy2-to-mpmath conversion `int(cos_sum * gmpy2.mpfr(1 << wp))` creates a large integer. This is correct but could be slow for very high precision. For the precision range in this problem (50-4200 bits), it's negligible.

4. **The `igcd` import removal**: The original code imports `igcd` from `sympy.core.numbers`. The optimized code uses `math.gcd` instead. Make sure to remove the `igcd` import to avoid unused-import warnings.
