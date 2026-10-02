# Problem Framing — Iteration 3

## Research Question
Can co-evolving per-type placement method assignments alongside type ordering improve the MaxRects packer's score beyond the 95.35 plateau from iteration 2?

The mechanism under study is in `solution.cpp`: the `greedyPackMixed()` function assigns a different MaxRects placement method (BSSF/BAF/BL/CP/BLSF) to each item type, allowing different types to use different placement heuristics within a single packing run.

## System Interface
- **Build:** `/opt/homebrew/bin/g++-15 -std=c++17 -O2 -o solution solution.cpp` (local); judge uses GCC in Docker
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output format:** `SCORE: <n>` printed to stdout (0-100 continuous)
- **Code evidence:** `solution.cpp` is the entire solution. Key structures:
  - `MaxRectsBin::tryOri()` — implements 5 placement methods (BSSF/BAF/BL/CP/BLSF) via switch on `method` parameter
  - `greedyPackMixed()` — type-level greedy that uses `mpt[ti]` (method-per-type array) for each type
  - `main()` Phase 3 — random search co-evolves ordering + MPT with 12 mutation strategies

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp
```

## Baseline Validation
Current `solution.cpp` (iter-2 v9) scores **89.02** on the current test set (down from 95.35 measured in iter-2 — test suite changed). Exit code 0, output format correct.

## Experimental Conditions

### h-main: Co-evolved MPT + ordering with gap-fill
Replace `solution.cpp` with v20 solution featuring:
1. **Per-type method assignment (MPT)**: Each item type uses its own MaxRects placement method (one of BSSF/BAF/BL/CP/BLSF), evolved alongside the type ordering
2. **Local search over methods**: After deterministic phase, hill-climb by changing individual type methods
3. **12-strategy random search**: Co-evolves ordering and MPT with mutation, crossover, and method-specific strategies
4. **Gap-fill post-processing**: After finding the best solution, re-run it and fill remaining gaps by density
5. **10 ordering strategies**: Added min-dim and aspect-ratio orderings

### h-control-negative: Uniform method (iter-2 baseline)
Current `solution.cpp` with uniform method per packing (no MPT). Tests whether the per-type method differentiation is the source of improvement.

## Success Criteria
h-main achieves a judge score ≥ 95.0, improving over the 89.02 baseline by at least 6 points. The per-type method assignment contributes measurably (h-main > h-control-negative).

## Constraints
- Time limit: 1 second per test case (15 test cases)
- Memory limit: 512 MB
- Must compile with C++17 on GCC in Docker
- Gap-fill must be time-bounded to avoid TLE (lesson from iter-2 v10)

## Prior Knowledge
- RP-1: MaxRects greedy with 6+ orderings × 3+ methods + randomized search achieves ~95% of fractional upper bound
- RP-2: Type-level greedy (exhaust one type before next) prevents TLE
- RP-3: Contact-point heuristic reduces fragmentation ~0.5%
- RP-4: Bin transposition helps on ~20-30% of cases
- RP-5: Both-orientation best-fit is critical (~6 points improvement)
- Iter-2 confirmed all above; gap-fill in every call causes TLE (v10 failure)
