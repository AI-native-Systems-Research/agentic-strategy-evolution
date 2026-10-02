# Problem Framing — Maximum Clique (Problem #185)

## Research Question

What algorithm maximizes the Frontier-CS judge score for problem #185 (Maximum Clique)?
The problem asks to find the largest clique in an undirected graph with N ≤ 1000, M ≤ 500,000, under a 2-second time limit. Score = (K/K*) × 100 where K is the found clique size and K* is optimal.

Key file: `solution.cpp` — the single C++17 source file to edit.

## System Interface

- **Build:** Handled by the judge script (compiles C++17 internally).
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0-100.
- **Code evidence:** `solution.cpp:1` — the entire solution is a single file.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp
```

## Baseline Validation

- Exit code: 0
- Output: `SCORE: 99.345` (consistent across 3 runs)
- The baseline uses a degeneracy-ordered branch-and-bound with greedy coloring bounds and bitset-accelerated candidate intersection.

## Experimental Conditions

### h-main: BnB with degeneracy ordering + bitset intersection
The primary approach: branch-and-bound using greedy coloring upper bound, degeneracy vertex ordering, and bitset<1001> for fast candidate set intersection. Greedy restarts (500 random orderings) provide a strong initial lower bound.

Key algorithmic components:
1. Greedy initialization with 500 random restarts
2. Degeneracy ordering (min-degree removal) for BnB processing order
3. Greedy sequential coloring for upper bound at each BnB node
4. Bitset intersection (`adj[v] & sub`) for candidate generation
5. 1850ms time cutoff to stay within 2s judge limit

### h-control-negative: Greedy-only (no BnB)
Remove the BnB phase entirely; rely only on greedy restarts. This tests whether the BnB component is necessary for high scores.

## Success Criteria

- h-main: score ≥ 95 (near-optimal on most test cases)
- h-control-negative: score significantly lower than h-main (demonstrating BnB value)

## Constraints

- Time limit: 2.0s per test case
- Memory: 512MB
- N ≤ 1000, M ≤ 500,000
- Output: exactly N lines, each 0 or 1

## Prior Knowledge

First iteration — no prior principles.
