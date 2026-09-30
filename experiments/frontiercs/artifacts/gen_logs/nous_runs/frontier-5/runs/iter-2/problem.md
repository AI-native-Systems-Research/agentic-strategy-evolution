# Problem Framing — Iteration 2: Frontier-CS Problem 5 (Hamiltonian Path)

## Research Question

How can we improve the Hamiltonian path solver beyond the greedy+Pósa rotation approach (score 72) by adding structure-aware graph decomposition for DAG-like graphs?

Iteration 1 established that Warnsdorff greedy + directed Pósa rotations achieve a score of 72/100, with full Hamiltonian paths (10/10) on 7 of 10 tests but poor coverage on 3 structurally hard tests:
- **Test 4** (n=500, m=3499, avg_deg=7): k=223/500 → 1/10 points. **366 SCCs** — a DAG-like structure with max SCC size 9.
- **Test 8** (n=9000, m=49K, avg_deg=5.44): k=3309/9000 → 1/10 points. Single SCC.
- **Test 10** (n=100K, m=300K, avg_deg=3): k=4966/100K → 0/10 points. Single SCC.

Key insight from exploration: **Test 4's graph is a DAG of 366 small SCCs** (max size 9). The rotation-based approach fails here because it treats the graph as monolithic, while the actual structure requires traversing a condensation DAG in topological order with bitmask DP within each SCC.

Relevant source files:
- `algorithmic/problems/5/chk.cc:48-55` — Scoring: score = count of a_i ≤ k, ratio pnt/10
- `solution_iter2c.cpp` — The validated improved algorithm
- `solution_v6.cpp` — The iter-1 baseline (score 72)

## System Interface

- **Build command:** `g++ -O2 -o sol solution.cpp`
- **Run/measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` where n is 0–100
- **Code evidence:** 
  - `chk.cc:49-50` — `for(int i=1;i<=10;i++) if(len>=jud[i]) pnt=i;`
  - `chk.cc:56` — `quitp(1.0*pnt/10,partial,len,1.0*pnt/10);`

## Baseline Command

```bash
# Copy v6 (iter-1 best) to solution.cpp, then:
bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp
```

## Baseline Validation

v6 (Warnsdorff + Pósa rotation) scores SCORE: 72 consistently across 5 runs. Per-test:
- Tests 1-3, 5-7, 9: 10/10 (full Hamiltonian path)
- Test 4: 1/10 (k=223/500)
- Test 8: 1/10 (k=3309/9000)
- Test 10: 0/10 (k≈5000/100K)

## Experimental Conditions

### h-main: SCC-aware Construction + Improved Rotation
- Add SCC decomposition (iterative Kosaraju) for graphs with n ≤ 2000
- When num_sccs > 10 (DAG-like): find HP in condensation DAG via DFS with backtracking, then bitmask DP within each SCC (max size 20)
- For all graphs: run v6-style Warnsdorff+Pósa rotation with multi-seed (primary seed 42 with 3.0s budget, then additional seeds in remaining time)
- File: `solution_iter2c.cpp` (validated, SCORE: 81 across 5 runs)

### h-control-negative: Pure Rotation (No SCC)
- The v6 algorithm: Warnsdorff greedy + directed Pósa rotation, single seed (42)
- File: `solution_v6.cpp` (validated, SCORE: 72)

## Success Criteria

- h-main scores strictly higher than h-control-negative
- The improvement is attributable to test 4 (SCC-aware construction) gaining ≥9 points
- No regression on tests previously scoring 10/10

## Constraints

- Time limit: 4 seconds per test case
- Memory limit: 512 MB
- Output: valid directed path with no repeated vertices
- Solution must be a single C++17 file

## Prior Knowledge

- **RP-1:** Directed Pósa rotations improve score by 76% over greedy alone (72 vs 41). Confirmed in iter-1.
- **RP-2:** Pósa rotation has a sharp effectiveness boundary — 100% coverage on 7/10 tests but 5-50% on 3 structurally hard tests. Confirmed in iter-1.
- **RP-3:** On structurally hard graphs, greedy sometimes outperforms rotation on raw path length. Medium confidence.

The h-main arm targets the structural gap identified by RP-2: test 4's failure is not a rotation limitation but a graph-structure mismatch (DAG vs SCC). The SCC-aware approach addresses this directly.
