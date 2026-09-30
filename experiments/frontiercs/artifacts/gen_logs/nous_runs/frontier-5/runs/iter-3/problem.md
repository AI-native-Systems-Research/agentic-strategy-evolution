# Problem Framing — Iteration 3

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #5 (Directed Hamiltonian Path)?

Iteration 3 targets the remaining score opportunity: test 10 (n=100K, avg_deg=3, 0/10 in iter-2). The mechanism is **break-and-extend** — a directed path manipulation that truncates the tail to an escape vertex (one with unvisited out-neighbors), re-extends greedily, and recovers removed vertices. This exploits the structural property of very sparse graphs where standard Pósa rotation stalls because all rotation candidates lack unvisited neighbors, but 99% of path vertices have unvisited out-neighbors that are inaccessible via rotation.

Key source files:
- `solution_iter3.cpp:201-303` — `solveBreakExtend()` function implementing the break-and-extend loop
- `solution_iter3.cpp:24-199` — `solveRotation()` with linked-list Pósa rotation (unchanged from iter-2)
- `solution_iter3.cpp:306-539` — `solveDAG()` with SCC decomposition (unchanged from iter-2)
- `solution_iter3.cpp:541-638` — `main()` with adaptive branching: sparse path (avg_deg < 4) vs standard path

## System Interface

- **Build command:** `g++ -O2 -o solution solution.cpp`
- **Run command:** `./solution < testdata/N.in`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`
  - Compiles, runs all 10 tests with 4s time limit each, scores via checker
  - Output: `SCORE: <float>` on stdout (sum of per-test scores, each 0-10)
- **Input format:** First line: `N M`, second line: 10 threshold values `a_1...a_10`, then M directed edges
- **Output format:** First line: `k` (path length), second line: k space-separated vertex IDs

### Code evidence
- `fmeasure_5.sh` compiles with `-O2` and runs with 4s timeout per test
- `solution_iter3.cpp:542-557` — main() reads input (N, M, thresholds, edges)
- `solution_iter3.cpp:581` — avg_deg < 4.0 branch condition for sparse path
- `solution_iter3.cpp:596` — per-attempt 0.2s budget for break-and-extend restarts
- `solution_iter3.cpp:601-623` — standard path: Phase 1 (seed 42 to 3.0s) + Phase 2 (max-degree to 3.5s)

## Baseline Command

```bash
cp solution_iter3.cpp solution.cpp && g++ -O2 -o solution solution.cpp && bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp
```

## Baseline Validation

Ran 3 times. All returned `SCORE: 83` (82.99999999999999 due to float).

Per-test k values:
- Tests 1-3: k = 5, 20, 60 (all full HP, 10/10 each)
- Test 4: k = 500 (full HP via SCC solver, 10/10)
- Tests 5-7: k = 1000, 2000, 4000 (full HP, 10/10 each)
- Test 8: k = 5638 (2/10, needs 6977 for 3/10)
- Test 9: k = 8000 (full HP, 10/10)
- Test 10: k = 25777 (1/10, new! was 0/10 in iter-2)

Score breakdown: 70 (tests 1-3,5-7,9) + 10 (test 4) + 2 (test 8) + 1 (test 10) = 83

## Experimental Conditions

### h-main: Break-and-extend for sparse graphs (score 83 target)

The treatment adds `solveBreakExtend()` and adaptive main() branching to the iter-2 solution. For graphs with avg_deg < 4 and N > 2000, the algorithm skips the standard Phase 1/Phase 2 pipeline and instead runs multi-restart break-and-extend with 0.2s per attempt.

Changes from iter-2 baseline (score 81):
1. **New function `solveBreakExtend()`** (lines 201-303): greedy construction + limited rotation + break-and-extend loop
2. **Adaptive branching in main()** (line 581): `if(avgDeg < 4.0 && N > 2000)` → sparse path; else → standard path (identical to iter-2)
3. **Multi-restart with 0.2s budget** (line 596): more restarts are better than fewer long attempts on sparse graphs

The standard path (tests 1-9) is byte-identical to iter-2's main(), preserving the proven 82-point floor.

### h-control-negative: Iter-2 solution (baseline, score 81-82)

The iter-2 solution without break-and-extend. Uses SCC + rotation only. Expected score: 82 (same as iter-2 h-main modal score).

Command: compile and run the v12 solution (iter-2 h-main, stored as `solution.cpp` at start of iteration).

## Success Criteria

- **Primary:** h-main scores strictly higher than h-control-negative (83 > 82)
- **Mechanism validation:** improvement comes exclusively from test 10 (break-and-extend engaging on avg_deg=3 graph)
- **No regression:** tests 1-9 must score identically between h-main and h-control-negative

## Constraints

- 4-second time limit per test case (hard wall-clock)
- Score is deterministic (seeded RNG) — single run is sufficient but multiple runs verify timing stability
- Active principles RP-1 through RP-6 apply (see Prior Knowledge)

## Prior Knowledge

### Active Principles

- **RP-1 (Warnsdorff seed 42):** Warnsdorff heuristic with MT19937 seed 42 reliably finds complete HP for tests 1-3, 5-7, 9 within 3s. Confirmed iter-1, iter-2.
- **RP-2 (SCC for DAGs):** SCC decomposition via iterative Kosaraju enables full HP on test 4 (366 SCCs, max size 9). Confirmed iter-2.
- **RP-3 (Max-degree greedy):** Max-degree greedy restarts improve coverage on moderate sparse graphs (test 8: k=5739 vs k=3309 with Warnsdorff). Confirmed iter-2.
- **RP-4 (Timing sensitivity):** Primary seed 42 needs >= 3.0s for reliable test 7 HP. Reducing Phase 1 below 3.0s causes test 7 regression. Confirmed iter-1 timing failures.
- **RP-5 (Rotation ceiling):** Pure rotation-based approaches hit a structural ceiling on sparse single-SCC graphs (~6414 on test 8, ~21021 on test 10) regardless of time/restarts. New in iter-2.
- **RP-6 (Sparse graphs need different strategy):** Graphs with avg_deg <= 3 require fundamentally different approaches — rotation stalls because rotation candidates don't have unvisited neighbors. New in iter-2.
