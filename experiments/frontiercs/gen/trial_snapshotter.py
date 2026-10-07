#!/usr/bin/env python3
"""Evidence snapshotter: persist every distinct solution.cpp a Claude run produces, and INDEPENDENTLY
re-judge each on our go-judge, so every score is backed by a saved artifact we can re-score later.

This is deliberately read-only w.r.t. the runner (it only reads solution.cpp and writes into a
`trials/` sibling dir), so it can watch an in-flight run without disturbing it. For future runs the
same logic should live in claude_code_runner.py.

Writes:
  <run_dir>/trials/t<seq>_<score>.cpp     (a copy of solution.cpp at the moment it was scored)
  <run_dir>/trials_evidence.jsonl         ({seq, ts, sha12, bytes, score} per distinct solution)

Usage:
  python3 trial_snapshotter.py <pid> <run_dir> [--interval 45]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")


def judge(pid, sol_path):
    try:
        r = subprocess.run(f"{FEVAL} eval algorithmic {pid} {sol_path} --json",
                           shell=True, capture_output=True, text=True, cwd=FRONTIER, timeout=600)
    except Exception:
        return None
    best = None
    for m in re.findall(r'"score"\s*:\s*([0-9.]+)', r.stdout + r.stderr):
        v = float(m); best = v if best is None else max(best, v)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int)
    ap.add_argument("run_dir")
    ap.add_argument("--interval", type=float, default=45.0)
    args = ap.parse_args()
    run = Path(args.run_dir)
    sol = run / "solution.cpp"
    tdir = run / "trials"; tdir.mkdir(exist_ok=True)
    log = run / "trials_evidence.jsonl"
    seen = set()
    seq = 0
    while True:
        try:
            data = sol.read_bytes() if sol.exists() else b""
        except Exception:
            data = b""
        sha = hashlib.sha256(data).hexdigest()[:12] if data else None
        # only score a solution that is new and non-placeholder
        if sha and sha not in seen and len(data) > 60:
            seen.add(sha)
            # copy first (freeze the artifact), then judge the frozen copy
            tmp = tdir / f"t{seq:03d}_pending.cpp"
            tmp.write_bytes(data)
            score = judge(args.pid, str(tmp))
            final = tdir / f"t{seq:03d}_score{('ERR' if score is None else format(score,'g'))}.cpp"
            tmp.rename(final)
            row = {"seq": seq, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "sha12": sha, "bytes": len(data), "score": score, "file": final.name}
            with open(log, "a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"[snap p{args.pid}] seq={seq} score={score} bytes={len(data)} -> {final.name}",
                  flush=True)
            seq += 1
        # stop when the run has finished (pred.json written) and we've captured the final file
        if (run / "pred.json").exists():
            time.sleep(args.interval)
            # one last capture already handled above; exit after a grace pass
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
