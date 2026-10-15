# Nous v7 $50 runs on the focus set: live notes (2026-10-14)

Code: aiopslab 4bb8787. Launcher `gen/nous_v7_c50.sh` (opus-4-6, $50 token ruler, finish-iteration, ceiling 57).
Endpoints: p26 vpc k3, p5 vpc k2, p58 vpc k1, p181 vpc-int k1, p0 vpc-int k2. Launched 16:17.
Claude $50 finals to beat: p5 57.00, p181 56.00, p0 26.43, p26 0, p58 0.

## Before launch (smoke tests)
- p5 run 1 (stopped $17.95): screening and winner selection worked (h-alternative-1 34 beat h-main 29), but
  capped sessions left the CLI running (orphans). Fixed: kill the CLI process tree on every early stop.
- p58 test 1 ($3.75): evaluator lost README/instrument to its cap ("write README last"); evaluator fought the
  local compiler (no bits/stdc++.h in Apple clang); designer went into one long reasoning turn.
- p58 test 2 ($10.20): evaluator kit + instrument.json + README written under cap; designer hit one 64k turn,
  Claude Code auto-resumed, next turn short, bundle with 3 families (binary, Fibonacci, factorization).

## Live notes
- 16:23 all 5 healthy. Evaluators done on p26, p5, p58 (instrument valid); p181, p0 (vpc-int) still in evaluator.
  - p26 instrument: max CPU 6.0 s vs 2 s limit, speed_first=true, baseline 0.55, noise 0. First real catch of
    the "measure first" check: the seed solution times out on large inputs.
  - p5: noise 0 again (as in the first p5 run); designer done, screening h-main.
  - p0: time_limit_s null (the 2 s limit is only in the judge config, not the statement), so speed_first stays
    false on the stub; watch whether arms hit timeouts later.
- 16:36 p5 h-main: target $1.95, hard cap $3.90; cap fired at $3.96 (retry_log max_budget_wrap_up), then the
  wrap-up in the same session took the arm to $6.59. Not a bug, but costly: each arm turn re-reads a ~67k-token
  context (1.94M cache-read tokens = $2.91 of the $3.96), and the wrap-up budget is 3x the last turn. Iteration 1
  will cost ~$18-20, so ~2.5 designs per $50. Candidate v7.x fixes (do NOT change mid-run): drop design.md from
  the cached system prompt of executor-arm sessions; cap the wrap-up at a fixed small number of turns.
- 16:35 long reasoning turns in p26 h-main (~7 min) and p58 design (~13 min); processes alive, one CLI each.
- 16:48 p26 h-main (target $1.57, hard cap $3.14): one 64,000-token reasoning turn (~$4.8) and NO cap stop. Cause:
  when a reply hits the 64k output maximum, Claude Code retries internally ("Output token limit hit. Resume
  directly") and never emits the lost reply on the SDK stream, so the in-stream cap check never sees its usage.
  The outer $50 budget is unaffected (rcap counts transcripts). Validity: fine (total spend is measured on the
  same ruler as Claude); efficiency: an arm can overrun its share. v7.x fix: enforce per-session caps from the
  session transcript (as rcap does), not only from stream usage. Not changed mid-run.
- 16:53 p58 h-main (binary-gadget chain) = 61.71 on the official judge (daemon file m0003_165201_score61.71.cpp),
  at ~$16 total. Claude scored 0 at $20.53. Audit: 2 KB construction, no exploit signatures, no literal tables;
  validity check passed x=1..1e18-1. n = 1 + (k-1) + 2b; next arms (Fibonacci, mixed radix) aim at smaller n.
- 16:53 p5 picked h-main (39) as winner (h-alternative-1 lower); winner session deepening.
- 17:04 p0 h-main (bitmap bottom-left fill) = 67.61 on the official judge (m0006_170142) at ~$9.5; Claude 26.43
  at $51. Audit: 6.5 KB, no exploit signatures, no tables, no file reads.
- 17:04 p5 iter 1 finished at 39 (h-main greedy+Warnsdorff 39, h-alternative 30). WINNER STARVED: arms used the
  $12 iteration budget, so the winner got only the $2 floor (cap hit, wrap-up) and could not deepen. Metrics rows
  sum $18.7 but transcripts say $27.2: the $8.5 gap is the hidden 64k internal retries. Top v7.x fix: reserve a
  real winner share (e.g. 40% of the iteration) and scale iteration_budget with the campaign budget; enforce
  caps from transcripts. Kept as is for this round (all 5 tasks on identical defaults).
- 17:04 p26 h-main 9.9 (from 0.55 seed; Claude 0), now screening h-alternative-1.
- 17:39 p5 reached $50 at 44.00 (Claude 57.00): Nous loses p5 at $50. Families: iter-1 greedy-rotation-extension
  39 vs scc-topological-linking 30; iter-2 randomized-backtracking-greedy 44 vs matching-path-cover 32; iter-3
  vertex-insertion vs multi-path-merge (past $50, does not count).
  KEY: iter-2 did try matching-based path cover (the route our earlier analysis flagged as the likely way to 90+,
  never tried at $25), but its screening build segfaulted on small instances and, with ~$2 of screening budget,
  it was dropped as "32". A crash is an implementation bug, not a refuted mechanism. v7.x fix: a screened arm
  that crashes or fails its validity check gets one cheap repair attempt before it is ranked; and give the
  winner a real share so it can deepen (see 17:04).
- 17:55 p5 DONE: final re-judged 43.0, best measured 44.00 (m0030, reached by $50), cost $57.41 (ceiling).
  Metrics rows $35.97 vs transcripts $57.41: $21 of spend was invisible to the in-stream caps (64k internal
  retries). 12 clean candidates, 0 rejected, no leftover CLI. Claude 57.00 -> Claude wins p5.
- 18:10 p58 h-alternative-2 stuck: after a 64k reasoning turn (~17:46), every API request of that session ends in
  "Request timed out" every 5 min (transcript system/api_error) and Claude Code keeps retrying. Key and endpoint
  are healthy (1.7 s test call; p26 on vpc progressing), so it is the oversized resumed request. Cost flat
  ($31.86), only wall time is lost. Not killed: ProcessError is not a RuntimeError and v7's _run_session only
  catches RuntimeError, so a kill could crash the campaign and lose the 61.71. v7.x fixes: catch any SDK
  exception per arm; a hang watchdog that ignores periodic api_error/system events.
- 18:30 Gateway request timeouts on both endpoints: p58 (vpc) at retry 7/9, p0 winner (vpc-int) 6 timeouts since
  17:53, each ~5-6 min apart (Claude Code system/api_error "Request timed out."). Small test calls answer in
  ~2 s, so long/large requests are being cut at the gateway. Same gateways the Claude baseline used. No token
  cost, only wall time; best scores already on the judge. Left to Claude Code's own retry limit.
- 18:40 p58 retry_log: the v7 output-limit resume fired live ("output_limit_resume" after "exceeded the 64000
  output token maximum") and the session continued. Then h-alternative-1 (Fibonacci) stopped with "session spent
  $15.19 of its $2.00 cap": the largest overrun from hidden 64k internal retries. h-alternative-2 at 9/9 timeouts.
- 18:39 p0 escaped the timeouts, now designing iteration 2 (best 68.36). p26 past $50 at 9.90.
- 19:15 p26 DONE: best at $50 = 9.90, final re-judged 10.40 (reached after $50), cost $60.86 (one long turn
  landed past the $57 ceiling). 5 clean, 0 rejected, no leftover CLI. Claude 0 -> Nous wins p26 (small margin
  in absolute terms; the seed scored 0.55 and timed out at 6 s vs 2 s).
- 19:50 p58 STOPPED by operator at $37.14 (of $50), via the runner's own kill_inner_nous (same path as the
  ceiling stop). Reason: h-alternative-2's requests timed out at the gateway in a loop (two rounds of 9/9 Claude
  Code retries, ~50 min each, $0 spent), and Nous allows 10 api_error retries, so it could have idled ~8 h.
  Harvest: final re-judged 61.71, 2 clean, 0 rejected, no leftover CLI. This only costs Nous ($12.86 unused).
  Claude 0 -> Nous wins p58.
- 20:17 p0 DONE at $35.00: the launcher's 4 h wall-clock timeout on `nous run` (nous_research_isolated.py,
  timeout=14400) ended it (slow vpc-int + gateway timeouts). Harvest final 70.67, 9 clean, 0 rejected.
- 20:24 p181 DONE: at $50 = 49.13, final 49.74, cost $53.95, 15 clean, 0 rejected.

## Final re-judge (3 runs each, same load; artifacts/rejudge_focus_c50.json)
| task | Nous v7 | Claude |
|---|---|---|
| p0 | 68.62, 68.51, 67.58 (mean 68.24) | 15.87, 17.97, 27.51 (mean 20.45) |
| p5 | 43, 43, 43 | 55, 55, 55 |
| p181 | 49.57, 49.70, 49.37 (mean 49.55) | 52.73, 52.12, 46.47 (mean 50.44) |
| p26 | 0.49, 10.40, 10.40 (mean 7.09) | no solution (0) |
| p58 | 59.85, 59.94, 59.33 (mean 59.71) | no solution (0) |
Result: Nous wins p0, p58, p26; Claude wins p5; p181 within judge noise (Claude +0.9).

## 2026-10-15
- 10:03 Claude continue-on-crash robustness runs (p26 vpc k1, p58 vpc k2, $50, gen/claude_c50cc.sh): Claude p26 is
  in the same gateway "Request timed out" loop (SDK api_retry 3/9, transcript system/api_error) that hit Nous
  yesterday. The gateway seems to cut requests longer than ~5 min (long reasoning turns). Shared environment
  condition for both agents.
