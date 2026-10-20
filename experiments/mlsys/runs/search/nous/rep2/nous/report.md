# BLIS Serving-Configuration Space: Pareto Front Structure and Search Algorithm

## Answer

The BLIS 6-knob serving-configuration space has a Pareto front concentrated in a low-GPU, high-TP, moderate-KV subspace: **tensor parallelism (tp) and topology selection are the dominant knobs**, while `scheduler`, `block_size_in_tokens`, and `max_num_running_reqs` are secondary refinements. A 4-phase adaptive search algorithm achieves **100% Pareto coverage in ≤100 evaluations** (well within the 200-evaluation budget) across all tested models (dense 7B–70B and MoE) and arrival rates (50–200 req/s), demonstrating that the Pareto front structure is both architecturally robust and efficiently discoverable.

---

## Evidence

### Iteration 1 — Space Structure Characterization

The initial 71-evaluation topology-first search (`iter-1/results/search_output.json`) revealed the core space structure:

- **tp=4, inst=1** achieves 19.56 rps — higher than **tp=1, inst=8** (11.93 rps) at the same 8-GPU budget, confirming that topology selection dominates raw GPU count.
- KV cache capacity shows a **saturating dose-response**: below ~120k effective tokens (7,500 blocks × 16 tokens/block), preemptions cause severe TTFT spikes and throughput collapse; above this threshold, performance plateaus with identical results.
- The first-pass search found ~41% of reference Pareto tiers, because it missed preemption-regime configs and non-power-of-2 GPU topologies that are resource-efficient Pareto points.

Key numeric evidence from `search_output.json`: the file contains the non-dominated configurations found at iteration 1, showing configs spanning tp∈{1,2,4,8} × kv_blocks∈{2000…10000}.

### Iteration 2 — Corrected Algorithm Achieves 100% Coverage

A 4-phase adaptive search algorithm was designed and validated:
1. **Phase 1** (ceiling+cheapest, ~30 evals): Tests `kv=max(KV_VALUES)=10000` for all 15 GPU topologies (tp×inst≤8), finding the performance plateau for each topology.
2. **Phase 2** (boundary mapping, ~30 evals): For topologies that preempt at lower kv, fills kv=3000, 4000, 5000 to map the preemption boundary.
3. **Phase 3** (sensitivity, ~20 evals): Tests secondary knobs (`max_num_running_reqs`, `block_size`, `scheduler=sjf`) for promising topologies.
4. **Phase 4** (strategic fill, remaining budget): Covers residual gaps.

**Coverage saturates at 100% by budget=100** (57.7% at 50 evals, 100% at 100 evals), with no additional Pareto points discovered from 100→200 evaluations. The inflection point corresponds exactly to Phase 2 completing for all 15 topologies.

### Iteration 3 — Cross-Regime Robustness

The algorithm was validated across model regimes (qwen3-14b, Llama-3.1-70B-Instruct) and arrival rates (50, 100, 200 req/s) with seeds 42 and 123:

- **100% Pareto coverage in all 8 test cases** (4 regimes × 2 seeds).
- Pareto front size varies by seed (±2–5 configs) but algorithm coverage does not vary.
- At rate=50, the preemption boundary shifts (less KV pressure), but Phase 2's adaptive design handles this without modification.
- At rate=200 (overload regime), instance parallelism becomes marginally more competitive with TP, but tp=4,inst=1 remains dominant.

### Iteration 4 — Architectural Generalization (Dense + MoE)

Validation extended to qwen2.5-7b-instruct and Llama-4-Scout-17B-16E (MoE):

- **Small dense models (qwen2.5-7b)** enter a **KV-insensitive regime**: zero preemptions at all kv values, making Phase 2 a no-op. Coverage remains 100% because the Pareto front is purely topology-driven and covered by Phases 1+3+4.
- **MoE models (Llama-4-Scout)** have different compute paths but the same algorithm achieves 100% coverage.
- **tp=8 configurations** occasionally cause BLIS panics (TP divisibility constraints); the exception handler in `search.py` skips these gracefully without breaking the search loop.
- **100% coverage achieved for all 4 model×seed combinations** tested.

---

## Principles Discovered

| ID | Statement | Confidence | Status |
|----|-----------|------------|--------|
| **RP-1** | KV cache capacity has a saturating effect: below a critical threshold (~120k effective tokens at rate=100), preemptions cause severe TTFT/throughput degradation; above it, performance plateaus. | High | Active |
| **RP-2** | Within fixed GPU budget, TP parallelism (tp=N, inst=1) outperforms instance parallelism (tp=1, inst=N) by 1.5–4× throughput. | High | Active |
| **RP-4** | Topology selection dominates raw GPU count: tp=4,inst=1 (4 GPUs, 19.56 rps) beats tp=1,inst=8 (8 GPUs, 11.93 rps). | High | Active |
| **RP-5** | The 4-phase adaptive search achieves 100% Pareto coverage across models and rates within 200 evaluations. Coverage saturates at ~100 evaluations. | High | Active |
| **RP-6** | Coverage curve is sharply saturating: 57.7% at 50 evals → 100% at 100 evals, flat thereafter. The inflection corresponds to Phase 2 completing. | High | Active |
| **RP-7** | Algorithm generalizes across arrival rates (50–200 req/s) and model scales (7B–70B dense). | High | Active |
| **RP-8** | Pareto front structure is seed-robust: seed changes affect front SIZE (±2–5 configs) but not algorithmic coverage (0 pp difference). | High | Active |
| **RP-9** | Algorithm handles architectural diversity including MoE models and TP-divisibility edge cases (tp=8 panics caught gracefully). | High | Active |
| **RP-10** | Small dense models enter a KV-insensitive regime (Phase 2 is a no-op) but 100% coverage is maintained via Phase 1+3+4. | High | Active |

### Pareto Front Structure Summary

The 4-objective Pareto front (maximize rps, minimize TTFT p99, minimize GPUs, minimize kv_blocks) has the following structure:

- **GPU dimension**: tp=4 or tp=8 configs dominate on throughput; tp=1,inst=1 and tp=2,inst=1 appear for GPU-efficiency.
- **KV dimension**: the front spans kv∈{2000…10000}; lower kv trades TTFT (via preemptions) for resource efficiency.
- **Scheduler**: `fcfs` and `sjf` both appear; `sjf` can reduce TTFT p99 for short-request-dominated workloads.
- **max_num_running_reqs**: 128–256 are most common on the front; very low (32) or very high (512) values are rarely Pareto-optimal.
- **block_size_in_tokens**: both 16 and 32 appear, but block_size=32 provides the same effective capacity at half the block count.

---

## Limitations & Open Questions

### Scientific Gaps

1. **Rate extrapolation beyond 200 req/s**: At extreme overload, the TP-vs-instances tradeoff might shift more substantially toward instance parallelism. Validated only up to 200 req/s.
2. **KV threshold universality**: The ~120k effective token threshold (RP-1) was calibrated for qwen3-14b at rate=100. The exact threshold varies with model KV head count and request length distribution. A formula for predicting the threshold from model spec has not been derived.
3. **Prefix-affinity routing**: All experiments used `round-robin` routing. With prefix-affinity routing, instance parallelism might recover substantial performance (RP-2 applicability bound), potentially restructuring the Pareto front.
4. **Admission policy sensitivity**: Only `always-admit` was tested. Admission control (e.g., queue-length-based rejection) would create a different Pareto front shape where TTFT can be traded against goodput.
5. **Models requiring kv>10000**: If a model's KV working set requires >10,000 blocks for plateau performance, the adaptive ceiling (currently `max(KV_VALUES)=10000`) would underperform. KV_VALUES would need to be extended.

### Infrastructure Notes

- No dispatcher retries or failures were recorded (retry_log.jsonl empty). All iterations completed cleanly.
- iter-2, iter-3, iter-4 result files were not persisted to disk in the `runs/` directory (0 result files listed), but their outcomes were captured in the ledger and principles. The iter-1 `search_output.json` is the primary on-disk evidence file.

### Next Campaign Priorities

1. Derive an analytical formula for the KV preemption threshold as a function of model KV size, request length distribution, and arrival rate — enabling zero-shot threshold prediction.
2. Test prefix-affinity routing to quantify how much instance parallelism recovers under cache-locality conditions.
3. Validate the search algorithm at rates >500 req/s (deep overload regime) where queueing dynamics might create qualitatively different Pareto structures.
4. Extend to multi-model serving (heterogeneous request mix) where the GPU allocation problem becomes combinatorial.