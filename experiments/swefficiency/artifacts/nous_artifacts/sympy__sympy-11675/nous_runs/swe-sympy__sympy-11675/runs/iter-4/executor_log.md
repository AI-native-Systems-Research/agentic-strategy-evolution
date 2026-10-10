Let me check for the draft patch, prior iteration results, and the workload file.## Phase 1: Prepare

Let me apply the preflight commands and verify the baseline.Good — the Python 3.11 compat fixes AND the diophantine.py changes are already applied in the worktree. This is likely from the design phase exploration. Let me verify the patch matches the h-main-draft.patch:The current worktree state exactly matches the draft patch. Now let me verify everything works — first reset to clean state, then run baseline, then apply treatment.Good, clean state. But we need the Python 3.11 compat fixes to run anything. Let me apply them first:Now let me run a quick baseline smoke test:Baseline works — takes ~42s per call. Now let me apply the treatment patch and test:Treatment works — ~0.125ms per call (warm). Results are identical to baseline. Now verify correctness:All three solutions are mathematically correct. Now run the tests:41 passed, 1 XFAIL (test_fail_holzer) — exactly as expected. The treatment is validated. Let me now save the proper patch:Now let me reset and verify the patch can be cleanly applied:Patch verified. Phase 1 preparation is complete.## Phase 2: Execute

I need to run:
1. **Baseline** (original code + compat fixes only) — across 3 seeds with the workload harness
2. **Treatment** (h-main patch applied) — across 3 seeds with the workload harness  
3. **Direct timing** for both baseline and treatment (more precise, avoids fork overhead)

Let me first set up the result directories and create the experiment plan:Now let me run the baseline (original code with compat fixes). First apply just the compat fixes:### Baseline runs (3 seeds)Baseline results: 43.043, 42.921, 41.767 — mean ~42.58s. Now apply treatment:### Treatment runs (3 seeds)Treatment results: 0.000311, 0.000305, 0.000288 — mean ~0.000301s. Now let me also get precise direct timing measurements:Excellent results. Now let me also verify baseline-vs-treatment result identity:Now let me also compare with iter-3 performance directly. Let me get the iter-3 patch and run it:Now I have the complete comparison. Let me also run the harness with iter-3 for fair comparison:Now I have all the data I need. Let me compile the measurements:

**Baseline (original + compat):**
- Harness: 43.043, 42.921, 41.767 → mean = 42.577s
- Campaign baseline: 57.3288s

**Iter-3 (comparison):**
- Harness: 0.000808s
- Direct: 0.172ms per call
- Campaign speedup (direct): 333,409x

**Iter-4 Treatment:**
- Harness: 0.000311, 0.000305, 0.000288 → mean = 0.000301s
- Direct: 0.1198ms per call (std 0.0031ms)
- Campaign speedup (harness): 57.3288 / 0.000301 = 190,461x
- Campaign speedup (direct): 57.3288 / 0.0001198 = 478,412x
- Incremental speedup over iter-3 (direct): 0.172 / 0.120 = 1.43x
- Incremental speedup over iter-3 (harness): 0.000808 / 0.000301 = 2.68x## Phase 3: Analyze

Let me now write the experiment plan and findings. First, let me restore the iter-4 treatment state for the worktree:Now write the experiment plan:Now let me analyze the predictions vs. observations and write findings:Now let me write the findings:## Phase 4: Extract PrinciplesNow let me run the validation:Two issues to fix: (1) remove `mode` from findings.json, (2) create the tests output file:Now let me re-validate:Validation passes.## Summary

**Iteration 4 — CONFIRMED** ✓

The h-main hypothesis is confirmed. Replacing sympy's number-theory utility functions (`divisors`, `sqrt_mod`, `divisible`) with pure-integer implementations and converting D/N/sD to Python `int` at the |N|>1 branch entry delivers:

| Metric | Predicted | Observed |
|--------|-----------|----------|
| Treatment harness mean | ~0.31ms | 0.301ms |
| Incremental speedup (harness, vs iter-3) | ~2.65x | 2.68x |
| Campaign speedup (harness) | ~185,000x | 190,335x |
| Direct warm-call mean | — | 0.120ms |
| Campaign speedup (direct) | — | 478,538x |
| Tests passing | 41 (1 XFAIL) | 41 (1 XFAIL) ✓ |
| Results identical | yes | yes ✓ |

**Key findings:**
- The harness speedup (2.68x) exceeds the direct warm speedup (1.43x) because forked-process measurement amplifies cold-start savings from eliminating sympy module imports
- Function call count reduced from 387 to 249 per invocation (36% reduction)
- All 3 solution tuples mathematically verified (x² − Dy² = −20)
- At 0.120ms warm per call, we're approaching Python's bytecode execution floor (~0.5μs per PQa iteration × 234 iterations)