# Frontier-CS: Nous vs baselines (canonical, updated 2026-10-13)

Single source of truth for the MLSys Frontier-CS experiments. Branch `aiopslab`. Older notes and the full
debugging history are in `HISTORY.md` (kept for provenance, not current).

## 1. Rules (every run)

1. **Agents as-is.** Nous as-is; real Engram (mit-nms, `agentic_handoff`); real AIDE (Weco aideml);
   Claude = plain Claude Code. No reimplementations, no chat/api loops.
2. **Iso-cost $50.** Stop at $50 or max score. Cost = tokens x $15 in / $75 out / $18.75 cache-write /
   $1.50 cache-read per M, model-independent, one ruler for all agents (§3).
3. **No cheating.** Sandboxed agents, sandboxed judge, exploit audit, independent re-judge (§4).
4. **Docs current.** Update this file and push after every result.

## 2. Agents and runners (research track)

| Agent | Runner | Stack |
|---|---|---|
| Nous | `gen/nous_research_cap.py` -> `gen/nous_research_isolated.py` | `nous run --agent sdk` (claude_agent_sdk 0.2.163, bundled CLI 2.1.286) |
| Claude | `gen/claude_sdk_research_runner.py` (+ `gen/claude_sdk_driver.py`) | same SDK + CLI as Nous; Claude Code preset system prompt; `bypassPermissions`; WebSearch/WebFetch disallowed; default effort/settings |
| Engram | `gen/engram_research_cap.py` | real Engram; agents' FS rooted at workspace, shell in Docker |
| AIDE | n/a (algorithmic-only adapter) | |

Nous and Claude differ only in what is tested: Nous's methodology prompts + loop vs one plain task prompt.
Endpoints: Nous on vpc (`FCS_VPC_URL/FCS_VPC_KEY`); Claude and Engram on vpc-int (`OPENAI_BASE_URL/OPENAI_API_KEY`).
Algorithmic track runners: `gen/nous_cap_launch.py`, `gen/claude_code_runner.py`, `gen/monitoring/engram_cost_cap.sh`, `gen/aide_frontier.py`.

## 3. Cost (one ruler)

- Nous and Claude: `gen/cost_meter.py` sums live Claude Code transcripts (`~/.claude/projects/<cwd-key>*`),
  **one count per reply** (message id). Verified: reproduces every recorded Nous cost to the cent and the
  CLI's own end-of-session totals. The Nous cap also reads Nous's `llm_metrics.jsonl` and uses the max.
- Engram: `gen/token_meter_proxy.py` meters every OpenAI-format response (Engram's self-reported cost
  double-counts under the meter and is kept only for reference).
- Cut at $50: the cap kills the agent mid-iteration (and any orphaned `claude` children); nothing is lost
  because the judge daemon archives every measured solution, which is harvested and re-judged.

## 4. Isolation and access (`gen/access_rule.py`, `gen/judge_sandbox.py`)

- **Visible to every agent (benchmark-faithful):** the task `readme` and `resources/` (e.g. the SQL engine
  source, `reference_data.csv`), read-only. Engram gets a copy in its workspace.
- **Hidden:** `evaluator.py`, `resources/datasets/` (test data), reference solutions, other runs'
  artifacts/logs/transcripts, other agents' repos, the web.
- **Judge:** every evaluation runs under sandbox-exec with no network and no writes outside a private
  scratch copy of the problem dir (deleted after). Only the score leaves. This closes the `/tmp` side
  channel found 2026-10-12 (solutions copying files out for the agent to read).
- **Exploit audit (all agents, in-loop = score 0, and at harvest):** import hooks / engine-internal
  imports, test-split or `datasets/` reads, rewriting cloudcast edge cost/throughput, calling the judge
  from inside a solution.

## FINAL (2026-10-13): Nous v6 vs Claude Code at $25 per task (opus-4-6, one cost ruler, sandboxed, audited)

| task | Claude @ $25 | **Nous v6 @ $25** | result | other Nous (at $25) | Engram / AIDE (old) |
|---|---|---|---|---|---|
| grammar_fuzzing | 85.33 | 85.33 | tie | v3 85.70, v4 82.97, v5 82.93 | - |
| llm_router | 58.12 | **58.89** | Nous +0.77 | v4 59.29, v3 56.69 | - |
| p0 (5x re-judged mean) | 74.28 (clean SDK re-run) | **75.27** | Nous +1.0 (within judge noise) | v5 74.52, v4 73.48 | 68.5 / 0 |
| p5 | 50.0 | **57.00** | Nous +7.0 | v4 58.00, v5 49.00 | 41 / 44 |
| p47 | 94.07 | **94.39** | Nous +0.3 | - | 94.2 / 96.8 |
| p9, p15, p22 | 100 / 100 / 0 | not re-run (old Nous 100 / 100 / 100 is contaminated, see §5) | - | | |

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

## Task selection for the next round (2026-10-14)

Why: gf, llm_router and p47 are near their ceilings (llm_router's real maximum is 75.0, and a lookup table by
eval_name already gives 59.71), so they cannot separate agents. Selection used only free signals plus a small Claude
pilot, and was fixed before any new Nous version was run.

Method: (1) published per-problem scores for 188 algorithmic problems (`~/frontier/Frontier-CS/results/*.csv`:
gemini-3.1-pro-cli, gemini-3.1-pro-amplio, gpt-5.6-sol) to find problems with a proven high ceiling and a wide
spread; (2) read each checker for smooth partial credit (not pass/fail, not an unreachable bound); (3) on our
judge, scored 6 bundled one-shot model solutions per problem and re-judged the best 3 more times for noise
(`/tmp/fcs_pilot/results.jsonl`, 99 runs, no LLM calls); (4) Claude SDK pilot at $5 (`gen/pilot_c5.sh`).

**Focus set (5):**

| task | type | one-shot models (our judge) | best published | judge noise | role |
|---|---|---|---|---|---|
| p0 polyomino packing | packing heuristic | 0-72 | 97.7 | +-2 (time-limit sensitive) | dev task (Nous was tuned on it) |
| p5 Hamiltonian path | graph search | 0-34 | 71 | +-5 (step scoring) | dev task |
| p181 binary QAP | local search | 10-31 | 86 | +-1 | held out |
| p26 OgreSort | sorting with move costs | 0-34 | 100 | 0 | held out |
| p58 inverse counting path | math construction | 1-59 | 86 | +-0.6 | held out |

**Backups:** p225 set merging (one-shot 0-39, published 99.8, deterministic, but bimodal scores), p44 Santa tour
(one-shot 0-45, published max 78, deterministic). **Dropped:** p211 (one-shot already 86 of a published 87; noise
+-10), p248 (noise +-7, 34 s per judge), p45 (everyone ~40-56), p48 (100 is the Kepler bound, unreachable), the
AHC-style problems (10 s x 100-150 tests per measurement is too slow to iterate), p47/gf/llm_router (saturated).
Judge caveat: the human p0 reference scored 84.0 on 2026-10-14 vs 81.2 before; compare agents under the same
judge load.

**Claude $5 pilot (2026-10-14, `gen/pilot_c5.sh`):** p181, p26, p58 all scored 0 at $5. p26 and p58 never
submitted a solution (each $5 went into one or two long reasoning turns). Taken as evidence these are hard.

## Focus set at $50: Claude Code baseline (2026-10-14, opus-4-6, done)

Same runner, sandbox, judge daemon, exploit audit and cost ruler as the $25 runs (`gen/claude_c50.sh`,
`gen/claude_c50_dev.sh`; keys from env `NOUS_LITELLM_*` / `NOUS_VPCINT_*`). Minimal prompt, WebSearch/WebFetch
off, default effort. Final score is the re-judged clean final solution.

| task | endpoint | final | cost | best known | pred |
|---|---|---|---|---|---|
| p5 | vpc-int | 57.00 | $51.29 | 96.0 (our Opus-5 Claude run; published 71) | `p5.claude_sdk.c50.json` |
| p181 | vpc | 56.00 | $50.76 | 86 | `p181.claude_sdk.c50.json` |
| p0 | vpc-int | 26.43 | $51.35 | 97.7 | `p0.claude_sdk.c50.json` |
| p26 | vpc | 0 | $20.13 | 100 | `p26.claude_sdk.c50.json` |
| p58 | vpc | 0 | $20.53 | 86 | `p58.claude_sdk.c50.json` |

p26 and p58: every turn was one reasoning block that hit Claude Code's 64k output-token maximum (Claude Code
auto-resumes with "Output token limit hit. Resume directly..."); after 4 in a row the CLI exited with code 1
("response exceeded the 64000 output token maximum") having never submitted a solution. Our driver auto-continues
only after a normal session end, so a CLI crash ends the run; we count these as 0. Audit: every run touched only
its own judge inbox/outbox; no test data, `.ans`, reference or other-run access; 0 exploit rejections.

## 5. Results

### Algorithmic (opus-4-6, go-judge 0-100) — INVALID for Nous, do not cite

**2026-10-14: the Nous column below is contaminated.** Every old algorithmic Nous campaign ran with
`sandbox: bypass` and read hidden `testdata` (p9 and p15 also read `.ans` files); p0 89.1/86.5 were seeded from
the human `reference.cpp`. Details: `NOUS_IMPROVEMENT_LOG.md` §3. The clean algorithmic Nous results are the
isolated $25 runs in the FINAL table above.

| task | Nous | Claude | Engram | AIDE |
|---|---|---|---|---|
| p0 | **89.1** | 79.4 | 68.5 | 0 |
| p5 | **83** | 50.0 | 41 | 44 |
| p9 | **100** | **100** | 67.8 | 95 |
| p15 | **100** | **100** | **100** | 0 |
| p22 | **100** | 0 | **100** | 0 |
| p47 | 95.5 | 94.1 | 94.2 | **96.8** |
| p0 variance (n=3) | **85.2** [80-89] | 73.6 [69-79] | 71.4 [68-74] | — |

Disclosure: the Claude algorithmic runs were capped by a transcript counter that double-counted replies,
so Claude's actual spend was ~$24-30 (p9 $9.4), not $50. Nous stopped on the SDK's own `cost_usd`, which prices
opus-4-6 ~3x below the shared $15/$75 ruler, so on that ruler Nous spent ~$97-162 per task. Engram overshot to
$56-68 (5-iteration cost logging). AIDE cost not yet re-checked on the shared ruler. This table is therefore NOT
iso-cost; p0 and p5 are being re-run (Nous vs Claude SDK, true $50 on one ruler).

### Research — model scaling, grammar_fuzzing (blocked-resources rule) — final, kept as is

| model | Nous | Claude (CLI) |
|---|---|---|
| Sonnet-4.5 | **54.23** / $50.6 | 53.95 / actual $26.6 |
| opus-4-6 | **59.55** / $50.2 | 57.70 / actual $27.5 |
| Opus-5 | **77.56** / $50.2 | 65.78 / actual $24.9 |

Agents could not read `resources/` under this rule; Claude's actual spend was ~half (same counter bug).

### Research — main comparison (opus-4-6, faithful access, $50, Nous vs Claude SDK minimal prompt) — RUNNING

Nous versions (all opt-in via `campaign.design_profile`; `standard` = original Nous, tag `nous-v1-pre-lightweight`):
- **v3 = `lightweight`** (a598468, 68121f7, ca49a72): 30-turn design-only designer that builds on the handoff,
  1-3 focused arms, 5 refine cycles per arm, turn-limit wrap-up (resume, not restart), executor writes
  `handoff_update.md` for the next designer, agents use this checkout's `nous` CLI.
- **v4 = `v4`** (0293c42): v3 + scripted sweeps of tunable values in EXECUTE (<=~100 settings, generalize, no
  special-casing), 10 refine cycles, ranked measured gap analysis that h-main must target from iteration 2.

| task | Claude SDK | Nous v3 | Nous v4 | notes |
|---|---|---|---|---|
| grammar_fuzzing | 85.70 @ $50.26 (done) | **86.30 @ $37.83** (stopped by user to free a slot for v4) | 83.59 @ $56.50 (at $50: 83.59; 9 hooked candidates rejected, incl. 91.44) | v3 beats Claude with 25% less spend |
| llm_router | 58.74 @ $51.93 (done; last reply overshot the $50 poll by $1.93) | 56.70 @ $33.17 (stopped by user; plateaued since iter 2) | **59.66 @ $57.51** (at $50: **59.57**; 1 rejected candidate) | v4 beats Claude; ~850 measurements via sweeps |

Run slugs/logs: Claude gf `gf_cmin46` (`runs/gf/claude_min_fa46.log`), Claude router `router_cmin46`;
Nous v3 `gf_v3bfa46` / `router_v3bfa46` (`runs/*/nous_v3_fa46.log`); Nous v4 `router_v4fa46` / `gf_v4fa46`
(`runs/*/nous_v4_fa46.log`). All on the vpc endpoint, one key per concurrent run (vpc-int too slow).
Stop rules: Claude hard $50; Nous finishes its iteration after $50 (ceiling $57) and records best_at_budget.
Both use the same $15/$75 token ruler (`gen/cost_meter.py`), the same access rule and judge.
Score-vs-spend curves (best score at each $) will be added when the runs finish.
Exploit found 2026-10-13: Nous v4 gf produced solutions that override `builtins.__import__` to instantiate
sql_engine AST classes directly (coverage gaming; 91.44). The audit now rejects `__import__`/`builtins` hooks
and string-targeting of engine modules (`gen/nous_research_isolated.py` EXPLOIT_SIGS); the v4 gf pred was
re-audited (clean best 83.59). All other gf archives were scanned: Claude and Nous v3 have no hooks.
Caveat (llm_router): the sanctioned measure scores on the same data every agent tunes against, so many-sample
search (Claude ~1,100 measurements, Nous v4 sweeps ~300) partly fits the evaluation data. Nous v4's own gap
analysis: tuning on resources/reference_data.csv alone gives 55.14 vs 59.28 when tuned with the measure. This is
allowed and identical for all agents, but scores reward measurement volume.

Backups (kept, superseded): Nous v1 gf 84.23 @ $49.08 (`gf_seed_sql.nous_v1.fa46.json`); Nous v2 gf 84.95 @ $39.81
and router 51.27 @ $18.92 (`*.nous_v2.fa46.killed_designbug.json`: iter-2 design hit the 30-turn cap 3x and
restarted from scratch); Nous v3a gf 77.83 / router 55.14 (`*.nous_v3.fa46.killed_pathbug.json`: agents'
`nous validate` came from another checkout and rejected `handoff_update.md`); Claude SDK verbose-prompt gf
(`runs/gf/claude_sdk_fa46.aborted_verbose_prompt/`); Claude router hung on vpc-int
(`runs/llm_router/claude_min_fa46.stuck_130354/`, $0). Engram held until we discuss.

### Algorithmic re-runs — Nous v4 at a $25 cap — RUNNING (p0 started 14:54; p5, p47 queued; max 3 runs at a time)

Claude's old algorithmic runs actually spent ~$24-30 (see disclosure above), so Nous v4 is re-run at a $25 cap
on p0, p5, p47 and compared with the existing Claude/Engram/AIDE numbers (unchanged). p22 is not re-run (old
Nous reached 100 in 18 min; its metrics file is missing, so its exact cost is unverified). Same isolated
pipeline as research (`gen/nous_research_cap.py <pid>`; integer ids dispatch to the algorithmic judge),
finish-iteration with ceiling $28.5, headline = best_at_budget ($25). Slugs `p<pid>_v4c25`, preds
`artifacts/preds/p<pid>.nous_v4.c25.json`, logs `runs/p<pid>/nous_v4_c25.log`.

| task | Claude (old, ~$25) | Nous old (overspent) | Engram | AIDE | **Nous v4 @ $25** (best_at_budget / final re-judged / total spent) |
|---|---|---|---|---|---|
| p0 | 79.4 (**contaminated**: copied a solution from the shared judge folder); clean SDK re-run: **75.47** @ $25.10 | 89.1 | 68.5 | 0 | 73.48 / 74.30 / $29.09 (1 full iteration inside $25) |
| p5 | 50.0 | 83 | 41 | 44 | **58.00** / 58.00 / $25.99 (beats Claude, Engram, AIDE at $25) |

Nous v5 at $25 (best_at_budget / final re-judged / spent): p0 **74.09 / 75.32 / $26.38**; p5 running. Claude's own p0
variance study (n=3, same old runner) averaged 73.6 [69-79], so the 79.4 single run is its best rep.
| p47 | 94.1 | 95.5 | 94.2 | 96.8 | dropped for v5 |

p0's judge is time-limited, so the same solution re-scores within about +/-2 (75.51 when measured, 74.30 re-judged).

Superseded research results (blocked rule, Claude at ~$25) and leaked runs are kept in
`artifacts/preds/` and `artifacts/preds/leaked_backup/` (with evidence) for provenance only.

**Improvement loop and integrity log:** `NOUS_IMPROVEMENT_LOG.md` (versions v1-v6, results, contamination of the
old Claude p0 baseline, sandbox fixes).

## 6. TODO

1. Finish research runs (above), add score-vs-spend curves, pick the Nous version for the paper.
2. Algorithmic: Nous v4 at $25 on p0, p5, p47 (queued).
3. Engram research runs: held until discussed.
4. Paper: update the case-studies table with the new company case studies.

## 7. How to run (research)

```bash
cd experiments/frontiercs
# Nous on vpc
env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$FCS_VPC_URL ANTHROPIC_API_KEY=$FCS_VPC_KEY \
  OPENAI_BASE_URL=$FCS_VPC_URL OPENAI_API_KEY=$FCS_VPC_KEY \
  python3 -u gen/nous_research_cap.py <task> --slug <slug> --model claude-opus-4-6 --budget 50 --niters 30 \
  --out artifacts/preds/<name>.nous.<tag>.json --logdir ~/frontier/gen_logs
# Claude (SDK) on vpc-int
env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$OPENAI_BASE_URL ANTHROPIC_API_KEY=$OPENAI_API_KEY \
  python3 -u gen/claude_sdk_research_runner.py <task> --slug <slug> --model claude-opus-4-6 --budget 50 \
  --out-dir runs/<dir>/claude_sdk_<tag> --out artifacts/preds/<name>.claude_sdk.<tag>.json
# Engram on vpc-int
OPENAI_BASE_URL=$OPENAI_BASE_URL OPENAI_API_KEY=$OPENAI_API_KEY \
  python3 -u gen/engram_research_cap.py <task> --slug <slug> --budget 50 --out artifacts/preds/<name>.engram.<tag>.json
```

Re-judge a solution: `python3 -c "import sys; sys.path.insert(0,'gen'); import judge_sandbox as J, nous_research_isolated as N; print(J.score(N.evalpy('<task>'), N.probdir('<task>'), open('<sol.py>').read()))"`.
cloudcast's evaluator is stochastic: report the mean of 5 re-judges.

## 8. Where things live

- Preds: `artifacts/preds/` (current), `artifacts/preds/leaked_backup/` (invalid, with evidence).
- Per-run dirs: `runs/<task>/<agent>_<tag>/` (trials, measured archive, transcripts excluded by .gitignore).
- Nous campaigns + measured archives: `~/frontier/gen_logs/` (not in repo). Quarantined `/tmp` dumps:
  `~/frontier/_quarantine_tmp_20261012/`.
- Engram adapter changes: `engram_real/engram_opus_patch.diff`, plus `examples/_common.py` `FCS_EXTRA_PATHS`
  and the research system prompt copy (`handoff_system_prompt_research.txt` = Engram's generic prompt).
