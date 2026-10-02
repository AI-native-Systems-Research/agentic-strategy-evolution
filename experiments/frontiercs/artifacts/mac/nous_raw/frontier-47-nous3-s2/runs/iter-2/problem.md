# Problem Framing — Iteration 2

## Research Question

How can we push the 2D rectangular knapsack score beyond 94.84 by improving the search strategy (simulated annealing over item orderings) and adding a residual gap-filling pass after the main ordered pack?

Iter-1 established that item ordering is the dominant lever (RP-1) and MaxRects with hill-climbing achieves ~94.8. The hill-climbing is limited by local optima — it stops at the first permutation with no improving swap/insert neighbor. Simulated annealing can escape these by accepting worse solutions with decreasing probability.

Additionally, the ordered packing approach processes item types sequentially — once it moves past type A to type B, it never revisits A even if free space could still fit A copies. A gap-filling pass after the ordered pack addresses this.

Source: iter-1 h-main.patch (`solution.cpp` lines 177-208 for hill-climbing, lines 103-121 for ordered packing).

## System Interface

- **Build:** N/A (judge compiles server-side with `bits/stdc++.h`)
- **Run:** `bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp`
- **Output:** `SCORE: <float>` on stdout
- **Code evidence:** The measure script at `/Users/toslali/frontier/gen_logs/fmeasure_47.sh` sends `solution.cpp` to a Docker-based judge that compiles and runs it on 15 hidden tests.

## Baseline Command

```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_47.sh $PWD/solution.cpp
```

## Baseline Validation

Iter-1 h-main achieved SCORE: 94.84 with the hill-climbing MaxRects solution. The current `solution.cpp` in the worktree is an earlier version scoring 94.46.

## Experimental Conditions

### h-main: SA + Gap Filling Enhanced MaxRects

Replace `solution.cpp` with an enhanced algorithm that:

1. **Simulated annealing over item orderings**: Replace hill-climbing with SA that starts from the best known ordering for each heuristic. Temperature schedule: T₀ = 0.1 × bestProfit, cooling factor α = 0.995 per iteration. Accept worse solutions with probability exp((new-old)/T). This allows escaping local optima that hill-climbing gets stuck in.

2. **Residual gap-filling pass**: After the main ordered pack, iterate over all item types (sorted by value density) and try to place additional copies into remaining free rectangles. This captures value the sequential ordering misses.

3. **Improved time management**: Allocate ~0.15s for initial sorted/greedy packing, ~0.65s for SA search, ~0.08s for random restarts. This prioritizes SA (the most effective phase) over permutation exhaustion.

4. **3-opt neighborhood**: In addition to swap and insert moves, add reverse-subsequence moves to the SA neighborhood.

### h-ablation: SA Only (No Gap Filling)

Same as h-main but WITHOUT the gap-filling pass. Tests whether gap filling contributes independently.

## Success Criteria

- h-main achieves score > 95.0 (improvement over iter-1's 94.84)
- h-main outperforms h-ablation (gap filling adds value)

## Constraints

- 1 second time limit per test case (15 test cases)
- 512 MB memory limit
- Must output valid JSON with exact schema
- RP-2: Avoid contact perimeter heuristic (too slow)

## Prior Knowledge

- RP-1: MaxRects with hill-climbing over orderings achieves ~94.8; ordering is the dominant lever
- RP-2: Contact perimeter heuristic too slow for 1s budget
- Iter-1 showed hill-climbing adds ~0.4 points over pure permutation + random search (94.45 → 94.84)
