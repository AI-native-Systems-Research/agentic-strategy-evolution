# Problem Framing — Iteration 4: Budget Efficiency via Phase 2.5 Scope Broadening

## Research Question

Can the hierarchical Pareto search algorithm achieve ≥88% Pareto tuple recall at budget=100 (half its maximum) by broadening Phase 2.5's scope to include non-best-per-GPU combos and testing sjf+256 at all degraded kv values?

Iterations 1-3 established four structural regularities (TP dominance, cache equivalence, maxr=256 plateau, SJF×concurrency interaction) and validated search effectiveness at budget=200 across three models. However, probing reveals the search's budget efficiency is limited by Phase 2.5's narrow scope:

**Current recall curve** (search.py with Phase 2.5 already positioned before Phase 3):

| Budget | Configs | Unique Tuples | GT Recall | Key Phase Active |
|--------|---------|---------------|-----------|------------------|
| 50     | 18      | 18            | 25.7%     | Phase 1 (ceiling) |
| 75     | 25      | 25            | 57.1%     | Phase 2 (cache sweep) complete |
| 100    | 33      | 30            | 80.0%     | Phase 2.5 (SJF interaction) |
| 125    | 34      | 30            | 80.0%     | Phase 3 (bs=16 sweep) — dead zone |
| 150    | 48      | 32            | 91.4%     | Phases 4-5 (SJF + concurrency) |
| 200    | 81      | 33            | 94.3%     | Phase 6 (refinement) |

The 7 missed tuples at budget=100 (80% recall) are:

| # | Config | Missed Because |
|---|--------|----------------|
| 1 | (1,1,sjf,256,kv=4000,bs=32) | kv=4000 ratio=0.993, not degraded at 0.95 threshold |
| 2 | (1,2,fcfs,64,kv=2000,bs=32) | (1,2) not in pareto_combos (best at gpus=2 is (2,1)) |
| 3 | (1,2,sjf,64,kv=2000,bs=32) | Same — (1,2) excluded from Phase 2.5 |
| 4 | (1,2,sjf,128,kv=2000,bs=32) | Same — (1,2) excluded from Phase 2.5 |
| 5 | (2,1,sjf,256,kv=4000,bs=32) | kv=4000 ratio=0.995, not degraded at 0.95 threshold |
| 6 | (4,2,sjf,128,kv=2000,bs=32) | (4,2) not in pareto_combos (best at gpus=8 is (8,1)) |
| 7 | (8,1,sjf,256,kv=3000,bs=32) | sjf+256 only tested at kv_severe, not at kv=3000 |

Three root causes:
1. **Pareto_combos scope too narrow** (misses #2,3,4,6): Phase 2.5 only tests best combo per GPU count. Multi-instance combos like (1,2) and (4,2) are excluded, even though they produce distinct Pareto points (different rps/ttft tradeoffs from TP dominance asymmetry at same GPU count).
2. **sjf+256 only at kv_severe** (misses #7): Phase 2.5 tests sjf+128 at all degraded kvs but sjf+256 only at the most severely degraded kv. For (8,1), kv_severe=2000 but the GT tuple at kv=3000 needs sjf+256.
3. **0.95 degradation threshold too strict** (misses #1,5): kv=4000 gives ratio>0.95 for (1,1) and (2,1), so SJF is never tested there. But SJF at kv=4000 does produce unique Pareto tuples.

Also notable: 2 tuples are permanently missed even at budget=200 — (1,2,fcfs,64,kv=2000) and (1,2,sjf,64,kv=2000) — because (1,2) is never included in degraded-regime exploration at that granularity. Actual GT tuple recall at budget=200 is 94.3% (33/35).

Key source files:
- `search.py:229-265` — Phase 2.5 implementation: `pareto_combos` scope, degradation threshold, per-kv testing
- `search.py:233-238` — `best_per_gpu` computation excludes non-best combos per GPU count
- `search.py:246` — `0.95 * ceiling[key]` threshold
- `search.py:259-265` — sjf+256 only at kv_severe

## System Interface

- **Build:** `go build -o blis main.go` (already built, binary at `./blis`)
- **CLI flags relevant to experiment:**
  - `--tp <int>` — tensor parallelism degree (`cmd/root.go:963`)
  - `--num-instances <int>` — number of instances (`cmd/root.go:966`)
  - `--scheduler <str>` — scheduling policy: fcfs or sjf (`cmd/root.go:791`)
  - `--max-num-running-reqs <int>` — max concurrent requests per instance (`cmd/root.go:972`)
  - `--total-kv-blocks <int>` — KV cache blocks per instance (`cmd/root.go:975`)
  - `--block-size-in-tokens <int>` — tokens per KV block (`cmd/root.go:978`)
  - `--metrics-path <path>` — JSON metrics output (`cmd/root.go:2078`)
- **Code evidence:** `cmd/root.go:963` defines `--tp`, `cmd/root.go:2078` defines `--metrics-path`
- **Native output:** `--metrics-path` writes JSON with `responses_per_sec`, `ttft_p99_ms`, etc.

## Baseline Command

```bash
python3 search.py --model qwen/qwen3-14b --rate 100 --budget 100 --seed 42 --out results/baseline_b100.json
```

## Baseline Validation

Ran the current search at budget=100 with seed=42:
- Exit code: 0
- Found 33 Pareto-optimal configurations (30 unique tuples)
- Recall: 28/35 = 80.0% against GT (final/ground_truth_pareto.json)
- Also measured: budget=200 gives 94.3% (33/35)

Recall curve verified at all 6 budget levels — see table above.

## Experimental Conditions

### Condition: Improved Phase 2.5 at multiple budgets (treatment)
Modify search.py Phase 2.5 to:
1. Include ALL (tp,ni) combos that show degradation — not just best-per-GPU. A combo qualifies if it has at least one kv value with rps < threshold × its own ceiling. This captures (1,2) which is degraded at kv=2000 (ratio=0.945) and potentially (4,2).
2. Test sjf+256 at ALL degraded kv values (not just kv_severe).
3. Lower degradation threshold from 0.95 to 0.99 to catch near-ceiling kv values where SJF still produces unique Pareto points (e.g., kv=4000 for (1,1) and (2,1)).
4. Process combos in descending TP order (highest first), since TP-dominant combos contribute most to the Pareto front.
5. Trim fcfs+128 from per-combo testing (rarely produces unique Pareto tuples) to save budget for broader scope.

Run at budget={50,75,100,125,150,200} on 14B/rate=100/seed=42.

### Code change description (search.py)
**Intent**: Broaden Phase 2.5's combo scope, threshold, and SJF coverage:
1. Replace `pareto_combos` filter with: any (tp,ni) combo that has at least one Phase 2 result with rps < 0.99 × ceiling.
2. For each degraded combo: test sjf+{128,256} at each degraded kv, plus fcfs+64 and sjf+64 at kv_severe.
3. Add one "near-ceiling SJF probe" per combo: sjf+256 at the least-degraded kv from Phase 2 (even if ratio>0.99), to catch Pareto points at near-ceiling cache.
4. Sort combos by descending TP within each GPU group, processing highest-TP combos first.

## Success Criteria

- **h-main**: Improved Phase 2.5 achieves ≥88.6% unique Pareto tuple recall (31/35) on 14B at rate=100 with budget=100 (seed=42), up from 80.0% with the current search
- **h-dose-response**: Budget→recall curve for improved search is monotone increasing, reaching ≥88.6% by budget=100
- **h-control-negative**: Current search at budget=100 achieves ≤82% recall (verified 80.0%)

## Constraints

- search.py must use Python 3 standard library only (no numpy/scipy)
- search.py interface unchanged: `--model`, `--rate`, `--budget`, `--seed`, `--out`
- Must finish within 3 minutes
- Budget ≤200 evaluations (no exhaustive enumeration)
- Must not violate active principles (RP-1 through RP-8)
- The code change should improve or maintain recall at budget=200 (currently 94.3%)

## Prior Knowledge

From iterations 1-3 (RP-1 through RP-8):
- TP dominance is architecture-independent, ratio scales with model size
- Cache equivalence: effective_cache = kv × bs
- maxr=256 saturation plateau is universal
- SJF×concurrency interaction creates Pareto tradeoffs in degraded regimes
- Pareto front diversity scales with model size and arrival rate

New probing discoveries (iter-4 design phase):
- **Non-best combos produce unique Pareto tuples**: (1,2) at gpus=2 (0.71× the rps of (2,1) but with 16% better ttft) and (4,2) at gpus=8 (0.84× the rps of (8,1) but with different ttft). These trade rps for ttft — a dimension the best-per-GPU selection ignores.
- **Near-ceiling SJF matters**: SJF at kv=4000 (ratio>0.95) produces unique Pareto tuples for (1,1) and (2,1) because even mild cache pressure differentiates SJF vs FCFS scheduling.
- **sjf+256 is not equivalent to sjf+128 at moderate kv**: At kv=3000 for (8,1), sjf+256 gives rps=29.23,ttft=1808 while sjf+128 gives different rps/ttft. They contribute separate Pareto tuples.
- **Budget=200 actual recall is 94.3%, not 100%**: The 2 permanently missed tuples require maxr=64 at (1,2), which no current phase targets directly. The improved Phase 2.5 will include (1,2) in its scope, enabling recovery of these tuples.
