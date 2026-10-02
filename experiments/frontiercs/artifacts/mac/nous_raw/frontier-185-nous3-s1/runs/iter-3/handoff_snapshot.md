# Handoff — Iteration 3 (Maximum Clique, Problem #185)

### Goal
Confirm the production BnB + local-search solution achieves score 100 at full scope, and test whether reallocating 100ms from BnB to local search maintains robustness.

### Key Discoveries
- **Score 100 is stable.** Two consecutive measurements of the current solution both returned 100, confirming iter-2's finding.
- **Both BnB-only and BnB+local-search achieve 100.** Iter-2 refuted the hypothesis that local search is necessary — BnB-only also scores 100 under normal load. Local search is defensive insurance only (RP-4).
- **Iter-1's 99.345 was a system load artifact.** Not an algorithmic limitation (RP-3).
- **BBMC bitset coloring is worse at N≤1000.** Higher constant factor than pairwise checks for small candidate sets (iter-1, iter-2 discovery).
- **The algorithm is well-tuned.** Greedy init (2000 restarts, 100ms) → BnB with degeneracy ordering (1800ms) → local search swap recovery (100ms) covers all test cases.

### System Interface
- **Build:** Handled by `fmeasure_185.sh` (g++ -O2 -std=c++17)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` on stdout
- **Baseline result:** SCORE: 100 (2 consecutive runs in iter-3 design phase)

### Code Map
- `solution.cpp:18-91` — `mcq_bs()` BnB with greedy coloring. The core search. Check here if BnB is slow or returning suboptimal cliques.
- `solution.cpp:28,81,287` — Timeout thresholds (1800ms). h-main changes these to 1700ms.
- `solution.cpp:93-216` — `local_search()` swap-based perturbation. Activated only on BnB timeout. Check if swaps aren't finding improvements.
- `solution.cpp:218-278` — Main setup: adjacency, degeneracy ordering, greedy init.
- `solution.cpp:280-299` — BnB decomposition loop.
- `solution.cpp:301-304` — Local search activation guard (`timed_out && ms() < 1900`).

### Code Targets
- **h-main:** `solution.cpp` lines 28, 81, 287 — change `1800` to `1700` (BnB timeout). This reallocates 100ms to local search.
- **h-control-negative:** No code changes. Run current solution.cpp as-is.

### What I Tried That Didn't Work
- **BBMC-style bitset coloring (iter-1, iter-2):** Score dropped to 90. Overhead from bitset operations exceeds savings at N≤1000.
- **Incremental sub with BBMC (iter-2 v3):** Score 99.345, no improvement over base.
- **Assuming iter-1's 99.345 was algorithmic (iter-2):** It was system load variance. BnB-only also achieves 100 under normal conditions.

### What I Excluded and Why
- **Tabu search:** Simple swap + perturbation already achieves 100. Complexity not justified.
- **Complement graph approach:** All test cases handled within time budget already.
- **Parallel search:** Judge is single-threaded.
- **Further BnB optimizations:** Diminishing returns — BnB already solves instances within budget.

### Evolution of Thinking
Iter-1: Discovered BnB + greedy coloring as core approach, identified timeout gap.
Iter-2: Tried to fix timeout gap with local search (worked) and BBMC (failed). Discovered the gap was actually system load variance.
Iter-3: Problem is solved at 100. Focus shifts to confirming robustness and testing a minor time-management tweak.

### Current Status
- **Validated:** Production solution scores 100 consistently (2/2 in iter-3 design, 7/7 post-warmup in iter-2)
- **Uncertain:** Behavior under extreme system load (iter-1 showed 90 under load)
- **Suggested next:** Problem is solved. If further work needed, could add adaptive timeout based on instance size (small N → more BnB time, large N → more local search time). But score is already 100.

### Warnings & Constraints
- **Time margin is tight.** BnB at 1800ms + local search at 1900ms leaves 100ms before the 2000ms judge limit. System load can eat this margin.
- **`_Find_first` / `_Find_next` are GCC extensions.** Judge uses GCC, so fine.
- **First-run cold start.** The measure script compiles on first run, which can cause timeout on the first test case (observed as score 90 in iter-2 first run). Subsequent runs are fine.
