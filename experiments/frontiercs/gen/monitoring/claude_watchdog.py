#!/usr/bin/env python3
"""Watchdog for Claude-agent (single_agent) gate runs. Stop: plateau(internal patience) / $50 / ceiling.
- cost >= $50 -> kill (single_agent writes usage periodically, so this is enforceable mid-run)
- best >= 99.5 -> ceiling, kill
- plateau handled internally by --early_stop_patience 3.
"""
import glob, json, os, re, subprocess
CAP = 50.0; CEIL = 99.5
TASKS = ["0", "5", "9", "15", "22"]
RES = os.path.expanduser("~/engram_repo/results")


def tree_kill(pat):
    """Kill matching procs AND their descendants (children first) so multiprocessing
    spawn workers don't orphan and keep running/burning."""
    mains = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True).stdout.split()
    for mp in mains:
        kids = subprocess.run(["pgrep", "-P", mp], capture_output=True, text=True).stdout.split()
        for k in kids:
            gks = subprocess.run(["pgrep", "-P", k], capture_output=True, text=True).stdout.split()
            for g in gks:
                subprocess.run(["kill", "-9", g])
            subprocess.run(["kill", "-9", k])
        subprocess.run(["kill", "-9", mp])
parts = []
for p in TASKS:
    log = f"/tmp/claude_fcs{p}_real.log"
    if not os.path.exists(log):
        continue
    up = subprocess.run(["pgrep", "-f", f"single_agent_example_usage.py --problem_name fcs_alg_{p} "],
                        capture_output=True).returncode == 0
    txt = open(log, errors="ignore").read()
    bests = re.findall(r"New best score: ([0-9.]+)", txt)
    best = float(bests[-1]) if bests else None
    # scope usage to the NEWEST run dir only (old leaked run dirs have stale $ that would false-trigger)
    rds = sorted(glob.glob(f"{RES}/single_agent_fcs_alg_{p}_*/"), key=os.path.getmtime)
    spend = None
    if rds:
        us = sorted(glob.glob(f"{rds[-1]}/FrontierCS/logs/*usage_stats*.json"), key=os.path.getmtime)
        if us:
            try:
                spend = float(json.load(open(us[-1])).get("total_cost") or 0)
            except Exception:
                spend = None
    # elapsed seconds of the running proc (for the usage-less wall-clock proxy)
    el = subprocess.run(["pgrep", "-f", f"single_agent_example_usage.py --problem_name fcs_alg_{p} "],
                        capture_output=True, text=True)
    elapsed = None
    if el.stdout.strip():
        pid0 = el.stdout.split()[0]
        es = subprocess.run(["ps", "-o", "etime=", "-p", pid0], capture_output=True, text=True).stdout.strip()
        # macOS etime: [[DD-]HH:]MM:SS
        m = re.match(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)", es)
        if m:
            d,h,mi,se = (int(x) if x else 0 for x in m.groups())
            elapsed = ((d*24+h)*60+mi)*60+se
    status = "UP" if up else "DOWN"
    if up:
        reason = None
        if spend is not None and spend >= CAP:
            reason = f"cost${spend:.0f}"
        elif best is not None and best >= CEIL:
            reason = "ceiling"
        elif spend is None and elapsed is not None and elapsed > 720:
            reason = f"walltime{elapsed//60}min~$50proxy"
        if reason:
            tree_kill(f"single_agent_example_usage.py --problem_name fcs_alg_{p} ")
            status = f"KILLED({reason})"
    parts.append(f"p{p}:{status} best={best} ${spend}")
print("[cwd] " + "  ".join(parts))
if subprocess.run(["pgrep", "-f", "single_agent_example_usage.py"], capture_output=True).returncode != 0:
    print("ALLDONE")
