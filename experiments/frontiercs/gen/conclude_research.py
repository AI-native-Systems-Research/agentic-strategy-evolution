#!/usr/bin/env python3
"""Conclude a (wedged, near-cap) research run: re-judge persisted solution.py attempts via the local
evaluator and write pred.json with the best (lowest total_cost) reproducible result.
Usage: python conclude_research.py <pid> <run_dir>
"""
import glob, json, os, re, shlex, subprocess, sys, tempfile
from pathlib import Path

FR = os.path.expanduser("~/frontier/Frontier-CS")
pid = sys.argv[1]; run = sys.argv[2]
pd = Path(FR) / "research" / "problems" / pid


def judge(sol):
    evalpy = pd / ".evalvenv" / "bin" / "python3"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    try:
        subprocess.run(f"{shlex.quote(str(evalpy))} {shlex.quote(str(pd/'evaluator.py'))} "
                       f"--solution {shlex.quote(sol)} --spec {shlex.quote(str(pd/'resources'/'submission_spec.json'))} "
                       f"--out {shlex.quote(out)}", shell=True, capture_output=True, text=True, timeout=900, cwd=str(pd))
        try: data = json.loads(Path(out).read_text())
        except Exception: return None, None
    finally:
        try: os.unlink(out)
        except OSError: pass
    if data.get("error") or data.get("runs_successfully", 0.0) != 1.0:
        return 0.0, data.get("total_cost")
    return float(data.get("score", 0.0)), data.get("total_cost")


ev = []; bscore = -1.0; bcost = None; bfile = None
for f in sorted(glob.glob(run + "/trials/*.py")) + [run + "/solution.py"]:
    if not os.path.exists(f): continue
    s, c = judge(f); ev.append({"file": os.path.basename(f), "rejudged_score": s, "total_cost": c})
    if s is not None and s > bscore: bscore = s; bcost = c; bfile = f
tx = ""
for g in glob.glob(run + "/cfg/projects/**/*.jsonl", recursive=True):
    tx += open(g, errors="ignore").read()
flags = sorted(set(re.findall(r"testdata|\.ans\b|gen_logs|nous_runs|research/solutions", tx)))
cost = None
try:
    t = open("/tmp/%s_claude.out" % pid).read(); mm = re.findall(r"cost=\$([0-9.]+)", t); cost = float(mm[-1]) if mm else None
except Exception: pass
json.dump(ev, open(run + "/trials_rejudged.json", "w"), indent=2)
pred = {"pid": pid, "track": "research", "agent": "claude-code", "model": "claude-opus-4-6",
        "metric": "total_cost ($) lower=better", "valid": (not flags),
        "final_total_cost": bcost, "final_score": (round(bscore, 4) if bscore >= 0 else None),
        "cost_est_cacheaware": cost, "stop_reason": "concluded_wedged_near_cap",
        "best_file": (os.path.basename(bfile) if bfile else None), "n_trials_rejudged": len(ev),
        "cheat_audit_hits": flags, "run_dir": os.path.abspath(run)}
json.dump(pred, open(run + "/pred.json", "w"), indent=2)
print("concluded %s total_cost=%s score=%s audit=%s" % (pid, bcost, bscore, "CLEAN" if not flags else flags))
