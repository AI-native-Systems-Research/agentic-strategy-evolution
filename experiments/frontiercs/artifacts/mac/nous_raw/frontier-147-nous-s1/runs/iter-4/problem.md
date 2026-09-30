# Problem Framing — Iteration 4

## Research Question
Does extending the SA time budget from 2.85s to 4.8s consistently improve the judge score for AHC001 rectangle packing? All previous iterations (1–3) used total_time=2.85s. Probes show the judge accepts solutions running up to at least 5.8s without TLE, meaning the SA was artificially time-constrained. The mechanism is straightforward: more SA iterations → more exploration → better configurations found.

Key source files:
- `solution.cpp:111` — `total_time = 2.85` controls the SA budget.
- `solution.cpp:122-188` — SA loop; iterations scale linearly with time budget.
- `solution.cpp:130-136` — Best-tracking saves peak configuration every 32K iters.

## System Interface
- **Build:** None needed — the judge compiles solution.cpp automatically.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0–100.
- **Code evidence:**
  - `solution.cpp:111` — `double total_time = 2.85;` (the knob under study)
  - `solution.cpp:123-127` — Time check uses `gtimer.elapsed()` (wall-clock via chrono)
  - `solution.cpp:128` — Exponential cooling: `T = T0 * pow(T1/T0, progress)`

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```
Where `solution.cpp` contains the current iter-3 SA with total_time=2.85, T0=0.08, T1=0.0005, best-tracking.

## Baseline Validation
- Ran baseline: exit 0, SCORE: 91.63 (this session), 90.71 (second run).
- Ran 4.5s variant: exit 0, SCORE: 93.16.
- Ran 5.8s variant: exit 0, SCORE: 92.70.
- Ran 8.0s variant: exit 0, SCORE: 91.86 (possible marginal TLEs on some test cases).
- Judge duration for baseline: ~40s total for 50 test cases.

## Experimental Conditions

### h-main: Extended SA time budget (4.8s)
Change `total_time` from 2.85 to 4.8 in solution.cpp:111. Everything else identical (T0=0.08, T1=0.0005, best-tracking every 32K iters, same greedy init). The exponential cooling schedule adapts automatically since temperature is parametrized by progress (elapsed/budget), not absolute time.

### h-control-negative: Current baseline (2.85s)
Identical to the current solution.cpp. total_time=2.85.

## Success Criteria
h-main scores consistently higher than h-control-negative across multiple judge runs. Direction: positive. No specific magnitude threshold — the hypothesis is directional.

## Constraints
- Judge variance is ~5 points stdev between runs (RP-5). Need multiple runs per arm.
- Must stay under the judge's per-test time limit. Probes show 5.8s works; 8s may cause marginal TLEs. 4.8s is safely within limits.
- Cannot compile locally on macOS (bits/stdc++.h). Judge compiles on its server.

## Prior Knowledge
- RP-1: Valid-by-construction proposals (max_expand bounds) are already used. Unchanged.
- RP-2: SA is the dominant mechanism (~70 pts over greedy). More SA time reinforces this.
- RP-3: Init quality doesn't matter much; SA converges regardless. Greedy init unchanged.
- RP-4: Best-tracking + wider temps give small directional improvement. Both retained.
- RP-5: Single-run probes are unreliable. We'll run multiple judge calls per arm.

## Dead Ends From This Exploration
- **Compound neighbor moves (89.5):** Two-rectangle boundary-shift moves. O(N) find_neighbor + O(N) overlap checks per compound move drastically reduce throughput. Net negative despite enabling space redistribution.
- **Multi-start SA (87.9):** 3 runs × 0.91s each. Each run too short to converge. Single long run with best-tracking dominates.
- **8s time budget (91.9):** Marginal TLEs on some test cases drag down the average. 4.8s is the sweet spot.
