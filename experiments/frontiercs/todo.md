# Frontier-CS controlled comparison — TODO

================================================================
## SECTION 1 — Simple summary (human-readable checkpoints)
================================================================

**Goal:** fair, same-model (Opus 4.6) comparison of 4 agents on Frontier-CS, to show when Nous's
scientific loop helps. The four agents: **Claude-agent → AIDE → Engram → Nous** (all tool-enabled,
same model, same budget rule).

**The rule for every run:** keep going until the score maxes out (100), stops improving (plateau),
or we hit **$50** — then report the final score AND the dollars spent. We compare on a
score-vs-cost view (quality per dollar), not a forced equal cost.

**Where we are:**
- [x] Established 7-task + p22/cloudcast results (with the OLD weak Engram reimpl + a chat-only Claude).
- [x] Got real Engram running locally on Opus; confirmed its judge matches ours.
- [x] Learned cloudcast is a **tie at the top** (Nous $626 ≈ real Engram ~$624 ≈ human expert $626;
      Engram paper $622–662). So cloudcast is NOT a Nous win — fix our writeup.
- [x] AIDE adapter drafted + smoke-tested (on branch frontier-mac).

**What's left (checkpoints):**
1. [x] Fix the cloudcast story in our results → it's a tie at SOTA, not a Nous win. (DONE 2026-10-01)
2. [ ] Run the real **Engram** on the hard/gate tasks (p0, p5, p9, p15, p22). (cloudcast already done.)
3. [ ] Then the **Claude *agent*** baseline (Engram `single_agent`, same harness — quick follow-on).
       Use the Claude agent with tools, NOT the old chat-only loop.
4. [ ] Re-run **Nous** only where it stopped early at a cap (p0, p211, p44) + a longer cloudcast run
       with the same hints Engram's prompt gets (fairness).
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
