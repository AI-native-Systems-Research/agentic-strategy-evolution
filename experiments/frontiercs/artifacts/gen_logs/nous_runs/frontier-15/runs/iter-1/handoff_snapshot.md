# Handoff — Frontier-CS Problem #15 (Iter 1)

## Goal

Implement and evaluate two algorithmic strategies for sorting a permutation via prefix-suffix swap operations, measuring the judge score (0-100). The primary strategy (circular buffer rotation) should achieve score 100; the control (greedy) should score lower.

## Key Discoveries

- **Scoring formula**: `score = 100 * clamp((4n - ops) / (2n - 1), 0, 1)`. For n=1000, score 100 requires ≤ 2001 ops. The benchmark `best_operations` is hardcoded to `2n+1` in `chk.cc:64`.
- **All test cases have n=1000** (verified by reading all 10 `.in` files). No small-n edge cases.
- **The 2-rotation algorithm achieves ≤ 2n+1 worst-case ops**: validated on 100 random permutations (n up to 1000) plus the judge itself (SCORE: 100).
- **Operation statistics for n=1000**: min=1971, max=1996, mean=1985.1 across 50 random trials. Always below 2001.
- **The checker requires the identity permutation**: `chk.cc:57` calls `check_sorted` which verifies p[i] < p[i+1]. Any non-sorted result gets WA.
- **Edge case for d=1, l≥3**: decomposition uses d1=2, d2=l-1 (sum = l+1 ≡ 1 mod l). Verified correct.
- **Edge case for element 1 at position 1**: requires 2-op special case (apply(2,1) then apply(1,1)) because apply(1, n-1) has x+y=n (invalid).

## System Interface

- **Build:** `g++ -O2 -std=c++17 -o solution solution.cpp`
- **Run baseline:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_15.sh $PWD/solution.cpp`
- **Output format:** Prints `SCORE: <n>` (0-100, continuous)
- **Baseline result:** SCORE: 100 with the h-main algorithm

## Code Map

- `algorithmic/problems/15/chk.cc:64` — `best_operations = 2 * n + 1` defines the scoring benchmark. Check here if scores seem miscalibrated.
- `algorithmic/problems/15/chk.cc:8-21` — `perform_operation()` implements the prefix-suffix swap. Check here if output format seems wrong.
- `algorithmic/problems/15/chk.cc:57` — `check_sorted()` validation. Check here if getting WA.
- `algorithmic/problems/15/config.yaml` — 10 test cases, 1s time limit, 512MB memory.
- `algorithmic/problems/15/testdata/` — 10 test inputs, all n=1000.

## Code Targets

### h-main (circular buffer rotation)
- File: `solution.cpp`
- Replace entire file with the 3-phase algorithm:
  1. Place element 1 (1-2 ops, special case for position 1)
  2. Two-operation rotation for elements 2..n-2
  3. Five-operation endgame for last 2 elements
- **The working implementation was already validated**: see verified solution in the workspace.

### h-control-negative (greedy lexicographic)
- File: `solution.cpp`
- Replace with greedy approach: try ops (1,1),(1,2),(2,1) each step, pick lexicographically smallest result.
- Expected to use many operations (close to 4n) and score poorly.

## What I Tried That Didn't Work

- **Sorted prefix invariant with 2 ops**: Tried bringing element k+1 to position 0 then restoring prefix. FAILS because Op2 puts k+1 at position n-1, not position k. The prefix is restored but never extended.
- **Single-operation placement**: Setting x=cur, y=k places element at position k in ONE op, but destroys the sorted prefix. Not usable without repair.
- **Direct swap of last 2 elements**: All 2-operation sequences on [1,..,n-2,n,n-1] cycle back to the start. Need odd number of ops (5-op sequence confirmed working).

## What I Excluded and Why

- **Merge sort approaches**: The 2-rotation approach already achieves the benchmark. No need for more complex strategies.
- **Adaptive sweep over parameters**: There are no continuous parameters to tune — the algorithm is deterministic.
- **n=3 edge cases**: All test cases have n=1000. n=3 has unreachable permutations but is irrelevant.

## Evolution of Thinking

1. Initially assumed sorted prefix could be maintained while placing each element → discovered that EVERY operation disrupts any sorted region.
2. Key breakthrough: viewing the unsorted region as a circular buffer where two operations compose rotations, while the sorted prefix "round-trips" to the end and back.
3. Discovered the d=1 edge case (d1+d2 can't sum to 1 with both ≥1 and <l using simple splitting) → solved with d1=2, d2=l-1.
4. Discovered last-2-element swap requires odd-parity operation count → found 5-op sequence that works for all n≥4.

## Current Status

- **Validated:** h-main algorithm achieves score 100. Compilation, correctness (100 random tests), and judge score all confirmed.
- **Uncertain:** Whether the greedy control will sort within 4n ops or fail for some inputs. The trinitylargethinking reference solution suggests it works but with many ops.
- **Suggested next:** If score 100 is confirmed across all seeds, consider whether there exist even more efficient algorithms (though no scoring benefit). Could also explore the problem's group-theoretic structure for theoretical insight.

## Warnings & Constraints

- **Time limit is 1 second**: The O(n²) loop (finding each element by linear scan) is fine for n=1000 but would need optimization for larger n.
- **Operation (x, y) requires x > 0, y > 0, x + y < n**: The "middle" must have at least 1 element. This constraint is the source of several edge cases (element 1 at position 1, last 2 elements).
- **The 5-op endgame sequence is specific to [1,..,n-2,n,n-1]**: Do NOT apply it if the last 2 are already in order — check `is_sorted()` first.
- **fmeasure_15.sh takes 30-60 seconds**: Each judge call is expensive. Minimize unnecessary calls.
