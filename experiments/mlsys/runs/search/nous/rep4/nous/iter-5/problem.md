# Problem Framing — Iteration 5

## Research Question

Can restructuring the hierarchical Pareto search's budget allocation — by selectively reducing Phase 2 scope and eliminating the zero-gain Phase 3, then reinvesting saved evaluations into expanded degraded-regime probing — achieve 100% unique Pareto tuple recall at budget=100?

The mechanism under study is budget reallocation within the hierarchical search (`search.py`). The search has 6 phases; Phases 1+2 consume 75/100 evals, leaving only 25 for degraded-regime interaction (Phase 2.5). Phase 3 (bs=16 sweep) consumes 30 evals with zero Pareto impact (RP-11). The hypothesis: by reducing Phase 2 from 60 to 38 evals (skip kv≥4000 for combos not degraded at kv=3000) and eliminating Phase 3, we free 52 evals (22 from Phase 2, 30 from Phase 3) for expanded Phase 2.5, which probes non-best combos, near-ceiling SJF differentiation, and maxr=64 operating points.

**Key source files:**
- `search.py:214-318` — search phases
- `search.py:229-265` — Phase 2.5 (primary edit target)
- `search.py:224-228` — Phase 2 (edit target: selective kv sweep)
- `search.py:267-270` — Phase 3 (edit target: eliminate)

## System Interface

- **Build:** `go build -o blis main.go`
- **CLI flags:** `--model`, `--hardware H100`, `--tp`, `--num-instances`, `--scheduler`, `--max-num-running-reqs`, `--total-kv-blocks`, `--block-size-in-tokens`, `--rate`, `--num-requests`, `--seed`, `--metrics-path` (output)
- **Code evidence:**
  - `cmd/root.go:963-980` — all 6 knob flag definitions
  - `sim/latency/trained_physics.go` — TP divisibility constraint
- **Output:** `--metrics-path` writes JSON with `responses_per_sec`, `ttft_p99_ms`

## Baseline Command

```bash
python3 search.py --model qwen/qwen3-14b --rate 100 --budget 100 --seed 42 --out /tmp/baseline.json
```

## Baseline Validation

Exit code 0. 100/100 evaluations used. 33 Pareto-optimal configs returned.
Recall: 28/35 GT unique tuples matched = 80.0%.
7 missed tuples traced to: non-best combo exclusion (3 tuples from (1,2), 1 from (4,2)), narrow sjf+256 coverage (1 from (8,1)), near-ceiling threshold too strict (2 from (1,1) and (2,1) at kv=4000).

## Experimental Conditions

### Condition: v2-treatment (code change)
Modify `search.py` with three changes:
1. **Selective Phase 2**: Replace full 15-combo × 4-kv sweep with: all combos at kv={2000,3000}, then extend to kv={4000,5000} ONLY for combos still degraded at kv=3000 (ratio < 0.99 vs ceiling). Saves 22 evals.
2. **Phase 3 elimination**: Remove bs=16 sweep entirely (proven zero Pareto impact across models, RP-11). Saves 30 evals at budget>100.
3. **Expanded Phase 2.5**: Probe ALL degraded combos (0.99 threshold), not just best-per-GPU. Backbone combos: sjf+128, sjf+256, fcfs+128 at each degraded kv + near-ceiling sjf+256. Non-best combos: sjf+128, sjf+64, fcfs+64 at each degraded kv. Process in descending TP order.

Run: `python3 search_v2.py --model qwen/qwen3-14b --rate 100 --budget <B> --seed 42 --out <file>`

### Condition: v1-baseline (unchanged code)
Run unmodified `search.py` at same budgets for comparison.

### Budget levels tested
{50, 75, 100, 125, 150, 200} — dose-response across budget dimension.

### Cross-validation
- Rate=50 (low contention: fewer degraded combos)
- Rate=200 (high contention: more degraded combos, larger Pareto front)
- 7B model (fewer valid TPs: tp=8 excluded due to head count)

## Success Criteria

- **Primary**: v2 at budget=100 achieves ≥95% unique Pareto tuple recall on 14B/rate=100 (vs 80.0% baseline)
- **Stretch**: v2 at budget=100 achieves 100% recall
- **Cross-model**: v2 at budget=100 achieves ≥95% recall on 7B
- **Cross-rate**: v2 at budget=100 achieves ≥90% recall at rate=200

## Constraints

- search.py must use Python standard library only
- Budget evaluations must finish within 3 minutes
- ~0.067s per BLIS evaluation
- Search must be general (work across models and rates)

## Prior Knowledge

- **RP-1**: TP dominance — higher TP strictly better at same GPU count
- **RP-3 (refuted)**: Phase 2.5 scope broadening fails at budget=100 due to budget arithmetic (Phase 1+2 = 75 evals)
- **RP-4**: maxr=256 plateau — 512 never improves
- **RP-5**: SJF × concurrency interaction in degraded regimes
- **RP-9**: Budget allocation is fundamental tradeoff (Phase 1+2 = 75/100)
- **RP-10**: fcfs+128 is significant GT contributor (13.7% of GT configs)
- **RP-11**: Phase 3 (bs=16) adds zero unique Pareto tuples — dead zone confirmed at budget=100-125

**Key design decision**: RP-3 established that improving budget=100 recall requires REDUCING Phase 1/2 eval count. This iteration does exactly that — selective Phase 2 reduces from 60 to 38 evals without losing any Pareto coverage, because non-degrading combos produce identical results at all kv values.
