# Frontier-CS controlled comparison — TODO

> **WHERE EVERYTHING LIVES** (branch: `aiopslab` on AI-native-Systems-Research/agentic-strategy-evolution)
> All under `experiments/frontiercs/`:
> - **Plan + status + run recipe:** `todo.md` SECTION 3 (the current 10-task plan, status matrix, remaining runs)
> - **How to run Nous (auth + 900s threshold fixes, launch command):** `NOUS_RUN_NOTES.md`  ← read this before any Nous run
> - **Results tables:** `BEST_AT_50.md` (iso-$50, our judge) · `RESULTS.md` (full writeup) · `REPRO.md` (repro steps)
> - **Per-agent result JSONs:** `aide_gates/preds/` · `artifacts/preds/` (originals) · `nous_gates/preds/`
> - **Runners:** `gen/frontier_gen_costbudget.py` (algorithmic) · `gen/frontier_research_gen.py` (research) · `gen/aide_frontier.py` (AIDE) · `gen/monitoring/`
> - **Setup/handoff:** `SETUP_NOTES.md` · `RUN_ON_MAC.md` · `SESSION_HANDOFF.md`
> - **Raw logs + nous_runs artifacts (NOT in repo, too large):** `~/frontier/gen_logs/` (and `~/frontier/gen_logs_b/`)

================================================================
## SECTION 1 — Simple summary (human-readable checkpoints)
================================================================

**Goal:** fair, same-model (Opus 4.6) comparison of 4 agents on Frontier-CS, to show when Nous's
scientific loop helps. The four agents: **Claude-agent → AIDE → Engram → Nous** (all tool-enabled,
same model, same budget rule).

**The rule for every run (UPDATED 2026-10-02):** keep going until the score maxes out (100) OR we
hit **$50** spent — **NO plateau early-stop** (removed). Report the final score AND the dollars spent.
We compare on a score-vs-cost view (quality per dollar), not a forced equal cost. Applies to ALL
variants going forward; set per-run caps high (e.g. Nous --nous-iters 12) so $50 is the binding limit.
NOTE: already-completed Claude-agent runs used --early_stop_patience 3 (plateau); if we want strict
conformance they'd re-run to $50, but their scores already exceed/plateau so it's low-value.

**Where we are:**
- [x] Established 7-task + p22/cloudcast results (with the OLD weak Engram reimpl + a chat-only Claude).
- [x] Got real Engram running locally on Opus; confirmed its judge matches ours.
- [x] Learned cloudcast is a **tie at the top** (Nous $626 ≈ real Engram ~$624 ≈ human expert $626;
      Engram paper $622–662). So cloudcast is NOT a Nous win — fix our writeup.
- [x] AIDE adapter drafted + smoke-tested (on branch frontier-mac).

**What's left (checkpoints):**
1. [x] Fix the cloudcast story in our results → it's a tie at SOTA, not a Nous win. (DONE 2026-10-01)
2. [x] Run the real **Engram** on the hard/gate tasks (p0, p5, p9, p15, p22). (DONE 2026-10-01)
       Result (our judge): Nous beats real Engram on all 5, cheaper: p0 86/74.8, p5 83/49, p9 100/55,
       p15 100/20, p22 100/0. Real Engram > reimpl/Claude but < Nous everywhere. See RESULTS.md +
       engram_real/gates/. LEARNING: real Engram ~$25-30/agent, so $50 cap = max_agents 2 (p0/p5
       overshot to $69-84). Usage not finalized if killed mid-agent → prefer max_agents=2 next time.
3. [x] Then the **Claude *agent*** baseline (Engram `single_agent`, Opus 4.6, tools). (DONE 2026-10-01)
       Our judge: p0 73.3, p5 44.0, p9 98.5, p15 0, p22 0. KEY: tool-enabled Claude nearly solves p9
       (98.5) — p9 is NOT a gate; true gates = p15, p22 (only Nous). COST BUG (fixed): SIGTERM didn't
       kill + multiprocessing-spawn workers orphaned & leaked -> p0/p5/p9 hit $201/$106/$207; p15 clean
       at $37.75 after tree-kill+wall-proxy fix. Costs are upper bounds, not iso-$50. See RESULTS.md +
       claude_agent_gates/. LESSON: for single_agent, watchdog must TREE-KILL (kids first) + wall-clock
       proxy (usage writes late, invisible for stuck runs); macOS ps uses etime not etimes.
4. [~] Re-run **Nous** (p0, p5 iso-rule; cloudcast hinted). BLOCKED 2026-10-02 by a reproducible
       Nous `--agent sdk` streaming hang (gateway/CLI/deepagents all fine; only Nous streaming wedges
       after ~1 iter; 3 relaunches). See engram_real/NOUS_RERUN_STATUS.md. FALLBACK (sound): originals
       ran UNDER $50 (p0 86@$27, p5 83@$46); Nous keeps best across iters so more budget can only hold
       or raise them -> 86/83 are conservative lower bounds under the rule, and Nous already beats the
       baselines there. p9/p15/p22 hit ceiling 100 (already compliant). Not required for the conclusion;
       retry reruns + cloudcast-hinted when the SDK-stream hang clears.
5. [ ] Add **AIDE** as a 4th baseline and run it on our tasks.
6. [ ] **Variance check:** pick a small subset (1–3 tasks), rerun each variant **2 more times**
       (3 total), and report run-to-run variance per variant.
7. [ ] **Stronger-model check:** same 1–3 task subset, rerun ALL variants with a better model
       (e.g. opus5) to see how the picture changes.

**Standing rule (every step):** when a step finishes, PERSIST before moving on — save artifacts
(preds, logs, journals), update the results table + repro doc, and commit & push. Persistence is NOT
a separate final step; it's part of completing each checkpoint. Keep everything on one branch.

Order note: Engram FIRST (expensive pacing item), then Claude-agent reuses the same harness.

**The honest headline:** the Nous advantage lives on the **gate tasks** (p15, p22, p9) where the
other agents score ~0; cloudcast and the easy task (p1) are ties. We keep the losses in (p44) too.

================================================================
## SECTION 3 — FINAL 10-TASK PLAN (revised 2026-10-06, MLSys submission)   [branch: aiopslab]
================================================================

**Framing:** "10 representative Frontier-CS tasks" = algorithmic classes + ML-systems research tasks.
Hard constraints in THIS environment: **no GPU**, **no interactive tasks** (skip any with
`interactor.cc`: p69, p79, p211). Same model (Opus 4.6), **$50-or-max** rule, **our go-judge (0-100)**
for algorithmic, **task-specific metric** for research.

**The 10 tasks:**

Algorithmic (6; 0-100 our judge):
| task | class | note |
|---|---|---|
| p0  | geometry / 2D polyomino packing | |
| p5  | graph / Hamiltonian path | |
| p9  | tree-DP / matching | |
| p15 | greedy / permutation (lexicographic) | gate — only Nous scores |
| p22 | ad-hoc / trick | gate — only Nous scores |
| p47 | 2D rectangular knapsack (+90 deg rotations) | EASY — all baselines ~95; honesty case, NOT a Nous win |

Research (4; CPU-only, task-specific metric; **AIDE N/A** — adapter is algorithmic-only):
| task | tag | note |
|---|---|---|
| cloudcast | ai (multi-cloud routing) | tie at SOTA (Nous $626 ~ Engram) |
| llm_router | ai (LLM serving/routing) | NEW |
| llm_sql | db (text-to-SQL) | NEW |
| poc_generation | security (exploit PoC) | NEW — 10th, widens taxonomy to ai+db+security |

**Status matrix (best score; cost). "cb10/nous3" = ran under an OLD budget, re-run under $50 for a clean row.**
| task | Nous | AIDE | Engram | Claude |
|---|---|---|---|---|
| p0  | 86 ($27) | 0 ($50) | 70 | ~26 |
| p5  | 83 ($46) | 44 ($50) | 49 | ~39 |
| p9  | 100 ($38) | 95 ($50) | 55 | 80 |
| p15 | 100 ($32) | 0 ($50) | 20 | 0 |
| p22 | 100 ($4.85) | 0 ($50) | 0 | 0 |
| p47 | ~96 (nous3,$15-16) | **TODO** | ~95 (cb10) | ~95 (cb10) |
| cloudcast | $626 @ $9.89 | N/A | ~$624 | TBD |
| llm_router | **TODO** | N/A | **TODO** | **TODO** |
| llm_sql | **TODO** | N/A | **TODO** | **TODO** |
| poc_generation | **TODO** | N/A | **TODO** | **TODO** |

**p47 caveat:** existing data is under `cb10` ($10 budget) / `nous3`/`ctrl` variants, NOT the $50 rule.
Scores are indicative (everyone ~95) but for a consistent row, re-run under $50 + re-score on our judge.
Files: ~/frontier/gen_logs/nous_runs/frontier-47-{nous3-s1,nous3-s2,ctrl}; frontier_47_{engram,claude}-cb10-s*.history.json. AIDE p47 not run.

**Remaining runs:** p47->AIDE (+optional $50 re-run of Nous/Engram/Claude); llm_router->{Nous,Engram,Claude};
llm_sql->{Nous,Engram,Claude}; poc_generation->{Nous,Engram,Claude}.

**CRITICAL run config — full recipe in `experiments/frontiercs/NOUS_RUN_NOTES.md`:**
- Nous (`--agent sdk`) MUST strip the inherited fleet token, scoped to the child:
  `env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=https://ete-litellm.ai-models.vpc.res.ibm.com
   ANTHROPIC_API_KEY=$IBM_LITELLM_KEY OPENAI_BASE_URL=<same> OPENAI_API_KEY=$IBM_LITELLM_KEY ...`
  Omitting this -> bundled CLI sends a conflicting Bearer header -> gateway 401 -> silent hang.
- Silence watchdog is **900s** (`turn_silence_threshold_seconds` in frontier_gen_costbudget.py). Do NOT
  lower it: backend TTFB on big subagent calls is 45-696s; a short threshold aborts valid slow responses
  and fails every iteration (the Oct-5 incident). max_turns 80/120 (defaults.yaml). Model Opus 4.6.
- `--cost-budget 50` is enforced for claude/engram paths but **NOT the nous path** -> for Nous, poll
  cumulative cost from `nous_runs/<slug>/**/llm_metrics.jsonl` and kill at $50 (driver then harvests).
- Baselines (claude/engram/aide) use the direct chat API, no auth-token issue.
- **Research runner = `gen/frontier_research_gen.py`** (the algorithmic `frontier_gen_costbudget.py`
  can't eval research). Research eval is CPU/docker: `frontier eval research <t> <sol.py> --backend docker`.
  Confirmed no GPU/API dep for cloudcast/llm_router/llm_sql; verify poc_generation before long runs.

**Still open:** CP6 variance (3x reruns of a subset), CP7 stronger-model (opus5).

================================================================
## SECTION 2 — Agent details (for me: commands, paths, gotchas)
================================================================

### Protocol specifics
- Stop rule: ceiling(100) / plateau / $50 ceiling. Report (score, actual $). $50 ≈ observed max.
- Primary analysis: cost-quality (score vs $) per task; secondary: one iso-cost slice.
- Model `claude-opus-4-6`; litellm DIRECT via VPN (OPENAI_BASE_URL, no :8443 tunnel). Local Mac.
- Judges agree across harnesses (our p22=100 scored 100 by Engram's frontier_cs judge) → comparable.

### Baseline mechanics
- **Claude-agent** = Engram's `single_agent` method (tools: shell + run_simulation, docker sandbox,
  early-stop; NO handoff/journal/KB). Entrypoint `examples/single_agent_example_usage.py`. Runs on
  claude-opus-4-6 via the SAME patched Engram env. DROP the old chat-completions Claude numbers.
- **Engram** = real `agentic_handoff`. Setup: engram_real/setup_engram.sh (clone@5295858 + apply
  engram_opus_patch.diff + venv + submodule + pip -e frontier_cs). Run: engram_real/run_engram.sh
  <problem> <max_agents> <timeout_min>. Problems: cloudcast, fcs_alg_<id>, fcs_res_<id>.
- **AIDE** = Weco aideml (MIT, ~/frontier/aideml), adapter experiments/frontiercs/gen/aide_frontier.py
  (ON frontier-mac — cherry-pick to our branch). venv ~/frontier/aide-venv. 3 monkeypatch hooks
  (determine_provider→openai, query user-slot relocation, extract_code C++-aware). Spec:
  artifacts/mac/AIDE_ADAPTER.md. Smoke proof: artifacts/mac/aide_raw/p44-smoke/, preds/p44.aide-smoke.json.
  TODO add token-cost accounting (wrap aide.backend.query) — it doesn't surface usage.
- **Nous** = run_campaign via ~/nous_repo (symlink to this repo). Runners: gen/frontier_gen.py,
  gen/frontier_gen_costbudget.py; research gen/frontier_research_gen.py.

### Nous rerun classification (under the rule)
- DONE (hit ceiling 100): p1, p9, p15, p22.
- RERUN (stopped at iter cap, <$50, no plateau): p0 (86@$27), p211 (87@$36), p44 (69@$29).
- cloudcast: rerun longer under $50 WITH Engram-style hint prompt (reveal ~target + suggest MILP).
- p5 (83@~$46): borderline (≈budget/time-wall) — optional confirm.

### cloudcast numbers (for the correction)
- Nous $626 @ $9.89 | real Engram ~$624 @ ~$52 (locked, agent 3/6) | human SOTA $626 | Engram paper
  $622–662 (o3/gpt-5.2) | evolutionary baselines $640–696 | naive $1046 | OLD reimpl Engram $1077 (drop).

### Gotchas
- Nous SDK design turn can hang (p22 iter1, cloudcast iter3). Relaunch; harvest completed iters.
- Real Engram ≈ $12/agent (800K-token prompts) → $50 ≈ ~4 agents.
- Needs: go-judge :8081 (algorithmic), colima docker up, python:3.11 sandbox image.
- macOS: ADRS evaluator needs fork context (in patch); spawn can't pickle its timeout wrapper.
- Branch: AIDE work is on frontier-mac; real-Engram + reruns on aiopslab. Unify.

### Variance + stronger-model checks (todo 7, 8)
- Subset: pick 1–3 tasks spanning regimes (e.g. a gate like p15/p22 + a headroom like p0 or cloudcast).
- Variance: 3 runs/variant total (2 extra) on the subset; report mean ± spread (judge ±5 noise +
  agent stochasticity). Nous ceilings (100) are deterministic; the discriminating/headroom ones vary.
- Stronger model: rerun all variants on opus5 (`aws/claude-opus-5`). Needs the model added to the
  Engram `--model` allowlist + pricing (extend engram_opus_patch.diff) and AIDE routing; Nous just
  takes --model. Same $50/plateau rule; report how the gaps shift with a stronger base model.

### Persistence
- preds → artifacts/preds/; Engram journals/kb + logs → engram_real/ ; Nous campaigns → artifacts/nous_runs/.
- Update RESULTS.md + REPRO.md; commit + push.
