import json, subprocess, os, sys, itertools, tempfile
from concurrent.futures import ThreadPoolExecutor
REPO = "/Users/toslali/mlsys_runs/repos/blis-pd-base"
SPACE = dict(tp=[1, 2, 4, 8], scheduler=["fcfs", "sjf"], max_num_running_reqs=[32, 64, 128, 256, 512],
             total_kv_blocks=[2000, 3000, 4000, 5000, 7500, 10000], block_size_in_tokens=[16, 32])
def configs():
    for tp in SPACE["tp"]:
        for inst in range(1, 8 // tp + 1):
            for s, m, kv, bs in itertools.product(SPACE["scheduler"], SPACE["max_num_running_reqs"], SPACE["total_kv_blocks"], SPACE["block_size_in_tokens"]):
                yield dict(tp=tp, num_instances=inst, scheduler=s, max_num_running_reqs=m, total_kv_blocks=kv, block_size_in_tokens=bs)
def run(c, model, rate):
    fd, p = tempfile.mkstemp(suffix=".json"); os.close(fd)
    cmd = ["./blis", "run", "--model", model, "--hardware", "H100", "--latency-model", "trained-physics", "--num-requests", "200",
           "--rate", str(rate), "--prefix-tokens", "512", "--seed", "42", "--max-num-scheduled-tokens", "4096",
           "--long-prefill-token-threshold", "0", "--admission-policy", "always-admit", "--preemption-policy", "fcfs",
           "--routing-policy", "round-robin", "--gpu-memory-utilization", "0.9", "--tp", str(c["tp"]),
           "--num-instances", str(c["num_instances"]), "--scheduler", c["scheduler"], "--max-num-running-reqs", str(c["max_num_running_reqs"]),
           "--total-kv-blocks", str(c["total_kv_blocks"]), "--block-size-in-tokens", str(c["block_size_in_tokens"]), "--metrics-path", p]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, timeout=300)
    d = json.load(open(p)) if r.returncode == 0 and os.path.getsize(p) else None
    os.unlink(p)
    return dict(config=c, ok=d is not None, rps=d and d["responses_per_sec"], ttft_p99_ms=d and d["ttft_p99_ms"],
                gpus=c["tp"] * c["num_instances"], preemptions=d and d["preemption_count"], completed=d and d["completed_requests"])
def pareto(rows):  # maximize rps, minimize ttft_p99, minimize gpus
    ok = [r for r in rows if r["ok"]]
    def dom(a, b): return (a["rps"] >= b["rps"] and a["ttft_p99_ms"] <= b["ttft_p99_ms"] and a["gpus"] <= b["gpus"] and
                           (a["rps"] > b["rps"] or a["ttft_p99_ms"] < b["ttft_p99_ms"] or a["gpus"] < b["gpus"]))
    return [r for r in ok if not any(dom(o, r) for o in ok)]
if __name__ == "__main__":
    model, rate, tag = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    cs = list(configs())
    with ThreadPoolExecutor(8) as ex: rows = list(ex.map(lambda c: run(c, model, rate), cs))
    front = pareto(rows)
    json.dump(dict(model=model, rate=rate, rows=rows, front=front), open(f"/Users/toslali/mlsys_runs/keys/search/space_{tag}.json", "w"))
    print(tag, len(rows), "configs", sum(r["ok"] for r in rows), "ok", len(front), "pareto")
