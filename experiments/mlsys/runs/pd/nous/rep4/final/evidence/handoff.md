# Handoff Snapshot — Iter-4: Structural vs Transient Formula Mismatch

## Goal

Run 54 BLIS simulations (9 rates × 2 P/D modes × 3 seeds), extract per-request ITL data from each run, and perform quartile analysis to determine whether the paper's ITL formula breakdown is caused by finite-horizon transient effects or by a structural mismatch in BLIS's latency model. The key analysis: compare R² of the best-fit 1/(1−ρ) formula applied to full-run means vs Q2-Q3 (quasi-steady-state) means.

## Key Discoveries

1. **Per-request ITL follows an inverted-U within each run at high rates**: At rate=100 (AL), Q1=18.1ms, Q2=19.4ms, Q3=18.9ms, Q4=17.2ms. Early requests (ramp-up) and late requests (drain) have lower ITL than the middle (quasi-steady-state). The ITL spread reaches 12.1% of the mean at rate=100.

2. **Removing transients WORSENS formula fit (critical finding)**: The best-fit 1/(1−wλ) formula applied to Q2-Q3 means gives R²=0.874 (AL) and R²=0.924 (AD), which is LOWER than the full-run fit of R²=0.918 (AL) and R²=0.947 (AD). The formula's convex shape is a structural mismatch with the data's concave shape — removing transients amplifies the concavity.

3. **AD scheduling delay is constant at 15.56ms**: For all rates 5–150 and all quartiles, the scheduling delay in AD mode is exactly 15.56ms. TTFT growth with rate comes entirely from prefill batching (prefill step time increases as the prefill instance batches more requests).

4. **TTFT decomposition differs between modes**: AL TTFT = scheduling_delay(rate, 21–25ms) + prefill_time(rate, 14–20ms). AD TTFT = const_sched(15.56ms) + prefill_batch_time(rate, 30–34ms) [includes ~3.4ms KV transfer].

5. **Near-zero seed variance persists**: Across all probes, ITL variance across seeds is < 0.01ms. The experiment tests structural formula fit, not stochastic variation.

6. **BLIS StepTime has nonlinear batch-size terms**: `sumCtx` in `tDcKv` (line 238) grows with total context lengths across all batch members, and `nEff = min(N, max(k, B*k))` (line 248) for MoE scaling grows sub-linearly with batch size once all experts are active.

7. **Both full and Q2-Q3 data are concave at high rates**: The acceleration (second differences) of ITL vs rate is negative for rates ≥60, with Q2-Q3 showing LARGER negative accelerations than full data. The formula predicts positive accelerations (convex growth).

## System Interface

- **Build:** `go build -o blis main.go` (exit 0, produces `./blis`)
- **Run (template):**
  ```bash
  ./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --pd-decider {never|always} --rate {rate} --seed {seed} --metrics-path {output_path} 2>/dev/null
  ```
- **Output format:** `--metrics-path` writes single JSON dict. Top-level keys include `itl_mean_ms`, `ttft_mean_ms`, `e2e_mean_ms`, `completed_requests`, and importantly `requests` (array of 300 per-request records). Each request record has `arrived_at`, `itl_ms`, `ttft_ms`, `scheduling_delay_ms`, `handled_by`, `requestID`.
- **Baseline result:** AL rate=10 seed=42: itl_mean_ms=12.801, ttft_mean_ms=36.584, completed=300, 300 per-request records present.

## Code Map

| File:Line | What's there | When to look |
|-----------|-------------|--------------|
| `sim/latency/trained_physics_model.go:154-331` | StepTime() — full step time computation | Understanding why ITL grows sub-linearly with batch size |
| `sim/latency/trained_physics_model.go:238` | `bytesDcKv` — decode KV bandwidth scales with sumCtx | The key nonlinear term: grows as Σ(context_length) across batch |
| `sim/latency/trained_physics_model.go:248` | `nEff = min(N, max(k, B*k))` — MoE expert scaling | Sub-linear scaling once B*k > N (all experts active) |
| `sim/latency/trained_physics_model.go:326` | `m.Beta[5]*batchSize` — direct linear batch overhead | Linear component of batch-size effect |
| `sim/simulator.go:715` | Scheduling delay recording: `now - ArrivalTime` | If scheduling delay values seem off |
| `sim/simulator.go:781-784` | TTFT recording: `now + stepAdvance + OutputTokenProcessingTime() - ArrivalTime` | If TTFT decomposition doesn't add up |
| `sim/simulator.go:772` | ITL recording: `currStepAdvance + OutputTokenProcessingTime()` | Per-token ITL computation |
| `sim/disaggregation.go:44-58` | NeverDisaggregate / AlwaysDisaggregate | If routing behavior seems wrong |
| `sim/metrics.go:95-116` | Aggregate metric computation | If aggregates don't match per-request analysis |
| `cmd/root.go:1019-1025` | CLI flag definitions for P/D settings | If flags don't behave as expected |

## Code Targets

No code changes — all arms use flag-only variations plus post-hoc per-request analysis.

## What I Tried That Didn't Work

1. **Hypothesis that Q2-Q3 restriction would improve formula fit**: Initial expectation was that removing ramp-up/drain transients would bring the data closer to the formula's steady-state prediction. Instead, it makes the fit WORSE. The reason: Q2-Q3 restriction raises high-rate means (where transients suppress ITL most) without changing low-rate means, making the overall curve MORE concave while the formula is convex.

2. **numpy/scipy for curve fitting**: Not available in system Python. Use manual grid search: α ∈ [11.50, 13.10] step 0.01, w ∈ [0.00100, 0.00600] step 0.00005. Linear fit via least-squares formulas.

3. **`--output` flag**: Does not exist. Use `--metrics-path`.

4. **4-way load balancing in AL mode**: With `--pd-decider never`, only 2 decode instances (instance_2, instance_3) receive requests. Prefill instances (0,1) get 0 requests.

## What I Excluded and Why

1. **Steady-state extraction by discarding early/late requests**: Iter-4 analysis covers this via Q2-Q3, but explicitly tests the hypothesis that Q2-Q3 is "steady-state." The result shows even Q2-Q3 doesn't recover the formula, so steady-state extraction is insufficient.

2. **Variable token lengths (stdev > 0)**: Locked at 0 by the research question to isolate rate effects.

3. **Higher-order formula fits (e.g., α(1 + wλ + (wλ)²))**: The quadratic Taylor expansion of 1/(1−wλ) could be tested, but the linear fit already achieves R² > 0.97, making higher-order corrections marginal. Future iterations could explore this.

4. **Rates above 150 or below 5**: The research question specifies 1–150. Rates below 5 have negligible batching (batch ≈ 1).

5. **Per-token ITL analysis (individual tokens within a request)**: The `itl_ms` field is the mean across 128 tokens. Sub-token granularity would require trace-level output not available via `--metrics-path`.

## Evolution of Thinking

**Starting assumption**: The formula breaks down at high rates because of finite-horizon transient effects. If we could extract the "steady-state" portion of each run (Q2-Q3), the formula would fit better.

**What the data revealed**: The OPPOSITE is true. Removing transients makes the formula fit WORSE. This is because:
1. The transient phases (ramp-up Q1, drain Q4) contribute LOW ITL values that partially linearize the overall mean curve.
2. The quasi-steady-state portion (Q2-Q3) is MORE concave than the full data, amplifying the structural mismatch with the convex 1/(1−ρ) formula.
3. The formula's fundamental problem is not transient averaging but that BLIS's StepTime() produces sub-linear per-request ITL scaling with batch size (due to sumCtx and MoE nEff terms).

**Revised understanding**: The formula breakdown has TWO independent causes:
1. **Structural**: BLIS's latency model (trained-physics) has nonlinear batch-size terms that the paper's linear-W assumption doesn't capture. This makes ITL grow concavely with rate.
2. **Transient**: The finite-horizon ramp-up/drain phases further suppress the mean below the (already too-low) quasi-steady-state value. But this transient effect partially COMPENSATES for the structural mismatch at moderate rates by linearizing the curve.

## Current Status

- **Validated:**
  - Build and baseline commands work correctly
  - Per-request data (`requests` array) is present in `--metrics-path` output with all needed fields
  - Quartile analysis reveals inverted-U ITL pattern at high rates (confirmed at rates 5, 20, 60, 100, 150)
  - Q2-Q3 formula R² is lower than full-run R² (AL: 0.874 < 0.918; AD: 0.924 < 0.947)
  - AD scheduling delay is constant at 15.56ms across all rates and quartiles
  - All 300 requests complete without drops at all rates 5–150

- **Uncertain:**
  - Exact R² values will be computed from fresh iter-4 data (expected to be very close to iter-3 values given near-deterministic behavior)
  - Whether the inverted-U ITL spread shape holds for AD mode at rate=150 (probed for AL only at all rates)

- **Suggested next (iter-5):**
  - Investigate whether a modified formula (e.g., ITL = α + b·log(1+c·rate)) captures the concave shape better than both linear and 1/(1-ρ)
  - Test with `--latency-model roofline` to see if the structural mismatch changes (roofline may have different batch-size scaling)
  - If the research question constraint is lifted: test with larger num_requests (e.g., 3000) to see if the transient fraction shrinks enough to make the formula viable

## Warnings & Constraints

1. **Suppress stderr**: Use `2>/dev/null` — BLIS prints wall-time timer to stderr that interferes with stdout parsing.

2. **Metrics-path output format**: Single JSON dict. The `requests` array is at top level: `d['requests']`, each entry has `itl_ms` (float, mean per-token ITL for that request).

3. **Formula fitting without numpy**: System Python lacks numpy/scipy. Use grid search:
   - α ∈ [11.50, 13.10] step 0.01, w ∈ [0.00100, 0.00600] step 0.00005
   - R² = 1 − SS_res/SS_tot
   - Linear fit: standard least-squares formulas (no library needed)

4. **Per-request ITL is the mean over 128 tokens**: The `itl_ms` field for each request is already averaged over its decode tokens. There is no per-token breakdown.

5. **Quartile boundaries**: With 300 requests, Q1=requests[0:75], Q2=requests[75:150], Q3=requests[150:225], Q4=requests[225:300]. Sorted by `arrived_at` (arrival time).

6. **Near-zero seed variance**: ITL variation across seeds < 0.01ms. Seed-averaged values are effectively identical to any single seed. Multi-seed is for replication confidence, not statistical power.

7. **AL mode uses only 2 instances**: `--pd-decider never` routes all requests to decode instances (2 and 3). Effective per-instance rate = total_rate/2.
