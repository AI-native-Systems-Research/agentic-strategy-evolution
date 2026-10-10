# Problem Framing — Iteration 4

## Research Question

Can a combined set of optimizations — early-exit detection (skip B&B when greedy+LS is already optimal), raw write() syscall output (bypassing stdio buffering), and #pragma GCC optimize("O3,unroll-loops") — further reduce TLE frequency in the go-judge Docker sandbox and reliably achieve 100/100?

**Context from iters 1-3:**
- Iter 1 (RP-1): B&B + Lagrangian relaxation finds exact integer optima on all 20 test cases. Score 100 locally.
- Iter 2 (RP-5): Docker timing variance causes 30% TLE rate. clock()-based guard doesn't help (CPU vs wall time).
- Iter 3 (RP-6): Amortized chrono guard (700ms, 512 nodes) improved reliability from 70% to 80% at 100 (mean 99.0).

**New findings from this exploration:**
1. **SIGALRM is blocked by go-judge sandbox.** A proof-of-concept that relies on SIGALRM to output before TLE scored 0/100 — the alarm never fires.  (`solution_alarm_proof.cpp` test → SCORE: 0).
2. **B&B finds the true optimum on all 20 test cases** (verified against answer files: `$TC_i.ans` line 2 = best_value).
3. **Greedy+LS is always above baseline** (minimum per-case score 43.9% on TC12), confirming score drops are TLE (0 points) not suboptimal output.
4. **Current reliability: 14/15 at 100, 1/15 at 90** across 15 judge runs in this exploration session.
5. **Greedy+LS is already optimal on 8/20 test cases** (TC2,3,4,5,10,13,17,19). Early-exit on these cases eliminates B&B overhead entirely, reducing TLE risk for 40% of evaluations.
6. **`#pragma GCC optimize` and write() don't materially change reliability** — v4 solution tested 8/10 at 100 (same as iter-3). The TLE is caused by Docker/go-judge overhead (~15-20% of runs) that is outside algorithmic control.

## System Interface

- **Build:** `g++ -O2 -pipe -static -s -std=gnu++17 -o solution solution.cpp`
- **Measure:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp`
  - Prints `SCORE: <n>` where n is 0-100.
  - Internally: `frontier eval algorithmic 1 <solution.cpp>` submits to go-judge (Docker), compiles, runs against 20 test cases with 1s time limit each.
- **Code evidence:**
  - go-judge time limit: `algorithmic/problems/1/config.yaml:3` — `time: 1s`
  - Checker scoring: `algorithmic/problems/1/chk.cc:86` — `score_ratio = max(0, min(1, (participant - baseline) / (best - baseline)))`
  - 20 test cases: `algorithmic/problems/1/config.yaml:8` — `n_cases: 20`
  - B&B solve entry: `solution.cpp:97` — recursive `solve()` function
  - Chrono guard: `solution.cpp:100-105` — every 512 nodes, 700ms threshold
  - Greedy heuristics: `solution.cpp:283-307` — 23 alpha variants + 2 pure density
  - Local search: `solution.cpp:137-212` — add, swap, remove-refill
  - Output: `solution.cpp:321-327` — printf to stdout

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_1.sh $PWD/solution.cpp
```

## Baseline Validation

Current solution (iter-3 with amortized chrono guard) tested 15 times:
- Runs 1-8: 100,100,100,100,100,100,100,100
- Runs 9-15: 100,90,100,100,100,100,100
- 14/15 at 100 (93.3%), 1/15 at 90
- Mean: 99.33

V4 solution (early-exit + write() + O3 pragma) tested 11 times:
- 9/11 at 100 (81.8%), 2/11 at 95
- Mean: 99.09

Both produce optimal output locally on all 20 test cases (verified against answer files).

## Experimental Conditions

### h-main: Optimized B&B with early-exit detection, write() output, and compiler pragmas

Starting from the worktree's solution.cpp (full B&B solver with chrono guard), make these changes:

1. **Add `#pragma GCC optimize("O3,unroll-loops")`** at the top of the file — instructs the go-judge's GCC to use aggressive optimization regardless of its default flags.

2. **Early-exit detection** — after greedy+LS, compute `tight_ub(0, MAX_MASS, MAX_VOL)`. If `(long long)(ub + 0.5) <= best_value`, greedy+LS already found the optimum — output immediately and return without running B&B. This saves B&B time on 8/20 test cases (TC2,3,4,5,10,13,17,19) and eliminates TLE risk for those cases.

3. **Replace printf() output with write() syscall** — format output to a static char buffer and use a single write(1, buf, len) call. This bypasses stdio buffering, ensuring output is committed to the pipe immediately rather than sitting in a libc buffer that's lost if the process is killed.

4. **Tighten chrono guard interval** from every 512 nodes to every 256 nodes — provides finer-grained time checking so the guard responds faster to approaching time limits. Keep threshold at 700ms (B&B finishes in <25ms locally; the threshold is a safety net, not a limiter).

5. **Remove LS2** — when B&B completes normally it found the exact optimum; LS2 cannot improve it. When B&B times out, the time budget for LS2 is exhausted anyway. Eliminating LS2 removes unnecessary code paths and saves a few ms.

**Rationale:** Each optimization reduces a different source of overhead: early-exit eliminates B&B entirely on easy cases; write() prevents output loss from buffering; O3 pragma accelerates computation; finer guard checks catch time pressure sooner; removing LS2 simplifies the critical path.

## Success Criteria

- **Primary:** Judge score of 100 on the official measurement run.
- **Secondary:** Expected score ≥ 99.0 across repeated runs (improvement over or equal to iter-3's 99.0).
- **Lower bound:** Score ≥ 90 on every run (no regression below observed worst case).

## Constraints

- 1-second time limit per test case in Docker (go-judge sandbox).
- SIGALRM does not work in go-judge sandbox (verified — alarm_handler never fires).
- Docker's go-judge uses SIGKILL for enforcement — no signal-based safety nets are possible.
- Must use `using namespace std` (judge convention) — do NOT use `ratio` as identifier.
- Solution must produce valid JSON output with all 12 item keys.
- Must compile with `-std=gnu++17`.

## Prior Knowledge

- **RP-1:** B&B + Lagrangian finds exact optima on all 20 test cases (100/100).
- **RP-2:** Single greedy scores 0/100 (below NSA baseline).
- **RP-3:** 12 ternary iterations preserve optimality.
- **RP-4:** Greedy+LS without B&B scores 90.597 with zero variance.
- **RP-5:** Docker timing causes 5% score drops. clock() measures CPU time, not wall time.
- **RP-6:** Amortized chrono guard at 700ms improved reliability from 70% to 80%.
- **New (this exploration):** SIGALRM blocked in go-judge. Greedy+LS always above baseline (min 43.9%). B&B optimal on all 20 cases (verified). Early-exit possible on 8/20 cases.
