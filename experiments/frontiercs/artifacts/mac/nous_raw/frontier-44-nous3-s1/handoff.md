# Handoff — Iteration 1

## Goal

Implement and measure a grid nearest-neighbor TSP solver with time-guarded 2-opt for Frontier-CS problem #44 (penalized TSP). Target score: ≥78 (baseline: 0 for x-sorted order).

## Key Discoveries

- **Grid NN scores 78.2 consistently.** The spatial grid with G=sqrt(N/4) cells per dimension and expanding-ring search reliably finds nearest unvisited cities. This is the dominant score contributor.
- **2-opt adds 0.1–0.3 points for small N only.** For N≤5000, systematic exact 2-opt helps marginally. For N>10000, any local search risks TLE.
- **Penalty is a ~1% effect.** Only 10% of steps are penalized, and the penalty is 10% extra distance. Prime density ~1/ln(N) means ~16K primes out of 200K cities, but 20K penalty positions exist — not all coverable. Prime-aware placement barely moves the needle.
- **Alternative constructions all fail.** Hilbert curve (40.4), strip boustrophedon (40.4), greedy TSP (74.9), set-based NN (68.2, 26.1) — all score lower, mostly due to TLE on large inputs.
- **O(1) 2-opt delta doesn't work with penalties.** Boundary-only delta ignores internal penalty changes from segment reversal, accepting bad moves (scored 32.0). Must compute exact segment delta.

## System Interface

- **Build:** Handled by judge (C++17, -O2 implied)
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout (0–100, higher is better)
- **Baseline result:** Pure NN = 78.193, NN + safe 2-opt = 78.29

## Code Map

- `solution.cpp:1` — The entire solution. Replace stub with full implementation.
- `fmeasure_44.sh:5` — Judge invocation. Calls `frontier eval algorithmic 44`. Do not modify.

## Code Targets

- **h-main → solution.cpp**: Replace the 3-line stub with a complete NN+2opt implementation. The reference implementation is saved at `inputs/solution_nn_2opt.cpp`. Use it as a starting point but improve: better time management, possibly smarter 2-opt candidate selection.

## What I Tried That Didn't Work

| Approach | Score | Why it failed |
|----------|-------|---------------|
| Set-based NN (efficient removal) | 68.2 | set iterator overhead causes TLE on large N |
| Binary-search NN on x-sorted array | 26.1 | set<int> operations too slow at scale |
| Hilbert curve ordering | 40.4 (with NN fallback: 73.5) | Poor tour quality; computing both wastes time |
| Strip boustrophedon | 40.4 | Bad spatial locality between strips |
| Greedy TSP (sorted edges) | 74.9 | Edge sorting + NN list construction too slow |
| SA with random swaps | 74.3 | Temperature too high, accepts bad moves |
| NN-guided 2-opt (K-NN lists) | 69.7 | Building NN lists for all cities causes TLE |
| O(1) boundary-only 2-opt delta | 32.0 | Ignores internal penalty changes, accepts harmful moves |
| Random swap local search | 73.3 | Swaps are poor TSP moves (don't fix crossings) |
| Prime-aware NN (0.95x bonus for primes) | 78.2 | Sometimes picks farther city; savings too small |
| Post-hoc prime swap optimization | 78.2 | Window=200 swap search barely finds improvements |

## What I Excluded and Why

- **Christofides algorithm**: O(N^3) MST + matching, impossible in 2s for N=200K.
- **LKH-style moves**: Too complex to implement correctly within tool budget. Could be iter-2.
- **Multi-start NN**: Each start takes ~0.5–1s, leaving no time for the second start on large inputs. Marginal benefit since tour quality depends on starting from city 0.
- **3-opt and or-opt moves**: Or-opt (relocate) changes step indices for all subsequent positions, making exact delta O(N). Only useful with approximate delta, which I couldn't get right.

## Evolution of Thinking

1. Started thinking the penalty (carrot constraint) was the key mechanism to exploit. Discovered it's only ~1% of total cost.
2. Assumed 2-opt with O(1) delta would work like standard TSP — wrong, penalties make delta O(segment_length).
3. Assumed faster NN data structures (set, binary search) would help — wrong, the constant-factor overhead causes TLE.
4. Realized the DOMINANT constraint is the 2-second time limit on N=200K inputs. Every optimization must be weighed against TLE risk.
5. Concluded that for iter-1, the grid NN construction IS the algorithm. Improvements come from better construction, not post-hoc optimization.

## Current Status

- **Validated:** Grid NN scores 78.2 consistently. Safe 2-opt adds 0.1 for N≤10000. Solution compiles and runs within time limit.
- **Uncertain:** Whether a better construction (e.g., farthest-insertion, or-opt with approximate delta) could push past 80. Whether the judge uses a faster machine than my Mac (which would allow more local search).
- **Suggested next:** (1) Try farthest-insertion heuristic as construction. (2) Implement or-opt with an O(1) approximate delta that accounts for the most common penalty changes. (3) Try a proper LKH-style move (sequential search) which handles penalty naturally. (4) Test whether the judge machine is faster/slower than local to calibrate time budgets.

## Warnings & Constraints

- **TLE is the #1 failure mode.** Any approach that works for small N may TLE on N=200K. Always test with the full judge (which includes large cases), never just local runs on small inputs.
- **Score averaging across test cases.** A TLE on one large case can tank the average. A conservative approach that scores well on ALL cases beats an aggressive one that TLEs on the largest.
- **Grid NN with visited[] array is the fastest construction.** Do NOT use set, map, or any log(N)-per-operation data structure in the inner loop. Vector iteration with boolean mask is fastest.
- **The judge score of 0 for x-sorted order confirms it's the baseline.** Any tour that's merely "different" from x-sorted will score > 0. The question is how much better.
