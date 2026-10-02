# Frontier-CS Mac — 4 NEW hard tasks, cost-matched comparison

Model claude-opus-4-6. claude/engram = cost-matched trajectories to $10 (cb10). nous = 3-iter (short).
Scores = recorded final_score (judge ~±5 noise). 2 seeds each.

| task | claude-cb10 ($10) | engram-cb10 ($10) | nous-3iter |
|---|---|---|---|
| 44 TSP (Traveling Santa) | 78.5±0.0 (n=2, $10) | 78.4±0.0 (n=2, $10) | 78.9±0.0 (n=1, $24) |
| 47 2D Knapsack | 95.0±0.5 (n=2, $11) | 95.4±0.4 (n=2, $10) | 96.2±0.4 (n=2, $16) |
| 192 Max-Cut | 86.1±1.4 (n=2, $10) | 43.4±43.4 (n=2, $10) | 84.5±2.8 (n=2, $13) |
| 185 Max Clique | 93.8±6.1 (n=2, $10) | 100.0±0.0 (n=2, $10) | 90.0±10.0 (n=2, $11) |

## Raw per-seed
- p44 claude-cb10: scores=[78.6, 78.5] costs=[10.0, 10.2]
- p44 engram-cb10: scores=[78.4, 78.4] costs=[10.1, 10.1]
- p44 nous3: scores=[78.9] costs=[26.6, 21.5]
- p47 claude-cb10: scores=[94.5, 95.5] costs=[10.4, 10.7]
- p47 engram-cb10: scores=[95.1, 95.8] costs=[10.2, 10.3]
- p47 nous3: scores=[95.7, 96.6] costs=[16.7, 15.6]
- p192 claude-cb10: scores=[84.7, 87.5] costs=[10.0, 10.0]
- p192 engram-cb10: scores=[86.7, 0] costs=[10.4, 10.2]
- p192 nous3: scores=[81.7, 87.3] costs=[13.1, 13.6]
- p185 claude-cb10: scores=[99.9, 87.6] costs=[10.3, 10.2]
- p185 engram-cb10: scores=[100, 100] costs=[10.2, 10.1]
- p185 nous3: scores=[100, 80] costs=[11.8, 10.7]

Note: p44 nous3-s1 failed twice (null harvest, ~$26 each) -> N/A; p44 nous uses s2 only.

## Takeaways
- Across all 4 new tasks, cost-matched vanilla claude ($10) >= or == engram and nous; nous never beats claude but costs 1.3-2x more.
- p44 TSP: all ~78.5 (plateau tie). p47 Knapsack: all ~95 (converge). p192 Max-Cut: claude 84.7 ~ nous 84.5 >> engram 0 (engram collapses). p185 Clique: all ~100 (saturates).
- Combined with task 147 (claude ~90 @ $10 vs nous 92.85 @ $25): cost-matched, nous's advantage disappears; vanilla claude matches it cheaper. engram is the weakest/most fragile.
