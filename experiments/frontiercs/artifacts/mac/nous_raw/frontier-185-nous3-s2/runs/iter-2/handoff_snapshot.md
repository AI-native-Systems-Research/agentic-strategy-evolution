# Handoff — iter-2 Maximum Clique (#185)

### Goal
Test whether the DLS tabu search fallback is necessary for score 100 by running the full BnB+DLS hybrid (h-main) and a BnB-only ablation (h-ablation). Record judge scores for both.

### Key Discoveries
- **Score 100 proven in iter-1** with BnB+DLS hybrid. The full solution is in `runs/iter-1/patches/h-main.patch`.
- **BnB alone was estimated at 88-90%** per iter-1 handoff. The ablation tests this precisely.
- **DLS fallback activates only when BnB times out** at 1600ms. For easy instances, BnB finishes well under budget and DLS never runs.
- **Greedy-only scores 33.8** (iter-1 control). No need to re-test.
- `bits/stdc++.h` works in the judge Docker environment. Don't compile locally.

### System Interface
- **Build:** No local build — judge compiles in Docker with g++ C++17.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` on stdout.
- **Baseline result:** iter-1 h-main = 100, iter-1 greedy = 33.8.

### Code Map
- `solution.cpp` — edit this file. Currently contains a simpler BnB (no degeneracy ordering, no DLS).
- `runs/iter-1/patches/h-main.patch` — full BnB+DLS solution that scored 100. Apply from stub (`int main(){return 0;}`), NOT from current `solution.cpp`.
- `fmeasure_185.sh` — judge invocation script. Takes path to solution.cpp as argument.

### Code Targets
- **h-main** (`solution.cpp`): Replace entire file with the BnB+DLS hybrid from iter-1 h-main.patch. Key components: degeneracy ordering (lines 178–191 of patch), greedy warm-starts (197–238), BnB with bitset coloring (22–76), DLS tabu search (86–162), main orchestration (164–263).
- **h-ablation** (`solution.cpp`): Same as h-main but delete the `local_search` function (lines 86–162 of patch) and the `if (timed_out) local_search(1950)` block (lines 256–258). Change `time_limit_ms = 1600` to `time_limit_ms = 1950` to give BnB the full budget.

### What I Tried That Didn't Work
- Iter-1: Basic BnB without degeneracy ordering scored only 80.
- Iter-1: Local compilation fails on macOS (`bits/stdc++.h` not found). Use judge only.
- Iter-1: Greedy by degree descending scored only 33.8.

### What I Excluded and Why
- Randomized restarts/SA/GA: BnB+DLS already achieves 100. No need for alternative metaheuristics.
- Bron-Kerbosch: Superseded by MCQ-style BnB with coloring bound which is strictly better for max clique.
- Parallel approaches: Single-thread suffices within 2s for N ≤ 1000.

### Evolution of Thinking
Iter-1 established BnB+DLS as the winning approach. Iter-2 asks whether both components are needed or if BnB alone (with enough time) would suffice. RP-1 claims BnB plateaus at 88-90% on hard dense instances — this ablation tests that claim precisely.

### Current Status
- **Validated:** BnB+DLS = 100 (iter-1). Greedy = 33.8 (iter-1).
- **Uncertain:** Exact score of BnB-only with full 1950ms budget (estimated 88-95 per RP-1).
- **Suggested next:** If ablation confirms DLS is critical, explore DLS parameter sensitivity (tenure, restart threshold). If ablation also scores 100, the DLS component is redundant for this test set.

### Warnings & Constraints
- The h-main.patch applies against the STUB (`int main(){return 0;}`), not the current solution.cpp. Reset solution.cpp to stub before applying, or just overwrite the file directly.
- Each judge call takes ~30-60s. Budget for 2 calls total.
- Output must be exactly N lines, each "0" or "1".
