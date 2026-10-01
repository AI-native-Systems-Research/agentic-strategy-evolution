# Problem Framing — Frontier-CS #22

## Research Question

What algorithm maximizes the judge score for problem #22, which asks for a tree decomposition (bag size ≤ 4, K ≤ 4N bags) of a tree augmented with a cycle on its leaves (outer ring road)?

The key source file is `solution.cpp` in the working directory. The checker is at `algorithmic/problems/22/checker.cpp`.

## System Interface

- **Build:** Compilation handled by the judge inside Docker.
- **Measure:** `bash /Users/toslali/frontier/gen_logs/fmeasure_22.sh $PWD/solution.cpp`
- **Output:** Single line `SCORE: <n>` where n is 0–100.
- **Code evidence:** Checker at `algorithmic/problems/22/checker.cpp:120` computes `ratio = max(0.0, min(1.0, 1.0 * (5*N - K) / 2 * N))`. Due to operator precedence this evaluates to `(5N-K)*N/2`, meaning any valid solution with K < 5N gets ratio clamped to 1.0 (full score). The real challenge is producing a **correct** tree decomposition.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_22.sh $PWD/solution.cpp
```

## Baseline Validation

Ran the baseline with a tree decomposition solution. Exit code 0, output: `SCORE: 100`.

## Experimental Conditions

### h-main: Tree Decomposition via L/R leaf tracking

**Strategy:** For each node u, track L[u] (leftmost leaf in subtree) and R[u] (rightmost leaf). Build bags:
- H_i = {u, c_i, L[c_i], R[c_i]} — covers tree edge (u, c_i)
- S_i = {u, R[u], L[c_i], R[c_i]} — spine maintaining u and R[u] connectivity
- Lnk_i = {u, R[u], R[c_i], L[c_{i+1}]} — covers ring edge between consecutive subtree boundaries

The wraparound ring edge (R[root], L[root]) is covered by S[0] at root since L[c_1] = L[root].

**Result:** Score 100.

## Success Criteria

Score = 100 (full marks). Already achieved.

## Constraints

- K ≤ 4N (problem statement), bag size ≤ 4
- Time limit 2 seconds, memory 1024 MiB
- N up to 100,000

## Prior Knowledge

First iteration — no prior principles.
