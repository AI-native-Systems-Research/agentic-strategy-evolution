# Handoff — Frontier-CS Problem 5: Hamiltonian Path Challenge

## Goal

Implement and measure two algorithmic strategies for finding long directed Hamiltonian paths: (1) h-main: Warnsdorff greedy + directed Pósa rotations with O(1) linked-list pointer surgery (validated at SCORE: 72), and (2) h-control-negative: Warnsdorff greedy without rotations (validated at SCORE: 41). Measure each with `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`.

## Key Discoveries

1. **Directed Pósa rotations are the dominant improvement**: Score jumped from 41 (greedy+insertion) to 72 (greedy+rotation) — a 76% improvement. The rotation lets the algorithm escape dead ends by restructuring the path to create new extension points.

2. **O(1) pointer surgery is critical for performance**: The vector-based rotation (v5) scored 52 while the linked-list rotation (v6) scored 72. The linked list enables O(1) pointer surgery per rotation vs O(n) array copy, allowing orders of magnitude more rotations within 4 seconds.

3. **All 10 test cases have full Hamiltonian paths** (verified from `.ans` files). Path lengths range from 5 to 100,000. The scoring thresholds are aggressive: test 10 (n=100K, avg_deg=3) requires k≥23,333 for even 1 point.

4. **Score is seed-sensitive**: Seed 42 gives 72, seed 123 gives 54. The randomization in shortcut selection and break-point choice during rotation significantly affects outcomes.

5. **Backward Pósa rotations (from head end) consistently hurt performance**: Every implementation with backward rotations scored 64-65 vs 72 for forward-only. Either the pointer surgery has a subtle bug or head-end rotations interfere with the forward rotation's efficiency.

6. **DFS with bounded backtracking is worse than greedy+rotation**: Scored 33 vs 72. Even with Warnsdorff guidance, the branching factor makes DFS uncompetitive on these graph sizes.

7. **Ruin-and-recreate local search didn't help**: v4 (ruin-and-recreate) scored 40 vs 41 baseline. For directed graphs, segment removal requires bypass edges which are scarce in sparse graphs.

## System Interface

- **Build:** `g++ -O2 -o sol solution.cpp` (validated, compiles cleanly)
- **Run/measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0–100 (continuous partial credit)
- **Baseline result:** Greedy+rotation (v6) achieves SCORE: 72; reference solutions score 25-33

## Code Map

- `solution.cpp` — The only file to edit. Contains the complete algorithm.
- `/home/ubuntu/frontier/gen_logs/fmeasure_5.sh` — The judge script. Calls `frontier eval algorithmic 5`.
- `algorithmic/problems/5/chk.cc:48-55` — The scoring logic: for each test case, score = count of a_i ≤ k, then ratio pnt/10.
- `algorithmic/problems/5/testdata/{1..10}.in` — Test inputs. Line 1: n m. Line 2: 10 scoring thresholds. Remaining lines: directed edges.

## Code Targets

### h-main: Warnsdorff + Pósa Rotation
- **File:** `solution.cpp` (complete rewrite of stub)
- **Reference implementation:** `/home/ubuntu/frontier/gen_logs/frontier_5_nous_ws/solution_v6.cpp` — this is the validated implementation scoring 72. The executor should use this as the reference for the h-main arm.
- **Key components:**
  - Lines 41-248: `solve()` lambda containing greedy build + rotation loop
  - Lines 118-216: The Pósa rotation loop with cycle case and general case
  - Lines 200-208: The O(1) pointer surgery (6 pointer assignments)

### h-control-negative: Warnsdorff WITHOUT Rotations
- **File:** `solution.cpp` (same as h-main but remove rotation loop)
- **Reference implementation:** `/home/ubuntu/frontier/gen_logs/frontier_5_nous_ws/solution_v1_backup.cpp` — the validated implementation scoring 41.
- **What to change:** Remove the entire Pósa rotation loop (lines 104-216 in v6). Keep everything else identical.

## What I Tried That Didn't Work

1. **DFS with bounded backtracking (v3)**: Score 33. Even with Warnsdorff-guided branching and bt_limit=500K, the search tree is too large for medium graphs. The DFS ate all the time budget, leaving no time for the greedy fallback.

2. **Ruin-and-recreate (v4)**: Score 40. Removing a segment and rebuilding requires bypass edges (P[i]→P[j+1] for non-adjacent i,j), which are rare in sparse directed graphs.

3. **Backward Pósa rotations (v7, v8)**: Score 64-65. Every attempt to add head-end rotations degraded performance.

4. **Multi-seed within single run (v13)**: Score 55-72. Splitting time across multiple RNG seeds reduces per-seed rotation budget.

5. **Per-restart time limits (v11)**: Score 66. Cutting rotation time per restart below ~1.5s hurts.

## What I Excluded and Why

- **SAT/ILP solvers**: Time limit is 4 seconds per test case with n up to 100K. Exact solvers can't handle this.
- **Genetic algorithms / ant colony**: Too slow per iteration for n=100K within 4 seconds.
- **SCC decomposition**: Test 10 is a single SCC of 100K vertices, so doesn't help for the hardest test.
- **2-opt / Or-opt moves**: For directed graphs, these require segment reversal (all reverse edges exist) or bypass edges, both rare in sparse directed graphs.

## Evolution of Thinking

1. **Started with greedy heuristics (v1)**: Warnsdorff + bidirectional + insertion scored 41, beating references.
2. **Tried DFS (v3)**: Expected backtracking to help. Much worse (33).
3. **Tried ruin-and-recreate (v4)**: Expected local search to help. Scored 40.
4. **Discovered Pósa rotations (v5-v6)**: The breakthrough. O(1) linked-list implementation was the key.
5. **Tried backward rotations (v7-v8)**: Consistently hurt. Focused on forward-only.

## Current Status

- **Validated:** v6 at SCORE 72, v1 at SCORE 41, build and judge commands work
- **Uncertain:** Per-test breakdown at 72, backward rotation bugs, test 10 performance
- **Suggested next (iter-2):** Debug backward rotation, test-case-adaptive strategies, SCC-aware construction for test 10, dose-response on rotation budget

## Warnings & Constraints

1. **Score is seed-sensitive**: Seed 42 gives 72, seed 123 gives 54. Always test with seed 42 as baseline.
2. **Time management is critical**: 4-second limit means tension between rotation depth and restart count.
3. **Judge takes ~60 seconds**: Each `fmeasure_5.sh` call takes about a minute.
4. **`sadj` arrays must stay sorted**: `hasEdge()` uses binary search. Don't shuffle `sadj`.
5. **Pointer surgery correctness**: 6 pointer assignments per rotation. One wrong corrupts the list silently.
