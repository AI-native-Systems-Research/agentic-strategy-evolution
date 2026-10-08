#!/usr/bin/env python3
"""Out-of-sandbox judge daemon for the RESEARCH track (cloudcast): evaluates a submitted solution.py
via the problem's own local evaluator (.evalvenv/bin/python3 evaluator.py), returning the score and the
headline metric total_cost (lower = better; score = 100/(1+total_cost)).

Mirrors judge_server.py but for research: the sandboxed agent cannot read ~/frontier (hides the
reference solutions + evaluator), so it drops solution.py here and reads back SCORE + COST.

Protocol:
  agent writes   <INBOX>/<pid>__<token>.py
  daemon writes  <OUTBOX>/<pid>__<token>.score  containing "SCORE: <score>\nCOST: <total_cost>"
Start once (outside sandbox): python3 research_judge_server.py
"""
import glob
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

FR = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
NAME_RE = re.compile(r"^([a-zA-Z0-9_]+)__")


def probdir(pid):
    return Path(FR) / "research" / "problems" / pid


def evaluate(pid, sol_path, timeout=900):
    pd = probdir(pid)
    evalpy = pd / ".evalvenv" / "bin" / "python3"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    try:
        subprocess.run(
            f"{shlex.quote(str(evalpy))} {shlex.quote(str(pd / 'evaluator.py'))} "
            f"--solution {shlex.quote(str(sol_path))} "
            f"--spec {shlex.quote(str(pd / 'resources' / 'submission_spec.json'))} "
            f"--out {shlex.quote(out)}", shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(pd))
        try:
            data = json.loads(Path(out).read_text())
        except Exception:
            return None, None
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass
    if data.get("error") or data.get("runs_successfully", 0.0) != 1.0:
        return 0.0, data.get("total_cost")
    return float(data.get("score", 0.0)), data.get("total_cost")


def main():
    root = Path("/tmp/fcs_rjudge")
    inbox = root / "inbox"; outbox = root / "outbox"; done = root / "done"
    for d in (inbox, outbox, done):
        d.mkdir(parents=True, exist_ok=True)
    print(f"[rjudge] watching {inbox} (frontier={FR})", flush=True)
    while True:
        for sol in sorted(inbox.glob("*__*.py")):
            m = NAME_RE.match(sol.name)
            if not m:
                sol.unlink(missing_ok=True); continue
            pid = m.group(1)
            score, cost = evaluate(pid, str(sol))
            token = sol.stem
            sc = "ERR" if score is None else score
            co = "ERR" if cost is None else cost
            (outbox / f"{token}.score").write_text(f"SCORE: {sc}\nCOST: {co}\n")
            try:
                sol.rename(done / sol.name)
            except Exception:
                sol.unlink(missing_ok=True)
            print(f"[rjudge] {token} pid={pid} score={score} cost={cost}", flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
