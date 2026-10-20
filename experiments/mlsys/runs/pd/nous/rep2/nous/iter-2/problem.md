# Problem Framing — Iteration 2: ITL-Rate Curve Shape and Model Breakdown

## Research Question

Iteration 1 confirmed the paper's directional predictions (AD yields lower ITL, higher TTFT than AL) and showed the alpha/(1-rho) model fits with R^2=0.94 (AL) and R^2=0.96 (AD) over rates 10-130 req/s. However, the analysis also revealed that a simple linear model fits *better* (R^2=0.985/0.991) and a quadratic model with negative leading coefficient fits best (R^2=0.999), suggesting the ITL-rate relationship is concave (decelerating) rather than convex (accelerating) as the alpha/(1-rho) formula predicts.

**Iteration 2 asks:** Over the extended range 1-150 req/s, does the ITL-rate curve follow the convex alpha/(1-rho) shape predicted by the paper, or a concave saturating shape? If concave, what mechanism in BLIS's step-time model causes the deviation?

The mechanism under investigation is **batch-size-dependent overhead amortization** in the trained-physics latency model (`sim/latency/trained_physics_model.go:321-328`). The step-time formula includes fixed per-step costs (weight loading beta_3*tWeight, per-layer overhead beta_5*L, per-step constant beta_7) that are amortized over all tokens in the batch. As arrival rate increases, batch sizes grow, reducing the per-token share of these fixed costs. This produces a concave ITL-rate curve (saturating toward a per-token floor), contradicting the paper's convex prediction.

## System Interface

- **Build command:** `go build -o blis main.go` (validated, exit 0)
- **CLI flags relevant to experiment:**
  - `--pd-decider {never,always}` — selects AL vs AD mode. Defined at `cmd/root.go:960-1025`, implemented at `sim/disaggregation.go:44-58`.
  - `--rate N` — Poisson arrival rate in req/s. Parsed at `cmd/root.go`.
  - `--seed N` — RNG seed for deterministic runs.
  - `--metrics-path PATH` — writes structured JSON output with per-request detail array. Defined at `cmd/root.go`.
  - `--model NAME` — model identifier. `qwen/qwen3-14b` uses trained-physics latency model.
  - `--num-instances`, `--prefill-instances`, `--decode-instances` — cluster topology.
  - `--num-requests`, `--prompt-tokens`, `--prompt-tokens-stdev`, `--output-tokens`, `--output-tokens-stdev` — workload parameters.
  - `--routing-policy` — request routing policy.
- **Code evidence:**
  - Step-time formula: `sim/latency/trained_physics_model.go:321-328` — `stepTime = prefillTerm + decodeTerm + beta_3*tWeight + beta_4*tTp + beta_5*L + beta_6*batchSize + beta_7`
  - Fixed per-step costs: `tWeight` at line 261 (model weight loading, constant per step), `beta_5*L` at line 325 (per-layer overhead), `beta_7` at line 327 (per-step constant).
  - Batch formation: `sim/batch_formation.go:73-280` — determines how many requests enter each step's batch.
  - Disaggregation: `sim/disaggregation.go:44-58` — NeverDisaggregate vs AlwaysDisaggregate.
- **Output mechanism:** `--metrics-path` writes JSON with `itl_mean_ms`, `ttft_mean_ms`, `completed_requests`, and `requests[]` per-request array.

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 \
  --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 \
  --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded \
  --pd-decider never --rate 50 --seed 42 --metrics-path results/baseline.json
```

## Baseline Validation

Ran the baseline command above. Exit code 0. Output file produced at the specified path.
Key metric: `itl_mean_ms=15.498`, `ttft_mean_ms=39.604`, `completed_requests=300`, `dropped_unservable=0`.

Additional probes to validate the rate range:
- AL rate=1: itl_mean=12.261ms (near-zero load, baseline alpha)
- AL rate=5: itl_mean=12.491ms
- AL rate=140: itl_mean=19.686ms, completed=300, dropped=0
- AL rate=150: itl_mean=19.889ms, completed=300, dropped=0
- AD rate=140: itl_mean=18.002ms, completed=300, dropped=0
- AD rate=150: itl_mean=18.204ms, completed=300, dropped=0

System remains stable (zero drops, zero preemptions) across the full 1-150 req/s range.

## Experimental Conditions

### h-main: Model comparison (linear vs alpha/(1-rho))

For each of AL and AD, run 12 rate points [1, 5, 10, 20, 30, 50, 70, 90, 110, 130, 140, 150] × 3 seeds [42, 43, 44]. Fit three models to the ITL-vs-rate data:
1. Paper's alpha/(1-rho): ITL = alpha / (1 - W*rate) — 2 free parameters
2. Linear: ITL = a + b*rate — 2 free parameters
3. Saturating (reciprocal): ITL = c - d/rate — 2 free parameters (approaches ceiling c as rate → infinity)

Compare R^2 values. Examine residual patterns.

Commands differ only in `--pd-decider` (never/always), `--rate`, `--seed`, and `--metrics-path`.

### h-dose-response: ITL shape characterization

Same runs as h-main (shared data). Test whether ITL vs rate follows a `saturating` shape — monotonically increasing with diminishing returns (concave). 12 rate points for both AL and AD. The prediction is that the marginal ITL increase per unit rate decreases monotonically for rates above ~20 req/s.

## Success Criteria

1. **h-main CONFIRMED if:** Over the full 1-150 req/s range, the linear model achieves higher R^2 than alpha/(1-rho) for both AL and AD. The residual pattern of alpha/(1-rho) is systematic (not random).
2. **h-dose-response CONFIRMED if:** The ITL-rate curve is monotonically increasing and the marginal increment (delta ITL per delta rate) decreases consistently for rate > 20 req/s — i.e., the curve is concave/saturating.

## Constraints

- All runs use the locked parameter set from the campaign: `--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded`.
- Rate range: 1-150 req/s (campaign allows 1-150).
- Seeds: 42, 43, 44 (consistent with iter-1).
- Total runs: 12 rates × 2 modes × 3 seeds = 72 runs.

## Prior Knowledge

- **RP-1** (high confidence): AD yields lower ITL than AL. Directional prediction confirmed in iter-1 — not re-tested here, but should hold as an invariant across all runs.
- **RP-2** (high confidence): AD incurs higher TTFT than AL. Same — expected to hold as an invariant.
- **RP-3** (medium confidence): Both AL and AD ITL follow a concave, monotonically increasing function with R^2=0.94/0.96 for alpha/(1-rho). **This iteration directly tests whether the alpha/(1-rho) formula is the correct functional form, or merely an adequate approximation in the moderate-load regime.**
- From iter-1 analysis: Linear fit R^2=0.985/0.991, quadratic (c<0) fit R^2=0.999 over 10-130 req/s. This strongly suggests concavity.
- Probe data from exploration: ITL increment per unit rate peaks around 30-50 req/s then monotonically decreases, confirming decelerating growth.
