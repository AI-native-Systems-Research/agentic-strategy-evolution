# Problem Framing — Iteration 3

## Research Question
Is the current BnB + local-search solution robust enough to score 100 consistently at full scope, and does tightening the time management (adaptive BnB cutoff based on elapsed time) provide any measurable benefit over the fixed 1800ms cutoff?

Key source files:
- `solution.cpp:18-91` — `mcq_bs()` BnB with greedy coloring bound
- `solution.cpp:93-216` — `local_search()` swap-based perturbation
- `solution.cpp:280-299` — BnB decomposition loop with degeneracy ordering
- `solution.cpp:301-304` — Local search activation on timeout

## System Interface
- **Build:** Handled internally by `fmeasure_185.sh` (compiles with g++ -O2 -std=c++17)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` to stdout
- **Code evidence:** The measure script compiles solution.cpp and runs it against hidden test cases with a 2.0s time limit per case.

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp
```

## Baseline Validation
Ran twice consecutively. Both returned `SCORE: 100`. The current solution (BnB + local search, v4 from iter-2) is the production baseline.

## Experimental Conditions

### h-main: Adaptive time management
Modify the BnB cutoff to be adaptive: use 1700ms for BnB (leaving 250ms for local search instead of 100ms). This gives local search more room to recover on hard instances while keeping BnB time sufficient.

Changes from baseline:
- `solution.cpp:28` — Change BnB timeout from 1800 to 1700
- `solution.cpp:81` — Same change
- `solution.cpp:287` — Same change  
- `solution.cpp:302` — Change local search activation threshold from 1900 to 1900 (unchanged)

Intent: Give local search 200ms budget instead of 100ms. On instances where BnB times out, the extra local search time should maintain score 100 even under system load.

### h-control-negative: Current production solution (unchanged)
Run the existing solution.cpp as-is. This confirms the baseline score at full scope for this iteration.

## Success Criteria
- h-main achieves score 100
- h-control-negative achieves score 100
- Both arms demonstrate the solution is robust at full scope

## Constraints
- Time limit: 2.0s per test case
- Memory limit: 512MB
- N ≤ 1000, M ≤ 500,000
- Must output exactly N lines of 0/1

## Prior Knowledge
- RP-1: BBMC-style bitset coloring is faster in theory but has higher constant factor at N≤1000 (iter-1 discovery)
- RP-2: Greedy restarts alone achieve ~92%, BnB achieves 100% (iter-1)
- RP-3: BnB with greedy coloring completes within 1900ms under normal load, achieving 100 (iter-2 confirmation)
- RP-4: Local search is defensive insurance, not necessary for 100 under normal conditions (iter-2)
- Iter-2 showed that the 99.345 from iter-1 was a system load artifact, not algorithmic
