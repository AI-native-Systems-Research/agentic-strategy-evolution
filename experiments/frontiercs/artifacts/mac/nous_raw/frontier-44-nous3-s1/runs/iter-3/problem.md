# Problem Framing — Iteration 3

## Research Question
Can or-opt (single-city relocation) with KNN candidate lists improve penalized TSP tour quality beyond what 2-opt + ILS achieves? The hypothesis is that or-opt finds improvements in a different neighborhood (relocation vs segment reversal) that 2-opt fundamentally cannot reach.

Key source files:
- `solution.cpp:1` — entire solution, single file
- `fmeasure_44.sh` — judge script (read-only)

## System Interface
- **Build:** Handled by judge (C++17, `-O2`)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp`
- **Output:** `SCORE: <n>` on stdout (0-100, higher is better)
- **Code evidence:** Solution is a self-contained C++ file compiled by the judge. No CLI flags.

## Baseline Command
```bash
cp inputs/solution_v25.cpp solution.cpp && bash /Users/toslali/frontier/gen_logs/fmeasure_44.sh $PWD/solution.cpp
```
(v25 = iter-2 best: grid NN + candidate-list 2-opt K=15 + window 2-opt + ILS double-bridge)

## Baseline Validation
v25 scores 78.93 consistently (observed 78.925, 78.926 in this session). Occasionally TLEs to ~73.93 under high machine load (RP-5).

## Experimental Conditions

### h-main: Or-opt1 + dist² early rejection
Copy `inputs/solution_v32.cpp` to `solution.cpp`. Changes from v25:
1. **Or-opt1 with KNN candidate lists** (`do_oropt1` function): For each city, compute removal gain (savings from extracting it). If positive, check K=15 nearest neighbors as candidate insertion points (both before and after each neighbor). Accept first improving relocation. Uses efficient memmove for array updates.
2. **dist² early rejection in candidate 2-opt**: Before computing eucl() (sqrt), check if dist²(a,c) ≥ threshold². Rejects most non-improving candidates with a cheaper check.
3. **Time allocation**: 2-opt 50% → or-opt1 58% → 2-opt 65% → window 75% → ILS remainder.
4. **Or-opt1 in ILS recovery**: After double-bridge perturbation, run 2-opt then or-opt1.

### h-control-negative: v25 baseline (no or-opt)
Copy `inputs/solution_v25.cpp` to `solution.cpp`. The iter-2 solution without or-opt.

## Success Criteria
h-main score > h-control-negative score (directional improvement). The mechanism test: if or-opt finds improvements that 2-opt can't, we should see consistent (though possibly small) score improvement.

## Constraints
- 2-second time limit per test case
- 512 MB memory limit
- Solution must be valid (start/end at city 0, visit all cities exactly once)
- Or-opt must not cause TLE on large test cases (N=200K)

## Prior Knowledge
- RP-1: Grid NN with G=sqrt(N/2.5) dominates construction quality (~78.2 alone)
- RP-2: Penalty (carrot constraint) is ~1% of cost — not worth optimizing directly
- RP-3: Fast 2-opt delta is O(1) Euclidean
- RP-4: Candidate-list 2-opt K=15 + ILS scores 78.93 (non-TLE)
- RP-5: ~5-point TLE drops are environmental, not algorithmic
- Iter-2 handoff: or-opt2 (pair relocation) and or-opt3 (triple relocation) cause TLE; only or-opt1 is safe
