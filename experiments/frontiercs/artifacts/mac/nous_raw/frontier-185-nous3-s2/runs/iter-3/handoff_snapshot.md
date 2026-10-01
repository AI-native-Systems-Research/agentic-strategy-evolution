# Handoff — iter-3 Maximum Clique (#185)

### Goal
Confirm the BnB-only solution (no DLS) achieves score 100 at full real-mode scope, and test timing robustness with a 1000ms budget.

### Key Discoveries
- **Score 100 confirmed 3 times**: iter-1 BnB+DLS=100, iter-2 BnB+DLS=100, iter-2 BnB-only=100, iter-3 probe BnB-only=100.
- **DLS is provably unnecessary** for this test set (RP-1, RP-3). BnB alone with degeneracy ordering solves all instances optimally.
- **Degeneracy ordering is critical**: BnB without it scored only 80 (iter-1). With it, BnB achieves 100.
- **Greedy alone scores 33.8** (iter-1 control). Far too weak.
- **The solution is already validated** — I ran the BnB-only code through the judge during exploration and got SCORE: 100.

### System Interface
- **Build:** No local build — judge compiles in Docker with g++ C++17.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` on stdout.
- **Baseline result:** BnB-only = 100 (just confirmed).

### Code Map
- `solution.cpp` — edit this file. Currently contains the BnB-only solution (degeneracy ordering, coloring bound, 1950ms budget).
- `runs/iter-2/patches/h-ablation.patch` — the BnB-only solution as a patch against stub. Equivalent to current solution.cpp.
- `runs/iter-1/patches/h-main.patch` — BnB+DLS hybrid (also scores 100 but unnecessarily complex).

### Code Targets
- **h-main** (`solution.cpp`): Use the current solution.cpp as-is (BnB-only with degeneracy ordering, 1950ms budget). It's already the correct code.
- **h-robustness** (`solution.cpp`): Same code but change `time_limit_ms = 1950` to `time_limit_ms = 1000`. Single line change.

### What I Tried That Didn't Work
- Iter-1: Basic BnB without degeneracy ordering scored only 80.
- Iter-1: Local compilation fails on macOS (`bits/stdc++.h` not found). Use judge only.
- Iter-1: Greedy by degree descending scored only 33.8.
- Iter-2: Predicted BnB-only would score 88-95 — it scored 100. The test set has no instances hard enough to time out BnB with degeneracy ordering.

### What I Excluded and Why
- **DLS tabu search**: Proven redundant by iter-2 ablation. Adds code complexity with zero scoring benefit.
- **Randomized restarts/SA/GA**: BnB alone achieves 100. No alternative metaheuristics needed.
- **Bron-Kerbosch**: Strictly inferior to MCQ-style BnB with coloring bound for max clique.
- **Parallel approaches**: Single-thread suffices within 2s for N ≤ 1000.

### Evolution of Thinking
Iter-1 found BnB+DLS=100 and estimated BnB-only at 88-90%. Iter-2 refuted that: BnB-only also scores 100. The estimate was based on BnB without degeneracy ordering (which scored 80). With degeneracy ordering, BnB is fast enough for all test instances. Iter-3 confirms this result at full scope and tests timing margin.

### Current Status
- **Validated:** BnB-only with degeneracy ordering = 100 (confirmed by 3 independent measurements across iters 2-3).
- **Uncertain:** Exact timing margin — does BnB finish well within 1000ms or does it need closer to 1950ms on hardest instances?
- **Suggested next:** Problem is solved (score 100). If further investigation desired, could explore minimum sufficient algorithm complexity (e.g., is per-vertex greedy warm-start needed, or does degree-only warm-start suffice?).

### Warnings & Constraints
- `bits/stdc++.h` doesn't compile on macOS. Only test via the judge script.
- Each judge call takes ~30-60s. Budget for 2 calls (h-main + h-robustness).
- The h-ablation.patch from iter-2 applies against the STUB (`int main(){return 0;}`), not the current solution.cpp. Current solution.cpp already contains the correct BnB-only code.
- Output must be exactly N lines, each "0" or "1".
