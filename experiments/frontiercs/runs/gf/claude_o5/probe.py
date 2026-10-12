"""Harness: write solution.py from a statement list, measure, and back out the
exact weighted coverage w from the score.

score = 0.7 * (w/100)^3 * 100 + 30 * 2^(-N/50)
"""
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SOL = os.path.join(BASE, "solution.py")
MEASURE = os.path.join(BASE, "measure.sh")

TEMPLATE = """STATEMENTS = {lit}


class Solution:
    def solve(self, resources_path: str) -> list[str]:
        return list(STATEMENTS)
"""


def build(stmts, path=SOL):
    with open(path, "w") as f:
        f.write(TEMPLATE.format(lit=json.dumps(list(stmts), indent=4)))


def measure(path=SOL):
    r = subprocess.run(["bash", MEASURE, path], capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        if line.strip().startswith("SCORE:"):
            return float(line.split(":", 1)[1])
    raise RuntimeError("no score: " + repr(r.stdout) + repr(r.stderr))


def w_from(score, n):
    eff = 30.0 * 2.0 ** (-n / 50.0)
    cov = (score - eff) / 0.7
    if cov <= 0:
        return float("nan")
    return 100.0 * (cov / 100.0) ** (1.0 / 3.0)


def run(stmts, label=""):
    build(stmts)
    s = measure()
    n = len(stmts)
    w = w_from(s, n)
    print("%-28s N=%3d SCORE=%10.5f  w=%8.4f%%" % (label, n, s, w))
    return s, w


if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    run(data, sys.argv[2] if len(sys.argv) > 2 else "")
