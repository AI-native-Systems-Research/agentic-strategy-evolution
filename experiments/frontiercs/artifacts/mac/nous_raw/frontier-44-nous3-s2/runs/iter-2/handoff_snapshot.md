# Handoff — Iter 2

## Goal

Push judge score above 78.9 (iter-1) by implementing iterated local search with double-bridge perturbation, multi-city Or-opt (1-3), and larger KNN (20) in `solution.cpp`.

## Key Discoveries

- **Iter-1 scored 78.881** with grid-NN + SA (NN-guided 2-opt, single-city Or-opt, prime post-pass). This is the baseline to beat.
- **Or-opt only relocates single cities in iter-1** — extending to 2-3 city segments is a proven TSP improvement that finds moves single-city misses.
- **No perturbation mechanism in iter-1** — SA gets stuck in local optima. Double-bridge (non-sequential 4-opt) is the standard escape technique used by LKH.
- **KNN=12 in iter-1** — increasing to 20 gives wider search neighborhood for NN-guided 2-opt.
- **Primes < 200K: 17,984; penalty positions at max N: 20,000** — ~10% of penalty positions can't be covered by primes.
- **Time budget**: 2s total, construction ~0.1s, SA+perturbation ~1.65s, prime post-pass ~0.05s.
- **Cannot compile locally** — `bits/stdc++.h` only works on judge's g++. Submit directly.

## System Interface

- **Build:** None — judge compiles internally.
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout.
- **Baseline result:** Iter-1 h-main = 78.881.

## Code Map

- `solution.cpp:1` — the only file to edit. Start from the iter-1 patch.
- `runs/iter-1/patches/h-main.patch` — the 78.9-scoring solution to build upon.
- Iter-1 key functions:
  - `constructNN()` — grid-based nearest-neighbor construction (~line 40 in patch).
  - `buildNN()` — builds KNN list for NN-guided 2-opt (~line 72). **Change KNN from 12 to 20.**
  - `twoOptDeltaFast()` — O(1+seg/10) delta for 2-opt (~line 108). Keep as-is.
  - SA loop (~line 145) — main optimization. Modify to add Or-opt segments and double-bridge.
  - Prime scheduling (~line 230) — post-pass. Keep as-is.

## Code Targets

### h-main → `solution.cpp`
Start from iter-1 patch, then:
1. **`buildNN()`**: Change `KNN=min(12,N-1)` to `KNN=min(20,N-1)`.
2. **SA loop (Or-opt section)**: Extend Or-opt to handle segments of 1, 2, and 3 cities. For a segment of size k starting at position i, remove the k cities and reinsert them at a random position j. Delta computation touches the 2k+2 edges at the cut/insert points plus any penalty positions in the affected range.
3. **New: double-bridge function**: Implement `doubleBridge()` — randomly select 3 cut points in [1, N-1], creating 4 segments A, B, C, D. Reconnect as A-D-C-B. This is a non-sequential 4-opt move that 2-opt cannot reverse.
4. **SA outer loop**: After SA stalls (no improvement for X iterations) or at regular time intervals, apply double-bridge and restart SA from the perturbed tour. Keep track of the best tour seen across all restarts.
5. **Time management**: Construction 0.1s, SA+perturbation cycles until 1.75s, prime post-pass 0.05s.

### h-ablation → `solution.cpp`
Same as h-main but remove the double-bridge perturbation. Run continuous SA for the full budget.

## What I Tried That Didn't Work (accumulated from iter-1)

- **Sequential tour**: Scores 0 — it IS the baseline.
- **Naive 2-opt with full recompute**: Only 17.6. O(N) per move is too slow.
- **Large segment 2-opt without fast delta**: Penalty recomputation kills throughput.
- **Compiling locally with `bits/stdc++.h`**: Fails on macOS clang.

## What I Excluded and Why

- **LK-style moves**: Complex to implement correctly with penalty structure. Double-bridge + 2-opt/Or-opt is simpler and often competitive.
- **Genetic algorithms**: Crossover for TSP is complex; SA+perturbation is more robust within 2s.
- **Exact solvers**: N=200K is far too large.
- **3-opt**: Complex delta computation with penalties. Double-bridge achieves similar diversification with simpler implementation.

## Evolution of Thinking

Iter-1 established that fast delta + NN-guided moves are the key to high scores. The 78.9 result suggests the SA is doing good local search but may be stuck in a suboptimal basin. The natural next step is perturbation (double-bridge) to escape, combined with incremental improvements to move quality (multi-city Or-opt, larger KNN). This follows the standard LKH/ILS pattern for TSP.

## Current Status

- **Validated:** Judge works, iter-1 scores 78.9, output format confirmed, fast delta correct.
- **Uncertain:** Whether double-bridge will improve score given the 2s time limit (perturbation wastes some SA iterations). Whether Or-opt for 2-3 cities adds meaningfully over single-city.
- **Suggested next:** If iter-2 plateaus around 82-85, consider: (1) LK-style moves (3-opt with backtracking), (2) population-based approaches (multiple tours evolved in parallel), (3) problem-specific construction heuristics that respect penalty structure.

## Warnings & Constraints

- **Do NOT compile locally** — `bits/stdc++.h` not available on macOS. Submit directly to judge.
- **Time limit 2 seconds** — double-bridge + restart must fit within budget. Leave 0.2s margin.
- **Output format strict**: N+1 on first line, then N+1 city IDs, one per line.
- **Judge runs multiple test cases** — score is averaged. Solution must work well across sizes.
- **Or-opt delta for multi-city segments**: Must account for all penalty positions in the affected range, not just the endpoints. Verify by comparing incremental vs full recompute on a small test.
