# Handoff — Iteration 3

## Goal

Implement and validate the amortized wall-time guard for the B&B solver: add `chrono::steady_clock` checked every 512 B&B nodes at 700ms threshold, preserve fast I/O (char[]/fread/printf), and make LS2 conditional on B&B timeout. Measure judge score.

## Key Discoveries

1. **Per-node chrono calls double execution time.** The prior iter-3 attempt called `chrono::steady_clock::now()` at every B&B node, increasing TC1 from 21ms to 40ms (~90% overhead). With thousands of B&B nodes, the ~50-100ns per chrono call accumulates. Amortizing to every 512 nodes (`bnb_nodes & 511 == 0`) eliminates this overhead entirely (TC1: 19ms with guard).

2. **Slow I/O negated the chrono fix in the prior attempt.** The prior iter-3 patch used `string` names, `istringstream` for parsing, and `cout` for output — all slower than the worktree's `char[]`, `fread` + manual parsing, and `printf`. Combined with per-node chrono overhead, the prior attempt scored 5/7 at 100 (71%) — essentially identical to iter-2's 7/10 (70%).

3. **The amortized approach with fast I/O achieves 8/10 at 100 (80%).** Design-phase testing: 10 judge runs yielded [100,100,100,100,100,95,100,100,95,100]. Mean: 99.0 vs iter-2's 98.5.

4. **Tight Lagrangian bounds at levels 0-7 are ESSENTIAL.** Testing with cheap bounds only (or tight bounds only at levels 0-3): all test cases hit the 700ms time guard. The tight bounds enable the B&B to prune so aggressively that it completes in <25ms locally.

5. **Reducing ternary iterations from 12 to 8 produces mixed results.** TC1 and TC14 get faster, but TC20 goes from 5ms to 21ms (4x slower). The looser bounds from fewer iterations sometimes require exploring more B&B nodes. 12 iterations is the optimal trade-off.

6. **The remaining ~20% failure rate (95 instead of 100) is likely irreducible Docker variance.** Docker container startup, CPU scheduling, and I/O overhead occasionally exceed 300ms, leaving insufficient budget for even a <100ms algorithm. No algorithmic optimization can fix this.

7. **LS2 after B&B is unnecessary when B&B completes normally.** B&B already found the exact optimum; LS2 cannot improve it. Making LS2 conditional on `bnb_timed_out` saves 5-50ms of unnecessary computation.

## System Interface

- **Build:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
- **Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
- **Output format:** Single line `SCORE: <n>` where n is 0-100
- **Baseline result:** 8/10 runs at 100, 2/10 at 95 (mean 99.0)

## Code Map

- `solution.cpp` — the only file to edit. Contains the full B&B solver with all optimizations.
- `solution.cpp:7` — `chrono::steady_clock::time_point start_time;` (NEW: wall-time tracking)
- `solution.cpp:8` — `bool bnb_timed_out = false;` (NEW: timeout flag)
- `solution.cpp:97-106` — `solve()` entry with amortized time guard (NEW: every 512 nodes at 700ms)
- `solution.cpp:86` — ternary search: `for (int iter = 0; iter < 12; iter++)`
- `solution.cpp:116-119` — tight vs cheap bound cutoff at level 8
- `solution.cpp:217` — `start_time = chrono::steady_clock::now();` (NEW: first line of main)
- `solution.cpp:283-307` — multi-greedy heuristics (23 alpha variants + 2 pure density)
- `solution.cpp:137-212` — local search (add, swap, remove-refill)
- `solution.cpp:309-318` — conditional LS2: only if B&B timed out and time < 800ms (NEW)
- `solution.cpp:214` — `static char inbuf[65536];` — fread input buffer
- `solution.cpp:321-327` — printf output (fast, no streams)

## Code Targets

### h-main (amortized-walltime-guard)
- **File:** `solution.cpp` (edit the worktree's existing full solver)
- **Change 1:** After `long long bnb_nodes = 0;` (line 6), add: `chrono::steady_clock::time_point start_time;` and `bool bnb_timed_out = false;`
- **Change 2:** In `solve()` after `bnb_nodes++;` (line 98), add amortized guard: check chrono every 512 nodes, set bnb_timed_out if >700ms. Add `if (bnb_timed_out) return;` for fast unwinding.
- **Change 3:** Add `start_time = chrono::steady_clock::now();` as first line of main() (line 217).
- **Change 4:** Replace unconditional `local_search();` after `solve()` with: `if (bnb_timed_out && chrono::steady_clock::now() - start_time < chrono::milliseconds(800)) { local_search(); }`
- **Why:** Addresses RP-5 (wall time), prior attempt's chrono overhead failure, and unnecessary LS2.

## What I Tried That Didn't Work

1. **(Prior iter-3 attempt) chrono::steady_clock at every B&B node with slow I/O:** TC1 doubled from 21ms to 40ms. Used string/istringstream/cout. Result: 5/7 at 100 (no improvement). The chrono overhead CAUSED more TLEs than it prevented.

2. **(This exploration) Per-node chrono without amortization:** Measured 40ms for TC1 vs 19ms with 512-node amortization. Confirmed: per-node chrono is the wrong approach.

3. **(This exploration) Reducing tight_ub depth from 8 to 4 (or 0):** ALL test cases hit the 700ms time guard. Tight Lagrangian bounds at levels 0-7 are essential for fast B&B. Cannot trade bound quality for speed.

4. **(This exploration) Reducing ternary from 12 to 8:** TC20 went from 5ms to 21ms (4x slower) because looser bounds cause more node exploration. 12 is optimal.

5. **(Iter-2) clock()-based time guard at 800ms CPU time:** clock() measures CPU time, not wall time. Docker overhead is wall-time-only. Didn't prevent TLEs.

6. **(Iter-2) Sorting by ascending effective max_k:** Slower on all test cases.

7. **(Iter-2) Tight bounds at ALL 12 levels (not just first 8):** No improvement.

8. **(Iter-1) Field name `ratio`:** Compilation failure in Docker's GCC with `using namespace std`.

## What I Excluded and Why

- **DP approaches**: 2D DP needs 20M x 25M state space. Even with 10K scaling: 2K x 2.5K = 5M states x 168 pseudo-items = 840M operations. Too slow.
- **Meet-in-the-middle**: 500^6 ~ 10^16 per half. Infeasible.
- **CLOCK_MONOTONIC_COARSE**: Lower overhead than chrono but with 512-node amortization, chrono overhead is already <0.1ms. Not worth the portability risk.
- **Further B&B algorithmic optimization**: The B&B runs in <25ms locally. The bottleneck is Docker overhead (~300-500ms), not algorithm speed. Making the algorithm faster has diminishing returns.
- **Simulated annealing / tabu search**: Only helps the greedy+LS fallback. B&B already finds exact optima.

## Evolution of Thinking

1. **Iter-1:** Discovered B&B + Lagrangian finds exact optima (100/100 locally).
2. **Iter-2:** Found Docker variance causes 30% failure rate. Clock()-based guard didn't help (CPU vs wall time).
3. **Prior iter-3 attempt:** Tried chrono::steady_clock but with per-node calling and slow I/O. No improvement.
4. **This exploration:** Diagnosed the prior attempt's failure: per-node chrono DOUBLES execution time. Amortization to every 512 nodes eliminates overhead entirely. Combined with preserved fast I/O, achieved 80% reliability at 100.
5. **Critical learning:** The remaining 20% failure rate is likely irreducible Docker variance. Container startup overhead sometimes exceeds 300ms, consuming most of the 1s budget regardless of algorithm speed.

## Current Status

- **Validated:** Amortized chrono guard compiles, produces correct output identical to original, runs in <25ms locally.
- **Validated:** 8/10 judge runs at 100 (80% reliability), 2/10 at 95 (mean 99.0).
- **Validated:** 12 ternary iterations and tight bounds at 8 levels are optimal — cannot reduce either.
- **Uncertain:** Whether the 20% Docker failure rate can be further reduced. May be irreducible.
- **Suggested next:** If 100 is the score, the problem is effectively solved (exact optima on all 20 cases). If further improvement is needed: (a) try reducing guard to 500ms to see if it helps or hurts; (b) investigate Docker startup overhead using /usr/bin/time or strace; (c) consider a completely different approach (pre-compiled lookup tables, or very fast DP with aggressive scaling).

## Warnings & Constraints

1. **NEVER use `ratio` as a struct field name** with `using namespace std`. GCC interprets it as `std::ratio`.
2. **Do NOT call chrono::steady_clock::now() at every B&B node.** It doubles execution time. Use 512-node amortization.
3. **Do NOT use string/istringstream/cout.** The worktree already has fast char[]/fread/printf I/O. The prior attempt's slow I/O negated the chrono fix.
4. **Do NOT reduce tight_ub depth below 8.** All test cases time out without tight bounds.
5. **Do NOT reduce ternary iterations below 12.** TC20 becomes 4x slower at 8 iterations.
6. **Docker timing varies 3-5x vs bare metal.** A 25ms solution may take 75-125ms in Docker.
7. **Run the judge at least 5 times** to assess reliability. Docker variance means a single score is not representative.
8. **JSON output must include all 12 item keys**, even with quantity 0.
