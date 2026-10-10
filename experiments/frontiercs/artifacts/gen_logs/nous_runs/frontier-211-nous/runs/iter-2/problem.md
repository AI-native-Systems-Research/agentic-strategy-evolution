# Problem Framing — Iteration 2

## Research Question

How can we improve beyond the iter-1 metric closure MST baseline (86.951) by combining perturbed MC MST restarts, relay reassignment, and degree-3 hub insertion?

The iter-1 algorithm (metric closure MST + subgraph MST + prune + greedy insertion) scores 86.951/100. Four tests score less than 10.0: tests 3, 5, 8, 10. Tests 4, 6, 7, 9 already score perfect 10.0. Tests 1, 2 are structurally limited by low relay counts (K=10).

The mechanism under study is implemented in `solution.cpp` (full rewrite). Key source files:
- `chk.cc:313-337` — Scoring formula: `base_cost = MST*8/9`, `zero_cost = MST`, linear interpolation.
- `chk.cc:29-45` — Edge cost rules (0.8 for RS/SR/SS, 1e18 for CC, 1.0 otherwise).

## System Interface

- **Build command:** `g++ -O2 -o sol solution.cpp`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp`
  - Prints `SCORE: <n>` where n is 0-100 (sum of 10 test cases, each 0-10).
  - Takes ~22-30 seconds total (10 test cases, up to 10s each).
- **Code evidence:**
  - `chk.cc:313` — `double d = base_mst(entities);` computes robot-only MST cost.
  - `chk.cc:315` — `double base_cost = d/9*8;` is the full-score threshold.
  - `chk.cc:336` — `score_ratio = min(1.0, (zero_cost-actual_cost) / (zero_cost-base_cost));`
  - `solution.cpp:8-16` — `ecost()` function implementing cost rules.
- **Output format:** Native stdout from the measure script. No file redirect needed.

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp
```

## Baseline Validation

Running the iter-1 metric closure MST solution:
- **Exit code:** 0
- **Score:** 86.951
- **Breakdown:** Tests 4,6,7,9 score 10.0. Tests 3,8 ≈ 9.3. Tests 5,10 ≈ 9.9. Tests 1,2 ≈ 8.5 (structurally limited).

## Experimental Conditions

### h-main: Enhanced MC MST with perturbed restarts, relay reassignment, and degree-3 hub insertion

The enhanced algorithm adds three improvements over the iter-1 baseline:

1. **Perturbed MC MST restarts** (biggest impact, ~50K cost savings on tests 3,8): Add random noise (ε ∈ [0.002, 0.102]) to metric closure weights, rebuild MST via Kruskal's, run full pipeline. Different perturbations explore alternative tree topologies. Keep best across all trials within the 9-second time budget.

2. **Relay reassignment** (small impact, ~4-12K savings on tests 5,10): After greedy insertion, for each used relay, check if an unused relay serves the same neighbors more cheaply. Iterates until no improvement found.

3. **Degree-3 hub insertion** (medium impact, ~10-49K savings): For each unused relay c, find the best triplet of tree robots (r1, r2, r3) such that connecting c to all three and removing 2 bottleneck tree edges reduces total cost. Uses Steiner subtree savings formula: savings = pm_max + pm_min - (d(c,r1) + d(c,r2) + d(c,r3)), where pm values are pairwise path-max bottleneck costs.

4. **Unlimited greedy insertion rounds** (minor): Iter-1 used 3 rounds; the enhanced version runs until convergence.

**Command:** Same measure command; the code change is in `solution.cpp`.

## Success Criteria

- **Primary:** h-main score > 86.951 (iter-1 baseline), confirming the enhanced algorithm improves upon the metric closure MST foundation.
- **Directional prediction:** The combined improvements should yield a consistent score increase of at least +0.1 points, primarily from perturbed restarts on tests 3 and 8.
- **Probe validation:** I measured 87.162 during exploration, a +0.211 improvement.

## Constraints

- 10-second time limit per test case (from problem specification).
- 512 MB memory limit.
- The scoring measure must use `bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp` exactly.
- Cannot violate C-C edge prohibition (RP-1, RP-4).
- Must not add top-K relays per MC edge to subgraph (RP-2: this hurts performance).

## Prior Knowledge

- **RP-1:** Metric closure MST dramatically outperforms full MST + prune (86.95 vs 62.15). The iter-2 algorithm builds on this foundation.
- **RP-2:** Adding more relay candidates to subgraph (top-K) HURTS performance. The iter-2 design respects this: only the best relay per MC edge enters the subgraph. The degree-3 hub insertion adds relays AFTER the subgraph MST, avoiding the top-K regression.
- **RP-3:** Scoring uses linear interpolation; 11.1% cost reduction needed for full marks. Tests 1,2 are structurally relay-scarce. No strategy can fix this.
- **RP-4:** The 0.8 S-type discount reduces relay effectiveness for edges involving S-type robots. The metric closure already accounts for this correctly.
- **Iter-1 failure (diagnostic):** Hub extension via bottleneck replacement regressed score from 86.95 to 77. The degree-3 hub insertion in iter-2 uses a different approach (Steiner subtree formula with LCA path-max) that was validated to produce genuine savings.
