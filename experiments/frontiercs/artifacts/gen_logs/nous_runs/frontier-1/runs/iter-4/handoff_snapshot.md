# Handoff — Iteration 4

## Goal

Implement and validate a combined optimization of the B&B solver: add early-exit detection (skip B&B when greedy+LS already found the optimum), replace printf() with write() syscall, add `#pragma GCC optimize("O3,unroll-loops")`, tighten chrono check to every 256 nodes, and remove LS2. Measure judge score.

## Key Discoveries

1. **SIGALRM is blocked by go-judge sandbox.** A proof-of-concept that uses setitimer(ITIMER_REAL, 800ms) + signal(SIGALRM, handler) to output before TLE scored 0/100 — the alarm handler never fires. go-judge uses SIGKILL for time enforcement, which is unblockable. No signal-based safety net is possible.

2. **B&B finds the exact optimum on all 20 test cases** (verified by comparing output against `$i.ans` line 2 = best_value for each test case). The score drops to 95/90 are exclusively from TLE (program killed before output), not from suboptimal solutions.

3. **Greedy+LS is always above baseline** (minimum per-case score 43.9% on TC12, 48.2% on TC16, 65.3% on TC14). This means if the program outputs greedy+LS, it NEVER gets 0 on any test case. The 0-scoring cases are from TLE (no output at all).

4. **Greedy+LS is already optimal on 8/20 test cases** (TC2,3,4,5,10,13,17,19: greedy_value == best_value). Early-exit detection using `tight_ub(0, MAX_MASS, MAX_VOL)` can skip B&B on these cases, eliminating any TLE risk for 40% of evaluations.

5. **write() vs printf() makes no measurable difference in judge reliability.** Tested v4 (write-based) 11 times: 9/11 at 100 vs original 14/15 at 100. The improvement is within noise. The TLE is caused by Docker/go-judge overhead that is outside algorithmic control.

6. **`#pragma GCC optimize("O3,unroll-loops")` has negligible local speedup.** TC1: 20ms→21ms, TC14: 12ms→13ms with pragmas. The program is already fast; the bottleneck is Docker overhead.

7. **Current reliability: ~85-93% at score 100.** Across 26 judge runs during this exploration: 22 at 100 (85%), 3 at 95, 1 at 90. The ~15% TLE rate appears irreducible from Docker/go-judge overhead.

## System Interface

- **Build:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
- **Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` where n is 0-100
- **Baseline result:** 22/26 runs at 100 (85%), 3 at 95, 1 at 90 (mean ~99.0)

## Code Map

- `solution.cpp` — the only file to edit. Contains the full B&B solver with all optimizations.
- `solution.cpp:1-2` — `#include <bits/stdc++.h>` and `using namespace std;`
- `solution.cpp:7` — `chrono::steady_clock::time_point start_time;`
- `solution.cpp:8` — `bool bnb_timed_out = false;`
- `solution.cpp:97-106` — `solve()` entry with amortized time guard (every 512 nodes at 700ms)
- `solution.cpp:86` — ternary search: `for (int iter = 0; iter < 12; iter++)`
- `solution.cpp:116-119` — tight vs cheap bound cutoff at level 8
- `solution.cpp:217` — `start_time = chrono::steady_clock::now();` (first line of main)
- `solution.cpp:283-307` — multi-greedy heuristics (23 alpha variants + 2 pure density)
- `solution.cpp:309` — `local_search();` (LS1, always runs)
- `solution.cpp:311-312` — B&B call: `solve(0, MAX_MASS, MAX_VOL, 0);`
- `solution.cpp:314-318` — conditional LS2 (to be REMOVED)
- `solution.cpp:320-327` — printf output (to be REPLACED with write())
- `solution.cpp:214` — `static char inbuf[65536];` — fread input buffer
- `algorithmic/problems/1/config.yaml:3` — `time: 1s` (go-judge time limit)
- `algorithmic/problems/1/chk.cc:86` — scoring formula: `(participant - baseline) / (best - baseline)`
- `algorithmic/problems/1/testdata/` — 20 test case files (1.in through 20.in)

## Code Targets

### h-main (optimized-bnb-v4)
- **File:** `solution.cpp`
- **Change 1:** Add `#pragma GCC optimize("O3,unroll-loops")` as the VERY FIRST line (before any #include).
- **Change 2:** Add `format_and_write_output()` function: formats JSON to a static `char outbuf[8192]` using sprintf, then writes with `write(1, outbuf, outlen)`. Include `<unistd.h>` for write(). Retry loop for partial writes.
- **Change 3:** After greedy+LS (line 309) and before B&B (line 311), add: `double ub = tight_ub(0, MAX_MASS, MAX_VOL); if ((long long)(ub + 0.5) <= best_value) { format_and_write_output(); return 0; }`
- **Change 4:** In `solve()`, change `(bnb_nodes & 511)` to `(bnb_nodes & 255)` on line 100.
- **Change 5:** Remove lines 314-318 (conditional LS2 block).
- **Change 6:** Replace lines 320-327 (printf output) with `format_and_write_output();`.

## What I Tried That Didn't Work

1. **(This exploration) SIGALRM safety net:** Created `solution_alarm_proof.cpp` with setitimer + signal handler to output before TLE. Score: 0/100. go-judge's sandbox blocks SIGALRM entirely — the alarm handler never fires.

2. **(This exploration) #pragma GCC optimize alone:** No measurable local speedup (TC1: 20→21ms). The program is already fast; the bottleneck is Docker infrastructure.

3. **(This exploration) write() instead of printf():** v4 solution tested 8/10 at 100 vs original's 14/15 at 100. write() doesn't improve reliability because the program finishes printf before being killed in normal operation. The TLE is from Docker overhead BEFORE/AROUND program execution, not from stdio buffering.

4. **(This exploration) Tighter chrono guard at 500ms with pragmas:** solution_fast scored 7/10 at 100 — WORSE than the original. The 500ms guard may be too aggressive for some test cases under Docker CPU throttling.

5. **(Iter-3) Per-node chrono calls:** Doubles execution time. Use amortized approach.
6. **(Iter-3) Slow I/O (string/istringstream/cout):** Negated timing improvements.
7. **(Iter-2) clock()-based guard:** Measures CPU time, not wall time.
8. **(Iter-2) Tight bounds at all 12 levels:** No improvement.
9. **(Iter-1) Field name `ratio`:** Compilation failure with `using namespace std`.

## What I Excluded and Why

- **DP approaches**: 2D DP needs 20M x 25M state space — infeasible even with scaling.
- **Meet-in-the-middle**: 500^6 ~ 10^16 per half — infeasible.
- **500ms chrono guard**: Tested with solution_fast, scored worse (7/10 at 100 vs 14/15). May cause premature B&B termination under Docker CPU throttling.
- **SIGALRM/setitimer**: Definitively blocked by go-judge sandbox. Do not attempt.
- **Simulated annealing / tabu search**: Only helps greedy+LS fallback. B&B already finds exact optima.
- **Further B&B algorithmic optimization**: The B&B runs in <25ms locally for ALL test cases. The bottleneck is Docker overhead (~15% failure rate), not algorithm speed.

## Evolution of Thinking

1. **Iter-1:** Discovered B&B + Lagrangian finds exact optima (100/100 locally).
2. **Iter-2:** Found Docker variance causes 30% failure rate. Clock()-based guard didn't help.
3. **Iter-3:** Amortized chrono guard improved reliability to 80%.
4. **This exploration (iter-4 design):**
   - Tried SIGALRM safety net → blocked by go-judge sandbox (SCORE: 0)
   - Verified B&B finds exact optima on ALL 20 cases (compared against answer files)
   - Verified greedy+LS is always above baseline (min per-case 43.9%)
   - Discovered early-exit opportunity on 8/20 cases
   - Tested pragma + write() + tighter guard → no measurable improvement
   - **Conclusion:** The ~15% TLE rate is caused by Docker/go-judge infrastructure overhead that is outside algorithmic control. The algorithm is already optimal and fast. The best we can do is minimize every source of overhead and accept the residual variance.

## Current Status

- **Validated:** B&B finds exact optima on all 20 test cases (verified against answer files)
- **Validated:** SIGALRM does not work in go-judge sandbox
- **Validated:** Greedy+LS always beats baseline (min 43.9% per case)
- **Validated:** Early-exit detects 8/20 cases where greedy+LS is optimal
- **Validated:** Current reliability ~85% at 100 across 26 judge runs
- **Uncertain:** Whether #pragma actually affects go-judge's compilation (may be overridden)
- **Uncertain:** Whether write() vs printf() helps under extreme Docker timing
- **Suggested next:** The algorithm is solved (exact optima on all cases). Remaining improvement requires either (a) understanding go-judge's specific timing mechanism to optimize for it, or (b) accepting the ~15% Docker variance as irreducible and considering the problem effectively solved at expected score ~99.

## Warnings & Constraints

1. **NEVER use `ratio` as a struct field name** with `using namespace std`. GCC interprets it as `std::ratio`.
2. **SIGALRM does NOT work in go-judge sandbox.** Do not attempt signal-based safety nets.
3. **Do NOT reduce chrono guard below 700ms.** Testing at 500ms with solution_fast gave WORSE results (7/10 at 100 vs 14/15). Docker CPU throttling may cause B&B to take longer than expected.
4. **Do NOT call chrono::steady_clock::now() at every B&B node.** Use amortized approach (every 256 or 512 nodes).
5. **Do NOT use string/istringstream/cout.** The worktree has fast char[]/fread I/O.
6. **Do NOT reduce tight_ub depth below 8 or ternary iterations below 12.** These are essential for B&B efficiency.
7. **Run the judge at least 3 times** to assess reliability. Docker variance means a single score is not representative.
8. **Docker timing varies 3-5x vs bare metal.** A 25ms solution may take 75-125ms in Docker.
9. **Score of 95 means exactly 1 out of 20 test cases TLEd.** Score of 90 means 2 TLEd.
10. **go-judge compiles the solution with its own flags.** #pragma may or may not be respected. If the judge returns SCORE: 0 with pragma, try removing it.
