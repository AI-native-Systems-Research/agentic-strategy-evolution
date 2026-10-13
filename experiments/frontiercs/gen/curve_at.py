#!/usr/bin/env python3
"""Best clean measured score at given spend levels: archive file times joined with the run log's cost lines.

usage: curve_at.py <run.log> <measured_dir> [marks...]   (log lines: '[rcap HH:MM:SS] ... cost=$x' or '[csdk HH:MM:SS] cost=$x')
"""
import glob, re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))


def curve(log, mdir, marks=(10, 25, 50), pid=None):
    pts = [(m.group(1), float(m.group(2))) for l in open(log)
           if (m := re.search(r"\[(?:rcap|csdk) (\d\d:\d\d:\d\d)\].*?cost=\$([0-9.]+)", l))]
    hooked = set()
    if pid:
        import nous_research_isolated as N
        hooked = {f for f in glob.glob(mdir + "/*") if N.exploit_hits(open(f, errors="ignore").read(), pid)}
    files = [(m.group(1)[:2] + ":" + m.group(1)[2:4] + ":" + m.group(1)[4:], float(m.group(2)))
             for f in glob.glob(mdir + "/*") if f not in hooked and (m := re.search(r"_(\d{6})_score([0-9.]+)\.", f))]
    out = {}
    for mk in marks:
        t = next((ts for ts, c in pts if c >= mk), None)
        out[mk] = max([s for ts, s in files if t is None or ts <= t], default=0.0)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    print(curve(a[0], a[1], tuple(float(x) for x in a[2:]) or (10, 25, 50)))
