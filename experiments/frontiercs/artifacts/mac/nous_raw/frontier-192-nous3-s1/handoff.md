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

### h-ablation (geometric-cooling SA, baseline)
- **File:** `solution.cpp` — use iter-1 baseline structure
- **Algorithm:** Random init → greedy → SA with T=2.0, geometric cooling 0.9995, cap 200k iterations, per-iteration time check, 0.90s limit → restart.

## What I Tried That Didn't Work

- **KL/Kernighan-Lin bucket passes:** Peaked at 87.4 but scored 84.2 half the time.
- **Tabu search:** Scored 85.1. Too slow per iteration.
- **LAHC:** Scored 80-83.
- **Pure greedy restarts:** Scored 81. 
- **Spectral initialization:** No consistent improvement.
- **Greedy construction:** Scored 84.4.
- **ILS/perturbation from best:** Scored 80.6.
- **Various T0 and SA budget tunings:** T0=3.0 with 0.10s/restart was the sweet spot.

## What I Excluded and Why

- **SDP relaxation:** Too slow for n=1000 within 1s.
- **Multi-threading:** Can't control compiler flags on judge.

## Evolution of Thinking

Iter-1 established greedy+SA+restarts at ~87. Iter-2 explored many alternatives (KL, tabu, spectral, LAHC) — all scored similarly or worse. The breakthrough was recognizing the geometric cooling schedule wastes ~99% of SA time because T drops to negligible after ~0.5ms per restart. Linear cooling uses the full 0.10s budget, giving 170x more SA iterations per restart. Fewer restarts (9 vs 1000+) but much higher quality each.

## Current Status

- **Validated:** Linear-cooling SA at 87.55-87.60, geometric SA at 86.7.
- **Uncertain:** Judge machine timing consistency.
- **Suggested next:** If 87.6 confirmed, try combining linear cooling with 2-opt swaps or KL passes.

## Warnings & Constraints

- 1s time limit strictly enforced. Use 0.90s internal budget.
- Scores vary ±0.5 points between runs (time-based RNG seed).
- Batched time checks every 256 iterations may slightly overshoot the 0.10s SA budget per restart.
