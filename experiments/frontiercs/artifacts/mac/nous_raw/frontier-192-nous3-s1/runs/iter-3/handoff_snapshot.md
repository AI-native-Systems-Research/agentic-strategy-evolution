# Handoff — Max-Cut (Problem 192), Iteration 3

## Goal

Implement and compare two SA configurations for Max-Cut: h-main uses incremental gain tracking + long SA (0.30s/restart); h-ablation uses the same incremental gain but short SA (0.03s/restart). Both use xorshift128+ RNG, linear cooling (T0=3.0→Tf=0.001), and post-SA greedy cleanup. Measure each on the judge.

## Key Discoveries

- **Incremental gain tracking is critical for fast SA.** The iter-2 code recomputes gain from scratch each iteration (O(degree) per call including rejected moves). Maintaining a gain array gives O(1) lookup for rejected moves and O(degree) updates only on accepted flips — ~5x throughput improvement.
- **Long SA (0.30s/restart) gives the most consistent 87.5+ scores.** First 3-run test: 87.58, 87.57, 87.57. Later runs show machine-speed-dependent variance (84.7–87.6).
- **Short SA (0.03s/restart) has higher variance:** 87.56, 84.88, 78.32. Many restarts don't compensate for shallow exploration.
- **Judge machine speed varies significantly between runs**, causing a bimodal score distribution (84–85 on slow runs, 87.5+ on fast runs). This is not algorithmic — the iter-2 code itself shows the same pattern today.
- **BLS (Breakout Local Search) scored 79–82** — much worse than SA. The partial_sort overhead and greedy-only search are insufficient.
- **Cosine reheating scored 87.49–87.53** — slightly worse than linear cooling.
- **Perturbation restarts from best didn't improve** over random restarts (81–87.6 range).
- **Xorshift128+ is faster than mt19937** for RNG — measurable throughput gain.

## System Interface

- **Build:** Automatic (judge compiles C++17).
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` (0–100).
- **Baseline result:** Current solution.cpp (iter-1 geometric SA) scores ~84.1.

## Code Map

- `solution.cpp:1` — The single file to edit. Contains the Max-Cut solver.
- `algorithmic/problems/192/config.yaml:2` — Time limit (1s) and case count (30).
- `algorithmic/problems/192/chk.cc` — Testlib checker computing c/m score.

## Code Targets

### h-main (incremental gain + long SA)
- **File:** `solution.cpp` — full rewrite
- **Algorithm:**
  1. Xorshift128+ RNG (seeded from steady_clock)
  2. Random init → compute incremental gain array → greedy to local optimum
  3. SA with linear cooling: T = T0 + (Tf-T0)*frac, frac = elapsed/0.30
  4. Batch time checks every 512 iterations
  5. Post-SA greedy cleanup
  6. Repeat until 0.90s total elapsed
  7. Output best partition found

### h-ablation (incremental gain + short SA)
- **File:** `solution.cpp` — same as h-main but saBudget = 0.03s

## What I Tried That Didn't Work

- **BLS (Breakout Local Search):** Scored 79–82. The partial_sort overhead and greedy-only escape mechanism are much worse than SA for this problem size.
- **Cosine reheating SA:** Scored 87.49–87.53. Slightly worse than linear cooling — the oscillating temperature wastes iterations in high-T phases.
- **Perturbation restarts from best:** Scored 78–87.6. Perturbing the best solution didn't consistently improve over random restarts.
- **Hybrid random+perturb restarts:** Scored 78–87.6. No improvement from mixing strategies.
- **Best-within-SA tracking (copying vector on every improvement):** Added overhead from vector copies, hurting throughput.
- **Adaptive SA budget (remaining*0.5):** No improvement over fixed budget.
- **T0=2.0 (lower starting temperature):** Slightly worse than T0=3.0.

## What I Excluded and Why

- **Genetic algorithms / crossover:** Complex to implement, uncertain payoff for this time budget.
- **SDP relaxation:** Too slow for n=1000 within 1s.
- **Multi-threading:** Can't control compiler flags on judge.
- **Variable neighborhood search:** 2-flip neighborhood too expensive per iteration.

## Evolution of Thinking

Iter-1 and iter-2 established that linear-cooling SA with restarts scores ~87.5. Iter-3 explored whether further optimization (faster RNG, incremental gain, different restart strategies, alternative metaheuristics) could push higher. The main finding is that the 87.5 ceiling is robust — it's achieved by both incremental and non-incremental SA when the judge machine is fast. The bimodal variance (84 vs 87.5) is entirely machine-speed-dependent. The algorithmic improvement from incremental gain tracking is not more iterations-to-score, but more robustness on slower machines (more iterations completed within the time budget).

## Current Status

- **Validated:** Incremental gain + long SA at 87.5–87.6 peak. Short SA at 87.5 peak but higher variance.
- **Uncertain:** Whether the judge machine consistently runs fast enough for 87.5+. 
- **Suggested next:** Try 2-opt local search (swap vertex pairs between partitions), or variable-depth KL within SA restarts. Could also try adaptive cooling (adjust T0 based on graph density).

## Warnings & Constraints

- Judge machine speed varies 2x between runs — observed bimodal 84–85 vs 87.5+.
- 0.90s internal budget is safe for 1s time limit.
- The exp() call is the bottleneck in the SA inner loop; skipping it for g < -10*T saves significant time.
- Vector copies (for saving localBest) add measurable overhead — avoid in the hot loop.
