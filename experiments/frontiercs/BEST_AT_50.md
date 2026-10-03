# Iso-cost comparison: best score achieved at <= $50 spend (our judge)

Re-derived from existing per-step data (NO extra reruns), per the rule "stop at $50 or max score."
Method: for each agent, take the best score (re-scored on OUR judge) among solutions produced while
cumulative spend was <= $50. Engram: budget-agents k = $50 / (total/agents), re-score the first-k
agents' solutions (`/tmp/best_at_50_engram.py`). Nous: originals already ran UNDER $50, so their
scores are the <=$50 value (and conservative — more budget could only raise them). Claude-agent: see
caveat.

## Algorithmic — best score @ <= $50 (our judge)

| task | Nous | AIDE | real Engram | Claude-agent | notes |
|---|---|---|---|---|---|
| p0  | **86** ($27) | 0 ($50.07) | 70.0 | ~26 | AIDE: 124 nodes all compile+run but score 0; Claude's 73 needed ~$84 |
| p5  | **83** ($46) | 44 ($50.28) | 49.0 | ~39 | |
| p9  | **100** ($38) | 95 ($50.16) | 55.0 | 80 | AIDE strongest here; Claude capped rerun re-scored 80 |
| p15 | **100** ($32) | 0 ($50.41) | 20.0 | 0 | gate |
| p22 | **100** ($4.85) | 0 ($50.04) | 0.0 | 0 | gate |

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
| p26  | dynamic programming | TBD | 30 ($50.33) | TBD | TBD |
| p69  | strings             | TBD | 0 ($50.32)  | TBD | TBD |
| p79  | math/number theory  | TBD | 0 ($50.54)  | TBD | TBD |
| p170 | flow/matching       | TBD | 0 (cut ~$34; best was 0, matching its three sibling gate-fails that reached $50 at 0) | TBD | TBD |

AIDE on the new classes: partial on DP (30), zero on strings/math/flow — same pattern as its original
tasks (helps only where incremental search has a score gradient).

cloudcast (transfer-cost $, lower=better): Nous **$626** @ $9.89 (<=$50); real Engram ~$624 @ ~$52
(slightly over; its best-at-$50 ~ same, found early); naive $1046. Tie at SOTA.

## Takeaways (iso-$50)
- **Nous is best on every task at <= $50**, and on the gates (p15, p22) it's the only one that scores.
- **Nous also reaches those scores far under budget** ($4.85-$46), while AIDE, Engram, and Claude burn
  the full $50 and still fall short. Nous wins on both score and cost.
- **AIDE** is the strongest single-task baseline on p9 (95) but scores 0 on p0 and both gates, so its
  tree search helps only where incremental improvement has a gradient; it never cracks the gate tasks.
- Capping at $50 barely changes Engram (it runs near $50/agent anyway): 70/49/55/20/0.
- Capping HURTS Claude-agent a lot where its best came late: p0 73 -> ~26 at $50. For p9 the earlier
  "98.5" was a leaked (cost-corrupted) run; a clean capped rerun reaches 80 on our judge, below Nous's 100.
- Net: on the fair iso-$50 axis, **Nous dominates all five algorithmic tasks** against all three
  baselines (AIDE, Engram, Claude); cloudcast is a tie with Engram at SOTA.

## Caveats
- Claude-agent p0/p9 runs leaked (orphaned multiprocessing workers kept spending after kill), so their
  per-checkpoint cost is inflated/unusable -> true best-at-$50 not cleanly derivable for those; p0 ~26
  is from a fixed-watchdog capped run cut at the ~8-min/$50 proxy; p9 is undetermined.
- Engram per-agent cost is approximated as total/agents (no per-agent usage persisted); budget-agent
  cutoff is therefore approximate. p9/p15 had no final usage file (killed mid-agent); treated as <=$50
  since their total spend was ~$45-70 and best was reached early.
- Nous originals are exact (<= $50). Nous reruns to literally $50 were attempted but blocked by an
  intermittent SDK-streaming stall at iter-2 (see NOUS_RERUN_STATUS.md); p0 rerun corroborates (~85 @ $2).
