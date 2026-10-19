# Task: understand and search the BLIS serving-configuration space

This repository is BLIS, a discrete-event simulator for LLM inference serving (Go; build with `go build -o blis main.go`).
Each evaluation is one `./blis run` and takes about 0.1 to 0.3 seconds.

Configuration space (6 knobs):
- `--tp` in {1, 2, 4, 8}; `--num-instances` in {1 .. 8/tp} (so tp * instances <= 8 GPUs)
- `--scheduler` in {fcfs, sjf}
- `--max-num-running-reqs` in {32, 64, 128, 256, 512}
- `--total-kv-blocks` in {2000, 3000, 4000, 5000, 7500, 10000}
- `--block-size-in-tokens` in {16, 32}

Fixed flags for every evaluation: `--model qwen/qwen3-14b --hardware H100 --latency-model trained-physics
--num-requests 200 --rate 100 --prefix-tokens 512 --seed 42 --max-num-scheduled-tokens 4096
--long-prefill-token-threshold 0 --admission-policy always-admit --preemption-policy fcfs --routing-policy round-robin
--gpu-memory-utilization 0.9`.

Four objectives: maximize `responses_per_sec`, minimize `ttft_p99_ms` (both from `--metrics-path` JSON), minimize GPU
count (tp * instances), minimize `total_kv_blocks`.

Research question: what is the structure of this space's Pareto front (which knobs matter, which do not, what are the
trade-offs), and can you design a search algorithm that finds a near-complete Pareto front with at most 200 evaluations?

Deliver a Python 3 script `search.py` (standard library only) that takes `--model`, `--rate`, `--budget` (max
evaluations), `--seed`, and `--out` (path), runs at most `--budget` BLIS evaluations, and writes a JSON list of the
non-dominated configurations it found, each as {"tp", "num_instances", "scheduler", "max_num_running_reqs",
"total_kv_blocks", "block_size_in_tokens"}. It will be run as `python3 search.py --model <m> --rate <r> --budget 200
--seed <s> --out <file>` from the repository root, possibly with a different model or rate than the ones above, and must
finish within 3 minutes. Do not exhaustively enumerate the space in your search script. Report what you learned about the
space's structure.
