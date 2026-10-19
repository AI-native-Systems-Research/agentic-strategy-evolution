"""Replay the v8 effort rule over finished runs' logs: which sessions it would run at which effort.

For each task's run: metrics rows give the sessions and their time windows; transcripts give each reply cut at
the output limit (stop_reason max_tokens). Prints per session the effort the rule picks and marks cut sessions.
Usage: python gen/replay_effort_ladder.py [slug-suffix, default v8c50]
"""
import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from orchestrator.effort import LEVELS, SETUP_LABELS, model_default  # noqa: E402

G = "/Users/toslali/frontier/gen_logs"
BASE = os.path.expanduser("~/.claude/projects")
SUFFIX = sys.argv[1] if len(sys.argv) > 1 else "v8c50"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def rule(label, model, step_down):
    normal = model_default(model)
    if label in SETUP_LABELS:
        normal = LEVELS[min(LEVELS.index(normal), LEVELS.index("medium"))]
    floor = min(LEVELS.index(normal), LEVELS.index("medium"))
    return LEVELS[max(floor, LEVELS.index(normal) - step_down)]


for p in ("0", "5", "26", "58", "181"):
    slug = f"p{p}-{SUFFIX}"
    cuts = []
    for d in glob.glob(f"{BASE}/-Users-toslali-frontier-gen-logs-research-{slug}-ws*"):
        if f"{SUFFIX}r" in d:
            continue
        for f in glob.glob(d + "/*.jsonl"):
            for line in open(f):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                m = r.get("message")
                if isinstance(m, dict) and m.get("stop_reason") == "max_tokens":
                    cuts.append(ts(r["timestamp"]))
    cuts = sorted(set(cuts))
    mf = f"{G}/nous_runs/research-{slug}/llm_metrics.jsonl"
    if not os.path.exists(mf):
        continue
    rows = [json.loads(x) for x in open(mf) if x.strip()]
    out = []
    for r in (x for x in rows if x.get("dispatcher") == "sdk"):
        end = ts(r["timestamp"])
        start = end - (r.get("duration_ms") or 0) / 1000
        label = r.get("session_label") or r.get("phase")
        eff = rule(label, r.get("model"), sum(1 for c in cuts if c < start))
        out.append((label, eff, any(start <= c <= end for c in cuts)))
    changed = sum(1 for _, e, _ in out if e != "high")
    print(f"p{p}: {len(out)} sessions, {changed} not at high, {len(cuts)} cut replies")
    print("   " + " ".join(f"{a}:{e}{'(CUT)' if c else ''}" for a, e, c in out))
