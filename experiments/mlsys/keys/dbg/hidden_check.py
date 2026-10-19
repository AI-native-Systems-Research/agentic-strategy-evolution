"""Hidden black-box regression checks for the debugging task. Run against a built `blis` binary.

Ground truth: the fixed upstream build (d8271ee) and an invariant that holds for any correct fix:
total_output_tokens must not depend on how often requests were preempted, for the same request set.
"""
import json, subprocess, sys, tempfile, os

CASES = [  # (name, extra args) — each compared preemption-heavy vs no-pressure on the same workload/seed
    ("rate20_kv600_s42", ["--rate", "20", "--num-requests", "200", "--seed", "42"], 600),
    ("rate20_kv600_s7", ["--rate", "20", "--num-requests", "200", "--seed", "7"], 600),
    ("rate40_kv900_s3", ["--rate", "40", "--num-requests", "300", "--seed", "3"], 900),
    ("short_out_kv400", ["--rate", "30", "--num-requests", "200", "--output-tokens", "64", "--seed", "11"], 400),
    ("long_out_kv1500", ["--rate", "10", "--num-requests", "120", "--output-tokens", "1024", "--seed", "5"], 1500),
    ("cluster2_kv700", ["--rate", "40", "--num-requests", "300", "--num-instances", "2", "--seed", "9"], 700),
]

NOPRESSURE = []  # filled from the fixed build by build_expected()

def run(blis, cwd, args, kv):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f: p = f.name
    r = subprocess.run([blis, "run", "--model", "qwen/qwen3-14b", "--total-kv-blocks", str(kv), *args, "--metrics-path", p],
                       cwd=cwd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.getsize(p): return None
    return json.load(open(p))

def check(repo):
    blis = os.path.join(repo, "blis")
    b = subprocess.run(["go", "build", "-o", "blis", "main.go"], cwd=repo, capture_output=True, text=True, timeout=600)
    if b.returncode != 0: return {"build": False, "error": b.stderr[-500:]}
    res = {"build": True, "cases": {}}
    for name, args, kv in CASES:
        hi, lo = run(blis, repo, args, kv), run(blis, repo, args, 1000000)
        if not hi or not lo: res["cases"][name] = {"ok": False, "why": "run failed"}; continue
        same = hi["total_output_tokens"] == lo["total_output_tokens"]
        res["cases"][name] = {"ok": bool(same and hi["preemption_count"] > 0 and hi["completed_requests"] == lo["completed_requests"]),
                              "preempt": hi["preemption_count"], "tok_pressure": hi["total_output_tokens"],
                              "tok_free": lo["total_output_tokens"]}
    # no-regression: without memory pressure, token totals must equal the fixed upstream build's values
    for name, args, want in NOPRESSURE:
        lo = run(blis, repo, args, 1000000)
        res["cases"][name] = {"ok": bool(lo and lo["total_output_tokens"] == want), "tok": lo and lo["total_output_tokens"], "want": want}
    res["pass"] = all(c["ok"] for c in res["cases"].values())
    return res

NP_ARGS = [("np_rate20_s42", ["--rate", "20", "--num-requests", "200", "--seed", "42"]),
           ("np_rate60_s1", ["--rate", "60", "--num-requests", "300", "--output-tokens", "256", "--seed", "1"])]
EXP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected_nopressure.json")
if os.path.exists(EXP):
    NOPRESSURE[:] = [(n, a, json.load(open(EXP))[n]) for n, a in NP_ARGS]

if __name__ == "__main__":
    if sys.argv[1] == "--build-expected":
        repo = sys.argv[2]; blis = os.path.join(repo, "blis")
        json.dump({n: run(blis, repo, a, 1000000)["total_output_tokens"] for n, a in NP_ARGS}, open(EXP, "w"))
        print(open(EXP).read())
    else:
        print(json.dumps(check(sys.argv[1]), indent=1))
