#!/usr/bin/env python3
import glob, json, os, re, subprocess, time

GATES = "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/experiments/frontiercs/aide_gates"
TASKS = [0, 5, 9, 15, 22]
NOUS = {0: 86, 5: 83, 9: 100, 15: 100, 22: 100}
ENGRAM = {0: 70.0, 5: 49.0, 9: 55.0, 15: 20.0, 22: 0.0}
CLAUDE = {0: "~26", 5: "~39", 9: 80, 15: 0, 22: 0}

up = subprocess.run(["pgrep", "-f", "aide_run_par.py"], capture_output=True).returncode == 0 or \
     subprocess.run(["pgrep", "-f", "aide_frontier.py"], capture_output=True).returncode == 0
done = os.path.exists("/tmp/aide_run_all.log") and "ALLDONE_AIDE" in open("/tmp/aide_run_all.log").read()
print(f"=== [{time.strftime('%H:%M')}] AIDE run: {'RUNNING' if up else ('DONE' if done else 'STOPPED')} ===")
print(f"{'task':5} {'AIDE step/best/cost':26} {'final':7} {'| Nous':7} {'Engram':7} {'Claude':7}")
for p in TASKS:
    log = f"/tmp/aide_p{p}.log"
    step = best = cost = None
    if os.path.exists(log):
        txt = open(log, errors="ignore").read()
        rows = re.findall(r"\[step (\d+)/\d+\].*?best=([0-9.]+|None) cost=\$([0-9.]+)", txt)
        if rows:
            step, best, cost = rows[-1]
    pred = f"{GATES}/preds/p{p}.aide.json"
    final = None
    if os.path.exists(pred):
        try:
            d = json.load(open(pred)); final = d.get("final_score"); cost = cost or d.get("final_cost_usd")
        except Exception:
            pass
    live = f"s{step} best={best} ${cost}" if step else ("done" if final is not None else "pending")
    print(f"p{p:<4} {live:26} {str(final):7} | {str(NOUS[p]):5} {str(ENGRAM[p]):7} {str(CLAUDE[p]):7}")
print("(AIDE/Nous/Engram/Claude = best score on OUR judge @ <=$50; stop=$50 or ceiling)")
