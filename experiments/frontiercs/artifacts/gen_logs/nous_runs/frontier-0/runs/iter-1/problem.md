# Problem Framing — Polyomino Packing Score Maximization (Iteration 1)

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #0 (polyomino packing into a minimum-area rectangle)?

The core mechanism under study is **skyline-based greedy packing with multi-width sweep** vs. naive 1D strip packing. The judge scores each test case as `1e5 * Σkᵢ / (W*H)`, rewarding higher packing density. Key files:
- `chk.cc:148-151` — scoring formula: `double score = (double)totalCells / (double)area;`
- `chk.cc:49-56` — transform application: reflect → rotate → translate
- `chk.cc:107-137` — validation: bounds checking + overlap detection
- `config.yaml` — 70 test cases, 2s time limit, 256MB memory

## System Interface

- **Build command:** `g++ -O2 -std=c++17 -o solution solution.cpp` (handled by judge internally)
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
  - Compiles and runs the solution against all 70 test cases
  - Prints `SCORE: <n>` where n is 0-100 (average across test cases)
- **Time limit:** 2 seconds per test case (`config.yaml:6`)
- **Memory limit:** 256MB per test case (`config.yaml:7`)
- **Test cases:** 70 cases, n ∈ [100, 10000], kᵢ ∈ [1, 10] (`config.yaml:10-11`)
- **Code evidence:**
  - `chk.cc:62` — n read as `readInt(100, 10000)`
  - `chk.cc:68` — kᵢ read as `readInt(1, 10)`
  - `chk.cc:82-83` — W, H read as `readLong(1, 4e12)`
  - `chk.cc:90-91` — R ∈ {0..3}, F ∈ {0,1}

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp
```

Where `solution.cpp` contains the h-control-negative naive strip packer.

## Baseline Validation

- **Exit code:** 0
- **Output:** `SCORE: 34.05833537714286`
- **Interpretation:** Naive strip packing achieves ~34% packing efficiency on average across 70 test cases. This establishes a floor.
- **Reference solution (human best):** `SCORE: 78.66597829428574` — establishes the approximate ceiling for greedy approaches.

## Experimental Conditions

### h-control-negative: Naive Strip Packing
- **Strategy:** Place pieces left-to-right in a horizontal strip. Each piece is oriented to minimize height (use R=1 if height > width). No vertical compaction.
- **Expected score:** ~34 (validated)
- **Intent:** Establish baseline showing packing without 2D awareness

### h-main: Skyline-Based Greedy Packer with Multi-Width Sweep
- **Strategy:** 
  1. Generate all unique orientations (up to 8: 4 rotations × 2 reflections) for each piece
  2. Sort pieces by decreasing cell count (larger first)
  3. For a given rectangle width W, maintain a "skyline" array (per-column max height)
  4. For each piece, try every (orientation, x-position) combination, choose the one minimizing: (a) resulting max height, (b) delta sum (new skyline area added), (c) y-position
  5. Sweep across ~160 candidate widths centered around `sqrt(totalCells * factor)`, picking the width yielding minimum area
  6. Time-managed to stay under 1.9s per test case
- **Expected score:** ~76 (validated at 76.21)
- **Code change:** Replace solution.cpp with the skyline packer implementation stored at `inputs/h-main-solution.cpp`

## Success Criteria

1. h-main score > h-control-negative score (directional: skyline approach packs more densely)
2. Both solutions produce valid output on all 70 test cases (score > 0)
3. h-main score ≥ 70 (demonstrating the approach is competitive with the reference's ~79)

## Constraints

- 2-second time limit per test case (hard, enforced by judge)
- 256MB memory limit per test case
- C++17 compilation required
- Each judge call takes ~30-60 seconds (call once per arm, not per test case)
- The judge runs all 70 tests internally

## Prior Knowledge

This is the first iteration. No active principles exist. The reference solution at `examples/reference.cpp` demonstrates that skyline-based approaches with multi-width sweep and lookahead can achieve ~79 on this problem. Several LLM-generated solutions in the solutions directory score 0, suggesting correctness (especially transform parameter recovery) is a significant challenge.
