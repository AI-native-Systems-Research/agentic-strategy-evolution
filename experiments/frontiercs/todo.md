# Frontier-CS controlled comparison — next steps

## Protocol (applies to ALL variants)
- Uniform stop rule per task: **ceiling (score 100) OR plateau OR $50 cost ceiling**, whichever first.
- Report **final score AND actual $ spent** for every run. $50 ≈ max we've actually spent (Nous p5 $46, real-Engram cloudcast $52).
- Headline comparison = **cost-quality (score vs $)**, not forced iso-cost. Keep one iso-cost slice (cap all to same per-task $) as a secondary clean number.
- Same model everywhere: **claude-opus-4-6** via litellm (direct VPN, no tunnel). Local on Mac.

## Baseline set (all tool-enabled, same model, same rule)
1. **Claude agent** = Engram's `single_agent` method (Claude Code w/ shell + run_simulation, NO handoff/journal). NOT the chat-completions loop — drop those Claude numbers.
2. **Engram** = real `mit-nms/Engram` `agentic_handoff`, as-is (patched for Opus + macOS, see engram_real/).
3. **AIDE** = Weco AI aideml, unmodified + adapter (see AIDE note below).
4. **Nous**.

## Tasks
cloudcast (research) + algorithmic {p0, p1, p5, p9, p15, p211, p44, p22}. Discriminating subset first: p0, p5, p9, p15, p22 + cloudcast (the gates/headroom where the story lives).

## TODO
- [ ] **Correct cloudcast framing** in RESULTS.md: real Engram ~$624 ≈ Nous $626 ≈ human SOTA $626 (paper $622–662); it's a **tie at SOTA**, not a Nous win. Drop the reimpl $1077 as the headline (keep as a footnote: scalar-feedback reimpl understated Engram).
- [ ] **Rerun real Engram** on the subset (p0, p5, p9, p15, p22) under the $50/plateau rule; cloudcast already at SOTA (~$624) — lock it.
- [ ] **Rerun Nous under the rule** only where it did NOT hit ceiling/plateau/$50:
      - needed: **p0, p211, p44** (stopped at iter cap, <$50, not ceiling).
      - **cloudcast**: rerun longer under $50 **with Engram-style hint prompt** (reveal target + suggest MILP) — test if Nous pushes below $624 toward the $419-style frontier on equal footing.
      - already done (ceiling 100): p1, p9, p15, p22. Borderline (≈$46/time-wall): p5 — optional confirm.
- [ ] **Claude-agent baseline (single_agent, Opus 4.6)**: run on ALL tasks under the rule (replaces the dropped chat-completions Claude).
- [ ] **AIDE baseline**: bring `aide_frontier.py` + adapter from `frontier-mac` onto our branch; install (`~/frontier/aide-venv`); add token-cost accounting (wrap `aide.backend.query`); run on our tasks under the rule. Spec: `experiments/frontiercs/artifacts/mac/AIDE_ADAPTER.md`. Proof: `artifacts/mac/aide_raw/p44-smoke/`, `preds/p44.aide-smoke.json`.
- [ ] **Branch housekeeping**: unify `frontier-mac` AIDE work with our working branch so everything is in one place; persist all runs (preds, logs, journals), update RESULTS.md + REPRO.md, commit + push.

## Fairness notes (bake into the writeup)
- Prompt parity: Engram's cloudcast prompt reveals the target (~$419) + pushes MILP; give Nous the same hints when comparing (above). State it.
- All agents are tool-enabled + same model + same $ rule, so the comparison isolates **methodology**, not tools/model/budget.
- AIDE fidelity: source unmodified (MIT); adapter only swaps Python→C++ prompts and LLM-stdout-review → go-judge scoring; its tree search is inherited (see AIDE_ADAPTER.md).

## Known gotchas
- Nous SDK design turn can hang (seen on p22/cloudcast); relaunch, harvest completed iters.
- Real Engram ≈ $12/agent (huge prompts) → $50 ≈ ~4 agents.
- Engram/AIDE/single_agent all need: go-judge on :8081 (algorithmic), colima docker up, `python:3.11` sandbox image.
- Judges agree (our p22=100 scored 100 by Engram's frontier_cs judge) → scores comparable across harnesses.
