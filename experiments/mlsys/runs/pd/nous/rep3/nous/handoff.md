# Handoff — Iteration 1: P/D Disaggregation Latency Model Validation

## Goal

Run BLIS at 8 arrival rates × 2 P/D modes (AL/AD) × 3 seeds = 48 experiments. For each, capture per-request ITL, TTFT, and E2E via `--metrics-path`. Compare AL vs AD at each rate. Fit the paper's ITL formula ITL = a/(1−b·λ)+c to the data. Report where the formula fits, where it breaks, and the mechanism behind any breakdown. Write `final/answer.json` in the repo root with quantitative claims.

## Key Discoveries

1. **AL uses only 2 of 4 instances.** With `--pd-decider never`, prefill instances (0,1) receive 0 requests. All 300 requests go to decode instances (2,3). Confirmed via per-instance metrics showing instances 0,1 have `completed_requests=0`.

2. **ITL gap grows monotonically with rate.** Probed at seed=42: ITL gap (AL−AD) goes from 0.06ms at rate=5 to 1.69ms at rate=150. This is consistent with the paper's 1/(1−ρ) amplification of the utilization difference.

3. **TTFT gap narrows at higher rates.** AD TTFT exceeds AL TTFT at all rates, but the gap shrinks from ~10ms at rate=5 to ~4ms at rate=130. This is because AL TTFT grows faster (decode server batch interference affects prefill under AL) while AD TTFT grows slowly (dedicated prefill server is lightly loaded).

4. **No saturation/drops at any rate up to 150.** All 300 requests complete with 0 drops, 0 preemptions, 0 timeouts at every tested rate. The system is stable across the full experimental range.

5. **TTFT for AD = prefillTTFT + transferDuration + firstDecodeStep** (sim/cluster/cluster.go:1694-1705). This is the code implementing the paper's Eq. 19 overhead.

6. **Per-request data available via `--metrics-path`.** Each request has `ttft_ms`, `itl_ms`, `e2e_ms`, `scheduling_delay_ms`, `handled_by`. Suitable for per-request curve fitting and distribution analysis.

7. **Runs are fast.** Each 300-request run completes in 3–5 seconds wall-clock. Total experiment (48 runs) should take < 5 minutes.

## System Interface

- **Build:** `go build -o blis main.go` (validated, exit 0)
- **Run baseline (AL):**
  ```bash
  ./blis run --model qwen/qwen3-14b --num-instances 4 --prefill-instances 2 --decode-instances 2 --num-requests 300 --prompt-tokens 512 --prompt-tokens-stdev 0 --output-tokens 128 --output-tokens-stdev 0 --routing-policy least-loaded --pd-decider never --rate 10 --seed 42 --metrics-path results/al_r10_s42.json
  ```
- **Run treatment (AD):** Same as above with `--pd-decider always`
- **Output format:** `--metrics-path` writes JSON with aggregate stats + `requests[]` array with per-request `ttft_ms`, `itl_ms`, `e2e_ms`
- **Baseline result:** AL rate=10 seed=42: `itl_mean_ms=12.80`, `ttft_mean_ms=36.58`, 300/300 completed

## Code Map

| Location | What's there | When to look |
|----------|-------------|--------------|
| `sim/disaggregation.go:44-58` | NeverDisaggregate / AlwaysDisaggregate deciders | If pd-decider behavior seems wrong |
| `sim/cluster/pd_events.go:90-283` | KVTransferStarted/Completed events, transfer duration formula | If transfer latency numbers look off |
| `sim/cluster/cluster.go:1690-1705` | TTFT rewrite for disaggregated requests (newTTFT = prefillTTFT + transferDuration + firstDecodeStep) | If AD TTFT values are unexpected |
| `sim/cluster/cluster.go:745` | Detection of prefill/decode sub-request completions | If request lifecycle accounting seems wrong |
| `sim/cluster/pd_events.go:233-260` | Transfer duration calculation: baseLatUs + transferBytes/bandwidth | If transfer duration values seem off |
| `cmd/root.go:1019-1022` | CLI flag definitions for prefill-instances, decode-instances, pd-decider | If flag parsing issues arise |
| `cmd/root.go:2078` | `--metrics-path` flag definition | If output file format issues arise |

## Code Targets

No code changes in this iteration — pure flag-variation experiment.

## What I Tried That Didn't Work

- Nothing significant failed. All commands worked as expected from the first probe.

## What I Excluded and Why

1. **`--pd-decider prefix-threshold`:** Excluded because the paper's core comparison is AL vs AD. The prefix-threshold decider is a practical middle ground but not part of the closed-form model validation. Can be explored in iteration 2.

2. **Higher rates (> 150 req/s):** Not tested because the research question caps the range at 150. Within 1–150, the system shows no saturation — the queueing model holds without drops.

3. **Transfer contention (`--pd-transfer-contention`):** Left at default (off). With contention enabled, concurrent transfers share bandwidth, which would increase AD TTFT. This is a second-order effect worth exploring in later iterations.

4. **Multiple seed counts / power analysis:** With 3 seeds and the deterministic simulator, we get 3 independent trials per condition. The effect sizes observed in probes (e.g., ITL gap of 0.06–1.69ms with absolute ITL values of 12–20ms) are large enough to be unambiguous without more seeds.

5. **Curve fitting during exploration:** Did not attempt to fit ITL = a/(1−b·λ)+c during design — this is the executor's analysis task with full per-request data.

## Evolution of Thinking

Started expecting I might need to find the "breakdown" rate where the formula fails. After probing the full range (1–150 req/s), I found the system is well-behaved everywhere — no saturation, no drops, monotonic ITL growth. The "breakdown" may be more subtle: the formula might fit well overall but have systematic residuals at specific rates (e.g., where chunked prefill kicks in), or the fit parameters may reveal that BLIS's work-per-iteration differs from the paper's analytic W_tot.

The TTFT behavior was surprising: I expected AD TTFT to be higher by a roughly constant offset (the transfer overhead). Instead, the gap narrows at higher rates because AL TTFT grows faster. This matches the paper's prediction (Eq. 20: the Q_D terms cancel, and the prefill pipeline overhead doesn't grow as fast as the decode server interference under AL).

## Current Status

- **Validated:** Build works, both AL and AD modes produce correct output at all rates 5–150, per-request metrics capture works, all 300 requests complete in every condition, no drops/preemptions.
- **Uncertain:** The exact R² of the ITL formula fit — probes suggest a good fit but quantitative curve fitting hasn't been done.
- **Suggested next (iteration 2):** If the ITL formula fits well, test the paper's dynamic disaggregation threshold (Eq. 27: ηQ_D + V/2 > Q_P) by implementing a threshold-based decider. Or test the chunking effect (Remark 1) by varying `--max-num-scheduled-tokens`.

## Warnings & Constraints

1. **Stderr warnings are normal.** BLIS emits `Using default tp=1`, `Using default GPU=H100`, `Using default vLLM version=...` on stderr for the default model config. These don't affect results.

2. **Output goes to stdout.** Per-instance and cluster metrics print to stdout in `=== Simulation Metrics ===` blocks. Use `--metrics-path` to get clean JSON. Don't redirect stdout — it breaks the metrics capture.

3. **AD mode prints extra "PD Metrics" block** at the end of stdout showing `Disaggregated Requests` and `Dropped at Decode KV` counts.

4. **Instance numbering:** With 4 instances, instances 0-1 are prefill, instances 2-3 are decode. Under AL (`--pd-decider never`), instances 0-1 are idle. Under AD (`--pd-decider always`), all 4 are used.

5. **`final/answer.json` required.** The campaign requires writing `final/answer.json` in the repository root with claims, evidence paths, and a repro command. The executor must create this file after analysis.
