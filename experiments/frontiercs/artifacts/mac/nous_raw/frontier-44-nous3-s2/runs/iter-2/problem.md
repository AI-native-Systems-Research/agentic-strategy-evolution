# Problem Framing — Iteration 2

## Research Question

Can targeted post-SA optimization (greedy edge-fix pass + penalty-aware tour direction selection) push the judge score above iter-1's ~69.5 for TSP problem #44 with carrot constraint?

Iter-1 established grid-NN + SA (40% swap + 60% boundary-2-opt) as the baseline. Extensive exploration in iter-2 found that:
- **2-opt contributes nothing**: 100% swap gives the same ~69.5 as 40% swap + 60% 2-opt. The boundary-only 2-opt approximation cannot find improving moves in a post-NN tour.
- **NN-guided moves with pos[] are too slow** for N=200K: the O(segment) pos[] update eats the throughput gain.
- **Double-bridge perturbation hurts**: the weak SA can't recover the destroyed structure.
- **Random swaps provide essential long-range diversification**: below ~30% swap rate, SA fails to improve NN at all.

The remaining opportunities are:
1. A greedy edge-fix post-pass that targets the worst (longest) edges with best-of-K swaps.
2. Choosing the cheaper direction (forward vs reversed) for the NN tour before SA, exploiting the penalty structure's directionality.

Key source: `solution.cpp:1` — the only file.

## System Interface

- **Build:** None — judge compiles internally with g++.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output:** `SCORE: <n>` on stdout.
- **Code evidence:** `fmeasure_44.sh` calls `frontier eval algorithmic 44 "$1" --json`.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

## Baseline Validation

Iter-1 h-main patch: SCORE: 69.496 (measured, multiple consistent runs).
Current h-main (iter-1 + reversed-tour + greedy edge-fix): SCORE: 69.503-69.511 (marginal improvement).

## Experimental Conditions

### h-main: Iter-1 SA + reversed-tour check + greedy edge-fix post-pass

Builds on iter-1's solution with two additions:
1. **Reversed-tour direction check**: After NN construction, also evaluate the reversed tour (reversed internal city order). Since penalty positions depend on step index, the reversed tour may have lower penalized cost. Pick the cheaper direction before SA.
2. **Greedy edge-fix post-pass**: After SA converges, identify the top-50 longest penalized edges. For each, try 200 random swaps targeting that position. Accept the best-improving swap. Repeat for 5 passes.

### h-ablation: Iter-1 SA only (no post-SA optimization)

Pure iter-1 code for comparison. Tests whether the post-SA additions contribute.

## Success Criteria

- h-main scores strictly higher than iter-1 (69.5).
- h-main scores higher than h-ablation (demonstrates post-SA value).

## Constraints

- Time limit: 2 seconds per test case.
- Memory limit: 512 MB.
- Cannot compile locally (`bits/stdc++.h` requires g++).
- Output format: first line N+1, then N+1 city IDs, one per line.

## Prior Knowledge

- RP-1: Grid-NN accounts for ~93% of final score (64.5/69.5).
- RP-2: Penalty structure contributes <1% to total cost.
- RP-3: Boundary-only 2-opt delta is comparable to exact (but 2-opt itself contributes nothing to score improvement — all improvement comes from swap moves).
