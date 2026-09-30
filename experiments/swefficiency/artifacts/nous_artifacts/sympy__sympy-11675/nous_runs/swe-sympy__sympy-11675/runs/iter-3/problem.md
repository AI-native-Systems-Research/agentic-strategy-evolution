# Problem Framing — iter-3: sympy__sympy-11675

## Research Question

After iter-2 achieved a 49,519x speedup by replacing symbolic sqrt with integer arithmetic in `PQa()` and `length()`, what additional performance can be gained by eliminating the redundant continued-fraction computation that `length()` performs separately from the PQa iteration loop in `diop_DN()`'s |N| > 1 branch?

The key mechanism is in `sympy/solvers/diophantine.py`, lines 1135-1184 (the |N| > 1 branch of `diop_DN`). The current algorithm:
1. Calls `length(z, abs(m), D)` to determine the CF period length (iterating the full CF expansion)
2. Then iterates PQa for up to that many steps (iterating the same CF expansion again)

This doubles the CF computation. Source files:
- `sympy/solvers/diophantine.py:1154-1182` — inner loop with PQa + length
- `sympy/solvers/diophantine.py:1250-1307` — PQa generator function
- `sympy/solvers/diophantine.py:1438-1495` — length function

## System Interface

- **Build command:** N/A (pure Python, `PYTHONPATH=$PWD`)
- **CLI flags:** `PYTHONPATH=$PWD python /tmp/workload.py` — runs `diop_DN(15591784605, -20)` 5 times
- **Code evidence:**
  - `diophantine.py:1156` — PQa generator creation per (z,m) pair
  - `diophantine.py:1160` — length() call (hoisted by iter-1, uses iter-2's integer CF)
  - `diophantine.py:1162-1183` — PQa iteration loop with `abs(i[1]) == 1` check and `j == l` termination
  - `diophantine.py:1294` — PQa's `a_i = floor((P_i + sqrt(D))/Q_i)` (iter-2 changes to integer)
  - `diophantine.py:1469-1495` — length() integer CF computation (iter-2 addition)
- **Native output:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`

## Baseline Command

```bash
cd /testbed && PYTHONPATH=$PWD python /tmp/workload.py
```

With iter-2's patch applied as baseline (the starting point for iter-3):
```bash
cd /testbed && git apply runs/iter-2/patches/h-main.patch && PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

**Campaign baseline (unmodified code):** Mean: 57.3288s (from campaign definition).

**Iter-2 baseline (with integer PQa + integer length + hoisting):**
- Exit code: 0
- Mean: 0.000929s (from workload harness) / 0.348ms (direct timing, 500 samples)
- Speedup: 49,519x (harness) / 164,700x (direct)
- Tests: 41 passed, 1 XFAIL

**Profiling breakdown of iter-2 baseline (per single diop_DN call, direct timing):**
- Total: 0.348ms
- `length()` (3 calls): 0.142ms (41% of total) — computes CF period, redundant with PQa
- PQa generator (234 iterations): ~0.12ms (34%) — tuple creation + generator protocol
- `sqrt_mod` (2 calls): ~0.035ms (10%)
- Other (divisors, abs, etc.): ~0.051ms (15%)

## Experimental Conditions

### h-main: Inline PQa + period detection + eliminate length()

In diop_DN's |N| > 1 branch (lines 1154-1183), replace the PQa generator call + length() termination with:

1. **Inline PQa arithmetic** — eliminate generator protocol overhead (tuple creation per iteration, next() calls, generator frame resumption)
2. **Set-based period detection** — track `(P_i, Q_i)` pairs to detect CF period completion, replacing the separate `length()` call that redundantly computes the same CF expansion
3. **Scalar G/B tracking** — replace G[] and B[] arrays with scalar variables (G_1, G_2, B_1, B_2), using G_1/B_1 directly as "previous" values when |Q_i| == 1
4. **Eliminate A_i computation** — the A_i recurrence (computed in PQa but never used by diop_DN) is removed entirely
5. **Correct negative-Q handling** — for Q_i < 0 (occurs when P_i² > D for small D), use `a_i = -((P_i + sD) // (-Q_i)) - 1` instead of `(P_i + sD) // Q_i` (which gives wrong floor for negative divisors when the dividend differs from the true value)

This builds on top of iter-2's patch (PQa integer arithmetic, length() integer-only, hoisting).

**Why it works:** The workload has 3 (z, m) pairs, each requiring ~155 CF iterations for period computation via `length()`, but PQa only needs 128, 28, and 78 iterations respectively before finding |Q_i| == 1. The current code does 3×155 + 234 = 699 CF iterations; the optimized code does only 234, a 66% reduction.

## Success Criteria

- **Primary:** Speedup > 200,000x over campaign baseline (57.3288s), representing >1.5x improvement over iter-2's 0.348ms. Based on prototype: measured 0.156ms mean → ~367,000x speedup.
- **Correctness gate:** All 41 covering tests pass (only `test_fail_holzer` XFAIL fails).
- **Results identical:** Same 3 solution tuples as baseline, all satisfying x² - Dy² = N.

## Constraints

- Do NOT edit `/tmp/workload.py` or any test files.
- Do NOT change observable behavior (solution set must be identical).
- Python 3.11 compat fixes required (`collections` → `collections.abc` in 3 files).
- The `@XFAIL` test `test_fail_holzer` always fails — this is expected.
- The negative-Q integer formula is CRITICAL: `(P_i + sD) // Q_i` gives wrong results when Q_i < 0. Must use the branching formula.

## Prior Knowledge

- **RP-1:** Loop-invariant hoisting of `length()` in diop_DN's inner loop reduces calls from O(sum_of_period_lengths) to O(num_z_values). Confirmed in iter-1 (59x speedup).
- **RP-2:** Integer arithmetic replacing symbolic sqrt in PQa and length eliminates symbolic engine overhead. Confirmed in iter-2 (49,519x combined with RP-1).
- Iter-3 extends RP-2 by eliminating the redundant CF computation entirely (merging period detection into the PQa loop), plus reducing Python overhead through inlining.
