> ⚠ **SUPERSEDED — read `README.md` first** (the canonical source of truth as of 2026-10-06).
> This file is detailed/historical. In particular, the "Claude-agent" column here is the OLD
> Engram-single_agent method and will be replaced by raw-Claude-Code reruns; p47 is not yet included.

# Iso-cost comparison: best score achieved at <= $50 spend (our judge)

Re-derived from existing per-step data (NO extra reruns), per the rule "stop at $50 or max score."
Method: for each agent, take the best score (re-scored on OUR judge) among solutions produced while
cumulative spend was <= $50. Engram: budget-agents k = $50 / (total/agents), re-score the first-k
agents' solutions (`/tmp/best_at_50_engram.py`). Nous: originals already ran UNDER $50, so their
scores are the <=$50 value (and conservative — more budget could only raise them). Claude-agent: see
caveat.

## Algorithmic — best score @ <= $50 (our judge)   [CORRECTED 2026-10-06]

Engram column = **cost-capped re-runs** (the old numbers used $69–347, not $50 — see README). Score /
LLM-$. Engram cost is the $ at cap-kill (fires at first 5-iter checkpoint >= $50, so ~$56–68).
Claude column = **raw Claude Code under §5.1 sandbox isolation, re-judged, cheat-audit CLEAN**
(updated 2026-10-08; the old Engram-single_agent Claude numbers are retired).

| task | Nous | AIDE | Engram (re-run) | Claude (isolated) | notes |
|---|---|---|---|---|---|
| p0  | **89.1** / $47 | 0 / $50 | 68.5 / $66 | 79.4 / $44 | Nous best (clean $50 rerun, patch-reproduced; orig 86/$27); Claude 2nd |
| p5  | **83** / $46 | 44 / $50 | 41.0 / $58 | 50.0 / $51 | Nous best; Claude beats AIDE/Engram |
| p9  | **100** / $38 | 95 / $50 | 67.8 / $65 | **100** / $15.9 | Nous=Claude=100 |
| p15 | 100 / $32 | 0 / $50 | **100** / <$50 | **100** / $44.5 | NOT a gate for tool-agents: Nous=Engram=Claude=100 |
| p22 | 100 / $4.85 | 0 / $50 | **100** / $68 | 0 / $50 | gate: Nous=Engram=100; Claude=0; AIDE=0 |
| p47 | 95.5 / $51 | **96.8** / $50 | 94.2 / $56 | 94.1 / $45 | easy task — all ~94–97 (honesty case) |

cloudcast (research; total transfer $, LOWER better): Nous **$626**, Claude **659** (isolated, re-judged),
capped Engram ~$942, naive $1046 — Claude near-SOTA (just above Nous, well below Engram). Gates split 3
ways: p15 cracked by Nous/Engram/Claude (not AIDE); p22 cracked only by Nous/Engram.

Research — score-metric (higher better; score / LLM-$), added 2026-10-09 (mirrors README §4):
| task | Nous | Claude | Engram | notes |
|---|---|---|---|---|
| grammar_fuzzing/seed (SQL-parser coverage, pl) | **86.9** / $53.7 | 55.4 / $30.9 | 59.1 / $3.9 | Nous best |
| llm_router (cost-aware routing, ai)            | **59.7** / $51.4 | 55.1 / $18.2 | 52.1 / $3.1 | Nous best; trivial baseline=25.4 |

> ⚠ Claude/Engram cells above are PROVISIONAL — being re-run to a TRUE $50 (the first runs stopped early:
> budget was set to $30, round caps bound first, and Engram had a plateau-stop; all fixed per README §1).
> Nous cells are final (sandboxed, isolated). This table + README §4 get the final api-loop numbers when
> the $50 re-runs finish.
>
> **Isolation (README §0):** Nous (tool agent) ran under `sandbox-exec` + out-of-sandbox judge daemon +
> exploit audit — the un-sandboxed first run gamed BOTH tasks (import-hook coverage 99.6; test-label
> oracle 75.0) and was rejected. Claude/Engram (api-loop) are isolated by construction (no filesystem).
> **llm_sql dropped:** evaluator hard-gates `avg_runtime>1.0s` (unsolvable; even references fail).

AIDE = Weco AIDE (arXiv:2502.13138), unmodified tree search + thin Frontier adapter (C++17 prompts,
go-judge scoring). Ran under the same rule ($50 or ceiling); each task hit the $50 cap. Scores are the
best node re-scored on OUR judge (p5=44 and p9=95 reproduce on isolated re-eval; the go-judge shows
~5pt downward variance under load on time-limited tasks, so p9 occasionally reads 90). Cost is from
in-process token accounting ($15/M in, $75/M out), the same pricing as the other agents. cloudcast not
run for AIDE (adapter is algorithmic-only).

## New-class tasks (6->10 subset expansion) — best score @ <= $50 (our judge)

Added to test whether Nous's win is class-specific. One task from each previously-untested class.
AIDE run first (same $50-or-max rule, in-process cost accounting). Nous/Engram/Claude pending.

| task | class | Nous | AIDE | Engram | Claude |
|---|---|---|---|---|---|
| p26  | dynamic programming | PENDING* | 30 ($50.33) | TBD | TBD |
| p69  | strings             | PENDING* | 0 ($50.32)  | TBD | TBD |
| p79  | math/number theory  | PENDING* | 0 ($50.54)  | TBD | TBD |
| p170 | flow/matching       | TBD | 0 (cut ~$34; best was 0, matching its three sibling gate-fails that reached $50 at 0) | TBD | TBD |

*Nous on p26/p69/p79 attempted 2026-10-02 but BLOCKED by the claude Agent SDK streaming hang: every
DESIGN turn connects to the bundled claude CLI then idles with zero streamed tokens (CPU ~0 for 9+ min),
so no solution is produced. The gateway itself is healthy (direct POST /v1/messages returns HTTP 200 in
~2s), so this is an SDK streaming-path issue, not the gateway, same intermittent hang that blocked the
earlier Nous reruns. Campaigns are saved at ~/frontier/gen_logs/campaign_{26,69,79}.yaml (phase=DESIGN);
retry with `nous resume <camp> --auto-approve --agent sdk` when the streaming condition clears.

AIDE on the new classes: partial on DP (30), zero on strings/math/flow — same pattern as its original
tasks (helps only where incremental search has a score gradient).

cloudcast (transfer-cost $, lower=better): Nous **$626** @ $9.89 (<=$50); Engram **cost-capped ~$942**
@ $59 (barely beats naive $1046 at ~$50 LLM budget — its historical ~$624 needed far more budget);
naive $1046. **At iso-$50, Nous wins cloudcast** (the old "tie at SOTA" assumed Engram's over-budget run).

## Takeaways (iso-$50)   [CORRECTED 2026-10-06]
- **Nous is best-or-tied on every task, and cheapest.** It reaches its scores far under budget
  ($4.85–$46) while AIDE/Engram burn ~$50–68.
- **Outright Nous wins: p0 (86 vs 68.5 vs 0), p5 (83 vs 41 vs 44), p9 (100 vs 67.8 vs 95), cloudcast
  ($626 vs ~$942).**
- **p15/p22 are NOT Nous-only gates.** Properly-run Engram solves both to 100 (verified on our judge,
  audited clean). The gates separate agentic-tool agents (Nous, Engram) from tree-search (AIDE=0),
  not Nous from Engram. (Earlier "only Nous scores" was from under-budgeted Engram runs.)
- **p47 (easy):** everyone ~94–97 (AIDE 96.8 nominally top) — honesty case, no agent dominates.
- **AIDE** helps only where incremental search has a gradient (p9=95, p47=96.8); 0 on p0 and both gates.
- **Engram's cost was previously mislabeled** (~$50) but actually $69–347; under a true cap its scores
  drop. Engram CAN match its published numbers given more budget — this is an iso-cost comparison.
- **Claude column is PENDING** (raw-Claude-Code reruns) — the old numbers are the wrong method + leaked.
- Net on the fair iso-$50 axis: **Nous leads p0/p5/p9/cloudcast and is cheapest; ties Engram on the
  gates (p15/p22=100) and on the easy task (p47); AIDE trails except p9/p47.** (Claude pending.)

## Caveats
- Claude-agent p0/p9 runs leaked (orphaned multiprocessing workers kept spending after kill), so their
  per-checkpoint cost is inflated/unusable -> true best-at-$50 not cleanly derivable for those; p0 ~26
  is from a fixed-watchdog capped run cut at the ~8-min/$50 proxy; p9 is undetermined.
- Engram per-agent cost is approximated as total/agents (no per-agent usage persisted); budget-agent
  cutoff is therefore approximate. p9/p15 had no final usage file (killed mid-agent); treated as <=$50
  since their total spend was ~$45-70 and best was reached early.
- Nous originals are exact (<= $50). Nous reruns to literally $50 were attempted but blocked by an
  intermittent SDK-streaming stall at iter-2 (see NOUS_RERUN_STATUS.md); p0 rerun corroborates (~85 @ $2).
