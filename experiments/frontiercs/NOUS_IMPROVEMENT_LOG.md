# Nous improvement log (Frontier-CS, opus-4-6)

Cumulative record of what we changed in Nous, why, and what it did. Newest entries at the bottom of each
section. Every Nous version is an opt-in `campaign.design_profile`; older profiles stay byte-identical
(checked before each commit). Budgets: research $50, algorithmic $25 (Claude's real algorithmic spend was
~$25-30). One cost ruler for everyone: tokens x $15/$75/$18.75/$1.50 per M, one count per reply.

Dev tasks for the improvement loop: grammar_fuzzing (gf), p0, p5. Final runs of the chosen version: p0, p5,
p47, gf, llm_router. Caveat for the paper: the dev tasks are also reported tasks, so tuning Nous on them
partly fits it to the benchmark.

## 1. Versions

| version | profile | commit | change | why (evidence) |
|---|---|---|---|---|
| v1 | `standard` | tag `nous-v1-pre-lightweight` | original Nous | baseline; design took ~61% of spend (~$14 / 63 turns per design) |
| v2 | `lightweight` (first cut) | a598468 | 30-turn design, 1-3 focused arms, per-arm refine loop | cut design overhead |
| v3 | `lightweight` | 68121f7, ca49a72 | design-only designer that builds on the handoff; turn-limit wrap-up (resume, not restart); executor writes `handoff_update.md`; agents use this checkout's `nous` CLI | v2 iter-2 design hit 30 turns 3x and restarted from scratch ($21 wasted); handoff was written before measurement so designers re-read the code |
| v4 | `v4` | 0293c42 | + scripted sweeps of tunable values, 10 refine cycles, ranked gap analysis targeted by the next design | Claude scored ~490 settings on llm_router via scripts; Nous scored 5-10 per iteration |
| v5 | `v5` | 4ca4882 | + carry-forward: the best arm's patch is committed to the target before each iteration (DESIGN and EXECUTE start from the best); 45-turn EXECUTE cap; edit-not-rewrite; sweep only tunable arms; re-measure on noisy judges | every iteration's worktree started from the seed, so iteration 2+ spent turns rebuilding; at $25 iteration 1 alone took $23 on p0 |
| v6 | `v6` | 0f25a7a | v5 without the EXECUTE turn cap | v5 p5 (capped) 49 vs v4 p5 (uncapped) 58; long uninterrupted executor sessions are where v4 and Claude gain most |
| v7 | `v7` | 85b04f2..4bb8787 | + local evaluator and instrument checks first (worst case, noise, knobs); designer names 2-3 competing families (h-main + h-alternative); each screened in a fresh capped session; winner deepened; losers become principles; output-limit resume; CLI killed on every early stop | every $25 run locked into one family early; timeouts on p0 looked like noise (section 9) |
| v8 | `v8` | 774dcff..ced5e56 | see section 10 | v7 at $50: caps undercounted output ~10x, winner starved, crashed arm dropped, unknown time limits, gateway hangs (NOUS_V7_RUN_NOTES.md) |

## 2. Results (score at the budget; final re-judged in parentheses when different)

| task (budget) | Claude | v1 | v2 | v3 | v4 | v5 | v6 |
|---|---|---|---|---|---|---|---|
| gf ($50) | 85.70 | 84.23 | 84.95* | **86.30** | 83.59 (hooked 91.44 rejected) | 85.70* ($36.94) | 85.33* ($28.83) |
| llm_router ($50) | 58.74 | - | 51.27* | 56.70* | **59.57** (59.66) | - | 58.89 at $25 ($28.66) |
| p0 ($25) | 79.4 **contaminated**; clean SDK re-run 75.47 (76.41 measured, $25.10); **5x mean 74.28** | - | - | - | 73.48 (74.30) | 74.09 (75.32); 5x mean 74.52 | 73.72 (73.65, $26.37); **5x mean 75.27** |
| p5 ($25) | 50.0 | - | - | - | **58.00** | 49.00 | 57.00 ($28.80) |
| p47 ($25) | 94.07 | - | - | - | - | - | **94.39** (94.57, $28.94) |

`*` stopped early (bug or by user). Old algorithmic Nous (89.1 p0, 83 p5) stopped on the SDK's own cost
figure (~3x below our ruler), so it spent ~$97-162 per task; not comparable at $25. **These old algorithmic
Nous scores are also contaminated and must not be cited** (see §3, 2026-10-14).

Old Claude algorithmic score-vs-spend (from transcripts, shared ruler):

| task | $5 | $10 | $15 | $20 | $25 | total |
|---|---|---|---|---|---|---|
| p0 | 0 | 69.3 | 78.2 | 79.4 | 79.6 | $25.52 (contaminated) |
| p5 | 45.0 | 50.0 | 50.0 | 50.0 | 50.0 | $29.97 |
| p47 | 91.4 | 92.6 | 93.2 | 93.9 | 94.1 | $25.68 |

Claude research score-vs-spend (SDK runner, minimal prompt): gf 83.87 @ $10, **85.33 @ $25**, 85.70 @ $50;
llm_router 56.27 @ $10, **58.12 @ $25**, 58.74 @ $50. From 2026-10-13 17:10 the user set a **$25 cap for every
final run** (research included), compared against these $25 points.

Research at **$25** (best clean score by $25 on each run's own curve, `gen/curve_at.py`):

| task | Claude | v3 | v4 | v5 | v6 |
|---|---|---|---|---|---|
| gf | 85.33 | **85.70** | 82.97 | 82.93 | 85.33 (81.11 @ $10; stopped at $28.65 under the $25 rule) |
| llm_router | 58.12 | 56.69 | **59.29** | - | - |

p0's judge is time-limited and noisy (same solution re-scores within about +-2), so p0 is compared on the
**best 5x-mean of each agent's top-3 measured solutions** (`artifacts/preds/p0_rejudge5.json`): Nous v6 75.27,
Nous v5 74.52, Claude 74.28. Nous v6 leads by ~1 point, within the judge noise (a narrow edge, not a clear win).

## 3. Integrity findings

- **Claude p0 baseline is contaminated (found 2026-10-13).** The old CLI runner shared `/tmp/fcs_judge` with
  every agent. Claude scored 0 seven times, listed `/tmp/fcs_judge/done/`, read `p0__e2e_test.cpp` and ran
  `cp /tmp/fcs_judge/done/p0__e2e_test.cpp solution.cpp` ("Copy reference solution"), jumped to 65, then
  climbed to 79.4. Its variance reps (rep1 72.08, rep2 69.26) also listed that folder (4 reads each). No clean
  Claude p0 baseline exists; it must be re-run (SDK runner, minimal prompt, $25). Claude p5 and p47
  transcripts only touch their own run dir (clean).
- **Nous agents probed other runs' judge dirs** (`find /tmp/fcs_rjudge2 ...` listed other runs' inbox
  `.py`/`.pyc` names) while looking for the judge's resources. A scan of every research-run transcript found
  no read of another run's file contents. Fix (4a7faa8): both sandboxes deny `/tmp/fcs_judge`,
  `/tmp/fcs_rjudge2`, `/tmp/fcs_rjudge_csdk` except the run's own dir; old shared folders quarantined to
  `~/frontier/_quarantine_tmp_20261013_1705/`.
- **Coverage-gaming hook (gf).** Nous v4 produced solutions overriding `builtins.__import__` to instantiate
  sql_engine AST classes (91.44). Audit signatures extended (74b9488); v4 gf re-audited to 83.59. All other gf
  archives scanned: Claude and v3 have none; the published Opus-5 Nous 77.56 is clean.
- **Every old (pre-isolation) algorithmic Nous run is contaminated (found 2026-10-14).** All `frontier-*`
  campaigns ran with `sandbox: bypass`, and the executor logs (`runs/iter-*/inputs/executor_log.jsonl`) show
  reads of hidden test data: p0 and p5 looped over `testdata/*.in` (p5 read tests 1, 7, 8, 10 and built
  `probe_graph.cpp` to profile them); p9 read `.ans` for tests 2 and 7; p15 read `1.ans`; p22 read `1.in`; no
  access found for p47 `frontier-47-p47nous`. p0 is also seeded from the human solution: `p0.nous_rr.cpp`
  (86.5) says "Based on reference.cpp (Shang Zhou, IIMOC #1443)" and `frontier-0-clean50` (89.1) iter-1
  `h-main.patch` says "Adapted from reference.cpp". `frontier-0-freshvpc` (80.08) also ran unsandboxed and read
  testdata. So p0 89.1/86.5/80.1 (and the n=3 mean 85.2), p5 83, p9/p15/p22 100 are **invalid**; `ATTRIBUTION.md`
  is built on them. Only the isolated $25 runs (v4-v6) are clean algorithmic Nous results.
- **llm_router tunes against the measure.** Both agents tune thresholds with the sanctioned measure, which
  scores on the same data; scores reward measurement volume (Claude ~1,100, v4 ~850 measurements).

## 4. Where the money goes (what we learned)

- After v3, design is cheap ($1.6-5, 10-30 turns). Almost all spend is the executor at ~$0.17-0.30 per reply.
- Per-reply cost and token mix are now the same for Nous and Claude (cache reads ~60%, output ~30%), so the
  remaining gap is search quality and run-to-run variance, not overhead.
- Task type matters: sweeps win tuning tasks (llm_router), careful reasoning wins discovery tasks (gf).
- The executor is an LLM agent, not machinery: implementing, refining, measuring and reading results are all
  model turns (~$0.17-0.30 each, mostly re-reading 70-120K tokens of context). Only the judge is free. $25 buys
  ~100-120 turns for Nous or Claude alike.
- At $25, depth beats iteration count: v6 (one long iteration, ~30 measurements) beat v5 (45-turn cap, 2-3
  iterations) on gf (85.33 vs 82.93) and p5 (57 vs 49). Nous's edge at small budgets comes from the focused
  design, distinct arms and gap analysis inside an iteration. Whether compounding across many iterations pays
  off at larger budgets is untested: the old high-budget runs (p0 89, p5 83) are contaminated (§3).
- The cost ruler is model-independent ($15/$75 for every model), so a cheaper executor model would not buy
  more turns on the ruler; trimming the executor's system prompt (it also carries the design method) would
  save only ~5%.
- Single runs are noisy: one idea can swing p5 by +-10; p0's judge itself re-scores a solution within +-2.

## 5. Decision log

- 2026-10-13 17:30: **v6 chosen for the final runs.** At $25: gf v6 85.33 = Claude 85.33 (v5 82.93); p5 v6 56.00
  so far > Claude 50.0 (v5 49.00); p0 v5 74.09 (v6 running). v6 keeps carry-forward and removes the EXECUTE cap
  that cut v5's iterations short. Final v6 runs: p0 (running), p47, llm_router at $25.

## 6. Next

1. Finish v5/v6 on gf and p5; pick v5 vs v6 on gf + p0 + p5 together.
2. Re-run Claude p0 clean (SDK runner, minimal prompt, $25, new sandbox).
3. Final runs of the chosen version on p0, p5, p47, gf, llm_router; report score at budget plus curves.

## 7. Final result (2026-10-13 18:45)

| task | Claude @ $25 | **Nous v6 @ $25** | result | other Nous (at $25) | Engram / AIDE (old) |
|---|---|---|---|---|---|
| grammar_fuzzing | 85.33 | 85.33 | tie | v3 85.70, v4 82.97, v5 82.93 | - |
| llm_router | 58.12 | **58.89** | Nous +0.77 | v4 59.29, v3 56.69 | - |
| p0 (5x re-judged mean) | 74.28 (clean SDK re-run) | **75.27** | Nous +1.0 (within judge noise) | v5 74.52, v4 73.48 | 68.5 / 0 |
| p5 | 50.0 | **57.00** | Nous +7.0 | v4 58.00, v5 49.00 | 41 / 44 |
| p47 | 94.07 | **94.39** | Nous +0.3 | - | 94.2 / 96.8 |
| p9, p15, p22 | 100 / 100 / 0 | not re-run (old Nous 100 / 100 / 100 is contaminated, §3) | - | | |

Score vs spend (best clean measured score by each $; p0 uses single measurements here, so it is noisy):

| task | agent | $5 | $10 | $15 | $20 | $25 |
|---|---|---|---|---|---|---|
| gf | Claude | 81.13 | 83.87 | 84.30 | 85.33 | 85.33 |
| gf | Nous v6 | 73.31 | 81.11 | 83.54 | 85.33 | 85.33 |
| llm_router | Claude | 55.10 | 56.27 | 57.37 | 58.09 | 58.12 |
| llm_router | Nous v6 | 25.38 | 55.21 | 56.57 | **58.89** | **58.89** |
| p0 | Claude (clean) | 67.05 | 75.47 | 76.17 | 76.41 | 76.41 |
| p0 | Nous v6 | 69.37 | 74.51 | 74.73 | 75.95 | 75.95 |
| p5 | Claude | 45.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| p5 | Nous v6 | 31.0 | 47.0 | 50.0 | **56.0** | **57.0** |
| p47 | Claude | 91.43 | 92.62 | 93.22 | 93.88 | 94.07 |
| p47 | Nous v6 | 90.66 | **94.26** | **94.39** | **94.39** | **94.39** |

Summary: at a true $25 per task, one Nous version (v6) beats Claude on 4 of 5 re-run tasks (p5 clearly; llm_router,
p47, p0 narrowly) and ties on gf. Claude climbs faster in the first ~$5-10 (one long session); Nous overtakes
by $15-25. Nous v6 = `design_profile: v6` (lightweight design-only designer, scripted sweeps, carry-forward of
the best arm, uncapped EXECUTE). Single runs per agent; p0 judge noise is about +-2. Full history, versions,
integrity findings: `NOUS_IMPROVEMENT_LOG.md`.


## 8. Opus-5 at $25 (started 2026-10-13 22:15)

Question: does a stronger model get more benefit from Nous? Identical setup to the opus-4-6 final (same $25 cap,
$15/$75 ruler, sandbox, judge, audit, Nous v6 vs Claude SDK minimal prompt); only the model changes to
`aws/claude-opus-5`. 10 runs (5 tasks x 2 agents), queued by `gen/o5_queue.sh`, max 3 concurrent, Nous and Claude
for the same task launched back to back. Results will be filled in below.

**Judge outage (2026-10-13 22:49-23:08).** The colima Docker VM running the algorithmic go-judge stopped; every
algorithmic score in that window was a false 0 (re-judging the same files after restart gives 91 etc.). Affected:
Nous p5 (finished; best 91 came before the outage, re-judged final 91.0, at $25 90.0) and Nous p0 (8 false-0
measurements after 22:57; best 92.08 came before). Claude p5 did not measure during the outage (unaffected).
Claude p0 had just started and was killed ($0.69). Fix: colima restarted, `~/frontier/judge_watchdog.sh`
restarts it if the judge disappears. Decision recorded before any re-run result: **clean re-runs of Nous p5, Nous
p0 and Claude p0 (`gen/o5_queue2.sh`, slugs *_o5b) are the official Opus-5 numbers**; the outage runs are kept
as `*.o5c25.outage_backup.json`.

Opus-5 results so far (headline rule as for opus-4-6: Claude = final re-judged harvest at its cap; Nous =
best_at_budget, i.e. best re-judged solution measured by $25):

| task | Claude (Opus-5) | Nous v6 (Opus-5) | notes |
|---|---|---|---|
| p5 | **96.0** ($25.69; final solution.cpp, last measured 92) | 90.0 @ $25 (outage run, backup; re-run queued) | |
| p0 | re-run queued | 93.96 @ $25 (outage run, backup; re-run queued) | |

## 9. What the $25 runs missed (p0, p5 transcript analysis, 2026-10-14) and the v7 plan

Read-only analysis of the clean Claude SDK and Nous v4-v6 runs (transcripts, measured candidates, findings),
with local per-test re-scoring (`/tmp/p0an/`, `/tmp/p5j/`; our local scorer reproduces the judge's totals).

**p0 (everyone ~75).** The packing is fine; the time limit is not. Per test, with a test over the judge's 2 s CPU
limit scored 0 (`judge_engine.js` cpuLimit from `config.yaml`; the limit is not in `statement.txt`):

| solution | mean density, no timeouts | judge score | timeouts (of 70) | max CPU |
|---|---|---|---|---|
| Claude m0024 | 81.23 | 76.13 | 4 | 3.98 s |
| Nous v6 best | 79.68 | 75.95 | 3 | 5.02 s |
| Nous v5 best | 81.50 | 76.36 | 4 | 7.01 s |
| human reference.cpp | 89.11 | 89.11 | 0 | 1.94 s (89.02 when capped at 0.9 s) |

Every agent saw only one aggregate SCORE, so timeouts looked like noise. Claude decided "the judge uses random
test cases"; Nous v6 wrote the same into its handoff; v5 wrote "time limit is ~7-8s". Most of the "+-2 judge
noise" is large tests flipping between finishing and timing out. Small tests (53 of 70) use 2-4% of the limit.
The reference's main idea, choosing the best next piece from a lookahead window instead of a fixed order,
was never tried at $25.

**p5 (Claude 50, v6 57, v4 58).** All runs committed early to SCC + greedy/DFS and hill-climbed it (Claude ran
~15 variants at 49-50). Nous's gain came from the executor's refine loop (v6: 31 -> 41 -> 50 -> 54 -> 56 -> 57)
and, for v4, Hopcroft-Karp matching, which only fixed the two near-DAG tests (t3 33 -> 60, t4 98 -> 500 path
length). The Nous designer's plan proposed a reversal "rotation" that is invalid on directed graphs; Claude
found it invalid and dropped rotation entirely. The likely route to 90+ (cycle cover by matching, then cycle
merging / rotation-extension) was never tried; local checks show a perfect matching gives only 4-15 cycles per
test.

**Lessons (general, not task-specific).** Same information for both agents; only the method differs.

1. **Build the instrument first.** Before tuning, the agent builds a local evaluator from the statement: an
   instance generator (including the largest allowed sizes), a per-instance score, and per-instance CPU time.
   An aggregate score hid the cause on both tasks.
2. **Per-instance, falsifiable gap analysis.** "Where is score lost" must be answered per instance and per size
   group. A noise explanation must be tested (re-run an unchanged solution) before it enters a handoff or a
   principle.
3. **Competing mechanisms in the bundle.** 2-3 arms with genuinely different algorithm families when the
   problem allows. Today every arm type is a variant of h-main and the lightweight profiles say to skip extra
   arms, so all $25 bundles had one arm. Needs a new arm type for a competing alternative.
4. **Cheap validity check of the design.** Check a proposed mechanism on a tiny case before the executor builds on
   it (the invalid directed rotation).
5. **Budget for a second iteration.** Every v6 run spent $16-24 of $25 in one executor session, so the designer,
   principles and gap analysis never fed a second design.

**v7 plan (to build).** v6 plus:
- DESIGN: 2-3 arms from different mechanism families (new competing-alternative arm type); first iteration
  must include building the local evaluator (lesson 1) and a validity check of each mechanism (lesson 4).
- EXECUTE: each arm runs in its own fresh executor session with a dollar budget (explore ~$3-5 per arm), then
  the winning arm gets the remaining iteration budget in one long session, starting from the best (keeps v6's
  depth). Losing arms' refuted predictions become principles.
- Gap analysis per instance and size group, with noise claims tested (lesson 2).
- Iteration budget sized so a $25 run gets at least 2 designs.
- Open question to measure on the first run: whether fresh per-arm sessions cut cost per turn (smaller context)
  or just re-explore.

Evaluation: on newly selected tasks fixed before any v7 run (not gf/p0/p5, which we tuned on).

## 10. v8 (2026-10-15): what changed and why

v7 at $50 (opus-4-6) won p0 (68 vs 20), p58 (60 vs 0) and p26 (7 vs 0), lost p5 (43 vs 55) and tied p181
(49.6 vs 50.4). Analysis of all five runs (transcripts, judge archive, metrics; `NOUS_V7_RUN_NOTES.md`) gave the
v8 changes below. Same model, CLI, effort and ruler as the Claude baseline; no thinking caps.

| # | change | evidence from v7 |
|---|---|---|
| 1 | Per-session caps and the iteration budget are charged from the live Claude Code transcript (polled every 10 s; CLI killed at the hard cap) | the stream reports a few output tokens per reply: p5 h-main 469 seen vs 38,246 real; 16-37% of every run's spend was invisible to the budget logic, so a "$12 iteration" cost $20-24 |
| 2 | Real-dollar defaults: iteration $22, design $8, arm $6, evaluator target at least $3; screening hard caps (2x target) never eat the winner's reserve | v7 defaults were set while undercounting; v7 evaluators really cost $2.7-4.7 and a design up to $12 |
| 3 | Judge profile learned only from official results and local runs: time limit assumed 1 s when the statement gives none, longest accepted runtime, "likely timeout" when official is 0 but local > 0; shown to every session | p0 lost $18.6 after its best to timed-out submissions (blamed on "a daemon issue"); p181 arms scored 0 at 1 s while the local evaluator used 28.5 s |
| 4 | The screening winner continues in its own session (resume, same worktree) with at least 40% of the iteration; from iteration 2, exploit (one h-main deepening the incumbent, no design call when the arm left a next step) while the best improves by more than max(noise, 0.5); explore (competing families) on a plateau | every gain came from a screening session; 7 fresh winner sessions ($23.5) and 8 h-alternative sessions ($62) never improved the best |
| 5 | Evaluator writes and officially measures a simple valid baseline first and measures noise on it; the baseline is committed | noise was measured on 0-score stubs in 3/5 tasks; first real score came at $9-17 vs Claude's $0.7-7 |
| 6 | One $1 repair turn (same session) for an arm that crashed, failed validity, or scored 0 before it is ranked | p5 matching path cover (the likely route to 90+) segfaulted and was ranked 32 |
| 7 | Local vs official check: evaluator marked untrusted when they disagree by more than 2x noise + 5 | p26 local 91.8 vs official 10.4 was never flagged |
| 8 | Robustness: every SDK exception marks the arm failed (never crashes the campaign); hang watchdog (>= 3 API errors and 15 min without a reply) restarts once from the session's latest edits; missing transcript logged loudly; launcher `--wall-hours` | gateway "Request timed out" loops (p58 idled 1.8 h, p0 2.2 h); the 4 h launcher limit ended p0 at $35 |
| 9 | Orchestrator writes findings/results after a cap stop (no LLM wrap-up) | wrap-ups cost $17.5 across the five runs |

Not taken: trimming design.md from the arm prompt (~$3-5 per task; Claude's context per turn is larger),
task-specific hints, any cap on reasoning length. Tests: 1536 passed (52 v8 tests); shared prompts byte-identical;
v4-v7 unchanged. Run with `gen/nous_research_cap.py --design-profile v8 --wall-hours`.

## 11. Status and plan (2026-10-15, written before compaction)

**Runs in progress (v8 at $50, opus-4-6, same sandbox/judge/ruler as Claude):** p5 on 486d822 (vpc k3; 58.00
at $49.69 vs Claude 57.00, v7 43.0); p0, p181 (vpc-int), p26, p58 (vpc) relaunched 15:23 on 125df97 after the
live-run fixes below. Launcher `gen/nous_v8_c50.sh <pid> <URL var> <KEY var>` (keys from env, `--wall-hours 24`).
Live log of every finding and restart: `NOUS_V7_RUN_NOTES.md` ("Nous v8 runs (2026-10-15)").

**v8 fixes found live on 2026-10-15 (each one restarted the affected runs; none of their spend counts):**
time limit read from the statement (26bc363); official-first evaluator, at most one h-alternative, $4 arm
floor, results rebuilt from official measures (1288dbd..e46749f); iteration-1 evaluator credited back to the
iteration budget (9635465); capped evaluator baseline from its best official measure (bcced84); $1 overshoot
margin so a cap trip does not skip the second family (ecc98b1); baseline always the evaluator's best official
measure (486d822); fallback one-arm design when a design is capped mid-reasoning (0e7ae60); an arm's result
follows its best official measure when the judge recorded more than the agent wrote (125df97).

**Claude robustness check (continue-on-crash, `gen/claude_c50cc.sh`):** p26 0 at $47.41, p58 0 at $48.55; even
resuming after CLI crashes Claude never submitted a solution (gateway timeouts were heavy today). The plain
baseline's zeros stand.

**Plan (agreed):**
1. Let the 5 focus runs finish. Fix only real bugs (rerun the affected task); do not tune v8 until it wins on
   these dev tasks (that would overfit; the held-out tasks carry the claim).
2. Freeze: tag the final commit `nous-algo-v1` and add a `design_profile: algo` alias for the paper.
3. Held-out runs, nothing changed after the freeze: p225 (set merging; one-shot 0-39, published 99.8,
   deterministic, bimodal) and p44 (Santa tour; one-shot 0-45, published 78, deterministic), optionally one
   more task chosen before looking at results. Claude baseline (plain) and nous-algo at $50 each; re-judge
   finals together (3x). Do not schedule until we discuss.

**Paper framing (agreed, no v1-v8 history in the paper):** case studies are real open-ended research tasks and
use Nous's full profile (heavyweight machinery: control, ablation, robustness, dose-response arms) because the
goal is explanation and causal attribution. Frontier-CS is a scoped benchmark of algorithm discovery under a
fixed budget with a fast automated judge, so it uses a lightweight profile of the same loop (hypotheses,
measured experiments, principles) that spends the budget on competing algorithm families and deepening the
best. State in the paper: the profile was developed on the benchmark's focus tasks and evaluated frozen on
held-out tasks; the Claude baseline has identical model, CLI, effort, budget, sandbox and judge. One sentence:
"Case studies use Nous's full profile; for the fixed-budget algorithmic benchmark we use a lightweight profile
of the same loop, tuned for automated-judge optimization."

## 12. v8 focus-set results, the 64k-output problem, and the effort work (2026-10-15 to 2026-10-16)

**v8 at $50, first runs (all finished; best judged score reached by $50):** p0 81.47, p5 58.0, p26 29.61,
p181 12.78, p58 0. Against v7 (68.24 / 43.0 / 7.09 / 49.55 / 59.71) and Claude (26.43 / 57.0 / 0 / 56.0 / 0):
v8 beats both on p0, p5, p26; loses p181 and p58. Preds: `artifacts/preds/p*.nous_v8.c50.json`.

**Repeats (to tell method from noise):**

| run | commit | p181 | p26 | p58 |
|---|---|---|---|---|
| v8 r1 | 125df97 / 486d822 | 12.78 | 29.61 | 0 |
| v8 r2 | 0d858f5 (repair reserve) | 47.67 | 10.14 (85ecf14) | 0 (stopped at $29) |
| v8 r3 | 85ecf14 (reply-sized arm floor) | | | 0 (stopped at $26) |

Single runs are noisy (p181 12.78 vs 47.67; p26 29.61 vs 10.14). Judge any change with at least 2 runs per task.

**Root problem found: replies cut at the 64k output limit.** On p58 (every run, every agent) and p26, opus-4-6
writes one reply of extended thinking that reaches Claude Code's 64,000 output-token limit (the model allows
128k). The reply is cut (`stop_reason: max_tokens` in the transcript), the thinking is lost, the resume restarts
the same reasoning, and the session never acts. Evidence: in p58 v8 runs every arm's 64k replies preceded no
tool call, and the official judge saw only the stub; Claude's p58 baseline had 4 of 5 replies at 64k (9 of 13
in the continue-on-crash run). v7 scored 59.71 on p58 because one of its three arms finished thinking at 47,440
tokens, just under the limit, then wrote code; v7's undercounted caps also let sessions run past their budget.
Tasks p0, p5, p181 never hit the limit (largest single reply $0.95-$2.12).

**What controls thinking (probed 2026-10-16, opus-4-6, opus-5, opus-5-5, on vpc and vpc-int, same results):**
`MAX_THINKING_TOKENS` is ignored by all three (adaptive thinking); `--effort` works (opus-4-6: low 335 output
tokens and a wrong answer, medium 1.1k-17.7k; opus-5 and opus-5-5 respond less, and opus-5-5 thinks ~4x less
than opus-4-6). All three report a 128k API output limit. Anthropic's guidance: effort is the primary control on
adaptive-thinking models, and on `stop_reason: max_tokens` either raise max_tokens or lower effort
(platform.claude.com/docs/en/build-with-claude/effort, .../thinking-steering-and-cost). Task budgets are not
available in Claude Code; per-message effort is not available on opus-4-6.

**Changes, in order (all pushed):**
- 0d858f5 keep: the first arm's hard cap reserves its repair turn; a repair runs only if every waiting arm
  keeps its floor (live p26/p0/p58: a $1.11 repair skipped the second family by $0.26).
- 85ecf14 then 9cf6a43 reverted: arm floor = 2x the campaign's largest reply. It did not fix p58 (the model
  still thought to 64k) and on p5 r2 one long, uncut $3.36 reply raised the floor to $6.72 and skipped the
  family that won p5 r1. Sessions still log `max_reply_usd`.
- 2c2094c keep (to be revised): effort ladder in `orchestrator/effort.py`. A reply cut at the output limit stops
  the session (`stop_on_output_limit`), which resumes one level lower with a "write and submit the simplest
  correct solution first" prompt, and later sessions start one level lower (floor medium). Metrics rows record
  the effort. Its first-session rule ("medium until an official score > 0") is wrong for p0: a replay on the r1
  logs runs 5 of p0's 7 sessions at medium, including the one that found 70.78.

**Process change (after the p5 regression):** replay every change against the logs of all five tasks before
any run, and report which sessions it changes. `/tmp/replay.py` did this for the ladder.

**Next (decided, not built):** evaluator session at medium; every other session at the model default; drop
one level only after a real cut-off. Replay result expected: p0, p5, p181 unchanged except the evaluator; p26,
p58 change after their first cut-off. Then run p58, p26, p5 (2 runs each before judging), then the freeze and
held-out plan in section 11.

**2026-10-19 update.** Built the decided rule as dcba58b (plan, plan review, tests, code review, replay):
evaluator at medium, other sessions at the model default, one level down per real cut-off (floor medium for
new sessions, low as a last resort inside a repeatedly cut session). Code review found that cuts after the
resumes ran out were not counted; fixed with a test. Live check: a session resumed with a different `--effort`
keeps its context. Replay on both v8 runs of every task: p0, p5, p181 change only their evaluator; p26 and p58
go to medium after their first cut-off. Design sessions are cut only on p58 (2 and 1) and are covered by the
step-down. Smoke runs `s1` (p58 vpc k1, p26 vpc k3, p5 vpc-int k1) started 10:02. Pass: p58 and p26 > 0, p5
near 58. Then freeze as `nous-algo-v1`; held-out tasks stay unseen until then. User doc:
`docs/design-profile-v8.md`.


## 13. 2026-10-19: from the effort rule to nous-algo-v1 and the stage-1 main runs

**What the smoke runs found, in order (each fixed, tested, then re-run):** cut-off not counted when a cap tripped
on the same reply (656c067); act-first note + saved-reasoning resume (29b48ff); one funded resume after a cap on a
cut reply (f0cd57b); resume double-counted the reply it resumed from, capped evaluator lost its code (7be9d7c);
old 600 s silence guard killed long thoughts, hang restart pointed at saved reasoning (f30139e); 128k output,
loose arm hard stops, 120 s LLM timeout (1a7d66f); soft session caps with a reserved write-and-measure wrap-up
(a090341). Replay tests on real p58 transcripts (tests/fixtures/transcripts) fail when each fix is removed.

**Root cause of p58/p26 zeros:** single thinking replies of 65k-128k tokens. No prompt or effort level stopped
them (medium and low both ran to 64k); only 128k output let them finish, and only soft caps let the session act
afterwards. Smoke s7: p26 evaluator 30.0 (first time > 10), p58 0.9967 (first nonzero) after a 128k reply plus a
funded resume.

**Frozen:** `nous-algo-v1` = a090341 (tag pushed). Claude baseline for the main runs also at 128k
(`--max-output-tokens`, 2e95962): with it Claude p0 rose from 26.43 to 74.41, p5 57 -> 59, so earlier Nous wins
were partly due to Claude losing 64k-cut thoughts.

**Stage 1 (1 run per agent per task, gen/main_queue.py, be07daf), in progress 15:25:**

| task | Nous r1 | Claude r1 (128k) | Nous v7 (64k era) | Claude (64k) |
|---|---|---|---|---|
| p0 | 79.69 at $11 (running) | 74.41 | 68.24 | 26.43 |
| p44 (held-out) | 74.80 at $11 (running) | 77.87 | - | 78.56 (Oct 1 pilot, $10) |
| p5 | 45.0 at $6 (running) | 59.0 | 43.0 | 57.0 |
| p26 | 30.0 (final) | queued | 7.09 | 0 |
| p58 | 4.56 (final) | queued | 59.71 | 0 |
| p225 (held-out) | 0 at $17 (running) | 39.02 | - | - |
| p181 | queued | queued | 49.55 | 56.0 |

**Findings for the paper:** (1) the CLI's 64k output default silently decides results for both agents;
(2) on p0/p44 Nous reached Claude's $50 score at 5-15% of the spend; (3) p58's arm passed a validity check on tiny
x but overflowed 64-bit path counts for large x (5/100 tests correct): tiny-case validity checks miss the hard
regime; (4) with $5-10 single thoughts, a $22 iteration funds only one family plus the winner.

**Next (agreed):** finish stage 1 only (no repeats unless a gap is within noise); then a 3x re-judge of finals,
score-vs-spend curves, and the decision on the main table (stock 64k vs both at 128k). Optional: cant_be_late
(research track, never run here) as one Nous/Claude pair after its evaluator is checked in our sandbox. Repeats
r2/r3 only if the stage-1 decision needs them (`REPEATS` in gen/main_queue.py).
