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
| **Claude** | **Real Claude Code CLI itself** — plain `claude -p`, opus-4-6, Bash/Read/Write/Edit + a measure.sh judge, iterates until **$50 or score 100** (resumes via `--continue`, never self/plateau-stops). No Nous loop, no harness. See §5.1 for exact flags/prompt/stopping. | **`gen/claude_code_runner.py <pid> --budget 50 --max-score 100 --out-dir runs/p<pid>/claude`** |

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

Score / LLM-$. Engram column = **cost-capped reruns** (corrected 2026-10-06 — the old numbers used
$69–347, not $50; see note below). Claude column = **raw Claude Code** (`claude_code_runner.py`),
budget-or-max rule, run under **sandbox isolation** (sandbox-exec deny `~/frontier` + out-of-sandbox
judge daemon; see §5.1) and re-judged from persisted artifacts. **Algorithmic column complete 2026-10-08;
cloudcast (research) pending.**

Algorithmic (our judge, 0–100):
| task | Nous | AIDE | Engram (capped) | Claude (raw CC) |
|---|---|---|---|---|
| p0  | **86** / $27 | 0 / $50 | 68.5 / $66 | 79.4 / $44 ✓iso |
| p5  | **83** / $46 | 44 / $50 | 41 / $58 | 50.0 / $51 ✓iso |
| p9  | **100** / $38 | 95 / $50 | 67.8 / $65 | **100** / $15.9 ✓iso |
| p15 | **100** / $32 | 0 / $50 | **100** / <$50 | **100** / $44.5 ✓iso |
| p22 | **100** / $4.85 | 0 / $50 | **100** / $68 | 0 / $50 ✓iso |
| p47 | 95.5 / $51 | **96.8** / $50 | 94.2 / $56 | 94.1 / $45 ✓iso |

Claude-baseline validity — **algorithmic column COMPLETE (2026-10-08)**, all 6 run under §5.1 sandbox
isolation, re-judged from persisted artifacts, cheat-audit **CLEAN** (0 testdata accesses):
- Gates: Claude **cracks p15 (100)** but **fails p22 (0)** — the only algorithmic task it zeroes.
  So the gates split 3 ways: Nous=Engram=100 on both; Claude 100/0; AIDE 0/0.
- Headroom: p0 79.4 (vs Nous 86), p5 50.0 (beats AIDE 44 / Engram 41, below Nous 83), p9 100.
- Easy: p47 94.1 (all agents ~94–97).
- **⚠ p0's FIRST (pre-isolation) run was rejected for cheating** — it read hidden `testdata/*.in` and an
  answer `.ans` under prompt-ban-only isolation. That incident is why all Claude algorithmic runs now
  use the §5.1 sandbox (sandbox-exec deny `~/frontier` + out-of-sandbox judge daemon).

Research (cloudcast metric = $ transfer cost, lower better):
| task | Nous | Engram (capped) | AIDE | baseline |
|---|---|---|---|---|
| cloudcast | **$626** / $9.89 | ~$942 / $59 | N/A | naive $1046 |
| llm_router | **TODO** | **TODO** | N/A | |
| llm_sql | **TODO** | **TODO** | N/A | |
| poc_generation | **TODO** | **TODO** | N/A | |

**Data-quality notes:**
- **Costs:** Nous = exact (summed from `llm_metrics.jsonl`). AIDE = exact (in-process token accounting).
  Engram = the $ at cost-cap kill (fires at the first 5-iter checkpoint ≥ $50, so ~$56–68). The earlier
  Engram numbers were mislabeled `~$50` but actually cost **$69–347** (no built-in cap, ~$6–9/iter); the
  capped reruns above are the corrected iso-cost figures. Claude = cache-aware estimate from the CLI
  transcript (authoritative live number used for the $50 kill).
- **Gates are NOT Nous-only.** Properly-run (capped) Engram also solves p15 and p22 to **100** (verified
  on our judge, audited clean). The gates separate agentic-tool agents (Nous, Engram) from tree-search
  (AIDE = 0), not Nous from Engram. The earlier "only Nous scores the gates" came from under-budgeted
  Engram runs and is retired.
- **Claude column = raw Claude Code** (`claude_code_runner.py`), replacing the old leaked
  Engram-`single_agent` numbers. Only **p5 = 35 @ $14.8** is banked, and it is a **lower bound**
  (stopped early by a gateway stall, not by $50 or the ceiling). p0/p9/p15/p22/p47 + research are in
  progress; do not cite the Claude column until each has a clean `pred.json`.
- **cloudcast at iso-$50:** Nous **$626** @ $9.89 beats capped Engram **~$942** @ $59 (Engram's historical
  ~$624 needed far more budget). The old "tie at SOTA" assumed Engram's over-budget run.
- **Headline (honest):** Nous is **best-or-tied on every task and cheapest** — it reaches its scores at
  $4.85–$46 while AIDE/Engram burn $50–68. Outright Nous wins: **p0 (86 vs 68.5 vs 0), p5 (83 vs 41 vs
  44), p9 (100 vs 67.8 vs 95), cloudcast ($626 vs ~$942)**. Ties Engram on the gates (p15/p22 = 100) and
  on the easy task (p47 ~94–97). AIDE trails except p9/p47.

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

**TODO for next Nous runs (user directive 2026-10-07): adopt the new CLI + SDK in Nous too.** The raw
Claude baseline now uses CLI **2.1.292** (`npm i -g @anthropic-ai/claude-code@2.1.292`, wired via
`CLAUDE_CLI_PATH=/opt/homebrew/bin/claude`) with `BUN_FEATURE_FLAG_DISABLE_IO_POOL=1` +
`CLAUDE_CODE_MAX_RETRIES=40`, which fixed the connection-pool hang. For Nous: `pip install -U
claude-agent-sdk` in `~/nous_repo/.venv` (refreshes its bundled `claude`, currently the older 2.1.286)
and set the same env on the SDK child. **Re-baseline Nous paper numbers after upgrading** — do not mix
pre/post-upgrade numbers in one comparison.

---

## 5.1 Claude baseline — exact setup (flags, config, prompt, stopping)

The Claude baseline is the **plain bundled Claude Code CLI** (the same binary the Nous SDK spawns),
run headless. Driver: `gen/claude_code_runner.py`. No Nous loop, no Engram journal — just the model +
tools + the judge.

**CLI invocation** (`claude_code_runner.py`):
```
claude -p "<prompt>" --output-format stream-json --verbose --model claude-opus-4-6 \
  --permission-mode bypassPermissions --allowedTools Bash Read Write Edit --max-turns 200
```
Resumed sessions use `claude --continue -p "<push prompt>"` with the same flags.

**Environment** (set by the runner; key/URL come from the shell, never hardcoded):
- `env -u ANTHROPIC_AUTH_TOKEN` — strip the inherited fleet token, else two auth headers → gateway
  401/silent hang.
- `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` (+ `OPENAI_*` mirror) — the IBM litellm gateway + main key,
  taken from the environment (laptop-direct = the `vpc-int` endpoint).
- `BUN_FEATURE_FLAG_DISABLE_IO_POOL=1` + `CLAUDE_CODE_MAX_RETRIES=40` — **the connection-pool-hang fix**
  (bundled `claude` is a Bun binary that reuses a keep-alive socket the gateway drops between turns;
  disabling the IO pool forces a fresh connection per request).
- Timeouts: first-byte 90s, idle 300s, API 300s, connect 20s. Telemetry/autoupdater disabled.
- `CLAUDE_CONFIG_DIR=<run>/cfg` — isolates the per-turn transcript (and is git-ignored).

**cwd (isolation):** only `statement.txt`, `measure.sh`, and a placeholder `solution.cpp` are placed in
the agent's working dir. `measure.sh` compiles `solution.cpp`, runs the **official go-judge**, and
prints `SCORE: <0-100>`.

**Prompt (intent):** solve Frontier-CS algorithmic #pid; read `statement.txt`; write C++17 to
`solution.cpp`; run `./measure.sh` to score; iterate to maximize. It is told **not to stop until it
reaches the ceiling** (never "good enough" / "cannot improve"). Hard rules: solve algorithmically; do
**not** read/use testdata or answer files; do **not** copy any pre-existing solution.

**Stopping rule — budget OR max score, nothing else:**
- The driver polls cache-aware cost from the transcript every 10s and **kills the instant cumulative
  cost ≥ $50** (`stop_reason=budget`).
- If the judge score reaches `--max-score` (100; gates are all-or-nothing but still top out at 100),
  it stops (`stop_reason=max_score`).
- If a `-p` session ends below the ceiling with budget remaining, the runner **resumes it
  (`--continue`)** and pushes it to keep trying — the agent cannot self/plateau-stop.
- Safety valve only: if a resumed session adds ~no cost (agent refuses to engage at all),
  `stop_reason=agent_will_not_continue` (flagged; distinct from a plateau, which keeps spending and
  runs on to budget).

**Trial persistence:** every scored solution is copied to `runs/p<pid>/claude/trials/t<n>.score<s>.cpp`
and appended to `trials.jsonl`; the best-scoring one is kept as `solution.best.cpp` and is what
`pred.json` reports as `final_score` (best at ≤ budget, per the rule).

**After stop:** re-score on our judge, run the cheat audit (grep transcript for
`testdata|.ans|gen_logs|nous_runs`; must be `[]`), write `pred.json`.

### Gateway stall + the fresh-connection proxy (REQUIRED launch step, root-caused 2026-10-07)

Symptom: every run froze at the first hard turn (`turns=3`, no solution written). Root cause: Claude
Code runs opus-4-6 with **extended thinking** (`thinking:{"type":"adaptive"}` +
`output_config:{"effort":"high"}`, inherited from `~/.claude/settings.json`). The IBM litellm->Bedrock
gateway **buffers the thinking phase and emits no bytes until the first visible output**, so first-byte
latency scales with think duration. On hard/heavy turns that latency **intermittently** crosses a ~60s
idle/first-byte timeout on an intermediate hop, and the silent connection is killed before any byte
arrives (`RemoteDisconnected` ~60s, or no byte at all). It is NOT a clean deterministic bug: replaying
a *light* request with thinking on often returns in ~18s, but replaying the actual captured heavy
request (130KB, 24 tools, real hard problem) timed out at 90s with zero bytes. The identical heavy
request with `thinking` removed returns the first byte in ~10-40s and completes. Ruled out (direct curl
always works): key, URL, auth (Bearer vs x-api-key), CLI binary (v131 vs v286), request size,
streaming, prompt caching. The lever is think-duration vs the ~60s cut; disabling thinking keeps
first-byte in the safe band so turns complete (verified: p0 ran normally once thinking was stripped).

Fix = run through `gen/fresh_conn_proxy.py`, a tiny local reverse proxy that (1) opens a FRESH
`Connection: close` socket to the gateway per request (no dead-socket reuse), (2) retries fast on a
wedged attempt (first-byte cutoff 55s, up to 12 tries, re-dialing just before the gateway's ~60s cut),
and (3) **strips the `thinking` field** so the baseline runs without extended thinking (the gateway
cannot stream thinking; this is an infra limitation, not a Claude Code one).

```bash
# 1. start the proxy against the gateway (key/URL from env, never hardcoded)
./.venv/bin/python experiments/frontiercs/gen/fresh_conn_proxy.py \
  --port 8900 --upstream "$ANTHROPIC_BASE_URL" &
# 2. point the runner's ANTHROPIC_BASE_URL at the proxy
env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=http://127.0.0.1:8900 ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  OPENAI_BASE_URL="$ANTHROPIC_BASE_URL" OPENAI_API_KEY=$ANTHROPIC_API_KEY \
  ./.venv/bin/python -u experiments/frontiercs/gen/claude_code_runner.py <pid> \
  --budget 50 --max-score 100 --out-dir experiments/frontiercs/runs/p<pid>/claude &
```

**Paper fairness note:** because of this gateway limitation the Claude baseline runs with extended
thinking **disabled**. State this explicitly; it is a backend constraint (thinking cannot be streamed
through this gateway), not a choice to weaken the baseline. `gen/repro_thinking_stall.py` is a
self-contained reproduction to hand to the litellm admins (thinking-ON stalls >90s with zero bytes;
thinking-OFF answers in seconds).

---

## 6. TODO / remaining work

- [x] **Build the raw-Claude-Code runner** (DONE 2026-10-06): `gen/claude_code_runner.py` — plain
  `claude -p`, one session, opus-4-6, Bash/Read/Write/Edit + measure.sh judge, **auth strip**, live
  cost from the CLI transcript (`CLAUDE_CONFIG_DIR/projects/**/*.jsonl`, per-turn usage incl cache),
  **kills at $50**, re-scores on our judge, and runs a **cheat audit** (greps transcript for
  testdata/.ans/gen_logs/nous_runs). Self-contained run folder `runs/p<pid>/claude/`.
- [~] **Claude baseline (raw Claude Code) on 7 tasks — reruns in progress (2026-10-07, off-peak).**
  Stopping rule is now strictly **budget ($50) OR max score (100)** — the runner resumes the session
  (`--continue`) whenever the agent yields below the ceiling with budget left, so no self/plateau-stop.
  Status: **p5 = 35.0 @ $14.8 (CLEAN audit) banked but LOWER BOUND** (stopped early by a gateway stall,
  not $50/ceiling; solution saved at runs/p5/claude/solution.score35.cost14_8.cpp — rerun for a clean
  number). p0, p9, p15, p22, p47, cloudcast = STILL TODO.
  - **Why paused:** the IBM litellm gateway hit a sustained ~70-min bad window the evening of 2026-10-06
    where even a plain `curl` intermittently timed out (90s, 0 bytes). During bad windows the CLI cannot
    complete a turn; runs just retry. This is gateway load/health, not our code. **Run off-peak.**
  - **Root cause of the earlier wedging (FIXED, verified):** the bundled `claude` is a **Bun** binary
    whose HTTP connection pool reuses a keep-alive socket the gateway silently drops between turns →
    every run wedged ~turn 5. Fix baked into `claude_code_runner.py`: `BUN_FEATURE_FLAG_DISABLE_IO_POOL=1`
    + `CLAUDE_CODE_MAX_RETRIES=40` + first-byte/idle/connect timeouts. p0 crossed its t=5 wall with ZERO
    retries once set; a pool-enabled control stayed stuck. **Apply the same env to the Nous SDK path**
    (same Bun binary) — this is very likely the real cure for the Nous "SDK hang".
  - **Optional:** bundled CLI is Bun build 2.1.286; npm latest is 2.1.292 (marginal). Could try upgrading
    + pointing `CLAUDE_CLI_PATH` at the newer binary (leaves the SDK-bundled one, so Nous unaffected).
  - **LAUNCH (turnkey, runner has the fix baked in), 2 at a time:**
    ```bash
    cd <repo>/agentic-strategy-evolution
    # Key + URL come from the environment — NEVER hardcode the key in a file. Set these env vars in your
    # shell rc (the laptop-direct endpoint is vpc-int with the main litellm key):
    U=$ANTHROPIC_BASE_URL; K=$ANTHROPIC_API_KEY   # e.g. U=https://ete-litellm.ai-models.vpc-int.res.ibm.com
    caffeinate -dimsu &                      # keep mac awake while running
    for p in 0 9; do                          # batch 1; then 15 22; then 47
      env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$U ANTHROPIC_API_KEY=$K \
        OPENAI_BASE_URL=$U OPENAI_API_KEY=$K \
        ./.venv/bin/python -u experiments/frontiercs/gen/claude_code_runner.py $p \
        --budget 50 --max-score 100 --out-dir experiments/frontiercs/runs/p$p/claude \
        > /tmp/p${p}_claude.out 2>&1 &
    done
    ```
    Then: on finish, `cat runs/p<pid>/claude/pred.json` has final_score (best across trials) + cost_est +
    sessions + stop_reason (`budget` | `max_score` | `agent_will_not_continue`) + cheat_audit_hits (must
    be `[]`). All scored trials are kept under `runs/p<pid>/claude/trials/` + `trials.jsonl`; the best is
    `solution.best.cpp`. cloudcast-Claude still needs a research measure.sh (runner is algorithmic-only) —
    adapt or do last. A healthy run shows turns climbing with low retries; if a run sits at the same turn
    with retries creeping, the gateway is in a bad window — wait, don't kill (MAX_RETRIES=40 survives it).
- [ ] **Rerun the Claude baseline (raw Claude Code) on ALL tasks** (p0,p5,p9,p15,p22,p47 + research) to replace the old Engram-single_agent numbers — needed for a consistent Claude column.
- [ ] **⚠ Engram cost-cap rerun — ALL tasks.** The current Engram numbers used $69–347 (not $50) because Engram has no cost cap and we mislabeled cost. Re-run Engram on p0/p5/p9/p15/p22/p47 + research under `gen/monitoring/engram_cost_cap.sh <alg_id> 50`, which polls Engram's real `Total cost:` and kills at $50 (cost logs every 5 iters ≈ $30, so it stops at the first checkpoint ≥ $50 ≈ $60; report best score at the ≤$50 point from the per-iteration Score progression). Discovered 2026-10-06 after a p47 run hit $347.
- [ ] **p47**: run AIDE; re-run Nous/Engram/Claude under $50 (existing data is nous3/cb10).
- [ ] **More research tasks (CPU-only, offline — verified feasible 2026-10-06).** Add for tag diversity
  (cloudcast=ai already done; pick ones in NEW tags to show Nous isn't class-specific):
  - **grammar_fuzzing** (tag `pl`): `python:3.11-slim`, dind:false, 300s, `datasets: []`, deps via
    `uv_project: resources`. Smallest/most-trivial (232K). Variants `grammar_fuzzing_sql_seed` + fuzzer.
  - **llm_sql** (tag `db`): `datasets: []`, bundled CSVs (beer/BIRD/movies/PDMX, 69M), 1800s, uv deps. CPU.
  - **llm_router** (tag `ai`): `datasets: []`, uv deps, `evaluator.py`+`run_evaluator.sh` (1.1M). CPU, but
    duplicates cloudcast's `ai` tag → lower priority than the two above.
  - **poc_generation** (tag `security`): CPU-feasibility NOT yet verified — check before committing.
  **Recommended 2 to add next: grammar_fuzzing (pl) + llm_sql (db)** → research spans ai/db/pl.
  Run Nous, Engram, Claude (AIDE N/A). Research runner = `gen/frontier_research_gen.py`; eval =
  `frontier eval research <name> <sol.py> --backend docker`. Claude runner is algorithmic-only → needs a
  research measure.sh variant (wrap `frontier eval research`).
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
