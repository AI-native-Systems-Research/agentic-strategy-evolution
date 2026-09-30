# Problem Framing — Iteration 2

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #1 (2D bounded knapsack with 12 item types)?

Iteration 1 established that branch-and-bound with Lagrangian LP relaxation achieves exact optima (score 100/100) on all 20 test cases (`solution.cpp`). However, empirical measurement reveals **Docker timing variability** causes intermittent TLEs, producing score drops to 85–95 on some judge invocations. Iteration 2 investigates whether **optimizing the B&B constant factor** and adding a **time guard** can eliminate these drops, and ablates the B&B to measure the isolated contribution of greedy+local-search.

Key source files:
- `solution.cpp` — the single editable file containing the solver.
- `algorithmic/problems/1/chk.cc:61-91` — checker scoring logic.
- `algorithmic/judge/config/langs.yaml:2` — compilation flags for C++17.

## System Interface

- **Build command:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
- **Output:** Single line `SCORE: <n>` where n is 0–100 (continuous partial credit).
- **Code evidence:**
  - `algorithmic/judge/config/langs.yaml:2` — compilation flags (`-O2 -pipe -static -s -std=gnu++17`).
  - `algorithmic/problems/1/chk.cc:77-78` — constraint constants: `max_mass=20000000`, `max_volume=25000000`.
  - `algorithmic/problems/1/chk.cc:88` — scoring formula: `100 * clamp((participant - baseline) / (best - baseline), 0, 1)`.

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp
```

## Baseline Validation

The current iter-1 solution (B&B with Lagrangian LP relaxation) was run 5 times on the Docker judge:
- Scores: 100, 95, 100, 90, 100
- **The variability confirms Docker timing causes intermittent TLEs.** The solution finds exact optima on all 20 test cases locally (gap=0 for every case), but Docker's 3–5× slowdown occasionally pushes the slowest cases past the 1-second limit.
- Local per-case timing: TC1=30ms, TC14=19ms, all others 2–5ms.

## Experimental Conditions

### h-main: Optimized B&B with timing guard

Changes from baseline (current iter-1 solution):
1. **Reduce ternary search iterations from 20 to 12.** Validated: TC1 drops from 30ms→21ms (30% faster), TC14 from 19ms→12ms (37% faster). Precision (1/3)^12 ≈ 2×10⁻⁶ is far beyond needed for integer LP bound. All 20 test cases still produce exact optima (gap=0).
2. **Add clock()-based time guard.** If B&B wall time exceeds ~800ms, stop recursion and use the best solution found so far (greedy+LS result is always available as fallback). This ensures we never TLE.
3. **Keep all other components**: multiple greedy heuristics (23 variants), local search (add/swap/remove-refill), density-sorted B&B ordering.

### h-ablation: Multi-greedy + local search only (no B&B)

Changes from baseline: disable the B&B call entirely (`solve(0, MAX_MASS, MAX_VOL, 0)` → commented out). Keep all greedy heuristics and local search.

Validated locally: achieves optimal on 9/20 test cases (gap=0), suboptimal on 11/20 with individual case scores ranging from 43.9 to 100.0. Average case score ≈ 85.6.

## Success Criteria

- **h-main**: Judge score ≥ 95 on every invocation (eliminates TLE-induced drops). Target: reliable 100.
- **h-ablation**: Judge score measurably lower than h-main, confirming B&B is necessary for consistent optimality.

## Constraints

- 1-second time limit per test case in Docker.
- 1024 MB memory limit.
- Must output valid JSON with exactly 12 keys (all item types, even if count is 0).
- Do NOT use `ratio` as a field/variable name with `using namespace std` (GCC namespace collision in Docker).

## Prior Knowledge

- **RP-1 (high confidence):** B&B with Lagrangian LP relaxation finds exact optima, scoring 100/100 on all 20 test cases.
- **RP-2 (high confidence):** Single greedy by v/(m+l) scores 0/100 — fails to beat the NSA baseline.
- **Iter-1 handoff:** Docker timing is 3–5× slower than bare metal. Solution must run <50ms locally for reliable 1s Docker limit. The `ratio` field name causes compilation failure in Docker's GCC.
