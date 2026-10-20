# Problem Framing — Iteration 4

## Research Question

Does the 4-phase adaptive Pareto search algorithm generalize across fundamentally different model architectures? Specifically:

1. **MoE architectures** (Llama-4-Scout-17B-16E-Instruct-FP8-dynamic): This model uses 16 local experts with 1 expert per token and interleaved MoE/dense layers (`interleave_moe_layer_step=1`). It exercises BLIS's MoE-aware latency model (`sim/latency/config.go:~300-360`) with different compute/memory characteristics than dense models.

2. **Small dense models** (qwen2.5-7b-instruct): With only 28 attention heads, this model cannot use tp=8 (28 not divisible by 8, validated by `sim/latency/config.go` NewLatencyModel → panic). Additionally, at rate=100 with kv=2000, preemption_count=0 across all topologies — the KV-insensitive regime where Phase 2 boundary mapping is entirely skipped.

These two models exercise the algorithm's two main structural assumptions: (a) Phase 1 discovers a ceiling-vs-cheapest preemption gap, and (b) Phase 2 maps the boundary. When both assumptions fail (qwen2.5-7b), the algorithm must still find all Pareto points.

Key source files:
- `sim/latency/config.go:323-360` — MoE expert count resolution and interleave handling
- `sim/model_hardware_config.go:15-25` — NumLocalExperts, NumExpertsPerTok, InterleaveMoELayerStep fields
- `search.py:182-214` — Phase 1 ceiling+cheapest scan
- `search.py:217-258` — Phase 2 boundary mapping (skipped when no preemptions)
- `search.py:103-146` — Evaluator with `except Exception` handler for tp constraint failures

## System Interface

- **Build command:** `go build -o blis main.go` (validated, exit 0)
- **CLI flags relevant to experiment:**
  - `--model <name>` — model selection (string, resolved via HF config lookup). Code: `cmd/run.go`
  - `--tp <N>` — tensor parallelism degree. Code: `cmd/run.go`
  - `--num-instances <N>` — instance count. Code: `cmd/run.go`
  - `--total-kv-blocks <N>` — KV cache blocks per instance. Code: `cmd/run.go`
  - `--metrics-path <path>` — native JSON output for metrics. Code: `cmd/run.go`
  - All 6 search knobs (tp, num-instances, scheduler, max-num-running-reqs, total-kv-blocks, block-size-in-tokens)
- **Code evidence:**
  - `sim/latency/config.go:323` — `InferWeightBytesFromModelName` for quantization detection
  - `sim/model_hardware_config.go:15` — `NumLocalExperts` field definition
  - `model_configs/llama-4-scout-17b-16e-instruct-fp8-dynamic/config.json` — MoE config with `num_local_experts: 16`
  - `model_configs/qwen2.5-7b-instruct/config.json` — Dense 7B model config
- **Native output:** `--metrics-path <path>` writes JSON with `responses_per_sec`, `ttft_p99_ms`, `preemption_count`, `dropped_unservable`

## Baseline Command

```bash
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

## Baseline Validation

### MoE model (Llama-4-Scout) at tp=4, inst=2:
- **Exit code:** 0
- **Output file:** `/tmp/moe_metrics.json`
- **Key metric:** `responses_per_sec=8.29`, `ttft_p99_ms=59.49`, `preemption_count=0`

### MoE model KV ceiling (tp=4, inst=2):
- kv=2000: rps=7.72, ttft_p99=9017.11, preempt=36 (preemption regime!)
- kv=3000: rps=8.29, ttft_p99=59.49, preempt=0 (ceiling)
- kv=5000: rps=8.29, ttft_p99=59.49, preempt=0 (identical to kv=3000)
- kv=10000: rps=8.29, ttft_p99=59.49, preempt=0 (identical to kv=3000)

### MoE model topologies at kv=10000 (ceiling):
- tp=8,inst=1 (8 GPUs): rps=9.26, ttft_p99=55.43
- tp=4,inst=2 (8 GPUs): rps=8.29, ttft_p99=59.49
- tp=4,inst=1 (4 GPUs): rps=7.55, ttft_p99=65.66
- tp=2,inst=4 (8 GPUs): rps=6.97, ttft_p99=70.13
- tp=1,inst=8 (8 GPUs): rps=5.55, ttft_p99=92.53
- tp=2,inst=1 (2 GPUs): rps=5.51, ttft_p99=88.70
- tp=1,inst=1 (1 GPU): rps=3.58, ttft_p99=152.94

### Small dense model (qwen2.5-7b) at tp=4, inst=2:
- **Key metric:** `responses_per_sec=42.26`, `ttft_p99_ms=22.25`, `preemption_count=0`
- **KV insensitivity:** kv=2000, 3000, 5000, 10000 all produce identical results (rps=42.26, ttft_p99=22.25, preempt=0)
- **tp=8 constraint:** Panics with "NumHeads (28) must be divisible by TP (8)" — handled by search.py's except clause

### Small dense topologies at kv=2000 (selected):
- tp=4,inst=2 (8 GPUs): rps=42.26, ttft_p99=22.25
- tp=2,inst=2 (4 GPUs): rps=30.24, ttft_p99=26.99
- tp=4,inst=1 (4 GPUs): rps=29.68, ttft_p99=2028.57
- tp=2,inst=1 (2 GPUs): rps=19.21, ttft_p99=4204.09
- tp=1,inst=2 (2 GPUs): rps=17.74, ttft_p99=2120.73
- tp=1,inst=1 (1 GPU): rps=11.17, ttft_p99=8760.67

### Search.py validation (quick test):
- MoE model, budget=50: 16 Pareto-optimal from 50 evals (exit 0)
- qwen2.5-7b, budget=50: 14 Pareto-optimal from 48 unique configs (50 evals, 2 failed on tp=8 topologies)

## Experimental Conditions

### Condition 1: MoE model search (h-main)
For each seed in {42, 123}:
1. Run exhaustive reference: all 15 topologies × 6 kv × 2 bs at fcfs/maxrun=256 (180 configs)
2. Run search.py with budget=200
3. Compute Pareto coverage (% of reference Pareto found by search)

```bash
python3 search.py --model meta-llama/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic \
  --rate 100 --budget 200 --seed 42 --out results/h-main/search_moe_s42.json
```

### Condition 2: Small dense model search (h-robustness)
For each seed in {42, 123}:
1. Run exhaustive reference: all 15 topologies × 6 kv × 2 bs at fcfs/maxrun=256 (180 configs, ~30 will fail on tp=8)
2. Run search.py with budget=200
3. Compute Pareto coverage

```bash
python3 search.py --model qwen/qwen2.5-7b-instruct \
  --rate 100 --budget 200 --seed 42 --out results/h-robustness/search_q7b_s42.json
```

## Success Criteria

- **h-main (MoE):** ≥90% Pareto coverage at both seeds for Llama-4-Scout at rate=100
- **h-robustness (small model):** ≥90% Pareto coverage at both seeds for qwen2.5-7b at rate=100, despite tp=8 failures and KV-insensitive regime

## Constraints

- Budget: ≤200 evaluations per search run
- Wall-clock: ≤3 minutes per search run
- No modifications to search.py (testing the iter-3 version as-is)
- Fixed flags from campaign: `--hardware H100 --latency-model trained-physics --num-requests 200 --prefix-tokens 512 --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 --admission-policy always-admit --preemption-policy fcfs --routing-policy round-robin --gpu-memory-utilization 0.9`

## Prior Knowledge

Active principles that apply:
- **RP-1 (KV saturation):** Confirmed — MoE ceiling is kv=3000 (same as Llama-70B). qwen2.5-7b has no saturation point (all kv identical).
- **RP-2 (tp > instances):** Confirmed — MoE model shows tp=8,inst=1 (9.26 rps) > tp=1,inst=8 (5.55 rps). qwen2.5-7b shows same pattern.
- **RP-5 (adaptive ceiling):** The kv=max(KV_VALUES) strategy should work for MoE (ceiling at 3000) and qwen2.5-7b (no ceiling needed).
- **RP-7 (cross-regime generalization):** Tested on dense models only. MoE is the untested architecture class.
- **RP-8 (seed robustness):** Expected to hold for both new models.
