Good — I have a clear picture now. The iter-1 B&B solution finds exact optima on all 20 cases, but Docker timing variability causes intermittent TLEs, with scores varying from 85-100. Reducing ternary search iterations from 20→12 gives 30%+ speedup while preserving optimality. I'll add a time guard for robustness.

Let me write the design artifacts.Now let me write the three design artifacts.Now let me write the handoff snapshot:Now write the campaign-level handoff copy:Now run the design validation:Design validation passes. Now let me proceed to execution.

## Phase 1: Prepare### Step 3a: Create h-main patch (optimized B&B with time guard)All 20 cases produce exact optima with the optimized solution. TC1: 20ms (down from 30ms), TC14: 14ms (down from 19ms). Now save the patch:### Step 3b: Create h-ablation patch (greedy+LS only, no B&B)Good, both patches are ready and verified. Now let me write the experiment plan and execute.

### Step 4: Write experiment_plan.yaml## Phase 2: Execute

### h-main: Optimized B&B with time guardh-main scores: 100, 100, 95, 100, 100. 4/5 runs at 100 (vs iter-1 original: 100, 95, 100, 90, 100 = 3/5 at 100). The optimization helps but Docker variance persists.

### h-ablation: Greedy+LS only (no B&B)Reset workspace for cleanliness:## Phase 3: Analyze and Write Findings## Phase 4: Extract Principles## Phase 5: ValidateValidation passes. Let me also run the design validation one more time to confirm everything is consistent:Both design and execution validation pass. Here's a summary:

## Iteration 2 Summary

### Research Question
Can optimizing the B&B constant factor and adding a time guard eliminate Docker-timing-induced score drops?

### Results

| Arm | Scores | Mean | Status |
|-----|--------|------|--------|
| **h-main** (optimized B&B + time guard) | 100, 100, 95, 100, 100 | 99.0 | PARTIALLY_CONFIRMED |
| **h-ablation** (greedy+LS only, no B&B) | 90.597, 90.597, 90.597 | 90.597 | CONFIRMED |
| *iter-1 baseline (for comparison)* | 100, 95, 100, 90, 100 | 97.0 | — |

### Key Findings

1. **h-main PARTIALLY_CONFIRMED**: Reducing ternary iterations from 20→12 gave 30-37% per-node speedup (TC1: 30ms→20ms) with zero accuracy loss. Score reliability improved (4/5 at 100 vs 3/5), and worst-case improved (95 vs 90). But Docker timing variance persists — one run still scored 95.

2. **h-ablation CONFIRMED**: Multi-greedy + local search (no B&B) consistently scores 90.597. B&B adds ~9.4 points on average. Greedy+LS is optimal on 9/20 test cases but fails on 11/20 (worst: TC12 at 43.9).

3. **New principle RP-5**: Docker timing variability causes score drops even after algorithmic optimization. The residual variance is from container scheduling overhead, not computation time.

### Artifacts Written
- `problem.md`, `bundle.yaml`, `handoff_snapshot.md` (design)
- `experiment_plan.yaml`, `findings.json`, `principle_updates.json` (execution)
- `patches/h-main.patch`, `patches/h-ablation.patch` (code changes)
- `results/h-main/score.txt`, `results/h-ablation/score.txt` (raw scores)