import json, subprocess, itertools, sys, os
B = "/Users/toslali/mlsys_runs/repos/blis-pd-base/blis"
OUT = "/Users/toslali/mlsys_runs/keys/pd/sweep"
os.makedirs(OUT, exist_ok=True)
def run(dec, rate, seed, n_in=512, n_out=128, P=2, D=2, nreq=300):
    p = f"{OUT}/{dec}_r{rate}_s{seed}_in{n_in}_out{n_out}_P{P}D{D}.json"
    if not os.path.exists(p):
        subprocess.run([B, "run", "--model", "qwen/qwen3-14b", "--num-instances", str(P + D), "--prefill-instances", str(P),
                        "--decode-instances", str(D), "--pd-decider", dec, "--rate", str(rate), "--num-requests", str(nreq),
                        "--prompt-tokens", str(n_in), "--prompt-tokens-stdev", "0", "--output-tokens", str(n_out),
                        "--output-tokens-stdev", "0", "--routing-policy", "least-loaded", "--seed", str(seed),
                        "--metrics-path", p], capture_output=True, check=True, cwd="/Users/toslali/mlsys_runs/repos/blis-pd-base")
    d = json.load(open(p))
    return {k: d.get(k) for k in ("itl_mean_ms", "ttft_mean_ms", "e2e_mean_ms", "completed_requests", "preemption_count")}
cfgs = [dict(n_in=512, n_out=128, P=2, D=2)]
if len(sys.argv) > 1 and sys.argv[1] == "heldout":
    cfgs = [dict(n_in=2048, n_out=256, P=2, D=2), dict(n_in=256, n_out=512, P=2, D=2), dict(n_in=512, n_out=128, P=3, D=3)]
rows = []
for c in cfgs:
    for dec in ("never", "always"):
        for rate in (1, 2, 5, 10, 15, 20, 30, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150):
            for seed in (42, 43, 44, 45, 46):
                rows.append(dict(cfg=c, dec=dec, rate=rate, seed=seed, **run(dec, rate, seed, **c)))
json.dump(rows, open(f"{OUT}_{sys.argv[1] if len(sys.argv)>1 else 'main'}.json", "w"), indent=1)
print(len(rows), "runs")
