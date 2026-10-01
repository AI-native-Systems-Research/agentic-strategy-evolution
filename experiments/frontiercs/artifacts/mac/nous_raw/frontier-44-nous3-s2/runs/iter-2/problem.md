# Problem Framing — Iteration 2

## Research Question

How can we push the judge score above 78.9 (iter-1 best) for TSP problem #44 with carrot constraint? The iter-1 solution used grid-NN construction + SA with NN-guided 2-opt and Or-opt (single-city relocate) + prime scheduling post-pass. The primary bottleneck is that SA gets stuck in local optima without a perturbation mechanism, and the Or-opt only moves single cities.

Key source files:
- `solution.cpp:1` — the only file; entire solution lives here.
- Iter-1 patch at `runs/iter-1/patches/h-main.patch` — the 78.9-scoring solution.

## System Interface

- **Build:** None — judge compiles `solution.cpp` internally with g++.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output:** Single line `SCORE: <n>` where n ∈ [0, 100].
- **Code evidence:** `fmeasure_44.sh:5` calls `frontier eval algorithmic 44 "$1" --json`.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

## Baseline Validation

Iter-1 h-main scored 78.881. The current `solution.cpp` in the worktree is the original stub (scores 0). The iter-1 patch is at `runs/iter-1/patches/h-main.patch`.

## Experimental Conditions

### h-main: Enhanced SA with double-bridge + multi-city Or-opt

Build on iter-1's solution (78.9) with three key improvements:

1. **Or-opt for segments of 1, 2, and 3 cities** — Currently only relocates single cities. Moving pairs and triples finds improvements that single-city moves miss, especially in clustered regions.

2. **Double-bridge perturbation (4-opt) with iterated local search** — After SA converges, apply a double-bridge (non-sequential 4-opt) perturbation to escape local optima, then re-run SA from the perturbed tour. This is the key technique in LKH-style solvers.

3. **Larger KNN list (20 instead of 12)** — More neighbor candidates means NN-guided 2-opt explores a wider neighborhood, finding better moves.

4. **Integrated penalty-aware neighbor selection** — When selecting NN-guided moves near penalty positions (every 10th step), bias toward moves that place prime cities at those positions.

### h-ablation: Same as h-main but without double-bridge perturbation

Tests whether the double-bridge restart mechanism contributes meaningfully, or if the improvements come entirely from better moves (Or-opt segments + larger KNN).

## Success Criteria

- h-main scores strictly higher than 78.9 (iter-1 best).
- h-main scores higher than h-ablation (demonstrates double-bridge value).

## Constraints

- Time limit: 2 seconds per test case.
- Memory limit: 512 MB.
- Must use `bits/stdc++.h` (g++ only — cannot compile locally on macOS).
- Output format: first line N+1, then N+1 lines of city IDs.

## Prior Knowledge

- RP-1: NN-guided 2-opt outperforms random 2-opt by ~2.3x (78.9 vs 33.5).
- RP-2: O(1+segment/10) delta computation for 2-opt is correct and efficient.
- Iter-1 handoff: sequential tour = 0 (is the baseline), grid-NN construction works, prime scheduling post-pass helps.
