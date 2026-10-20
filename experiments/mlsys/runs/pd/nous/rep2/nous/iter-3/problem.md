# Problem Framing — Iteration 3

## Research Question

Do the paper's ITL and TTFT predictions for always-local (AL) vs always-disaggregate (AD) P/D serving hold inside BLIS, and if not, does a physics-corrected model accounting for batch-size-dependent overhead amortization provide a better fit?

**Background from iters 1-2:** The paper's alpha/(1-rho) ITL model fits with R²=0.94 (AL) / 0.96 (AD) over rates 1-150 req/s. A saturating model (Michaelis-Menten) fits better with R²=0.997 (AL) / 0.998 (AD). The mechanism is batch-size-dependent overhead amortization: fixed per-step costs (weight loading, per-layer overhead, per-step constant) in `sim/latency/trained_physics_model.go:321-328` are shared across all tokens in a batch, so per-token ITL = F/B + c where F is fixed overhead and B is batch size.

**This iteration:** Runs the full experiment at scale (12 rates × 2 modes × 3 seeds = 72 runs), fitting four competing models to the ITL data:
1. Paper's alpha/(1-rho)
2. Linear
3. Physics-corrected saturating: ITL = a + b*rate/(1+d*rate)
4. Full physics: (amortization + queueing) ITL = (F/(1+k*rate) + c)/(1-W*rate)

Additionally characterizes TTFT dose-response and the ITL-TTFT tradeoff between AL and AD.

**Key source files:**
- `sim/latency/trained_physics_model.go:321-328` — Step-time formula with fixed overhead terms
- `sim/latency/trained_physics_model.go:72-82` — Beta coefficient documentation
- `defaults.yaml` (trained_physics_coefficients) — Actual coefficient values: beta_5=32.1µs/layer, beta_6=4.4µs/req, beta_7=126.0µs/step
- `sim/cluster/cluster.go:1690-1716` — PD TTFT computation (prefillTTFT + transfer + firstDecodeStep)
- `sim/simulator.go:587-644` — E2E and per-request ITL computation

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags:**
  - `--pd-decider {never|always}` — routing mode (AL vs AD). Defined at `cmd/root.go:960-1025`, parsed at `sim/disaggregation.go:44-58`.
  - `--rate N` — arrival rate in req/s. Poisson process.
  - `--seed N` — RNG seed for deterministic reproducibility (INV-6).
  - `--metrics-path PATH` — writes cluster-level + per-request JSON metrics to file. Native output mechanism.
  - `--model`, `--num-instances`, `--prefill-instances`, `--decode-instances`, `--num-requests`, `--prompt-tokens`, `--prompt-tokens-stdev`, `--output-tokens`, `--output-tokens-stdev`, `--routing-policy` — all locked parameters.
- **Output format:** JSON file via `--metrics-path` containing cluster-level `itl_mean_ms`, `ttft_mean_ms`, `e2e_mean_ms` and per-request `requests[]` array with `itl_ms`, `ttft_ms`, `e2e_ms` per request.
- **Code evidence:**
  - `--pd-decider`: `cmd/root.go:1000` (flag definition), `sim/cluster/cluster.go:394-398` (wiring)
  - `--rate`: `cmd/root.go:962` (flag definition)
  - `--seed`: `cmd/root.go:964` (flag definition)
  - `--metrics-path`: `cmd/root.go:970` (flag definition)

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded \
  --pd-decider never --rate 50 --seed 42 \
  --metrics-path /path/to/results/baseline.json
```

## Baseline Validation

**Validated:** Exit 0. Metrics file produced at specified path. Key metric values from `--metrics-path`:
- AL rate=50 seed=42: `itl_mean_ms=15.498`, `ttft_mean_ms=39.604`, `e2e_mean_ms=2008.578`. 300 completed, 0 dropped.
- AD rate=50 seed=42: `itl_mean_ms=14.668`, `ttft_mean_ms=47.833`, `e2e_mean_ms=1869.248`. 300 completed, 0 dropped.
- System stable at all rates 1-150 (0 drops, 0 preemptions confirmed at rate=150 for both modes).

## Experimental Conditions

### h-main: Corrected ITL model vs paper model

**Configuration-only experiment.** For each of 12 rate points × 2 modes × 3 seeds = 72 runs:

```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded \
  --pd-decider {never|always} --rate {RATE} --seed {SEED} \
  --metrics-path {OUTPUT_PATH}
```

Rate points: 1, 5, 10, 20, 30, 50, 70, 90, 110, 130, 140, 150
Seeds: 42, 43, 44
Modes: never (AL), always (AD)

**Analysis:** For each mode, aggregate ITL means across seeds at each rate, then fit four models:
1. Paper: ITL = alpha / (1 - W*rate) [2 params]
2. Linear: ITL = a + b*rate [2 params]
3. Corrected (saturating): ITL = a + b*rate/(1+d*rate) [3 params]
4. Full physics: ITL = (F/(1+k*rate) + c) / (1-W*rate) [4 params]

Compare R² values. Report per-rate residuals for paper model.

### h-dose-response: TTFT shape characterization

Same 72 runs as h-main (shared data). Extract `ttft_mean_ms` from each run. Compute per-rate marginals. Classify shape as saturating, accelerating, or linear.

**From probes:**
- AL TTFT: 29.9ms (rate=1) → 45.5ms (rate=150), growth = 15.6ms
- AD TTFT: 45.6ms (rate=1) → 49.9ms (rate=150), growth = 4.3ms
- AL marginals: mixed (5 inc, 5 dec) — approximately saturating
- AD marginals: clearly saturating (2 inc, 8 dec)

### h-tradeoff: ITL-TTFT tradeoff

Same 72 runs (shared data). Compute for each rate:
- ITL_benefit = AL_itl - AD_itl (positive = AD wins)
- TTFT_penalty = AD_ttft - AL_ttft (positive = AD loses)
- E2E_benefit = AL_e2e - AD_e2e (positive = AD wins)

**From probes:** AD has lower E2E than AL at ALL tested rates (28.9ms benefit at rate=1, growing to 254.8ms at rate=150). The TTFT penalty (15.7ms→4.4ms) shrinks with rate while ITL benefit (0→1.7ms) grows.

## Success Criteria

1. **h-main:** Corrected model R² exceeds paper model R² for both AL and AD, consistently across seeds. Max residual of corrected model is smaller than paper model's at every rate point.
2. **h-dose-response:** TTFT marginals for AD are monotonically decreasing above rate ~30, confirming saturating shape. AL TTFT shape is less cleanly saturating due to prefill-decode contention.
3. **h-tradeoff:** E2E benefit of AD over AL is positive at all rates and grows monotonically with rate, confirming that ITL benefit dominates TTFT penalty across the full range.

## Constraints

- Rates must stay within 1-150 req/s (campaign constraint).
- All other parameters are locked per the campaign specification.
- 300 requests per run (may take up to 300s simulated time at rate=1).
- Seeds must be deterministic (INV-6).

## Prior Knowledge

- **RP-1:** AD yields consistently lower ITL than AL (confirmed iter-1, iter-2).
- **RP-2:** AD incurs consistently higher TTFT than AL with ~4-9ms penalty (confirmed iter-1).
- **RP-3:** ITL follows concave, monotonically increasing function of rate with R²=0.94/0.96 for paper model (confirmed iter-1, iter-2). Iter-2 showed saturating model (R²=0.997/0.998) is superior.
