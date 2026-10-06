#!/usr/bin/env python3
"""Run Nous on the remaining new-class tasks with the fresh litellm key.
Pool=2 so that, together with the already-running p26, total concurrent Nous runs stay <= 3.
Tasks: p69 (string), p79 (math/NT), p170 (flow). Each: own log, pred, 90s silence watchdog (baked
into the runner's spec now). $50-or-max.
"""
import os, subprocess, time
from pathlib import Path

REPO = "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution"
RUNNER = f"{REPO}/experiments/frontiercs/gen/frontier_gen_costbudget.py"
PY = os.path.expanduser("~/frontier/aide-venv/bin/python")
GATES = f"{REPO}/experiments/frontiercs/nous_gates"
TASKS = [69, 79, 170]
POOL = 2
NEWKEY = os.environ.get("IBM_LITELLM_KEY", "")  # set via env; never hardcode secrets

os.makedirs(f"{GATES}/preds", exist_ok=True)
env = dict(os.environ)
env["OPENAI_API_KEY"] = NEWKEY
env["ANTHROPIC_API_KEY"] = NEWKEY
env["ANTHROPIC_BASE_URL"] = env.get("OPENAI_BASE_URL", "")
for k in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
          "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
    env[k] = "1"
env.pop("CLAUDE_CONFIG_DIR", None)


def launch(p):
    lf = open(f"/tmp/nous_rest_p{p}.log", "w")
    out = f"{GATES}/preds/p{p}.nousNEWKEY.json"
    print(f"=== [{time.strftime('%H:%M')}] START nous p{p} ===", flush=True)
    return subprocess.Popen(
        [PY, "-u", RUNNER, str(p), "--agent", "nous", "--model", "claude-opus-4-6",
         "--nous-iters", "12", "--cost-budget", "50", "--label", "nousNEWKEY",
         "--out", out, "--logdir", os.path.expanduser("~/frontier/gen_logs")],
        stdout=lf, stderr=subprocess.STDOUT, cwd=REPO, env=env)


pending = list(TASKS)
running = {}
while pending or running:
    while pending and len(running) < POOL:
        p = pending.pop(0)
        running[launch(p)] = p
    done = [pr for pr in running if pr.poll() is not None]
    for pr in done:
        p = running.pop(pr)
        print(f"=== [{time.strftime('%H:%M')}] DONE nous p{p} rc={pr.returncode} ===", flush=True)
    time.sleep(10)
print("ALLDONE_NOUS_REST", flush=True)
