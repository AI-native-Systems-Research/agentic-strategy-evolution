# Problem Framing — Iteration 3

## Research Question

Can the circular buffer rotation sort be further optimized by extending the BFS-optimal endgame from the last 3 elements to the last 4 elements, and what is the theoretical tight worst-case operation bound for this algorithm family?

The core mechanism is implemented in `solution.cpp` (the worktree's single file). The checker at `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:64` hardcodes `best_operations = 2 * n + 1`, and the clamping at line 78 means any solution using ≤ 2n+1 operations scores 100 (the maximum achievable score).

## System Interface

- **Build command:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run:** `./solution < input.in` (reads n and permutation from stdin, writes operations to stdout)
- **Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp` — prints `SCORE: <n>`
- **Output format:** First line: number of operations m. Next m lines: `x y` per operation.
- **Code evidence:**
  - `chk.cc:64` — `int best_operations = 2 * n + 1;` (scoring benchmark)
  - `chk.cc:78` — `ratio = std::max(0.0, std::min(1.0, your_value / best_value));` (clamp to [0,1])
  - `chk.cc:51` — `if (x <= 0 || y <= 0 || x + y >= n)` (operation validity)
  - `chk.cc:57` — `check_sorted()` (requires strictly increasing output)
  - `chk.cc:43` — `if (m < 0 || m > 4 * n)` (operation count limit)

## Baseline Command

```bash
cd /home/ubuntu/frontier/gen_logs/frontier_15_nous_ws
g++ -O2 -std=c++17 -o solution solution.cpp
bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp
```

## Baseline Validation

Ran the current solution (iter-1 algorithm with 5-op endgame). Exit code 0. Output: `SCORE: 100`. Per-case operation counts: 1985–1996, average ~1990. All 10 test cases have n=1000. All operations valid, all outputs correctly sorted.

## Experimental Conditions

### h-main: k=4 BFS-Optimal Endgame Algorithm

**Change from baseline:** Replace `solution.cpp` with the k=4 endgame algorithm:
1. Main loop places elements 2 through n-4 (instead of n-2 or n-3) using the standard 2-op circular buffer rotation.
2. The last 4 elements are handled by a 23-case dispatch, each with a BFS-proven optimal operation sequence (max 4 ops).
3. For small n (≤5), falls back to the iter-1 algorithm.

**Verified improvement:** All 23 non-trivial configurations of the last 4 elements solved in ≤4 ops for all n ∈ {6, 7, 8, 10, 20, 100, 500, 1000}. Distribution: 5 configs need 2 ops, 6 need 3, 12 need 4.

**Worst-case analysis:**
- Element 1 placement: ≤2 ops
- Main loop (elements 2 to n-4): ≤2(n-5) ops
- k=4 endgame: ≤4 ops
- Total: ≤2n-4 (1996 for n=1000)

**Empirical validation on 200 random n=1000 permutations:** min=1971, max=1993, avg=1983.5. All under 2n-4=1996.

## Success Criteria

- Score 100 on the official judge (all 10 test cases)
- All per-case operation counts ≤ 2n-4 = 1996 (tighter than iter-2's 2n-2 = 1998 bound)
- Average operation count ≤ 1985 (improved from iter-2's ~1984)

## Constraints

- Time limit: 1 second per test case
- Memory limit: 512 MB
- Maximum 4n = 4000 operations per test case
- Score capped at 100 (ratio clamped to [0,1] in checker)
- All test cases have n = 1000

## Prior Knowledge

- **RP-1:** Circular buffer rotation sort achieves ≤2n-2 ops with BFS-3 endgame (iter-1 & iter-2 evidence). Iter-3 extends this to ≤2n-4 with BFS-4 endgame.
- **RP-2:** For d=1 edge case, decomposition d1=2, d2=l-1 resolves the constraint (algebraic identity, iter-1).
- **RP-3:** Op2 (prefix restoration) is essential — removing it yields score 0 (iter-2 ablation, confirmed).

The score ceiling of 100 has been reached since iter-1. Iter-3 focuses on the tighter worst-case bound and confirming that the k=4 endgame is a genuine generalization.
