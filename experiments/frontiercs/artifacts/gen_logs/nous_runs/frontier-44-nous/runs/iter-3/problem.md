# Problem Framing — Iteration 3

## Research Question

What algorithm maximizes the Frontier-CS judge score for problem #44 (Traveling Santa with Carrot Constraint)?

Previous iterations established NN construction + spatial NN-list 2-opt (K=20) as the best approach, scoring 76.3. This iteration investigates whether multi-start construction, or-opt with linked-list moves, and better time allocation can push the score higher.

Key code references:
- `chk.cc:91-101` — penalized cost computation
- `chk.cc:133-176` — scoring formula (part1+part2, tau=1.25, s_full=N^0.6, visibility remap)
- `chk.cc:19-42` — piecewise linear visibility remap with steep cliff at ratio_base=0.66-0.75

## System Interface

- **Build:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` where n is 0-100 (average across 20 test cases)
- **Time limit:** 2.5s per test case (config.yaml says 2.5s, not 2.0s as in problem text)
- **Code evidence:**
  - `config.yaml:3` — `time: 2.5s`
  - `chk.cc:150` — `s_full = pow((double)N, 0.6)` controls full-score threshold
  - `chk.cc:19-42` — visibility remap anchors (0.66→0.30, 0.75→0.70 — steep cliff)

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```

## Baseline Validation

The iter-2 solution (NN construction + NN-list 2-opt K=20 + window 2-opt + carrot) was validated:
- SCORE: 76.288 (consistent across 3 runs, variance ±0.5 from time-dependent 2-opt convergence)
- 14/20 test cases score 100.0%, contributing 1400/20 = 70.0 to the average
- 6 failing test cases: TC1(10.6%), TC2(7.1%), TC4(21.9%), TC6(48.7%), TC7(29.3%), TC10(8.1%)

## Per-Test-Case Analysis (Critical Discovery)

Test case sizes: N ∈ {10, 97, 250×3, 1000, 5000×3, 15000, 40000, 80000×4, 120000×4, 200000}

**Failing test cases — diagnostic:**

| TC | N | Type | Score | ratio_base | Bottleneck |
|---|---|---|---|---|---|
| 1 | 10 | grid 5×2 | 10.6% | 0.31 | s_full=3.98 too small — mathematically limited |
| 2 | 97 | scattered | 7.1% | 0.19 | Small s_full=16.4 limits achievable score |
| 4 | 1000 | scattered | 21.9% | 0.51 | Correlated x,y data → identity baseline efficient |
| 6 | 15000 | grid 2501×6 | 48.7% | 0.70 | **2-opt cycling bug** — stuck at pass 38 |
| 7 | 40000 | scattered | 29.3% | 0.65 | Correlated data (avg step 62M vs expected 530M) |
| 10 | 200000 | grid 800×250 | 8.1% | 0.22 | 2-opt hasn't converged (500 impr/pass at timeout) |

**Key timing observations:**
- TC4 (N=1000): 2-opt converges in **11ms** — 2490ms unused
- TC7 (N=40000): 2-opt converges in **482ms** — 2018ms unused
- TC6 (N=15000): 2-opt **cycles** at pass 38 (exactly 3388 improvements/pass forever)
- TC10 (N=200000): 2-opt **hasn't converged** at 2000ms (still ~500 impr/pass)
- TC8 (N=80000, 100%): NN construction alone is perfect — **0 improvements** in first 2-opt pass

## Experimental Conditions

### h-main: Multi-start NN + 2-opt with cycling detection and or-opt
Replace solution.cpp with an algorithm that:
1. Detects test case characteristics (N, time budget)
2. For N ≤ 5000: multi-start NN from random starting cities + 2-opt each + keep best
3. For 5000 < N ≤ 50000: limited multi-start (3-5 attempts) + 2-opt with cycling detection
4. For N > 50000: single-start NN + 2-opt (current approach)
5. After 2-opt: or-opt via linked list (O(1) per move) in remaining time
6. Final post-2opt sweep after or-opt
7. Carrot optimization at end
**Target**: Score ≥ 76.5, improving on the 6 failing test cases

### h-control-negative: Baseline iter-2 algorithm (no changes)
Exact copy of iter-2's winning solution (proto_v10.cpp) to measure judge variance and confirm no regression.
**Target**: Score ≈ 76.3 (within ±0.5 of previous measurement)

## Success Criteria

- **CONFIRMED**: h-main scores ≥ 76.5 consistently (above baseline + variance range)
- **REFUTED**: h-main scores ≤ 76.3 (within baseline variance)
- **PARTIALLY_CONFIRMED**: h-main improves some test cases but not overall

## Constraints

- Time limit: 2.5s per test case on judge hardware (use ≤ 2350ms safety margin)
- Memory: 512MB
- 20 test cases averaged, each worth 5% of total score
- Must not regress on the 14 test cases currently scoring 100%

## Prior Knowledge

- **RP-1**: Strip+2opt scored 55.4 (iter-1)
- **RP-2**: NN-list 2-opt escapes window 2-opt local optima (iter-2)
- **RP-3**: Carrot penalty contributes only 1-5% of total cost
- **RP-4**: NN+NN-list 2-opt K=20 scores 76.3 (iter-2 confirmed)
- **RP-5**: NN construction provides quality + stability over strip construction

**Iter-3 exploration findings (NOT yet confirmed by experiment):**
- 2-opt cycling bug on grid data (TC6) — detected by monitoring per-pass cost change
- Multi-start doesn't improve score (local optima are similar quality)
- ILS (double-bridge + re-2opt) doesn't improve (re-2opt converges to same quality)
- Or-opt with linked list is neutral (±0.3 of baseline)
- K=30 is worse than K=20 (extra precompute steals 2-opt time)
