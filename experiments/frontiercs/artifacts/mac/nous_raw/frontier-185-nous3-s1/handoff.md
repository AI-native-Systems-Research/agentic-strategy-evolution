# Handoff — Iteration 1 (Maximum Clique, Problem #185)

### Goal
Implement and measure two max-clique algorithms: a full BnB approach (h-main) and a greedy-only approach (h-control-negative), then compare scores.

### Key Discoveries
- **Bitset intersection is the key speedup.** Using `bitset<1001> adj[1001]` and computing `sub & adj[v]` for candidate generation made the BnB ~3x faster than array-based adjacency checks. This was the difference between 80 and 99.345 score.
- **Degeneracy ordering matters.** Processing vertices from highest core number first concentrates search in the dense subgraph where large cliques live. Combined with BnB, this is very effective.
- **Greedy coloring bound is tight enough.** Sequential greedy coloring (first-fit) gives a good upper bound. DSATUR or other fancier orderings added overhead without improving scores.
- **Time sensitivity is real.** The judge uses a 2.0s time limit. Solutions that take >1.85s on some test cases show score variance (some runs get 89, others 99) due to system load. Use 1850ms as the safe cutoff.
- **500 greedy restarts provide a good lower bound quickly** (<50ms). This seeds the BnB with a strong initial solution, enabling more pruning.
- **Rebuilding the `sub` bitset each iteration is faster than incremental removal** — likely due to cache effects. The incremental approach caused timing variance.

### System Interface
- **Build:** Handled internally by `fmeasure_185.sh` (compiles C++17)
- **Run baseline:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout
- **Baseline result:** SCORE: 99.345 (consistent across 6 runs)

### Code Map
- `solution.cpp:1-170` — entire solution. Key sections:
  - `mcq_bs()` function — the BnB with bitset candidate tracking. Check here if BnB is slow.
  - Degeneracy ordering block in `main()` — min-degree removal loop. Check here if ordering seems wrong.
  - Greedy coloring inside `mcq_bs()` — uses `uint64_t used[16]` for fast color tracking.

### Code Targets
- **h-main:** `solution.cpp` — full implementation with BnB + greedy restarts + degeneracy ordering + bitset intersection. Already implemented and validated at 99.345.
- **h-control-negative:** `solution.cpp` — remove the entire BnB loop (the `for (int i = N-1; ...)` block in main). Keep only the greedy restarts section.

### What I Tried That Didn't Work
- **`bool g[MAXN][MAXN]` adjacency matrix:** Slower than bitset for candidate intersection. Score was ~96.7 vs 99.3 with bitset.
- **Static arrays in recursive function:** Overwritten by recursive calls — caused wrong results.
- **DSATUR coloring:** Added overhead without tighter bounds. Reduced score from timing pressure.
- **MaxCliqueDyn recoloring:** Tried to improve the coloring bound by swapping colors at tight nodes. Added ~10% overhead per node with minimal pruning benefit.
- **Incremental remaining bitset:** `remaining.reset(v)` instead of rebuilding `sub` — caused timing variance (89 vs 99 scores).
- **Per-level subdeg sorting:** Sorting candidates by subgraph degree at every recursion level was too expensive. Only worth doing at the top-level BnB decomposition.
- **Bron-Kerbosch with pivoting:** Scored ~78 — the pivot selection added overhead and the pruning was weaker than coloring bounds.

### What I Excluded and Why
- **Simulated annealing / tabu search:** Could improve on hard instances where BnB times out, but the current score (99.345) leaves little room for improvement.
- **Complement graph approach:** For dense graphs, working on the complement and finding independent sets can be faster. Excluded because the current approach handles density well enough.
- **Parallel search:** Single-threaded constraint from the judge.

### Evolution of Thinking
Started with simple BnB (score 80) → added degeneracy ordering (96.7) → switched from `bool g[][]` to `bitset adj[]` for candidate intersection (99.345). The key insight was that the bottleneck wasn't the algorithm design but the constant factor — bitset parallelism for 1001-vertex candidate sets made the critical difference.

### Current Status
- **Validated:** h-main implementation at 99.345, measure script works reliably, time cutoff at 1850ms is safe
- **Uncertain:** Whether the remaining 0.655% comes from one hard test case timing out or from genuinely missing the optimal clique
- **Suggested next:** If score needs improvement, try (1) complement graph for very dense instances, (2) local search post-processing for cases where BnB times out, (3) tighter coloring via DSATUR only at shallow BnB depths

### Warnings & Constraints
- **Score variance:** If the time cutoff is too aggressive (>1850ms), scores fluctuate between runs due to system load. Keep at 1850ms.
- **Stack depth:** Deep recursion with large local arrays (`int V[1000]`, `int color[1000]`) can use significant stack space. Haven't hit limits at N=1000 but could be an issue on some judges.
- **`_Find_first` / `_Find_next`:** These are GCC extensions on `bitset`. The judge uses a GCC-compatible compiler.
