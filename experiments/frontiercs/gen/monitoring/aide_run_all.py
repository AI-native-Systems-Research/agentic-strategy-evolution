#!/usr/bin/env python3
"""Run AIDE on the 5 algorithmic tasks sequentially under the $50-or-max rule.
In-process budget stop (adapter checks spend() each step) makes an external watchdog unnecessary.
Judge is a single Docker container on :8081, so we run SEQUENTIALLY to avoid eval contention.
Per-task: log -> /tmp/aide_p{P}.log, pred -> aide_gates/preds/p{P}.aide.json, best cpp copied to solutions/.
"""
import os, subprocess, time
from pathlib import Path

REPO = "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution"
ADAPTER = f"{REPO}/experiments/frontiercs/gen/aide_frontier.py"
PY = os.path.expanduser("~/frontier/aide-venv/bin/python")
GATES = f"{REPO}/experiments/frontiercs/aide_gates"
TASKS = [0, 5, 9, 15, 22]

os.makedirs(f"{GATES}/preds", exist_ok=True)
os.makedirs(f"{GATES}/solutions", exist_ok=True)

for p in TASKS:
    log = f"/tmp/aide_p{p}.log"
    out = f"{GATES}/preds/p{p}.aide.json"
    print(f"=== [{time.strftime('%H:%M')}] START p{p} ===", flush=True)
    with open(log, "w") as lf:
        rc = subprocess.run(
            [PY, ADAPTER, str(p), "--model", "claude-opus-4-6",
             "--steps", "150", "--num-drafts", "5", "--budget", "50", "--ceiling", "99.5",
             "--label", "aide", "--out", out, "--logdir", os.path.expanduser("~/frontier/gen_logs")],
            stdout=lf, stderr=subprocess.STDOUT, cwd=REPO).returncode
    # copy best solution out of the AIDE workdir for provenance
    wd = Path(os.path.expanduser(f"~/frontier/gen_logs/frontier_{p}_aide_aide/solution.cpp"))
    if wd.exists():
        (Path(f"{GATES}/solutions") / f"p{p}.aide.cpp").write_text(wd.read_text())
    print(f"=== [{time.strftime('%H:%M')}] DONE p{p} rc={rc} ===", flush=True)

print("ALLDONE_AIDE", flush=True)
