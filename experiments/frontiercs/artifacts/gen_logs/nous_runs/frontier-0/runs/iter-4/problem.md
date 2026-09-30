# Problem Framing — Iteration 4

## Research Question

What algorithm maximizes the Frontier-CS judge score for polyomino packing problem #0?

Specifically for iter-4: **Does combining unified time allocation (removing the 60/40 phase split), position-level early termination, fast I/O, and random-restart ordering diversity produce a measurable improvement over the v7 baseline?**

The core mechanism is making each `pack()` call faster (early termination) and allocating all time to the primary width sweep (unified allocation), then exploiting any remaining time budget with random ordering restarts at the best discovered width. This targets the RP-3 bottleneck: the width sweep's time sensitivity.

Key source files:
- `iter-4/inputs/h-main-solution.cpp` (v10): Lines 185-187 (quick early termination), lines 198-199 (exact early termination), lines 353-369 (unified sweep), lines 397-418 (random restart phase)
- `iter-4/inputs/h-control-negative-solution.cpp` (v7): Lines 246-265 (60/40 phase split)
- `Frontier-CS/algorithmic/problems/0/chk.cc`: Lines 107-137 (transform validation), lines 148-151 (scoring)
- `Frontier-CS/algorithmic/problems/0/config.yaml`: 2s time limit, 256MB memory, 70 test cases

## System Interface

- **Build command:** N/A (solutions are single-file C++ compiled by the judge)
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **CLI flags:** The measure script calls `frontier eval algorithmic 0 <solution.cpp> --json`
- **Output format:** Prints `SCORE: <float>` where the score is `100000 * sum(k_i) / (W*H)` averaged over 70 test cases, range [0, 100]
- **Time limit:** 2 seconds per test case
- **Memory limit:** 256 MB

**Code evidence:**
- Score formula: `chk.cc:148-151` — `score = (double)totalCells / (double)area` (multiplied by 1e5 per test, averaged to 0-100 scale)
- Transform order: `chk.cc:109-124` — reflect (negate x if F=1) → rotate CW → translate
- Time/memory limits: `config.yaml` — `time: 2s`, `memory: 256m`
- Fast I/O struct: `h-main-solution.cpp:10-24`
- Early termination: `h-main-solution.cpp:185-199`
- Random restart: `h-main-solution.cpp:397-418`

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh /home/ubuntu/frontier/gen_logs/nous_runs/frontier-0/runs/iter-4/inputs/h-control-negative-solution.cpp
```

## Baseline Validation

The baseline (v7) was tested back-to-back with the treatment (v10):
- v7 run 1: SCORE: 82.56
- v7 run 2: SCORE: 82.33
- v10 run 1: SCORE: 81.45
- v10 run 2: SCORE: 82.73

Both produce valid output, exit 0, and score in the expected ~80-84 range. The scores are within the ~6 point system-load variance documented in RP-3.

## Experimental Conditions

### h-main: v10 (unified sweep + early termination + random restart)

**Solution file:** `iter-4/inputs/h-main-solution.cpp`

Changes from v7 baseline:
1. **Fast I/O** (lines 10-24): Custom fread-based scanner replaces cin/scanf, saving ~30-50ms on large inputs
2. **Unified width sweep** (lines 353-369): Eliminates the 60/40 phase split — all time goes to the primary ordering's width sweep first
3. **Position-level early termination** (lines 174-199):
   - Quick check: `max(maxH, y0 + maxHiP1) > bestScore2` skips before computing nhBuf (line 187)
   - Exact check: `localH > bestScore2` skips before computing deltaSum and roughDelta (line 199)
4. **Random restart** (lines 397-418): After width sweep and fixed alt orderings, remaining time is used for shuffled-ordering restarts at bestWidth ± 1

**Command:**
```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh /home/ubuntu/frontier/gen_logs/nous_runs/frontier-0/runs/iter-4/inputs/h-main-solution.cpp
```

### h-control-negative: v7 (unchanged baseline)

**Solution file:** `iter-4/inputs/h-control-negative-solution.cpp`

The v7 baseline from iter-2/iter-3: skyline + lookahead (K=n/4) + roughness + column compaction + 60/40 time split (Phase 1 width sweep, Phase 2 alt orderings at best width ±3).

**Command:**
```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh /home/ubuntu/frontier/gen_logs/nous_runs/frontier-0/runs/iter-4/inputs/h-control-negative-solution.cpp
```

## Success Criteria

1. **Primary:** v10 (h-main) achieves a higher mean score than v7 (h-control-negative) across 3 seeds, with the paired difference being consistent in direction (2 of 3 seeds positive).
2. **Secondary:** The paired standard deviation is smaller than the individual score variance, confirming that back-to-back comparison controls for system load.
3. **Mechanism validation:** If improvement is detected, it should be larger for the heaviest test cases (n>1000, totalCells>7000) where the time allocation change matters most.

## Constraints

- 2-second time limit per test case (config.yaml)
- 256 MB memory limit
- 70 test cases per judge run
- System-load-induced score variance of ~6 points (RP-3) requires paired comparison design
- Transform order must match checker exactly (RP-2)

## Prior Knowledge

### Active Principles Applied:
- **RP-1:** Skyline + width sweep baseline (~72 pts). Both v7 and v10 build on this.
- **RP-2:** Transform order correctness. Both solutions handle this identically.
- **RP-3:** Time-managed width sweep variance (~6 pts). This is the primary target — v10 aims to reduce sensitivity by making pack() faster and allocating all time to width sweep.
- **RP-4:** Dynamic lookahead (K=n/4) as dominant mechanism (~63% of improvement). Both solutions use identical lookahead.
- **RP-5:** Secondary improvements (roughness, compaction, multi-ordering) contribute ~4 pts. Both solutions include these.
- **RP-6:** Gap-filling is not viable. Not attempted in v10.

### Previous Iterations:
- **Iter-1:** Established skyline packing baseline (71.76 vs strip 34.59)
- **Iter-2:** Added lookahead (82.86 avg) and measured its contribution (63%)
- **Iter-3:** Tested gap-filling (NOT significant, +0.50 pts, p>>0.05)
- **Iter-4 (this):** Tests time allocation optimization + ordering diversity
