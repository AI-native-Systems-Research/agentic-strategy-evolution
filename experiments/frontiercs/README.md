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

## 5. Results

### Algorithmic (opus-4-6, go-judge 0-100) — final, kept as is

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
| p0 | 79.4 | 89.1 | 68.5 | 0 | 73.48 / 74.30 / $29.09 (1 full iteration inside $25) |
| p5 | 50.0 | 83 | 41 | 44 | **58.00** / 58.00 / $25.99 (beats Claude, Engram, AIDE at $25) |
| p47 | 94.1 | 95.5 | 94.2 | 96.8 | dropped for v5 |

p0's judge is time-limited, so the same solution re-scores within about +/-2 (75.51 when measured, 74.30 re-judged).

Superseded research results (blocked rule, Claude at ~$25) and leaked runs are kept in
`artifacts/preds/` and `artifacts/preds/leaked_backup/` (with evidence) for provenance only.

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
