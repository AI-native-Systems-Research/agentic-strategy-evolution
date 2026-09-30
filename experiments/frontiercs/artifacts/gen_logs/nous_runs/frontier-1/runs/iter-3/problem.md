# Problem Framing — Iteration 3

## Research Question

Can an amortized wall-time guard (chrono::steady_clock checked every 512 B&B nodes) combined with fast I/O (fread/printf) and conditional LS2 reliably achieve 100/100 on the Frontier-CS judge, eliminating the intermittent Docker-induced score drops observed in iterations 1-2?

**Root cause from iter-2 (RP-5):** Docker timing variability causes 5% score drops on ~30% of judge runs. The iter-2 `clock()` guard measured CPU time (useless for Docker wall-time overhead). The prior iter-3 attempt used `chrono::steady_clock` but: (a) called it at EVERY B&B node, doubling execution time (TC1: 21ms->40ms), and (b) used slow I/O (string, istringstream, cout). Result: 5/7 at 100, no improvement over iter-2.

**New insight from this exploration:** Per-node chrono calls add ~100% overhead. Amortizing to every 512 nodes eliminates this overhead entirely (TC1: 19ms with guard vs 21ms without). Combined with fast I/O (char[], fread, printf from the existing codebase), the solution achieves 8/10 at 100 vs iter-2's 7/10.

## System Interface

- **Build:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
- **Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
  - Prints `SCORE: <n>` where n is 0-100.
  - Internally: `frontier eval algorithmic 1 <solution.cpp>` compiles and runs against 20 test cases in Docker.
- **Code evidence:**
  - `solve()` function: `solution.cpp:97` -- B&B recursion entry
  - ternary search loop: `solution.cpp:86` -- `for (int iter = 0; iter < 12; iter++)`
  - tight_ub cutoff: `solution.cpp:116` -- `if (idx < 8)` (tight bounds for first 8 levels)
  - greedy heuristics: `solution.cpp:283-307` -- 23 alpha-parameterized variants + 2 pure density sorts
  - local search: `solution.cpp:137-212` -- add, swap, remove-refill moves
  - JSON parser: `solution.cpp:220-262` -- fread + manual char-by-char parsing (zero allocations)
  - JSON output: `solution.cpp:321-327` -- printf (no cout/streams)

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp
```

## Baseline Validation

Ran the modified solution (amortized chrono + fast I/O) on the judge 10 times:
- Runs 1-5: 100, 100, 100, 100, 100
- Runs 6-10: 95, 100, 100, 95, 100
- 8/10 at 100 (80%), 2/10 at 95 (20%)
- Mean: 99.0

Compared to iter-2 h-main (clock()-based guard): 7/10 at 100 (70%), 3/10 at 95 (30%), mean 98.5.

Local timing (all 20 test cases complete in <25ms):
- TC1 (hardest): 19ms
- TC5: 2ms, TC10: 3ms, TC14: 12ms, TC20: 5ms

## Experimental Conditions

### h-main: Amortized wall-time guard with fast I/O

Starting from the worktree's solution.cpp (full B&B solver with 12 ternary iterations, multi-greedy, local search, fast char[]/fread/printf I/O), make four changes:

1. **Add chrono globals:** `chrono::steady_clock::time_point start_time;` and `bool bnb_timed_out = false;` as global variables.

2. **Amortized time guard in solve():** Check `chrono::steady_clock::now()` every 512 B&B nodes (using `bnb_nodes & 511 == 0`). If >700ms elapsed from program start, set `bnb_timed_out = true` and return. Also check `bnb_timed_out` at every node for fast recursion unwinding.

3. **Set start_time at program entry:** `start_time = chrono::steady_clock::now();` as the first line of main(), before parsing.

4. **Conditional LS2:** Replace unconditional `local_search()` after B&B with: run LS2 only if `bnb_timed_out && elapsed < 800ms`. When B&B completes normally (finds optimal), LS2 is unnecessary. When B&B times out, LS2 may improve the greedy+LS1 fallback.

**Rationale for 512-node amortization:** `chrono::steady_clock::now()` has ~50-100ns overhead per call. The B&B explores thousands of nodes. Per-node calling doubles execution time (TC1: 21ms->40ms, measured). Checking every 512 nodes amortizes this to <0.1ms total, with <0.5ms worst-case guard latency.

**Rationale for 700ms threshold:** The solution completes in <25ms locally. Docker slowdown is typically 3-5x (75-125ms). The 700ms guard leaves 300ms for Docker startup/shutdown overhead.

## Success Criteria

- **Primary:** Judge score of 100 on the official measurement run.
- **Reliability target:** 80%+ of judge runs at 100 (improvement over iter-2's 70%).
- **Lower bound:** Score >= 95 on every run (no regression below iter-2's worst case).

## Constraints

- 1-second time limit per test case in Docker.
- Docker uses GCC with `-static` flag and `using namespace std` (do NOT use `ratio` as identifier).
- Solution must produce valid JSON output with all 12 item keys.
- Must compile with `-std=gnu++17`.

## Prior Knowledge

- **RP-1:** B&B with Lagrangian LP relaxation finds exact integer optima on all 20 test cases (100/100).
- **RP-3:** 12 ternary iterations preserve optimality with 30-37% speedup vs 20 iterations.
- **RP-4:** Greedy+LS without B&B scores 90.597 with zero variance.
- **RP-5:** Docker timing variability causes 5% score drops. `clock()` measures CPU time, not wall time.
- **Prior iter-3 attempt:** chrono::steady_clock at 850ms with slow I/O gave 5/7 at 100. Per-node chrono calls double execution time.
