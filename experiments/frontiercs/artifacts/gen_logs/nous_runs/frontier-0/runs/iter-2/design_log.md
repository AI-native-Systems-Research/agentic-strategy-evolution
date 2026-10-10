I'll start by exploring the current state of the codebase, the reference solution, and the previous iteration's artifacts to design iteration 2.Now let me read the iter-1 solution and the reference solution to understand the gap:Now let me study the key differences between iter-1 and reference solutions, and probe the system:Let me probe the current system by running the iter-1 solution and the reference to measure the actual gap:Good - iter-1 scores 72.78, reference scores 79.94 on this machine. ~7 point gap. Let me now write an enhanced solution incorporating all reference improvements and test it:Now let me write the enhanced h-main solution. I'll incorporate: lookahead, roughness tiebreaker, column compaction, multiple orderings, and wider width sweep:Let me test this solution:Excellent! 83.64 - a 3.7 point improvement over the reference (79.94). Let me see if I can push even higher. Let me try a version with more orderings and tuned parameters:84.77! Good progress. Let me try a two-phase approach: quick scan then quality pass on best widths:v3 was worse (79.57) - the two-phase approach doesn't work well. v2 at 84.77 is best. Let me try refining v2 further with some additional optimizations. Let me try adding some intelligence to the width selection and see if I can push higher:v4 (83.43) worse than v2 (84.77). Wider sweep wastes time on too many widths. Let me stick with v2's approach and try small refinements. Let me test if the ordering matters by trying a version focused only on the best ordering:v2 scored 79.70 on re-run (vs 84.77 first time) - high variance due to time-dependent width sweep. The solution is sensitive to system load. Let me design a more robust solution with consistent time allocation:87.37! Huge jump! Let me verify reproducibility:Still high variance (78.64 vs 87.37). The issue is system load variability. Let me take a fundamentally different approach - cap lookahead to be faster and more consistent, enabling more width exploration:Let me try a hybrid approach: reference-style width sweep first, then multi-ordering on the best width with remaining time:Excellent! v7 is very consistent: 86.23, 85.03, 84.90 (range: 1.33 points). All above 84.9, averaging ~85.4. This is 5+ points above the reference. Let me finalize v7 as h-main and create the ablation (no-lookahead) version:Now write the ablation version (same as v7 but with lookahead disabled):Now I need to disable the lookahead. The key change is to set `dynLIM = 1` always (no window):Also disable the dynamic lookahead adjustment blocks:Good - the dynamic adjustment blocks won't trigger with `dynLIM = 1` since `lim = placed + 1` always (only examines one piece). But let me also clean up the unused variables to avoid any subtle issues. Let me test the ablation:The ablation results (76.07, 71.29, 81.72) show high variance and average ~76.4, confirming lookahead provides ~9 points improvement. Now let me finalize the design. Let me write all three artifacts:Now write the handoff snapshot:Now copy the handoff to the campaign-level location:Now let me run validation:Validation passes. Let me provide a summary of the design.

## Design Summary — Iteration 2

**Research Question:** Does adding a lookahead window to the skyline greedy packer significantly improve packing density scores?

### Score Progression
| Solution | Score (avg) | Range |
|----------|-------------|-------|
| Iter-1 strip packer | ~34 | — |
| Iter-1 skyline (no lookahead) | ~73 | — |
| Reference solution | ~80 | — |
| **h-main (enhanced + lookahead)** | **~85.4** | 1.3 pts |
| h-ablation (enhanced, no lookahead) | ~76.4 | 10.4 pts |

### Key Design Decisions

**h-main** combines four improvements over iter-1:
1. **Lookahead window** (K = n/4) — the dominant mechanism (~9 pts improvement)
2. **Roughness tiebreaker** — prefer smoother skylines for future placements
3. **Column compaction** — remove empty columns from final packing
4. **Hybrid time strategy** — phase 1 (60%) sweeps widths, phase 2 (40%) tests alternative orderings at the best width

**h-ablation** disables lookahead (window=1) while keeping all other improvements. This isolates the lookahead's ~9-point contribution.

### Tier 2 Justification
Single mechanism (lookahead) with ablation. Tier 1 was confirmed in iter-1 (skyline ≫ strip). Escalating to test the next improvement identified by iter-1's designer.

### Pre-written Solutions
Both solutions are in `inputs/` — the executor just copies them to `solution.cpp` and runs the judge once per arm.