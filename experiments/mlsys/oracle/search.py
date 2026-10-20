"""Oracle for the blis-search optimization task.

The oracle runs the arm's delivered `search.py` itself, in a fresh copy of the arm's repo, with a fresh seed, on the
main config and on two held-out configs. It then scores the configurations returned, by looking each one up in our
exhaustive sweep (keys/search/space_*.json), so a search cannot inflate its result by reporting wrong metrics.

- B1: HV ratio >= 0.95 on the main config (mean over 3 fresh seeds), within 3 minutes and <= 200 evaluations.
- B2: same on the held-out configs (llama-3.1-8b rate 100; qwen3-14b rate 50).
- B3: HV ratio (number).
- T1..T4: structure facts from our sweep, matched against the answer (fixed phrase lists).
Budget is enforced by counting real `blis run` invocations through a wrapper binary placed first on PATH and at
./blis in the repo copy.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from common import KEYS, GO_ENV

sys.path.insert(0, os.path.join(KEYS, "search"))
from hv import hv  # noqa: E402

SPACES = {"main": ("qwen/qwen3-14b", 100), "heldout_llama": ("meta-llama/llama-3.1-8b-instruct", 100),
          "heldout_qwen_r50": ("qwen/qwen3-14b", 50)}
SEEDS = (1001, 1002, 1003)
BUDGET = 200
TIME_LIMIT = 180
KNOBS = ("tp", "num_instances", "scheduler", "max_num_running_reqs", "total_kv_blocks", "block_size_in_tokens")

_space_cache = {}


def space(tag):
    if tag not in _space_cache:
        d = json.load(open(os.path.join(KEYS, "search", f"space_{tag}.json")))
        rows = {tuple(r["config"][k] for k in KNOBS): r for r in d["rows"] if r["ok"]}
        allrows = [dict(r, total_kv_blocks=r["config"]["total_kv_blocks"]) for r in rows.values()]
        _space_cache[tag] = (rows, hv(allrows))
    return _space_cache[tag]


WRAPPER = """#!/bin/bash
# counts real evaluations; forwards to the clean BLIS binary
if [ "$1" = "run" ]; then echo x >> "{count}"; fi
exec "{real}" "$@"
"""


def run_search(arm_repo, tag, seed):
    model, rate = SPACES[tag]
    work = tempfile.mkdtemp(prefix="search_oracle_")
    try:
        repo = os.path.join(work, "repo")
        shutil.copytree(arm_repo, repo, symlinks=True,
                        ignore=shutil.ignore_patterns(".nous", ".nous-experiments", "__pycache__", "final", ".git"))
        b = subprocess.run(["go", "build", "-o", "blis.real", "main.go"], cwd=repo, capture_output=True, text=True,
                           timeout=900, env=GO_ENV)
        if b.returncode != 0:
            return dict(ok=False, why="build failed")
        count = os.path.join(work, "count")
        open(count, "w").close()
        wrapper = WRAPPER.format(count=count, real=os.path.join(repo, "blis.real"))
        for p in (os.path.join(repo, "blis"), os.path.join(work, "bin", "blis")):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(wrapper)
            os.chmod(p, 0o755)
        out = os.path.join(work, "front.json")
        env = dict(GO_ENV, PATH=os.path.join(work, "bin") + ":" + GO_ENV["PATH"])
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, "search.py", "--model", model, "--rate", str(rate), "--budget", str(BUDGET),
                                "--seed", str(seed), "--out", out], cwd=repo, capture_output=True, text=True,
                               timeout=TIME_LIMIT + 60, env=env)
        except subprocess.TimeoutExpired:
            return dict(ok=False, why="timeout", wall=time.time() - t0)
        wall = time.time() - t0
        evals = sum(1 for _ in open(count))
        if r.returncode != 0 or not os.path.exists(out):
            return dict(ok=False, why=f"exit {r.returncode}: {r.stderr[-300:]}", wall=wall, evals=evals)
        try:
            found = json.load(open(out))
        except json.JSONDecodeError:
            return dict(ok=False, why="bad json", wall=wall, evals=evals)
        rows, H = space(tag)
        pts, bad = [], 0
        for c in found if isinstance(found, list) else []:
            try:
                k = tuple(str(c[n]) if n == "scheduler" else int(c[n]) for n in KNOBS)
            except (KeyError, TypeError, ValueError):
                bad += 1
                continue
            if k in rows:
                rr = rows[k]
                pts.append(dict(rps=rr["rps"], ttft_p99_ms=rr["ttft_p99_ms"], gpus=rr["gpus"], total_kv_blocks=k[4]))
            else:
                bad += 1
        ratio = hv(pts) / H if pts else 0.0
        return dict(ok=True, hv_ratio=round(ratio, 4), n_returned=len(found) if isinstance(found, list) else 0,
                    n_invalid=bad, evals=evals, wall=round(wall, 1),
                    within_limits=bool(evals <= BUDGET and wall <= TIME_LIMIT))
    finally:
        shutil.rmtree(work, ignore_errors=True)


T_PHRASES = {
    "T1_block_size_32": [r"block[-_ ]?size[^.\n]{0,60}\b32\b[^.\n]{0,80}(domina|always|almost|nearly|most|\d{2}([.·]\d)?\s*%|optimal|best|preferred)",
                         r"\b32\b[^.\n]{0,40}block[-_ ]?size[^.\n]{0,80}(domina|always|almost|nearly|most|optimal|best)",
                         r"(bs|block_size_in_tokens|block_size|block[- ]size)\s*=\s*32[^.\n]{0,80}(domina|\d{2}([.·]\d)?\s*%|most|almost|nearly|always)"],
    "T2_scheduler_irrelevant": [r"scheduler[^.\n]{0,100}(irrelevant|negligible|minimal|little|no (significant |meaningful )?(effect|impact|difference)|near[- ]zero|marginal|tiny|insignificant|barely|does not matter|doesn'?t matter|least|weak)",
                                r"(fcfs|sjf)[^.\n]{0,60}(vs\.?|and|or)[^.\n]{0,20}(fcfs|sjf)[^.\n]{0,80}(negligible|little|no (significant )?difference|similar|equivalent|interchangeable|barely)"],
    "T3_gpu_tradeoff": [r"(more|additional|higher)\s+(gpus?|gpu count|replicas|instances|tp)[^.\n]{0,100}(throughput|rps|responses_per_sec|ttft|latency)",
                        r"(throughput|rps|latency|ttft)[^.\n]{0,100}(cost|at the expense|trade[- ]?off|vs\.?)[^.\n]{0,40}(gpus?|gpu count|hardware)",
                        r"(gpus?|gpu count)[^.\n]{0,60}(trade[- ]?off|vs\.?|versus)[^.\n]{0,60}(throughput|rps|latency|ttft)"],
    "T4_small_kv": [r"(small|smaller|smallest|low|lower|minimal|2000)[^.\n]{0,40}(kv|total_kv_blocks|kv[- ]blocks|kv budget|kv cache)[^.\n]{0,100}(suffic|enough|optimal|domina|pareto|best|most common|preferred)",
                    r"(large|larger|high|>\s*5000|7500|10000)[^.\n]{0,60}(kv|total_kv_blocks|kv[- ]blocks)[^.\n]{0,100}(never|not|rarely|no)[^.\n]{0,40}(pareto|optimal|on the front|help|benefit)",
                    r"(kv|total_kv_blocks|kv[- ]blocks)[^.\n]{0,60}(2000|smallest|minimum)[^.\n]{0,80}(domina|most|\d{2}([.·]\d)?\s*%|front|pareto)"],
}


def score(ws, answer, text):
    res = {}
    if not os.path.exists(os.path.join(ws, "search.py")):
        res.update(B1_main=False, B2_heldout=False, B3_hv_main=0.0, deliverable=False)
    else:
        res["deliverable"] = True
        runs = {tag: [run_search(ws, tag, s) for s in SEEDS] for tag in SPACES}
        res["runs"] = runs

        def agg(tag):
            rs = runs[tag]
            ok = all(r.get("ok") and r.get("within_limits") for r in rs)
            vals = [r.get("hv_ratio", 0.0) if r.get("ok") and r.get("within_limits") else 0.0 for r in rs]
            return ok, round(sum(vals) / len(vals), 4)
        okm, hvm = agg("main")
        res["B3_hv_main"] = hvm
        res["B1_main"] = bool(okm and hvm >= 0.95)
        h = [agg(t) for t in ("heldout_llama", "heldout_qwen_r50")]
        res["B3_hv_heldout_llama"], res["B3_hv_heldout_qwen_r50"] = h[0][1], h[1][1]
        res["B2_heldout"] = bool(all(o and v >= 0.95 for o, v in h))
        res["limits_respected"] = all(r.get("within_limits") for rs in runs.values() for r in rs)
    for k, pats in T_PHRASES.items():
        res[k] = any(re.search(p, text) for p in pats)
    tscore = sum(res[k] for k in T_PHRASES)
    res["T_score"] = tscore
    res["O1"] = bool(res["B1_main"] and tscore >= 3)
    res["O2_heldout"] = res["B2_heldout"]
    return res
