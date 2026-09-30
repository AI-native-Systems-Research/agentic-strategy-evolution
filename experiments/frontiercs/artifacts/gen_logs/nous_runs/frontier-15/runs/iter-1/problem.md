# Problem Framing: Frontier-CS Algorithmic Problem #15

## Research Question

What algorithm maximizes the Frontier-CS judge score for problem #15 — sorting a permutation via prefix-suffix swap operations using the fewest operations?

The problem asks: given a permutation of [1..n], apply operations that cut the sequence into three non-empty parts [Prefix|Middle|Suffix] and swap to [Suffix|Middle|Prefix]. The goal is to sort the permutation (reach [1,2,...,n]) using ≤ 4n operations, minimizing operation count.

Key source files:
- `algorithmic/problems/15/chk.cc` — the checker/scorer
- `algorithmic/problems/15/config.yaml` — 10 test cases, 1s time limit
- `solution.cpp` — the contestant's solution (our target)

## System Interface

- **Build command:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100 (continuous, higher is better)
- **Code evidence:**
  - `chk.cc:64` — `best_operations = 2 * n + 1` (the benchmark against which score is computed)
  - `chk.cc:78` — `ratio = std::max(0.0, std::min(1.0, your_value / best_value))` (scoring formula)
  - `chk.cc:57` — `check_sorted(p_contestant)` verifies result is identity permutation [1..n]
  - `config.yaml:2` — `time: 1s` (per-test time limit)
  - `config.yaml:6-7` — 10 test cases, all n=1000

## Scoring Formula

`score = 100 * clamp((4n - ops) / (4n - (2n+1)), 0, 1) = 100 * clamp((4n - ops) / (2n-1), 0, 1)`

For n=1000: score 100 requires ≤ 2001 operations. Score 0 at ≥ 4000 operations.

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh /home/ubuntu/frontier/gen_logs/frontier_15_nous_ws/solution.cpp
```

## Baseline Validation

- **Stub (0 operations):** SCORE: 0 — outputs nothing, checker fails
- **h-main algorithm (circular buffer rotation):** SCORE: 100 — sorts correctly in ≤ 2001 ops
- **Operation statistics (n=1000, 50 random trials):** min=1971, max=1996, mean=1985.1 ops (all ≤ 2n+1=2001)

## Experimental Conditions

### h-main: Circular Buffer Rotation Sort
Implements a 3-phase sorting algorithm:
1. **Phase 1**: Place element 1 at position 0 (1-2 operations)
2. **Phase 2**: For elements 2..n-2, use a 2-operation circular buffer rotation to extend the sorted prefix one position at a time
3. **Phase 3**: Handle last 2 elements with a 5-operation endgame sequence if needed

Worst case: 2 + 2(n-3) + 5 = 2n+1 operations. Expected: ~1985 for n=1000.

### h-control-negative: Greedy Lexicographic Minimization
At each step, try a small set of candidate operations {(1,1), (1,2), (2,1)} and pick whichever produces the lexicographically smallest permutation. This myopic approach should converge slowly and use many more operations.

## Success Criteria

- h-main achieves score ≥ 95 (ideally 100) on all test cases
- h-main uses ≤ 2n+1 operations consistently
- h-control-negative achieves measurably lower score than h-main

## Constraints

- Time limit: 1 second per test case
- n = 1000 for all 10 test cases
- Maximum 4n = 4000 operations allowed
- Solution must be valid C++17

## Prior Knowledge

This is the first iteration. No prior principles exist.
