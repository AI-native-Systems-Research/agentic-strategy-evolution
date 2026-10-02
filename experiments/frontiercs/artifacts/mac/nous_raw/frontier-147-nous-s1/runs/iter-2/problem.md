# Problem Framing — Iteration 2

## Research Question
Can multi-cell greedy initialization (using max-expansion bounds per direction) improve the starting configuration enough to raise the SA-based rectangle packing score above the iter-1 baseline of ~89?

The mechanism under test: replacing single-cell expansion with bounds-aware multi-cell expansion in the greedy init phase, allowing each rectangle to grow by multiple cells per step using the same max_expand_left/right/down/up functions used in SA. This fills the grid faster (0.12s vs 0.3s), giving SA more time and a better starting point.

Key source files:
- `solution.cpp:1` — entire solution, the only file

## System Interface
- **Build:** Judge compiles automatically; no local build needed.
- **CLI flags:** The solution reads from stdin and writes to stdout. No flags.
- **Output format:** N lines, each with `a b c d` (rectangle coordinates).
- **Measurement:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp` — prints `SCORE: <n>`.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```

## Baseline Validation
Iter-1 SA with valid-by-construction moves (0.3s greedy init, 2.55s SA, T0=0.05→T1=0.001) scores in the range 85–90 across different judge test sets.

The new multi-cell init approach scored 90.5 in a probe run (vs 88.6 and 89.8 for the single-cell 0.3s and 0.15s variants respectively). All scores measured via the judge command above.

## Experimental Conditions

### h-main: Multi-cell greedy init + SA
Replace the single-cell greedy expansion loop with a bounds-aware multi-cell expansion that uses max_expand_left/right/down/up to grow each rectangle by up to half its current dimension per step. Init time: 0.12s. SA time: ~2.73s. SA approach unchanged (valid-by-construction edge moves, T0=0.05, T1=0.001).

### h-ablation: Single-cell greedy init + SA (iter-1 approach)
Identical SA but with the iter-1 single-cell greedy init (0.15s). Tests whether the init improvement matters or SA converges to the same quality regardless of init.

## Success Criteria
h-main should score higher than h-ablation on the same judge run. Any consistent improvement confirms the mechanism.

## Constraints
- 3-second time limit per test case. Budget: 0.12s init + 2.73s SA + 0.1s margin.
- Cannot compile locally (needs `bits/stdc++.h`). Each judge call takes 30-60s.
- Judge uses different random test cases each run, introducing ~5-point variance.

## Prior Knowledge
- RP-1: Valid-by-construction SA proposals (computing max expansion bounds per edge) yield higher scores than random-step + rejection. [CONFIRMED iter-1]
- RP-2: SA is the dominant score mechanism, providing ~70 points over greedy-only. [CONFIRMED iter-1]
- Iter-1 exploration found that coordinated neighbor moves were too expensive — O(N) adjacent search per step reduced iteration count.
