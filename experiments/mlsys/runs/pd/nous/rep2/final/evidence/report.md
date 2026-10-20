# P/D Disaggregation Latency Model in BLIS: Research Report

## Answer

The paper's ITL formula ITL = α/(1 − λW) holds in BLIS with R² = 0.94 (AL) and R² = 0.96 (AD) over arrival rates 10–130 req/s, confirming the model's predictive validity in the moderate-load regime (ρ < 0.36). Always-disaggregate (AD) consistently yields **lower ITL** than always-local (AL) — by 0.13 ms at 10 req/s growing to 1.68 ms at 130 req/s — while paying a **higher TTFT** penalty of 4.2–9.4 ms due to KV transfer overhead (~3.4 ms) plus prefill-server queueing.

---

## Evidence

### Iteration 1 (confirmed; `analysis_summary.json`)

`/runs/iter-1/results/analysis_summary.json` contains the primary quantitative evidence. Key numbers extracted:

**ITL formula fit (α/(1 − λW) form, fitted via nonlinear least-squares):**

| Mode | α (ms) | b (utilization/req/s) | R² |
|------|--------|----------------------|----|
| AL   | ~5.2   | 0.0027               | 0.94 |
| AD   | ~4.8   | 0.0023               | 0.96 |

- The b-parameter ratio (AL/AD ≈ 1.174) reflects that AD decode instances carry ~14.8% less utilization per unit rate because prefill work is offloaded to dedicated prefill instances.
- At all tested rates the model fits without systematic bias in the moderate-load regime; residuals become larger at rates above ~110 req/s as ρ approaches 0.36, but the formula does not break down.

**ITL comparison (AD vs. AL), selected rates:**

| Rate (req/s) | ITL_AL (ms) | ITL_AD (ms) | Δ ITL (ms) |
|--------------|-------------|-------------|------------|
| 10           | ~5.3        | ~5.2        | −0.13      |
| 50           | ~5.8        | ~5.5        | −0.30      |
| 100          | ~6.9        | ~6.1        | −0.80      |
| 130          | ~8.1        | ~6.4        | −1.68      |

AD ITL advantage grows monotonically with load, consistent with the 1/(1−ρ) amplification mechanism.

**TTFT comparison (AD vs. AL), selected rates:**

| Rate (req/s) | TTFT_AL (ms) | TTFT_AD (ms) | ΔTTFT (ms) |
|--------------|--------------|--------------|------------|
| 10           | ~42          | ~51          | +9.4       |
| 50           | ~55          | ~63          | +8.0       |
| 100          | ~89          | ~94          | +5.1       |
| 130          | ~118         | ~122         | +4.2       |

AD always incurs higher TTFT; the penalty narrows at high rates because AL TTFT rises faster with congestion.

### Iterations 2–4 (failed schema validation; partial data)

- **Iteration 2** (`analysis.json`): Contained raw run data but used disallowed fields in `findings.json`; the underlying simulation outputs are consistent with iter-1 trends (no contradictions found in the raw metrics).
- **Iteration 3** (`analysis_summary.json`, `smoke_test.json`): Schema failure on findings; `smoke_test.json` confirms the simulator runs correctly and ITL values at rate=10 match iter-1 baseline (~5.2 ms AL, ~5.1 ms AD).
- **Iteration 4**: Zero result files produced before schema failure; no data to extract.
- No dispatcher-level retries were recorded; failures were strictly schema/format issues in the findings artifact, not simulation failures.

---

## Principles Discovered

### RP-1 — AD yields lower ITL than AL, growing with load
**Confidence: High**  
AD ITL < AL ITL across all rates 10–130 req/s, with advantage +0.13 ms → +1.68 ms. Mechanism: dedicated prefill instances reduce decode-instance utilization ρ_D relative to AL, lowering per-step time via the T_iter = α/(1−ρ) model. Confirmed by b-parameter fit (ratio 1.174).  
*Regime:* qwen3-14b, 4 instances (2P+2D), 300 requests, 512/128 token counts, least-loaded routing.

### RP-2 — AD incurs higher TTFT than AL due to KV transfer
**Confidence: High**  
AD TTFT > AL TTFT by 4.2–9.4 ms at all tested rates. The base penalty (~3.4 ms) arises from KV cache transfer at 25 GB/s; additional prefill-server queueing adds further delay. Penalty narrows at high loads as AL congestion grows faster.  
*Regime:* Default pd-transfer-bandwidth = 25 GB/s; penalty scales inversely with bandwidth.

### RP-3 — ITL follows the paper's α/(1−λW) formula; R² > 0.94 over rates 10–130
**Confidence: Medium**  
Both AL and AD ITL fit the closed-form model with R² ≥ 0.94. The formula does not break down in the moderate-load regime (ρ < 0.36). Fit quality is expected to improve at higher loads where the 1/(1−ρ) nonlinearity is sharper, but those rates were not reached in this study.  
*Applicability bounds:* Tested only at ρ < 0.36; extrapolation to near-saturation (ρ > 0.8) untested.

---

## Limitations & Open Questions

### Scientific Gaps

1. **Near-saturation regime untested.** The maximum rate tested (130 req/s, ρ ≈ 0.36) is well below saturation. The paper's model is most distinctive near ρ → 1; whether BLIS reproduces the sharp upturn (and whether AL or AD saturates first) remains unverified.

2. **TTFT model accuracy not quantified.** While the paper also provides a closed-form TTFT prediction, this study only compared AL vs. AD empirically; no fit of the TTFT formula was performed.

3. **Token-count variability unexplored.** All runs used `--prompt-tokens-stdev 0 --output-tokens-stdev 0`. The paper's model assumes heterogeneous requests; BLIS behavior under high variance is unknown.

4. **Prefill-instance utilization not directly measured.** The conclusion that AD reduces ρ_D by offloading prefill is inferred from the b-parameter ratio; direct measurement of per-instance step-time distributions would strengthen this.

5. **Only "never" vs. "always" routing tested.** The paper proposes a hybrid threshold policy; its validity in BLIS was not investigated.

### Infrastructure Gaps

- Iterations 2–4 failed exclusively due to `findings.json` schema violations (extra keys), not simulation failures. The underlying simulation data in iterations 2–3 is intact and consistent with iter-1. Future campaigns should enforce schema compliance in the findings writer before submission.