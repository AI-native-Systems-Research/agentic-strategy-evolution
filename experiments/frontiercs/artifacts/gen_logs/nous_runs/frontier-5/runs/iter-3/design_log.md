I'll start by checking for any artifacts from the prior interrupted attempt and examining the current codebase state.Let me read the existing artifacts from the interrupted attempt and the current solution state.Let me check if validation already passed and understand the current solution state.The design validation already passes. Let me verify the campaign-level handoff matches the iter-3 snapshot.The files are identical. Now let me verify that the solution_iter3.cpp actually exists and scores 83 as claimed, since this is the critical artifact for the executor.All artifacts from the prior interrupted attempt are complete and validated. Let me confirm the full state:

1. **`problem.md`** ✓ — Documents the break-and-extend mechanism for sparse graphs, validated baseline at SCORE: 83
2. **`bundle.yaml`** ✓ — Two arms: h-main (break-and-extend, score 83) vs h-control-negative (iter-2 solution, score 82), complexity tier 2
3. **`handoff_snapshot.md`** ✓ — Full exploration context for executor, matching campaign-level `handoff.md`
4. **Validation** ✓ — `nous validate design` returns `{"status": "pass"}`
5. **Solution verified** — `solution_iter3.cpp` scores 82.99999999999999 (= 83) on the judge

## Summary

**Iteration 3 design is complete.** The hypothesis tests whether a **break-and-extend** mechanism for very sparse directed graphs (avg_deg < 4) improves the Hamiltonian path score from 82 → 83.

Key design decisions:
- **h-main** adds `solveBreakExtend()` with adaptive branching: sparse graphs (test 10, avg_deg=3, n=100K) skip the standard Pósa pipeline and use multi-restart break-and-extend (0.2s per attempt, ~15 restarts). This achieves k≈25,777 on test 10 (crossing the 23,333 threshold for +1 point). Tests 1-9 are preserved identically.
- **h-control-negative** uses the iter-2 solution (SCC + rotation only) as the baseline, expected score 82.
- The improvement is +2 points over iter-2's score of 81: +1 from test 8 (max-degree greedy restarts in Phase 2) and +1 from test 10 (break-and-extend).