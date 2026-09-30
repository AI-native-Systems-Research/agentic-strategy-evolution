# Handoff — sympy__sympy-11675 iter-4

## Goal

Apply four layers of cumulative optimization to `sympy/solvers/diophantine.py`: (1) iter-2's PQa and length() integer arithmetic, (2) iter-3's inlined PQa with period detection in diop_DN's |N|>1 branch, (3) iter-4's pure-integer utility elimination (divisors, sqrt_mod, divisible) plus int() conversion and micro-optimizations, and (4) Python 3.11 compat fixes. Measure speedup over campaign baseline (57.3288s) and verify covering tests pass.

## Key Discoveries

1. **Sympy utility functions account for ~33% of iter-3's per-call time.** Profiling 100 warm calls shows `sqrt_mod` takes 0.007s (21%), `divisors`/`factorint` take 0.004s (12%), out of 0.034s total. These are general-purpose algorithms solving a trivial problem: finding divisors of 20 and computing modular square roots mod 5 and mod 20.

2. **Pure-integer replacements achieve 86-88% savings per utility call.** Microbenchmarks: sympy `divisors(20)` = 5.0μs → inline trial division = 0.7μs (86% savings); sympy `sqrt_mod(D, 20)` = 14.6μs → brute-force = 1.7μs (88% savings); sympy `sqrt_mod(D, 5)` = 3.0μs → brute-force = 0.9μs (70% savings).

3. **int() conversion eliminates sympy Integer dispatch in the inner loop.** When called from sympy's equation solver, D and N are sympy `Integer` objects. Converting to Python `int` at branch entry avoids `Integer.__mul__`, `Integer.__floordiv__`, `Integer.__mod__` dispatch on every iteration of the 234-step PQa loop. CRITICAL: bitshift `>>` does NOT work on sympy Integers — must convert first.

4. **Function call count drops from 387 to 249 per invocation.** Eliminating divisors/factorint/sqrt_mod and their transitive callees removes 138 function calls, which is significant at Python's per-call overhead floor.

5. **Harness speedup: 2.65× over iter-3.** Five harness runs: 0.304, 0.309, 0.304, 0.328, 0.313ms (mean 0.312ms). Iter-3 baseline: 0.837, 0.844, 0.789ms (mean 0.823ms). Campaign speedup: 57.3288 / 0.000312 ≈ 183,747×.

6. **Warm direct speedup: 0.118ms vs iter-3's ~0.25ms (2.1× improvement).** Campaign speedup on warm timing: 485,707×.

7. **Max abs_m in the full test suite is 27.** Brute-force sqrt_mod is trivial for all test-suite inputs. The 100,000 threshold for fallback to sympy is very generous.

8. **`diop_DN(D, -1)` is never reached for our workload.** All 3 z values find solutions via `r*r - D*s*s == m` without needing the `diop_DN(D, -1)` path. But the lazy caching is still correct for inputs that do reach it.

9. **Python 3.11 compat fixes still required** (same as all prior iters). Three `collections` → `collections.abc` changes.

## System Interface

- **Build:** N/A (pure Python, use `PYTHONPATH=$PWD`)
- **Run workload:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/solvers/tests/test_diophantine.py`
- **Output format:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Campaign: 57.3288s. Iter-3 harness: 0.823ms. Iter-4 harness: 0.312ms.

## Code Map

- `sympy/solvers/diophantine.py:10` — `from sympy.core.power import integer_nthroot, isqrt` — already imported, no change needed.
- `sympy/solvers/diophantine.py:1074` — `sD, _exact = integer_nthroot(D, 2)` — computes isqrt(D) for D>0. Converted to `_sD = int(sD)` in the |N|>1 branch.
- `sympy/solvers/diophantine.py:1094-1133` — **|N|==1 branch.** Uses PQa generator (iter-2's integer PQa modification). NOT modified by iter-4.
- `sympy/solvers/diophantine.py:1135-1215` — **|N|>1 branch.** THIS IS THE TARGET. Full replacement with pure-integer utilities + inlined PQa + period detection.
- `sympy/solvers/diophantine.py:1333-1349` — **PQa() generator.** Has iter-2's integer arithmetic (benefits |N|==1 branch).
- `sympy/solvers/diophantine.py:1512-1574` — **length() function.** Has iter-2's integer-only CF period computation.
- `sympy/core/basic.py:3` — `collections.Mapping` → `collections.abc.Mapping`
- `sympy/plotting/plot.py:28` — `collections.Callable` → `collections.abc.Callable` (both the import line and the isinstance call)
- `sympy/matrices/matrices.py:389` — `collections.Callable` → `collections.abc.Callable`

## Code Targets

### h-main: Pure integer utilities + all prior optimizations

**Target 1 — diop_DN |N|>1 branch (sympy/solvers/diophantine.py:1135-1208):**
Replace the entire branch. Key changes from iter-3:
- Add `_D = int(D); _N = int(N); _sD = int(sD)` at branch entry
- Replace `divisors(N)` + `divisible(N, d**2)` with: `d=1; while d*d <= absN: if absN%(d*d)==0: fs.append(d)`
- Replace `sqrt_mod(D, abs(m), all_roots=True)` with: `for x in range(abs_m): if (x*x) % abs_m == D_mod` (fallback to sympy for abs_m > 100000)
- Use `_sD` instead of `sD`, `_D` instead of `D` in inner loop for pure-int arithmetic
- Use `r * r` instead of `r**2`, `P_i * P_i` instead of `P_i**2`
- Use conditional instead of `abs()`: `abs_m = -m if m < 0 else m`
- Cache `diop_DN(D, -1)` with `dn1_cache` variable

**Target 2 — PQa generator (same as iter-2/3).**

**Target 3 — length() function (same as iter-2/3).**

**WHY these locations**: The utility functions (divisors, sqrt_mod) are the last remaining sympy overhead in the hot path. The inner loop already uses pure-integer arithmetic from iter-3, but the int() conversion at branch entry prevents sympy Integer dispatch at the variable level.

## What I Tried That Didn't Work

1. **`abs_m >> 1` without int() conversion** — `>>` (bitshift) is not defined for sympy `Integer` objects. Tests that call diop_DN through the equation solver pass sympy Integers. Must convert to Python int first.

2. **Considering set elimination** — The period detection set (tracking 78-128 (P_i, Q_i) pairs) adds ~0.002s/100 calls. Floyd's cycle detection would use O(1) space but double the work. Brent's algorithm requires function restarts. Neither is worth the complexity for ~0.02μs savings per iteration.

3. **Considering inlining PQa for |N|==1 branch** — Not a bottleneck (the workload uses |N|>1). Would add complexity for zero measurable gain.

4. **Profiling beyond inner loop** — The inner loop itself (0.021s/100 calls) is 87% of total time. The only way to make it faster would be C extension or algorithmic change (matrix methods for Pell equations).

## What I Excluded and Why

1. **C extension for inner loop** — Would break the pure-Python constraint and add build complexity. Not appropriate for a sympy optimization.

2. **Matrix exponentiation for PQa** — The a_i values change each iteration, so matrix batching doesn't apply. Would need a fundamentally different algorithm (e.g., Lenstra's method).

3. **Caching across diop_DN calls** — The workload calls diop_DN only once per fork. No benefit from memoization.

4. **Optimizing the |N|==1 branch's PQa usage** — Not on the hot path for N=-20.

## Evolution of Thinking

1. **Started with iter-3 profile analysis** — Identified that 33% of time was in sympy utility functions, not the PQa loop itself.
2. **Microbenchmarked alternatives** — Confirmed 70-88% savings from pure-integer replacements for small inputs.
3. **Hit the `>>` TypeError** — Discovered that sympy Integer inputs break pure-integer operations. Solution: convert to Python int at branch entry.
4. **Found abs_m values are tiny** — Max abs_m in entire test suite is 27. Brute-force sqrt_mod is optimal for this regime.
5. **Measured combined effect** — 2.65× harness improvement, 2.1× warm improvement. The harness benefit is larger because first-call cold-start overhead for sympy modules is eliminated.

## Current Status

- **Validated:** Full iter-4 optimization works: ~185,000× campaign speedup, 41 tests pass, results identical to original code. Direct warm timing 0.118ms, harness timing 0.312ms.
- **Uncertain:** Whether further meaningful speedup is achievable in pure Python. The per-call time is now ~0.12ms warm, with the 234-step inner loop being ~87% of that. At ~0.5μs per iteration, we're near Python's bytecode execution floor for this algorithm.
- **Suggested next:** The optimization appears to be at diminishing returns within the current algorithmic framework. Remaining possibilities: (a) algorithmic change to reduce the 234 PQa iterations (e.g., direct Pell equation solution methods), (b) precomputation of frequently-used results, (c) further micro-optimizations within the inner loop (variable renaming for faster local lookup, eliminating the `j` counter). These would likely yield <1.5× additional improvement.

## Warnings & Constraints

1. **Python 3.11 compat fixes required** (same as all prior iters). Three files need `collections` → `collections.abc` changes. Apply via preflight commands.
2. **The `@XFAIL` test `test_fail_holzer` always fails.** Expected; marked with `@XFAIL`.
3. **The negative-Q formula is CRITICAL** (from iter-3). Do NOT use `(P_i + _sD) // Q_i` when Q_i < 0. Must use `a_i = -((P_i + _sD) // (-Q_i)) - 1`.
4. **int() conversion is CRITICAL.** Without `_D = int(D); _N = int(N); _sD = int(sD)`, bitshift operations fail on sympy Integer inputs, and all arithmetic in the inner loop uses sympy's slow dispatch.
5. **sqrt_mod fallback threshold (100000)** must be maintained for correctness with large moduli. For the test suite and workload, brute-force handles everything.
6. **A draft patch is available** at `runs/iter-4/patches/h-main-draft.patch` — validated working patch from design exploration. The executor should verify it applies cleanly and tests pass.
7. **`mpmath` and `pytest` must be installed.** `pip install mpmath pytest` is needed.
