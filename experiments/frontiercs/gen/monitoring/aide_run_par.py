#!/usr/bin/env python3
"""Run AIDE on the 5 algorithmic tasks with a concurrency pool of 3 under the $50-or-max rule.
LLM calls (slow part) parallelize via the gateway; the single judge container may serialize evals
(correctness preserved, just queues). Each task: own workdir + log + pred. In-process $50 stop.
"""
import os, subprocess, time
from pathlib import Path

REPO = "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution"
ADAPTER = f"{REPO}/experiments/frontiercs/gen/aide_frontier.py"
PY = os.path.expanduser("~/frontier/aide-venv/bin/python")
GATES = f"{REPO}/experiments/frontiercs/aide_gates"
TASKS = [26, 69, 79, 170]
POOL = 3

os.makedirs(f"{GATES}/preds", exist_ok=True)
os.makedirs(f"{GATES}/solutions", exist_ok=True)


def launch(p):
    lf = open(f"/tmp/aide_p{p}.log", "w")
    out = f"{GATES}/preds/p{p}.aide.json"
    print(f"=== [{time.strftime('%H:%M')}] START p{p} ===", flush=True)
    return subprocess.Popen(
        [PY, "-u", ADAPTER, str(p), "--model", "claude-opus-4-6",
         "--steps", "150", "--num-drafts", "5", "--budget", "50", "--ceiling", "99.5",
         "--label", "aide", "--out", out, "--logdir", os.path.expanduser("~/frontier/gen_logs")],
        stdout=lf, stderr=subprocess.STDOUT, cwd=REPO)


pending = list(TASKS)
running = {}  # pid_obj -> task
while pending or running:
    while pending and len(running) < POOL:
        p = pending.pop(0)
        running[launch(p)] = p
    done = [proc for proc in running if proc.poll() is not None]
    for proc in done:
        p = running.pop(proc)
        wd = Path(os.path.expanduser(f"~/frontier/gen_logs/frontier_{p}_aide_aide/solution.cpp"))
        if wd.exists():
            (Path(f"{GATES}/solutions") / f"p{p}.aide.cpp").write_text(wd.read_text())
        print(f"=== [{time.strftime('%H:%M')}] DONE p{p} rc={proc.returncode} ===", flush=True)
    time.sleep(5)

print("ALLDONE_AIDE", flush=True)
