# Problem Framing — Iter-3: Quantitative ITL Formula Validation

## Research Question

Does the paper's closed-form ITL prediction `ITL = α/(1−ρ)` where `ρ = λ_eff·W` (Eq. 10 in `docs/pd-disagg.pdf`) quantitatively match BLIS's ITL under the P/D disaggregation setup, and if not, where, by how much, and why?

Previous iterations (iter-1 and iter-2) confirmed the paper's **directional** predictions: ITL_AD < ITL_AL at all rates, TTFT_AD > TTFT_AL at all rates, ITL monotone increasing with rate. Iter-3 now tests the **quantitative formula fit** — can the paper's closed-form expression actually predict ITL values from arrival rate?

Key source files implementing the mechanism:
- `sim/latency/trained_physics_model.go:154-331` — StepTime() computes iteration time from batch composition. The paper assumes `T_iter = α + B·δ` (linear in batch size); BLIS includes nonlinear terms (decode KV bandwidth scales with `sumCtx`, MoE expert count scales with batch size).
- `sim/simulator.go:772` — ITL recording: `currStepAdvance + OutputTokenProcessingTime()` where `currStepAdvance = StepTime(batch)`.
- `sim/latency/trained_physics_model.go:326` — `m.Beta[5]*batchSize` is the direct batch-size term in StepTime.
- `sim/disaggregation.go:44-58` — NeverDisaggregate (AL) and AlwaysDisaggregate (AD) routing deciders.

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags relevant to experiment:**
  - `--pd-decider {never|always}` — routing mode (AL vs AD). Defined at `cmd/root.go:1019`.
  - `--rate N` — Poisson arrival rate (req/s). Defined at `cmd/root.go` workload flags.
  - `--seed N` — deterministic RNG seed. Defined at `cmd/root.go`.
  - `--metrics-path PATH` — write cluster-aggregate JSON to file. Defined at `cmd/root.go`.
  - `--num-instances`, `--prefill-instances`, `--decode-instances` — cluster topology. Defined at `cmd/root.go:1019-1025`.
- **Code evidence:**
  - `--pd-decider` parsed at `cmd/root.go:1019` (flag registration) and `cmd/root.go:1638-1640` (config wiring).
  - `--metrics-path` writes cluster aggregate JSON with `itl_mean_ms`, `ttft_mean_ms`, `e2e_mean_ms`.
  - StepTime formula at `sim/latency/trained_physics_model.go:321-328`.
  - ITL recording at `sim/simulator.go:772`.
- **Native output:** `--metrics-path` writes JSON with all needed metrics. No shell redirects needed.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --pd-decider never --rate 10 --seed 42 --metrics-path results/baseline_al_r10_s42.json
```

## Baseline Validation

Ran the baseline command (with reduced num-requests=10 for speed). Exit code: 0. Output file produced at the specified metrics path. Key metric: `itl_mean_ms = 12.408` (10 requests at rate=5), `ttft_mean_ms = 35.396`, `e2e_mean_ms = 1611.927`. All 10 requests completed, 0 dropped.

At rate=1 (batch≈1): `itl_mean_ms = 12.261` — this is the baseline α (iteration time with 1 request in the batch).

## Experimental Conditions

All conditions share the locked parameters: `--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded`.

**Condition matrix:** 2 modes × 9 rates × 3 seeds = 54 runs total.

| Dimension | Values |
|-----------|--------|
| `--pd-decider` | `never` (AL), `always` (AD) |
| `--rate` | 5, 10, 20, 40, 60, 80, 100, 120, 150 |
| `--seed` | 42, 43, 44 |

For each run, the command is:
```bash
./blis run [locked params] --pd-decider {mode} --rate {rate} --seed {seed} --metrics-path results/{MODE}-r{rate}-s{seed}.json
```

**Analysis conditions** (post-hoc, applied to collected data):

1. **Low-rate formula calibration**: For each mode, calibrate `α` and `w` in `ITL = α/(1−rate·w)` from rates 5 and 10 (two-point fit). This is the paper's formula applied to BLIS.

2. **Full-range formula fit**: For each mode, find best-fit `α` and `w` via grid search across all 9 rates. Report R².

3. **Linear fit**: For each mode, fit `ITL = a + b·rate` via least-squares across all 9 rates. Report R².

4. **Per-rate residuals**: Compute `predicted − observed` at each rate using the low-rate-calibrated formula.

## Success Criteria

1. **h-main (formula underperforms linear):** For both AL and AD, the 1/(1-ρ) formula's best-fit R² < 0.95 AND linear fit R² > 0.95 across full rate range.
2. **h-dose-response (monotone residuals):** Low-rate-calibrated formula residuals are strictly positive and monotone increasing for rates ≥ 20.
3. **h-control-negative (formula valid at low rates):** At rates 5-20, formula mean absolute percentage error < 1% for both modes.

## Constraints

- **Fixed 300-request horizon** — cannot increase num-requests. This is the root cause of the transient regime that prevents steady-state behavior.
- **Rate range 1-150** — per research question specification.
- **3 seeds per condition** — sufficient given the very low seed variance observed in iter-2 (< 0.01ms ITL variation across seeds).
- **Active principles RP-1 through RP-4** apply — all directional findings from iter-2 should still hold.

## Prior Knowledge

- **RP-1:** AD produces strictly lower ITL than AL at all rates. (iter-2, high confidence)
- **RP-2:** AD produces strictly higher TTFT than AL at all rates. (iter-2, high confidence)
- **RP-3:** ITL is monotone increasing but decelerates at high rates due to transient effects. (iter-2, high confidence) — this is the key prior that motivates iter-3's quantitative formula test.
- **RP-4:** AD TTFT cost decreases with rate. (iter-2, medium confidence)

From iter-2 probe data, preliminary formula fit analysis shows:
- Low-rate-calibrated formula (rates 5,10) produces R²(full-range) of -1.95 (AD) and -7.84 (AL) — dramatically negative.
- Best-fit formula across all rates: R² = 0.93 (AD), 0.88 (AL).
- Simple linear fit: R² = 0.985 (AD), 0.976 (AL).
- The 1/(1-ρ) overprediction grows from <1% at rate≤20 to >50% at rate=150 (AD) and >100% (AL).
