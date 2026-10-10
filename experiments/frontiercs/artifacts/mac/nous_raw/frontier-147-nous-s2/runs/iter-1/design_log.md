Now let me understand the problem and build a solution. This is AHC001 — rectangle packing optimization on a 10000×10000 grid.Now I understand the problem and scoring system. Let me write a strong SA-based solution and test it.Now let me write the SA solution. The key moves: expand/contract rectangle boundaries, checking overlap with O(n) neighbors.The judge uses a Docker-based judge server. It compiles the solution server-side. So I can't locally compile, but I can just submit via the measure script. Let me test the solution directly.Score 0 — the SA works but the greedy expansion is too weak. The issue is my greedy doesn't fill space well. Let me write a much better solution using a more sophisticated approach — start with a grid-based partitioning, then use SA.Score 80.42 with the initial SA solution. Now let me think about improvements for the h-main arm. Let me look at the best existing solutions for reference on approach quality:Good — I already have 80.42 with my first attempt. Let me focus on making a stronger solution. The key improvements:

1. Better greedy initialization (weighted Voronoi-like partitioning)
2. SA with multi-rect moves (shrink one to grow another)
3. Better temperature schedule

Let me write a substantially improved version:Type mismatch with `max`. Let me fix all `max(int, long long)` issues:The second version regressed. Let me rewrite based on the first version (80.42) with targeted improvements:Let me try a simpler approach — minimal greedy, maximum SA time with good temperature:Let me go back to the approach that scored 80.42 and make targeted improvements. The key was small-step greedy + longer SA time:85.31! Better than before. Now let me think about what further improvements to try. The h-main arm should be the best I can achieve. Let me consider two strategies for arms:

1. **h-main**: SA with "swap" moves — when shrinking one rect, try to grow a neighbor simultaneously
2. **h-control-negative**: Simple greedy-only (no SA) as baseline

Let me now write the final h-main solution with the key improvement: two-rect SA moves where we shrink one to grow another:The two-rect moves slowed things down. Let me go back to the 85.31 approach and optimize further. Key idea: focus SA budget on high-impact moves.Let me go back to the exact 85.31 version — that was the best:Good. Now let me verify this scores 85+ again, then write the design artifacts.84.70. Close to 85.31 — variation across test cases is expected. Now let me write the design artifacts.Now write the handoff:Now validate:Validation passes. 

**Summary:** Designed iter-1 bundle for AHC001 rectangle packing (problem #147). Two arms:

- **h-main**: Greedy expansion + simulated annealing — scored **84.70** in probe. Greedy fills ~2s with small-step expansion; SA runs ~7s with 8 move types including expand-to-limit and target-aware moves, linear cooling from T=0.01.
- **h-control-negative**: Greedy-only (no SA) — tests whether SA is the key driver of quality.

Key finding from exploration: simpler SA moves with higher iteration throughput beat sophisticated multi-rect moves. The iteration count matters more than move complexity at N≤200.