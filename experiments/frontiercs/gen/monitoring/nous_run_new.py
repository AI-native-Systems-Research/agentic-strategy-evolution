#!/usr/bin/env python3
"""Run Nous on the 3 new-class tasks (p26 DP, p69 string, p79 math/NT) in parallel (pool=3).
Uses frontier_gen_costbudget.py --agent nous. $50-or-max via high iter cap + cost budget.
Each: own log /tmp/nous_p{P}.log, pred nous_gates/preds/p{P}.nous.json.
"""
import os, subprocess, time
from pathlib import Path

REPO = "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution"
RUNNER = f"{REPO}/experiments/frontiercs/gen/frontier_gen_costbudget.py"
PY = f"{REPO}/.venv/bin/python"
GATES = f"{REPO}/experiments/frontiercs/nous_gates"
TASKS = [26, 69, 79]

os.makedirs(f"{GATES}/preds", exist_ok=True)
os.makedirs(f"{GATES}/solutions", exist_ok=True)

env = dict(os.environ)
# Nous SDK path uses the claude CLI -> Anthropic messages API; point it at the gateway + quiet telemetry.
env["ANTHROPIC_BASE_URL"] = env.get("OPENAI_BASE_URL", "")
env["ANTHROPIC_API_KEY"] = env.get("OPENAI_API_KEY", "")
for k in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
          "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
    env[k] = "1"


def launch(p):
    lf = open(f"/tmp/nous_p{p}.log", "w")
    out = f"{GATES}/preds/p{p}.nous.json"
    print(f"=== [{time.strftime('%H:%M')}] START nous p{p} ===", flush=True)
    return subprocess.Popen(
        [PY, "-u", RUNNER, str(p), "--agent", "nous", "--model", "claude-opus-4-6",
         "--nous-iters", "12", "--cost-budget", "50", "--label", "nous",
         "--out", out, "--logdir", os.path.expanduser("~/frontier/gen_logs")],
        stdout=lf, stderr=subprocess.STDOUT, cwd=REPO, env=env)

procs = {launch(p): p for p in TASKS}
while any(pr.poll() is None for pr in procs):
    time.sleep(10)
for pr, p in procs.items():
    print(f"=== [{time.strftime('%H:%M')}] DONE nous p{p} rc={pr.returncode} ===", flush=True)
print("ALLDONE_NOUS", flush=True)
