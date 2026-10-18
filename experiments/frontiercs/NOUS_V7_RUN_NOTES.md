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

## Nous v8 runs (2026-10-15)
- 11:20 p5 v8 launched (vpc k3, $50, --wall-hours 24, code 0c1c0b2). Evaluator baseline officially scored 28
  at ~$1 and 39 at ~$4 (v7 needed a full arm and ~$12 for 39). Found: judge profile said "assumed 1 s" during
  the evaluator although the statement says 4 s (limit was only read from instrument.json). Fixed in 26bc363
  (parse "Time Limit: N second" from the statement). Restarted p5 at $4.08 so all v8 tasks run one version.
- 11:29 p5 v8 relaunched on 26bc363; judge profile now: time limit 4.0 s from the statement.
- 11:50 p5 v8 smoke #2 stopped at $12.35 (best 41 = evaluator baseline). Findings: (a) the evaluator spent its
  whole $6 hard cap on this Mac's broken toolchain (Apple clang cannot find <vector> even outside the sandbox;
  only /opt/homebrew/bin/g++-15 works) and wrote no instrument.json/README; (b) that squeezed the 3 screening
  arms to a $1.77 target ($3.54 hard); h-main hit its hard cap without writing result.json, and its $1 repair
  turn did too. Caps themselves worked (metrics $11.50 vs transcripts $12.26). Next: official-first evaluator
  (orchestrator measures noise 3x and writes instrument.json), at most 1 h-alternative with a $4 arm floor,
  orchestrator-built result.json from official measures in the session window.
- 12:41 p5 v8 smoke #3 on 2039cfd (vpc k3): official-first evaluator ($2 target; orchestrator measures noise 3x
  and writes instrument.json); max one h-alternative; $4 arm floor; iteration-1 evaluator credited back;
  results rebuilt from official measures (attributed by submit time, incumbent re-measures ignored; a judge
  that never answered is no score). measure_command in campaign: bash fmeasure_p5_v8c50.sh $PWD/solution.cpp.
- 12:57 smoke #3 stopped at ~$6: evaluator capped before saving its baseline, so noise was measured on the 0 seed and arms started from it. Fixed (best official measure becomes the baseline; 0-score noise = unknown). Smoke #4 launched on bcced84.
- 13:32 smoke 4 (p5 $16, best 43) showed the competing family skipped by a $0.14 margin (cap overshoot). Fixed ($1 overshoot margin per waiting arm). Relaunched p5 (vpc k3), p0 (vpc-int k1), p181 (vpc-int k2) on ecc98b1. p58/p26 follow on vpc k2/k1 when the Claude robustness runs end.
- 14:06 Found: the committed baseline was the evaluator's saved patch even when its best official measure was
  higher (p0 45.98 vs 63.51; p5 26 vs 40), so arms started from the worse version. Fixed: the baseline is
  always the best official measure (> 0). I also stopped p5 thinking its official log mixed in aborted runs;
  it did not (the launcher starts a fresh log per run), so that stop was unnecessary. All runs relaunched on
  486d822: p5 vpc k3, p58 vpc k2, p0 vpc-int k1, p181 vpc-int k2; p26 starts on vpc k1 when
  Claude p26 (continue-on-crash) ends. Claude p58 continue-on-crash ended 0 at $48.55 (stopped while stuck).
- 14:25 Claude continue-on-crash robustness runs done: p26 0 at $47.41 (4 CLI crashes resumed), p58 0 at $48.55
  (2 crashes resumed); neither ever submitted a solution. Both were stopped by me with < $3 left while stuck in
  gateway "Request timed out" retries. Caveat: today's gateway timed out long requests far more than yesterday.
- 15:03 p58 stopped at $20.71 (0): its designer hit the $8 cap mid-reasoning twice, wrote no bundle, iteration 1 abandoned (design_incomplete). Fixed: fallback one-arm design. p58 relaunched on 0e7ae60; other tasks keep running on 486d822 (the fallback only matters when a design fails).
- 15:24 Found: arms' self-written result.json can understate their best official measure (p181 alt 49.55 official vs 12.46 written) so the wrong arm won. Fixed in 125df97 (result follows the judge). Restarted p181, p0, p26, p58 on it; p5 continues on 486d822 (its winner picks were correct).
- 15:30 p5 v8: 58.00 at $49.69 (judge file m0042_152900_score58.00.cpp; clean: no exploit signatures, no tables, no file reads; 13.8 KB). Came from iteration 3 (explore after the exploit iteration plateaued at 55). Claude 57.00.

## 2026-10-16 runs (repeats and effort work)

- 08:19 p58 r2 (vpc k3) and p181 r2 (vpc k1) on 0d858f5. p181 r2 finished 47.67 at $50 (both families
  screened). p58 r2: every session had a 64k reply, no submission; stopped at $29.44 for the floor fix.
- 10:21 p58 r3 (vpc k1) on 85ecf14: arm got $9.74 but both replies were 64k thinking, no submission; stopped at
  $26.31. 10:34 p26 r2 (vpc k3): 10.14 at $50 (first run 29.61); long replies again.
- 12:20 probes: thinking budget ignored on opus-4-6/5/5-5 (vpc and vpc-int); effort works.
- 14:56 p58 r4, p26 r3 (vpc), p5 r2 (vpc-int) on 2c2094c (effort ladder). Stopped at 15:20 ($11.42, $7.57,
  $16.34; p5 best 39.0) after p5 r2 skipped its second family because of the reply-sized floor (reverted in
  9cf6a43) and a replay showed the ladder's first-session rule would change p0. Their spend does not count.
