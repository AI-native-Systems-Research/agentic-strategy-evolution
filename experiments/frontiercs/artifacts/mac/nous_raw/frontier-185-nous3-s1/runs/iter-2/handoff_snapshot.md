# Handoff — Iteration 2 (Maximum Clique, Problem #185)

### Goal
Validate that BnB + local search achieves score 100 consistently (h-main) vs the iter-1 BnB-only baseline at 99.345 (h-control-negative).

### Key Discoveries
- **Local search is the key to 100.** Adding swap-based perturbation after BnB timeout raised score from 99.345 → 100 consistently (4/4 runs).
- **BnB times out on hard instances.** The `timed_out` flag triggers on some test cases at 1800ms, confirming the gap comes from incomplete BnB, not algorithmic error.
- **1-remove/2-add swaps are sufficient.** The local search finds improvements by removing one clique vertex and adding two connected replacements. No need for larger perturbations.
- **BBMC-style bitset coloring is NOT faster for N≤1000.** Tested in v2 and v3 — the bitset AND operations on 1001-bit vectors have higher constant factor than pairwise adjacency checks for small candidate sets deep in recursion. Score dropped to 90 with BBMC.
- **100ms is enough for local search.** BnB at 1800ms + local search at 1900ms cutoff = reliable 100.

### System Interface
- **Build:** Handled by `fmeasure_185.sh`
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout
- **Baseline result:** SCORE: 100 (4 consecutive runs)

### Code Map
- `solution.cpp:18-80` — `mcq_bs()` BnB with greedy coloring. Check if BnB is slow.
- `solution.cpp:83-178` — `local_search()` swap-based perturbation. Check if local search isn't finding improvements.
- `solution.cpp:191-210` — Greedy initialization (2000 restarts, 100ms budget).
- `solution.cpp:213-228` — BnB decomposition with degeneracy ordering.
- `solution.cpp:231-233` — Local search activation on timeout.

### Code Targets
- **h-main:** `solution.cpp` — already implemented (v4). BnB + local search.
- **h-control-negative:** `solution.cpp` — revert to iter-1 version (remove local_search function, restore 1850ms timeout, 500 greedy restarts).

### What I Tried That Didn't Work
- **BBMC-style bitset coloring (v2):** Score dropped to 90. The independent-set-extraction coloring allocates `bitset<1001> color_class[1001]` per recursive call — ~125KB stack per level. Massive overhead for small candidate sets.
- **BBMC coloring + incremental sub (v3):** Score stayed at 99.345. The coloring overhead exactly canceled the sub-reconstruction savings.
- **Incremental sub alone (without BBMC coloring):** Tested implicitly in v3 — no improvement over the original sub-reconstruction approach, likely due to cache effects favoring sequential writes.

### What I Excluded and Why
- **Tabu search:** Full tabu with aspiration criteria is more sophisticated but the simple swap + random perturbation already achieves 100. No need for complexity.
- **Complement graph approach:** For very dense graphs, could be faster. But BnB + local search handles all test cases within time, so unnecessary.
- **Parallel search:** Judge is single-threaded.
- **Deeper swaps (2-remove/3-add):** 1-remove/2-add is sufficient for 100.

### Evolution of Thinking
Iter-1 identified BnB timeout as the bottleneck (99.345 vs 100). Initially tried to speed up BnB itself (BBMC coloring) — this made things worse due to constant-factor overhead at N≤1000. The breakthrough was realizing that instead of making BnB faster, we should use the remaining time budget for a different search strategy (local search) that complements BnB's strengths.

### Current Status
- **Validated:** h-main at score 100 (4/4 runs), measure script reliable
- **Uncertain:** Whether 100 holds under heavy system load (iter-1 showed variance under load)
- **Suggested next:** Problem is solved at 100. If further robustness needed, could add adaptive time management (detect system load and adjust cutoffs).

### Warnings & Constraints
- **Time budget is tight.** BnB at 1800ms + local search at 1900ms leaves only 100ms margin before the 2000ms judge limit. If system is under heavy load, scores could drop.
- **`_Find_first` / `_Find_next` are GCC extensions.** Judge uses GCC, so this is fine.
- **Stack depth:** Deep BnB recursion with `int V[1000]` and `int color[1000]` per level uses significant stack. No issues observed at N=1000.
