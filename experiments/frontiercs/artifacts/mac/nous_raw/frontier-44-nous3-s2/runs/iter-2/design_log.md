Now let me understand the iter-1 solution thoroughly and design improvements. Let me check the current solution file in the worktree:Now I have full context. Let me write the design artifacts for iter-2.Validation passed. 

**Summary:** Designed iter-2 bundle (tier 2) with two arms:
- **h-main**: Iterated local search — double-bridge perturbation + multi-city Or-opt (1-3) + KNN=20 + all iter-1 features. Predicted to beat iter-1's 78.9.
- **h-ablation**: Same without double-bridge, to isolate perturbation's contribution.

Key improvements target SA getting stuck in local optima (double-bridge) and limited move quality (Or-opt segments, wider neighbor search).