# Problem Framing — Iteration 3

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #0 (polyomino packing)?

Iterations 1-2 established that a skyline-based greedy packer with dynamic lookahead, roughness tiebreaker, column compaction, and multi-ordering scores ~83 on average (range 79-86 depending on system load). This iteration tests whether **integrated bitmap-based gap-filling** — detecting and filling internal gaps below the skyline during placement — can push the score higher.

Relevant source files:
- `algorithmic/problems/0/chk.cc:49-56` — `rot90cw()` CW rotation.
- `algorithmic/problems/0/chk.cc:107-137` — Validation: reflect→rotate→translate, bounds, overlap.
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`.
- `algorithmic/problems/0/config.yaml:6-7` — 2-second time limit, 256MB memory.
- `algorithmic/problems/0/examples/reference.cpp` — Human best (Shang Zhou, IIMOC), same skyline approach, scores ~86.

## System Interface

- **Build:** Handled internally by the judge (g++ -O2 -std=c++17).
- **Run:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (0-100, higher is better).
- **Time limit:** 2 seconds per test case, 70 test cases.
- **Memory limit:** 256 MB.

## Baseline Command

```bash
cp inputs/h-control-negative-solution.cpp solution.cpp && bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp
```

## Baseline Validation

The v7 baseline (iter-2 h-main) was run 6 times during design probing. Scores: 82.38, 83.73, 79.95, 83.90, 81.11, 86.33. All runs produced valid output (non-zero score). The high variance (range 6.38) is due to system load affecting the time-managed width sweep. Average: ~82.9.

## Experimental Conditions

### h-main: Skyline + integrated gap-filling
Copy `inputs/h-main-solution.cpp` to `solution.cpp` and run the judge.

The key algorithmic change: during skyline packing, maintain a 2D bitmap alongside the skyline array. After the scoring loop selects the best (piece, orientation, x, y) candidate using the skyline, check the bitmap for a lower y position in gaps below the skyline. If the piece fits in a gap, place it there instead of on top of the skyline. This fills internal gaps that pure skyline tracking misses.

Implementation details:
- Bitmap is row-major: `bitmap[y * W + x]`, allocated per pack call
- Gap scan: for each placement, scan y from 0 to skyline_y0-1, checking k cells
- Cost: O(y0 * k) per placement, O(n * y_avg * k) total ≈ 12.5M ops — negligible
- The skyline is still updated after gap placement (using the gap position's top)
- Column compaction and multi-ordering are unchanged from v7

### h-control-negative: v7 baseline (no gap-filling)
Copy `inputs/h-control-negative-solution.cpp` to `solution.cpp` and run the judge.

This is the unmodified iter-2 h-main (v7): skyline + dynamic lookahead + roughness + column compaction + 3 orderings + hybrid time strategy. No bitmap, no gap-filling.

## Success Criteria

h-main scores higher than h-control-negative. Given the high per-run variance (~5 points), a single-run comparison may not be definitive. The experiment is CONFIRMED if h-main >= h-control-negative, REFUTED if h-main < h-control-negative by >3 points.

## Constraints

- Judge call takes ~30-60 seconds per arm.
- Time limit: 2 seconds per test case.
- Memory: 256 MB.
- Scores range from 0 to 100 (higher is better).
- System load sensitivity: scores vary ±5 points across runs.

## Prior Knowledge

- **RP-1:** Skyline-based 2D greedy packing with multi-width sweep produces ~2x the density of naive 1D strip packing.
- **RP-2:** Transform parameter recovery (X, Y, R, F) must exactly match the checker's reflect→rotate→translate convention.
- **RP-3:** Score is sensitive to time-managed width sweep budget; system load causes ±6 point variance.
- **RP-4:** Dynamic lookahead (K = n/4) is the dominant improvement mechanism (~63% of iter-2's improvement).
- **RP-5:** Secondary improvements (roughness, compaction, multi-ordering) contribute ~4 points over iter-1 baseline.
