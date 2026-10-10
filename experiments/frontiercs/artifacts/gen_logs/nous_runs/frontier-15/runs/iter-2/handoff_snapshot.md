# Handoff — Frontier-CS Problem #15 (Iter 2)

## Goal

Implement and test two variants of the circular buffer rotation sort: (1) an optimized version with BFS-derived last-3-element endgame sequences, and (2) an ablation that removes Op2 (prefix restoration) to prove it is essential. Measure judge scores for both. The h-main score should be recorded in findings metadata under key `score`.

## Key Discoveries

- **4-op endgame replaces 5-op**: BFS proves the last-2-element swap `[1,..,n-2,n,n-1]→sorted` can be done in 4 ops `(1,2),(1,n-2),(1,2),(2,2)` for n≥5 (previously 5 ops). Verified for all n=5..1000.
- **Last-3-element optimal sequences**: Handling the last 3 elements as a unit (instead of 1-by-1 + endgame) saves up to 4 operations. Five non-trivial configurations exist, each with a BFS-optimal sequence:
  - `[n-2, n, n-1]` → 4 ops: `(1,2), (1,n-2), (1,2), (2,2)`
  - `[n-1, n-2, n]` → 4 ops: `(1,1), (1,2), (2,2), (2,1)`
  - `[n-1, n, n-2]` → 2 ops: `(n-3, 2), (1, n-3)`
  - `[n, n-2, n-1]` → 2 ops: `(n-3, 1), (2, n-3)`
  - `[n, n-1, n-2]` → 3 ops: `(1,1), (1,3), (1,n-2)`
- **Worst-case reduction**: Original=2n+1, with 4-op endgame=2n, with last-3 optimization=2n-2. For n=1000: 2001→2000→1998.
- **Comparative statistics (500 random n=1000 perms)**: Original avg=1985.4, max=2000. Optimized avg=1984.0, max=1996. Optimized never loses (253 wins, 247 ties, 0 losses). Max savings=4 ops.
- **Op2 is essential**: Removing the prefix-restoration step causes 0/5 random permutations to sort. The sorted-prefix invariant breaks after the first Op1-only placement.
- **Scoring reminder**: Findings must include `"score": <number>` in each arm's metadata. Iter-1 omitted this, causing `best_found.json` to show 0.0.

## System Interface

- **Build:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0-100, continuous)
- **Baseline result:** SCORE: 100 with both the original and optimized algorithms

## Code Map

- `solution.cpp` — entire solution file; replace for each arm
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:64` — `best_operations = 2 * n + 1`. Check here if scoring formula seems wrong.
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:78` — score clamping logic. Score = 100 when ops ≤ 2001.
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:57` — `check_sorted()` — requires strictly increasing output.
- `/home/ubuntu/frontier/Frontier-CS/algorithmic/problems/15/chk.cc:51` — operation validity: `x > 0, y > 0, x + y < n`.

## Code Targets

### h-main (optimized last-3 endgame)
- File: `solution.cpp`
- Change main loop from `targ <= n-2` to `targ <= n-3`
- Replace the 5-op endgame `if (!is_sorted()) { apply(1,1); ... }` with a 6-case dispatch on `(p[n-3], p[n-2], p[n-1])` matching the patterns above
- Keep n=3 and n=4 special cases unchanged
- The complete optimized solution was already written and validated at `/tmp/solution_optimized.cpp` during design exploration

### h-ablation (remove Op2)
- File: `solution.cpp`
- In the main loop body, REMOVE the line `apply(d2, cf);` (Op2)
- Keep everything else (Op1, element search, d decomposition, endgame)
- The algorithm will fail to sort because the sorted prefix is moved to array end by Op1 and never restored

## What I Tried That Didn't Work

- **Single-operation greedy placement**: Tried placing each element with ONE operation (choosing x,y to map element to target position). Array never sorts because each op disrupts previously placed elements. 0/5 random permutations sorted in ~1000 ops.
- **Improving average ops via decomposition choice**: Analyzed whether choosing d1≠1 could help subsequent elements. Proved mathematically that the final buffer state is identical regardless of d1/d2 decomposition (only total d matters), so no optimization is possible here.
- **3-op-per-element approaches**: Explored using 3 operations per element (extract to position 0, move to target, restore prefix) — collapses to the same logic as the 2-op approach or fails to maintain any invariant.
- **Handling last 4+ elements as a unit**: Analyzed but diminishing returns — BFS max for 4 elements may not be better than 2(K-1) threshold needed to improve over the last-3 approach.

## What I Excluded and Why

- **Cycle-based sorting**: A fundamentally different approach that decomposes the permutation into cycles. Excluded because the 2-op circular buffer approach already achieves the benchmark (2n+1) and any cycle-based approach using prefix-suffix swaps faces the same global-disruption issue.
- **Reverse-direction sort (sorted suffix)**: The mirror-image algorithm building a sorted suffix from right-to-left. Excluded because it's structurally identical with the same operation count — no new scientific information.
- **n < 5 optimization**: All test cases have n=1000. The n=3 and n=4 special cases are inherited from iter-1 unchanged.

## Evolution of Thinking

1. Started by trying to find a fundamentally different algorithm that could beat score 100 — realized the score is clamped at 100 (maximum achievable).
2. Shifted focus to OPERATION COUNT optimization within the existing mechanism. Discovered via BFS that the 5-op endgame can be reduced to 4 ops for n≥5.
3. Extended the analysis to handle the last 3 elements as a unit, finding BFS-optimal 2-4 operation sequences. This reduces worst case from 2n+1 to 2n-2.
4. For the ablation, initially considered various "worse" algorithms but realized the cleanest ablation is removing Op2 — it directly tests whether the prefix-restoration step is necessary (it is).
5. Verified that no decomposition optimization is possible (the final state after 2 ops depends only on the total rotation d, not on how d is split into d1+d2).

## Current Status

- **Validated:** Optimized algorithm compiles, passes 200 random n=1000 tests (0 failures), and scores 100 on the judge. Op2 ablation confirmed non-functional (0/5 sorts).
- **Uncertain:** Whether there exist permutations where the optimized last-3 endgame uses more than 4 operations (would need >6 total elements in the endgame unit). Theoretical worst case is 4 ops, matching BFS proof.
- **Suggested next:** The algorithm is at the scoring ceiling (100). Future iterations could explore: (a) whether the 2n-2 worst case is tight or can be further reduced with larger endgame units, (b) a formal lower bound on operation count for this operation type, (c) completely different algorithmic strategies (if any exist) that achieve the benchmark.

## Warnings & Constraints

- **fmeasure_15.sh takes 30-60 seconds**: Minimize unnecessary calls. One call per arm is sufficient.
- **The optimized endgame sequences use large x or y values**: `(n-3, 2)` and `(n-3, 1)` have x=997 for n=1000. These are valid (x+y=999 < 1000) but look unusual.
- **The ablation will NOT sort**: Don't waste time debugging the ablation output — it's expected to fail. Just confirm SCORE: 0.
- **Score must be in findings metadata**: Record `"score": <number>` in each arm entry. Iter-1 omitted this, causing `best_found.json` to show 0.0 for all arms.
- **Pattern 3 `[n-1,n-2,n]` uses (1,1),(1,2),(2,2),(2,1)**: These small-valued operations work for all n≥5 because x+y ≤ 4 < n always.
