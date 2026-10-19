"""Print one line per run: task/arm/rep, state, cost so far, last LLM call, iterations, oracle O1 if scored."""
import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cost_meter  # noqa: E402

RUNS = Path.home() / "mlsys_runs" / "runs"
total = 0.0
for d in sorted(glob.glob(str(RUNS / "*" / "*" / "rep*"))):
    d = Path(d)
    tag = "/".join(d.parts[-3:])
    camp = d / "nous_work"
    c = cost_meter.run_cost(str(d / "claude_cfg"), str(camp) if camp.exists() else None)["total"]
    total += c
    last = ""
    pl = d / "logs" / "proxy.log"
    if pl.exists():
        age = time.time() - pl.stat().st_mtime
        last = f"last call {age/60:.0f}m ago"
    if (d / "oracle.json").exists():
        o = json.load(open(d / "oracle.json"))
        state = f"SCORED O1={o.get('O1')} status={o.get('status')} iters={o.get('E1_iterations')}"
    elif (d / "meta.json").exists():
        state = "scoring"
    else:
        n = len(glob.glob(str(d / "logs" / "session-*.jsonl"))) or len(glob.glob(str(camp / "*" / "runs" / "iter-*")))
        state = f"running iter/session {n}"
    print(f"{tag:28s} ${c:7.2f}  {state:48s} {last}")
print(f"{'TOTAL':28s} ${total:7.2f}")
