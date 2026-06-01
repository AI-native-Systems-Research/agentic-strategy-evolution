# Campaign authoring guide

This guide covers the disciplines that make a Nous campaign
**reproducible**, **spec-faithful**, and **defensible to a paper
reviewer**. It collects the practices that emerged from the friction
report on paper-memorytime-mirage (tracking issue #245) — most of
which now have concrete tooling support behind them.

## The "what to lock" inventory (#258 / F13)

Before you start a campaign, enumerate every target-system parameter
that could plausibly affect the experimental physics. For EACH,
decide: **is deviation acceptable?** If no, lock it.

The reactive failure mode — adding parameters to ``locked_parameters``
only after each one bites you in a review round — turns a 2-week
campaign into a 5-round dance with no end in sight. Up-front
enumeration costs an hour and saves all of it.

### Inventory template (LLM-serving target)

Adapt for your target system. The table is the discipline; the
specific knob names vary.

| Category | Parameter | Default | Lock? | Reasoning |
|---|---|---|---|---|
| Workload identity | ``model`` | (varies) | YES | Model determines π/δ in the latency model — different model = different physics |
| Workload identity | ``concurrency_per_tenant`` | 32 | YES | Concurrency directly drives the metric |
| Workload identity | ``duration_seconds`` | 600 | YES | Below ~120s, scale-dependent checks (PMF histogram, 99.9% backlog-nonempty) lose statistical power |
| Workload identity | ``warmup_seconds`` | 30 | YES | Short warmup admits transients into measurement window |
| KV / batching | ``total_kv_blocks`` | (derived from GPU) | YES if testing contention | K=1M with 16-token blocks = no contention; K=24576 ≈ realistic on H100 |
| KV / batching | ``MaxModelLen`` | 4096 | YES if requests exceed | Below P_max, requests are silently dropped |
| KV / batching | ``MaxOutputLen`` | 1024 | YES if D matters | Overrides D=1 in the workload spec |
| KV / batching | ``max_num_seqs`` | 256 | Maybe | Below 2 × concurrency, throttles closed-loop |
| KV / batching | ``max_batched_tokens`` | 8192 | YES if prefill matters | Limits prefill batch composition |
| KV / batching | ``gpu_memory_utilization`` | 0.9 | YES if K is derived | Affects K derivation |
| KV / batching | ``BlockSize`` | 16 | Usually no | Architecture-dependent; document the value |
| Latency model | ``MfuPrefill`` | (per-model file) | Snapshot via #262 | Snapshot the file SHA into reproducibility metadata |
| Latency model | ``MfuDecode`` | (per-model file) | Snapshot via #262 | Same |
| Latency model | TP factor | 1 | YES if testing distributed | TP=2 vs TP=1 changes π/δ |
| Admission / gateway | ``AdmissionLatency`` | 0 | Usually no | Document; rarely matters |
| Admission / gateway | ``RoutingLatency`` | 0 | Usually no | Document; rarely matters |
| Admission / gateway | ``FlowControlEnabled`` | false | YES if relevant | Changes admission semantics |
| Disaggregation | ``PDDecider`` | none | YES if testing | Changes architecture |
| Disaggregation | ``PDTransfer*`` | (defaults) | YES if testing | Changes architecture |
| Network | ``rtt_ms`` | 0 | YES if testing | Changes timing |
| Network | ``bandwidth`` | unlimited | YES if testing | Changes timing |
| Streaming | ``streaming`` | false | YES if testing | Changes per-token timing |

## Pre-lock unit check (#259 / F14)

Before locking a parameter to a specific value, **unit-check the
closed-form prediction against your locked parameters**.

### Worked example (paper-memorytime-mirage)

The campaign locked ``D=8`` (output tokens per request) and ``K=1M``
(KV blocks). Both choices were defensible in isolation; combined,
they produced a regime where the campaign's own theory predicted
ρ_mt ≈ 1.06 — a null result. The campaign author would have caught
this by computing:

```
C_KV(P=1024, D=8) / C_KV(P=mixture, D=8)
```

Under realistic π/δ, that ratio comes out to ≈ 1.06 (decode
dominates; equal-mean P_A=P_B masks the variance signal). Pre-lock
unit check would have shown the D=8 error before iter-1 ran.

The principle: *closed-form math is cheap; an iter-1 LLM run is
expensive*. Walk the prediction by hand at your locked parameters
before committing.

## Rehearsal as scientific instrument (#259 / F14)

This is the **affirmative case for the rehearsal mechanism**. In
paper-memorytime-mirage iter-1, the rehearsal_subset (h-main arm,
seed 42, both schedulers) ran at the campaign's locked parameters.
Both Token-WFQ and KV-time-greedy produced ρ_mt ≈ 1.06 — vastly
below the predicted 3.0×. Rather than reporting null findings, the
agent ran a diagnostic D=1 probe, which produced ρ_mt ≈ 4.378 under
WFQ. From the contrast, it correctly diagnosed two campaign-author
errors:

1. **D=8 puts the system in a decode-dominated regime** where
   memory-time ∝ P·D, and equal-mean P_A=P_B masks the variance
   signal. Recommendation: D=1.
2. **K=1M blocks makes the bucket inoperative** (ω·K = 450K vs
   ~152 actual occupancy). Recommendation: K ≤ 1000.

The findings.json discrepancy_analysis was a clean post-mortem.
The agent confirmed apparatus correctness (zero conservation
violations, WFQ counter balance ratio 1.003) before declaring
REFUTED with diagnostic_note recommending specific parameter fixes
for iter-2.

**Why this matters.** The campaign author made two non-trivial
workload-design errors that no amount of pre-run review caught.
Iter-1 surfaced both with diagnostic precision, suggested fixes, and
confirmed the underlying mechanism is real (4.38× mirage at D=1).
Without rehearsal, iter-2 would have produced null results at full
scale.

**Use rehearsal as the diagnostic instrument it is.** When iter-1
produces a result far from the predicted magnitude, don't just mark
it REFUTED — probe the regime, contrast against a known-engaging
configuration, and recommend specific fixes. ``rehearsal_subset``
exists for this discipline; populate it generously.

## Apparatus discipline (#252 / F7)

Apparatus invariants must validate the **attribution** the experiment
depends on, not an upstream total. See the methodology prompt for
the worked example (the BLIS ``runningBatch`` vs ``RequestMap``
case). Two-line summary: *if the bug-of-interest involves
attribution among items, your invariant must distinguish per-item,
not just sum*.

## Spec-fidelity (#246 / F1, #265 / F20)

``locked_parameters`` and ``locked_workload`` are nous's spec-
fidelity primitives. They hard-fail bundles that deviate from the
campaign's intent, regardless of ``--auto-approve``. Use them
liberally — they are the cheapest defense against silent design-
agent rewrites.

## Reproducibility (#262 / F17)

nous auto-captures ``reproducibility_metadata`` at INIT (target
repo commit, hardware-config sha, language versions, latency-config
file snapshots). The first capture wins — re-running INIT on an
existing campaign preserves the original commit, which is what
reviewers want.

To produce a paper-grade artifact tarball:

```
nous package <run_id>
```

This bundles the work_dir, a ``reproduce.sh`` template, a
``Dockerfile`` pinning captured language versions, and a README.
Drop the tarball in your artifact-evaluation submission.
