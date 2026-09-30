# Problem Framing — Iteration 1

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #1 (Treasure Packing)?

The problem is a **2-dimensional bounded knapsack**: 12 item types, each with quantity limit q (up to 10,000), value v, mass m (constraint: total ≤ 20,000,000 mg), and volume l (constraint: total ≤ 25,000,000 µL). The goal is to maximize total value.

Key source files:
- `solution.cpp` — the C++17 solution file we edit
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/1/chk.cc` — the checker that scores solutions
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/1/testdata/` — 20 test cases (.in/.ans pairs)

## System Interface

- **Build command:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
  - Docker compilation flags from `algorithmic/judge/config/langs.yaml:2`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
  - Prints `SCORE: <n>` where n is 0-100 (average across 20 test cases)
- **Code evidence:**
  - Checker scoring: `chk.cc:86` — `score_ratio = max(0.0, min(1.0, (double)(participant_value - baseline_value) / (best_value - baseline_value)));`
  - Constraints: `chk.cc:77-78` — `max_mass = 20000000`, `max_volume = 25000000`
  - 12 items: `chk.cc:25` — `for (int i = 0; i < 12; ++i)` in input parser
- **Output format:** JSON to stdout with same keys as input, integer quantities per item type

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp
```

## Baseline Validation

With the stub solution (`int main(){return 0;}`): SCORE: 0 (no output produced).

With the optimized branch-and-bound solution: SCORE: 100 (consistently across 3 runs).

Per-case validation: all 20 test cases achieve gap=0 (exactly matching the "best" reference value), with mass and volume within constraints.

## Experimental Conditions

### h-main: Branch-and-Bound with Lagrangian LP Relaxation

Replace `solution.cpp` with an algorithm that combines:
1. **Multiple greedy heuristics** (21 variants using different density metrics v/(αm + (1-α)l) for α ∈ {0, 0.05, ..., 1.0}) to establish a strong initial lower bound
2. **Local search** (add/swap/remove-and-refill moves) to improve the greedy solution
3. **Branch-and-bound** with:
   - Items sorted by combined density v/(m+l) descending for good branching order
   - Tight LP upper bound via Lagrangian relaxation (relax volume constraint, ternary search for optimal dual variable)
   - Cheap upper bound (min of two 1D fractional knapsack relaxations) for per-k pruning
   - Effective max_k reduction: min(q, M/m, V/l) per item

The key insight: with only 12 item types, the B&B tree has depth 12. High-density items are decided first, leaving low-density items for the bottom of the tree where capacity is tight and pruning is aggressive. The Lagrangian LP bound equals the LP optimum (by strong duality), providing near-tight bounds at every node.

### h-control-negative: Pure Greedy

A single greedy heuristic (sort by v/(m+l), fill greedily) without branch-and-bound or local search. Expected to score significantly lower, demonstrating that the B&B optimization matters.

## Success Criteria

- **h-main:** Judge score ≥ 95 (ideally 100)
- **h-control-negative:** Judge score measurably lower than h-main, demonstrating the value of B&B

## Constraints

- 1 second time limit per test case
- 1024 MB memory limit
- Must compile with `g++ -O2 -pipe -static -s -std=gnu++17`
- Avoid `std::ratio` name collision when using `using namespace std`

## Prior Knowledge

This is the first iteration. No prior principles.
