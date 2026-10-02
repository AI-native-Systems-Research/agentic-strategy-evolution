# Problem Framing — Iteration 3

## Research Question

Can expanding the MaxRects heuristic set from 4 to 8, adding per-item rotation mode as an SA dimension, and tuning SA cooling/restart strategy push the 2D rectangular knapsack score beyond iter-2's 95.21?

Key source files:
- `solution.cpp` — the entire solution (single-file C++17)
- Judge: `/Users/toslali/frontier/Frontier-CS/src/frontier_cs/runner/algorithmic_local.py`

## System Interface

- **Build:** N/A (judge compiles server-side with `bits/stdc++.h`)
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <float>` (0-100, higher is better)
- **Code evidence:** Judge runs 15 test cases, 1s time limit per test, bins 900-2000, 8-12 item types

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp
```

(With iter-2 h-main.patch applied as baseline)

## Baseline Validation

- Exit code: 0
- Output: `SCORE: 95.21464666666665`
- This is the iter-2 best score using SA over joint (ordering × per-item-heuristic) with 4 MaxRects heuristics.

## Experimental Conditions

### h-main: Expanded heuristic set + rotation mode + tuned SA
Changes from iter-2 baseline:
1. **8 MaxRects heuristics** (was 4): Add perimeter-sum fit, top-right, left-bottom (x-primary), and aspect-ratio fit
2. **Per-item rotation mode** as SA dimension: 0=auto (try both, pick best), 1=normal only, 2=force rotate. Expands search space from 8^M to 24^M effective configurations per ordering.
3. **SA cooling**: T*=0.995 (was 0.9995), reheat every 500 iterations (was 1000). Faster cooling + more frequent reheat = more greedy exploitation between reheats.
4. **3 SA restarts** (was 1): Seeds 12345, 67890, 31415. Time splits 0.35-0.58, 0.58-0.74, 0.74-0.87.
5. **Remove gap-fill phase** (proven useless per RP-4)
6. **Remove random perturbation restarts** (replaced by SA restarts)

### h-control-negative: Original 4 heuristics with same SA improvements
Same SA cooling/restart/rotation improvements, but restricted to original 4 heuristics. Isolates the contribution of expanded heuristic space.

## Success Criteria

- h-main score > 95.21 (iter-2 baseline), targeting ~96.4
- h-main > h-control-negative (demonstrates expanded heuristics contribute)

## Constraints

- 1s time limit per test case
- Solution must be single-file C++17, compiles with `bits/stdc++.h`
- 512 MB memory limit
- `bits/stdc++.h` only works server-side (no local macOS compilation)

## Prior Knowledge

- RP-1: MaxRects + hill-climbing achieves ~94.8 (iter-1)
- RP-2: Contact perimeter heuristic is too slow for 1s budget
- RP-3: SA over joint (ordering × per-item-heuristic) achieves ~95.2; per-item heuristic is the key lever
- RP-4: Gap filling provides zero value when per-item heuristics are optimized

## Probed Results

Multiple probe runs of h-main during design:
- 8 heuristics alone: 95.61
- + rotation mode: 95.68
- + 3 SA restarts: 95.73
- + tuned cooling (T*=0.995): 96.47
- Verified range across multiple runs: 96.3-96.5
