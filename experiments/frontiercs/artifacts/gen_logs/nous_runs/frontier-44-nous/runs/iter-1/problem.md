# Problem Framing — Iteration 1

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #44 (Traveling Santa with Carrot Constraint)?

The problem is a TSP variant on N cities (up to 200,000) with a 10% distance penalty on every 10th step unless the source city has a prime ID. The baseline is the identity tour (visiting cities in x-sorted order), which scores 0. The scoring curve (`chk.cc:91-178`) computes improvement ratio `r = (L_base - L_you) / L_base`, speedup ratio `s = L_base / L_you`, and maps through a piecewise-linear + logarithmic curve with visibility remap.

Key source files:
- `chk.cc:91-101` — penalized cost computation
- `chk.cc:105-119` — baseline cost (identity order)
- `chk.cc:133-176` — scoring formula: part1 (20% weight, linear up to 25% improvement) + part2 (80% weight, log-based up to s_full = N^0.6, power tau=1.25)
- `chk.cc:19-42` — visibility remap (piecewise linear, compresses low scores, expands mid-range)

## System Interface

- **Build command:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run/measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` where n is 0-100 (average across 20 test cases)
- **Code evidence:**
  - `fmeasure_44.sh` — invokes `frontier eval algorithmic 44 <solution.cpp> --json`, extracts last `"score"` from JSON output
  - `config.yaml:3` — time limit 2.5s per test case
  - `config.yaml:4` — memory limit 512 MB
  - `config.yaml:8` — 20 test cases, single subtask worth 100 points

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

Where `solution.cpp` contains the algorithm under test.

## Baseline Validation

- **Identity order (0, 1, 2, ..., N-1, 0):** SCORE = 0.0 (exit code 0, output produced)
- **Strip-based serpentine + 2-opt + carrot optimization:** SCORE ≈ 50-55 (varies due to time-dependent 2-opt passes)
- Exit code 0 in all cases. Judge runs in ~6 seconds total across all 20 test cases.

## Experimental Conditions

### Condition 1: h-main — Strip construction + 2-opt local search + carrot-aware prime placement

The primary algorithm combines three mechanisms:

1. **Strip-based serpentine construction**: Sort cities by y-coordinate, divide into sqrt(N * H/W) horizontal strips, sort within each strip by x alternating direction. This eliminates the y-zigzag that dominates baseline cost.

2. **2-opt local search**: Iteratively try reversing tour segments [i+1..j] when it reduces total distance. Uses adaptive window size (N for small inputs, down to 30 for N=200K) and runs until 2.1 seconds elapsed.

3. **Carrot-aware prime placement**: At penalty positions (tour indices 9, 19, 29, ...), swap non-prime cities with nearby prime cities if the net effect (penalty savings minus geometric cost increase) is positive. Search radius up to 500 positions.

Code changes to `solution.cpp`: Replace the empty stub with a complete C++17 implementation of this algorithm.

### Condition 2: h-control-negative — Identity order

Output the identity tour (0, 1, 2, ..., N-1, 0). This IS the baseline used by the checker, so it should score exactly 0.

Code changes to `solution.cpp`: Replace stub with trivial identity-order output.

## Success Criteria

- **h-main:** Score > 0, demonstrating the algorithm produces a meaningfully shorter penalized tour than the baseline. Based on probes, expect score in range 45-60.
- **h-control-negative:** Score = 0, confirming the baseline produces no improvement.
- The contrast (h-main score >> h-control-negative score) validates that the TSP optimization mechanism produces real improvement.

## Constraints

- Time limit: 2.5 seconds per test case (from config.yaml)
- Memory limit: 512 MB
- N up to 200,000 cities
- Must produce valid tour (start/end at 0, visit all cities exactly once)
- Test cases include both scattered points (unique x) and grid-like distributions (shared x)
- Judge call takes ~30-60s total; call once per arm

## Prior Knowledge

This is iteration 1. No active principles from prior iterations.

The scoring curve is deliberately harsh for large N: s_full = N^0.6 means a perfect score on N=200,000 would require the tour to be ~1520x shorter than the baseline, which is likely unattainable. Practical scores in the 40-70 range represent strong optimization. The visibility remap further compresses low scores and expands the 66-90% range (`chk.cc:21-28`).
