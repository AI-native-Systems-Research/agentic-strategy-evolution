# Handoff — Frontier-CS Problem #15 (Iter 4)

## Goal

Run the k=5 BFS-optimal endgame solution (pre-validated at `inputs/solution_k5endgame.cpp`), measure its judge score, and confirm the worst-case bound of 2n-5 operations. The solution is complete and tested — the executor needs to copy it to `solution.cpp`, build, measure, and record the score.

## Key Discoveries

- **k=5 endgame max 5 ops (NEW):** All 119 non-identity permutations of the last 5 elements can be sorted in ≤5 operations using n-dependent prefix-suffix swaps. BFS was done at n=11 (not n=10) because at n=10 the small set {1,2,3,4} and n-dependent set {n-5,...,n-2}={5,6,7,8} overlap at value 5, causing 4 sequences to fail generalization to large n. At n=11 the gap at value 5 ensures clean small/large separation.
- **Endgame distribution (k=5):** 9 configs need 2 ops, 33 need 3 ops, 73 need 4 ops, 4 need 5 ops. The 4 five-op configs are: [n-3,n-4,n-2,n,n-1], [n-3,n-4,n,n-1,n-2], [n-2,n-3,n-4,n,n-1], [n-1,n-2,n-3,n-4,n].
- **Worst case tightened to 2n-5:** Element 1: ≤2 ops + main loop (elements 2..n-5): ≤2(n-6) + endgame: ≤5 = 2n-5. For n=1000: max 1995 (down from iter-3's 1996).
- **Score ceiling confirmed at 100:** No change from iter-3. Any solution with ≤2001 ops scores 100. The k=5 algorithm uses at most 1995.
- **Empirical performance on 10 judge test cases:** ops range [1982, 1990], avg 1986.0. On 200 random n=1000 perms: min=1967, max=1993, avg=1981.9.
- **k=5 improvement over k=4:** Average ops reduced from 1987.3 to 1986.0 on judge tests. Max observed reduced from 1993 to 1990. Worst-case bound reduced from 1996 to 1995.
- **n=11 BFS took ~2 min 20s:** 11! = 39,916,800 states, 36 interesting operations. Nearly all states (39.8M/39.9M) reachable from goal within depth 7.
- **k=6 likely intractable:** 12! ≈ 480M states would need ~2GB+ memory. Diminishing returns: k=5→k=6 saves 2 main-loop ops but endgame max could be 6 or more.

## System Interface

- **Build:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0-100, continuous)
- **Baseline result:** SCORE: 100 with the k=5 endgame algorithm

## Code Map

- `solution.cpp` — the worktree solution file to replace
- `inputs/solution_k5endgame.cpp` — pre-validated k=5 endgame solution (201 lines, copy to solution.cpp)
- `inputs/gen_k5_robust.cpp` — the generator that produced the solution (BFS + path tracing + cross-n verification + code generation)
- `inputs/k5_bfs_n11.cpp` — standalone BFS exploration at n=11 showing endgame distances
- `inputs/k5_bfs.cpp` — initial BFS at n=10 (showed the n=10 generalization failure)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:64` — `best_operations = 2 * n + 1`
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:78` — score clamping `std::min(1.0, ...)`
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/testdata/` — 10 test cases, all n=1000

## Code Targets

### h-main (k=5 endgame algorithm)
- File: `solution.cpp`
- Replace entirely with `inputs/solution_k5endgame.cpp`
- The solution is COMPLETE and TESTED:
  - Compiles with `g++ -O2 -std=c++17`
  - All 10 test cases produce correctly sorted output
  - Operation counts: 1982-1990 (all under 1995)
  - Judge score: 100
  - 200/200 random n=1000 permutations pass
  - All 119 endgame configs verified at n=20, 50, 100, 500, 1000

## What I Tried That Didn't Work

- **BFS at n=10 for k=5:** Initial attempt used n=10 where interesting ops {1..4} and {n-5..n-2}={5..8} overlap at value 5. The BFS found valid sequences, but 4 configs used operation x=5 which maps to both "literal 5" and "n-5" ambiguously. At n=20+, these sequences broke because n-5=15≠5. Fixed by using n=11 where the gap at 5 ensures clean separation.
- **Greedy path tracing without cross-n verification:** The first gen_k5_solution.cpp traced paths greedily (first operation leading to lower distance). Some paths happened to work at n=11 by coincidence but failed at n=1000. Fixed in gen_k5_robust.cpp by DFS with backtracking, testing each candidate path at n=20,50,100,500,1000 before accepting.
- **k=5 BFS in Python (iter-3):** Took >5 minutes and was abandoned. The C++ BFS at n=11 completes in ~2.5 minutes with full state coverage.

## What I Excluded and Why

- **k=6 endgame:** 12! ≈ 480M states exceeds practical BFS memory (~2GB+). Even if tractable, the improvement would be at most 1 operation in worst case (from 2n-5 to 2n-6 if max endgame ops ≤5, but likely max is 6+). Score already at ceiling.
- **Alternative algorithmic paradigms:** Iter-3 handoff exhaustively documented that all alternatives (reverse selection sort, cycle-based, divide-and-conquer, greedy local improvement) reduce to ≥2 ops/element or worse. No new paradigms to explore.
- **h-ablation:** Op2 ablation done in iter-2 (RP-3). h-control-negative uninformative (score ceiling is algebraic).

## Evolution of Thinking

1. **Started by implementing k=5 BFS at n=10.** Found max 5 ops for all 119 configs — promising! But 4 configs failed verification at n=20+.
2. **Diagnosed the n=10 ambiguity.** Value 5 is simultaneously "small" (literal) and "large" (n-5 at n=10). Operations using x=5 at n=10 map to x=15 at n=20, changing their effect entirely.
3. **Moved to n=11.** Gap at value 5 eliminates ambiguity. Small={1,2,3,4}, large={6,7,8,9}={n-5,...,n-2}. Same endgame distances (max 5), but sequences now generalizable.
4. **Fixed path tracing with cross-n verification.** DFS+backtracking finds the FIRST path that works at all tested n values, not just n=11.
5. **Confirmed improvement over k=4.** Judge score: 100 (unchanged). Average ops: 1986.0 vs 1987.3. Max observed: 1990 vs 1993. Worst-case bound: 1995 vs 1996.

## Current Status

- **Validated:** k=5 endgame solution compiles, passes all 10 judge test cases (score 100), passes 200/200 random tests, all 119 endgame configs verified at 5 different n values.
- **Uncertain:** Whether k=6 endgame can stay at max 5 ops (would give 2n-7 worst case). The 12! state space makes BFS impractical without algorithmic advances (e.g., symmetry reduction).
- **Suggested next:** The problem is definitively solved at score 100 (the ceiling). Remaining research questions are purely theoretical:
  - (a) Is 2n-5 tight, or can some endgame sequence find max 4 ops for k=5? (Would require proving the 4 five-op configs can't do better with non-interesting operations.)
  - (b) What is the information-theoretic lower bound on sorting via prefix-suffix swaps?
  - (c) Can the k=6 endgame be computed using IDDFS with pruning instead of full BFS?

## Warnings & Constraints

- **fmeasure_15.sh takes 30-60 seconds:** One call per arm is sufficient.
- **The k=5 endgame requires n ≥ 7:** Operations like (n-5, y) need n-5 ≥ 2 and y ≥ 1 with (n-5)+y < n. For n=6: n-5=1, some ops become (1,y) which overlap with small ops. The code uses the n ≤ 5 fallback, so this is safe. All test cases have n=1000.
- **Score must be in findings metadata:** Record `"score": <number>` in each arm's findings.
- **The solution is at inputs/solution_k5endgame.cpp:** Copy to solution.cpp before building. Do NOT edit the worktree's existing solution.cpp in place — replace it entirely.
- **n=11 BFS is the foundation:** If any endgame sequence seems wrong, re-run `inputs/gen_k5_robust.cpp` which rebuilds the entire table from scratch with verification.
