# Handoff — Iteration 2

## Goal

Implement two algorithmic strategies for the Traveling Santa with Carrot Constraint problem (#44) and measure each with the judge:
1. **h-main**: NN construction + spatial NN-list 2-opt (K=20) + window 2-opt + carrot — targeting ~76 score
2. **h-ablation**: Strip construction + same optimization pipeline — targeting ~71 score

## Key Discoveries

1. **Spatial NN-list 2-opt is the single biggest improvement over iter-1**: Using K=20 precomputed nearest spatial neighbors per city for 2-opt candidate search jumps score from ~55 to ~76. This works because window-based 2-opt only checks tour-order neighbors (window=30 for N=200K), missing geometrically close cities far apart in tour order.

2. **NN construction beats strip construction by ~5 points**: Greedy nearest-neighbor construction from city 0 produces a tour where consecutive cities are spatially close, giving a better starting point for 2-opt. Strip construction creates inter-strip edges that 2-opt must fix.

3. **NN precompute uses dual x-sorted and y-sorted windows**: Cities are sorted by x (by ID) and by y (separately computed). For each city, candidates from both windows are merged and top-K by squared distance are kept. This catches neighbors in both x and y directions, critical for grid-like test cases (TC10: 800 cols × 250 rows).

4. **Forward-only NN 2-opt outperforms bidirectional**: Checking only j > i (where j is the NN position) is better than also checking j < i, because backward swaps involve very long segment reversals (O(N)) that consume time without proportional tour improvement. Tested: bidirectional scored 71.0 vs forward-only at 76.0.

5. **Or-opt disrupts more than it helps**: Alternating 2-opt and or-opt (single-city relocation) in a mega-loop scored 71.3, worse than pure 2-opt at 76.3. The or-opt moves cities to new positions that require re-optimization, and the time spent on or-opt is better spent on more 2-opt passes.

6. **Time allocation matters**: NN precompute takes 400-500ms for N=200K. Giving ~1.5s to NN 2-opt, ~0.3s to window 2-opt, and ~0.1s to carrot is optimal. Reducing precompute time would give marginal benefit.

7. **Score is reproducible at ±0.5**: v5 scored 76.01 on two consecutive runs. v8 scored 76.32. Variance comes from time-dependent 2-opt convergence.

## System Interface

- **Build:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run/measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0-100, average across 20 test cases)
- **Baseline results:** Identity order = 0, iter-1 strip+2opt+carrot = 55.4, h-main NN+NN2opt = 76.3

## Code Map

- `chk.cc:91-101` — `computeCost()`: penalized tour cost (multiplier 1.1 when t%10==0 and source not prime). **Check here** to verify penalty logic.
- `chk.cc:133-176` — Scoring formula (part1=linear up to r=0.25, part2=log tail with tau=1.25, s_full=N^0.6). **Check here** to understand score curve.
- `chk.cc:19-42` — Visibility remap. **Check here** if scores seem compressed.
- `config.yaml` — Time limit 2.5s, memory 512MB, 20 test cases.
- `testdata/10.in` — Largest test case (N=200K, 800×250 grid). **Check here** for grid structure.
- Reference solutions in `Frontier-CS/algorithmic/solutions/44/` — Various AI solutions. `gemini3pro.cpp` uses bitonic tour + windowed 2-opt + prime swaps (similar to iter-1 approach).

## Code Targets

### h-main: `solution.cpp` (entire file)
Replace stub with complete C++17 program:
- NN precompute: dual x/y-sorted windows, squared distance, K=20 neighbors per city
- Greedy NN construction from city 0 using NN list + fallback x-proximity search
- NN-list 2-opt: forward direction only (j > i), time-budgeted to ~2000ms
- Window 2-opt cleanup: adaptive window (25-300), time-budgeted to ~200ms
- Carrot optimization: swap primes into penalty positions

**Reference implementation**: `proto_v8.cpp` in the worktree (scored 76.3). Use this as the template.

### h-ablation: `solution.cpp` (entire file)
Same as h-main but replace NN construction section with strip-based serpentine construction:
- Sort cities 1..N-1 by y-coordinate
- Divide into √(N·H/W) horizontal strips
- Sort each strip by x, alternate direction
- All other phases (NN precompute, NN-list 2-opt, window 2-opt, carrot) identical

**Reference implementation**: `proto_v4.cpp` in the worktree (scored 71.2, but with K=10; use K=20 for fair comparison).

## What I Tried That Didn't Work

1. **Grid-based NN precompute with ring expansion**: O(N²) worst case for scattered data (2558ms for N=40K). Replaced with dual x/y-sorted windows.
2. **Bidirectional NN 2-opt (j < i swaps)**: Long segment reversals are expensive and don't improve tour quality enough. Scored 71.0 vs forward-only 76.0.
3. **Or-opt + 2-opt mega-loop**: Alternating phases is worse than dedicating all time to 2-opt. Scored 71.3 vs pure 76.3.
4. **Increasing NN 2-opt time to 2000ms (v10)**: Marginal gain (76.29 vs 76.32). The NN 2-opt converges before the time limit on most test cases.
5. **NN construction fallback with only x-proximity**: For grid data (800 distinct x), cities in adjacent columns have IDs 250 apart. The fallback search needs W_nn > 250 or a smarter grid search. Current fallback with expanding ID range works but is slow for edge cases.

## What I Excluded and Why

1. **3-opt / Lin-Kernighan moves**: Too complex to implement correctly within the time budget. 2-opt with NN lists already captures most of the improvement.
2. **Iterated Local Search (double-bridge)**: Requires multiple 2-opt convergences. With NN 2-opt taking 1.5s per convergence for N=200K, only 1 perturbation+re-opt cycle would fit. Not enough for statistical significance.
3. **Simulated annealing**: Requires careful temperature schedule tuning. 2-opt is more predictable.
4. **MST-based construction (Christofides)**: Would require O(N log N) MST computation. NN construction is simpler and produces good results.
5. **Penalty-aware 2-opt**: Accounting for the 1.1 multiplier during 2-opt evaluation makes each check O(segment_length) instead of O(1). Not worth the complexity given carrot is only ~1-5% of cost.

## Evolution of Thinking

Started by trying to fix the "missing direction" in NN 2-opt (checking both j > i and j < i). Discovered that backward swaps are counterproductive — they involve long reversals that are expensive and often suboptimal. This led to the realization that the forward-only approach combined with NN construction (which produces a locally-connected tour) is the sweet spot.

Also tried or-opt as a complement to 2-opt, but found it disrupts the tour structure more than it helps. The key insight is that in the time budget available, maximizing the number of 2-opt evaluations with good candidates (spatial NN lists) is more valuable than diversifying with or-opt or or-3opt moves.

The NN precompute approach evolved from grid-based (too slow for scattered data) to dual sorted-window (fast and general). The dual x/y windows are critical for grid-like data where cities with similar x have very different y (and vice versa).

## Current Status

- **Validated:** h-main algorithm (NN+NN2opt K=20) scores 76.3 ± 0.5. h-ablation (strip+NN2opt K=10) scores ~71.2 (needs retesting with K=20). All 20 test cases handled correctly within 2.5s. NN precompute takes 400-500ms for N=200K.
- **Uncertain:** Whether K>20 would help (diminishing returns expected). Whether a better NN construction (e.g., starting from center or multiple starts) would improve the initial tour. Whether the y-sorted window is large enough for all test case distributions.
- **Suggested next:**
  - Iter-3 should try **3-opt or Lin-Kernighan style moves** for further improvement beyond 2-opt local optimum.
  - Iter-3 should try **multiple NN construction starts** (from different cities) and keep the best initial tour.
  - Iter-3 should investigate **penalty-aware optimization** more aggressively — maybe an SA phase specifically for carrot positions.
  - Iter-3 should consider **adaptive K_NN** — larger K for smaller N where precompute is cheap.

## Warnings & Constraints

1. **NN precompute W_nn must be large enough for grid data**: TC10 has 800 distinct x values with 250 cities each. Cities in adjacent columns differ by ~250 IDs. W_nn=45 for N>80K catches 90 candidates in each direction, which may miss some true nearest neighbors in grid data. Increasing W_nn to 60+ for N>100K would be safer but costs precompute time.

2. **Forward-only NN 2-opt misses backward improvements**: This is a known limitation. The trade-off is accepted because backward swaps with long reversals are expensive. A future approach could limit backward reversals to segment lengths < 1000.

3. **NN construction fallback is slow**: When a city's NN list is exhausted (all K=20 neighbors visited), the fallback searches expanding ID ranges. For cities in sparse regions or at distribution edges, this can be O(N). Mitigated by the fallback's early-exit once a candidate is found.

4. **The `tour` vector is exactly N+1 entries**: `tour[0] = tour[N] = 0`. Do NOT access `tour[N+1]` — this was a segfault source in prototyping (v3 crash on TC4, N=1000 with window=N/2).

5. **Carrot optimization search radius 500**: Swapping primes within 500 tour positions. For N=200K, this is ~0.25% of the tour. Increasing might help for grid data where primes are clustered, but the 10% penalty is only ~1-5% of total cost.
