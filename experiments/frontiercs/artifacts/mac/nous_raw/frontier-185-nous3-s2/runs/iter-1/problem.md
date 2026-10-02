# Problem Framing — Maximum Clique (Problem #185)

## Research Question

What algorithm maximizes the judge score for the Maximum Clique problem (N≤1000, M≤500000, 2s time limit)? The key file is `solution.cpp` in the worktree.

## System Interface

- **Build:** Compilation happens inside the judge's Docker container (Linux, g++, C++17). `bits/stdc++.h` is available.
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0–100 (continuous). Score = (K/K*)*100 where K is found clique size and K* is optimal.
- **Code evidence:** `fmeasure_185.sh:5` — calls `frontier eval algorithmic 185 "$1" --json`. The judge server runs in Docker (`algorithmic_local.py:89`).

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp
```

## Baseline Validation

- **Greedy-only (degree-sorted):** SCORE: 33.76 — exits 0, produces valid output.
- **Basic BnB (v1, no degeneracy ordering):** SCORE: 80 — some test cases time out or aren't pruned enough.
- **Improved BnB (degeneracy ordering + color bound, MCQ-style):** SCORE: 100 — optimal cliques found within 2s.

## Experimental Conditions

### h-main: Branch-and-Bound with degeneracy ordering and greedy coloring bound
Replace the stub `solution.cpp` with a full MCQ-style maximum clique solver:
- Bitset adjacency for O(N/64) neighbor intersection
- Degeneracy ordering to process high-core vertices first
- Greedy coloring upper bound for pruning
- Color-class ordering so highest-color (hardest to prune) vertices are tried last
- Greedy initial clique as warm start

### h-control-negative: Greedy-only approach (no search)
Replace `solution.cpp` with a simple greedy clique builder (sort by degree, greedily add compatible vertices). Expected to score much lower since it doesn't search.

## Success Criteria

- h-main achieves score ≥ 90 (ideally 100), demonstrating exact or near-exact max clique finding within the time limit.
- h-control-negative scores significantly lower, confirming that exhaustive search with pruning is necessary.

## Constraints

- Time limit: 2.0s per test case
- Memory limit: 512MB
- N ≤ 1000, M ≤ 500,000
- Output format: exactly N lines, each 0 or 1

## Prior Knowledge

First iteration — no prior principles.
