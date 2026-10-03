#!/usr/bin/env python3
"""One resume attempt for the 3 new-task Nous campaigns (p26/p69/p79), in parallel.
They wedged at iter-1 DESIGN (intermittent SDK streaming hang); a fresh resume may stream.
Logs -> /tmp/nous_resume_p{P}.log. Harvest handled separately.
"""
import os, subprocess, time

NOUS_BIN = os.path.expanduser("~/nous_repo/.venv/bin/nous")
NOUS_REPO = os.path.expanduser("~/nous_repo")
GL = os.path.expanduser("~/frontier/gen_logs")
TASKS = [26, 69, 79]

env = dict(os.environ)
env["ANTHROPIC_BASE_URL"] = env.get("OPENAI_BASE_URL", "")
env["ANTHROPIC_API_KEY"] = env.get("OPENAI_API_KEY", "")
env["NOUS_CAMPAIGN_PARENT"] = f"{GL}/nous_runs"
for k in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
          "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
    env[k] = "1"


def launch(p):
    lf = open(f"/tmp/nous_resume_p{p}.log", "w")
    camp = f"{GL}/campaign_{p}.yaml"
    print(f"=== [{time.strftime('%H:%M')}] RESUME nous p{p} ===", flush=True)
    return subprocess.Popen(
        [NOUS_BIN, "resume", camp, "--auto-approve", "--agent", "sdk",
         "--max-iterations", "12", "--timeout", "2400"],
        stdout=lf, stderr=subprocess.STDOUT, cwd=NOUS_REPO, env=env)

procs = {launch(p): p for p in TASKS}
while any(pr.poll() is None for pr in procs):
    time.sleep(10)
for pr, p in procs.items():
    print(f"=== [{time.strftime('%H:%M')}] DONE resume p{p} rc={pr.returncode} ===", flush=True)
print("ALLDONE_NOUS_RESUME", flush=True)
