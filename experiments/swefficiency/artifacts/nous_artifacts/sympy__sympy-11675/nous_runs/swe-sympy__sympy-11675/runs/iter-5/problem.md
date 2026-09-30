# Problem Framing — iter-5: Inner-Loop Micro-Optimizations

## Research Question

Can we further reduce the runtime of `diop_DN(D, N)` for the workload
(D=15591784605, N=-20) by applying three micro-optimizations to the PQa
inner loop in the |N|>1 branch of `diop_DN`
(`sympy/solvers/diophantine.py:1135-1241`)?

Iterations 1–4 achieved a cumulative ~190,000× harness speedup (57.3s →
0.30ms) by: (1) hoisting the `length()` call out of the loop, (2)
replacing symbolic sqrt with integer arithmetic in PQa/length, (3)
inlining PQa with set-based period detection, and (4) replacing sympy
utility functions with pure-integer implementations.

RP-5 identifies the 231-iteration PQa inner loop as consuming ~87% of
per-call time at ~0.5μs/iteration. This iteration targets the remaining
overhead within that loop:

1. **Set-based period detection** — 231 tuple allocations + set
   lookups/inserts per call, never actually used as the exit condition
   (all 3 z values exit via Q_i==±1). Source: `diophantine.py:1188-1194`
   (iter-4 code).

2. **j counter and j!=0 check** — The first PQa iteration (j=0) never
   yields a solution, yet every subsequent iteration checks `j != 0`.
   Source: `diophantine.py:1187,1205` (iter-4 code).

3. **P²/Q division** — Each iteration computes `Q_{i+1} = (D - P_{i+1}²) / Q_i`,
   involving a square and integer division. The algebraic Q_prev
   recurrence `Q_{i+1} = Q_{i-1} + a_i·(P_i - P_{i+1})` replaces this
   with two multiplications and an addition — no square, no division.
   Source: `diophantine.py:1224-1225` (iter-4 code); recurrence derived
   from the PQa identity `Q_{i+1}·Q_i = D - P_{i+1}²`.

## System Interface

- **Build:** N/A (pure Python, use `PYTHONPATH=$PWD`)
- **CLI flags:** `PYTHONPATH=$PWD python /tmp/workload.py` (workload),
  `python -m pytest -q sympy/solvers/tests/test_diophantine.py` (tests)
- **Code evidence:**
  - `sympy/solvers/diophantine.py:1135` — |N|>1 branch entry
  - `sympy/solvers/diophantine.py:1177-1241` — Target region (PQa inner loop)
  - `sympy/solvers/diophantine.py:1333-1352` — PQa generator (unchanged; used by |N|==1 branch)
  - `sympy/solvers/diophantine.py:1512-1574` — length() function (unchanged)
- **Output format:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`

## Baseline Command

```bash
PYTHONPATH=$PWD python /tmp/workload.py
```

## Baseline Validation

With iter-4 optimizations (the code as it exists in the working tree
before iter-5 changes):
- Exit code: 0
- Harness mean: 0.000291s (5 fork runs)
- Direct warm-call mean: 0.116ms (500 calls)
- Tests: 41 passed, 1 XFAIL (test_fail_holzer)
- Campaign speedup (harness): 196,903×

## Experimental Conditions

### h-main: All three micro-optimizations combined

Replace the PQa inner loop (lines 1177-1226 of iter-4 code) with:

1. **Counter-based period bound** instead of set — `for _ in range(max_period)`
   where `max_period = 4·isqrt(D)`, a generous upper bound on the CF
   period (actual period is 154, bound is 499,468). Eliminates 231
   tuple allocations and set operations per call.

2. **First iteration unrolled** — Execute the j=0 iteration before the
   loop, removing the `j` counter and `j != 0` check from the hot path.

3. **Q_prev recurrence** — Track Q_{i-1} and compute
   `Q_{i+1} = Q_{i-1} + a_i·(P_i - P_{i+1})` instead of
   `Q_{i+1} = (D - P_{i+1}²) / Q_i`. Eliminates one P² computation
   and one integer division per iteration, replacing them with
   multiplications and additions.

4. **Early Q_i check** — Move the `Q_i == ±1` solution check to the
   top of the loop (before computing a_i/B_i/G_i), saving unnecessary
   arithmetic on the exit iteration.

### h-ablation: Set elimination + unroll only (no Q_prev)

Same as h-main but keeping the original `Q_i = (_D - P_i * P_i) // Q_i`
formula. Tests whether the Q_prev recurrence provides additional speedup
beyond the set elimination.

## Success Criteria

- h-main: Consistent reduction in direct warm-call time below iter-4's
  ~0.116ms, with all 41 covering tests passing.
- Directional prediction: h-main < h-ablation < iter-4 baseline on
  direct warm-call timing.

## Constraints

- Must not modify `/tmp/workload.py` or any test files.
- All 41 covering tests must pass (1 XFAIL: test_fail_holzer).
- Python 3.11 compat fixes still required (3 `collections` →
  `collections.abc` changes).
- The negative-Q formula `a_i = -((P_i + _sD) // (-Q_i)) - 1` must be
  preserved for correctness when Q_i < 0.
- The `int()` conversion at branch entry (from iter-4) must be preserved.
- The `dn1_cache` lazy evaluation path must be preserved for z values
  where `r²-D·s² ≠ m`.
- The sqrt_mod fallback to sympy for abs_m > 100000 must be preserved.

## Prior Knowledge

- **RP-1 (high):** Hoisting `length()` out of loop → 44× speedup.
- **RP-2 (high):** Integer arithmetic in PQa/length → 49,519× cumulative.
- **RP-3 (high):** Inlined PQa with set-based period detection → 334,595× cumulative.
- **RP-4 (high):** Pure-integer utilities + int() conversion → 190,335× cumulative (harness).
- **RP-5 (medium):** Approaching bytecode execution floor; inner loop is 87% of time.

Microbenchmarks (from design exploration, isolated inner computation):
- iter-4 code (set-based): 116.6μs mean
- Set elimination + unroll only: 88.0μs mean (1.33×)
- Set elimination + unroll + Q_prev + early check: 78.4μs mean (1.49×)
