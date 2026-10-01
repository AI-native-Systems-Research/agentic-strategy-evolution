# Problem Framing — Iteration 3

## Research Question

Is the L/R leaf-tracking tree decomposition in solution.cpp still the optimal algorithm for problem #22, achieving maximum score 100? This is a full-scope confirmation run after iter-1 (discovery) and iter-2 (rehearsal confirmation).

Source: `solution.cpp` — implements the S/Lnk/H bag pattern with bag size ≤ 4 and K ≤ 3(N−1).

## System Interface

- **Build:** Handled by judge script (C++17, Docker).
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_22.sh $PWD/solution.cpp`
- **Code evidence:** Scoring formula in `algorithmic/problems/22/checker.cpp:120` — awards 100 for any valid decomposition with K < 5N.
- **Output:** Single line `SCORE: <n>` on stdout.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_22.sh $PWD/solution.cpp
```

## Baseline Validation

Exit code 0. Output: `SCORE: 100`. Verified during iter-3 design exploration.

## Experimental Conditions

### h-main: Confirm maximum score
- Run the existing solution.cpp unchanged through the judge.
- Expected: SCORE: 100.

No alternative arms needed — score is already maximal (100/100) and has been confirmed in two prior iterations.

## Success Criteria

- SCORE: 100 (maximum possible).

## Constraints

- Cannot compile C++ locally; must use `fmeasure_22.sh`.
- Time limit: 2 seconds per test case (handled by judge).
- Memory limit: 1024 MiB (handled by judge).

## Prior Knowledge

- RP-1 (high confidence): L/R leaf-tracking decomposition achieves bag size ≤ 4, K ≤ 3N. Confirmed in iter-1 and iter-2.
- Iter-1: Score 100 (discovery). Iter-2: Score 100 (confirmation). Both CONFIRMED.
