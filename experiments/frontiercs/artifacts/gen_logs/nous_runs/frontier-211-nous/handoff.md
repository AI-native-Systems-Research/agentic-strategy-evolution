# Handoff Snapshot — Iteration 3

## Goal

Implement and measure the multi-seed perturbation algorithm (h-main: 3 seeds interleaved round-robin) against the single-seed baseline (h-control-negative: seed 54321), comparing scores via the judge.

## Key Discoveries

1. **Different LCG seeds explore independent MST topology regions.** Testing 6 seeds on test 3 (N=K=1500) showed cost variance from 159,260,358 (seed 98765) to 159,313,903 (seed 77777) — a range of 53,545 cost units. Seed 54321 gives 159,274,195, which is not the global best.

2. **3-seed interleaved perturbation scores 87.18 (+0.018 over baseline).** Seeds {54321, 98765, 33333} cycled round-robin. Verified stable across 4 judge runs. This is the best variant discovered across all exploration.

3. **5 seeds slightly worse than 3 seeds (87.179 vs 87.18).** With ~10 trials per big test, 5 seeds means only 2 trials per seed — insufficient depth. 3 seeds (3-4 trials each) is the optimal diversity-vs-depth tradeoff.

4. **Varying epsilon ranges per seed hurts (87.16).** Seed 2 with wide ε ∈ [0.05, 0.25] produces too-diverse topologies that degrade quality. Uniform ε ∈ [0.002, 0.102] for all seeds is better.

5. **The tree is locally optimal after the full pipeline — no degree upgrade opportunities exist.** After greedy insertion + reassignment + hub, checking ALL used relay-to-robot non-tree edges found 0 profitable additions. The Prim MST on the subgraph guarantees path_max(u,v) ≤ ecost(u,v) for all pairs.

6. **Hub top-k parameter is insensitive between 6 and 10.** Top-6/8/10 all produce score 87.18. Top-12 causes TLE on judge (80.193). The best hubs are always among the 6 nearest robots.

7. **Prim-on-all-nodes (3000 nodes) adds no value.** Post-prune cost is 168M vs 159M for MC MST pipeline. The MC metric closure is a superior initial approximation.

8. **Tests 1,2 structurally capped (K=10 relays, 8.462/20 pts).** Tests 4,6,7,9 already perfect (40/40). Improvement potential confined to tests 3,5,8,10.

## System Interface

- **Build:** `g++ -O2 -o sol solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_211.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout (0-100, sum of 10 test cases × 10 pts each)
- **Baseline result:** 87.162 (iter-2, single seed). Multi-seed probe: 87.18.
- **Judge runtime:** ~30-35 seconds total across all 10 test cases.

## Code Map

- `chk.cc:29-45` — `dist_cost()`: edge cost rules. Check if scores seem wrong.
- `chk.cc:75-108` — `base_mst()`: robot-only MST for scoring baseline.
- `chk.cc:313-337` — Scoring: `base_cost = d/9*8`, `zero_cost = d`, linear interpolation.
- `solution.cpp:8-16` — `ecost()`: must return 1e18 for C-C pairs.
- `solution.cpp:40-176` — `build_solution()`: full pipeline (Prim MST + prune + greedy + reassign + hub).
- `solution.cpp:179-223` — `main()`: MC computation + initial Kruskal + perturbation loop.
- `solution.cpp:206-218` — Perturbation while-loop: WHERE THE SEED CHANGE GOES.

## Code Targets

### h-main (Multi-Seed Perturbation)
- **File:** `solution.cpp`
- **Location:** `main()`, lines 180 and 206-218
- **Change:** Replace `unsigned seed = 54321;` with `unsigned seed_states[3] = {54321, 98765, 33333}; int trial = 0;`. In the while-loop, use `seed_states[trial % 3]`, save back after each trial.
- **Validated solution:** `/tmp/sol_v3b.cpp` scores 87.18.

### h-control-negative (Baseline)
- **File:** `solution.cpp`
- **Change:** None. The current worktree `solution.cpp` IS the baseline.

## What I Tried That Didn't Work

1. **Relay degree upgrade:** 0 improvements (Prim MST local optimality).
2. **5-seed perturbation:** 87.179 (too few trials per seed).
3. **Varying ε ranges:** 87.16 (wide ε degrades quality).
4. **Relay swap post-processing:** 0 improvements (reassignment covers this).
5. **Prim-on-all-nodes:** 168M vs 159M, never beats MC approach.
6. **Hub top-k = 12:** TLE on judge (80.193).
7. **Sequential multi-seed (3 phases):** TLE on judge (77.147).
8. **Non-adjacent relay insertion (iter-2):** 0 improvements.
9. **Edge-swap with unused relays (iter-2):** 0 improvements.
10. **Prim-based perturbation (iter-2):** 87.127 (worse than Kruskal-based 87.162).

## What I Excluded and Why

1. **Simulated annealing:** Time budget too tight for SA moves.
2. **Degree-4 hub insertion:** Complex, marginal benefit.
3. **Coordinate perturbation:** O(2.3s) MC recomputation per trial.
4. **Randomized greedy:** Reduces perturbation trials by 2-3x.

## Evolution of Thinking

### Iter-1 → Iter-2
Established MC MST as the foundation (RP-1, score 86.951). Iter-2 added three orthogonal mechanisms: perturbation restarts (+0.08), relay reassignment (+0.05), degree-3 hubs (+0.08). Combined: 87.162 (+0.211). Mechanisms are additive (RP-7).

### Iter-2 → Iter-3
Investigated multiple approaches to break through the plateau:
- **Relay degree upgrade:** Theoretically interesting (upgrade used degree-2 relays to degree-3), but disproven — the Prim MST property means no single-edge addition can improve the tree.
- **Alternative starting points:** Prim-on-all-nodes produces a fundamentally different tree but always worse than MC approach.
- **Perturbation diversity:** Multi-seed confirmed as the only effective improvement. Systematic testing of variants (3/5 seeds, uniform/varying ε, hub k=6/8/10/12) pinpointed 3-seed with uniform ε as optimal.

**The algorithm has reached a firm performance plateau.** The remaining 1.28-point gap is dominated by tests 3/8 needing 0.7%/0.6% additional cost reduction — beyond what perturbation or local search can achieve.

## Current Status

- **Validated:** Multi-seed (87.18) stable ×4. Baseline (87.162) stable ×5.
- **Uncertain:** Behavior under extreme CPU contention (one verbose eval gave 77.219).
- **Suggested next:** LP relaxation, branch-and-bound on relay subsets, or specialized Steiner tree heuristics. The current greedy+local-search architecture is exhausted.

## Warnings & Constraints

1. **`ecost()` MUST return 1e18 for C-C pairs.**
2. **Reset `par[i] = i` before each Kruskal call.**
3. **Save LCG seed states per-seed** — forgetting makes seeds identical.
4. **Perturbation time budget: 9.0s max.** Do not increase.
5. **Hub top-k ≤ 10.** Top-12 causes TLE.
6. **Memory:** ~68MB total, well under 512MB.
