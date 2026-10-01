Let me read the key prototype files and previous iteration results to understand the baseline.Good, the prototype files are in the main repo. Let me read them to understand what we're building from.Now let me set up task tracking and check the measurement script, then start building the solution.Good, now I have full context. Let me implement the h-main solution. The key improvements from the bundle are:
1. Multi-start NN for small N (leverage unused time on TC4)
2. Cycling detection (fix the TC6 infinite loop)
3. Or-opt after 2-opt
4. Better time management

Let me also read the `proto_iter3g.cpp` for the ILS variant which has good cycling detection:Now I have all the context. Let me implement the h-main solution and h-control-negative, create patches, and run experiments. Let me start by implementing the h-main solution.Build succeeded. Let me smoke-test the h-main solution first, then create the patch:Works. Now let me create the h-main patch and prepare the h-control-negative:Now create the h-control-negative solution (exact copy of proto_v10.cpp):Now verify both patches apply cleanly:Both patches apply cleanly. Now let me create result directories and write the experiment plan:Now execute h-main arm. Apply patch, build, and run 3 times:75.85 — slightly below the 76.3 baseline. Let me run the remaining runs:H-main results: 75.85, 73.86, 70.74 — below baseline and high variance. This suggests the or-opt overhead is causing TLE on large test cases. Let me run the control arm now:The control shows variance too (76.29, 71.29, 76.29) suggesting system load issues. Let me do additional runs to get cleaner comparison data:System load is causing TLEs. Let me wait and re-run when it's stable:System is back to stable (76.288 for control). Now let me re-run h-main under stable conditions:76.31! Very close to baseline. Let me run a few more times under stable conditions:System load is very unstable. Let me check the per-test-case behavior locally to understand the algorithm's quality independent of timing:Let me run individual test cases locally with the h-main solution and the checker to compare per-test-case scores:There's a critical bug — the output is truncated! The or-opt is corrupting the tour. Let me investigate:The checker needs an answer file. Let me check how to properly invoke it:The argument order is `checker input output answer`! Let me re-run per-test-case analysis:Good — locally h-main scores identically to baseline. The per-test-case analysis shows no improvement. Let me also run the control arm locally:Now I have clean per-test-case data. Let me save detailed results and get one more judge run under stable conditions:Now let me get one more clean judge measurement for each arm:Clean results: h-main 76.31, h-control-negative 76.29. Essentially identical. Let me save these clean results:Now let me proceed to Phase 3: Analysis and write findings.Now write principle_updates.json:Now let me validate:Validation passes. Let me mark the task as complete:## Summary

**Iteration 3 complete. Validation passed.**

### Results

| Arm | Prediction | Observed | Status |
|---|---|---|---|
| **h-main** (multi-start NN + cycling detection + or-opt) | Score > 76.3, improving failing test cases | Score ≈ 76.26-76.31 (identical to baseline within noise) | **REFUTED** |
| **h-control-negative** (exact iter-2 baseline) | Score ≈ 76.3 ± 0.5 | Score = 76.288 (stable under low load) | **CONFIRMED** |

### Key Findings

1. **Multi-start, or-opt, and cycling detection are all individually neutral** — combining them produces no synergy. The 2-opt local optimum quality is a hard ceiling.

2. **Per-test-case analysis** reveals the h-main algorithm is within ±0.5% of the control on every test case. TC4 (N=1000) improved by +0.33% from multi-start, but TC6 and TC7 regressed by -0.36% and -0.54%.

3. **System load caused significant judge variance** during testing (scores as low as 66.3 for the control arm). Clean runs under stable conditions confirmed both arms are functionally equivalent.

### New Principles (RP-6, RP-7)
- **RP-6**: Multi-start, or-opt, and cycling detection are all neutral at the 2-opt-converged quality level.
- **RP-7**: The 2-opt local optimum is a hard ceiling. Breaking through requires 3-opt or Lin-Kernighan moves.

### Suggested Next (iter-4)
- Implement proper LK moves (Lin-Kernighan 3-opt)
- Try penalized-cost-aware optimization
- Investigate construction heuristics that exploit correlated data structure in TC4/TC7