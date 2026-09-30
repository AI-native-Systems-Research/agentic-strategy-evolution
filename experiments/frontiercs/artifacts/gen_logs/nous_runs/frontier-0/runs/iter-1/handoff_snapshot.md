# Handoff — Polyomino Packing (Iteration 1)

## Goal

Implement two algorithmic strategies for polyomino rectangle packing and measure their judge scores: (1) a skyline-based greedy packer with multi-width sweep (h-main), and (2) a naive strip packer (h-control-negative). The solutions are pre-written in `inputs/`; the executor copies them to `solution.cpp` and runs the judge.

## Key Discoveries

- **Score range:** Naive strip packing scores ~34; skyline-based packing scores ~76; the human reference solution scores ~79. The 2x+ gap between naive and skyline validates that 2D spatial awareness is the dominant mechanism.
- **Transform parameter recovery is critical.** The checker at `chk.cc:107-137` validates that reflect→rotate→translate produces cells in [0,W)×[0,H). Many LLM solutions in `solutions/0/` score 0 (likely incorrect transform recovery). My solutions were validated.
- **70 test cases** with n ∈ [100, 10000]. Test data at `algorithmic/problems/0/testdata/{1..70}.{in,ans}`. Largest n=6472.
- **2-second time limit per test.** The skyline packer's time management (1900ms budget) is important for large n cases.
- **Judge call takes ~30-60s** — it compiles and runs all 70 test cases internally.
- **Pre-written solutions are in `inputs/`.** The executor should copy the appropriate `.cpp` file to `solution.cpp` and run the judge.

## System Interface

- **Build:** Handled internally by judge (g++ -O2 -std=c++17)
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (n is 0-100, average across 70 test cases)
- **Baseline result:** Strip packer = 34.06, Skyline packer = 76.21

## Code Map

- `algorithmic/problems/0/chk.cc:49-56` — `rot90cw()` function: defines CW rotation. **Check here** if placement coordinates are wrong.
- `algorithmic/problems/0/chk.cc:107-137` — Main validation loop: reflect→rotate→translate, bounds check, overlap check. **Check here** if solutions get score 0.
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`. The `quitp(score, ...)` gives partial credit.
- `algorithmic/problems/0/config.yaml:6-7` — Time (2s) and memory (256MB) limits.
- `algorithmic/problems/0/config.yaml:10-11` — 70 test cases, single subtask worth 100 points.
- `algorithmic/problems/0/examples/reference.cpp` — Human best solution (Shang Zhou, IIMOC). Scores ~79. Uses skyline packing with lookahead, roughness tiebreaking, column compaction, and adaptive time management.

## Code Targets

### h-main (skyline packer)
- **Source:** `inputs/h-main-solution.cpp` → copy to `solution.cpp`
- **Key sections:** Lines 62-122 (orientation generation), Lines 125-132 (piece ordering), Lines 134-211 (skyline pack function), Lines 213-254 (width sweep)

### h-control-negative (strip packer)
- **Source:** `inputs/h-control-negative-solution.cpp` → copy to `solution.cpp`
- **Key sections:** Lines 30-55 (strip placement loop)

## What I Tried That Didn't Work

- **gpt5.cpp reference solution:** Scores 0. Many LLM-generated solutions in `solutions/0/` likely have transform parameter recovery bugs. This confirms correctness is a hard challenge.
- **My first naive baseline attempt** had a slight orientation logic error (picking wider vs taller incorrectly) — was fixed.

## What I Excluded and Why

- **Lookahead optimization:** The reference solution uses a window of N future pieces to pick the globally best next placement. This adds significant complexity. Excluded for iter-1 (tier 1 = single mechanism). This is the most promising improvement for iter-2.
- **Column compaction:** The reference removes empty columns from the final packing. My h-main uses a simpler "used width" calculation. This is a minor optimization, likely worth 1-2 points.
- **Roughness tiebreaker:** The reference tracks skyline roughness (Σ|h[i]-h[i-1]|) as a tiebreaker. Excluded to keep the scoring function simpler. Worth testing in iter-2.
- **Multiple piece orderings:** The reference tries multiple orderings. My h-main uses a single decreasing-size order. Multiple orderings could improve score by 1-3 points.

## Evolution of Thinking

Initially expected the problem to be about exact optimization (e.g., ILP or dynamic programming). Reading the constraints (n up to 10000, kᵢ up to 10, 2s time limit) quickly showed this is a greedy/heuristic problem — optimal packing is NP-hard, and the competitive scoring rewards good heuristics. The human reference solution confirms this: it's entirely greedy with time-managed iteration. The key insight is that the width sweep is as important as the placement heuristic — the right W makes the skyline packer converge to a near-square rectangle, which minimizes area.

## Current Status

- **Validated:** Both solutions compile, produce valid output, and score correctly (h-main: 76.2, h-control-negative: 34.1)
- **Uncertain:** Whether my h-main's score is reproducible across judge runs (the judge may have nondeterminism in timing). The reference solution uses `chrono` seeding which makes it nondeterministic; my solution is deterministic.
- **Suggested next (iter-2):** Add lookahead (choose best from next N pieces, not just the next one), roughness tiebreaker, and multiple piece orderings. These are the features that separate my 76.2 from the reference's 78.7. A tier-2 ablation study could test which of these contributes most.

## Warnings & Constraints

- **Judge call is expensive (~30-60s).** Don't call it unnecessarily. Call once per arm.
- **The judge compiles internally.** You don't need to compile separately, but your code must be valid C++17.
- **Transform order matters.** The checker applies: reflect (F=1 means negate x) → rotate (R CW rotations) → translate (add X,Y). Getting this wrong produces score 0. My solutions were carefully validated against `chk.cc:109-124`.
- **The judge returns SCORE: 0 for compile errors or runtime errors.** Check stderr if score is 0.
- **Skyline height tracking:** The skyline array tracks the first UNOCCUPIED row (not the last occupied), so placing a piece at y0 means the top of the piece at column j is at `y0 + hi[j]`, and the new skyline is `y0 + hi[j] + 1`. I initially had an off-by-one here.
