# Iso-cost comparison: best score achieved at <= $50 spend (our judge)

Re-derived from existing per-step data (NO extra reruns), per the rule "stop at $50 or max score."
Method: for each agent, take the best score (re-scored on OUR judge) among solutions produced while
cumulative spend was <= $50. Engram: budget-agents k = $50 / (total/agents), re-score the first-k
agents' solutions (`/tmp/best_at_50_engram.py`). Nous: originals already ran UNDER $50, so their
scores are the <=$50 value (and conservative — more budget could only raise them). Claude-agent: see
caveat.

## Algorithmic — best score @ <= $50 (our judge)

| task | Nous | real Engram | Claude-agent | notes |
|---|---|---|---|---|
| p0  | **86** ($27) | 70.0 | ~26 | Claude's 73 needed ~$84; at $50 it's ~26 |
| p5  | **83** ($46) | 49.0 | ~39 | |
| p9  | **100** ($38) | 55.0 | 80 | capped rerun (killed at ~$50 wall-clock proxy); best cpp re-scored 80 on our judge |
| p15 | **100** ($32) | 20.0 | 0 | gate |
| p22 | **100** ($4.85) | 0.0 | 0 | gate |

cloudcast (transfer-cost $, lower=better): Nous **$626** @ $9.89 (<=$50); real Engram ~$624 @ ~$52
(slightly over; its best-at-$50 ~ same, found early); naive $1046. Tie at SOTA.

## Takeaways (iso-$50)
- **Nous is best on every task at <= $50**, and on the gates (p15, p22) it's the only one that scores.
- Capping at $50 barely changes Engram (it runs near $50/agent anyway): 70/49/55/20/0.
- Capping HURTS Claude-agent a lot where its best came late: p0 73 -> ~26 at $50. For p9 the earlier
  "98.5" was a leaked (cost-corrupted) run; a clean capped rerun (killed at the ~$50 wall-clock proxy)
  reaches 80 on our judge, below Nous's 100.
- Net: on the fair iso-$50 axis, **Nous dominates all five algorithmic tasks**; cloudcast is a tie
  with Engram at SOTA. This is stronger and cleaner than the raw final-best table.

## Caveats
- Claude-agent p0/p9 runs leaked (orphaned multiprocessing workers kept spending after kill), so their
  per-checkpoint cost is inflated/unusable -> true best-at-$50 not cleanly derivable for those; p0 ~26
  is from a fixed-watchdog capped run cut at the ~8-min/$50 proxy; p9 is undetermined.
- Engram per-agent cost is approximated as total/agents (no per-agent usage persisted); budget-agent
  cutoff is therefore approximate. p9/p15 had no final usage file (killed mid-agent); treated as <=$50
  since their total spend was ~$45-70 and best was reached early.
- Nous originals are exact (<= $50). Nous reruns to literally $50 were attempted but blocked by an
  intermittent SDK-streaming stall at iter-2 (see NOUS_RERUN_STATUS.md); p0 rerun corroborates (~85 @ $2).
