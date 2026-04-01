# Case Study: BLIS — LLM Inference Serving Optimization

This case study documents how the Nous methodology was developed and validated through 30 iterations and over 1,000 experiments on [BLIS](https://github.com/inference-sim/inference-sim), a discrete-event simulator for LLM inference serving systems.

## Context

BLIS models the full lifecycle of LLM inference requests — routing, scheduling, KV-cache management, and batching — at the level of individual decode steps. It supports multiple GPU types, SLO tiers, and arrival distributions.

The research question: **How should requests be routed, scheduled, and admitted to minimize tail latency while maintaining throughput across heterogeneous workloads?**

## Campaign Structure

The investigation split into two parallel tracks that converged on a shared discovery:

| Track | Iterations | Focus | Key Metric |
|---|---|---|---|
| Scheduling | 11 | Priority scheduling, preemption, batch management | Critical TTFT P99 |
| Routing | 19 | Request routing signals, load balancing, admission | Combined latency improvement |

## Key Discovery: SLO-Gated Admission Control

Both tracks independently discovered that **SLO-gated admission control** is the critical mechanism for avoiding zero-sum tradeoffs at saturation. This emerged not from confirming hypotheses, but from analyzing refuted predictions.

**Scheduling Track, Iteration 1:** The bundle included a custom arm H-zero-sum testing whether prioritizing critical requests would degrade cluster-wide metrics. Prediction: <10% degradation. Observed: **62.4% cluster degradation**. This direction error revealed that priority scheduling without admission control is fundamentally zero-sum — improving one tier necessarily degrades others.

The diagnostic clause ("if failed, investigate whether the system needs a mechanism to reject low-value work") led directly to the admission control hypothesis in the next iteration.

**Routing Track, Iteration 6:** Testing removal of the KV-utilization routing scorer. H-main confirmed that removing it improved performance, establishing principle RP-6 (KV-utilization is counterproductive under memory pressure). The control-negative arm revealed the regime boundary: the effect vanished only below 30% memory pressure, not the predicted 50%.

## Extracted Principles

### Routing Principles (RP-1 through RP-14)

| ID | Statement | Evidence |
|---|---|---|
| RP-1 | Prefix-affinity routing reduces tail latency variance; effect strongest under burst load | Iterations 2, 5 (H-main confirmed, H-robustness confirmed across distributions) |
| RP-2 | Queue-depth balancing prevents starvation of shallow sequences under high contention | Iteration 3 (H-main confirmed) |
| RP-3 | Compound routing (prefix-affinity + queue-depth) exhibits super-additivity at >60% utilization | Iteration 5 (H-super-additivity confirmed) |
| RP-4 | Compound routing effect vanishes below 60% utilization (not 50% as initially predicted) | Iteration 5 (H-control-negative refuted, regime error corrected) |
| RP-5 | Request-size-aware routing outperforms random assignment by >20% for heterogeneous workloads | Iteration 4 (H-main confirmed) |
| RP-6 | KV-utilization scorer is counterproductive under memory pressure >30% | Iteration 6 (H-main confirmed removal improves performance) |
| RP-7 | Admission control admission threshold is load-dependent, not fixed | Iterations 8, 12 (H-control-negative refuted, regime error, updated from 50% to 60%) |
| RP-8 | SLO-gated admission is non-zero-sum at saturation — it creates capacity rather than redistributing it | Iteration 9 (H-main confirmed, H-zero-sum refuted) |
| RP-9 | Admission control + compound routing yields >65% combined improvement over baseline | Iteration 12 (H-main confirmed) |
| RP-10 | Bursty (Gamma) arrivals amplify the benefit of admission control vs. constant arrivals | Iteration 14 (H-robustness partial, magnitude error) |
| RP-11 | Three-signal routing (prefix-affinity, queue-depth, request-size) is robust across GPU heterogeneity | Iteration 15 (H-robustness confirmed) |
| RP-12 | Routing signal weights should be workload-adaptive, not static | Iteration 16 (H-main confirmed via Bayesian optimization) |
| RP-13 | Over-admission is preferable to under-admission: rejected requests can retry, but admitted requests consume resources | Iteration 17 (H-main confirmed) |
| RP-14 | Token-level preemption interacts with routing: preemptible requests tolerate suboptimal routing | Iteration 19 (H-super-additivity refuted, independence confirmed) |

### Scheduling Principles (S1 through S16)

| ID | Statement | Evidence |
|---|---|---|
| S1 | SLO-tiered priority without admission control is zero-sum at saturation | Iteration 1 (H-zero-sum refuted, 62.4% cluster degradation) |
| S2 | Priority scheduling reduces critical TTFT P99 by >40% when paired with admission control | Iteration 2 (H-main confirmed) |
| S3 | Preemption of low-priority requests is necessary for SLO compliance under burst load | Iteration 3 (H-main confirmed) |
| S4 | Batch size limiting reduces decode latency variance at the cost of throughput | Iteration 4 (H-main confirmed, tradeoff quantified) |
| S5 | Chunked prefill prevents head-of-line blocking for long-context requests | Iteration 5 (H-main confirmed) |
| S6 | Admission control threshold must be SLO-tier-aware, not global | Iteration 6 (H-control-negative refuted) |
| S7 | Token budget allocation per SLO tier prevents starvation more effectively than strict priority | Iteration 7 (H-main confirmed) |
| S8 | Dynamic batch sizing (based on queue depth) outperforms fixed batch sizes by >15% | Iteration 7 (H-ablation confirmed) |
| S9 | Preemption granularity matters: token-level outperforms request-level by 20% for mixed workloads | Iteration 8 (H-main confirmed) |
| S10 | Scheduling overhead is <2% of total latency for batches up to 64 requests | Iteration 8 (H-control-negative confirmed) |
| S11 | Compound scheduling (priority + preemption + admission) reduces critical TTFT P99 by 73.7% | Iteration 9 (H-main confirmed, compound strategy validated) |
| S12 | The three scheduling components are super-additive: compound effect > sum of parts | Iteration 9 (H-super-additivity confirmed) |
| S13 | Greedy-fill batch packing outperforms first-fit by 8-12% for heterogeneous request sizes | Iteration 10 (H-main confirmed) |
| S14 | NNLS-fitted latency models predict per-token decode time within 5% error | Iteration 10 (H-robustness confirmed across GPU types) |
| S15 | Teacher-forced reconstruction improves latency model accuracy by 15% vs. autoregressive | Iteration 11 (H-main confirmed) |
| S16 | The scheduling strategy is robust across Poisson, Gamma, and trace-driven arrival patterns | Iteration 11 (H-robustness confirmed) |

## Prediction Error Analysis

The most valuable insights came from prediction errors:

### Direction Errors (mechanism fundamentally wrong)
- **S1:** Priority scheduling alone was predicted to be Pareto-improving. Actual: zero-sum at saturation. This redirected the entire scheduling track toward admission control.
- **RP-6:** KV-utilization scorer was predicted to help routing. Actual: it degraded performance under memory pressure. Led to principle that KV-utilization is counterproductive in constrained regimes.

### Magnitude Errors (right direction, wrong strength)
- **RP-10:** Admission control benefit under bursty arrivals was predicted at 2x vs. constant. Actual: 1.4x. Refined the quantitative model without changing the mechanism.

### Regime Errors (works in different conditions)
- **RP-4/RP-7:** Utilization threshold for routing/admission effects was predicted at 50%. Actual: 60%. Corrected the regime boundary, which was critical for deployment decisions.
- **S6:** Global admission threshold was predicted to work across SLO tiers. Actual: tier-specific thresholds needed. Led to per-tier admission control design.

## Fast-Fail in Practice

Fast-fail rules saved significant compute:
- **Scheduling iteration 1:** H-zero-sum refuted with 62.4% degradation. Remaining arms (H-ablation, H-robustness) were skipped, saving ~4 hours of simulation time.
- **Routing iteration 6:** H-main confirmed removal of KV scorer. H-control-negative refuted (regime error at 30% vs. predicted 50%), triggering deeper investigation rather than parameter tuning.

## Convergence

The campaign demonstrated two-track convergence:
- **Scheduling track** (11 iterations): 73.7% critical TTFT P99 improvement. Stabilized after iteration 9 (S11, compound strategy), with iterations 10-11 focused on robustness and parameter fitting.
- **Routing track** (19 iterations): 65% combined improvement. Longer due to the larger design space, but principles stabilized after iteration 15.

Both tracks converged on admission control as the breakthrough "third lever" — discovered through prediction errors, not successful predictions.
