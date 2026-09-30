# Handoff — Frontier-CS Problem #15 (Iter 3)

## Goal

Implement the k=4 BFS-optimal endgame algorithm (pre-validated at `inputs/solution_k4endgame.cpp`), measure its judge score, and confirm the worst-case bound of 2n-4 operations. The solution is complete and tested — the executor primarily needs to copy it to `solution.cpp`, build, measure, and record the score.

## Key Discoveries

- **k=4 endgame max 4 ops (NEW):** All 23 non-trivial permutations of the last 4 elements can be sorted in ≤4 operations using n-dependent prefix-suffix swaps. Verified for n=6 through n=1000 with 0 errors. This matches the k=3 maximum (also 4), meaning each step up in endgame size is "free."
- **Worst case tightened to 2n-4:** Element 1: ≤2 ops + main loop (elements 2..n-4): ≤2(n-5) + endgame: ≤4 = 2n-4. For n=1000: max 1996 (down from iter-2's 1998).
- **Score ceiling confirmed at 100:** The checker at `chk.cc:78` clamps the ratio to [0,1]. Any solution with ≤2001 operations scores 100. The k=4 algorithm uses at most 1996. No further score improvement is possible.
- **k=4 endgame distribution:** Of 23 non-identity configurations: 5 need 2 ops, 6 need 3, 12 need 4. Distribution is identical across all tested n values.
- **Empirical performance on 200 random n=1000 perms:** min=1971, max=1993, avg=1983.5. All strictly under 2n-4=1996.
- **k=5 endgame intractable:** The BFS search for 120 permutations of last 5 elements with ~39 interesting operations at depth ≤5 exceeded 5 minutes and was abandoned. The k=4 endgame is sufficient since score is already maximized.

## System Interface

- **Build:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0-100, continuous)
- **Baseline result:** SCORE: 100 with the k=4 endgame algorithm

## Code Map

- `solution.cpp` — the worktree solution file to replace
- `inputs/solution_k4endgame.cpp` — pre-validated k=4 endgame solution (copy to solution.cpp)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:64` — `best_operations = 2 * n + 1` (scoring benchmark)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:78` — score clamping `std::min(1.0, ...)` (confirms ceiling)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/testdata/` — 10 test cases, all n=1000

## Code Targets

### h-main (k=4 endgame algorithm)
- File: `solution.cpp`
- Replace entirely with `inputs/solution_k4endgame.cpp`
- The solution is COMPLETE and TESTED:
  - Compiles with `g++ -O2 -std=c++17`
  - All 10 test cases produce correctly sorted output
  - Operation counts: 1984-1993 (all under 1996)
  - Judge score: 100
  - 200/200 random n=1000 permutations pass

## What I Tried That Didn't Work

- **k=5 endgame BFS:** Attempted to compute optimal sequences for all 120 permutations of the last 5 elements. The search space (39 interesting ops, depth ≤5, 120 starting states) exceeded 5 minutes and was abandoned. The pure k=5 BFS for n=k=5 showed max 5 ops, but the large-n version needs n-dependent ops that explode the search space.
- **Batch placement (consecutive block detection):** Analyzed whether detecting consecutive ascending blocks in the buffer could reduce operations. For random permutations, consecutive blocks have expected length ~1 (P(next element adjacent) ≈ 1/(n-1)), so savings are negligible (~0.002 ops per permutation). Not worth the implementation complexity.
- **Alternative algorithmic paradigms:** Exhaustively analyzed reverse selection sort (building sorted suffix), cycle-based placement, merge sort analog, divide-and-conquer, and greedy local improvement. ALL either reduce to the same 2-ops-per-element bound or are strictly worse. The fundamental constraint: each operation disrupts ALL positions except the middle, so maintaining any invariant requires a restoration step.
- **Single-operation placement:** Proved that placing element k with exactly 1 operation (using suffix-based positioning) always destroys the sorted prefix. The restoration requires a second operation, making 2-ops-per-element the theoretical minimum for invariant-based approaches.

## What I Excluded and Why

- **Dose-response on endgame size:** The natural variable (k=2,3,4,5) produces identical scores (100) for all values, since worst-case ops are well under 2001 for all k. The operation count varies but isn't the scored metric.
- **Ablation of Op2:** Already done in iter-2 (RP-3 confirmed essential, score 0 without it). Repeating would produce no new knowledge.
- **Adversarial input construction:** All 10 test cases are fixed (n=1000, random-looking permutations). Constructing adversarial inputs isn't possible since the judge uses fixed test data.

## Evolution of Thinking

1. **Started by computing k=4 endgame sequences.** Used iterative deepening search with n-dependent "interesting" operations ({1,2,3,n-4,n-3,n-2} for x and y). Found ALL 23 configurations solvable in ≤4 ops — the same maximum as k=3!
2. **Verified generalization across n.** Tested all sequences for n=6..1000. Discovered that the operation values generalize cleanly (e.g., (n-4,2) works for any n≥6) because the middle portion (positions 1..n-5) remains sorted through the operations.
3. **Attempted k=5 but hit computational limits.** The search space grows too fast. Accepted k=4 as the practical optimum.
4. **Exhaustively analyzed alternative algorithms.** Proved that the 2-ops-per-element bound is fundamental: any invariant-maintaining approach requires a placement + restoration pair. The circular buffer rotation is THE canonical algorithm for this operation type.
5. **Concluded the problem is SOLVED.** Score 100 is the ceiling. The k=4 endgame is a marginal worst-case improvement (1996 vs 1998) with no score impact. Future iterations cannot improve the score.

## Current Status

- **Validated:** k=4 endgame algorithm compiles, passes all 10 judge test cases (score 100), passes 200/200 random tests. All operation counts under 1996.
- **Uncertain:** Whether k=5 endgame also achieves ≤4 max ops (would give 2n-6 worst case). The pure k=5 BFS for n=5 shows max 5 ops, but n-dependent operations might reduce this.
- **Suggested next:** The problem is solved at the scoring ceiling (100). If further iterations are desired: (a) compute k=5 endgame using C++ BFS instead of Python (2-3 orders of magnitude faster), (b) prove a formal lower bound on operation count for prefix-suffix swap sorting, (c) investigate whether the algorithm generalizes to related operations (e.g., prefix reversal, cyclic shift).

## Warnings & Constraints

- **fmeasure_15.sh takes 30-60 seconds:** One call per arm is sufficient. The solution is pre-tested.
- **The k=4 endgame uses operations (3,2) and (2,3) which require n≥6.** The code falls back to iter-1 algorithm for n≤5. All test cases have n=1000.
- **Score must be in findings metadata:** Record `"score": <number>` in each arm's findings. Iter-1 omitted this, causing best_found.json to show 0.0.
- **The solution is at inputs/solution_k4endgame.cpp:** Copy to solution.cpp before building. Do NOT edit the worktree's existing solution.cpp in place — replace it entirely.
