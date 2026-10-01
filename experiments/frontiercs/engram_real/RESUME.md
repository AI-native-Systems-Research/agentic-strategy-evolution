# Real-Engram runs — PAUSED 2026-10-01 ~14:11, resume on request

All Engram processes stopped and monitors cancelled. Setup is intact and reproducible
(`setup_engram.sh`, `engram_opus_patch.diff` @ Engram commit 5295858). Partial artifacts saved
under `partial/`.

## Decided plan (from user)
- Budget: **fair fixed regime** (~5 agents/task or plateau), report ACTUAL cost next to Nous.
- Scope: **discriminating subset first** = cloudcast + fcs_alg {0, 5, 9, 15, 22}.
- Model: claude-opus-4-6 via litellm. Local on the Mac. Cap ~3 concurrent (429 / CPU / docker).

## Status when paused
| task | real-Engram (Opus) partial | spend | vs Nous | state |
|---|---|---|---|---|
| cloudcast | best ~$624 transfer-cost (score 0.0016) | ~$52 (3 of 6 agents) | Nous $626 @ $9.89 | STOPPED mid-run (agent 3) |
| fcs_alg_22 | 0 (gate, agent 1, no valid sol) | — | Nous 100 | STOPPED, incomplete |
| fcs_alg_15 | 0 (gate, agent 1, ~149 calls, no crack) | — | Nous 100 | STOPPED, incomplete |
| fcs_alg_0 / _5 / _9 | not started | — | | QUEUED |

Early read (honest): on **cloudcast**, real Engram ~matches Nous quality ($624 vs $626) but at ~5x
the $ ($52 vs $9.89). On the **gates (p15, p22)**, real Engram scores 0 like Claude — only Nous
cracks them. (These are partial/incomplete; re-run to finalize.)

## How to resume (per task)
```
# env + validation already in place; go-judge on :8081 must be up for fcs_alg
cd ~/engram_repo && source .venv/bin/activate
export OPENAI_API_KEY=... OPENAI_BASE_URL=<litellm> OPENAI_API_BASE=$OPENAI_BASE_URL
# finish/redo cloudcast, then the subset (cap 3 concurrent):
bash <repo>/experiments/frontiercs/engram_real/run_engram.sh cloudcast 6 20
bash <repo>/experiments/frontiercs/engram_real/run_engram.sh fcs_alg_22 5 15
bash <repo>/experiments/frontiercs/engram_real/run_engram.sh fcs_alg_15 5 15
bash <repo>/experiments/frontiercs/engram_real/run_engram.sh fcs_alg_0  5 15
bash <repo>/experiments/frontiercs/engram_real/run_engram.sh fcs_alg_5  5 15
bash <repo>/experiments/frontiercs/engram_real/run_engram.sh fcs_alg_9  5 15
```
Harvest: best "New best score" per run + spend from `results/handoff_<p>_*/*/logs/*usage_stats*.json`.
Re-score any winner on our judge if needed (judges confirmed to agree: our p22=100 scored 100 by
Engram's `frontier_cs` judge). Then add the real-Engram column to RESULTS.md.

## Open follow-up (noted, not done)
Prompt-fairness: Engram's cloudcast prompt reveals the expert target (~$419) + pushes MILP; Nous's
prompt doesn't. Optional matched-prompt Nous rerun. See NOTES.md.
