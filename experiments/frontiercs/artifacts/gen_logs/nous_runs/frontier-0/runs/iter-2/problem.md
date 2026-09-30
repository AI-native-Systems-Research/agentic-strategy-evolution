# Problem Framing — Iteration 2: Lookahead-Enhanced Greedy Packing

## Research Question

Does adding a lookahead window to the skyline greedy packer — allowing the algorithm to choose the best piece from the next K candidates rather than strictly following the fixed ordering — significantly improve packing density scores?

The mechanism is implemented in the `pack()` function where the inner loop scans `ord[placed..placed+dynLIM)` instead of just `ord[placed]`. Key source files:
- `algorithmic/problems/0/chk.cc:107-137` — Checker validation: reflect→rotate→translate
- `algorithmic/problems/0/chk.cc:148-151` — Scoring: `score = totalCells / area`
- `algorithmic/problems/0/examples/reference.cpp:62-207` — Reference packer with lookahead

## System Interface

- **Build:** Handled internally by the judge (g++ -O2 -std=c++17)
- **CLI:** `bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp`
- **Output:** Prints `SCORE: <n>` to stdout (0-100, average across 70 test cases)
- **Time limit:** 2 seconds per test case, 256MB memory (from `config.yaml:6-7`)
- **Test cases:** 70 cases, n ∈ [104, 6472], single subtask worth 100 points

**Code evidence:**
- `chk.cc:49-56` — `rot90cw()`: CW rotation used by checker
- `chk.cc:62` — n read with `readInt(100, 10000)`
- `chk.cc:148` — `double score = (double)totalCells / (double)area`
- `config.yaml:6` — `time_limit: 2.0`

## Baseline Command

```bash
bash /home/ubuntu/frontier/gen_logs/fmeasure_0.sh $PWD/solution.cpp
```

## Baseline Validation

Ran the iter-1 skyline packer (no lookahead, no roughness, no column compaction):
- **Score: 72.78** (exit 0, valid output on all 70 test cases)
- Reference solution: **79.94** on same machine

Ran the enhanced v7 solution (with lookahead, roughness, compaction, multi-ordering):
- **Scores: 86.23, 85.03, 84.90** across 3 runs (consistent, range 1.33 points)

Ran the ablation (no lookahead but keeping roughness, compaction, multi-ordering):
- **Scores: 76.07, 71.29, 81.72** across 3 runs (high variance, range 10.4 points)

## Experimental Conditions

### h-main: Enhanced Packer with Lookahead
Copy `inputs/h-main-final-solution.cpp` to `solution.cpp`. Key features:
1. **Lookahead window**: Examines next K pieces (K = n/4, dynamically adjusted for big instances) and selects the piece with the best placement. This is the PRIMARY new mechanism.
2. **Roughness tiebreaker**: When placements are equally good by max-height and delta-sum, prefer the one creating a smoother skyline (lower Σ|h[i]-h[i-1]| delta).
3. **Column compaction**: Remove empty columns from the final packing to reduce effective width.
4. **Three piece orderings**: Try ascending-min-dim, descending-cell-count, and descending-max-dim.
5. **Hybrid time strategy**: Phase 1 (60% time) sweeps widths with primary ordering; Phase 2 (40% time) tries alternative orderings at best width ± 3.

### h-ablation: Same without Lookahead
Copy `inputs/h-ablation-solution.cpp` to `solution.cpp`. Identical to h-main except:
- Lookahead window fixed at 1 (always place the next piece in order)
- Retains roughness tiebreaker, column compaction, multi-ordering, and hybrid time strategy

## Success Criteria

- h-main scores consistently higher than iter-1 baseline (~73) and reference (~80)
- h-main minus h-ablation ≥ 5 points, confirming lookahead as the key improvement mechanism
- h-main scores ≥ 83 on average across runs (target: 85+)

## Constraints

- 2-second time limit per test case enforced by judge
- Solution must be valid C++17 compilable by g++ -O2
- Must produce valid placements (no overlaps, all cells in [0,W)×[0,H))
- Score is averaged across 70 test cases; consistency matters

## Prior Knowledge

- **RP-1**: Skyline packing ≫ strip packing (~72 vs ~34). Iter-1 confirmed.
- **RP-2**: Transform parameter recovery is critical. Incorrect reflect→rotate→translate ordering produces score 0.
- **RP-3**: Score is sensitive to time-managed width sweep budget. Validated by observing variance in iter-1 (76 designer probe vs 72 execution).

The iter-1 designer identified lookahead as the "most promising improvement for iter-2" and noted the 3-point gap between their packer and the reference. This iteration tests that hypothesis directly.
