# Problem Framing: Traveling Santa with Carrot Constraint (Problem #44)

## Research Question

What algorithmic strategy maximizes the judge score for the penalized TSP variant in problem #44? The problem is a TSP on N cities (N up to 200,000) with a 10% distance penalty on every 10th step unless the source city has a prime-numbered ID. Cities are pre-sorted by x-coordinate, making the x-ordered traversal a strong baseline. The code under study is `solution.cpp` — a single C++17 file compiled and evaluated by the judge.

## System Interface

- **Build command:** Compilation handled by the judge internally (C++17, `-O2`).
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` where n is 0–100 (higher is better). The score is averaged across multiple test cases of varying N.
- **Code evidence:** `solution.cpp:1` — the entire solution is a single file. The judge (`fmeasure_44.sh:5`) invokes `frontier eval algorithmic 44` which compiles, runs on test cases, and extracts `"score"` from JSON output.
- **Time limit:** 2 seconds per test case. Memory: 512 MB.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

## Baseline Validation

- **X-sorted order (0,1,2,...,N-1,0):** SCORE: 0 (this IS the strengthened baseline the judge compares against).
- **Grid nearest-neighbor (NN):** SCORE: 78.193 (consistent across runs).
- **NN + safe 2-opt (N≤10000 only):** SCORE: 78.29.
- Exit code 0 in all cases.

## Experimental Conditions

### h-main: Grid NN + penalty-aware 2-opt + or-opt

The primary strategy combines:
1. **Grid-based nearest-neighbor construction** — O(N√N) construction using spatial grid with cell size √(N/4). At each step, select the nearest unvisited city via expanding-ring grid search.
2. **Time-guarded exact 2-opt** — For N≤10000, systematically try all 2-opt reversals (exact delta with penalty awareness). For N>10000, skip local search to avoid TLE.
3. **Or-opt moves** — For medium N (10K-50K), try relocating single cities to better positions using a time budget. This avoids the segment-reversal penalty issue.

**Intent:** Replace the stub `solution.cpp` with a complete implementation of this strategy.

### Observed performance regimes
- N≤5000: Systematic 2-opt runs multiple passes, score improvement ~0.1–0.5 points above NN.
- N=10K–50K: Random small-segment 2-opt gives marginal improvement but risks TLE.
- N>50K: Pure NN construction dominates. Grid NN runs well within 2s. Any local search must be very lightweight.

## Success Criteria

- **Primary:** Judge score > 0 (improvement over x-sorted baseline). Validated: NN alone achieves 78.2.
- **Stretch:** Judge score > 80 (requires better local search or construction). 
- The arm's score is recorded as `score` in findings metadata.

## Constraints

- 2-second time limit per test case (N up to 200,000).
- 512 MB memory limit.
- Must output exactly N+1 lines: tour starting and ending at city 0, visiting every other city exactly once.
- The penalty mechanism: step t (1-indexed) incurs 1.1× multiplier iff t%10==0 AND the source city (tour[t-1]) is NOT prime. By PNT, ~N/ln(N) cities are prime (~16K out of 200K), but N/10=20K penalty positions exist, so not all can be covered.

## Prior Knowledge

This is iteration 1. No prior principles exist. Key empirical discoveries from exploration:
- Grid NN is the fastest reliable construction for large N.
- Local search (2-opt, SA, swaps) barely helps because the penalty cost function makes delta computation O(segment_length) instead of O(1).
- Alternative constructions (Hilbert curve, strip-based, greedy TSP) all score worse due to TLE on large inputs.
- The penalty is a ~1% effect on total cost; tour construction quality dominates.
