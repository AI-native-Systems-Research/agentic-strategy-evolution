# Handoff Snapshot — Iteration 5

## Goal

Implement and validate a restructured hierarchical Pareto search that achieves 100% unique Pareto tuple recall at budget=100 by reducing Phase 2 waste (selective kv sweep), eliminating Phase 3 (zero-gain bs=16), and expanding Phase 2.5 (all degraded combos, near-ceiling SJF probes).

## Key Discoveries

1. **Phase 2 efficiency is only 33.3%**: Of 60 Phase 2 evals, only 20 produce GT Pareto tuples. The 40 wasted evals test non-degrading combos (8 of 15 combos have ratio=1.0 at ALL kv values, including kv=2000) at high kv values where they produce ceiling-identical results.

2. **Degradation-at-kv=3000 is a reliable filter**: Only 4 combos show degradation at kv=3000: (1,1), (2,1), (4,1), (8,1) — all single-instance high-TP combos. Extending to kv=4000,5000 only for these 4 combos saves 22 evals while preserving all Pareto coverage.

3. **Non-best combos contribute 4 of 7 missed tuples**: (1,2) at kv=2000 has 3 unique tuples (sjf+128, sjf+64, fcfs+64), and (4,2) at kv=2000 has 1 (sjf+128). Current Phase 2.5's best-per-GPU filter excludes them.

4. **Near-ceiling SJF differentiation creates 2 unique tuples**: (2,1,sjf,256,4000) and (1,1,sjf,256,4000) have ratio ≥0.99 at fcfs but distinct tuples at SJF because scheduler differentiation emerges even with minimal cache pressure.

5. **v2 prototype achieves 100% recall at budget=100**: Validated on 14B/rate=100 (35/35), 7B/rate=100 (21/21), and 14B/rate=50 (23/23). At rate=200, achieves 97.6% (40/41) at budget=100 and 100% at budget=150.

6. **v1 comparison data**: v1 recall at 14B/rate=100: b=50→25.7%, b=75→57.1%, b=100→80.0%, b=125→80.0%, b=150→91.4%, b=200→94.3%. At rate=200: b=100→70.7%, b=200→92.7%.

7. **Budget arithmetic: v2 at budget=100**: Phase 1 (15) + Phase 2 selective (38) = 53 evals, leaving 47 for Phase 2.5 expanded (44 used), then 3 for Phase 4+. All 7 previously-missed tuples covered within 97 evals.

## System Interface

- **Build:** `go build -o blis main.go` (~2s, binary at `./blis`)
- **Run v1 search:**
  ```bash
  python3 search.py --model qwen/qwen3-14b --rate 100 --budget 100 --seed 42 --out results/v1_b100.json
  ```
- **Run v2 search (after patching):**
  ```bash
  python3 search.py --model qwen/qwen3-14b --rate 100 --budget 100 --seed 42 --out results/v2_b100.json
  ```
- **Output format:** `--metrics-path` writes JSON with `responses_per_sec`, `ttft_p99_ms`
- **GT Pareto:** `final/ground_truth_pareto.json` (14B, rate=100, seed=42, 35 unique tuples from 124 configs)
- **Full enumeration:** `final/full_enumeration.json` (14B, 1800 configs)
- **Baseline result:** v1 at budget=100 → 80.0% recall (28/35 tuples)

## Code Map

- `search.py:214-318` — all search phases. Main edit target.
- `search.py:220-228` — Phase 1 (ceiling) + Phase 2 (cache sweep). Phase 2 needs selective kv extension.
- `search.py:229-265` — Phase 2.5 (degraded-regime interaction). Needs expansion to all degraded combos.
- `search.py:267-270` — Phase 3 (bs=16 sweep). **Delete entirely.**
- `search.py:272-317` — Phases 4-6 (SJF, concurrency, neighbor). Keep but remove Phase 5's maxr=512.
- `search.py:40-48` — `get_tp_instance_combos()` helper
- `search.py:204-212` — `_get_ceiling_rps()` helper
- `final/ground_truth_pareto.json` — 14B GT Pareto (124 configs, 35 unique tuples)
- `final/full_enumeration.json` — 14B full enumeration (1800 configs)
- `cmd/root.go:963-980` — All 6 knob flag definitions
- `sim/latency/trained_physics.go` — TP divisibility constraint

## Code Targets

### search.py — Three modifications

**Modification 1: Selective Phase 2 (lines 224-228)**
Replace full 15-combo × 4-kv sweep with: all combos at kv=2000,3000; then extend to kv=4000,5000 ONLY for combos still degraded at kv=3000 (ratio < 0.99 vs ceiling).

**Modification 2: Eliminate Phase 3 (lines 267-270)**
Delete the Phase 3 block entirely (bs=16 sweep, zero Pareto impact).

**Modification 3: Expand Phase 2.5 (lines 229-265)**
Probe ALL degraded combos (0.99 threshold, not just best-per-GPU). Backbone: sjf+128, sjf+256, fcfs+128 at degraded kv + near-ceiling sjf+256. Non-best: sjf+128, sjf+64, fcfs+64 at degraded kv. Descending TP order.

## What I Tried That Didn't Work

- **(iter-1) maxr=512 never improves over 256**: Universal across all models.
- **(iter-2) Independent SJF exploration**: Misses interaction effect.
- **(iter-3) qwen2.5-7b at tp=8**: Panics. Dynamic TP validation handles this.
- **(iter-4) Phase reordering alone**: Improved 57.1% → 80% but still below target.
- **(iter-4) Budget=200 ≠ 100% recall**: Both orderings give 94.3%. Prior claim was incorrect.
- **(iter-4) Phase 2.5 scope broadening without Phase 2 reduction**: Budget arithmetic blocks it (RP-3, RP-9).
- **(iter-4) Removing fcfs+128 from Phase 2.5**: Loses 13.7% of GT Pareto configs (RP-10).

## What I Excluded and Why

- **Block size 16 exploration**: Proven zero Pareto impact (bs=32 dominates at same kv). RP-11.
- **maxr=512 variants**: RP-4 plateau at 256.
- **maxr=32 variants**: Not in GT Pareto — too restrictive.
- **kv=7500,10000 in Phase 2**: At ceiling, produces dominated tuples.
- **Adaptive budget allocation**: Not needed — fixed-phase restructuring achieves 100%.

## Evolution of Thinking

**Iter-1-2**: Discovered structural regularities (TP dominance, cache equiv, maxr plateau, SJF×maxr).
**Iter-3**: Validated across models (7B, 14B, 70B). Added dynamic TP validation.
**Iter-4**: Phase ordering improved b=100 from 57.1% → 80%. Scope broadening blocked by budget arithmetic.
**Iter-5**: Key insight — fix Phase 2 EFFICIENCY (33.3%), not Phase 2.5 scope within fixed overhead. Selective Phase 2 + Phase 3 elimination frees 52 evals. Expanded Phase 2.5 uses freed budget to probe all degraded combos. 100% recall at budget=100 achieved.

## Current Status

- **Validated:** v2 prototype: 100% at budget=100 on 14B/rate=100, 7B/rate=100, 14B/rate=50. 97.6% at rate=200.
- **Uncertain:** Rate=200 single miss (sjf near-ceiling kv=5000) addressable within budget=100.
- **Suggested next (iter-6):** Adaptive Phase 4 priority for rate=200 edge case. Cross-GPU-type testing. Seed robustness.

## Warnings & Constraints

- **GT key names differ**: 14B GT uses `rps`/`ttft_p99`, search uses `responses_per_sec`/`ttft_p99_ms`.
- **Rounding**: Use `round(x, 4)` for tuple matching.
- **search.py must remain stdlib-only**: No numpy.
- **Phase 2.5 near-ceiling probe**: Scan cache for tested kv at (tp,ni) to find first non-degraded kv.
- **7B has 11 combos (not 15)**: tp=8 invalid. Phase 2 selective adapts automatically.
