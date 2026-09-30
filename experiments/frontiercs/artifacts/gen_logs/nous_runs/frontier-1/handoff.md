# Handoff — Iteration 2

## Goal

Implement and test two algorithmic variants for Frontier-CS Problem #1 (Treasure Packing, 2D bounded knapsack):
- **h-main**: Optimized B&B with reduced ternary iterations (20→12) and a clock()-based time guard (~800ms cutoff). Measure judge score.
- **h-ablation**: Multi-greedy + local search only (no B&B). Measure judge score.

## Key Discoveries

1. **Docker timing causes intermittent TLEs.** The iter-1 B&B solution scores 85–100 across 5 runs (observed: 100, 95, 100, 90, 100). The algorithm finds exact optima locally (gap=0 on all 20 cases in <30ms) but Docker's 3–5× slowdown occasionally exceeds the 1s limit.

2. **Reducing ternary search from 20→12 iterations gives 30–37% speedup with zero accuracy loss.** Validated: TC1 goes from 30ms→21ms, TC14 from 19ms→12ms. All 20 test cases still produce exact optima (gap=0). Precision (1/3)^12 ≈ 2×10⁻⁶ is far beyond needed for integer LP bounds.

3. **Greedy+LS (no B&B) achieves optimal on 9/20 cases but fails on 11/20.** Per-case scores range from 43.9 to 100.0, averaging ~85.6. The hardest cases (TC8: 83.7, TC12: 43.9, TC14: 65.3, TC16: 48.2, TC20: 84.5) have large optimality gaps that local search cannot close.

4. **Test data: 20 fixed cases**, each with baseline and best values in `.ans` files. Score = 100 * clamp((your_value - baseline) / (best - baseline), 0, 1), averaged across cases.

5. **Docker uses GCC with `-static` flag.** The field name `ratio` clashes with `std::ratio` when `using namespace std` is active. Use `dens` or another name.

6. **`clock()` is available in Docker's C++ environment** for time measurement. Use `CLOCKS_PER_SEC` for conversion.

## System Interface

- **Build:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
- **Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` where n is 0–100
- **Baseline result:** Iter-1 B&B solution scores 85–100 with Docker variance (100 locally, exact optima on all 20 cases)

## Code Map

- `solution.cpp` — the only file to edit. Currently contains the iter-1 B&B solver.
- `solution.cpp:91` — ternary search loop: `for (int iter = 0; iter < 20; iter++)` — change 20→12 for h-main.
- `solution.cpp:102-133` — `solve()` function: the B&B recursion. Add time guard at entry. Comment out call for h-ablation.
- `solution.cpp:298` — `solve(0, MAX_MASS, MAX_VOL, 0)` call in main: comment out for h-ablation.
- `solution.cpp:300` — second `local_search()` call after B&B: comment out for h-ablation.
- `solution.cpp:264-293` — greedy heuristics: 23 alpha-parameterized variants + 2 pure density sorts.
- `solution.cpp:135-213` — local search: add, swap, remove-refill moves.
- `algorithmic/problems/1/chk.cc:61-91` — checker main logic.
- `algorithmic/problems/1/testdata/{1..20}.in` — test inputs.
- `algorithmic/problems/1/testdata/{1..20}.ans` — baseline and best values.

## Code Targets

### h-main (optimized-bnb-time-guard)
- **File:** `solution.cpp`
- **Change 1:** Line 91 — reduce ternary loop from `iter < 20` to `iter < 12`.
- **Change 2:** Add a global `clock_t start_time;` variable. Set it in `main()` before the greedy section. In `solve()`, add a time check at the top: if `(clock() - start_time) > 0.8 * CLOCKS_PER_SEC`, return immediately.
- **Why:** 30%+ constant-factor speedup plus absolute timing safety net.

### h-ablation (greedy-ls-only)
- **File:** `solution.cpp`
- **Change:** Comment out line 298 (`solve(0, MAX_MASS, MAX_VOL, 0);`) and line 300 (second `local_search();`). Keep all greedy heuristics and first local search.
- **Why:** Measures isolated contribution of B&B to the score.

## What I Tried That Didn't Work

1. **Sorting items by ascending effective max_k (smallest branching factor first):** TC1 went from 30ms→48ms, TC14 from 19ms→66ms. The density-based ordering is much better because it establishes strong lower bounds early.

2. **Using tight Lagrangian bounds at ALL 12 B&B levels (instead of first 8 only):** No improvement — TC1 stayed at 31ms, TC14 at 19ms. Deeper levels have so little remaining capacity that both cheap and tight bounds are equally effective.

3. **(From iter-1) Naive B&B with min-of-two-1D LP bounds:** Timed out at 5+ seconds. Bounds are 80% loose for 2D problems.

4. **(From iter-1) Field name `ratio`:** Compilation failure in Docker's GCC with `using namespace std`.

## What I Excluded and Why

- **DP approaches**: 2D DP with scaling needs either huge memory (20M×25M) or aggressive scaling that loses precision. With n=12, B&B is more natural and already optimal.
- **Meet-in-the-middle**: 6 types × up to 500 quantities = 500^6 ≈ 10^16 combinations per half. Infeasible.
- **Alternative time measurement (gettimeofday, chrono)**: `clock()` is simplest and portable. If it doesn't work in Docker, `chrono::steady_clock` is the fallback.
- **More advanced local search (simulated annealing, tabu)**: The B&B already finds exact optima; more sophisticated LS only helps the fallback case, which the time guard makes rare.

## Evolution of Thinking

1. Started iter-2 expecting to just confirm the iter-1 score of 100.
2. Discovered significant Docker variance (85–100 across 5 runs) — this wasn't visible in iter-1's 3 runs that all scored 100.
3. Identified the root cause: Docker timing variability causing sporadic TLEs on the slowest test cases (TC1, TC14).
4. Found that reducing ternary iterations (20→12) is a clean 30%+ speedup with no accuracy cost — the precision was wildly excessive.
5. Added time guard as the ultimate safety net — even if Docker has an unusually bad run, we never TLE.
6. Validated greedy+LS (no B&B) to have concrete ablation data: 9/20 optimal, avg ~85.6.

## Current Status

- **Validated:** Reduced ternary iterations (12) maintains exact optimality on all 20 cases. Greedy+LS alone averages ~85.6 per case.
- **Uncertain:** Whether the time guard will trigger in Docker under normal conditions (it shouldn't — the optimized B&B runs in <25ms locally, well under the ~200ms Docker budget). Whether `clock()` measures CPU time or wall time in Docker (in C, `clock()` typically measures CPU time; wall time may differ under containerization).
- **Suggested next:** If score is reliably 100, the problem is solved. If time guard triggers on some cases, investigate: (a) further B&B optimizations (precompute suffix bounds), (b) stronger greedy+LS fallback (more aggressive local search neighborhoods).

## Warnings & Constraints

1. **NEVER use `ratio` as a struct field name** with `using namespace std`. GCC in Docker interprets it as `std::ratio` template.
2. **Docker timing is 3–5× slower than bare metal.** Keep solutions under 50ms locally.
3. **JSON output must have all 12 item keys**, even if quantity is 0.
4. **The judge score varies between runs** due to Docker timing. Run multiple times to assess reliability. A single score of 100 does not prove robustness — run at least 3 times.
5. **`clock()` may measure CPU time, not wall time.** If the Docker container has CPU throttling, `clock()` might undercount. Consider `chrono::steady_clock::now()` as an alternative if `clock()` doesn't prevent TLEs.
