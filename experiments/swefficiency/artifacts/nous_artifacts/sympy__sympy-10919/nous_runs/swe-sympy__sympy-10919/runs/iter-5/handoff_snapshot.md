# Handoff — Iteration 5: mpf_cos Optimization Package

## Goal

Apply three orthogonal optimizations to the mpf_cos bottleneck in the high-precision HRR path: (1) analytical q=2, (2) angle pre-reduction mod 2π, (3) mpf_shift doubling. Measure speedup vs the 1.3901s reference baseline. Confirm all covering tests pass and results are bit-identical.

## Key Discoveries

### From Iterations 1-4 (carried forward)
1. **`_a()` was 70% of original runtime** — now eliminated via Dedekind sum + inline computation.
2. **`math.gcd` is 9x faster than `igcd`** — C builtin vs Python type checking.
3. **Dedekind sum identity**: `T(h,j) = j^2 * s(h,j) + j^2*(j-1)/4` gives O(log j) computation.
4. **Float64 fast path**: For q >= 94 (p <= 64), hardware floats replace mpf. Accounts for 2.2x additional speedup.
5. **h/j-h cosine symmetry**: Halves mpf_cos calls.
6. **@lru_cache memoization**: Eliminates 73% of redundant _dedekind_sum calls.
7. **Inline T computation**: Avoids 15ms precomputation loop overhead.

### From Iteration 5 (new)
8. **mpf_cos is 40% of remaining time**: 1328 calls total, 18ms out of ~45ms single-run. The cost is concentrated at high-precision terms: q=2 at p=3728 costs 3.4ms alone; q=3 at p=1878 costs 0.18ms.
9. **Angles are ~10^6 radians**: For n=10^6, the angles passed to mpf_cos are approximately `-2nh/q * π/q ≈ -10^6` radians. This makes mod_pi2 (which divides by π/2 at full precision) the dominant cost inside mpf_cos.
10. **Analytical q=2 saves 3.4ms**: cos(-nπ) = (-1)^n. For n=10^6 (even), this is exactly 1. Replacing the mpf_cos call with `fone` eliminates the most expensive single operation.
11. **Angle pre-reduction saves 7ms**: `g = g % (pi_fixed(p) << 1)` reduces the angle to [0, 2π) in integer arithmetic. After reduction, mod_pi2 inside mpf_cos only needs to handle angles < 2π (quotient 0-3), not ~10^6 radians. Measured: mpf_cos time drops from 17.6ms to 10.8ms (38% reduction).
12. **Pre-reduction rounding**: The reduced angle differs from the unreduced by ~10^-560 (at 1878-bit precision). This is negligible; the final integer result is bit-identical.
13. **mpf_shift(cos_val, 1) saves 0.7ms**: Replaces two mpf_add calls with one shift+add. mpf_shift just increments the tuple's exponent field.
14. **Combined improvement**: Cold cache ~35ms (vs 54ms original), warm cache ~24ms (vs 30ms). Workload mean: 0.045s → 31x speedup.

## System Interface

- **Build:** None (pure Python). Install deps: `pip install mpmath pytest`
- **Run baseline:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/ntheory/tests/test_partitions.py`
- **Output format:** `Mean: <seconds>` and `Std Dev: <seconds>` on stdout
- **Python 3.11 compat:** Apply `iter-1/patches/py311-compat.patch` first
- **Iter-4 baseline:** Mean: 0.0561s (24.8x) on this machine
- **h-main measured:** Mean: 0.0446s (31.2x speedup over reference)
- **h-ablation measured:** Mean: 0.0483s (28.8x speedup over reference)

## Code Map

- `sympy/ntheory/partitions_.py:14` — `_dedekind_sum(h, j)`: recursive O(log j) Dedekind sum with `@lru_cache(maxsize=None)`. Check here if cache memory grows unexpectedly.
- `sympy/ntheory/partitions_.py:40` — `_d(n, j, prec, sq23pi, sqrt8)`: unchanged sinh term.
- `sympy/ntheory/partitions_.py:57` — `npartitions(n)`: main function. Float path starts at line ~109, mpf path at line ~131.
- `sympy/ntheory/partitions_.py:5-6` — mpf imports: must include `mpf_shift, mpf_neg` for iter-5.
- `sympy/core/basic.py:3` — Py3.11 compat: `collections.Mapping` → `collections.abc.Mapping`.
- `mpmath/libmp/libelefun.py:1288` — `mod_pi2`: the expensive angle reduction inside mpf_cos. This is where the savings come from.

## Code Targets

### h-main: `sympy/ntheory/partitions_.py` — mpf_cos optimization package

**What to change:**
1. Add `mpf_shift, mpf_neg` to the mpmath.libmp import line.
2. Replace q=2 mpf path with analytical: `a = fone if n % 2 == 0 else mpf_neg(fone)`.
3. Before mpf_cos in q>=3 loop: `two_pi = pi << 1; g = g % two_pi`.
4. Replace double mpf_add with: `a = mpf_add(a, mpf_shift(cos_val, 1), p)`.
5. Cache mpf functions as local variables.
6. Hoist q_sq, q_sq_qm1 outside inner h-loop.

**Patch available:** `runs/iter-5/patches/h-main.patch`

### h-ablation: Only analytical q=2

**What to change:** Add `mpf_neg` to imports. Replace q=2 mpf path only.

**Patch available:** `runs/iter-5/patches/h-ablation.patch`

## What I Tried That Didn't Work

### From Iterations 1-4 (carried forward)
1. **Weight-grouping** (iter-1 v3): SLOWER (~1.03s).
2. **Per-h NumPy arrays** (iter-2): Array creation overhead negates benefit.
3. **Early termination at d_bits==0** (iter-2): Breaks correctness.
4. **Fraction-based Dedekind sum** (iter-3): Python Fraction objects too slow.
5. **Fixed-point cos to replace mpf_cos** (iter-4): only 1.15x at specific precisions.
6. **NumPy batch for float-path T** (iter-4): 27ms overhead vs 16ms benefit.
7. **Fixed-point accumulation** (iter-4): tuple unpacking slower than mpf_add.
8. **Iterative Dedekind sum** (iter-4): can't share work across calls.

### From Iteration 5 (new)
9. **Precomputing b,c in _d**: Computing b = n-1/24 and c = sqrt(b) once at full precision and reusing at lower precisions is 17% SLOWER (6.08ms vs 5.19ms) because full-precision b,c values are larger and slower to operate on at lower precisions. Each mpf operation at prec=65 is dominated by mantissa size of operands, not the target precision.
10. **Merging a*d computation**: Computing each cos_val * d directly (instead of accumulating cos into a, then multiplying a*d) increases the number of mpf_mul calls from 1 per q to euler_totient(q)/2 per q. Since mpf_mul > mpf_add, this is slower.
11. **Precomputing coprime lists**: The sieve costs the same ~5ms as in-loop gcd checks. No net savings for single-use (forked process with cold state).
12. **Reducing precision margin from +50 to +40**: Would save ~1.5ms by transitioning to float path at q≈83 instead of q≈93. Deemed too risky without formal error analysis (could produce wrong integer for edge-case n values).
13. **Goertzel's algorithm for cosine sum**: Angles are NOT evenly spaced (depend on Dedekind sum), so Goertzel doesn't apply.

## What I Excluded and Why

1. **C extension / Cython**: Would eliminate Python loop overhead but adds build complexity incompatible with sympy's pure-Python philosophy.
2. **Custom mpf_cos for small precisions (p < 150)**: Potential double-double or fixed-point Taylor series. Complex to implement correctly, diminishing returns (~2ms target).
3. **Kloosterman sum closed forms for specific j**: Mathematically deep, would require per-j special cases. Not general.
4. **Reducing M (outer loop terms)**: Risky for correctness at general n values.
5. **Precision margin reduction**: 3ms potential savings but correctness risk.

## Evolution of Thinking

### Iteration 1 → 4 (summary)
Profiling → _a bottleneck → igcd replacement → frac_table → small-int sum → symmetry → Dedekind sum → float64 path → memoization → inline computation → 25.7x.

### Iteration 5
Started by profiling iter-4 code. Found mpf_cos at 40% of remaining time (18ms out of ~45ms). Investigated three approaches: (a) precomputing b,c in _d (failed: slower with full-precision values), (b) merging a*d computation (failed: more mpf_mul calls), (c) reducing mpf_cos overhead directly.

Key insight from angle analysis: all angles are ~10^6 radians because the dominant term is -2nh/q * π/q ≈ -10^6. This makes mod_pi2's high-precision division the bottleneck inside mpf_cos. Pre-reducing mod 2π in integer arithmetic is cheap (single Python int modulo) and eliminates the expensive reduction.

Second insight: q=2 is a special case. cos(-nπ) = (-1)^n is exact. The original code was computing this via 3728-bit mpf_cos, spending 3.4ms on what could be a constant lookup.

Combined the three orthogonal optimizations (analytical q=2 + pre-reduction + shift doubling) into h-main. Measured 31x workload speedup (vs 24.8x baseline).

## Current Status

- **Validated:** h-main at 0.045s workload (31.2x vs reference). h-ablation at 0.048s (28.8x). All tests pass. Bit-identical results for npartitions(10^6) and small values.
- **Uncertain:** Whether the remaining ~35ms (cold cache) has further optimization potential. The time is now split: mpf_cos ~11ms, _d cosh/sinh ~4ms, _dedekind_sum (cold cache) ~9ms, integer arithmetic ~3ms, float path ~5ms, overhead ~3ms.
- **Suggested next:** (1) Investigate caching pi_fixed results across precision levels. (2) Custom cosh_sinh for the specific argument structure in _d. (3) Profile at n=10^7 to check if optimizations scale. (4) Explore whether the precision margin (+50) can be formally proven safe at +30 for all n.

## Warnings & Constraints

1. **Python 3.11 compatibility**: Apply `iter-1/patches/py311-compat.patch` before running. 4 files need patching.
2. **lru_cache memory**: For n=10^6, cache holds ~10,230 entries. Negligible.
3. **lru_cache in forked processes**: Each forked process starts with empty cache. The workload's measurement reflects cold-cache performance.
4. **Do NOT edit /tmp/workload.py** — read-only for the experiment.
5. **Dedekind sum recursion depth**: Max ~8 levels for j ≤ 243. Well within Python's limit.
6. **Angle pre-reduction introduces ~10^-560 rounding difference**: This is from integer modular arithmetic (g % two_pi) vs mpf's internal mod_pi2. Completely negligible — the final integer result is identical because the 0.5 rounding tolerance absorbs this by 10^550 orders of magnitude.
7. **mpf_neg import**: The h-main and h-ablation patches add `mpf_neg` to the import line. Verify this import exists in the installed mpmath version.
8. **mpf_shift import**: The h-main patch also adds `mpf_shift`. Verify import.
