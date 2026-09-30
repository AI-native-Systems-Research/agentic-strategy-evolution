# Problem Framing — Iteration 2

## Research Question

Can the circular buffer rotation algorithm be improved by optimizing the endgame handling (last 3 elements), and is the prefix-restoration step (Op2) essential to the mechanism?

The iter-1 algorithm achieves score 100 using a 2-operation-per-element circular buffer rotation with a 5-operation endgame for the last 2 elements. BFS analysis reveals the endgame can be solved in 4 operations (for n≥5), and handling the last 3 elements as a unit saves up to 4 operations total. We test the optimized algorithm and ablate Op2 to confirm mechanism necessity.

**Key source files:**
- `solution.cpp` — the solution implementation (entire file is the controllable knob)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:64` — `best_operations = 2 * n + 1` defines the scoring benchmark
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:78` — score clamping: `ratio = max(0.0, min(1.0, your_value / best_value))`
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:57` — `check_sorted()` validation: requires strictly sorted output

## System Interface

- **Build command:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **CLI flags:** The solution reads from stdin (n, then permutation), writes to stdout (m operations, then x y pairs).
- **Judge command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp`
- **Code evidence:**
  - `chk.cc:64` — `int best_operations = 2 * n + 1;` (benchmark for scoring)
  - `chk.cc:43` — `if (m < 0 || m > 4 * n)` (operation count validation)
  - `chk.cc:51` — `if (x <= 0 || y <= 0 || x + y >= n)` (operation validity check)
  - `chk.cc:78` — `ratio = std::max(0.0, std::min(1.0, your_value / best_value))` (score clamping to [0,1])
- **Output format:** Judge prints `SCORE: <n>` where n is 0-100.

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp
```

## Baseline Validation

The iter-1 circular buffer rotation algorithm (currently in `solution.cpp`) was validated:
- **Exit code:** 0
- **Output:** `SCORE: 100`
- **Operation count statistics (500 random n=1000 permutations):** avg=1985.4, max=2000, all ≤ 2001

## Experimental Conditions

### h-main: Optimized last-3-element endgame

Replace the current algorithm's main loop terminus and endgame handling:
- Change main loop from `targ <= n-2` to `targ <= n-3`
- Replace the 5-operation endgame for last 2 elements with BFS-optimal sequences for last 3 elements:
  - `[n-2, n, n-1]` → 4 ops: `(1,2), (1,n-2), (1,2), (2,2)`
  - `[n-1, n-2, n]` → 4 ops: `(1,1), (1,2), (2,2), (2,1)`
  - `[n-1, n, n-2]` → 2 ops: `(n-3,2), (1,n-3)`
  - `[n, n-2, n-1]` → 2 ops: `(n-3,1), (2,n-3)`
  - `[n, n-1, n-2]` → 3 ops: `(1,1), (1,3), (1,n-2)`
- Reduces worst-case from 2n+1 to 2n-2 operations
- Verified correct on all n=5..1000 and 200 random n=1000 permutations (0 failures)
- Operation count: avg=1984.0, max=1996 (vs original avg=1985.4, max=2000)

### h-ablation: Single-operation placement without prefix restoration

Ablate Op2 (the prefix-restoration step) from the 2-op rotation scheme:
- For each element, apply ONLY Op1 (buffer rotation) and SKIP Op2 (prefix restoration)
- The sorted prefix invariant breaks immediately after the first placement
- Without the invariant, subsequent element searches and placements operate on incorrect assumptions
- Expected outcome: array is NOT sorted after all operations → score 0
- Tested on 5 random n=1000 permutations: 0/5 produced sorted output

## Success Criteria

- **h-main:** Score = 100 on the judge (all 10 test cases). Operation count ≤ 1998 (= 2n-2) in worst case.
- **h-ablation:** Score = 0 on the judge (output permutation is not sorted).

## Constraints

- All test cases have n=1000 (verified from iter-1 handoff)
- Time limit: 1 second per test case (O(n²) algorithms are fine)
- Memory limit: 512 MB
- Maximum 4n = 4000 operations per test case
- Score formula: `100 * clamp((4000 - ops) / (4000 - 2001), 0, 1)`

## Prior Knowledge

- **RP-1 (high confidence):** The 2-op circular buffer rotation sorts any permutation of length n≥4 in ≤ 2n+1 operations. Confirmed in iter-1.
- **RP-2 (high confidence, algebraic):** The d=1 edge case uses d1=2, d2=l-1 decomposition. Confirmed in iter-1.
- **Iter-1 finding:** Score 100 confirmed (h-main CONFIRMED), mechanism validated against no-operation control (h-control-negative CONFIRMED at score 0).
- **New in iter-2:** BFS analysis shows the 5-op endgame can be reduced to 4 ops for n≥5, and the last-3-element handling further reduces worst case from 2n+1 to 2n-2.
