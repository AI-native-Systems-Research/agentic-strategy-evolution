# Problem Framing: P/D Disaggregation Latency Model in BLIS

## Research Question

Does the paper's ("When to Disaggregate", `docs/pd-disagg.pdf`) closed-form model for ITL and TTFT under always-local (AL) and always-disaggregate (AD) policies hold inside BLIS? Specifically:

1. Does AD yield lower mean ITL than AL across arrival rates 10–130 req/s, as the paper's utilization-based model predicts (lower decode utilization ρ_D in AD)?
2. Does AD yield higher mean TTFT than AL due to the prefill pipeline overhead (prefill server queueing + KV transfer)?
3. Does the ITL follow the paper's form `T_iter = α/(1-ρ)` where `ρ = λ·δ` is the per-instance decode utilization?

**Key source files:**
- `sim/disaggregation.go:44-58` — AlwaysDisaggregate / NeverDisaggregate deciders
- `sim/latency/trained_physics_model.go:154-330` — StepTime computation (roofline-based with learned corrections)
- `sim/batch_formation.go:73-280` — VLLMBatchFormation.FormBatch (chunked prefill + decode budget)
- `sim/cluster/cluster.go:394-398` — PDDecider wiring in cluster setup
- `sim/cluster/deployment.go:70-82` — PD deployment config (transfer bandwidth, base latency)

## System Interface

### Build Command
```bash
go build -o blis main.go
```

### CLI Flags Relevant to Experiment

| Flag | Default | Semantics | Code evidence |
|------|---------|-----------|---------------|
| `--pd-decider` | `never` | Disaggregation decider: never (AL), always (AD) | `cmd/root.go:1022` |
| `--prefill-instances` | 0 | Number of dedicated prefill instances | `cmd/root.go:1008` |
| `--decode-instances` | 0 | Number of dedicated decode instances | `cmd/root.go:1009` |
| `--num-instances` | 1 | Total instances (prefill + decode + shared) | `cmd/root.go:961` |
| `--rate` | 10 | Request arrival rate (Poisson, req/s) | `cmd/root.go:962` |
| `--seed` | 42 | Random seed for deterministic runs | `cmd/root.go:960` |
| `--routing-policy` | `round-robin` | Cluster routing policy | `cmd/root.go:968` |
| `--metrics-path` | (none) | File to write MetricsOutput JSON (aggregate + per-request) | `cmd/root.go:2078` |
| `--pd-transfer-bandwidth` | 25.0 | KV transfer bandwidth in GB/s | `cmd/root.go:1023` |
| `--pd-transfer-base-latency` | 0.05 | KV transfer base latency in ms | `cmd/root.go:1024` |
| `--max-num-scheduled-tokens` | 2048 | Token budget M per step | `cmd/root.go:965` |
| `--max-num-running-reqs` | 256 | Max batch size | `cmd/root.go:964` |

### Output Format
- **stdout**: Per-instance JSON metrics blocks separated by `=== Simulation Metrics ===` headers. AD mode also appends `=== PD Metrics ===` with transfer stats.
- **`--metrics-path <path>`**: Writes structured JSON containing both aggregate cluster metrics and per-request detail (`requests[]` array with `ttft_ms`, `itl_ms`, `e2e_ms` per request). This is the preferred output mechanism for automated collection.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded \
  --pd-decider never --rate 50 --seed 42 \
  --metrics-path results/baseline.json
```

## Baseline Validation

Ran the baseline (AL, rate=50, seed=42):
- **Exit code:** 0
- **Output:** `--metrics-path` writes JSON with aggregate + per-request data
- **Key metrics (cluster):**
  - `itl_mean_ms`: 15.498
  - `ttft_mean_ms`: 39.604
  - `e2e_mean_ms`: 2008.578
  - `completed_requests`: 300 (all completed, no drops)
  - `preemption_count`: 0

Ran the AD condition (rate=50, seed=42):
- `itl_mean_ms`: 14.668 (lower than AL ✓)
- `ttft_mean_ms`: 47.833 (higher than AL ✓)
- `e2e_mean_ms`: 1869.248

## Experimental Conditions

### Fixed Parameters (all conditions)
```
--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2
--num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0
--output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded
```

### Varied Parameters
- **`--pd-decider`**: `never` (AL) vs `always` (AD)
- **`--rate`**: 10, 30, 50, 70, 90, 110, 130 req/s
- **`--seed`**: 42, 43, 44

### Conditions (42 total = 7 rates × 2 modes × 3 seeds)
For each (rate, pd-decider, seed) triple:
```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded \
  --pd-decider {never|always} --rate {RATE} --seed {SEED} \
  --metrics-path results/h-main/{pd-decider}_r{RATE}_s{SEED}.json
```

## Success Criteria

1. **ITL direction (primary)**: AD mean ITL < AL mean ITL at every tested rate, consistently across all 3 seeds.
2. **TTFT direction**: AD mean TTFT > AL mean TTFT at every tested rate, consistently across all 3 seeds.
3. **Formula fit**: The relationship `ITL = α/(1-ρ) + C₀` fits the rate-sweep data with R² > 0.95 for both AL and AD modes when ρ is proportional to rate.
4. **Breakdown characterization**: If the formula diverges at high rates, identify the rate threshold and the mechanism (e.g., preemption onset, token budget saturation, queueing blowup).

## Constraints

- **Fixed setup** (from campaign research question): `--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded`
- **Rate range**: 1 to 150 req/s (campaign constraint); we test 10–130 for a well-spaced sweep.
- **Allowed knobs**: Only `--pd-decider`, `--rate`, `--seed` may vary.
- **Resource**: Each run completes in ~1-3 seconds (CPU-only simulator); total experiment ~2 minutes.

## Prior Knowledge

This is iteration 1. No active principles from prior iterations.

**Paper predictions** (from `docs/pd-disagg.pdf`):
- Equation (17): ITL = T_iter^D + β + γ(l + (o+1)/2), where T_iter^D = α/(1-ρ_D)
- For AL: ρ_D = λ·W_tot (decode instances handle full work)
- For AD: ρ_D = λ·W_D (decode instances only handle decode work, W_D < W_tot)
- Equation (18-20): TTFT_local < TTFT_disagg due to prefill pipeline overhead
- Section 3.5 table: Disaggregation reduces ρ_D (protecting ITL) at the cost of higher TTFT

**Probe observations**:
- AL rate sweep ITL: 12.80 (rate=10) → 19.45 (rate=130) — monotone increasing, sub-linear
- AD rate sweep ITL: 12.67 (rate=10) → 17.77 (rate=130) — same pattern, consistently lower
- AD-AL ITL gap widens with rate: 0.13ms at rate=10, 1.68ms at rate=130
- Seed variation is minimal (ITL varies < 0.01ms across seeds) due to zero token stdev
- In AL mode, only decode instances (2 of 4) process requests; prefill instances idle
- In AD mode, all 4 instances active (2 prefill, 2 decode)
