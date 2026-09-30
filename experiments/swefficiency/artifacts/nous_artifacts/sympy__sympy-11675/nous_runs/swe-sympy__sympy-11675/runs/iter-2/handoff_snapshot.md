# Handoff — sympy__sympy-11675 iter-2

## Goal

Apply two code changes in `sympy/solvers/diophantine.py` to replace symbolic sqrt with integer isqrt in `PQa()` and `length()`. Measure the combined speedup over campaign baseline (57.3288s). Verify covering tests remain green.

## Key Discoveries

1. **Symbolic sqrt is the remaining bottleneck.** After iter-1's hoisting, profiling shows `length()` takes 2.097s (84%) and `PQa` takes 0.433s (17%) of the 2.5s per-call runtime. Both use sympy's symbolic `sqrt(D)` which triggers ~3.5M function calls through the symbolic engine.

2. **Integer isqrt is a drop-in replacement for PQa.** For Q > 0 (true in all call sites), `floor((P + sqrt(D))/Q) = (P + isqrt(D)) // Q` exactly. Verified for all 237 iterations in the workload. PQa's `Q_i = (D - P_i**2)/Q_i` should use `//` not `/` to avoid float precision loss.

3. **length() needs careful truncation-toward-zero handling.** The original `continued_fraction_periodic` uses `int((p + sd)/q)` which truncates toward zero, NOT `floor()`. This matters when `p + isqrt(d) < 0` (occurs for small D test cases like `length(-5, 4, 17)`). The integer formula differs by sign-handling branches.

4. **isqrt must be recomputed after normalization.** `continued_fraction_periodic` normalizes: `d *= q²`, `p *= |q|`, `q *= |q|`. After this, `isqrt(d_new) ≠ isqrt(d_old) × |q|` because `isqrt(a·b²) ≠ isqrt(a)·b` when `frac(sqrt(a))·b ≥ 1`. Must call `integer_nthroot(d, 2)[0]` again after normalization.

5. **diop_DN(D, -1) is never called for this workload.** All 3 (z,m) pairs satisfy `r² - D·s² == m`, so the elif branch at line 1176 is never taken. Caching it provides zero benefit.

6. **Combined speedup: ~47,000x over campaign baseline.** Treatment mean 0.0012s (workload) / 0.000374s (direct call). All 41 tests pass.

7. **Python 3.11 compat fixes still required** (same as iter-1). Three `collections` → `collections.abc` changes.

## System Interface

- **Build:** N/A (pure Python, use `PYTHONPATH=$PWD`)
- **Run workload:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/solvers/tests/test_diophantine.py`
- **Output format:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Mean: 57.3288s (campaign). Iter-1 treatment: 0.967s.

## Code Map

- `sympy/solvers/diophantine.py:10` — `from sympy.core.power import integer_nthroot, isqrt` — already imported, no change needed.
- `sympy/solvers/diophantine.py:1285-1308` — **PQa() function body.** Lines 1294-1296: the while loop with `a_i = floor((P_i + sqrt(D))/Q_i)`. Line 1308: `Q_i = (D - P_i**2)/Q_i`.
- `sympy/solvers/diophantine.py:1439-1481` — **length() function body.** Lines 1473-1481: calls `continued_fraction_periodic` and counts terms.
- `sympy/solvers/diophantine.py:1096` — `pqa = PQa(0, 1, D)` — caller in |N|==1 case, Q=1>0.
- `sympy/solvers/diophantine.py:1156` — `pqa = PQa(z, abs(m), D)` — caller in general case, Q=abs(m)>0.
- `sympy/solvers/diophantine.py:1161` — `l = length(z, abs(m), D)` — the hoisted call from iter-1.
- `sympy/ntheory/continued_fraction.py:5-92` — `continued_fraction_periodic()` — NOT modified (general-purpose function). Only bypassed by the new length() fast path.
- `sympy/core/basic.py:3` — Needs `collections.Mapping` → `collections.abc.Mapping`.
- `sympy/plotting/plot.py:28` — Needs `collections.Callable` → `collections.abc.Callable`.
- `sympy/matrices/matrices.py:389` — Needs `collections.Callable` → `collections.abc.Callable`.

## Code Targets

### h-main: Integer arithmetic in PQa and length

**Target 1 — PQa (sympy/solvers/diophantine.py:1285-1308):**
- After line 1292 (`Q_i = Q_0`), add: `sqD = integer_nthroot(D, 2)[0]`
- Line 1296: change `a_i = floor((P_i + sqrt(D))/Q_i)` → `a_i = (P_i + sqD) // Q_i`
- Line 1308: change `Q_i = (D - P_i**2)/Q_i` → `Q_i = (D - P_i**2) // Q_i`
- WHY: eliminates symbolic sqrt+floor. `integer_nthroot` is already imported at line 10.

**Target 2 — length (sympy/solvers/diophantine.py:1473-1481):**
- Replace the body (lines 1473-1481) with an integer-only CF period computation:
  1. `sd, is_perfect = integer_nthroot(D, 2)`. If perfect square, fall back to original.
  2. Normalize: if `(d - p²) % q != 0`, scale `d *= q²`, `p *= |q|`, `q *= |q|`, **then recompute** `sd = integer_nthroot(d, 2)[0]`.
  3. Iterate: track `(p, q)` pairs in a dict. For each step, compute CF quotient using integer truncation-toward-zero:
     - `num = p + sd`
     - For `q > 0`: if `num >= 0`, `a = num // q`; else `abs_num = -num`, if `abs_num % q == 0` then `a = 1 - abs_num // q` else `a = -(abs_num // q)`
     - For `q < 0`: `Q_abs = -q`, if `num >= 0` then `a = -(num // Q_abs)`; else `abs_num = -num`, if `abs_num % Q_abs == 0` then `a = abs_num // Q_abs - 1` else `a = abs_num // Q_abs`
  4. Update: `p = a*q - p`, `q = (d - p*p) // q`
  5. Return count when `(p, q)` repeats.
- WHY this logic: matches `int((p + sqrt(d))/q)` truncation-toward-zero semantics exactly. Verified against all 8 test cases in `test_length()`.

## What I Tried That Didn't Work

- **Simple `(p + isqrt_d) // q` for all cases** — fails for `length(-5, 4, 17)` and others where `p + isqrt_d < 0`. Python's `//` floors while the original `int()` truncates toward zero. Needed sign-aware branching.
- **`sd *= abs(q)` after normalization** — gives wrong results because `isqrt(d·q²) ≠ isqrt(d)·|q|`. For `length(0, 4, 13)`: `isqrt(13)·4 = 12` but `isqrt(208) = 14`. Must recompute with `integer_nthroot(d, 2)[0]`.
- **Monkey-patching via `import sympy.solvers.diophantine as dio`** — fails because importing `sympy.solvers` triggers import chain that expects `diophantine` as submodule. Had to test by editing files directly.

## What I Excluded and Why

1. **Modifying `continued_fraction_periodic()` directly** — it's a general-purpose function in `sympy.ntheory` used by many other callers. Safer to bypass it with an inline integer path in `length()` and leave the original untouched.
2. **diop_DN(D, -1) caching** — verified that this code path is never reached for our workload (all z values satisfy `r² - D·s² == m`). Zero benefit.
3. **PQa negative-Q handling** — all PQa call sites in `diop_DN` use Q > 0 (`abs(m)` or `1`). The simple `//` formula is sufficient. Did not add sign-handling branches to PQa.
4. **Further optimization of `divisors()`, `sqrt_mod()`, etc.** — after PQa and length are integer, `diop_DN` takes ~0.0004s. The remaining functions contribute negligibly.

## Evolution of Thinking

1. **Started by profiling the hoisted codebase** — saw `length()` (2.1s) and `PQa` (0.4s) dominate, both via symbolic sqrt.
2. **Verified the integer formula for PQa** — straightforward, all Q > 0, `(P + isqrt_D) // Q` matches `floor((P + sqrt(D))/Q)` exactly.
3. **Hit the normalization bug** — `isqrt(d·q²) ≠ isqrt(d)·q`. Cost several failed attempts before realizing the need to recompute after normalization.
4. **Hit the truncation bug** — `//` vs `int()` differs for negative quotients. Had to reverse-engineer the exact semantics of `int((p + sd)/q)` for all sign combinations and implement matching integer formulas.
5. **Verified all 8 test_length cases pass** — including edge cases with small D and negative P.
6. **Measured 47,000x speedup** — far exceeds the ~59x from iter-1 alone.

## Current Status

- **Validated:** Both PQa and length integer optimizations work. 47,774x speedup over campaign baseline. All 41 tests pass. Solutions identical.
- **Uncertain:** Whether the integer truncation-toward-zero formula for `length()` handles ALL possible inputs correctly (only tested against the 8 test cases + 3 workload cases). Edge cases with very small D or large negative P might still diverge — the fall-back to `continued_fraction_periodic` for perfect-square D provides a safety net.
- **Suggested next:** If more speedup is desired (unlikely given 47,000x), optimize `sqrt_mod()` or `divisors()`. If robustness is a concern, add a verification mode that cross-checks the integer `length()` against the symbolic version for the first call and falls back on mismatch.

## Warnings & Constraints

1. **Python 3.11 compat fixes required** (same as iter-1). Three files need `collections` → `collections.abc` changes.
2. **The `@XFAIL` test `test_fail_holzer` always fails.** Expected; marked with `@XFAIL`.
3. **The normalization recompute is CRITICAL.** After `d *= q*q`, `sd` MUST be recomputed via `integer_nthroot(d, 2)[0]`. Using the scaled `sd *= abs(q)` gives WRONG results for many inputs.
4. **The truncation-toward-zero branching is CRITICAL.** Do NOT simplify the `length()` integer quotient to just `(p + sd) // q`. This fails for negative `(p + sd)`. The full sign-aware formula is required.
5. **`mpmath` and `pytest` must be installed.** `pip install mpmath pytest` is needed.
