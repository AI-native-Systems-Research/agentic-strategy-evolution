#!/usr/bin/env python3
"""Conclude a (wedged, near-cap) Claude run: re-judge its persisted artifacts on our go-judge and write
pred.json with the best REPRODUCIBLE score. Used when a run can't cleanly reach $50 because the gateway
is wedging it near the cap -- we bank the best score we can reproduce from a saved .cpp (<= $50 rule).

Usage: python conclude_run.py <pid> <run_dir>
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

pid = int(sys.argv[1]); run = sys.argv[2]
FR = os.path.expanduser("~/frontier/Frontier-CS"); FEVAL = FR + "/.venv/bin/frontier"


def judge(cpp, tries=5):
    for _ in range(tries):
        try:
            r = subprocess.run(f"{FEVAL} eval algorithmic {pid} {cpp} --json", shell=True,
                               capture_output=True, text=True, cwd=FR, timeout=600)
        except Exception:
            time.sleep(3); continue
        m = re.findall(r'"score"\s*:\s*([0-9.]+)', r.stdout + r.stderr)
        if m:
            return max(map(float, m))
        time.sleep(3)
    return None


best = -1.0; bestf = None; ev = []
for f in sorted(glob.glob(run + "/trials/*.cpp")) + [run + "/solution.cpp"]:
    if not os.path.exists(f):
        continue
    s = judge(f); ev.append({"file": os.path.basename(f), "rejudged_score": s})
    if s is not None and s > best:
        best = s; bestf = f

claimed = []
try:
    for l in open(run + "/stream.jsonl", errors="ignore"):
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("type") == "user":
            for c in (d.get("message", {}).get("content") or []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    s = c.get("content"); s = s if isinstance(s, str) else json.dumps(s)
                    claimed += [float(x) for x in re.findall(r"SCORE:\s*([0-9.]+)", s)]
except Exception:
    pass
acb = max(claimed) if claimed else None

# cheat audit (isolation check)
testd = 0; den = 0
try:
    for l in open(run + "/stream.jsonl", errors="ignore"):
        if "not permitted" in l.lower():
            den += 1
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("type") == "assistant":
            for c in d.get("message", {}).get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use" and \
                        re.search(r"testdata|/problems/\d+/testdata|\.ans\b", json.dumps(c.get("input", {}))):
                    testd += 1
except Exception:
    pass

cost = None
try:
    t = open("/tmp/p%d_claude.out" % pid).read()
    mm = re.findall(r"cost=\$([0-9.]+)", t); cost = float(mm[-1]) if mm else None
except Exception:
    pass

json.dump(ev, open(run + "/trials_rejudged.json", "w"), indent=2)
pred = {
    "pid": pid, "agent": "claude-code", "model": "claude-opus-4-6",
    "valid": (testd == 0),
    "final_score": (round(best, 2) if best >= 0 else None),
    "reproduced_best": (round(best, 2) if best >= 0 else None),
    "agent_claimed_best": acb,
    "repro_gap": (round(acb - best, 3) if (acb and best >= 0 and acb > best) else 0.0),
    "cost_est_cacheaware": cost, "stop_reason": "concluded_wedged_near_cap",
    "budget": 50.0, "max_score": 100.0,
    "best_file": (os.path.basename(bestf) if bestf else None),
    "n_trials_rejudged": len(ev),
    "cheat_audit_hits": (["testdata_access:%d" % testd] if testd else []),
    "cheat_audit_note": "testdata tool-calls=%d, permission-denied=%d" % (testd, den),
    "isolation": "sandbox-exec(deny ~/frontier)+judge-daemon",
    "run_dir": os.path.abspath(run),
}
json.dump(pred, open(run + "/pred.json", "w"), indent=2)
print("concluded p%d final=%s cost=%s audit=%s" % (pid, pred["final_score"], cost,
      "CLEAN" if testd == 0 else "CHEAT:%d" % testd))
