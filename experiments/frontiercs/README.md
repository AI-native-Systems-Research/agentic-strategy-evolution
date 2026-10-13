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

### Research — main comparison (opus-4-6, faithful access, Nous v2 lightweight vs Claude SDK minimal prompt) — RUNNING

| task | Nous v2 (lightweight) | Claude (SDK, minimal prompt) | status |
|---|---|---|---|
| grammar_fuzzing | running (`runs/gf/nous_v2_fa46.log`, slug gf_v2fa46, vpc key nous-dam) | **85.70 @ $50.26** (`gf_seed_sql.claude_sdk.fa46.json`) | Nous running; Claude done |
| llm_router | running (`runs/llm_router/nous_v2_fa46.log`, slug router_v2fa46, vpc key 3) | running (`runs/llm_router/claude_min_fa46.log`, slug router_cmin46, vpc litellm key) | started 12:48 / 13:05 |

Backups: Nous v1 (standard design) gf 84.23 @ $49.08 (`gf_seed_sql.nous_v1.fa46.json`); Claude SDK verbose-prompt gf
stopped at $13.6 (85.70, `runs/gf/claude_sdk_fa46.aborted_verbose_prompt/`). Engram held until we discuss.
vpc-int was too slow (first request hung 5 min), so all three concurrent runs use vpc with separate keys; the hung
Claude llm_router attempt is kept at `runs/llm_router/claude_min_fa46.stuck_130354/` ($0 spent).
Stop rules: Claude hard $50; Nous finishes its iteration after $50 (ceiling $57) and records best_at_budget.
Both use the same $15/$75 token ruler (`gen/cost_meter.py`), the same access rule and judge.

Superseded research results (blocked rule, Claude at ~$25) and leaked runs are kept in
`artifacts/preds/` and `artifacts/preds/leaked_backup/` (with evidence) for provenance only.

## 6. TODO

0. **Nous v2 (lightweight design), in progress:** design capped ~30 turns (Opus kept), 2-4 focused arms with
   controls/ablations only when needed, per-arm refine loop, budget-aware iteration sizing. Nous v1 gf
   result (84.23 @ $49.08) is kept as a backup (`artifacts/preds/gf_seed_sql.nous_v1.fa46.json`). Then re-run
   Nous v2 on gf + llm_router; algorithmic re-runs later.


1. Re-run the Claude baseline on the algorithmic tasks (p0, p5, p9, p15, p22, p47 + p0 variance reps) on the
   SDK stack with the shared cost ruler, so the algorithmic Claude column is a true iso-$50 baseline.
2. Paper: update the case-studies table with the new company case studies.

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
