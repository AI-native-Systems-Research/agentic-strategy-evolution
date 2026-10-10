# Handoff — Polyomino Packing (Iteration 2)

## Goal

Measure the judge score for two algorithmic strategies: (1) an enhanced skyline packer with lookahead, roughness tiebreaker, column compaction, and multiple orderings (h-main), and (2) the same packer with lookahead disabled (h-ablation). Copy the pre-written `.cpp` files from `inputs/` to `solution.cpp` and run the judge once per arm.

## Key Discoveries

- **Lookahead is the dominant mechanism.** h-main (with lookahead) probed at 86.2, 85.0, 84.9 across 3 runs. h-ablation (without) probed at 76.1, 71.3, 81.7. The ~9-point gap isolates lookahead's contribution.
- **Hybrid time strategy is critical for consistency.** Phase 1 (60% time) sweeps widths with one ordering. Phase 2 (40% time) tries alternative orderings at the best width ± 3. This gives range < 2 points for h-main vs range ~10 points for older approaches.
- **Three orderings help.** Ascending-min-dimension, descending-cell-count, and descending-max-dimension each win on different test cases. Multi-ordering adds ~2-3 points over single ordering.
- **Column compaction is safe.** 4-connected polyominoes have contiguous column projections, so remapping the leftmost x preserves internal structure. Verified empirically: no score-0 results.
- **Reference scores ~80 consistently** on this machine. The enhanced packer beats it by ~5 points.
- **Score variance comes from big test cases** (n > 2000, of which there are ~4 in the test suite). Time-managed width sweep explores fewer widths on slower runs.

## System Interface

- **Build:** Handled internally by judge (g++ -O2 -std=c++17)
- **Run:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (0-100)
- **Baseline result:** Iter-1 skyline = 72.78, reference = 79.94, enhanced v7 = 85.4 avg

## Code Map

- `algorithmic/problems/0/chk.cc:49-56` — `rot90cw()`: CW rotation. Check here if placements are invalid.
- `algorithmic/problems/0/chk.cc:107-137` — Validation: reflect→rotate→translate, bounds, overlap. Check here if score is 0.
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`. Check here for scoring formula.
- `algorithmic/problems/0/config.yaml:6-7` — Time (2s) and memory (256MB) limits.
- `algorithmic/problems/0/examples/reference.cpp:62-207` — Reference packer. Check here to compare strategies.
- `inputs/h-main-final-solution.cpp` — The h-main solution. Copy this to `solution.cpp`.
- `inputs/h-ablation-solution.cpp` — The h-ablation solution. Copy this to `solution.cpp`.

## Code Targets

### h-main (enhanced packer with lookahead)
- **Source:** `inputs/h-main-final-solution.cpp` → copy to `solution.cpp`
- **Key sections:** Lines 126-130 (dynamic lookahead init), Lines 137-200 (inner placement loop with window), Lines 245-260 (hybrid time strategy: phase 1 width sweep, phase 2 multi-ordering)

### h-ablation (no lookahead)
- **Source:** `inputs/h-ablation-solution.cpp` → copy to `solution.cpp`
- **Key difference:** Line 130: `int dynLIM = 1;` (forces window of 1, disabling lookahead)

## What I Tried That Didn't Work

- **v3 (two-phase: fast scan + quality pass):** Scored 79.57. The fast scan with small lookahead (3) produced inaccurate width rankings, causing the quality phase to focus on wrong widths.
- **v4 (wider width sweep with many candidates):** Scored 83.43. Too many candidate widths diluted the time budget — fewer widths actually tried despite having more candidates.
- **v6 (fixed lookahead cap):** Scored 81.2-84.9, still variable. Capping lookahead at fixed values (10-100) didn't adapt well to instance sizes.
- **v2 (3 orderings per width, no phasing):** Scored 79.7-84.8, highly variable. For big instances, 3 orderings per width meant only 1-2 widths tried total.

## What I Excluded and Why

- **Simulated annealing / local search:** After greedy placement, moving pieces to improve packing. Too complex to implement reliably within 2s, and the greedy with lookahead is already near-optimal for this problem size.
- **Grid-based gap filling:** Placing small pieces in internal gaps below the skyline. O(W×H) per piece makes this too slow for big instances. Worth testing if a fast implementation can be built.
- **More than 3 orderings:** Diminishing returns — each additional ordering takes time from width exploration. 3 orderings capture the main strategies (small-first, large-first, tall-first).
- **Random tiebreaking (like reference):** Introduces nondeterminism. The multi-ordering approach achieves similar diversity deterministically.

## Evolution of Thinking

Started by replicating the reference solution's individual improvements (lookahead, roughness, compaction) and testing each. Found that all improvements together scored ~84 on first try. Then discovered extreme variance (79-87) across runs, caused by the time-managed outer loop exploring different numbers of widths.

The key insight was that for big instances, trying 3 orderings per width is wasteful — it burns the time budget on one width when the optimal width might be elsewhere. The hybrid strategy (phase 1: many widths × 1 ordering, phase 2: best width × multiple orderings) solved this by ensuring good width coverage first, then exploiting the best width with multiple orderings.

The ablation confirmed the initial hypothesis from iter-1: lookahead is the single most impactful improvement. Without it, roughness + compaction + multi-ordering provide only ~3 points over the iter-1 baseline.

## Current Status

- **Validated:** Both solutions compile, produce valid output, and score correctly
  - h-main: 86.23, 85.03, 84.90 (3 runs, avg 85.4, range 1.3)
  - h-ablation: 76.07, 71.29, 81.72 (3 runs, avg 76.4, range 10.4)
- **Uncertain:** Whether the scores are reproducible under different system loads (the judge environment may differ from design-time probing)
- **Suggested next (iter-3):** 
  1. Grid-based gap filling for small pieces (fill internal holes below skyline)
  2. Beam search (maintain top-K partial packings instead of single greedy path)
  3. Instance-adaptive width estimation (use totalCells distribution to predict optimal width)
  4. Profile which test cases contribute most to score loss and optimize for those

## Warnings & Constraints

- **Judge call takes ~30-60s.** Run it once per arm only.
- **The judge compiles internally.** Don't compile separately.
- **Transform order matters.** The checker applies: reflect (F=1 → negate x) → rotate (R CW rotations) → translate (add X,Y). My solutions use `rot90cw` matching the checker's convention, so R is used directly (no conversion needed, unlike the reference which uses CCW internally and converts with `Ri = (4-t.r)%4`).
- **Score depends on system speed.** The time-managed width sweep explores fewer widths on slower systems. h-main is designed to be robust (range < 2 points), but h-ablation is more sensitive (range ~10 points).
- **Column compaction correctness.** Relies on 4-connected polyominoes having contiguous column projections. This is mathematically guaranteed but could fail if the input violates 4-connectivity (which the problem says won't happen).
