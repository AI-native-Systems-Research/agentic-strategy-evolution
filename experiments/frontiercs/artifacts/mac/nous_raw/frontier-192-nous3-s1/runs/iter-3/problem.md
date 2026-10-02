# Problem Framing — Iteration 3

## Research Question

Can incremental gain tracking combined with longer SA restarts (0.30s vs 0.10s) push Max-Cut scores above iter-2's 87.5 baseline? The mechanism: O(1) gain lookup (vs O(degree) recomputation per rejected move) allows ~5x more SA iterations per second, and longer per-restart budgets enable deeper exploration of each basin.

Relevant source: `solution.cpp` (single-file solution for Max-Cut).

## System Interface

- **Build:** Automatic (judge compiles C++17 internally).
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` (0–100, continuous).
- **Time limit:** 1s per test case, 30 test cases.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp
```

## Baseline Validation

Current solution.cpp (iter-1 geometric SA) scores ~84.1 on one run. The iter-2 linear-cooling SA scored 87.52-87.57 in iter-2 executor runs. Today's probing shows 81-87.5 range depending on judge machine speed (bimodal distribution).

## Experimental Conditions

### h-main: Incremental gain + long SA + post-SA greedy

Full rewrite of solution.cpp implementing:
- **Xorshift128+ RNG** instead of mt19937 (faster random generation)
- **Incremental gain array** maintained across all flips (O(1) gain lookup vs O(degree) recomputation)
- **Linear-cooling SA** with T0=3.0, Tf=0.001 (same schedule as iter-2)
- **0.30s SA budget per restart** (~3 restarts in 0.90s total) — deeper exploration per restart
- **Post-SA greedy cleanup** to ensure each restart ends at a local optimum
- **Batch time checks** every 512 iterations to minimize chrono overhead

### h-ablation: Short SA with many restarts (same incremental gain)

Same incremental gain tracking and fast RNG, but with **0.03s SA budget per restart** (~30 restarts in 0.90s). Tests whether breadth (many shallow restarts) or depth (few deep restarts) is better, holding the gain-tracking improvement constant.

## Success Criteria

- h-main scores ≥ 87.5 consistently (median over 3 runs)
- h-main scores higher than h-ablation, confirming deeper restarts beat many shallow ones
- Score improvement over iter-2 baseline (87.5) is directionally positive

## Constraints

- 1s time limit per test case (30 cases)
- Internal budget 0.90s to avoid TLE
- Judge machine speed varies between runs (observed bimodal 84-85 vs 87.5+)
- Single-threaded execution only

## Prior Knowledge

- RP-1: FM + greedy + SA restarts achieves ~87 (iter-1)
- RP-2: RNG-seed variance can cause ~5-point drops
- RP-3: Linear cooling outperforms geometric cooling by ~1 point (87.5 vs 86.6)
- RP-2-update: Linear cooling reduces variance to ~0.05 points

From iter-3 probing:
- BLS scored 79-82 — much worse than SA (dead end)
- Cosine reheating scored 87.49-87.53 — slightly worse than linear cooling
- Long SA (0.30s) gave the most consistent 87.5+ scores in initial testing
- Short SA (0.03s) showed higher variance (78-87.6)
- Perturbation restarts from best didn't improve over random restarts
