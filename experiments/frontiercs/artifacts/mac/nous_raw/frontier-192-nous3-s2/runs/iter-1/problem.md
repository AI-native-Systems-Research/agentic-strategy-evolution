# Problem Framing — Max-Cut (Problem #192)

## Research Question

What algorithm maximizes the Frontier-CS judge score for Max-Cut (problem #192)? The problem requires partitioning n≤1000 vertices into two sets to maximize the fraction of edges crossing the partition. Score = cut_edges / total_edges × 100.

The key source file is `solution.cpp` — the only controllable knob.

## System Interface

- **Build:** The judge compiles and runs `solution.cpp` internally via `frontier eval algorithmic 192`.
- **Measure command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` where n is 0–100 (higher is better).
- **Code evidence:** `fmeasure_192.sh` invokes `frontier eval algorithmic 192 <solution.cpp> --json`, then extracts the `"score"` field.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_192.sh $PWD/solution.cpp
```

Where `solution.cpp` contains a random assignment (each vertex assigned 0 or 1 uniformly at random).

## Baseline Validation

- Random assignment baseline: **SCORE: 51.00** (exit code 0).
- Greedy local search (50 restarts): **SCORE: 79.81**.
- SA v5 (30 restarts, alpha=0.9999): **SCORE: 86.95**.
- SA v8 (greedy init + SA + re-greedy, 20 restarts): **SCORE: 87.28**.

All validated via the fmeasure script.

## Experimental Conditions

### Arm: h-main — Multi-start SA with greedy init

Replace `solution.cpp` with an implementation of:
1. **Greedy construction** (5 of 20 restarts): assign vertices in random order, each to the side that maximizes current cut edges.
2. **Random construction** (15 of 20 restarts): assign each vertex 0 or 1 uniformly.
3. **Greedy local search**: repeatedly flip any vertex that improves cut, until no single-vertex flip improves.
4. **Simulated annealing**: from the local optimum, run SA with T_start=3.0, T_min=0.001, alpha=0.99997. Accept improving moves always; accept worsening moves with probability exp(delta/T).
5. **Re-greedy**: after SA, run greedy local search again from the SA best.
6. **Multi-start**: repeat 20 times, keep the global best.

This is the `sa_v8_solution.cpp` approach validated above at SCORE 87.28.

## Success Criteria

- h-main scores ≥ 85 (substantially above the ~51 random baseline).
- This demonstrates that SA-based local search is an effective heuristic for Max-Cut on graphs of this size.

## Constraints

- Time limit per test case: unknown exact value, but solutions must complete within it. Fixed iteration counts (no chrono/clock-based timing, which caused score=0 in testing).
- n ≤ 1000, m ≤ 20000.
- Output format: exactly one line of n space-separated 0/1 values.

## Prior Knowledge

First iteration — no prior principles. Max-Cut is NP-hard; the Goemans-Williamson SDP relaxation gives a 0.878-approximation guarantee. Our SA approach empirically achieves ~87% which is consistent with near-GW performance.
