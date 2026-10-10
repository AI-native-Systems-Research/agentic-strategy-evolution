# Problem Framing — Hamiltonian Path Challenge (Problem #5)

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #5 (directed Hamiltonian Path)?

The problem asks us to find the longest simple path in a directed graph where a Hamiltonian path is guaranteed to exist. Scoring is via 10 thresholds per test case (10 test cases, 100 points max). The key files are:
- `solution.cpp` — the algorithm we edit (C++17 stub)
- `algorithmic/problems/5/chk.cc:48-55` — the judge scoring logic: score = count of a_i where k ≥ a_i; pnt/10 ratio when pnt < 10

## System Interface

- **Build command:** `g++ -O2 -o sol solution.cpp` (validated)
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp`
  - This compiles, runs on all 10 test cases, and prints `SCORE: <n>` (0–100)
  - Code evidence: `/home/ubuntu/frontier/gen_logs/fmeasure_5.sh:5` — calls `frontier eval algorithmic 5`
- **Output format:** Single line `SCORE: <n>` on stdout; n is the judge score (continuous 0–100)
- **Time limit per test case:** 4 seconds; Memory limit: 512 MB

### Test Case Characteristics (from exploration)

| Test | n       | m       | avg_deg | Threshold 1 | Threshold 10 |
|------|---------|---------|---------|-------------|-------------|
| 1    | 5       | 7       | 1.4     | 4           | 5           |
| 2    | 20      | 124     | 6.2     | 10          | 20          |
| 3    | 60      | 359     | 6.0     | 20          | 60          |
| 4    | 500     | 3,499   | 7.0     | 123         | 500         |
| 5    | 1,000   | 6,999   | 7.0     | 233         | 1,000       |
| 6    | 2,000   | 11,999  | 6.0     | 444         | 2,000       |
| 7    | 4,000   | 23,999  | 6.0     | 817         | 4,000       |
| 8    | 9,000   | 48,999  | 5.4     | 1,926       | 9,000       |
| 9    | 8,000   | 107,999 | 13.5    | 1,926       | 8,000       |
| 10   | 100,000 | 299,999 | 3.0     | 23,333      | 100,000     |

All test cases have full Hamiltonian paths as the answer (verified from `.ans` files).

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_5.sh $PWD/solution.cpp
```

## Baseline Validation

- **Stub solution** (`return 0`): `SCORE: 0` (empty output)
- **Naive greedy** (random neighbor, forward-only): `SCORE: 3`
- **Warnsdorff greedy + insertion** (v1, no rotations): `SCORE: 41`
- **Warnsdorff greedy + Pósa rotations** (v6, O(1) linked list): `SCORE: 72`
- **Reference solutions**: gemini3pro.cpp=33, gpt5.cpp=25

## Experimental Conditions

### h-main: Warnsdorff Greedy + Directed Pósa Rotations (O(1) linked list)

Write `solution.cpp` implementing:
1. **Dynamic Warnsdorff heuristic**: Track remaining out-degree as vertices are visited; prefer vertices with lowest remaining out-degree (breaks ties randomly)
2. **Bidirectional extension**: Extend path forward from tail AND backward from head using reverse adjacency
3. **Insertion passes**: For each consecutive pair (u, w) in path, insert unused vertex v if u→v and v→w edges exist
4. **Directed Pósa rotations** (the key innovation):
   - When tail is stuck (no unvisited out-neighbor), find shortcut edge tail→v_i to interior path vertex
   - **Cycle case** (v_i == head): Tail→head forms cycle. Walk cycle to find v_j with unvisited out-neighbor. Break cycle: new path is nxt[v_j]→...→tail→head→...→v_j. New tail is v_j.
   - **General case** (v_i != head): Need edge prv[v_i]→nxt[v_j] for break point v_j between v_i and tail. Restructure: prefix→prv[v_i]→nxt[v_j]→...→tail→v_i→...→v_j. New tail is v_j.
   - After rotation, extend from new tail (and try backward from head)
   - All rotations use O(1) pointer surgery on a doubly-linked list (nxt/prv arrays)
5. **Smart start selection**: Try in-degree-0 vertices first, then low in-degree, then high out-minus-in-degree
6. **Multiple random restarts** within 3.6-second budget, keeping best path
7. **Post-processing**: Final insertion + prepend/append passes

### h-control-negative: Warnsdorff Greedy WITHOUT Rotations

Write `solution.cpp` implementing:
1. Same Warnsdorff greedy + bidirectional extension + insertion passes
2. Same smart starts + random restarts
3. **NO Pósa rotations** — when stuck, just move to next restart
4. Same post-processing

This validates that the Pósa rotation is the key algorithmic improvement.

## Success Criteria

- **h-main** achieves a score strictly higher than **h-control-negative**
- **h-main** achieves a score ≥ 50 (demonstrating substantial improvement over reference solutions at 25-33)

## Constraints

- 4-second time limit per test case, 512 MB memory
- Solution must be valid C++17
- No external libraries
- Each arm gets one judge call (~60s)

## Prior Knowledge

This is the first iteration. No active principles. Key findings from exploration:

1. **Pósa rotations are transformative**: Score jumped from 41 (greedy+insertion) to 72 (greedy+rotation) — a 76% improvement. The rotations let the algorithm escape dead ends by restructuring the path to create new extension points.

2. **O(1) pointer surgery is critical**: The vector-based v5 scored 52 while the linked-list v6 scored 72. The O(1) rotations allow many more rotation attempts within the time budget.

3. **Score is seed-dependent**: Seed 42 gives 72, seed 123 gives 54. The algorithm's randomized choices during rotation target selection significantly affect outcomes.

4. **Backward rotations hurt performance**: Adding backward (head-end) Pósa rotations consistently degraded the score (from 72 to 64-65). This might be due to bugs in the backward pointer surgery or simply because head-end rotations are less effective for this problem structure.

5. **DFS with bounded backtracking is worse**: For n≤2000, DFS with backtracking scored only 33, much worse than the greedy+rotation approach (72).
