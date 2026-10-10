# Handoff — sympy__sympy-11675 iter-1

## Goal

Apply a single code change (hoist loop-invariant `length()` call) in `sympy/solvers/diophantine.py` and measure the speedup on the `diop_DN(15591784605, -20)` workload. Verify covering tests remain green.

## Key Discoveries

1. **The bottleneck is `length()` called inside the inner loop.** Profiling showed 167M function calls in 120s; `length()` accounted for 231 calls at ~0.52s cumulative each = ~120s total. It's called at line 1181 on every iteration `j` of the inner PQa loop despite being loop-invariant.

2. **`length()` is expensive because of symbolic sqrt.** It delegates to `continued_fraction_periodic()` in `sympy/ntheory/continued_fraction.py:5`, which computes `sd = sqrt(d)` (symbolic) and then iterates with symbolic arithmetic. A single `length(0, 20, 15591784605)` call takes ~0.335s.

3. **The workload exercises the general-case branch.** D=15591784605 is not a perfect square (isqrt=124868), N=-20, |N|!=1, so we go to line 1135. There are 3 (z,m) pairs: f=1 gives m=-20 with 2 z-values, f=2 gives m=-5 with 1 z-value.

4. **Hoisting length() from inside to before the loop gives ~59.6x speedup.** Validated: single diop_DN call went from 42s to 0.95s. Full workload (5 repeats) went from 57.33s mean to 0.96s mean.

5. **Python 3.11 compatibility fixes are required.** Three pre-existing `collections` → `collections.abc` fixes needed for import to work: `sympy/core/basic.py:3`, `sympy/plotting/plot.py:28`, `sympy/matrices/matrices.py:389`.

6. **Tests pass with the change.** 41 passed, 1 expected failure (`test_fail_holzer` is `@XFAIL`).

## System Interface

- **Build:** N/A (pure Python, use `PYTHONPATH=$PWD`)
- **Run baseline:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Output format:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`
- **Run tests:** `python -m pytest -q sympy/solvers/tests/test_diophantine.py`
- **Baseline result:** Mean: 57.3288s (campaign-declared); single-call: ~42s (observed)

## Code Map

- `sympy/solvers/diophantine.py:996` — `diop_DN()` entry point. D>0, not-perfect-square, |N|>1 goes to line 1135.
- `sympy/solvers/diophantine.py:1135-1184` — General case: iterates over divisor-square factors `fs`, computes `sqrt_mod` roots `zs`, then for each `(z,m)` pair runs PQa iteration with a `length()` termination check.
- `sympy/solvers/diophantine.py:1181` — **THE LINE TO CHANGE:** `if j == length(z, abs(m), D):` — loop-invariant call that should be hoisted.
- `sympy/solvers/diophantine.py:1174-1175` — Redundant `diop_DN(D, -1)` calls (called twice: once to check emptiness, once for value). Not addressed in this iteration.
- `sympy/solvers/diophantine.py:1249` — `PQa()` generator. Uses symbolic `sqrt(D)` at line 1294 for floor computation. Potential future optimization target (use integer `isqrt`).
- `sympy/solvers/diophantine.py:1435` — `length()` function. Calls `continued_fraction_periodic()`.
- `sympy/ntheory/continued_fraction.py:5` — `continued_fraction_periodic()`. Uses symbolic `sqrt(d)` at line 64. The root cause of per-call expense.
- `sympy/core/basic.py:3` — Needs `collections.Mapping` → `collections.abc.Mapping` for Python 3.11.
- `sympy/plotting/plot.py:28` — Needs `collections.Callable` → `collections.abc.Callable` for Python 3.11.
- `sympy/matrices/matrices.py:389` — Needs `collections.Callable` → `collections.abc.Callable` for Python 3.11.

## Code Targets

### h-main: length-hoisting
- **File:** `sympy/solvers/diophantine.py`
- **Location:** Lines 1154-1182
- **Change:** Add `l = length(z, abs(m), D)` after line 1159 (before the inner for-loop), change line 1181 from `if j == length(z, abs(m), D):` to `if j == l:`
- **WHY this location:** This is the only place `length()` is called inside a loop. The arguments `(z, abs(m), D)` are constant throughout the inner loop.

## What I Tried That Didn't Work

- **Direct `from sympy.ntheory import integer_nthroot` in a script** — failed because importing sympy triggers `from collections import Mapping` on Python 3.11. Had to fix compat issues first.
- **Importing `sympy.solvers.diophantine as dio`** caused circular import with solvers package. Used direct function imports instead.

## What I Excluded and Why

1. **`PQa` integer-arithmetic optimization** — `PQa()` uses symbolic `floor((P_i + sqrt(D))/Q_i)` at line 1294, which could be replaced with integer `(P_i + isqrt(D)) // Q_i`. This would further reduce per-iteration cost but requires careful handling of edge cases (when the fractional part of sqrt(D) pushes the quotient over). Excluded because the length-hoisting alone gives ~60x speedup, and PQa optimization is a separate mechanism.
2. **`diop_DN(D, -1)` caching** — Lines 1174-1175 call `diop_DN(D, -1)` twice. Caching would help but the overhead is small (0-2 extra calls per workload). Excluded for simplicity; would be a good iter-2 target if more speedup is needed.
3. **`continued_fraction_periodic` integer arithmetic** — The function at `continued_fraction.py:64` uses `sd = sqrt(d)` symbolically. Replacing with `isqrt(d)` would make `length()` itself faster. Excluded because hoisting already reduces calls from 231 to 3.

## Evolution of Thinking

1. **Started by reading the workload** — saw it calls `diop_DN(15591784605, -20)` with large D.
2. **Read `diop_DN` code** — identified the general-case branch and its nested loops.
3. **Profiled** — immediately saw `length()` dominating at 231 calls. Initially suspected PQa or sqrt_mod overhead, but profiling pinpointed `length()` via `continued_fraction_periodic`.
4. **Spotted the loop-invariant** — `length(z, abs(m), D)` at line 1181 is called inside `for i in pqa:` but depends only on outer-loop variables.
5. **Validated the fix** — hoisting reduced 42s to 0.95s per call with identical results.

## Current Status

- **Validated:** The length-hoisting fix works. 59.6x speedup, identical results, all tests green.
- **Uncertain:** Whether additional gains from PQa integer arithmetic or diop_DN(-1) caching would compound meaningfully beyond the 59.6x.
- **Suggested next:** If more speedup is desired, (a) replace symbolic sqrt in PQa with integer isqrt, (b) cache diop_DN(D,-1) result, (c) replace symbolic sqrt in continued_fraction_periodic with isqrt.

## Warnings & Constraints

1. **Python 3.11 compat fixes required.** Three files need `collections` → `collections.abc` changes for imports to work. These are NOT part of the optimization but are prerequisites for the workload and tests to run. The executor must apply them.
2. **The `@XFAIL` test `test_fail_holzer` always fails.** This is expected (marked with `@XFAIL`) and is not related to our change.
3. **`mpmath` and `pytest` must be installed.** `pip install mpmath pytest` is needed.
