# Problem Framing — Max-Cut (Problem 192)

## Research Question

What algorithm maximizes the Frontier-CS judge score for Max-Cut (problem #192)?
The mechanism under study is Fiduccia-Mattheyses (FM) partitioning with random restarts, compared against simple greedy local search.
Key file: `solution.cpp` in the worktree root.

## System Interface

- **Build command:** Handled internally by `frontier eval` (compiles C++17 with g++).
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` where n is 0–100 (continuous partial credit). The score equals `100 * (cut_edges / total_edges)` averaged across 30 test cases.
- **Code evidence:** Problem config at `algorithmic/problems/192/config.yaml:2` — time limit is **1 second**, memory 1024 MB.
- **Checker:** `algorithmic/problems/192/chk.cc` (testlib-based, computes c/m ratio).

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp
```

Where `solution.cpp` contains the greedy local search (random init + flip positive-gain vertices until convergence, with restarts under 0.85s time budget).

## Baseline Validation

- **Greedy local search:** SCORE: 84.3 (exit 0)
- **Trivial alternating (i%2):** SCORE: 49.4 (exit 0)
- **FM + greedy local search:** SCORE: 87.2 (exit 0)
- **Simulated annealing + greedy:** SCORE: 84.1 (exit 0)
- **Reference gpt5_high.cpp (FM-only):** SCORE: 83.8

## Experimental Conditions

### h-main: FM partitioning with greedy local search and restarts
Replace `solution.cpp` with an implementation that:
1. Randomly initializes partition
2. Runs greedy local search (flip any vertex with positive gain) to reach local optimum
3. Applies FM passes (Fiduccia-Mattheyses: try all vertices in gain-priority order, find best prefix of flips) to escape local optima
4. Repeats with new random starts within 0.90s time budget
5. Outputs best partition found

### h-control-negative: Trivial alternating assignment
Replace `solution.cpp` with `s[i] = i % 2` — no optimization at all. Expected to score ~49.

## Success Criteria

- h-main achieves score > 85 (already observed 87.2 in probe).
- h-main score exceeds h-control-negative by a large margin (>30 points).

## Constraints

- Per-test time limit: 1 second. All solutions must complete within this.
- Memory limit: 1024 MB.
- Output format: exactly n space-separated integers on one line, each 0 or 1.

## Prior Knowledge

First iteration — no active principles.
