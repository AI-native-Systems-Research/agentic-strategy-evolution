# Problem Framing — Iteration 1: P/D Disaggregation Latency Model Validation

## Research Question

Does the paper's ("When to Disaggregate") closed-form ITL and TTFT predictions for always-local (AL) and always-disaggregate (AD) modes hold inside BLIS's discrete-event simulator, over what range of arrival rates (1–150 req/s), and where and why do they break down?

The paper (Section 2.5, Eq. 10) predicts iteration time T_iter = α/(1−ρ), where ρ = λ·W_tot is the utilization. Section 3.4 (Eq. 17) gives ITL = T_iter^D + β + γ(l + (o+1)/2), which depends on the decode server's iteration time. The critical prediction is:

- **Under AL** (d=0): ρ_D = λ·W_tot (prefill + decode work on same server), yielding higher ITL.
- **Under AD** (d=1): ρ_D = λ·W_D (only decode work on decode server, W_D < W_tot), yielding lower ITL.
- **TTFT tradeoff** (Eq. 18 vs 19): TTFT_disagg > TTFT_local due to the prefill pipeline overhead (Q_P + T_iter^P + c).

Key source files:
- `sim/disaggregation.go:44-58` — NeverDisaggregate (AL) and AlwaysDisaggregate (AD) deciders
- `sim/cluster/pd_events.go:90-283` — KV transfer events implementing the disaggregation pipeline
- `sim/cluster/cluster.go:1690-1705` — TTFT rewrite for disaggregated requests: `newTTFT = prefillTTFT + transferDuration + firstDecodeStep`
- `sim/cluster/cluster.go:745` — Detection of prefill/decode sub-request completions

## System Interface

- **Build command:** `go build -o blis main.go`
- **Run command:** `./blis run` with flags below.

### CLI flags relevant to the experiment

| Flag | Semantics | Code evidence |
|------|-----------|---------------|
| `--pd-decider` | Disaggregation decider: `never` (AL), `always` (AD), `prefix-threshold` | `cmd/root.go:1022`, `sim/disaggregation.go:65-82` |
| `--prefill-instances` | Dedicated prefill pool size | `cmd/root.go:1019` |
| `--decode-instances` | Dedicated decode pool size | `cmd/root.go:1020` |
| `--num-instances` | Total cluster instances | `cmd/root.go:1019` area |
| `--rate` | Poisson arrival rate (req/s) | `cmd/root.go` (workload gen) |
| `--seed` | RNG seed for determinism (INV-6) | `cmd/root.go` |
| `--routing-policy` | Routing policy (`least-loaded`) | `cmd/root.go` |
| `--metrics-path` | Write MetricsOutput JSON (aggregate + per-request) | `cmd/root.go:2078` |
| `--num-requests` | Number of requests to generate | `cmd/root.go` |
| `--prompt-tokens` / `--prompt-tokens-stdev` | Input token distribution | `cmd/root.go` |
| `--output-tokens` / `--output-tokens-stdev` | Output token distribution | `cmd/root.go` |

### Native output mechanism

`--metrics-path <file>` writes a JSON file containing:
- Aggregate metrics: `itl_mean_ms`, `ttft_mean_ms`, `e2e_mean_ms`, etc.
- Per-request array `requests[]` with: `ttft_ms`, `itl_ms`, `e2e_ms`, `scheduling_delay_ms`, `handled_by`, `requestID`

Stdout also emits per-instance and cluster-level metrics blocks.

## Baseline Command

```bash
./blis run \
  --model qwen/qwen3-14b \
  --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 \
  --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 \
  --routing-policy least-loaded \
  --pd-decider never \
  --rate 10 --seed 42 \
  --metrics-path results/baseline.json
```

## Baseline Validation

Ran the baseline command. Observed:
- **Exit code:** 0
- **Output:** MetricsOutput JSON with 300 completed requests, 0 dropped/queued/preempted
- **Key metric values (cluster-level):** `itl_mean_ms=12.80`, `ttft_mean_ms=36.58`, `e2e_mean_ms=1663.06`
- **Per-request data:** Each request has `ttft_ms`, `itl_ms`, `e2e_ms` — suitable for curve fitting

Also validated AD baseline (`--pd-decider always`): `itl_mean_ms=12.67`, `ttft_mean_ms=45.98`, `e2e_mean_ms=1616.92`, plus "PD Metrics" section with `Disaggregated Requests: 300`.

## Experimental Conditions

### Fixed parameters (from research question, must not change)
- `--model qwen/qwen3-14b`
- `--num-instances 4 --prefill-instances 2 --decode-instances 2`
- `--num-requests 300`
- `--prompt-tokens 512 --prompt-tokens-stdev 0`
- `--output-tokens 128 --output-tokens-stdev 0`
- `--routing-policy least-loaded`

### Variable parameters
- `--pd-decider`: `never` (AL) or `always` (AD)
- `--rate`: [5, 10, 20, 40, 60, 80, 100, 130] req/s
- `--seed`: [42, 43, 44]

### Condition matrix
Total runs: 8 rates × 2 modes × 3 seeds = **48 runs**

Each run produces a `--metrics-path` JSON file with per-request latency data.

### Conditions detail

**Condition A — Always-Local (AL, control):**
```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 \
  --routing-policy least-loaded --pd-decider never \
  --rate {RATE} --seed {SEED} --metrics-path {OUTPUT_PATH}
```

**Condition B — Always-Disaggregate (AD, treatment):**
```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 \
  --routing-policy least-loaded --pd-decider always \
  --rate {RATE} --seed {SEED} --metrics-path {OUTPUT_PATH}
```

## Success Criteria

1. **ITL ordering (h-main):** At each tested rate, mean ITL under AD is lower than mean ITL under AL, consistently across all 3 seeds.
2. **TTFT ordering (h-main):** At each tested rate, mean TTFT under AD is higher than mean TTFT under AL, consistently across all 3 seeds.
3. **ITL gap growth:** The absolute ITL gap (ITL_AL − ITL_AD) increases monotonically with arrival rate.
4. **ITL formula fit:** The ITL vs. rate relationship for each mode fits the form ITL = a/(1 − b·rate) + c with R² > 0.95, where b captures the per-request work term W.
5. **Low-load control:** At rate=5 req/s, the ITL gap is less than 0.5 ms, confirming the effect is load-dependent.

## Constraints

- All parameters except `--pd-decider`, `--rate`, and `--seed` are locked by the research question.
- No code changes — this is a pure flag-variation experiment.
- BLIS is deterministic (INV-6): same seed → byte-identical output. Multiple seeds provide independent trials.
- Each run is CPU-only and fast (< 5 seconds per run at tested rates).

## Prior Knowledge

This is iteration 1 — no prior principles. The paper's closed-form model (Eq. 10, 17, 18, 19) serves as the external theory grounding. The key theoretical prediction is that ITL depends on decode utilization ρ_D via T_iter = α/(1−ρ_D), and AD reduces ρ_D from λW_tot to λW_D by offloading prefill work.

## Probe Summary (from exploration)

| Rate | AL ITL (ms) | AD ITL (ms) | Δ ITL | AL TTFT (ms) | AD TTFT (ms) | Δ TTFT |
|------|-------------|-------------|-------|--------------|--------------|--------|
| 5    | 12.49       | 12.43       | 0.06  | 35.74        | 45.74        | −10.0  |
| 10   | 12.80       | 12.67       | 0.13  | 36.58        | 45.98        | −9.4   |
| 30   | 14.10       | 13.65       | 0.45  | 37.91        | 46.93        | −9.0   |
| 50   | 15.50       | 14.67       | 0.83  | 39.60        | 47.83        | −8.2   |
| 80   | 17.44       | 16.10       | 1.34  | 43.18        | 48.96        | −5.8   |
| 100  | 18.44       | 16.88       | 1.56  | 43.51        | 49.45        | −5.9   |
| 130  | 19.45       | 17.77       | 1.68  | 45.82        | 49.82        | −4.0   |
| 150  | 19.89       | 18.20       | 1.69  | 45.47        | 49.86        | −4.4   |

All probes show: AD ITL < AL ITL (gap grows with rate), AD TTFT > AL TTFT (gap narrows with rate), 0 preemptions, 0 drops, 300/300 completed at all rates up to 150.
