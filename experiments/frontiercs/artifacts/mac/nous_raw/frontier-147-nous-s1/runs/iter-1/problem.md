# Problem Framing — Iter 1

## Research Question
What algorithm maximizes the judge score for AHC001-style rectangle packing (problem #147)? The task places N non-overlapping axis-aligned rectangles on a 10000×10000 grid, each containing a desired point, with satisfaction maximized when rectangle area matches the desired area. The solution is in `solution.cpp`.

## System Interface
- **Build:** The judge compiles C++17 automatically via the `frontier eval` pipeline.
- **Measure:** `bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp` — prints `SCORE: <n>` (0–100).
- **Code evidence:** `solution.cpp:1` — the only controllable file. The scoring formula is p_i = 1 - (1 - min(r_i,s_i)/max(r_i,s_i))^2; total score = 10^9 × Σp_i/n.
- **Time limit:** ~3s per test case (standard AHC). Solutions must finish within this.
- **Output format:** N lines, each `a_i b_i c_i d_i` (integer coords of rectangle diagonal).

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_147.sh $PWD/solution.cpp
```

## Baseline Validation
- Trivial 1×1 rectangles: SCORE 0 (areas too small for any satisfaction).
- Greedy expansion (500 iters, expand by 1 each direction): SCORE ~20.5.
- Simulated annealing (greedy init + 2.8s SA with edge moves): SCORE ~85.1.

## Experimental Conditions

### h-main: Simulated annealing with coordinated neighbor moves
Improve upon the basic SA by adding:
- When shrinking one rectangle's edge, simultaneously try expanding the adjacent rectangle into the freed space ("coordinated moves")
- Better step-size adaptation: large steps early, fine-grained steps late
- Improved initial placement via sorted greedy expansion (process companies by area, smallest first)

### h-control-negative: Greedy-only (no SA)
Simple greedy expansion without simulated annealing to validate that SA provides the score lift. Expected score ~20–25.

## Success Criteria
- h-main should score higher than the basic SA baseline (~85) consistently.
- h-control-negative should score significantly lower, confirming SA is the key mechanism.

## Constraints
- Must complete within 3s per test case.
- N ≤ 200 companies, so O(N) overlap checks per move are feasible.
- Output must be exactly N lines of 4 integers.

## Prior Knowledge
First iteration — no prior principles.
