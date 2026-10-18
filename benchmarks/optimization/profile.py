"""cProfile of one Nous campaign, written as JSON beside the benchmark.

    .venv/bin/python -m benchmarks.optimization.profile                  # sparse_knobs_12, seed 1, x1
    .venv/bin/python -m benchmarks.optimization.profile --surface bowl

Writes ``docs/benchmarks/optimization-benchmark-profile.json``: the code
digests, the campaign's CPU under the profiler, and the top cumulative Nous
functions. Run it under the heavy wrapper (one campaign, about 100 s).
"""
from __future__ import annotations

import argparse
import cProfile
import json
import logging
import pstats
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.optimization import run as R  # noqa: E402

MODULES = ("certificate.py", "adequacy.py", "stage_runner.py", "effects.py", "decide.py")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--surface", default="sparse_knobs_12")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mult", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=R.DEFAULT_OUT / "optimization-benchmark-profile.json")
    a = ap.parse_args(argv)
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as d:
        pr = cProfile.Profile()
        pr.enable()
        r = R.run_nous(a.surface, a.mult, a.seed, d)
        pr.disable()
    rows = []
    for (fn, ln, name), (_cc, nc, tt, ct, _callers) in pstats.Stats(pr).stats.items():
        if Path(fn).name in MODULES:
            rows.append({"function": f"{Path(fn).name}:{name}", "line": ln, "calls": nc,
                         "tottime_s": round(tt, 2), "cumtime_s": round(ct, 2)})
    rows.sort(key=lambda x: -x["cumtime_s"])
    out = {"what": f"cProfile of one {a.surface} campaign (seed {a.seed}, noise x{a.mult:g})",
           "nous_digest": R._nous_digest(), "bench_digest": R._bench_digest(),
           "campaign_cpu_s_under_profiler": round(r["cpu_s"], 2), "budget": r["budget"],
           "top_cumulative": rows[:15]}
    a.out.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
