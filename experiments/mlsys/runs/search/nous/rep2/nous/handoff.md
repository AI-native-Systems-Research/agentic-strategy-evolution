# Handoff Snapshot — Iteration 4

## Goal

Validate that the 4-phase Pareto search algorithm generalizes across fundamentally different model architectures: MoE (Llama-4-Scout-17B-16E with interleaved expert/dense layers) and small dense models (qwen2.5-7b with no KV pressure and invalid tp=8). Run search.py at full scale (budget=200) on both models × 2 seeds, compute coverage against exhaustive reference fronts.

## Key Discoveries

1. **MoE model (Llama-4-Scout) has KV ceiling at kv=3000** — identical to Llama-70B. At tp=4,inst=2: kv=2000 causes preempt=36 (rps=7.72, ttft_p99=9017ms); kv=3000+ gives preempt=0 (rps=8.29, ttft_p99=59.49ms). kv=3000, 5000, 10000 all produce byte-identical results.

2. **MoE model follows tp > instances pattern.** At kv=10000: tp=8,inst=1: rps=9.26; tp=4,inst=2: rps=8.29; tp=1,inst=8: rps=5.55. The 1.67x throughput advantage of tp=8 over tp=1 at same GPU count is consistent with dense models.

3. **qwen2.5-7b has NO preemptions at any kv value.** At tp=4,inst=2: kv=2000 through kv=10000 all give rps=42.26, ttft_p99=22.25, preempt=0. The model is so small that the KV cache is never stressed. This means Phase 2 boundary mapping is entirely skipped.

4. **qwen2.5-7b panics at tp=8** — "NumHeads (28) must be divisible by TP (8)". This eliminates the tp=8,inst=1 topology. The search.py's `except Exception` handler returns None gracefully (verified: budget=50 test ran successfully with 48 unique configs out of 50 evals, 2 lost to tp=8 failures).

5. **qwen2.5-7b has fundamentally different throughput range.** At tp=4,inst=2: rps=42.26 (vs qwen3-14b's 26.78, Llama-70B's 8.35, MoE's 8.29). At tp=1,inst=1: rps=11.17 (still rate-limited at rate=100 with ttft_p99=8760ms). Small model = faster per-token, more throughput headroom.

6. **Each BLIS eval still takes 0.1-0.15s for all models.** Wall-clock is simulator-speed-bound, not model-dependent.

7. **search.py works on both new models out of the box.** Quick tests: MoE budget=50 → 16 Pareto configs; qwen2.5-7b budget=50 → 14 Pareto configs. No code changes needed.

## System Interface

- **Build:** `go build -o blis main.go` (exit 0 in <5s)
- **Run baseline (MoE):**
  ```
  ./blis run --model meta-llama/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic \
    --hardware H100 --latency-model trained-physics \
    --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
    --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
    --admission-policy always-admit --preemption-policy fcfs \
    --routing-policy round-robin --gpu-memory-utilization 0.9 \
    --tp 4 --num-instances 2 --scheduler fcfs --max-num-running-reqs 256 \
    --total-kv-blocks 5000 --block-size-in-tokens 32 \
    --metrics-path results/baseline_moe.json
  ```
- **Run baseline (small):**
  ```
  ./blis run --model qwen/qwen2.5-7b-instruct \
    --hardware H100 --latency-model trained-physics \
    --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
    --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
    --admission-policy always-admit --preemption-policy fcfs \
    --routing-policy round-robin --gpu-memory-utilization 0.9 \
    --tp 4 --num-instances 2 --scheduler fcfs --max-num-running-reqs 256 \
    --total-kv-blocks 5000 --block-size-in-tokens 32 \
    --metrics-path results/baseline_q7b.json
  ```
- **Output format:** `--metrics-path <path>` writes JSON with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`, `dropped_unservable`
- **MoE baseline result:** rps=8.29, ttft_p99=59.49, preempt=0
- **Small model baseline result:** rps=42.26, ttft_p99=22.25, preempt=0

## Code Map

- `search.py` — The search algorithm deliverable. 469 lines, 4-phase strategy. No code changes needed for iter-4.
- `search.py:103-146` — Evaluator class. `except Exception` handler at line 142 returns None for failed evals (tp=8 crash for qwen2.5-7b). Check here if failure handling is incorrect.
- `search.py:182-214` — Phase 1 ceiling+cheapest scan. Uses `max(KV_VALUES)=10000` as ceiling. For qwen2.5-7b, both ceiling and cheapest return identical results → no preemption detected.
- `search.py:217-258` — Phase 2 boundary mapping. Skipped when `has_preemptions=False` for all topologies (qwen2.5-7b case).
- `sim/latency/config.go:300-360` — MoE latency model path. Reads `num_local_experts`, `num_experts_per_tok`, `interleave_moe_layer_step` from config. Check here if MoE model gives unexpected latency values.
- `sim/model_hardware_config.go:15-25` — MoE fields in ModelConfig struct.
- `model_configs/llama-4-scout-17b-16e-instruct-fp8-dynamic/config.json` — MoE model config (16 experts, 1 per token, FP8 quantized, 48 layers, 5120 hidden_size).
- `model_configs/qwen2.5-7b-instruct/config.json` — Small model config (28 heads, not divisible by 8).

## Code Targets

No code changes needed for iter-4. Testing existing search.py on new model architectures.

## What I Tried That Didn't Work

- **tp=8 for qwen2.5-7b panics.** "NumHeads (28) must be divisible by TP (8)". This is expected behavior and the search.py handles it gracefully via exception handling. Not a bug.
- **Parsing metrics from stdout instead of --metrics-path file.** The stdout output includes per-instance metrics in addition to cluster metrics. Always use `--metrics-path` for reliable JSON parsing. Some python inline commands failed because the metrics file wasn't found after a redirect issue.

## What I Excluded and Why

- **Testing qwen2.5-7b at different rates.** Since kv doesn't matter at all for this model, rate variation tests would only test the topology dimension — less informative than the architecture dimension already being tested.
- **Budget-coverage curve for new models.** Could be useful but the primary question is whether full-budget (200) search achieves coverage, not where coverage saturates. Budget efficiency is well-characterized for qwen3-14b (RP-6).
- **Other MoE models (Mixtral).** Only one MoE model config is available in the repo (Llama-4-Scout). No Mixtral configs found.
- **codellama-34b, yi-34b, mistral-nemo, llama-2-7b.** Available but these are all dense models at various sizes. MoE + small-dense covers the two most architecturally distinct test cases.

## Evolution of Thinking

1. **Initially planned to test only MoE.** The iter-3 handoff suggested MoE as next. But during probing, discovered that qwen2.5-7b exercises a completely DIFFERENT failure mode (no preemptions, tp=8 crash) that tests algorithm robustness in ways MoE alone doesn't.
2. **Expected MoE to have a HIGHER KV ceiling.** The Scout model has 16 experts and FP8 quantization, which could change per-token KV memory. In fact, the ceiling is at kv=3000 — same as Llama-70B. The MoE overhead affects compute latency, not KV cache pressure.
3. **Discovered that qwen2.5-7b is the TRUE stress test for the algorithm.** When Phase 2 is entirely skipped and many kv variations are wasted (all identical), the algorithm's budget efficiency depends entirely on Phase 3+4 finding non-topology Pareto points. If the Pareto front is purely topology-driven (likely for this model), Phase 3+4 evals are overhead but not harmful.

## Current Status

- **Validated:** BLIS builds. Both models run successfully. search.py works on both (quick tests at budget=50). MoE KV ceiling measured (kv=3000). qwen2.5-7b KV insensitivity confirmed. tp=8 crash handled gracefully.
- **Uncertain:** Exact Pareto coverage for both models at budget=200 (needs exhaustive reference). Whether qwen2.5-7b's Pareto front includes any non-topology differentiators (maxrun, scheduler, bs).
- **Suggested next (iter-5, if needed):** If both pass >=90%, the algorithm is validated across 5 model regimes (qwen3-14b, Llama-70B, MoE-17B, qwen2.5-7b) × 3 rate levels × 2 seeds. Final deliverable: update final/answer.json with cross-architecture claims. If any regime fails, diagnose which Phase missed configs and add a targeted fix.

## Warnings & Constraints

- **MoE model name is case-sensitive:** `meta-llama/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic` (capital L, capital S). The directory is lowercase: `llama-4-scout-17b-16e-instruct-fp8-dynamic`.
- **qwen2.5-7b tp=8 crash is a panic, not a clean error.** The process exits with non-zero status and prints a stack trace to stderr. search.py handles this via `capture_output=True` + `except Exception`, but check that the metrics file was NOT created (it won't be, since the process panicked before writing output).
- **qwen2.5-7b reference: only ~150 valid configs out of 180.** The 30 configs with tp=8 will fail. Account for this when computing reference Pareto front — only include configs that successfully produce metrics.
- **MoE model emits a rope_scaling warning.** "rope_scaling.factor present but not applied" — this is cosmetic, does not affect metrics. Goes to stderr.
- **`--metrics-path` writes cluster-level JSON only.** Per-instance metrics are on stdout. Always parse the JSON file for search/coverage analysis.
