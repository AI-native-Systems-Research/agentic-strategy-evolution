# Problem Framing — iter-3 Maximum Clique (#185)

## Research Question

What is the simplest algorithm that achieves score 100 on the maximum clique judge? Iter-1 proved BnB+DLS hybrid scores 100. Iter-2 proved BnB-only (no DLS) also scores 100. Iter-3 confirms the minimal winning solution at full scope in real mode.

Key source files:
- `solution.cpp` — the single file to edit. Currently contains a basic BnB without degeneracy ordering.
- Iter-2 `h-ablation.patch` — BnB-only with degeneracy ordering, proven score 100.

## System Interface

- **Build:** Judge compiles in Docker with g++ C++17. No local build needed.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` on stdout.
- **Code evidence:** Output is N lines of 0/1 (vertex inclusion). Format defined in problem statement.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp
```

## Baseline Validation

Ran BnB-only with degeneracy ordering solution. Exit code 0, output: `SCORE: 100`.

## Experimental Conditions

### h-main: BnB-only with degeneracy ordering (confirmed optimal)
Replace `solution.cpp` with the BnB-only algorithm: degeneracy ordering, greedy coloring bound with bitset color classes, greedy warm-starts, 1950ms BnB budget. No DLS fallback. This is the simplest solution proven to score 100.

### h-robustness: Tighter time budget (1000ms)
Same BnB-only algorithm but with `time_limit_ms = 1000` instead of 1950. Tests whether the solution has comfortable timing margin or depends on the full 1950ms budget.

## Success Criteria

- h-main: Score = 100 (confirming iter-2 ablation result at full scope).
- h-robustness: Score >= 90 indicates comfortable margin; score = 100 indicates BnB finishes well within half the budget on all test cases.

## Constraints

- Time limit: 2.0s per test case.
- Memory limit: 512MB.
- N ≤ 1000, M ≤ 500,000.
- Output: exactly N lines, each 0 or 1.

## Prior Knowledge

- RP-1: BnB with degeneracy ordering + coloring bound achieves score 100 within 2s. DLS fallback unnecessary.
- RP-2: Greedy alone scores ~34%. Exhaustive search essential.
- RP-3: DLS adds no improvement over BnB-only on this test set.
- Iter-1: BnB+DLS = 100, greedy = 33.8, basic BnB (no degeneracy) = 80.
- Iter-2: BnB+DLS = 100 (confirmed), BnB-only = 100 (DLS proven redundant).
