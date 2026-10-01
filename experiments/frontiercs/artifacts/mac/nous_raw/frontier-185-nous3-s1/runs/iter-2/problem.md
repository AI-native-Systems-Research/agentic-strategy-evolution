# Problem Framing — Iteration 2

## Research Question
Can adding a local search phase after BnB timeout improve max clique score from 99.345 to 100 on the test distribution? The iter-1 BnB (`solution.cpp:18-80`) achieves optimal on most test cases but times out on hard instances. Local search (swap-based perturbation) may recover the remaining 0.655%.

## System Interface
- **Build:** Handled by `fmeasure_185.sh` (compiles C++17 with g++)
- **CLI:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp`
- **Code evidence:** `solution.cpp:14-16` — `ms()` timer function; `solution.cpp:27,67` — 1800ms timeout checks; `solution.cpp:136-178` — local_search function
- **Output:** `SCORE: <n>` on stdout

## Baseline Command
```bash
bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp
```
(Using iter-1 solution at 99.345 as baseline)

## Baseline Validation
- Exit code: 0
- Output: `SCORE: 99.345` (consistent across 6 runs in iter-1)
- The iter-1 BnB + greedy solution is the baseline.

## Experimental Conditions

### h-main: BnB + Local Search
The main improvement: add a swap-based local search phase that activates when BnB times out. After BnB exhausts its 1800ms budget:
1. Try direct clique extension (add vertices connected to all current clique members)
2. Try 1-remove/2-add swaps: remove one clique vertex, find two non-clique vertices that connect to all remaining members and to each other
3. Random perturbation restarts: remove a random vertex, greedily rebuild, repeat

Also: increased greedy restarts from 500→2000, reduced BnB timeout from 1850→1800ms to leave 100ms for local search.

**Command:** `bash /Users/toslali/frontier/gen_logs/fmeasure_185.sh $PWD/solution.cpp` (with v4 solution)

### h-control-negative: BnB Only (iter-1 baseline)
The original iter-1 solution without local search. Expected to remain at 99.345.

## Success Criteria
- h-main achieves score 100 consistently (across 3+ measurements)
- h-main > h-control-negative (99.345)

## Constraints
- 2.0s time limit per test case
- N ≤ 1000, M ≤ 500,000
- Single-threaded execution
- C++17, GCC-compatible

## Prior Knowledge
- RP-1: BBMC-style bitset coloring is faster than sequential greedy for BnB (confirmed iter-1)
- RP-2: Greedy with 5000 restarts achieves ~92%, BnB achieves 100% when it doesn't timeout
- Iter-1 showed BnB times out on some hard instances, causing score variance (90-100)
