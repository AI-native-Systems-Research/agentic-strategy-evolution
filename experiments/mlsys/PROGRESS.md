# MLSys controlled experiments: progress log

Times are local (EDT).

## 2026-10-19

- 18:40 Branch `mlsys-exp` from `main` (`decbde7`). Nous `main` installed in its own venv (`.venv-mlsys`,
  claude-agent-sdk 0.2.168). Mac kept awake with `caffeinate`.
- 18:55 pd-disagg answer key: our own BLIS sweep (BLIS `4e88b20`, 40 rate points x 5 seeds x AL/AD = 200 runs, plus
  600 held-out runs on 3 unseen workload/topology configs). Result: ITL = alpha/(1-lambda W), W fit on rates 2-60,
  max error 1.12% (AL) / 0.65% (AD) on 2-60; overpredicts at high rate: AL +14.3% at 100, +28.3% at 120, +65% at 150;
  AD first >10% at 110. AD TTFT > AL TTFT at every rate; AD ITL < AL ITL at every rate >= 2. Seed std ~0.001 ms.
  Independently reproduces the original campaign's "+29% at rate 120".
- 19:05 Debugging task: BLIS snapshot at `4d75db2` (parent of fix `d8271ee`), single-commit repo with no history
  (the fix cannot be found via git). Bug reproduces from the CLI: total_output_tokens 114630 with KV=600 vs 105082
  with a large KV, same 200 requests. Hidden checks (6 preemption cases + 2 no-pressure regression cases): buggy build
  fails 6/8, upstream fix passes 8/8. Upstream test fails on the buggy build (as it should). Self-review caught one
  invalid hidden case (PD cluster dropped 148 requests even on the fixed build); replaced.
- 19:15 blis-search answer key: our own exhaustive sweeps (1800 configs each) for the main config (qwen3-14b, rate 100)
  and two held-out configs (llama-3.1-8b rate 100, qwen3-14b rate 50). Exact 4-objective hypervolume (same objectives
  and reference point as the original campaign). Reference: random search with 200 evals reaches 0.944 mean HV
  ratio (min 0.855) on the main config. Trade-off facts T1-T4 locked in `keys/search/facts.json`.
- 19:20 Task prompts and shared output contract written (`tasks/`). Keys + prompts committed before any run.
- 19:55 Oracle written (`oracle/`): common checks (contract, C1 evidence, R1/R2 repro in a fresh copy, V4 forbidden
  access from transcripts, S1-S3 stopping, E1 cost), per-task oracles, and the color grid renderer.
  Self-tests, all before any arm run:
  - dbg: upstream fix -> D1-D6 all pass, O1 true; empty patch -> all fail; fake test-only patch -> hidden checks and
    upstream test fail. Two oracle bugs found and fixed: (1) `bash -lc` picked up an old Go 1.20 at /usr/local/go,
    which made every suite fail; now pinned to /opt/homebrew go 1.24 with GOTOOLCHAIN=local; (2) diff parsing for
    D5/D6 split on the wrong marker.
  - pd: a correct answer -> O1 true, and a deliberately wrong claimed ITL (25.0 at rate 120; truth 19.17) is caught as
    a false claim by re-measurement in a clean BLIS; "formula holds everywhere" -> O1 false; wrong sign
    (underpredicts) -> K2 false.
  - search: a 200-eval random search scored through the oracle -> HV 0.941 (our offline reference 0.944), 200
    evaluations counted by the wrapper, 21 s. Config lookups score against our exhaustive sweep, not the arm's
    reported metrics.
- 20:20 Harness (`harness/`), identical for every arm:
  - isolation: fresh single-commit repo copy per run; macOS `sandbox-exec` profile with no internet (only the localhost
    LLM proxy), no reads of keys/oracle/other runs/original checkouts/Desktop/Downloads/~/.claude, writes only in
    the run dir + build caches. Tested: reading keys, the fixed checkout, ~/.claude and Desktop all fail; `curl
    github.com` and `git clone` of the public repo fail; writing outside the run dir fails; BLIS builds and runs.
  - each run has its own CLAUDE_CONFIG_DIR (own transcripts; no user settings or memory) and own pass-through proxy
    (request bodies unchanged; no thinking stripping).
  - cost: one ruler over the run's transcripts. Self-review caught a pricing bug (opus-4-6 is $5/$25 per M, not
    $15/$75); fixed, and the meter now equals the CLI's own total_cost_usd exactly on opus-4-6 and sonnet-4-6.
  - Nous: `main` + one opt-in change, `--gate-mode agent`: the continue gate follows the continue-gate summary's
    `recommendation` (stop/continue). Default behavior unchanged. 6 new tests, 310 existing related tests pass, no
    live LLM calls. Nous runs from a pinned copy at ~/mlsys_runs/nous (outside the denied folders).
  - Nous executes in throwaway worktrees, so after the campaign one short packaging session (counted in Nous's cost)
    applies the campaign's own patches and writes final/answer.json from its report. It may not run new
    experiments or change conclusions.
- 20:43 Pilot launched: debugging task, one run per arm (nous_prompt on key 1, l2 on key 2, nous on key 3).
  Audit after 5 min: all three arms on claude-opus-4-6 (Nous design phase; execute will be Sonnet 4.6 by default),
  same CLI 2.1.301, tools working inside the sandbox; subagent (Explore) transcripts are captured and also on
  opus-4-6, and included in cost. One HTTP 400 per arm at CLI startup (CLI probe), then normal 200s.
- 19:47 tick: pilot (dbg x 3 arms) running, all in session/iteration 1, no crashes, $3.57 total.
- 19:52 tick: pilot running, all arms in iteration 1 (Nous still in DESIGN), $6.67 total, no crashes.
- 19:57 tick: pilot still in iteration 1 for all arms, $10.51 total, no crashes.
- 20:02 tick: Nous finished DESIGN of iter 1 (bundle validated), now EXECUTE; l2/nous_prompt still in session 1. $13.63 total.
- 20:04 Pilot 1 stopped and discarded ($15.60). Harness bug found by self-review: the sandbox denied reads
  of the whole runs/ tree to block access to other runs, but git needs to read parent directories, so
  `git worktree add` and `git stash` failed inside the sandbox. This killed Nous's iteration 1 (worktree add, exit 128)
  and also broke git stash for nous_prompt (L2 had not hit it yet). Fix: deny only sibling task/arm/rep dirs, keep
  parents traversable. Re-tested: worktree add, stash, build OK; sibling runs and keys still unreadable. Pilot
  data archived under keys/_archive (unreadable to agents). Relaunching the pilot.
- 20:09 Pilot 2 running (dbg x 3 arms, rep1) via harness/queue.py (one cell per key slot). Two small harness
  fixes: queue launcher (zsh loop bug never started the first relaunch), and the cost meter now skips the CLI's
  zero-token "<synthetic>" error placeholders (they carry no usage). An old pilot-1 L2 CLI process had briefly kept
  writing into a stale rep0 dir after its proxy was killed; it is gone and the stale dirs were removed.
- 20:09 tick: pilot 2 running (3 arms, iteration/session 1), no errors.
- 20:14 tick: pilot 2 still in iteration 1, no errors.
- 20:19 Pilot 2, L2 finished: O1 true. One session, $3.75, 10.5 min, declared done. Verified by hand: its
  source change is the upstream fix in substance (remove the inline TotalOutputTokens++ in executeBatchStep, count
  ProgressIndex - len(InputTokens) once at completion; 2 non-test lines), plus a 69-line regression test that fails
  on the buggy code. Upstream hidden test, full suite, and all 8 hidden checks pass; 5/5 claims backed and
  reproduced. Note: this bug may be too easy to separate the arms (a strong baseline solves it in one session).
- 20:19 tick: L2 done; nous_prompt and Nous running.
- 20:24 tick: nous_prompt and Nous still running, no errors.
- 20:29 tick: Nous in EXECUTE iter 1 (worktree OK, Sonnet executor); nous_prompt session 1.
- 20:29 Pilot 2, nous_prompt finished: O1 true, one session, $5.67, 21.5 min. Verified by hand: same fix as
  upstream (10 non-test lines, incl. the zero-output guard), 68-line regression test; all hidden checks pass, 6/6 claims
  backed and reproduced. Both baselines solve this bug in one session.
- 20:34 Nous pilot in findings gate of iter 1. Started smoke cells pd/nous_prompt/2 and search/l2/2 on free slots 3,4 to exercise those task paths (they count as real runs).
- 20:35 Pilot 2, Nous: iteration 1 done; its continue-gate summary recommended stop, and the agent gate
  followed it (gate mode works). Notable: Nous also found that the same root cause inflates AllITLs and TTFTSum
  after preemption and patched those too; this matches the separate upstream fix 320aa47. The oracle does not score
  this (pre-registered checks only); recorded as a qualitative observation. Packaging step next.
- 20:40 Pilot 2 complete. Debugging task, rep 1 (all O1 true, all checks pass):
  | arm | cost | wall | iters | non-test lines | claims backed/reproduced |
  | L2 | $3.75 | 10.5 min | 1 | 2 | 5/5 |
  | nous_prompt | $5.67 | 21.5 min | 1 | 10 | 6/6 |
  | Nous | $6.87 (opus $5.18 + sonnet $1.61 + gate calls $0.08) | 29 min | 1, agent gate said stop | 29 | 4/4 |
  Nous's fix differs in approach (subtract pre-preemption tokens/TTFT at re-queue) and also corrects AllITLs and
  TTFTSum (matching later upstream fix 320aa47); not scored, since only pre-registered checks count.
  Harness bug found: the Nous packaging session never started (--disallowedTools is variadic and swallowed the
  prompt argument). No effect on this run (Nous's planner wrote final/answer.json and edited the repo directly),
  but it would break pd/search. Fixed: prompt on stdin. Also: RUNNING markers so two queues never run the same
  cell or key.
- 20:40 Main queue launched: 24 cells (dbg reps 2-3; pd and search reps 2-4), arms interleaved by rep, on
  key slots 0-2 now and 3-4 once the two smoke cells finish.
- 20:41 tick: 5 runs live (pd nous/l2 rep2, search nous_prompt rep2, smoke pd nous_prompt/search l2 rep2).
- 20:46 tick: 5 runs live, all in iteration/session 1.
- 20:51 tick: 5 runs live, no crashes.
- 20:56 pd/nous_prompt/rep2 finished ($4.35, 17.5 min, 1 session, declared done). Its harness run_one wrote
  meta + oracle fine; the queue's "no oracle.json" was a race in my monitor. Oracle: O1 false (K1 yes, K3 yes,
  K2 no). It fit W over the whole range 1-150 and reported "holds well, max error 7.2%, S-shaped residual from
  concave step time (weight amortization)" - the mechanism is right, but it never reports a high-rate breakdown.
  Oracle parser bugs found on this answer and fixed (applies to every run; no run had been scored on pd before):
  decimals ("3.76%") ended a sentence for the phrase windows; AL-vs-AD differences like "AD ITL reduction (%)" were
  read as formula errors; "raises TTFT"/"decreases ITL" verbs missing; K4 missed "concave ... step time". Self-tests
  (good/wrong-sign/bad answers) still behave. Not changed: the pre-registered K2 criterion. Caveat to report: K2
  depends on fitting W at moderate rates (as the paper does: W is a per-request work constant); a whole-range fit
  spreads the error and can hide the breakdown.
- 20:56 tick: 5 runs live.
- 21:01 search/l2/rep2 ($3.66, 1 session): HV 0.997 main, 0.997/0.997 held-out, within 186 evals and 20 s. T-facts: scheduler near-irrelevant and GPU trade-off stated; it claims block size has 'near-zero impact' (our sweep: block 32 is on 93.5% of the front) and does not state that small KV budgets dominate. Parser fix: T2 phrase list lacked 'near-zero/marginal/tiny/insignificant' (same meaning; applied to all arms). O1 = HV>=0.95 and T>=3.
- 21:01 tick: 5 runs live.
- 21:06 tick: 5 runs live.
- 21:11 search/nous_prompt/rep2 ($5.12, 1 session): HV 0.997 main and held-out (same as L2). T-facts 0/4, checked by hand against its answer: it calls scheduler AND block size 'secondary' (block 32 is on 93.5% of our front, so not T1; 'secondary' is not 'irrelevant', so not T2), says KV has 'sharp threshold effects' (not that small KV suffices), and states TP raises throughput without naming the GPU-cost trade-off. Scored as is; no matcher change. 5/8 claims backed by evidence.
- 21:12 tick: 5 runs live.
- 21:13 search/nous/rep2: one gateway request stalled mid-stream for ~5 min (21:06-21:11); the CLI retried on its own and the run continues. Gateway stalls hit all arms alike; wall time is reported but not used for any primary result.
- 21:16 tick: 5 runs live.
- 21:20 pd/l2/rep2 ($10.55, 2 sessions): read by hand. Fits within 0.44% at rates 1-60, says the model
  "breaks down structurally at high rates": observed ITL saturates near 21 ms instead of diverging (= formula
  over-predicts), mechanism batch cap (max_num_running_reqs). AD ITL < AL ITL and AD TTFT > AL TTFT, plus a TTFT
  reversal at rate ~250. First scored O1 false because of two matcher gaps, both meaning-preserving and applied to
  every arm: K3 now accepts symbolic comparisons ("TTFT_AD > TTFT_AL"); K2 accepts "observed ITL saturates / hits a
  ceiling / grows slower than predicted" as the observed-side statement of over-prediction. Rescored: L2 O1 true;
  nous_prompt rep2 unchanged (O1 false: it reports no breakdown). Self-tests unchanged.
- 21:21 tick: 5 runs live.
- 21:22 dbg/nous_prompt/rep2 ($5.23, 1 session): O1 true (upstream test, suite, all 8 hidden checks pass). D5 false, verified by hand: its new regression test passes on the original buggy code too, so it does not catch the bug.
- 21:26 tick: 5 runs live.
- 21:31 tick: 5 runs live.
- 21:32 dbg/l2/rep2 scored (see oracle.json).
- 21:35 tick: 5 runs live.
- 21:40 tick: 5 runs live.
- 21:46 pd/l2/rep3 ($4.45, 1 session): O1 false. Read by hand: whole-range fit (MAPE 3.9%), says a linear model fits better, names the right mechanism (decreasing marginal cost, weight amortization), never reports the formula breaking or over-predicting at high rate. Oracle bug fixed: C2 re-measured derived quantities ('marginal ITL cost (us)') as if they were ITL means, wrongly counting 2 false claims; now only plain mean ITL/TTFT is re-measured. Rescored all pd runs (O1 unchanged).
- 21:47 tick: 5 runs live; independent cost+isolation audit agent running on finished runs.
- 21:50 12/27 scored, 5 running, 10 queued. $88.
- 21:52 tick: 5 runs live.
- 21:54 Independent audit (separate agent, own scripts) of the 12 finished runs:
  - Cost: our meter = independent recomputation to 0.00% on every run; = CLI's own total_cost_usd on 11/12; on
    dbg/nous_prompt/2 the CLI is $0.045 (0.9%) higher (one stream-broken request not in the transcript; meter reads
    low, never high). All successful proxy requests accounted for. Models: only opus-4-6 and sonnet-4-6.
  - Isolation: zero tool calls touching keys, oracle, hidden tests, fixed checkouts, Desktop, ~/.claude, other runs;
    no git clone/fetch/curl/wget; WebSearch/WebFetch used 0 times; denied attempts were pip install (network
    blocked) and `nous validate` (its editable install points into the denied Desktop) - same for every arm. Every ws
    has 1 commit, no remote, no d8271ee. All sandbox profiles identical apart from the run path. Task text
    identical within each task.
  - Gaps found (none exploited by any run): readable full inference-sim clones containing the fix in /private/tmp
    (blis-main, blis-pr, blis-llmdr, from earlier unrelated work) and outputs of the fixed binary there; and
    repos/blis-pd-base had full git history incl. d8271ee. Closed: moved them to keys/_quarantine_tmp (denied;
    restorable), removed blis-pd-base/.git (the oracle only uses its binary), and the sandbox now also denies all of
    repos/, launch/, tasks/, ~/swefficiency, ~/aiopslab. /private/tmp kept writable as before, for consistency.
  - Arm difference noted: Nous's SDK sessions were offered WebSearch/WebFetch (l2/nous_prompt disable them); never
    called and the network is blocked, so no effect.
- 21:55 Full scan of /private/tmp (40 dirs) for the fix: three more copies held it (blis-pr2, and my own oracle self-test dirs dbgselftest/searchselftest). Moved to keys/_quarantine_tmp. /private/tmp now has no copy of the fix; no run's transcript ever referenced any of these paths.
- 21:57 tick: 5 runs live.
- 22:02 tick: 5 runs live.
- 22:06 tick: 5 runs live.
- 22:16 Nous pd results (read by hand):
  - pd/nous/rep2 ($20.79, 88.6 min): iteration 1 succeeded and its gate said continue; iterations 2-4 each FAILED
    Nous's own schema validation (executor added fields like 'mode', 'summary_statistics' to findings.json; schema
    is unchanged from main, additionalProperties=false). This is Nous-as-shipped behavior, not a harness bug, and is
    counted as is (status crashed, S3=true). Final answer (from the report): whole-range fit R2 0.94/0.96, formula is
    convex but BLIS is concave, mechanism = weight-loading amortization; proposes a better 3-param model. O1 false:
    no moderate-range fit claim, no statement that the formula over-predicts at high rate.
  - pd/nous/rep3 ($5.41, 1 iteration, agent gate stop): says the formula UNDER-predicts AL ITL above ~100 req/s.
    That is the wrong sign (our sweep: over-predicts by +14% at 100, +28% at 120). O1 false.
  Oracle fixes found on these answers, applied to all arms, all pd runs rescored (O1 unchanged everywhere):
  C2 now only re-measures raw mean latencies (it was re-measuring R2/model-fit claims as if they were ITL values);
  K3 accepts "AD carries a TTFT penalty". pd so far: L2 1/2, nous_prompt 0/2, Nous 0/2.
- 22:16 tick: 5 runs live.
- 22:20 search/nous_prompt/rep3 ($7.16, 1 session): HV 0.997 main and held-out; T1 yes (block 32 'almost universally dominant'), T3 yes; T2 no (scheduler 'matters only in saturated regime... minor differences' - stated as minor-but-relevant, so not counted as irrelevant); T4 no (says trade-off vs KV cost, not that small KV suffices). T=2/4, O1 false. Checked by hand; no matcher change.
- 22:21 tick: 5 runs live.
- 22:26 tick: 5 runs live.
- 22:31 search/l2/rep3 ($2.59, 1 session): HV 0.995 main, held-out pass; T1 yes, T3 yes; T2 no (claims fcfs Pareto-dominates sjf, i.e. scheduler matters - contradicts our sweep, both appear ~equally on the front); T4 no (KV 'sufficiency threshold', not that small KV suffices). T=2/4, O1 false. Checked by hand. 17/27 scored.
- 22:35 tick: 5 runs live.
- 22:36 dbg/l2/rep3 scored. 18/27.
- 22:41 tick: 5 runs live.
- 22:45 tick: 5 runs live.
- 22:46 dbg/nous_prompt/rep3: O1 true, all D checks pass, $4.08. 19/27.
- 22:50 tick: 5 runs live.
- 22:51 pd/nous/rep4: iteration 1 failed in DESIGN with "JSON message exceeded maximum buffer size of
  1048576 bytes": the designer read 10 pages of the paper PDF in one Read call (1.6 MB tool result), which overflows
  the Claude Agent SDK's default 1 MB message buffer (Nous main does not set max_buffer_size). The baselines call the
  CLI directly and have no such limit. This is Nous-as-shipped behavior, so it is counted as is (not fixed mid-
  experiment; fixing it would change the Nous arm). Nous moved on to iteration 2. Noted as a Nous robustness finding
  (one-line fix for main: pass a larger max_buffer_size in ClaudeAgentOptions).
- 22:55 tick: 5 runs live.
- 22:56 pd/nous_prompt/rep4 ($4.10): O1 true. Read by hand: <1% fit at rates 1-50, breaks for AL above ~130
  (14.5% at 150; key: >10% from 100), mechanism = batch cap max_num_running_reqs (not the weight-amortization one in
  K4, so K4 false). Note: it changed --num-requests (3000) for part of its analysis, which the task fixes at 300;
  locked-parameter check V1 is not implemented, so this is recorded, not scored. Its K1/K2 claims are supported at
  the fixed 300 as well. pd now: L2 1/2, nous_prompt 1/3, Nous 0/2 (+1 running).
- dbg/nous/rep3: Sonnet executor runs go test with -timeout 300s; ~5 min between LLM calls is a long test, not a hang.
- 23:00 tick: 5 runs live.
- 23:04 tick: 5 runs live.
- 23:09 tick: 5 runs live.
