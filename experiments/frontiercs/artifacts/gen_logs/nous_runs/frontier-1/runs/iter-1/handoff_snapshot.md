# Handoff — Iteration 1

## Goal

Implement and test algorithmic solutions for Frontier-CS Problem #1 (Treasure Packing, a 2D bounded knapsack). The h-main arm should use branch-and-bound with Lagrangian LP relaxation to maximize the judge score. The h-control-negative arm uses a simple greedy for comparison.

## Key Discoveries

1. **The problem is a 2D bounded knapsack with exactly 12 item types.** Mass ≤ 20,000,000 mg, volume ≤ 25,000,000 µL. Quantities up to 10,000 but effective max is min(q, M/m, V/l) — typically 12-333 per type.

2. **Simple 1D LP bounds (min of mass-only and volume-only relaxations) are far too loose.** For test case 1, min(UB_mass, UB_vol) ≈ 316M vs optimal 176M — 80% overestimate. This makes naive B&B infeasible (no pruning).

3. **Lagrangian relaxation (relax one constraint, ternary search for dual variable) gives exact LP bound.** This is tight enough (within ~1% of integer optimum) to make B&B practical with 12 items. Key: relax volume, solve 1D fractional knapsack on mass with modified values (v_i - λ*l_i).

4. **Docker uses GCC with `-static` flag.** The field name `ratio` clashes with `std::ratio` when `using namespace std` is active, causing compilation failure in Docker. Use `dens` or another name instead.

5. **Docker timing variability can cause sporadic TLE.** Solution must run in <50ms locally to reliably pass 1s limit in Docker. The optimized B&B runs in ≤40ms on the slowest test case.

6. **Test data: 20 fixed cases** in `testdata/`, each with baseline and best values in `.ans` files. Score = 100 * clamp((your_value - baseline) / (best - baseline), 0, 1), averaged.

7. **All 20 test cases can be solved optimally.** The B&B finds exact optimum (gap=0) on all 20 cases in <50ms each.

## System Interface

- **Build:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` where n is 0-100
- **Baseline result:** SCORE: 100 (3 consecutive runs with the B&B solution)

## Code Map

- `solution.cpp` — the only file to edit. Currently contains the optimized B&B solver.
- `algorithmic/problems/1/chk.cc:61-91` — checker main logic. Reads input JSON, participant output JSON, baseline/best from .ans file. Computes score_ratio.
- `algorithmic/problems/1/chk.cc:77-78` — hard-coded constraints: max_mass=20000000, max_volume=25000000.
- `algorithmic/problems/1/chk.cc:38-58` — `read_output_json`: parses participant output. Expects exactly 12 keys, reads with `readToken()` then strips trailing comma.
- `algorithmic/judge/config/langs.yaml:2` — compilation command for C++17.
- `algorithmic/problems/1/testdata/{1..20}.in` — test inputs (JSON).
- `algorithmic/problems/1/testdata/{1..20}.ans` — two integers per file: baseline_value and best_value.

## Code Targets

### h-main (bnb-lagrangian)
- **File:** `solution.cpp`
- **What:** Replace stub with full B&B solver with Lagrangian LP bound, multiple greedy heuristics, and local search.
- **Why:** Exploits n=12 structure for exact optimization.

### h-control-negative (pure-greedy)
- **File:** `solution.cpp`
- **What:** Replace stub with simple greedy by v/(m+l) density, no B&B.
- **Why:** Baseline comparison to demonstrate B&B value.

## What I Tried That Didn't Work

1. **Naive B&B with min-of-two-1D LP bounds**: Timed out (5+ seconds on TC1). The bounds are too loose for 2D — they ignore the interaction between mass and volume constraints.

2. **Field name `ratio` in structs**: Causes compilation failure in Docker's GCC with `using namespace std` due to `std::ratio` name collision. Fixed by renaming to `dens`.

3. **Dual Lagrangian (relax both mass and volume separately)**: Too expensive per B&B node. Single Lagrangian (relax volume only) suffices — gives exact LP optimum by strong duality.

4. **Per-k tight bound computation**: Computing Lagrangian bound for every k value at each B&B level was too slow. Fixed with two-level strategy: tight bound at node level, cheap bound for per-k pruning.

## What I Excluded and Why

- **DP approaches**: 2D DP with scaling (mass × volume grid) requires either huge memory or coarse scaling that loses precision. With n=12, B&B is more natural and gives exact results.
- **Meet-in-the-middle**: Splitting 12 types into two groups of 6 — even with 6 types, enumeration over quantities (up to 500 each) gives 500^6 ≈ 10^16 combinations. Infeasible.
- **ILP solver libraries**: Not available in competitive programming context. Manual B&B is the appropriate approach.

## Evolution of Thinking

1. Started thinking this was straightforward B&B with 12 items — should be fast.
2. Discovered that quantities up to 10,000 (effective ~300) make the branching factor large.
3. Realized the 1D LP bounds are way too loose for 2D — 80% overestimate means no pruning.
4. Implemented Lagrangian relaxation for tight LP bound — this was the key insight that made B&B practical.
5. Discovered Docker compilation issue with `ratio` field name — subtle GCC namespace collision.
6. Optimized with two-level pruning (tight at node, cheap per-k) and reduced ternary iterations for speed.

## Current Status

- **Validated:** B&B solution scores 100 on all 20 test cases locally and 100 consistently on the Docker judge.
- **Uncertain:** Whether edge-case test inputs (e.g., all items with identical density) could cause B&B slowdown. Current solution handles all 20 test cases in <50ms.
- **Suggested next:** If score drops below 100 on new test data, investigate: (a) add time-based fallback using greedy+local search; (b) try alternative B&B orderings (smallest effective max_k first).

## Warnings & Constraints

1. **NEVER use `ratio` as a struct field name** with `using namespace std`. GCC in Docker interprets it as `std::ratio` template, causing compilation failure that doesn't reproduce locally with newer GCC versions.

2. **Docker timing is ~3-5x slower than bare metal.** A solution running 200ms locally may TLE at 1s in Docker. Keep solutions under 50ms locally for safety.

3. **JSON parser in chk.cc expects exactly 12 keys.** Output must have all 12 item keys, even if quantity is 0. Missing keys cause WA.

4. **The `readToken()` in chk.cc reads whitespace-delimited tokens.** Output values followed by commas are fine (comma is stripped). But values MUST be integers — no floats.
