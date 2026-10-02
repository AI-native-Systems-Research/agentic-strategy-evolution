# Problem Framing — iter-2 Maximum Clique (#185)

## Research Question
Iter-1 achieved score 100 with a hybrid BnB+DLS approach. Is the DLS tabu search fallback necessary, or does the BnB component alone (with degeneracy ordering + greedy coloring bound) achieve score 100? This tests whether the DLS component is the critical factor for hard dense instances or whether BnB alone suffices when given the full 2s time budget.

Relevant source: iter-1 patch `h-main.patch` lines 86–162 implement the DLS fallback; lines 22–76 implement the BnB core.

## System Interface
- **Build:** No local build needed — judge compiles inside Docker with g++ C++17.
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output:** Single line `SCORE: <n>` on stdout (0–100 continuous).
- **Code evidence:** `fmeasure_185.sh` calls `frontier eval algorithmic 185 "$1" --json`.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp
```
With `solution.cpp` containing the full BnB+DLS hybrid from iter-1.

## Baseline Validation
Iter-1 h-main scored 100. The current worktree `solution.cpp` contains a simpler BnB variant (no degeneracy ordering, no DLS). The proven solution is in `runs/iter-1/patches/h-main.patch`.

## Experimental Conditions

### h-main: Full BnB+DLS hybrid (proven approach)
Apply the iter-1 h-main.patch to solution.cpp. This includes degeneracy ordering, bitset greedy coloring bound, greedy warm-starts, and DLS tabu fallback when BnB times out. Expected: score 100 (confirming reproducibility).

### h-ablation: BnB-only (no DLS fallback)
Same as h-main but remove the DLS local_search function and the `if (timed_out) local_search(1950)` call. Give BnB the full 1950ms instead of 1600ms. Tests whether the DLS component is necessary.

## Success Criteria
- h-main: score 100 (reproduces iter-1).
- h-ablation: if score < 100, DLS is confirmed necessary for hard instances. If score == 100, DLS is redundant for this problem set.

## Constraints
- 2s time limit per test case.
- N ≤ 1000, M ≤ 500,000.
- Output exactly N lines, each "0" or "1".
- Judge calls take ~30-60s each.

## Prior Knowledge
- RP-1: BnB+DLS hybrid achieves score 100; pure BnB plateaus at 88-90% on hard dense instances.
- RP-2: Greedy-only scores ~34%.
- Iter-1 established the BnB+DLS approach works. This iteration tests whether the DLS component is the critical differentiator.
