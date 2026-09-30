# Handoff — sympy__sympy-11675 iter-5

## Goal

Apply five layers of cumulative optimization to `sympy/solvers/diophantine.py`: (1) iter-1's loop-invariant hoisting, (2) iter-2's PQa and length() integer arithmetic, (3) iter-3's inlined PQa with period detection, (4) iter-4's pure-integer utility elimination + int() conversion, and (5) iter-5's inner-loop micro-optimizations (set elimination, first-iteration unrolling, Q_prev recurrence). Measure speedup over campaign baseline (57.3288s) and verify covering tests pass.

## Key Discoveries

1. **Set-based period detection is pure overhead for this workload.** All 3 z values (z=5, z=-5, z=0) exit via Q_i==±1 (at iterations 127, 27, 77 respectively). The set is never the exit condition, yet costs 231 tuple allocations + set hash/lookup/insert per call. Replacing with `for _ in range(max_period)` saves ~28μs (from 116μs to 88μs).

2. **The Q_prev recurrence eliminates P² and division from the inner loop.** The algebraic identity `Q_{i+1} = Q_{i-1} + a_i·(P_i - P_{i+1})` replaces `Q_{i+1} = (D - P_{i+1}²) / Q_i`. This saves an additional ~10μs (from 88μs to 78μs), a 1.13x improvement on top of the set elimination.

3. **The CF period of sqrt(D=15591784605) is 154.** The max_period bound of 4·isqrt(D) = 499,468 is 3243x generous. The bound is a safety net; exit always occurs via Q_i==±1 within 127 iterations for this workload.

4. **For-range is slightly faster than while+counter in CPython.** The C-level range iterator avoids per-iteration LOAD_FAST + COMPARE + BINARY_SUBTRACT overhead. Measured: 78.4μs (for-range) vs 80.9μs (while), a 3% advantage.

5. **Combined iter-5 direct speedup: 1.49-1.55x over iter-4.** Warm-call timing: 75-78μs (iter-5) vs 116μs (iter-4). Campaign speedup: ~734,000-760,000x (direct).

6. **Harness improvement is smaller due to fixed fork overhead.** Harness: ~0.229ms (iter-5) vs ~0.291ms (iter-4) = 1.27x. The ~155μs fork+IPC overhead is a fixed floor that cannot be reduced by algorithmic changes.

7. **Q_prev recurrence is algebraically exact.** Derived from Q_{i+1}·Q_i = D - P_{i+1}²: `Q_{i+1} = Q_{i-1} + a_i·(2·P_i - a_i·Q_i)`. Requires Q_{-1} = (D - P_0²)/Q_0 as initial value. Validated correct for all 41 test cases.

## System Interface

- **Build:** N/A (pure Python, use `PYTHONPATH=$PWD`)
- **Run workload:** `PYTHONPATH=$PWD python /tmp/workload.py`
- **Run tests:** `python -m pytest -q sympy/solvers/tests/test_diophantine.py`
- **Output format:** stdout — `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Campaign: 57.3288s. Iter-4 harness: 0.291ms. Iter-5 harness: 0.229ms. Iter-5 direct: 75.4μs.

## Code Map

- `sympy/solvers/diophantine.py:1135` — |N|>1 branch entry. `_D = int(D)`, `_N = int(N)`, `_sD = int(sD)` at lines 1139-1141.
- `sympy/solvers/diophantine.py:1177-1179` — `dn1_cache` init and `_max_period = _sD << 2` computation.
- `sympy/solvers/diophantine.py:1181-1241` — **THE TARGET.** Inline PQa with counter-based period bound, Q_prev recurrence, first-iteration unroll.
- `sympy/solvers/diophantine.py:1190-1191` — Q_prev initialization: `Q_prev = (_D - z * z) // abs_m`.
- `sympy/solvers/diophantine.py:1193-1205` — Unrolled first iteration (j=0).
- `sympy/solvers/diophantine.py:1209-1241` — Main for-range loop with Q_i check at top, Q_prev recurrence at bottom.
- `sympy/solvers/diophantine.py:1333-1352` — PQa generator (iter-2 integer arithmetic, used by |N|==1 branch only).
- `sympy/solvers/diophantine.py:1512-1574` — length() function (iter-2 integer arithmetic).
- `sympy/core/basic.py:3` — `collections.Mapping` → `collections.abc.Mapping`
- `sympy/plotting/plot.py:28` — `collections.Callable` → `collections.abc.Callable`
- `sympy/matrices/matrices.py:389` — `collections.Callable` → `collections.abc.Callable`

## Code Targets

### h-main: Full cumulative optimization (iters 1-5)

**All changes from iters 1-4 PLUS:**
- Replace `seen = set()` and set-based while-True with `for _ in range(_max_period)` counter-based loop
- Add `Q_prev = (_D - z * z) // abs_m` before the loop
- Unroll first iteration before the for-range loop (j=0 never yields a solution)
- Move Q_i==±1 check to top of loop body (before a_i computation)
- Replace `Q_i = (_D - P_i * P_i) // Q_i` with `Q_new = Q_prev + a_i * (P_i - P_new); Q_prev = Q_i; Q_i = Q_new`

A validated patch is at `runs/iter-5/patches/h-main.patch` — it contains ALL cumulative changes from iters 1-5 plus the 3 Python 3.11 compat fixes.

### h-ablation: Same as h-main but WITHOUT Q_prev recurrence

Apply all optimizations EXCEPT the Q_prev recurrence. Keep the original `P_i = a_i * Q_i - P_i; Q_i = (_D - P_i * P_i) // Q_i` formula. This isolates the Q_prev contribution.

## What I Tried That Didn't Work

1. **Compacted 3-tuple assignment for Q_prev/Q_i/P_i** — `Q_prev, Q_i, P_i = Q_i, Q_new, P_new` creates a 3-tuple for unpacking, which is slower than 3 separate STORE_FAST operations. Measured: 80.9μs vs 78.1μs. CPython only has fast ROT_TWO for 2-element swaps.

2. **While loop with counter** — `while iters > 0: ... iters -= 1` is ~3% slower than `for _ in range(max_period)` because the while version needs LOAD_FAST + COMPARE_OP + BINARY_SUBTRACT + STORE_FAST per iteration, while for-range uses a C-level iterator.

3. **Considered Floyd's/Brent's cycle detection** — Would use O(1) space but double the work (Floyd) or require function restarts (Brent). The counter-based bound is simpler and faster since Q_i==±1 is always found before a full period.

4. **Considered sharing work between z=5 and z=-5** — Both use abs_m=20 but have different initial P_0 values (5 vs -5), leading to different a_i sequences. No sharing possible.

5. **Considered numpy or math.isqrt** — integer_nthroot already takes only ~1μs per call. Not a bottleneck.

## What I Excluded and Why

1. **Optimizing the |N|==1 branch** — Not on the hot path for the workload (N=-20). Would add complexity for zero measurable gain.

2. **C extension for inner loop** — Breaks pure-Python constraint. Not appropriate for sympy.

3. **Import-time optimization** — With fork-based harness, child inherits parent's imported modules. Import time is zero in the child.

4. **Caching across diop_DN calls** — Workload calls diop_DN only once per fork. No benefit.

5. **Reducing harness fork overhead** — The ~155μs fork+IPC cost is intrinsic to the multiprocessing measurement methodology. Cannot be reduced by algorithm changes.

## Evolution of Thinking

1. **Started by profiling iter-4's remaining overhead** — cProfile showed 23,400 set.add calls (231/invocation) consuming 8.3% of profiled time (after profiling overhead correction).

2. **Traced inner loop exit conditions** — All 3 z values exit via Q_i==±1, never via set period detection. Confirmed the set is pure overhead for this workload.

3. **Tested set elimination + unroll** — 1.33x improvement (116→88μs). Significant because it removes the most object-allocation-heavy operations.

4. **Derived Q_prev recurrence** — From Q_{i+1}·Q_i = D - P_{i+1}², derived Q_{i+1} = Q_{i-1} + a_i·(P_i - P_{i+1}). Replaces P² computation and division with multiplications and addition.

5. **Tested combined optimizations** — 1.49x total (116→78μs). The Q_prev recurrence adds 1.12x on top of set elimination.

6. **Tested for-range vs while** — for-range 3% faster. Chose for-range.

7. **Verified full function correctness** — All 41 tests pass. Solutions mathematically verified (x²-D·y² = N).

## Current Status

- **Validated:** Full iter-5 optimization works: ~734,000× campaign speedup (direct), ~250,000× (harness), 41 tests pass, solutions identical to original code.
- **Uncertain:** Whether any further meaningful speedup is achievable in pure Python. At 78μs warm-call and 231 inner-loop iterations (~0.34μs/iteration), we are very close to CPython's bytecode interpretation floor for this algorithm. The per-iteration cost consists of ~6 integer multiplications/additions, 2 comparisons, and ~7 variable assignments.
- **Suggested next:** The optimization is at severe diminishing returns. Remaining possibilities: (a) algorithmic change to reduce the 231 PQa iterations (direct Pell solution via matrix methods or lookup table for small D mod primes), (b) running the inner loop in C via ctypes or Cython (breaks pure-Python constraint), (c) memoization of diop_DN results (no benefit for single-call workload). The campaign may be effectively complete — further iterations are unlikely to yield >1.1x additional improvement within the current algorithmic framework.

## Warnings & Constraints

1. **Python 3.11 compat fixes still required.** Apply via preflight commands (sed for 3 files).
2. **The `@XFAIL` test `test_fail_holzer` always fails.** Expected; marked with `@XFAIL`. Do not count this as a test failure.
3. **The negative-Q formula is CRITICAL.** When Q_i < 0, must use `a_i = -((P_i + _sD) // (-Q_i)) - 1`. Do NOT use `(P_i + _sD) // Q_i`.
4. **int() conversion is CRITICAL.** Without `_D = int(D); _N = int(N); _sD = int(sD)`, bitshift operations fail on sympy Integer inputs.
5. **Q_prev initialization is CRITICAL.** `Q_prev = (_D - z * z) // abs_m` computes Q_{-1} = (D - P_0²)/Q_0. This MUST be computed before the first iteration (which uses it).
6. **The Q_prev recurrence requires `P_i - P_new` (old P minus new P).** The computation order is: `P_new = a_i * Q_i - P_i` then `Q_new = Q_prev + a_i * (P_i - P_new)`. Do NOT swap these lines.
7. **A validated cumulative patch is available** at `runs/iter-5/patches/h-main.patch` — contains all changes from iters 1-5 plus Python 3.11 compat fixes.
8. **`mpmath` and `pytest` must be installed.** `pip install mpmath pytest` is needed.
