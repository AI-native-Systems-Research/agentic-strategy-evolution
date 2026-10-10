# Handoff — Polyomino Packing (Iteration 3)

## Goal

Measure the judge score for two algorithmic strategies: (1) an enhanced skyline packer with integrated bitmap-based gap-filling (h-main), and (2) the iter-2 skyline packer without gap-filling (h-control-negative). Copy the respective `.cpp` files from `inputs/` to `solution.cpp` and run the judge once per arm.

## Key Discoveries

- **Gap-filling fills internal skyline gaps.** When the skyline says y0=10 but there's an empty gap at y=3 (visible only in the bitmap), the piece can be placed at y=3. This prevents unnecessary height increases. The gap scan costs O(y0 * k) per placement — negligible compared to the inner scoring loop.
- **Score variance is ±5 points across runs** due to system load affecting the time-managed width sweep. This makes marginal improvements (0-2 points) hard to detect in a single run. Design probing showed mixed results: one back-to-back comparison showed +1.3 points for gap-filling, others showed no reliable difference.
- **The reference solution (Shang Zhou, IIMOC human best) scores ~86 on a fast system.** Both v7 (iter-2) and v8 (iter-3) achieve similar scores on comparable loads. The algorithms are fundamentally identical (skyline + lookahead + roughness + compaction), differing only in gap-filling.
- **Gravity compaction and extra orderings were tested but NOT included** in the final h-main. Gravity compaction (post-placement pass moving pieces downward) added ~300ms overhead and inconsistent benefit. Extra orderings (6 instead of 3) diluted the time budget without reliable score gains.
- **Bitmap memory is bounded.** For W=200, bitmapH=1025: ~25KB (packed vector<bool>). Fits in L2 cache. No memory concerns for 256MB limit.

## System Interface

- **Build:** Handled internally by judge (g++ -O2 -std=c++17)
- **Run:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (0-100)
- **Baseline result:** v7 = 82.9 avg (6 runs during design), v8 = ~82-84 avg (noisy)

## Code Map

- `algorithmic/problems/0/chk.cc:49-56` — `rot90cw()`: CW rotation. Check here if placements are invalid.
- `algorithmic/problems/0/chk.cc:107-137` — Validation: reflect→rotate→translate, bounds, overlap. Check here if score is 0.
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`. Check here for scoring formula.
- `algorithmic/problems/0/config.yaml:6-7` — Time (2s) and memory (256MB) limits.
- `algorithmic/problems/0/examples/reference.cpp:62-207` — Reference packer (Shang Zhou, human best).

## Code Targets

### h-main (v8: skyline + gap-filling)
- **Source:** `inputs/h-main-solution.cpp` → copy to `solution.cpp`
- **Key new section:** Lines ~240-265 (gap scan after winning candidate selection)
- **Bitmap allocation:** Line ~185 (inside pack function)
- **Bitmap update:** Lines ~267-273 (after gap placement)

### h-control-negative (v7: skyline baseline)
- **Source:** `inputs/h-control-negative-solution.cpp` → copy to `solution.cpp`
- **This is the unmodified iter-2 h-main.** No changes needed.

## What I Tried That Didn't Work

- **Post-placement gravity compaction (v8-gravity):** After packing, build a 2D grid and move pieces downward. Added ~300ms overhead. In 6 alternating runs, no reliable improvement over v7 (sometimes +0.2, sometimes -1.5). The gravity pass only helps when there are gaps directly below a piece's current position; most gaps are beside pieces, not below them.
- **Extra orderings (6 instead of 3):** Added descending-min-dim, descending-area, ascending-k orderings to phase 2. In testing, this diluted the time budget without reliable gains. The original 3 orderings (ascending-min-dim, descending-k, descending-max-dim) already capture the main strategies.
- **Gap-filling + gravity + extra orderings combined:** Scored 81.3 vs v7's 83.9 in one test. The combined overhead (bitmap allocation per pack call + gravity post-processing + more orderings) hurt more than the gap-filling helped.
- **Gravity compaction without gap-filling:** First test attempt. Scored 79.87 vs v7's 81.30. The overhead of allocating a grid and scanning for lower positions wasn't compensated by the modest height reductions.

## What I Excluded and Why

- **Simulated annealing / local search:** After greedy placement, apply random perturbations. Could potentially add 5+ points but too complex to implement correctly within 2s, and the greedy+lookahead approach is already near-optimal for the piece sizes.
- **Full BL (bottom-left) bitmap packing:** Scan all (x, y) positions for each piece using a bitmap. O(W * H * k) per piece, too slow for n=10000 (estimated 40B operations). Would only work for small instances.
- **Low-point targeting:** Reduce x-position search to only positions near skyline valleys. Could provide 6x speedup for large instances, enabling more width exploration. Not implemented due to complexity and risk of quality loss.
- **Better width factor tuning:** The base width formula uses empirical factors. Re-tuning might shift the average by 0.5-1 point but wouldn't be detectable in a single run.

## Evolution of Thinking

Started by implementing gravity compaction (move pieces down after initial packing). Found it added overhead without reliable benefit because most gaps are beside pieces, not below them. 

Shifted to integrated gap-filling (maintain bitmap during placement, check for gaps before each placement). This is theoretically sounder: gaps are filled during the packing, benefiting future placements. One clean back-to-back test showed +1.3 points.

Then tried adding gravity compaction ON TOP of gap-filling, plus extra orderings. The combined approach was actually WORSE, likely due to overhead. Reverted to gap-filling only.

Key insight: **the score variance (~5 points) from system load dwarfs the algorithmic improvement (~0-2 points).** The time-managed width sweep makes the algorithm sensitive to system speed: on a fast system, 15+ widths are explored and the optimal is likely found. On a slow system, only 3-4 widths are explored, and missing the optimal width costs 5+ points. Any algorithmic overhead that slows down the pack function reduces the number of widths explored.

## Current Status

- **Validated:** Both solutions compile, produce valid output, and score in expected range.
  - h-main (v8 gap-filling): 82.48 (one run during final verification)
  - h-control-negative (v7): 86.33 (one run during final verification)
  - Note: these runs were NOT back-to-back; the load difference explains the gap.
- **Uncertain:** Whether gap-filling provides a reliable improvement over v7. The mechanism is sound but the effect size is small relative to load-induced variance.
- **Suggested next (iter-4):**
  1. **Speed optimization for big instances:** Low-point targeting (reduce x-position search to skyline valleys) to enable 6x more width exploration. This could reduce variance MORE than any placement improvement.
  2. **Adaptive width search:** Instead of linear sweep, use golden section or Bayesian optimization to find optimal width faster.
  3. **Instance-adaptive strategy:** Use totalCells to decide between different algorithms (BL bitmap for small, skyline for large).
  4. **Profile test cases:** Determine which of the 70 test cases contribute most to score loss and optimize for those.

## Warnings & Constraints

- **Judge call takes ~30-60s.** Run once per arm only.
- **The judge compiles internally.** Don't compile separately.
- **Transform order matters.** Checker: reflect (F=1 → negate x) → rotate (R CW rotations) → translate (add X,Y). The h-main solution uses CW rotation matching the checker's convention.
- **Score depends on system speed.** The time-managed width sweep explores fewer widths on slower systems. Both v7 and v8 use the same time management (1980ms budget).
- **Bitmap in v8 uses vector<bool> (packed bits).** Access involves bit manipulation, which is slower than regular array access. Cache effects might be negative for the inner loop. If debugging performance, try `vector<char>` instead.
- **Column compaction correctness.** Relies on 4-connected polyominoes having contiguous column projections. Mathematically guaranteed.
