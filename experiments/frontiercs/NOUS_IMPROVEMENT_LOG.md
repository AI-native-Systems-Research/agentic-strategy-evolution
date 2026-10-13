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

## 2. Results (score at the budget; final re-judged in parentheses when different)

| task (budget) | Claude | v1 | v2 | v3 | v4 | v5 | v6 |
|---|---|---|---|---|---|---|---|
| gf ($50) | 85.70 | 84.23 | 84.95* | **86.30** | 83.59 (hooked 91.44 rejected) | 85.70* ($36.94) | 85.33* ($28.83) |
| llm_router ($50) | 58.74 | - | 51.27* | 56.70* | **59.57** (59.66) | - | - |
| p0 ($25) | 79.4 **contaminated** (see 3) | - | - | - | 73.48 (74.30) | 74.09 (75.32) | - |
| p5 ($25) | 50.0 | - | - | - | **58.00** | 49.00 | 57.00 ($28.80) |

`*` stopped early (bug or by user). Old algorithmic Nous (89.1 p0, 83 p5) stopped on the SDK's own cost
figure (~3x below our ruler), so it spent ~$97-162 per task; not comparable at $25.

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
  design, distinct arms and gap analysis inside an iteration; compounding across many iterations needs more
  budget (old Nous with 3-6x spend: p0 89, p5 83).
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
