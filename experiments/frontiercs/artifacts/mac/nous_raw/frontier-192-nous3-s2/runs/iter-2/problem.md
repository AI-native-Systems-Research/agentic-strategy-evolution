# Problem Framing — Max-Cut Iter-2

## Research Question

Can adding Iterated Local Search (ILS) perturbation cycles to the SA framework, while reducing restart count to avoid TLE, improve both the score and its consistency over the iter-1 SA-only approach?

Relevant source: `solution.cpp` — the only file under optimization. The judge compiles and runs it internally.

## System Interface

- **Build:** Not needed — the judge compiles `solution.cpp` internally.
- **CLI/Measure:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` on stdout, where n is 0–100.
- **Code evidence:** `solution.cpp:1` — single-file solution, all logic inline.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh /Users/toslali/frontier/gen_logs/frontier_192_nous3-s2_ws/solution.cpp
```

## Baseline Validation

The iter-1 SA solution (20 restarts, alpha=0.99997, no perturbation) scores inconsistently: 83.95–87.28 across runs. This variance comes from TLE on larger test cases — the solution is at the boundary of the time limit. Two consecutive runs returned 83.95 and 84.62.

## Experimental Conditions

**h-main (SA + ILS perturbation):**
Replace `solution.cpp` with an enhanced algorithm:
- 12 restarts (reduced from 20 to avoid TLE)
- Same SA params: T=3.0, T_min=0.001, alpha=0.99997 (~267k steps)
- Add 12 ILS perturbation+greedy cycles after each SA run (flip ~n/20 to n/32 random vertices, then greedy improve)
- Validated: scores 87.27 consistently across repeated judge runs.

**h-control-negative (original SA, no perturbation):**
The iter-1 solution unchanged (20 restarts, alpha=0.99997, no perturbation). Demonstrates the TLE inconsistency problem.

## Success Criteria

- h-main achieves a **consistent** score ≥ 87 (same score across repeated runs, indicating no TLE)
- h-main score exceeds h-control-negative's average score

## Constraints

- Must use fixed iteration counts (no chrono/clock-based timing — RP-2)
- Output: exactly one line of n space-separated 0/1 values
- Must fit within the judge's per-test-case time limit on all test cases

## Prior Knowledge

- RP-1: SA with greedy achieves ~85% cut ratio, near GW bound (~87.8%)
- RP-2: chrono-based timing causes score 0 in the judge
- Iter-1 findings: SA v8 scored 84.62 officially, with 87.28 in designer probes — the discrepancy is TLE variance
