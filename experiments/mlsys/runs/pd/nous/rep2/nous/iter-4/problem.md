# Problem Framing — Iteration 4: Statistical Robustness and Cross-Validation of Corrected ITL Model

## Research Question

Iterations 1–3 established that a 3-parameter corrected model ITL = a + b·rate/(1+d·rate) dramatically outperforms the paper's 2-parameter α/(1−ρ) model (R²=0.997 vs 0.939 for AL; R²=0.999 vs 0.960 for AD), identified the batch-size overhead amortization mechanism (`sim/latency/trained_physics_model.go:321-328`), and confirmed that AD is E2E-superior to AL at all rates 1–150.

**Iteration 4** asks: **are these findings statistically robust and generalizable?** Specifically:
1. Do the R² values hold with 5 seeds (vs 3), and what are the 95% confidence intervals?
2. Does the corrected model generalize to held-out rates (cross-validation), or does it merely overfit the 12-point grid?
3. Is the rate=1 regime (batch size=1) a valid control-negative where disaggregation yields zero ITL benefit — confirming the batch-size amortization mechanism?

Key source files:
- `sim/latency/trained_physics_model.go:321-328` — step-time formula with fixed costs (β₃·tWeight, β₅·L, β₇) that create the amortization effect
- `sim/latency/trained_physics_model.go:72-82` — beta coefficient documentation
- `sim/disaggregation.go:44-58` — NeverDisaggregate/AlwaysDisaggregate routing
- `sim/batch_formation.go:73-280` — VLLMBatchFormation.FormBatch (token budget=2048)

## System Interface

- **Build command:** `go build -o blis main.go`
- **CLI flags for experiment:**
  - `--model qwen/qwen3-14b` — model selection (locked)
  - `--num-instances 4 --prefill-instances 2 --decode-instances 2` — cluster topology (locked)
  - `--num-requests 300` — request count (locked)
  - `--prompt-tokens 512 --prompt-tokens-stdev 0` — fixed input length (locked)
  - `--output-tokens 128 --output-tokens-stdev 0` — fixed output length (locked)
  - `--routing-policy least-loaded` — routing (locked)
  - `--pd-decider {never|always}` — AL vs AD mode (varied)
  - `--rate {1..150}` — arrival rate in req/s (varied)
  - `--seed {42..46}` — RNG seed (varied)
  - `--metrics-path <path>` — JSON output (native output mechanism)
- **Code evidence:**
  - `--pd-decider`: parsed at `cmd/root.go` via cobra, routed to `sim/disaggregation.go:44-58`
  - `--rate`: controls Poisson arrival process in `sim/workload/`
  - `--metrics-path`: writes JSON with cluster-level `itl_mean_ms`, `ttft_mean_ms`, `e2e_mean_ms` plus `requests[]` per-request detail
  - `--seed`: deterministic RNG partitioned per subsystem (`sim/rng.go`)

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded \
  --pd-decider never --rate 50 --seed 42 --metrics-path results/baseline.json
```

## Baseline Validation

Validated with seeds 42, 45, 46. All exit 0, produce valid JSON.

- **Seed 42, AL, rate=50**: itl_mean_ms=15.497, ttft_mean_ms=39.604, completed=300, dropped=0
- **Seed 45, AL, rate=50**: itl_mean_ms=15.497, ttft_mean_ms=39.673, completed=300, dropped=0
- **Seed 46, AD, rate=50**: itl_mean_ms=14.667, ttft_mean_ms=47.836, completed=300, dropped=0
- **Rate=1 identity**: AL itl=12.260953ms, AD itl=12.260953ms (difference = 0.000000ms) — confirmed for seed 45

## Experimental Conditions

**120 runs total**: 12 rates × 2 PD modes × 5 seeds

### Condition grid:
- **Rates**: [1, 5, 10, 20, 30, 50, 70, 90, 110, 130, 140, 150]
- **PD modes**: `never` (AL), `always` (AD)
- **Seeds**: [42, 43, 44, 45, 46]

### Analysis dimensions:
1. **h-main (model comparison)**: For each seed, fit paper model α/(1−λW) and corrected model a+b·rate/(1+d·rate) to the 12-rate ITL curve. Compute per-seed R², MAE, max|residual|. Report 5-seed means and 95% CI.

2. **h-robustness (cross-validation)**: For each held-out rate (12 iterations), fit both models on the other 11 rates, predict the held-out rate. Report cross-validated MAE for both models.

3. **h-control-negative (mechanism validation)**: Extract ITL at rate=1 for all 5 seeds × 2 modes. Verify AL_ITL(rate=1) = AD_ITL(rate=1) = 12.261ms exactly.

## Success Criteria

1. **h-main**: Corrected model 5-seed mean R² > 0.995 for both AL and AD. Paper model < 0.960. The 95% CI for the R² difference (corrected − paper) has lower bound > 0 (statistically significant).
2. **h-robustness**: Corrected model cross-validated MAE < 0.3ms for both modes. Paper model cross-validated MAE > 0.5ms.
3. **h-control-negative**: ITL difference (AL − AD) at rate=1 is exactly 0.000ms for all 5 seeds.

## Constraints

- Locked parameters: all parameters except `--pd-decider`, `--rate`, and `--seed` are fixed per campaign.
- Rate range: 1–150 req/s (campaign constraint).
- Analysis requires scipy/numpy: use `/opt/anaconda3/bin/python3` (NOT system python3, which lacks scipy).
- Always use `--metrics-path` for clean JSON output (AD mode appends PD Metrics text to stdout).

## Prior Knowledge

- **RP-1 (high)**: AD yields lower ITL than AL at rates ≥ 5, with zero difference at rate=1.
- **RP-2 (high)**: AD incurs higher TTFT (4.6–15.7ms penalty).
- **RP-3 (high)**: Corrected model R²=0.997 (AL), 0.999 (AD) over 3 seeds.
- **RP-4 (high)**: Corrected model MAE is 4.4–5.0× smaller than paper model.
- **RP-5 (high)**: AD TTFT growth is only 28% of AL's.
- **RP-6 (high)**: AD is E2E-superior at all rates despite TTFT penalty.

All six principles were established with 3 seeds. This iteration extends to 5 seeds for robustness and adds cross-validation to test generalization.

**Paper model residual structure** (from iter-3 data):
- AL: overshoots by 0.3–0.8ms at rates 1–20, crosses zero at rate≈30, undershoots by 0.6–1.1ms at rates 50–110, crosses zero again at rate≈132, overshoots at 140–150.
- AD: similar S-shaped pattern with smaller magnitudes.
- The S-shape arises because α/(1−ρ) is globally convex while the true curve is concave — no choice of (α, W) can simultaneously fit the low-rate and high-rate regions.
