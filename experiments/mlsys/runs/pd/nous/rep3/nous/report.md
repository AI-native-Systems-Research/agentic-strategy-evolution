# P/D Disaggregation Latency Model Validation in BLIS

## Answer

The paper's ITL formula ITL = α/(1 − λ·W) + c fits BLIS simulation data well (R² = 0.956 for AD, R² = 0.927 for AL) across arrival rates of 5–130 req/s, confirming the queueing-theoretic structure. Always-disaggregate (AD) consistently delivers lower ITL than always-local (AL) at every tested rate, with the gap growing monotonically from 0.06 ms at λ = 5 req/s to 1.68 ms at λ = 130 req/s; conversely, AD carries a TTFT penalty of 4–10 ms over AL due to KV-transfer pipeline overhead, a penalty that narrows as AL TTFT degrades faster under load.

## Evidence

### Iteration 1 — `pd-latency-model-validation`

Results are stored in:
- `/runs/iter-1/results/summary.json` — per-rate, per-mode ITL and TTFT values across seeds 42–44
- `/runs/iter-1/results/smoke_test.json` — sanity checks (no request drops, stable seeds)

**ITL formula fit (from `summary.json`):**

| Mode | R² | Fitted α (ms) | Fitted W (b parameter) |
|------|----|--------------|------------------------|
| AD   | 0.956 | ~3.5 ms | b_AD |
| AL   | 0.927 | ~3.5 ms | b_AL = 1.21 × b_AD |

The ratio b_AL/b_AD = 1.21 is consistent with the theoretical prediction that AL servers handle prefill + decode work while AD decode servers handle only decode work; under the model W_P/W_D ≈ 0.21 for qwen3-14b with 512-token prompts and 128-token outputs.

**ITL comparison (AD vs AL, selected rates from `summary.json`):**

| λ (req/s) | ITL_AL (ms) | ITL_AD (ms) | Gap (ms) |
|-----------|-------------|-------------|----------|
| 5         | ~3.56       | ~3.50       | 0.06     |
| 40        | ~4.10       | ~3.85       | 0.25     |
| 80        | ~5.20       | ~4.72       | 0.48     |
| 130       | ~8.30       | ~6.62       | 1.68     |

**TTFT comparison (AL vs AD, selected rates):**

| λ (req/s) | TTFT_AL (ms) | TTFT_AD (ms) | Overhead (AD−AL) ms |
|-----------|--------------|--------------|---------------------|
| 5         | ~90          | ~100         | ~9.6                |
| 80        | ~105         | ~113         | ~8.0                |
| 130       | ~130         | ~134         | ~4.2                |

**Formula breakdown regime:** The 1/(1−ρ) formula holds well below λ ≈ 100 req/s. Above this threshold the fit error grows, particularly for AL, because (a) the decode batch mixes prefill and decode tokens non-linearly, and (b) the effective ρ approaches 1 faster than the simple λ·W model predicts, introducing superlinear ITL growth that the single-parameter formula underestimates.

**Control (near-zero load, λ = 5):** The ITL gap is only 0.058 ms (3.4% of the gap at λ = 130), confirming the advantage is load-driven via the 1/(1−ρ) amplifier and is not an artifact of architectural differences at idle.

All claims are backed by `summary.json`; no dispatcher retries or failed runs were recorded.

## Principles Discovered

**RP-1** *(high confidence)*: AD ITL < AL ITL at every tested rate (5–130 req/s), gap grows monotonically from 0.06 ms to 1.68 ms. Mechanism: AD removes prefill work from decode servers, reducing ρ_D and hence T_iter via the 1/(1−ρ) amplifier. Applies to the fixed standard setup; may not hold if prefill servers saturate.

**RP-2** *(high confidence)*: AD TTFT > AL TTFT at every tested rate, overhead 4–10 ms (narrowing under load). Mechanism: AD TTFT includes KV-transfer pipeline latency absent in AL; the gap narrows because AL TTFT degrades faster as shared decode-server load increases.

**RP-3** *(high confidence)*: The ITL disaggregation advantage is almost entirely load-driven. At λ = 5 req/s the gap is only 0.058 ms; the 1/(1−ρ) amplifier ≈ 1 at low load, eliminating the structural advantage.

**RP-4** *(medium confidence)*: The paper's ITL formula fits BLIS with R² = 0.956 (AD) and 0.927 (AL). Fitted b_AL/b_AD = 1.21, implying W_P/W_D ≈ 0.21 for qwen3-14b at 512/128 tokens. Fit quality degrades for AL at extreme rates (λ > 100 req/s) due to mixed-batch non-linearity.

## Limitations & Open Questions

### Scientific Gaps
1. **Formula breakdown mechanism**: The exact cause of superlinear AL ITL growth above λ ≈ 100 req/s was identified qualitatively (mixed prefill+decode batches) but not quantified. A chunked-prefill ablation would isolate this.
2. **Prefill server saturation**: All tested rates produced zero drops, so the regime where prefill servers become the bottleneck (and RP-1/RP-2 may reverse) was not reached. Rates > 150 req/s or longer prompts would probe this.
3. **Variable-length workloads**: Only fixed prompt_tokens=512 / output_tokens=128 was tested. Variable-length workloads (non-zero stdev) would change the effective W distribution and the formula's Poisson-M/G/1 assumptions.
4. **TTFT formula fit**: The paper gives a closed-form TTFT prediction for AD and AL; only ITL was formally fit here. A dedicated TTFT formula validation campaign remains open.
5. **KV-transfer bandwidth sensitivity**: RP-2's TTFT overhead depends on NVLink bandwidth (default 100 Gbps). Sweeping `--kv-transfer-bandwidth` would determine how much of the TTFT gap is transfer-dominated vs. queue-wait-dominated.

### Infrastructure Gaps
No dispatcher failures or retries were recorded. The campaign ran cleanly with 2 iterations and complete result files. The `final/answer.json` artifact reflects the most current conclusions.