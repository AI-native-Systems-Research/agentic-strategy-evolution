#!/usr/bin/env python3
"""Out-of-sandbox judge daemon for the isolated Claude/Nous arena.

WHY: a bash-enabled agent on a shared filesystem can read the judge's hidden testdata/answers by
absolute path (observed: p0 ran `ls ~/frontier/.../testdata` and `head 1.ans`). We now run the agent
under sandbox-exec with reads of ~/frontier DENIED, so it cannot touch testdata. But the agent still
needs to score itself -- so scoring is done HERE, in a daemon that runs OUTSIDE the sandbox and does
have testdata access. The agent's measure.sh only drops solution.cpp into the inbox and reads back a
SCORE; it never sees a testdata path.

Protocol (plain files, no network):
  agent writes   <INBOX>/p<pid>__<token>.cpp
  daemon writes  <OUTBOX>/p<pid>__<token>.score   containing a line "SCORE: <0-100>"
  daemon moves   the .cpp into <DONE>/ after scoring

Start once (outside any sandbox), leave running:
  python3 judge_server.py            # defaults to /tmp/fcs_judge
"""
import argparse
import os
import re
import subprocess
import time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")
NAME_RE = re.compile(r"^p(\d+)__")


def judge(pid, cpp):
    try:
        r = subprocess.run(f"{FEVAL} eval algorithmic {pid} {cpp} --json",
                           shell=True, capture_output=True, text=True, cwd=FRONTIER, timeout=600)
    except Exception as e:
        return None, f"judge-exc:{type(e).__name__}"
    best = None
    for m in re.findall(r'"score"\s*:\s*([0-9.]+)', r.stdout + r.stderr):
        v = float(m); best = v if best is None else max(best, v)
    return best, ("ok" if best is not None else "no-score")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp/fcs_judge")
    ap.add_argument("--poll", type=float, default=0.4)
    args = ap.parse_args()
    root = Path(args.root)
    inbox = root / "inbox"; outbox = root / "outbox"; done = root / "done"
    for d in (inbox, outbox, done):
        d.mkdir(parents=True, exist_ok=True)
    print(f"[judge] watching {inbox} -> {outbox}  (frontier={FRONTIER})", flush=True)
    while True:
        for cpp in sorted(inbox.glob("p*__*.cpp")):
            m = NAME_RE.match(cpp.name)
            if not m:
                cpp.unlink(missing_ok=True); continue
            pid = int(m.group(1))
            score, status = judge(pid, str(cpp))
            token = cpp.stem  # p<pid>__<token>
            (outbox / f"{token}.score").write_text(
                f"SCORE: {score if score is not None else 'ERR'}\n")
            try:
                cpp.rename(done / cpp.name)
            except Exception:
                cpp.unlink(missing_ok=True)
            print(f"[judge] {token} pid={pid} score={score} ({status})", flush=True)
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
