# Frontier-CS agent comparison — START HERE (canonical, 2026-10-06)

Single source of truth for the MLSys Frontier-CS experiments. If other docs conflict with this, this
wins. Branch: **`aiopslab`** (AI-native-Systems-Research/agentic-strategy-evolution).

---

## 0. Isolation / no-cheating protocol (MANDATORY for every run)

Agents run with shell access on a shared filesystem that also holds the judge's **answer files**
(`~/frontier/Frontier-CS/algorithmic/problems/<id>/testdata/*.ans`) and **prior solutions**
(`~/frontier/gen_logs/nous_runs/*/**/solution.cpp`). A bash-enabled agent *could* read those and cheat.
We do not yet hard-sandbox (no container), so isolation is enforced by **prompt-ban + mandatory audit**:

1. **Prompt ban:** every agent prompt explicitly forbids reading/using testdata, answer files, or any
   pre-existing solution (see claude_code_runner.py prompt; add the same to any new runner).
2. **Mandatory audit after EVERY run** — grep the agent's full command/transcript log for forbidden access:
   `grep -niE "testdata|\.ans\b|/problems/[0-9]+/testdata|nous_runs|gen_logs" <console-or-transcript>`
   A run with any real hit is **rejected and re-done**. (Claude: transcript jsonl; Engram: console_output.log;
   AIDE: it only generates code, lower risk, still spot-check.)
3. **Independent re-score:** surprising/high scores (esp. on gate tasks) are re-scored on our go-judge from
   the harvested solution, to confirm the number is real and not a judge artifact.

Audited so far (2026-10-06): Engram re-runs p0/p5/p9/p15/p22 = CLEAN; p15/p22=100 independently re-scored
on our judge = confirmed legit (not cheating). Claude runner has prompt-ban + built-in audit.

## 1. The rule (same for every agent)

**$50 budget, or stop early at max score.** No plateau early-stop. Run each agent on each task until
cumulative spend hits **$50** or the score maxes out, then report **(best score, actual $ spent, wall-clock)**.
- Algorithmic tasks: scored on **our go-judge, 0–100** (continuous partial credit).
- Research tasks: **task-specific metric** (e.g. cloudcast = $ transfer cost, lower is better).
- Same model everywhere: **claude-opus-4-6**. Uniform pricing for token accounting: **$15/M in, $75/M out**.

---

## 2. The four agents (what each is + how to run it)

| Agent | What it is | How it's run |
|---|---|---|
| **Nous** | Our scientific-loop harness (hypothesis → experiment → analyze), wrapping the Claude Agent SDK | `gen/frontier_gen_costbudget.py <pid> --agent nous` (see §5 for the full env) |
| **Engram** | mit-nms/Engram **as-is** (`agentic_handoff`: sequential fresh-context agents + research journal/KB), + our small Frontier-CS patch | **`gen/monitoring/engram_cost_cap.sh <alg_id> 50`** (NOT bare run_engram.sh — see cost warning below) |
| **AIDE** | Weco aideml **as-is** (tree search: draft/debug/improve), + our small Frontier-CS adapter | `gen/aide_frontier.py <pid> --budget 50 --ceiling 99.5 --steps 80` |
| **Claude** | **Real Claude Code CLI itself** — plain `claude -p`, one session, opus-4-6, Bash/Read/Write/Edit + a measure.sh judge, iterates to $50/max. No Nous loop, no harness. | **`gen/claude_code_runner.py <pid> --budget 50 --out-dir runs/p<pid>/claude`** |

Setups (where each agent lives):
- **Nous**: `~/nous_repo` (= this repo checkout). Bin: `~/nous_repo/.venv/bin/nous`.
- **Engram**: `~/engram_repo` (clone @5295858 + `engram_real/engram_opus_patch.diff`); setup `engram_real/setup_engram.sh`. Problems named `cloudcast | fcs_alg_<id> | fcs_res_<id>`.
- **AIDE**: `~/frontier/aideml`, venv `~/frontier/aide-venv`; adapter `gen/aide_frontier.py` (teaches C++17 + go-judge scoring, in-process token cost hook).
- **Claude**: raw bundled `claude` CLI (same one the Nous SDK spawns).
- **Benchmark**: `~/frontier/Frontier-CS`; go-judge Docker on `:8081` (algorithmic). `frontier eval algorithmic <id> <sol.cpp> --json` / `frontier eval research <name> <sol.py> --backend docker`.

---

## 3. The 10 tasks

Constraints in this environment: **no GPU**, **no interactive tasks** (skip any with `interactor.cc`: p69, p79, p211).

Algorithmic (6; 0–100 our judge):
| task | class |
|---|---|
| p0 | geometry / 2D polyomino packing |
| p5 | graph / Hamiltonian path |
| p9 | tree-DP / matching |
| p15 | greedy / permutation (gate — only Nous scores) |
| p22 | ad-hoc / trick (gate — only Nous scores) |
| p47 | 2D rectangular knapsack (+90° rot) — easy, all baselines ~95 (honesty case) |

Research (4; CPU-only, task metric; **AIDE N/A** — adapter is algorithmic-only):
| task | tag |
|---|---|
| cloudcast | ai (multi-cloud routing) |
| llm_router | ai (LLM serving/routing) |
| llm_sql | db (text-to-SQL) |
| poc_generation | security (exploit PoC) |

---

## 4. Results so far (best score / actual $ / wall-clock)

**$50-or-max rule, our judge (algorithmic) / task metric (research).**

Algorithmic:
| task | Nous | AIDE | Engram | Claude ⚠ |
|---|---|---|---|---|
| p0  | 86 / $27 / — | 0 / $50.07 / 68m | 70 / ~$50 / — | ~26 / ~$50 / — |
| p5  | 83 / $46 / — | 44 / $50.28 / 71m | 49 / ~$50 / — | ~39 / ~$50 / — |
| p9  | 100 / $38 / 230m | 95 / $50.16 / 58m | 55 / ~$50 / — | 80 / ~$50 / — |
| p15 | 100 / $32 / — | 0 / $50.41 / 49m | 20 / ~$50 / — | 0 / ~$50 / — |
| p22 | 100 / $4.85 / 19m | 0 / $50.04 / 77m | 0 / ~$50 / — | 0 / ~$50 / — |
| p47 | ~96 / $15–16 / — ⚠ | **TODO** | ~95 / — ⚠ | ~95 / — ⚠ |

Research (cloudcast metric = $ transfer cost, lower better):
| task | Nous | Engram | AIDE | baseline |
|---|---|---|---|---|
| cloudcast | $626 / $9.89 / 57m | ~$624 / ~$52 / — | N/A | naive $1046 (tie at SOTA) |
| llm_router | **TODO** | **TODO** | N/A | |
| llm_sql | **TODO** | **TODO** | N/A | |
| poc_generation | **TODO** | **TODO** | N/A | |

**Data-quality notes (read these — they're why the old docs looked confusing):**
- **Costs:** Nous = exact (summed from `llm_metrics.jsonl`). AIDE = exact (in-process token accounting). **⚠ Engram costs in the tables are WRONG** — they were a `total/agents` approximation labeled `~$50`, but Engram's *actual* logged cost (its own `Total cost:` line) was **$83.6 (p0), $68.9 (p5), $347 (p47)** — it has no `$`-cap and burns ~$6–9/iteration. So the current Engram scores were achieved with **$69–347 of budget, not $50** → the whole Engram column must be re-run under `engram_cost_cap.sh` (see TODO). **Claude (current numbers) = unreliable** (old single_agent runs leaked; actual $100–207) → being replaced by raw Claude Code anyway.
- **Durations:** AIDE = exact (`elapsed_sec`). Nous = only p9 (230m), p22 (19m), cloudcast (57m) retained; others `—`. Engram/Claude durations were not recorded.
- **⚠ Claude column is the OLD method** (Engram `single_agent`), **not** raw Claude Code. It will be **replaced** by raw-Claude-Code reruns (see §6 TODO). Do not treat the current Claude numbers as final.
- **⚠ p47** data is under non-$50 budgets (`nous3` for Nous, `cb10`=$10 for Engram/Claude) → **re-run under $50** for a clean row.
- **Headline (honest):** Nous is best on every algorithmic task at ≤$50 and is the only agent that scores on the gates (p15, p22). On the easy task (p47) everyone ties ~95. cloudcast is a tie with Engram at SOTA.

---

## 5. Exact Nous launch (the one with the fixes — see NOUS_RUN_NOTES.md for why)

```bash
cd <repo>/agentic-strategy-evolution
env -u ANTHROPIC_AUTH_TOKEN \
  ANTHROPIC_BASE_URL=https://ete-litellm.ai-models.vpc.res.ibm.com \
  ANTHROPIC_API_KEY=$IBM_LITELLM_KEY \
  OPENAI_BASE_URL=https://ete-litellm.ai-models.vpc.res.ibm.com \
  OPENAI_API_KEY=$IBM_LITELLM_KEY \
  ./.venv/bin/python -u experiments/frontiercs/gen/frontier_gen_costbudget.py <pid> \
    --agent nous --model claude-opus-4-6 --nous-iters 20 --cost-budget 50 \
    --label <label> --out experiments/frontiercs/nous_gates/preds/p<pid>.<label>.json \
    --logdir ~/frontier/gen_logs
```
Two non-obvious musts (both learned the hard way, 2026-10-05/06):
1. **`env -u ANTHROPIC_AUTH_TOKEN`** — else the bundled CLI sends a conflicting Bearer header → gateway 401 → silent hang.
2. **Silence watchdog = 900s** (in `frontier_gen_costbudget.py`). Backend time-to-first-byte on big subagent calls is 45–696s; a short threshold aborts valid slow responses and fails every iteration.
3. `--cost-budget 50` is **not** enforced for the Nous path — poll `nous_runs/<slug>/**/llm_metrics.jsonl` cumulative cost and kill at $50; the driver then harvests + scores.

Baselines (Engram/AIDE/Claude) use the direct chat API or raw CLI — only Nous needs the token strip.

---

## 6. TODO / remaining work

- [x] **Build the raw-Claude-Code runner** (DONE 2026-10-06): `gen/claude_code_runner.py` — plain
  `claude -p`, one session, opus-4-6, Bash/Read/Write/Edit + measure.sh judge, **auth strip**, live
  cost from the CLI transcript (`CLAUDE_CONFIG_DIR/projects/**/*.jsonl`, per-turn usage incl cache),
  **kills at $50**, re-scores on our judge, and runs a **cheat audit** (greps transcript for
  testdata/.ans/gen_logs/nous_runs). Self-contained run folder `runs/p<pid>/claude/`.
- [~] **IN PROGRESS (2026-10-06): Claude baseline (raw Claude Code) on all 7 tasks**, 2 at a time, $50 cap.
  Command per task: `env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=<vpc> ANTHROPIC_API_KEY=<key>
  OPENAI_BASE_URL=<vpc> OPENAI_API_KEY=<key> ./.venv/bin/python -u gen/claude_code_runner.py <pid>
  --budget 50 --out-dir runs/p<pid>/claude`. Batches: p0,p5 → p9,p15 → p22,p47. cloudcast-Claude needs
  a research measure.sh (claude_code_runner is algorithmic-only) — do last or adapt. WATCH: the bundled
  CLI can stall on slow gateway TTFB (first p47 attempt hung); if a run shows no transcript progress /
  no solution for ~10min, kill+relaunch. Audit each transcript (README §0) + re-score on our judge.
- [ ] **Rerun the Claude baseline (raw Claude Code) on ALL tasks** (p0,p5,p9,p15,p22,p47 + research) to replace the old Engram-single_agent numbers — needed for a consistent Claude column.
- [ ] **⚠ Engram cost-cap rerun — ALL tasks.** The current Engram numbers used $69–347 (not $50) because Engram has no cost cap and we mislabeled cost. Re-run Engram on p0/p5/p9/p15/p22/p47 + research under `gen/monitoring/engram_cost_cap.sh <alg_id> 50`, which polls Engram's real `Total cost:` and kills at $50 (cost logs every 5 iters ≈ $30, so it stops at the first checkpoint ≥ $50 ≈ $60; report best score at the ≤$50 point from the per-iteration Score progression). Discovered 2026-10-06 after a p47 run hit $347.
- [ ] **p47**: run AIDE; re-run Nous/Engram/Claude under $50 (existing data is nous3/cb10).
- [ ] **llm_router, llm_sql, poc_generation**: run Nous, Engram, Claude (AIDE N/A). Research runner = `gen/frontier_research_gen.py`; verify poc_generation is CPU-feasible first.
- [ ] CP6 variance (3× reruns of a subset); CP7 stronger-model (opus5).

### Paper-writing notes (record these)
- **Engram's paper/historical scores ARE reproducible — but at HIGHER cost than $50.** Our audit of
  the original runs showed real LLM spend of $69–84 per algorithmic task, ~$624-transfer cloudcast,
  and uncapped runs reaching $347. Under a *true $50 cap* Engram's scores drop (e.g. p5 49→41,
  cloudcast strong→barely-beats-baseline). So the honest framing is: **the comparison is iso-cost
  ($50) — Engram can match its published numbers given more budget; Nous reaches its scores within
  (often well under) $50.** Mention this explicitly so we're not accused of under-running Engram.
- **Gates are not Nous-exclusive:** properly-run Engram solves p15 and p22 to 100 (verified our judge).
  Reframe away from "only Nous cracks the gates"; the real story is Nous = best-or-tied everywhere +
  cheapest, clear outright wins on p0/p5/p9, and (at iso-$50) stronger on cloudcast.

---

## 7. Where everything lives

- **Runners:** `gen/frontier_gen_costbudget.py` (algorithmic: nous/claude-chat/engram-style), `gen/frontier_research_gen.py` (research), `gen/aide_frontier.py` (AIDE), `gen/monitoring/`.
- **Per-agent result JSONs:** `aide_gates/preds/`, `artifacts/preds/` (originals), `nous_gates/preds/`.
- **Raw logs + per-iteration artifacts (NOT in repo — too large):** `~/frontier/gen_logs/` (and `~/frontier/gen_logs_b/`). Nous per-run: `~/frontier/gen_logs/nous_runs/<slug>/runs/iter-*/` (inputs/solution.cpp, results/score.txt, design_log.md, executor_log.jsonl, llm_metrics.jsonl).
- **Detailed/historical docs:** `NOUS_RUN_NOTES.md` (Nous run recipe + fix history), `todo.md` (checkpoint history), `BEST_AT_50.md` / `RESULTS.md` (older detailed writeups — superseded by this file for the headline numbers).
