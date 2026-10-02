# Frontier-CS Mac results — cost-matched comparison (task 147, AHC ad-placement)

Model: claude-opus-4-6. Judge: local Docker (arm64). Scores are the recorded `final_score`
(single judge eval; judge has ~+/-5 run-to-run variance). Cost = uniform token-based ($15/M in, $75/M out).
Task 8 was dropped (saturated tie; nous SDK hung on it). Curie not wired (see CURIE_SPIKE.md).

| config | score mean+-sd (n) | cost mean |
|---|---|---|
| p8 claude (default ~$2) | 1.0 +- 0.0 (n=3) | $1.5 |
| p8 engram (default ~$2) | 1.0 +- 0.0 (n=3) | $1.7 |
| p147 claude (default ~$2) | 68.6 +- 11.3 (n=3) | $2.1 |
| p147 engram (default ~$2) | 72.0 +- 25.4 (n=3) | $2.2 |
| p147 claude (cost-matched $10) | 90.1 +- 0.1 (n=2) | $10.1 |
| p147 engram (cost-matched $10) | 72.4 +- 10.9 (n=2) | $10.3 |
| p147 nous (full) | 88.5 +- 4.3 (n=2) | $19.8 |

## Raw p147 scores
- p147 claude (default ~$2): [84.7, 60.7, 60.5]
- p147 engram (default ~$2): [36.1, 88.3, 91.5]
- p147 claude (cost-matched $10): [90.2, 89.9]
- p147 engram (cost-matched $10): [61.5, 83.2]
- p147 nous (full): [92.8, 84.2]

## Headline (cost-matched, task 147)
- nous (full): mean ~88.5 at ~$20/run (s1 92.85@$25, s2 84.21@$14.6).
- vanilla claude at matched $10: mean ~90.1 (s1 89.9, s2 90.2) — equals/beats nous at ~half the cost.
- engram-style at matched $10: mean ~72.4 (s1 61.5, s2 83.2) — weakest; handoff/struggle overhead doesn't scale with budget here.
- claude default (~$2): 68.6; engram default (~$2): 72.0 — both climb with budget, claude far more.

**Takeaway:** on this hard task, nous's raw-score lead over the plain driver loop disappears under cost-matching; vanilla Claude given an equal budget matches it at lower cost. Engram-style trails.
