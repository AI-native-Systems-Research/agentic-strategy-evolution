#!/usr/bin/env python3
"""Re-derive Engram 'best score at <= $50 spend' from existing data (no rerun).
Per task: total cost + #agents -> budget_agents k = max(1, floor(50/(total/agents))).
Then re-score (our judge) every C++ snapshot belonging to the first k agents and take the max.
Agents are the per-agent workspace dirs (oldest = agent 1) + knowledgebase/agent_i snapshots.
"""
import glob, json, math, os, re, subprocess
FR = os.path.expanduser("~/frontier/Frontier-CS"); FEVAL = f"{FR}/.venv/bin/frontier"
RES = os.path.expanduser("~/engram_repo/results")
TASKS = ["0", "5", "9", "15", "22"]

def jscore(pid, f):
    try:
        r = subprocess.run([FEVAL, "eval", "algorithmic", pid, f, "--json"], capture_output=True, text=True, cwd=FR, timeout=240)
    except Exception: return None
    m = re.findall(r'"score"\s*:\s*([0-9.]+)', r.stdout + r.stderr)
    return float(m[-1]) if m else None

for p in TASKS:
    rds = sorted(glob.glob(f"{RES}/handoff_fcs_alg_{p}_model*/"), key=os.path.getmtime)
    if not rds: print(f"p{p}: no run"); continue
    rd = rds[-1]
    us = glob.glob(f"{rd}/FrontierCS/logs/*usage_stats*.json")
    total = round(float(json.load(open(us[0])).get("total_cost") or 0), 2) if us else None
    # count agents from knowledgebase dirs (fallback: handoff log 'Starting Agent')
    agents = len(glob.glob(f"{rd}/FrontierCS/workspace/*/knowledgebase/agent_*"))
    if agents == 0:
        log = f"/tmp/engram_fcs{p}_real.log"
        agents = max(1, open(log).read().count("Starting Agent")) if os.path.exists(log) else 1
    per = (total / agents) if (total and agents) else total
    kbud = max(1, math.floor(50.0 / per)) if per else agents
    # agent workspaces oldest-first; first kbud are within budget
    wss = sorted(glob.glob(f"{rd}/FrontierCS/workspace/*/"), key=os.path.getmtime)
    # collect candidate cpps from the first kbud agent-workspaces + their experiments/knowledgebase
    cands = set()
    for ws in wss[:kbud] if len(wss) >= kbud else wss:
        cands |= set(glob.glob(f"{ws}/**/*.cpp", recursive=True))
    # also knowledgebase/agent_0..agent_{kbud-1}
    for i in range(kbud):
        cands |= set(glob.glob(f"{rd}/FrontierCS/workspace/*/knowledgebase/agent_{i}/**/*.cpp", recursive=True))
    cands = [c for c in cands if os.path.getsize(c) > 0 and "initial_program" not in c]
    best = -1.0
    for c in cands:
        s = jscore(p, c)
        if s is not None and s > best: best = s
    print(f"p{p}: total=${total} agents={agents} ~$/agent={round(per,1) if per else '?'} budget_agents={kbud} "
          f"best@<=$50={best if best>=0 else 'n/a'} (cands={len(cands)})", flush=True)
