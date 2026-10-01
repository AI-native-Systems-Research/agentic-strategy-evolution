# Handoff — Iteration 3 (Traveling Santa with Carrot Constraint)

## Goal

Implement and test a multi-start NN + 2-opt with cycling detection + or-opt solution for problem #44, measuring whether it beats the iter-2 baseline of 76.3 on the Frontier-CS judge. The control arm runs the exact iter-2 solution for variance measurement.

## Key Discoveries

1. **14/20 test cases already score 100%** — only TC1(N=10), TC2(N=97), TC4(N=1000), TC6(N=15000), TC7(N=40000), TC10(N=200000) are failing. All improvement must come from these 6 cases.

2. **2-opt cycling bug on grid data** — TC6 (N=15000, grid 2501×6) shows exactly 3388 improvements per pass after pass 38, with tour cost not decreasing. Fixed by monitoring per-pass cost change and breaking when cost doesn't decrease by 0.001%.

3. **Multi-start helps only for small N** — For N=1000 (TC4), 2-opt converges in 11ms, leaving 2490ms unused. Multi-start from random cities (200+ restarts) can explore many local optima. For N>15000, each 2-opt run is too slow for more than 2-3 starts.

4. **ILS is risky for time** — proto_iter3f (aggressive ILS) scored 69.8 due to TLE. proto_iter3g (conservative ILS with time budget) scored 76.3 — equal to baseline. Double-bridge perturbation + re-2opt doesn't find better solutions within the time budget.

5. **TC7 has correlated data** — average identity step is 62M vs expected 530M for uniform random, meaning the identity baseline is already efficient, limiting how much any tour optimizer can beat it.

6. **Scoring formula has a steep cliff** — ratio_base 0.66→0.75 maps to visible 0.30→0.70. TC6 at ratio_base=0.70 is right at the cliff edge, so even small improvements in tour cost translate to disproportionate score gains.

7. **K=30 is worse than K=20** — extra precompute time for larger K steals 2-opt passes, net negative effect.

## System Interface

- **Build:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100 (average across 20 test cases, visibility remapped)
- **Baseline result:** SCORE: 76.288 (iter-2 solution, consistent across 3 runs ±0.5)
- **Checker compilation:** `g++ -O2 -std=c++17 -I../../judge/include -o chk chk.cc` (need `-I../../judge/include` for testlib.h)

## Code Map

- `chk.cc:91-101` — `computeCost()` with penalty logic (1.1x on every 10th step if source not prime). Check here if cost calculations seem wrong.
- `chk.cc:133-176` — Scoring formula: part1 (linear, 0.20 weight) + part2 (log tail, 0.80 weight, tau=1.25, s_full=N^0.6). Check here if score seems inconsistent with tour quality.
- `chk.cc:19-42` — Piecewise linear visibility remap. The steep cliff at 0.66→0.75 is the critical scoring bottleneck.
- `config.yaml:3` — `time: 2.5s` (NOT 2.0s as problem text says)
- `proto_v10.cpp` — Iter-2 winning solution (baseline). Copy this exactly for h-control-negative.
- `proto_iter3g.cpp` — Conservative ILS variant (76.3). Has cycling detection + ILS with time management. Good reference for executor.
- `proto_iter3h.cpp` — Multi-start variant (76.3). Has multi-start NN construction + cycling detection. Good reference for executor.

## Code Targets

### h-main: solution.cpp
- Start from `proto_iter3h.cpp` as the closest prototype
- **Multi-start NN**: `nn_construct()` function (lines 78-124) builds NN chain from any start city, rotates to put city 0 at front
- **Cycling detection**: In `do_nn2opt()` (lines 66-73), breaks when rawCost doesn't decrease by 0.001%
- **Strategy branching**: Lines 204-249, adapts number of starts based on N
- Add or-opt pass after 2-opt convergence using NN-list for candidate selection
- Add window 2-opt after or-opt (already present in lines 252-279)

### h-control-negative: solution.cpp
- Copy exact content of `proto_v10.cpp` — no modifications

## What I Tried That Didn't Work

| Attempt | File | Score | Why it failed |
|---|---|---|---|
| K=25 + or-opt + ILS | proto_iter3.cpp | 76.0 | Or-opt disrupts 2-opt improvements; K=25 wastes precompute time |
| Or-opt after 2-opt | proto_iter3b.cpp | 76.3 | Or-opt improvements are neutral — same quality as without |
| City swap | proto_iter3c.cpp | 75.9 | Swap neighborhood too small, and conflicts with 2-opt |
| Linked-list or-opt | proto_iter3d.cpp | 75.9 | Linked-list overhead + or-opt doesn't find improving moves |
| Serpentine construction | proto_iter3e.cpp | 75.9 | Rotation to start from city 0 breaks serpentine pattern |
| Aggressive ILS | proto_iter3f.cpp | 69.8 | **TLE** — double-bridge+re-2opt on N=15000-40000 exceeds 2.5s |
| Conservative ILS | proto_iter3g.cpp | 76.3 | Neutral — time-managed ILS finds no better solutions |
| Multi-start NN | proto_iter3h.cpp | 76.3 | Neutral — different starting cities converge to same-quality local optima |

## What I Excluded and Why

1. **3-opt / LKH moves** — Too complex to implement correctly within the session; would need verified LK implementation. Reserved for iter-4.
2. **Greedy construction** — Building tour by adding cheapest edges. Would require edge-list + union-find. NN construction is simpler and produces similar quality for TSP.
3. **Christofides** — Minimum spanning tree + matching. High implementation complexity, and NN+2-opt typically matches or beats it for Euclidean TSP.
4. **Penalized cost optimization** — Optimizing the penalized cost directly instead of raw distance. The 10% carrot penalty is small (RP-3: 1-5% of total), and the carrot swap at the end handles it efficiently.

## Evolution of Thinking

Started with the assumption that multi-start, or-opt, and ILS would each provide 1-3% improvement. Discovered that:
- The problem is nearly solved (14/20 at 100%) and the remaining 6 test cases have fundamental limitations (small N → small s_full, correlated data, grid cycling)
- All optimization techniques converge to the same local optimum quality — the NN+2-opt landscape has very uniform basins for this problem's data distributions
- The main untapped opportunity is TC6 (grid, cycling bug) where cycling detection frees ~1500ms, and TC4 (N=1000) where multi-start can explore many optima
- The scoring formula's steep cliff means TC6 improvements are amplified (ratio_base 0.70 → 0.75 maps to visible 0.30 → 0.70)

## Current Status

- **Validated:** Baseline scores 76.3 consistently. Build works. Measurement script works. Checker compiles with `-I../../judge/include`. Per-test-case scoring confirmed.
- **Uncertain:** Whether multi-start + cycling fix + or-opt combined can beat 76.3. Individual prototypes each scored 76.3 or worse. The combination hasn't been tested as a single solution yet — it's possible the synergy (multi-start for small N + cycling fix for TC6 + or-opt for all) pushes score to 76.5-77.
- **Suggested next:** If iter-3 fails to improve: (a) implement proper LK moves (Lin-Kernighan), (b) try penalized-cost-aware 2-opt (optimize penalized cost directly), (c) investigate TC7's correlated data to find a construction heuristic that exploits the correlation.

## Warnings & Constraints

1. **Time limit is 2.5s, NOT 2.0s** — config.yaml says `time: 2.5s`. Use 2350ms safety margin.
2. **fmeasure_44.sh takes the .cpp file path**, not the binary path. It compiles internally.
3. **Judge hardware is slower** — judge times differ from local. proto_iter3f (aggressive ILS) scored 69.8 on judge despite finishing locally. Use conservative time budgets.
4. **The sieve flags primes for cities** — `isp[i]` is true if city index `i` is prime, used for carrot penalty. Don't confuse with city coordinates.
5. **Tour format**: first line is N+1 (number of cities + return), then N+1 city indices starting and ending with 0.
6. **NN fallback search** — when all K nearest neighbors are visited, the fallback scans `cur±r` for nearby unvisited cities. This works because cities are sorted by x-coordinate in the input for most test cases (verified for grids).
