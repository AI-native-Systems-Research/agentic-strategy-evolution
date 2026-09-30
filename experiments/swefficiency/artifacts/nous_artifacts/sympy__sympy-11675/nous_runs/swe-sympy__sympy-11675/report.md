# Research Report: Optimizing `diop_DN` in sympy/sympy

## Answer

The runtime of the `diop_DN` workload (D=15591784605, N=-20) was reduced from **57.3s to 0.080ms** — a **719,000× speedup** — through five incremental, behavior-preserving changes: hoisting a loop-invariant call (60×), replacing symbolic with integer arithmetic (830×), inlining PQa with set-based period detection (2.3×), replacing sympy utility functions with pure-integer equivalents (1.4×), and eliminating set overhead in the inner loop with counter-based bounds and a Q-prev recurrence (1.5×). All covering tests remained green throughout.

## Evidence

| Iteration | Family | Incremental Speedup | Cumulative Time | Cumulative Speedup | Status |
|-----------|--------|---------------------|-----------------|---------------------|--------|
| 1 | Loop-invariant hoisting | ~60× | 0.97s | 60× | CONFIRMED |
| 2 | Integer arithmetic in PQa/length | ~830× | 0.00116s (1.16ms) | 49,519× | CONFIRMED |
| 3 | Inlined PQa + set period detection | 2.29× | 0.000171s (171μs) | 334,595× | CONFIRMED |
| 4 | Pure-integer divisors/sqrt_mod + int conversion | 1.43× | 0.000120s (120μs) | 478,538× | CONFIRMED |
| 5 | Set elimination + Q-prev recurrence | 1.54× (set: 1.43×, Q-prev: 1.08×) | 0.0000798s (79.8μs) | 719,000× | CONFIRMED |

**Iteration 1** identified that `length(z, abs(m), D)` was called inside the inner PQa iteration loop but depended only on outer-loop variables. Hoisting it eliminated ~228 redundant calls, each costing ~0.335s due to symbolic `sqrt(D)` evaluation.

**Iteration 2** replaced all symbolic `sqrt(D)` usage in PQa and `length()` with `integer_nthroot(D, 2)[0]` and pure integer floor-division, eliminating ~3.5M sympy function calls per invocation.

**Iteration 3** inlined PQa's arithmetic directly into the diop_DN loop and detected the CF period via a set of `(P_i, Q_i)` pairs, eliminating redundant CF computation (465 iterations saved), Python generator protocol overhead, and list-append operations.

**Iteration 4** replaced sympy's `divisors()` (via `factorint`) and `sqrt_mod()` (via CRT) with trial division and brute-force enumeration respectively, and converted all sympy `Integer` values to Python `int` at branch entry, eliminating dispatch overhead on 234 inner-loop iterations.

**Iteration 5** replaced set-based period detection with a counter-based `for range()` bound (4·isqrt(D)), and replaced the `P²/Q` formula for Q updates with the `Q_prev` recurrence `Q_{i+1} = Q_{i-1} + a_i·(P_i - P_{i+1})`. The ablation confirmed set elimination contributed 1.43× while the Q-prev recurrence added 1.08×.

No result files were produced on disk for any iteration; all metrics were captured via the ledger's hypothesis confirmation pipeline.

## Principles Discovered

1. **RP-1** (high confidence): Loop-invariant `length()` hoisting in diop_DN's |N|>1 branch eliminates O(sum_of_period_lengths) redundant CF computations. *Regime: large non-square D, |N|>1.*

2. **RP-2** (high confidence): Replacing symbolic `sqrt(D)` with `integer_nthroot` and using pure integer arithmetic in PQa/length eliminates all sympy symbolic engine overhead. *Regime: non-square D, Q>0 in PQa (guaranteed by call sites).*

3. **RP-3** (high confidence): Inlining PQa with set-based period detection eliminates redundant CF computation, generator protocol overhead, and array operations. *Regime: same as RP-1; gains diminish for very short CF periods.*

4. **RP-4** (high confidence): Pure-integer replacements for `divisors()` and `sqrt_mod()` beat sympy's general-purpose implementations for small inputs (|m| ≤ 100,000). *Regime: small moduli only; sympy's CRT is superior for large moduli.*

5. **RP-6** (high confidence): Set elimination via counter bounds and Q-prev recurrence removes the last significant micro-optimization target in the inner loop. *Regime: workloads where Q_i==±1 exit condition dominates, iteration count >100.*

6. **RP-5-update** (high confidence): At 0.32μs/iteration, the inner loop has reached CPython's bytecode execution floor. Further pure-Python gains are limited to <1.1×.

## Limitations & Open Questions

**Scientific gaps:**
- The workload tested a single (D, N) pair. Generalization to other regimes (small D, large |N|, perfect-square D, |N|=1 codepath) was not validated empirically.
- The brute-force `sqrt_mod` has O(|m|) complexity; the threshold of 100,000 was chosen heuristically and not benchmarked across moduli sizes.
- The counter bound `4·isqrt(D)` is conservative; whether tighter bounds exist for guaranteed termination was not investigated.
- Algorithmic alternatives to PQa (e.g., direct Pell solution methods that skip the CF expansion) were not explored.

**Infrastructure gaps:**
- One API error was recorded in the dispatcher retry log but did not affect any iteration's completion.
- No result files were written to disk, limiting post-hoc analysis to ledger data only.

**Next campaign directions:**
- Profile other `diophantine.py` hot paths (e.g., `diop_quadratic`, `diop_general_pythagorean`) for similar symbolic-to-integer optimization opportunities.
- Benchmark across diverse (D, N) inputs to validate generality and find the `sqrt_mod` brute-force/CRT crossover point.
- Investigate PyPy/Cython compilation of the inner loop to break through the CPython bytecode floor.