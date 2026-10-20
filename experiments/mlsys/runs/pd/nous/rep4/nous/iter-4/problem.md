# Problem Framing — Iteration 4: Structural vs Transient Formula Mismatch

## Research Question

Does the paper's ITL formula ITL = α/(1−ρ) break down at high arrival rates in BLIS due to **finite-horizon transient effects** (ramp-up/drain phases that suppress the mean below steady-state) or due to a **structural mismatch** (BLIS's latency model produces different batch-size scaling than the formula assumes)?

Previous iterations (1–3) established that the formula fits well at low rates (MAPE < 0.1% for rates 5–20) but overpredicts dramatically at high rates (108% for AL at rate=150). A linear fit (R² > 0.975) outperforms the best-fit formula (R² < 0.95). This iteration uses per-request ITL analysis to disentangle the two candidate mechanisms.

Key source files implementing the mechanism:
- `sim/latency/trained_physics_model.go:154-331` — StepTime() computation with nonlinear batch terms (sumCtx, MoE nEff scaling)
- `sim/simulator.go:772-784` — Per-request ITL and TTFT recording
- `sim/simulator.go:715` — Scheduling delay recording
- `sim/disaggregation.go:44-58` — NeverDisaggregate / AlwaysDisaggregate routing

## System Interface

- **Build:** `go build -o blis main.go` (validated, exit 0)
- **CLI flags relevant to experiment:**
  - `--pd-decider {never|always}` — P/D mode selection (parsed at `cmd/root.go:1019-1025`)
  - `--rate <float>` — Arrival rate in req/s
  - `--seed <int>` — RNG seed for determinism
  - `--metrics-path <path>` — Native JSON output for aggregate and per-request metrics
  - `--model`, `--num-instances`, `--prefill-instances`, `--decode-instances`, `--num-requests`, `--prompt-tokens`, `--prompt-tokens-stdev`, `--output-tokens`, `--output-tokens-stdev`, `--routing-policy` — Locked parameters
- **Code evidence:**
  - `--metrics-path` produces a JSON dict with top-level aggregate fields (`itl_mean_ms`, `ttft_mean_ms`, etc.) plus a `requests` array with per-request records containing `itl_ms`, `ttft_ms`, `scheduling_delay_ms`, `arrived_at`, `handled_by` (`sim/metrics.go:95-116`)
  - Scheduling delay is recorded as `now - request.ArrivalTime` at batch formation time (`sim/simulator.go:715`)
  - TTFT recorded at prefill completion: `now + stepAdvance + OutputTokenProcessingTime() - ArrivalTime` (`sim/simulator.go:783`)

## Baseline Command

```bash
./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --pd-decider never --rate 10 --seed 42 --metrics-path results/baseline.json 2>/dev/null
```

## Baseline Validation

- **Exit code:** 0
- **Output file:** `/tmp/blis_baseline_iter4.json` (single JSON dict, cluster-level entry)
- **Key metrics:** `completed_requests=300`, `itl_mean_ms=12.801`, `ttft_mean_ms=36.584`, per-request records: 300 entries
- **Per-request fields confirmed:** `arrived_at`, `itl_ms`, `ttft_ms`, `scheduling_delay_ms`, `handled_by`, `requestID`

## Experimental Conditions

All conditions share the locked setup:
```
--model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 
--num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 
--output-tokens-stdev 0 --routing-policy least-loaded
```

### Factor grid (54 runs total):
- **P/D mode:** `--pd-decider never` (AL), `--pd-decider always` (AD)
- **Arrival rate:** `--rate` ∈ {5, 10, 20, 40, 60, 80, 100, 120, 150}
- **Seeds:** `--seed` ∈ {42, 43, 44}

### Per-run analysis (the NEW contribution of iter-4):
For each run, sort per-request records by `arrived_at` and compute:
1. **Quartile ITL means** (Q1=first 25%, Q2=25-50%, Q3=50-75%, Q4=last 25%)
2. **Q2-Q3 mean ITL** (quasi-steady-state, middle 50% of requests)
3. **ITL intra-run spread** = (max_quartile_ITL − min_quartile_ITL) / mean_ITL × 100%
4. **TTFT decomposition** = scheduling_delay_mean + (TTFT_mean − scheduling_delay_mean) for each quartile

### Analysis conditions (applied to collected data):
- **Full-run formula fit:** Best-fit α/(1−w·λ) to full-run mean ITL across 9 rates → R²_full
- **Q2-Q3 formula fit:** Best-fit α/(1−w·λ) to Q2-Q3 mean ITL across 9 rates → R²_Q2Q3
- **Linear fits:** Best-fit a + b·λ to both datasets → R²_linear_full, R²_linear_Q2Q3

## Success Criteria

1. **h-main (structural mismatch):** R²_Q2Q3(formula) < R²_full(formula) for both AL and AD modes (the formula fit WORSENS when transients are removed). The deficit R²_full − R²_Q2Q3 ≥ 0.02 for at least one mode.
2. **h-control-negative:** At rates ≤10, |Q2Q3_ITL − full_ITL| / full_ITL < 0.2% for both modes.
3. **h-dose-response:** The ITL intra-run spread shows an inverted-U shape across rates (peaks between 80–120, lower at both extremes).

## Constraints

- All parameters except `--pd-decider`, `--rate`, `--seed` are locked per the research question.
- Rate range: 1–150 req/s (using 5–150 for the grid).
- 300 requests per run (finite-horizon constraint).
- No code changes — all arms use flag-only variations + post-hoc analysis.

## Prior Knowledge

**Active principles (iter-1 through iter-3):**
- RP-1: AD produces strictly lower mean ITL than AL at all tested rates.
- RP-2: AD produces strictly higher mean TTFT than AL at all tested rates.
- RP-3: ITL is monotone increasing with rate for both modes but decelerates at high rates.
- RP-5: Formula achieves MAPE < 0.1% at low rates (5–20 req/s).
- RP-6: Linear fit R² > 0.975 outperforms formula R² < 0.95 across all rates.
- RP-7: Formula overprediction is monotone increasing with rate for rates ≥ 20.
- RP-8: w_AL > w_AD (0.00471 vs 0.00369), confirming W_tot > W_D.

**New observations from iter-4 exploration:**
- Per-request ITL follows an inverted-U within each run at high rates: rises Q1→Q2, peaks Q2-Q3, falls Q4.
- Restricting to Q2-Q3 makes the formula fit WORSE (R² drops from 0.918 to 0.874 for AL, from 0.947 to 0.924 for AD).
- The Q2-Q3 data is MORE concave than the full data, amplifying the structural mismatch.
- AD mode has constant scheduling delay (15.56ms) at all rates; TTFT growth comes entirely from prefill batching.
- AL mode scheduling delay grows with both rate (21.2→25.1ms) and request position (later arrivals wait longer).
