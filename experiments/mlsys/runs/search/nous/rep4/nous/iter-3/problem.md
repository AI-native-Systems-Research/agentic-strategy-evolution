# Problem Framing — Iteration 3: Model Generalization

## Research Question

Does the hierarchical Pareto search algorithm (search.py), which exploits four structural regularities discovered in iterations 1-2 (TP dominance, effective cache equivalence, maxr=256 plateau, scheduler×concurrency interaction in degraded regimes), generalize to fundamentally different model architectures?

Iter-1/2 validated the search on qwen/qwen3-14b (14B params, 40 layers, 40 attention heads, 8 KV heads). This iteration tests two contrasting models:
- **meta-llama/llama-3.1-70b-instruct** (70B params, 80 layers, 64 attention heads, 8 KV heads) — 5x larger, different architecture family, all TP values valid
- **qwen/qwen2.5-7b-instruct** (7B params, 28 layers, 28 attention heads, 4 KV heads) — half the size, and crucially **tp=8 is invalid** because 28 attention heads is not divisible by 8

The search script must be made robust to handle models where not all TP values are valid (a constraint discovered during probing: `sim/latency/trained_physics.go` panics when `NumHeads % TP != 0`).

Key source files:
- `search.py` — current search algorithm, hardcodes `TP_VALUES = [1, 2, 4, 8]`
- `cmd/root.go:963-980` — CLI flag definitions for all 6 knobs
- `sim/metrics.go:127` — `ResponsesPerSec` calculation
- `sim/latency/trained_physics.go` — TP divisibility constraint (panics on `NumHeads % TP != 0`)
- `cmd/hfconfig.go:260` — model config resolution

## System Interface

- **Build:** `go build -o blis main.go` (already built, binary at `./blis`)
- **CLI flags relevant to experiment:**
  - `--model <name>` — HuggingFace model path (e.g., `meta-llama/llama-3.1-70b-instruct`)
  - `--tp <int>` — tensor parallelism degree (`cmd/root.go:963`)
  - `--num-instances <int>` — number of instances (`cmd/root.go:966`)
  - `--scheduler <str>` — scheduling policy: fcfs or sjf (`cmd/root.go:791`)
  - `--max-num-running-reqs <int>` — max concurrent requests per instance (`cmd/root.go:972`)
  - `--total-kv-blocks <int>` — KV cache blocks per instance (`cmd/root.go:975`)
  - `--block-size-in-tokens <int>` — tokens per KV block (`cmd/root.go:978`)
  - `--metrics-path <path>` — JSON metrics output (`cmd/root.go:2078`)
- **Code evidence:** `cmd/root.go:963` defines `--tp`, `cmd/root.go:2078` defines `--metrics-path`
- **Native output:** `--metrics-path` writes JSON with `responses_per_sec`, `ttft_p99_ms`, etc.

## Baseline Command

```bash
./blis run --model meta-llama/llama-3.1-70b-instruct --hardware H100 --latency-model trained-physics \
  --num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 \
  --max-num-scheduled-tokens 4096 --long-prefill-token-threshold 0 \
  --admission-policy always-admit --preemption-policy fcfs \
  --routing-policy round-robin --gpu-memory-utilization 0.9 \
  --tp 8 --num-instances 1 --scheduler fcfs --max-num-running-reqs 256 \
  --total-kv-blocks 10000 --block-size-in-tokens 16 \
  --metrics-path results/baseline_70b.json
```

## Baseline Validation

Ran the baseline command for 70B model. Exit code 0. Output:
- rps=12.49, ttft_p99=53.5ms (ceiling at tp=8,ni=1)

Also verified:
- **TP dominance holds for 70B**: tp=1,ni=8 → rps=2.75; tp=8,ni=1 → rps=12.49 (4.5x ratio, stronger than 14B's 2.68x)
- **Cache equivalence holds**: kv=5000,bs=32 and kv=10000,bs=16 produce identical rps=12.49 and ttft_p99=53.5
- **maxr=256 plateau holds**: maxr=256 and maxr=512 produce identical results
- **maxr sensitivity differs**: maxr=128 loses 14% rps at ceiling for 70B (vs 0% for 14B); maxr=64 loses 37%; maxr=32 loses 59%
- **SJF×concurrency interaction holds at degraded cache**: At kv=3000,bs=32, SJF+128 gives rps=11.02 vs FCFS+256 rps=10.08 (+9.3% rps, +10.4% ttft)
- **qwen2.5-7b at tp=8 crashes**: `panic: NumHeads (28) must be divisible by TP (8)`. Valid TP: {1, 2, 4}

## Experimental Conditions

### Condition 1: Full enumeration of 70B model (ground truth)
Enumerate all 1800 configurations for meta-llama/llama-3.1-70b-instruct at rate=100 to establish ground truth Pareto front. Same 6-knob space as 14B (all TP values valid for 70B since num_heads=64).

### Condition 2: Full enumeration of 7B model (ground truth)
Enumerate all valid configurations for qwen/qwen2.5-7b-instruct at rate=100. Since tp=8 is invalid, there are 14 (tp,ni) combos × 120 = 1680 configs.

### Condition 3: Run search.py (modified) on 70B
Code change: add TP validation to search.py that probes each TP value with a minimal eval and skips invalid ones. Run the modified search with `--model meta-llama/llama-3.1-70b-instruct --rate 100 --budget 200 --seed 42`.

### Condition 4: Run search.py (modified) on 7B
Same modified search.py with `--model qwen/qwen2.5-7b-instruct --rate 100 --budget 200 --seed 42`.

### Code change description (search.py)
**Intent**: Add a `_discover_valid_tp` method that probes each TP value in {1, 2, 4, 8} with a quick eval (min settings, num-requests=1 style or catch failure). Invalid TPs are removed from the search space. `get_tp_instance_combos()` is adapted to use only valid TPs. This makes the search robust to any model's architecture constraints.

**Why this location**: The `TP_VALUES` constant (line 25) and `get_tp_instance_combos()` function (line 33) assume all 4 TP values are valid. The fix should make TP discovery dynamic based on the model being tested.

## Success Criteria

- **h-main (70B)**: Search achieves ≥90% unique Pareto tuple recall on 70B with ≤200 evaluations
- **h-robustness (7B)**: Search achieves ≥80% unique Pareto tuple recall on 7B with ≤200 evaluations

## Constraints

- search.py must use Python 3 standard library only (no numpy/scipy)
- search.py interface: `--model`, `--rate`, `--budget`, `--seed`, `--out`
- Must finish within 3 minutes
- Budget ≤200 evaluations (no exhaustive enumeration)
- Must not violate active principles (RP-1 through RP-6)

## Prior Knowledge

From iter-1 and iter-2:
- **RP-1**: TP is the dominant throughput lever. Verified for 70B (4.5x ratio, even stronger).
- **RP-2**: Hierarchical search with adaptive degraded-regime interaction achieves 100% recall on 14B.
- **RP-3**: KV preemption degradation is gradual below cache plateau.
- **RP-4**: maxr=256 is a universal plateau (256≡512). Verified for 70B.
- **RP-5**: SJF×maxr interaction creates Pareto tradeoffs in degraded regimes. Verified for 70B (+9.3%).
- **RP-6**: Pareto front diversity scales with arrival rate.

Key observation from probing: the 70B model has **steeper maxr sensitivity below the plateau** (14% loss at maxr=128 vs 0% for 14B at ceiling). This could create additional Pareto points involving maxr variations, potentially making the space harder for the search. But since low-maxr at ceiling is dominated (worse rps AND worse ttft, same gpus/kv), these points likely don't affect the Pareto front.
