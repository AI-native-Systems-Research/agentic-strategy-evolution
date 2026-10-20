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
