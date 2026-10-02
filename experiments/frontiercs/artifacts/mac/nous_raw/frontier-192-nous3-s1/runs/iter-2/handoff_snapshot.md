# Handoff — Max-Cut (Problem 192), Iteration 2

## Goal

Implement two SA cooling strategies for Max-Cut and measure which scores higher on the judge. h-main uses linear-cooling SA (time-proportional temperature); h-ablation uses the iter-1 geometric-cooling baseline.

## Key Discoveries

- **Linear-cooling SA (0.10s per restart, T0=3.0) peaked at 87.6** — the highest score observed across all probing. Median 87.55 over 5 runs.
- **Original geometric SA scores ~86.7 consistently** with ~1000+ fast restarts per test case.
- **Geometric SA runs only ~10.6k meaningful iterations per restart** (T drops below 0.01 after ~0.5ms). Each restart is fast but shallow.
- **Linear-cooling SA gets ~1.7M iterations per 0.10s restart** — much deeper exploration but only ~9 restarts per test case.
- **The quality-vs-quantity tradeoff favors fewer-but-deeper restarts** when machine speed is consistent (judge environment).
- **Approaches that failed:** KL passes (high variance 84-87), tabu search (85, too expensive), LAHC (80-83), pure greedy restarts (81), spectral initialization (no consistent gain), greedy construction init (84), ILS with adaptive perturbation (80.6).

## System Interface

- **Build:** Automatic (frontier eval compiles C++17 internally).
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0–100).
- **Baseline result:** Original solution scored 86.7 (5-run mean).

## Code Map

- `solution.cpp:1` — The single file to edit. Everything goes here.
- `algorithmic/problems/192/config.yaml:2` — Time limit (1s) and case count (30).
- `algorithmic/problems/192/chk.cc` — Testlib checker computing c/m score.

## Code Targets

### h-main (linear-cooling SA)
- **File:** `solution.cpp` — full rewrite
- **Algorithm:** Random init → greedy to local optimum → SA with linear temperature (T = T0*(1-frac) + Tf*frac, where frac = elapsed_in_sa/0.10s) → restart. T0=3.0, Tf=0.001. Time checks every 256 SA iterations.
- **Reference implementation:** The designer validated this as `solution_v19.cpp` in the worktree (scores 87.55-87.60).

### h-ablation (geometric-cooling SA, baseline)
- **File:** `solution.cpp` — use iter-1 baseline structure
- **Algorithm:** Random init → greedy → SA with T=2.0, geometric cooling 0.9995, cap 200k iterations, per-iteration time check, 0.90s limit → restart.
- **Reference:** Original `solution.cpp` in the worktree (scores ~86.7).

## What I Tried That Didn't Work

- **KL/Kernighan-Lin bucket passes (v7):** Peaked at 87.4 but scored 84.2-84.5 half the time. Too expensive, reduces restart count.
- **Tabu search (v_tabu):** Scored 85.1. Per-iteration O(n) scan for best non-tabu move makes it too slow.
- **LAHC (v16):** Scored 80-83. Late acceptance doesn't work well for Max-Cut.
- **Pure greedy restarts (v5):** Scored 81. Without SA, greedy local optima are too shallow.
- **Spectral initialization (v13):** Scored 83.5-86.8, no consistent improvement over random init.
- **Greedy construction (v6):** Scored 84.4. Slower than random init, fewer restarts.
- **ILS/perturbation from best (v9):** Scored 80.6. Adaptive perturbation + greedy from best solution was unstable.
- **T0=2.0 with linear cooling (v22):** Scored 84.3-87.6. Not enough exploration at T=2.0.
- **T0=5.0 with linear cooling (v23):** Scored 82.4-87.6. Too much exploration at T=5.0.
- **0.15s SA per restart (v21):** Higher variance (76.4 outlier). Too few restarts.
- **0.05s SA per restart (v20):** More variance than 0.10s. Sweet spot is 0.10s.
- **Slower geometric cooling (v28, cooling=0.99994):** Scored 81-87. Too few restarts.
- **T0=3.0 with geometric cooling (v29):** Scored 78-86.7. Higher T with fast cooling wastes initial exploration.
- **Best-tracking during SA (v30):** Vector copy overhead reduces restarts.

## What I Excluded and Why

- **SDP relaxation (Goemans-Williamson):** Requires eigenvalue computation, too slow for n=1000 within 1s.
- **Genetic algorithms:** Too much overhead for 1s budget.
- **Multi-threading:** Compiler flags can't be controlled; unclear if judge supports it.

## Evolution of Thinking

Started by trying to improve upon iter-1 via sophisticated algorithms (KL, tabu, spectral). All scored similarly or worse than the simple greedy+SA+restarts baseline. The breakthrough came from realizing the SA cooling schedule was the bottleneck: geometric cooling wastes most of the time budget because T drops to near-zero after ~10k iterations (~0.5ms), but each restart gets 0.9ms total. Switching to linear cooling that uses the FULL 0.10s SA budget per restart gave each restart ~170x more SA iterations and produced the best scores (87.6). The tradeoff is fewer restarts (9 vs 1000+), which works because each restart is much higher quality.

## Current Status

- **Validated:** Linear-cooling SA at 87.55-87.60 (v19), geometric SA at 86.7 (original).
- **Uncertain:** Whether the judge's machine has consistent timing (variance seen locally may be CPU-load-dependent).
- **Suggested next:** If 87.6 is confirmed, try combining linear cooling with KL passes for a potential 88+ push. Or try a 2-opt neighborhood (swap pairs across sides) instead of single-vertex flips.

## Warnings & Constraints

- The 1s time limit is strictly enforced. Use 0.90s as the internal budget.
- `frontier eval` compiles internally — you cannot pass compiler flags.
- Scores may vary ±0.5 points between runs due to time-based RNG seed.
- The batched time check (every 256 iterations) means SA may slightly overshoot the 0.10s per-restart budget. This is acceptable because the outer loop also checks time.
