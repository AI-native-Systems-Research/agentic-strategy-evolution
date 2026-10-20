# Problem Framing — Iter-2: P/D Disaggregation Latency Model Validation

## Research Question

Do the closed-form ITL and TTFT predictions from the "When to Disaggregate" paper (docs/pd-disagg.pdf) hold inside BLIS, over what range of arrival rates, and where and why do they break down?

Specifically, the paper predicts (Section 3.4–3.5):
1. **ITL formula** (Eq. 17): `ITL = T_iter^D + β + γ(l + (o+1)/2)` where `T_iter^D = α/(1 − ρ_D)` and `ρ_D = λ·W` depends on the routing mode.
2. **Directional predictions**: Always-Disaggregate (AD) has lower ITL than Always-Local (AL) because AD reduces decode-server utilization (`ρ_D = λ·W_D < λ·W_tot`). Conversely, AD has higher TTFT than AL due to the prefill pipeline overhead (prefill queueing + KV transfer).
3. **Shape**: ITL follows a `1/(1−ρ)` hyperbolic form that accelerates as arrival rate increases.

Key source files implementing the mechanism:
- `sim/disaggregation.go` — `DisaggregationDecider` interface and `AlwaysDisaggregate`/`NeverDisaggregate` implementations
- `sim/latency/trained_physics_model.go:154` — `StepTime()` computes per-iteration duration as a function of batch composition
- `sim/simulator.go:724` — `executeBatchStep()` where ITL = StepTime + OutputTokenProcessingTime (line 772)
- `sim/simulator.go:781-784` — TTFT recording
- `cmd/root.go:1022` — `--pd-decider` flag definition

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags relevant to experiment:**
  - `--pd-decider {never,always}` — routing mode (`cmd/root.go:1022`)
  - `--rate <int>` — arrival rate in req/s (`cmd/root.go:970`)
  - `--seed <int>` — RNG seed for Poisson arrivals (`cmd/root.go:969`)
  - `--num-instances <int>` — total instances (`cmd/root.go:943`)
  - `--prefill-instances <int>` — dedicated prefill pool size (`cmd/root.go:1019`)
  - `--decode-instances <int>` — dedicated decode pool size (`cmd/root.go:1020`)
  - `--num-requests <int>` — total requests (`cmd/root.go:972`)
  - `--prompt-tokens <int>` — fixed input length (`cmd/root.go:975`)
  - `--output-tokens <int>` — fixed output length (`cmd/root.go:979`)
  - `--routing-policy least-loaded` — load balancing (`cmd/root.go:1007`)
  - `--metrics-path <path>` — write aggregate metrics JSON to file (`cmd/root.go:1044`)
  - `--pd-transfer-bandwidth <float>` — KV transfer bandwidth in GB/s, default 25.0 (`cmd/root.go:1023`)
  - `--pd-transfer-base-latency <float>` — KV transfer base latency in ms, default 0.05 (`cmd/root.go:1024`)
- **Output:** `--metrics-path <path>` writes MetricsOutput JSON. Stdout emits `=== Simulation Metrics ===` sections per instance + cluster aggregate + `=== PD Metrics ===` (when pd-decider != never).

## Baseline Command

```bash
./blis run \
  --model qwen/qwen3-14b \
  --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 \
  --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 \
  --routing-policy least-loaded \
  --pd-decider never --rate 10 --seed 42 \
  --metrics-path results/baseline_al_r10_s42.json
```

## Baseline Validation

Ran with `--num-requests 50 --rate 10 --pd-decider never --seed 42`. Exit code 0.

Key observed values (cluster aggregate):
- `itl_mean_ms`: 12.738
- `ttft_mean_ms`: 36.840
- `e2e_mean_ms`: 1655.306
- `completed_requests`: 50
- `dropped_unservable`: 0

All 50 requests completed. Only decode instances (2,3) received traffic; prefill instances (0,1) had 0 requests — confirmed AL routes directly to decode pool.

AD mode also validated (`--pd-decider always`):
- `itl_mean_ms`: 12.627
- `ttft_mean_ms`: 45.920
- `e2e_mean_ms`: 1611.527
- KV Transfer Duration: mean=3406µs

## Experimental Conditions

### Condition 1: Always-Local (AL) sweep across rates
Run with `--pd-decider never` at rates {5, 10, 20, 40, 60, 80, 100, 120, 150}, seeds {42, 43, 44}.

### Condition 2: Always-Disaggregate (AD) sweep across rates
Run with `--pd-decider always` at rates {5, 10, 20, 40, 60, 80, 100, 120, 150}, seeds {42, 43, 44}.

All other parameters are fixed per the research question specification.

### Probe Data (100 requests, seed 42)

| Rate | AL ITL (ms) | AD ITL (ms) | AL TTFT (ms) | AD TTFT (ms) |
|------|-------------|-------------|--------------|--------------|
| 5    | 12.49       | 12.43       | 35.63        | 45.73        |
| 20   | 13.32       | 13.08       | 36.44        | 46.34        |
| 40   | 14.19       | 13.77       | 37.46        | 46.84        |
| 60   | 14.68       | 14.21       | 37.48        | 46.96        |
| 100  | 15.06       | 14.59       | 39.29        | 46.94        |
| 120  | 15.15       | 14.69       | 40.34        | 46.93        |
| 150  | 15.25       | 14.78       | 40.40        | 46.93        |

Key observation: ITL growth **decelerates** at higher rates, unlike the paper's 1/(1−ρ) form which predicts acceleration. Likely caused by transient effects — at rate=150, the 300-request experiment runs for only 2s, while per-request processing takes ~1.6s, so steady state is never reached.

## Success Criteria

1. **Directional consistency** (h-main): ITL_AD < ITL_AL at all rates and seeds tested.
2. **TTFT tradeoff** (h-main): TTFT_AD > TTFT_AL at all rates and seeds tested.
3. **Dose-response shape** (h-dose-response): ITL is monotone increasing with rate for both AL and AD.
4. **Formula fit quality**: Report R² of the paper's α/(1−λW) model fitted to BLIS data, and characterize the residual pattern (systematic vs. random).

## Constraints

- Fixed parameters per research question: `--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded`
- Variable: `--pd-decider`, `--rate` (1–150), `--seed`
- BLIS is deterministic for a given seed (INV-6)
- PD transfer defaults: bandwidth=25.0 GB/s, base latency=0.05 ms

## Prior Knowledge

This is iteration 2. No prior findings or principles exist from iteration 1 (iter-1 produced no findings.json). This iteration functions as the initial real investigation.
