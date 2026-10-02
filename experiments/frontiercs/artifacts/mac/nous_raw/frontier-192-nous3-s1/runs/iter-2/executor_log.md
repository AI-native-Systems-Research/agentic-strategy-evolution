Let me gather all the context I need first.Good. Now I have the iter-1 h-main solution (FM-based). The iter-2 design wants:
- **h-main**: Linear-cooling SA with time-proportional restarts
- **h-ablation**: Geometric-cooling SA (the iter-1 baseline approach, but SA-focused, not FM)

Let me check if there are any snapshot solutions from the designer's probing.Now I have full context. Let me implement both arms, create patches, run them, and analyze.Let me define short vars and create the result directories:Now write the h-main solution (linear-cooling SA):Smoke-test h-main:h-main works, scores 87.54. Now reset and write the h-ablation solution:Smoke-test h-ablation:Good — h-ablation scores ~86.6, matching the expected ~86.7 baseline. Reset and verify patches:Both patches verified. Now run the full experiment — 3 seeds × 2 arms = 6 runs:All 6 runs complete. Summary:
- **h-main** (linear cooling): 87.52, 87.57, 87.52 → mean 87.54
- **h-ablation** (geometric cooling): 86.60, 86.54, 86.55 → mean 86.56

Clear directional win for h-main (~1.0 point). Now write the artifacts:Now validate:Validation passes.

**Summary:** Both arms CONFIRMED. Linear-cooling SA (h-main) scored 87.54 mean vs geometric-cooling SA (h-ablation) at 86.56 mean — a consistent ~1.0 point improvement across all 3 seeds with very low variance (std 0.03). The mechanism is validated: linear cooling uses the full 0.10s SA budget per restart for productive exploration, while geometric cooling wastes most of the time after temperature drops to near-zero in ~0.5ms.