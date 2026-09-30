# Handoff — Frontier-CS Problem 5: Hamiltonian Path Challenge (Iteration 2)

## Goal

Implement and measure two algorithmic strategies: (1) h-main: SCC-aware construction + Pósa rotation (validated at SCORE: 81), and (2) h-control-negative: pure Pósa rotation without SCC (validated at SCORE: 72). Copy the validated source files to `solution.cpp` and measure each with `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`.

## Key Discoveries

1. **Test 4 has 366 small SCCs (max size 9)** — it's a DAG, not a single strongly connected graph. The rotation approach fails here because it can't exploit topological structure. SCC-aware construction solves test 4 completely: k=500/500 (full HP), up from k=223.

2. **SCC-aware construction adds +9 points**: Test 4 goes from 1/10 to 10/10. All other tests are unaffected (same results as v6). Total: 81 vs 72.

3. **Tests 8 and 10 remain unsolved**: Test 8 (single SCC, n=9K, avg_deg=5.44) stuck at k=3309 (37% coverage, 1/10 points). Test 10 (single SCC, n=100K, avg_deg=3) stuck at k≈5000 (5% coverage, 0/10 points). Multi-seed restarts don't help — the rotation mechanism is fundamentally limited on these graph structures.

4. **Timing sensitivity matters**: The primary seed (42) must get ≥3.0s budget to reproduce v6 results on tests 5-9. Reducing this budget causes test 7 (n=4000) to occasionally miss full HP. SCC computation should be skipped for large n (≤2000 threshold) to avoid overhead.

5. **DFS with backtracking finds condensation DAG HP reliably**: For test 4's 366-node condensation, DFS with topological-order pruning finds the HP in <1ms. The heuristic (sort candidates by out-degree) provides good backtracking performance.

6. **Bitmask DP handles internal SCCs efficiently**: All SCCs in test 4 have ≤9 vertices, so bitmask DP (O(sz·2^sz)) runs in microseconds per SCC. The DP handles entry/exit vertex constraints from the condensation path.

7. **Score is 81 consistently**: 5/5 runs give 81 after the timing fix (skip SCC for n>2000, primary seed budget 3.0s).

## System Interface

- **Build:** `g++ -O2 -o sol solution.cpp` (validated)
- **Run/measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` where n is 0-100
- **h-main result:** SCORE: 81 (5/5 runs consistent)
- **h-control-negative result:** SCORE: 72 (iter-1 validated, consistent)

## Code Map

- `solution_iter2c.cpp` — h-main implementation. SCC + rotation + multi-seed. **Use this file for h-main arm.**
  - Lines 1-10: Globals, includes
  - Lines 11-25: Adjacency lists, edge check (binary search on sorted adj)
  - Lines 27-35: Timer, global best tracking
  - Lines 37-199: `solveRotation()` — the v6-style linked-list Pósa rotation solver
  - Lines 201-350: `solveDAG()` — SCC decomposition + condensation DAG HP + bitmask DP
  - Lines 352-420: `main()` — graph reading, SCC threshold check, start candidate selection, multi-seed orchestration
  
- `solution_v6.cpp` — h-control-negative implementation. Pure Warnsdorff + Pósa rotation, seed 42. **Use this file for h-control-negative arm.**

- `algorithmic/problems/5/chk.cc:48-55` — Scoring logic
- `algorithmic/problems/5/testdata/{1..10}.in` — Test inputs

## Code Targets

### h-main: SCC-aware + Rotation
- **File:** `solution.cpp` — copy from `solution_iter2c.cpp`
- **Validation:** SCORE: 81 across 5 runs

### h-control-negative: Pure Rotation 
- **File:** `solution.cpp` — copy from `solution_v6.cpp`
- **Validation:** SCORE: 72

## What I Tried That Didn't Work

1. **Array-based path with position tracking** — O(n) prepend killed backward extension. Test 7 regressed from 4000 to 2745. The linked-list approach is faster for all path manipulation.

2. **Adjacency-based break-point search** — The position update cost O(n) per rotation dominates, making it no faster than v6's path walk (O(n/deg) average). The v6 approach is actually ~6x faster per rotation.

3. **Vertex recycling / perturbation** — Removing bypassed vertices and re-extending lost more than it gained. The removed vertices weren't recovered, and extension didn't compensate. Tests 7 and 8 both regressed.

4. **Multi-seed with reduced primary budget** — Giving the primary seed only 2.5s caused test 7 to occasionally miss full HP (3998/4000). The primary seed needs ≥3.0s.

5. **Unordered_set for edge lookup** — Higher constant factor than binary_search for small degree vertices (avg_deg 3-7).

6. **SCC computation on large graphs** — Computing SCCs for n=100K takes 42ms and returns 1 SCC (single SCC). Wasted time for no benefit. Fixed by n≤2000 threshold.

## What I Excluded and Why

- **Backward Pósa rotation (from head end)** — Iter-1 showed backward rotations consistently score 64-65 vs 72 for forward-only. The mechanism seems to interfere with forward rotation efficiency. Not included in iter-2.

- **DFS with backtracking for large single-SCC graphs** — Even with pruning, DFS can't handle n=9K or n=100K in 4 seconds. Only used for the condensation DAG (366 nodes).

- **Simulated annealing / genetic algorithms** — Too slow per iteration for n=100K. The 4-second time limit is too tight.

- **Test 10 optimization** — At avg_deg=3 with n=100K, the rotation mechanism is fundamentally limited. Even with 186K rotation attempts, coverage only reaches 5%. A fundamentally different approach (e.g., structure-specific heuristics for near-Hamiltonian sparse directed graphs) would be needed.

## Evolution of Thinking

Started with the hypothesis that better rotation (adjacency-based search, position tracking) would improve coverage on hard tests. Testing showed this is NOT true: the O(n) position update cost equals the O(n/deg) path walk cost, so no speedup. The real breakthrough came from recognizing test 4's structural difference: it's not a "hard single-SCC graph" but a DAG of small SCCs. This required a completely different algorithm (topological DP) rather than a better rotation.

The multi-seed approach helps marginally (test 10: 5088 vs 4985) but doesn't break through the fundamental rotation limit on sparse single-SCC graphs.

## Current Status

- **Validated:** solution_iter2c.cpp at SCORE: 81 (consistent). solution_v6.cpp at SCORE: 72 (consistent).
- **Uncertain:** Whether additional seeds help test 8 or 10 in a meaningful way. The variance is within 1-2% of coverage.
- **Suggested next (iter-3):**
  - For test 8: investigate why rotation gets stuck at 37% on a single SCC with avg_deg=5.44. The rotation should theoretically converge but 99.5% of rotations don't lead to extension. Try longer rotation chains (multiple rotations without intermediate extension checks).
  - For test 10: explore structure-specific algorithms for near-3-regular directed graphs. SCC decomposition doesn't help (single SCC). Need O(n) or O(n log n) algorithms that exploit the regularity.
  - For test 4: solved. SCC-based construction achieves full HP.

## Warnings & Constraints

1. **Time budget is critical**: Primary seed must get ≥3.0s to reliably solve tests 5-9. Any overhead (SCC computation, extra data structures) on large tests risks regressions.

2. **SCC computation only for n≤2000**: The `if(N <= 2000) solveDAG()` guard is essential. Without it, test 10 loses ~208ms to unnecessary computation.

3. **Static arrays in solveRotation**: The function uses `static` vectors sized to N+1 on first call. Since each test runs as a separate program invocation, this is fine. But don't try to reuse the solver across different graph sizes in the same process.

4. **Judge score variance**: Score is 81 in 5/5 recent runs. Earlier runs showed 71 (1/5) due to timing issues, which were fixed by the n≤2000 SCC guard and 3.0s primary budget. If variance recurs, suspect CPU load variability on the judge machine.
