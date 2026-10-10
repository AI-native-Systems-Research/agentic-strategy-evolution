# Handoff — Iter 3

### Goal
Implement two solution variants for AHC001 rectangle packing: (1) SA with best-tracking + wider temperature (T0=0.08, T1=0.0005), (2) iter-2 baseline SA (T0=0.05, T1=0.001, no best-tracking). Measure both via the judge. Compare scores.

### Key Discoveries
- **Best-tracking + wider temps scored 92.7 in probe**: The combination is super-additive. Wider temps alone scored ~88.4 (iter-2 dead end). Best-tracking alone scored 91.8. Combined scored 92.7.
- **Best-tracking is nearly free**: Computing total_score() every 32K iterations costs O(N) per check, negligible vs the O(N) per SA iteration.
- **T0=0.08 is the sweet spot**: T0=0.1 is too aggressive (90.7). T0=0.05 is too conservative when combined with best-tracking.
- **Kick moves, contract-expand, targeted selection all failed**: These add complexity without improving score (89.9, 87.0, 89.9 respectively).
- **Post-SA greedy refinement catastrophically fails**: Shrinking oversized rects then expanding undersized ones scored 37.7. The cascading adjustments destroy the SA configuration.
- **Score variance is ~5 points between judge runs**: Due to different random test sets. Single-run comparisons are unreliable.

### System Interface
- **Build:** None needed — judge compiles automatically.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp`
- **Output format:** stdout prints `SCORE: <n>` where n is 0–100.
- **Baseline result:** SA + best-tracking + wider temps scored 92.73 in best probe.

### Code Map
- `solution.cpp:1` — The only file. Must be completely replaced per arm.
- Satisfaction formula (`solution.cpp:~35`): `p_i = 1 - (1 - min(r,s)/max(r,s))^2`.
- `max_expand_*` functions (`solution.cpp:~44-80`): O(N) per call. The bottleneck for SA throughput.
- SA loop (`solution.cpp:~100-150`): Exponential cooling, single-edge moves with valid-by-construction proposals.
- Best-tracking (`solution.cpp:~90-100`): `save_best()` computes total_score() and memcpy's arrays if improved. Called every 32K iterations.

### Code Targets
- **h-main** (`solution.cpp`): Full rewrite with best-tracking + T0=0.08, T1=0.0005. Use the exact code from the probe that scored 92.73.
- **h-control-negative** (`solution.cpp`): Full rewrite identical to iter-2 h-main patch. T0=0.05, T1=0.001, no best-tracking.

### What I Tried That Didn't Work
- **Kick moves — reset worst rect to 1x1 then re-expand (89.94)**: Negligible improvement over baseline. The worst rectangle is usually constrained by geometry, not local optima.
- **Contract-expand moves — shrink one axis, expand other (87.0)**: Expensive per iteration (2 max_expand calls), reduces throughput without quality gain. The max-expansion is too greedy, creating suboptimal shapes.
- **Targeted selection — 30% sample worst rect (89.94)**: The O(5) sampling overhead per iteration is small but the heuristic doesn't help. SA already naturally focuses on improvable rects via acceptance.
- **Post-SA greedy refinement (37.7)**: CATASTROPHIC. Shrinking oversized rects breaks the carefully tuned SA configuration. Never do this.
- **T0=0.1, T1=0.0002 (90.73)**: Too aggressive — early SA accepts too many bad moves, spending too long in poor configurations.
- All iter-2 dead ends still apply: BSP init (83-86), paired boundary moves (0), area-biased proposals (85.7), adaptive step sizes (88.2), two-edge moves (89.7), SA with reheat (90.4), weighted rect selection (85.3).

### What I Excluded and Why
- **Multi-start SA**: With 2.85s total, splitting into 2x1.4s runs gives each run less time to converge. Best-tracking already captures peaks from one long run.
- **Spatial indexing for max_expand**: With N≤200, the O(N) loop is ~200 iterations. A KD-tree or grid index would have higher constant factors for this N range.
- **Fundamentally different representations** (grid-based, strip-based): Would require complete redesign. SA with the current representation appears to have room to improve with better meta-strategy (like best-tracking).
- **Multi-dimensional temperature** (different T per rectangle): Too complex, unlikely to help given the uniform cost of bad moves.

### Evolution of Thinking
Started iter-3 expecting novel SA move types to be the path forward. Tried kick moves, contract-expand, and targeted selection — all neutral or negative. The breakthrough was recognizing that the iter-2 "dead end" of wider temperature range (88.4) failed ONLY because the final state was returned. Adding best-tracking transformed a failed experiment into the best result yet (92.7). This is a meta-strategy insight: **the SA already explores good configurations, it just doesn't keep them**. The fix is bookkeeping, not algorithmic.

### Current Status
- **Validated:** Best-tracking + T0=0.08, T1=0.0005 produces valid output and scores ~92.7 in probe. Baseline scores ~89-90.
- **Uncertain:** Whether the ~3 point improvement is consistent given ~5-point judge variance. Need multiple runs to confirm.
- **Suggested next:** If confirmed: (1) optimize best-check frequency (try every 4K or 16K instead of 32K), (2) try non-exponential cooling schedules (e.g., linear, or piecewise with reheat), (3) explore per-rectangle temperature scaling based on satisfaction.

### Warnings & Constraints
- Judge calls take 30-60s (sometimes >120s). Budget accordingly.
- Score variance is ~5 points between judge runs. Need 3+ runs per arm to detect a ~3 point improvement.
- Cannot compile locally on macOS — `bits/stdc++.h` not available.
- The timer uses wall clock. Judge server speed may vary.
- The xorshift RNG seed is fixed at 88172645463325252. Both arms use the same seed.
- The `total_score()` call in best-tracking is O(N). At N=200 with checks every 32K iters, the overhead is ~0.1% of total SA time.
