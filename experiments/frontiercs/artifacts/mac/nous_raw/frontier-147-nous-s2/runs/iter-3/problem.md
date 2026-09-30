# Problem Framing — iter-3

## Research Question
Can multi-restart SA with shuffled greedy initialization be confirmed as the dominant strategy for AHC001 rectangle packing, and what is the magnitude of improvement over single-run SA?

Prior iterations established SA as dominant over greedy (RP-1, iter-1: 81.6 vs 46.8) and tentatively found multi-restart gives modest gains (RP-2, iter-2: medium confidence). This iteration runs both approaches at full scope to confirm the restart effect with tighter variance bounds.

Key source files:
- `solution.cpp:65-195` — single-run SA (baseline)
- `solution_v5.cpp:65-223` — multi-restart SA (treatment)

## System Interface
- **Build:** Not needed — judge compiles server-side.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` (0-100).
- **Code evidence:** `solution.cpp:101` defines SA rng seed; `solution_v5.cpp:202-206` implements restart loop with `doGreedy(rng)` + `doSA(rng, restartEnd)`.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```

## Baseline Validation
Ran twice. Exit code 0 both times. Score: 85.44 (run 1). Output format: `SCORE: 85.4396`.

## Experimental Conditions

### h-main: Multi-restart SA with shuffled greedy
**Code change:** Refactor solution.cpp into `doGreedy(rng)` + `doSA(rng, endTime)` functions. Main loop: 3 restarts with `shuffle(order)` before each greedy. Keep `global_best` across restarts. Use `sqrt(ratio)*3, max 150` greedy steps. Reference: `solution_v5.cpp`.

### h-ablation: Single-run SA (baseline)
No code change. Run `solution.cpp` as-is. Fixed-order greedy + 9.3s SA.

## Success Criteria
- h-main score > h-ablation score by ≥1.0 points (above the ~0.02 per-run variance).
- Both arms produce valid output (all rects contain target points, no overlaps).

## Constraints
- 10s wall-clock time limit per test case.
- Judge evaluates on 50 provisional test cases.
- Judge variance is ~0.02 points for deterministic solutions, but different algorithmic strategies can produce wider variation.

## Prior Knowledge
- **RP-1** (high confidence): SA doubles score over greedy alone.
- **RP-2** (medium confidence): Multi-restart doesn't clearly help. This iteration aims to sharpen this finding.

### Probing results from design phase
Tested 10 variants during exploration:
- v5 (3-restart, shuffled greedy, T=0.01): **87.55** (best, two runs)
- solution.cpp (single-run): **85.44**
- v6 (neighbor-swap moves): 85.2 — overhead kills throughput
- v7 (weighted rect selection): 85.1 — overhead kills throughput
- v8 (quadratic cooling): 84.6
- v10 (recursive bisection init): 30.2 — broken
- v11 (spatial grid): 84.7 — grid overhead worse than O(N) scan for N≤200
- v12 (2 restarts): 85.1 — less diversity than 3
- v13 (no translation moves): 84.5 — translations help
- v14 (5 restarts, fast greedy): 83.5 — fast greedy gives poor initial states
- v15 (T0=0.015): 82.6 — too much exploration
- v16 (hybrid restart+finishing SA): 85.0 — finishing SA doesn't add value
