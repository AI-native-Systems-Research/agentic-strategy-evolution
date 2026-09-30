# Handoff — Iter 2

### Goal
Implement two solution variants for AHC001 rectangle packing: (1) multi-cell greedy init + SA, (2) single-cell greedy init + SA. Measure both via the judge. Compare scores to determine if init quality affects final SA score.

### Key Discoveries
- **Multi-cell init scored 90.5 in a probe**: Using max-expansion bounds to grow rects by up to half their current dimension per step. Init finishes in 0.12s, giving SA ~2.73s.
- **Single-cell init scores 85-90 depending on test set**: Score variance between judge runs is ~5 points due to random test cases.
- **SA iteration count is the dominant factor**: More SA time generally means better scores. The main value of faster init is giving SA more budget.
- **Complex SA moves hurt**: Paired boundary moves, two-edge moves, area-biased proposals, and weighted rect selection all reduced throughput without improving quality.
- **Init quality may or may not matter**: The experiment will determine this. SA might converge regardless of starting point.
- **BSP/recursive bisection init scored worse (83-86)**: The tree-structured partition creates poorly-shaped initial rectangles that SA struggles to fix.

### System Interface
- **Build:** None needed — judge compiles automatically.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** stdout prints `SCORE: <n>` where n is 0–100.
- **Baseline result:** SA with multi-cell init scored 90.5 in best probe run.

### Code Map
- `solution.cpp:1` — The only file. Contains entire solution. Must be replaced per arm.
- Scoring formula: `p_i = 1 - (1 - min(r,s)/max(r,s))^2`. Even 50% area match gives p=0.75.
- max_expand_left/right/down/up functions: O(N) per call, compute the valid range for an edge move.

### Code Targets
- **h-main** (`solution.cpp`): Full rewrite. Multi-cell greedy init using max_expand bounds (grow by up to half current dim per step, 0.12s budget). Then SA with valid-by-construction moves (T0=0.05, T1=0.001, until 2.85s total). The exact code is the version that scored 90.5 in the probe — see the multi-cell expansion loop in the design probes.
- **h-ablation** (`solution.cpp`): Full rewrite. Single-cell greedy init (0.15s), then identical SA. This is essentially the iter-1 h-main with shortened init.

### What I Tried That Didn't Work
- **BSP/recursive bisection init (86.3→83.6)**: Creates thin, poorly-sized initial rectangles.
- **Paired boundary moves (0)**: Moving shared boundaries between adjacent rects is buggy — j's expansion can overlap a third rect k. Produced score 0.
- **Area-biased SA proposals (85.7)**: Biasing edge proposals toward the target area reduced exploration, hurting score.
- **Adaptive step sizes (88.2)**: Restricting proposal range based on SA progress was counterproductive.
- **Two-edge moves (89.7)**: Moving two edges per iteration is more expensive per iter, losing throughput.
- **SA with reheat/3-phase (90.4)**: Marginal — overhead of best-tracking cancels the benefit of escaping local optima.
- **Weighted rect selection (85.3)**: Binary search overhead per iteration reduces total iteration count significantly.
- **Wider temperature range T0=0.08,T1=0.0005 (88.4)**: Neutral — default schedule is already well-tuned.

### What I Excluded and Why
- **Grid-based cell assignment**: A fundamentally different representation (assign each grid cell to a company). Would require complete redesign and can't easily guarantee non-overlapping rectangles. Deferred.
- **Rectangle swaps/translations**: Moving entire rectangles (all 4 edges simultaneously) is constrained by the point-containment requirement. Not worth the complexity.
- **Local compilation**: `bits/stdc++.h` not available on macOS. All testing must go through the judge (30-60s per call).

### Evolution of Thinking
Started iter-2 expecting complex SA move types (paired moves, multi-edge, weighted selection) to be the key improvement. All of them either broke correctness or added overhead that reduced iteration count. The actual win was simpler: **make greedy init faster** by using the same max-expansion bounds the SA uses, allowing multi-cell growth per step. This fills the grid faster in less time, giving SA both a better starting point and more iterations.

### Current Status
- **Validated:** Multi-cell init + SA produces valid output and scores ~90.5 in best probe. Single-cell init + SA scores ~85-90.
- **Uncertain:** Whether the init improvement is statistically significant given ~5-point judge variance. The experiment needs both arms to run on the same judge call.
- **Suggested next:** If multi-cell init wins: explore even faster init methods (Voronoi-based assignment with O(1) per cell). If no difference: focus on fundamentally different SA neighborhoods (e.g., rectangle swap moves that exchange two companies' areas while maintaining containment).

### Warnings & Constraints
- Judge calls take 30-60s. Each arm = one judge call. Budget accordingly.
- Score variance is ~5 points between judge runs (different random test cases). Single runs don't give reliable comparisons.
- Cannot compile locally on macOS — `bits/stdc++.h` not available.
- The timer uses wall clock. Judge server speed may differ from local. Use conservative time limits (2.85s total, not 3.0s).
- The xorshift RNG seed is fixed at 88172645463325252. Both arms use the same seed so differences are from init, not randomness divergence.
