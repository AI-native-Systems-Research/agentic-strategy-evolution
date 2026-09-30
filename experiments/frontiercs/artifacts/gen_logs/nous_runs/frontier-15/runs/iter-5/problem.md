# Problem Framing — Iteration 5

## Research Question

What algorithm maximizes the Frontier-CS judge score for algorithmic problem #15?

The problem is to sort a permutation of [1..n] using prefix-suffix swap operations [A|B|C] → [C|B|A], minimizing the operation count. The judge scores as `100 * clamp((4n - ops)/(4n - (2n+1)), 0, 1)`, making score 100 the ceiling for any solution using ≤ 2n+1 operations.

Iterations 1–4 established the circular buffer rotation sort with BFS-optimal k=5 endgame as the definitive solution. This iteration confirms the result at full scope.

Key source files:
- `solution.cpp` — the solution file (currently the k=5 BFS endgame algorithm, 201 lines)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:64` — `best_operations = 2 * n + 1` (hardcoded benchmark)
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:78` — `ratio = std::max(0.0, std::min(1.0, your_value / best_value))` (score clamping)

## System Interface

- **Build command:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Measure command:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp`
- **CLI semantics:** The measure script compiles solution.cpp, runs it on all 10 test cases (each n=1000), checks correctness via `chk.cc`, and prints `SCORE: <n>` (0–100, continuous).
- **Code evidence:**
  - `chk.cc:64` — `int best_operations = 2 * n + 1;` defines the scoring denominator
  - `chk.cc:78` — `ratio = std::max(0.0, std::min(1.0, your_value / best_value));` clamps score to [0, 100]
  - `chk.cc:57` — `check_sorted(p_contestant)` validates the output is correctly sorted
- **Output:** Single line `SCORE: <n>` to stdout.

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp
```

## Baseline Validation

Ran the k=5 BFS-optimal endgame solution (already in `solution.cpp`):
- **Exit code:** 0
- **Score:** 100
- **Per-case operation counts:** 1987, 1987, 1983, 1987, 1990, 1984, 1982, 1990, 1987, 1983
- **Average:** 1986.0, **Max:** 1990, **Min:** 1982
- All well under the 2001 threshold for score 100

## Experimental Conditions

### h-main: Confirm k=5 BFS-optimal endgame (no code change)

The solution is already the k=5 BFS-optimal algorithm from iter-4. No modification needed.

Command:
```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp
```

Expected: SCORE: 100, with per-case ops matching iter-4 observations (deterministic algorithm on fixed test data).

## Success Criteria

- Score = 100 (the mathematical ceiling, per RP-4)
- Per-case operations all ≤ 1995 (the 2n-5 worst-case bound, per RP-1)
- Results match iter-4 exactly (deterministic algorithm, same test inputs)

## Constraints

- Judge measurement takes 30–60 seconds; one call per arm
- Score cannot exceed 100 (checker clamps at 1.0)
- All 10 test cases have n=1000
- The solution must handle edge cases n ≤ 5 via fallback (not exercised by test data)

## Prior Knowledge

Five established principles apply:
- **RP-1** (high): Circular buffer rotation sort achieves ≤ 2n-5 operations for n ≥ 7
- **RP-2** (high, algebraic): d=1 decomposition d1=2, d2=l-1 resolves the modular edge case
- **RP-3** (high): Op2 (prefix restoration) is essential — ablation produces score 0
- **RP-4** (high, algebraic): Score ceiling is 100 for any solution with ≤ 2n+1 ops
- **RP-5** (high): BFS reference n must be ≥ 2k+1 to avoid small/large operation overlap

No principles have been refuted. No brief_amendments.md from prior iterations.
