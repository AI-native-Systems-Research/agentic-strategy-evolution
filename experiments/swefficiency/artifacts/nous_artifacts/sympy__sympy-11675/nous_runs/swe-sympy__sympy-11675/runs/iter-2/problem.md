# Problem Framing — Iteration 2: Integer Arithmetic in PQa and length()

## Research Question

After hoisting the loop-invariant `length()` call (iter-1, ~59x speedup), the remaining runtime of `diop_DN(15591784605, -20)` is dominated by **symbolic square-root arithmetic** in two functions:

1. **`length()` → `continued_fraction_periodic()`** at `sympy/ntheory/continued_fraction.py:64` uses `sd = sqrt(d)` (sympy symbolic), making each of the 3 remaining `length()` calls cost ~0.7s.
2. **`PQa()`** at `sympy/solvers/diophantine.py:1296` uses `floor((P_i + sqrt(D))/Q_i)` (sympy symbolic floor+sqrt) on every iteration of the inner loop.

Both functions compute continued-fraction quotients using sympy's symbolic `sqrt(D)`, which triggers the full symbolic algebra engine (evalf, simplify, etc.) for each arithmetic operation. Since D is a positive non-perfect-square integer, the quotients can be computed exactly using `integer_nthroot(D, 2)[0]` (integer square root) and pure integer arithmetic — eliminating all symbolic overhead.

**Key source files:**
- `sympy/solvers/diophantine.py:1296` — PQa's symbolic `floor((P_i + sqrt(D))/Q_i)`
- `sympy/solvers/diophantine.py:1439` — `length()` delegates to `continued_fraction_periodic()`
- `sympy/ntheory/continued_fraction.py:64` — `continued_fraction_periodic()` uses `sd = sqrt(d)` symbolically
- `sympy/core/power.py` — `integer_nthroot()` already imported at `diophantine.py:10`

## System Interface

- **Build:** None (pure Python, `PYTHONPATH=$PWD`)
- **Run workload:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/solvers/tests/test_diophantine.py`
- **Output format:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`
- **Code evidence:**
  - `sympy/solvers/diophantine.py:10` — `from sympy.core.power import integer_nthroot, isqrt` (already imported)
  - `sympy/solvers/diophantine.py:1296` — `a_i = floor((P_i + sqrt(D))/Q_i)` — symbolic sqrt+floor per iteration
  - `sympy/solvers/diophantine.py:1308` — `Q_i = (D - P_i**2)/Q_i` — uses Python `/` (true division), should be `//`
  - `sympy/solvers/diophantine.py:1473` — `length()` calls `continued_fraction_periodic(P, Q, D)` which uses symbolic sqrt
  - `sympy/ntheory/continued_fraction.py:64` — `sd = sqrt(d)` — the root cause of per-call expense in `length()`

## Baseline Command

```bash
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

Ran the workload on the iter-1-hoisted codebase (current state of `/testbed`):
- **Exit code:** 0
- **Workload mean:** 0.967s (iter-1 treatment, from findings.json)
- **Direct call timing:** 0.73s per `diop_DN(15591784605, -20)` call (profiled)
- **Profile breakdown:** `length()` via `continued_fraction_periodic`: 2.097s cumtime (84%), `PQa`: 0.433s cumtime (17%)

## Experimental Conditions

### h-main: Integer arithmetic in PQa and length()

Two code changes, both in `sympy/solvers/diophantine.py`:

**Change 1 — PQa (lines 1285–1308):** Replace symbolic `floor((P_i + sqrt(D))/Q_i)` with integer `(P_i + isqrt_D) // Q_i` where `isqrt_D = integer_nthroot(D, 2)[0]` is computed once before the loop. Also change `Q_i = (D - P_i**2)/Q_i` to use `//` (integer division) instead of `/` (float division, which could lose precision for large D).

**Correctness guarantee for PQa:** For Q_i > 0 (guaranteed in all call sites: line 1096 `PQa(0, 1, D)` and line 1156 `PQa(z, abs(m), D)`), `floor((P + sqrt(D))/Q) = (P + isqrt(D)) // Q` exactly, because `sqrt(D) - isqrt(D) ∈ (0, 1)` and the remainder `(P + isqrt(D)) % Q + frac < Q`. Verified empirically for all 237 PQa iterations in the workload — every `a_i` matches.

**Change 2 — length() (lines 1473–1481):** Replace the call to `continued_fraction_periodic(P, Q, D)` with an inline integer-only continued-fraction iteration that counts the period length directly. This avoids symbolic sqrt entirely. Must correctly replicate `int()` truncation-toward-zero semantics (matching the original `continued_fraction_periodic`'s `int((p + sd)/q)` behavior) for cases where the CF quotient is negative (occurs when P + isqrt(D) < 0 with Q > 0, or when Q < 0 during iteration). After normalization, `isqrt(d)` must be recomputed because `isqrt(d * q²) ≠ isqrt(d) * q` in general.

**Validated:** Applied both changes, ran workload: Mean 0.0012s (47,774x vs campaign baseline). All 41 covering tests pass. Solutions identical.

## Success Criteria

- Treatment mean runtime < 0.01s (speedup > 5,000x vs campaign baseline of 57.3288s)
- All 41 covering tests pass (1 `@XFAIL` expected failure)
- `diop_DN(15591784605, -20)` returns identical 3 solution tuples as baseline

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files
- Do NOT change observable behavior of any function — only internal implementation
- Three Python 3.11 compat fixes must be applied first (same as iter-1): `collections.Mapping` → `collections.abc.Mapping` in `sympy/core/basic.py:3`, `collections.Callable` → `collections.abc.Callable` in `sympy/plotting/plot.py:28` and `sympy/matrices/matrices.py:389`

## Prior Knowledge

- **RP-1** (iter-1): Loop-invariant length() hoisting gives ~59x speedup. Already applied in the codebase.
- **Iter-1 handoff:** Suggested next targets: (a) replace symbolic sqrt in PQa with integer isqrt, (b) cache diop_DN(D,-1) result, (c) replace symbolic sqrt in continued_fraction_periodic with isqrt.
- **Finding from exploration:** `diop_DN(D, -1)` is never actually called for this workload (all z values satisfy `r² - D*s² == m` on the first branch), so caching it provides no benefit.
