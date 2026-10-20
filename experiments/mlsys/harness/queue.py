"""Run a list of cells across the 5 LLM key slots, one cell per slot at a time.

  queue.py <cells_file> [slots]   slots: comma list of key slots to use (default all 5); one cell per line: "<task> <arm> <rep>"; lines starting with # are skipped

Arms are interleaved in the cells file so no arm systematically gets a faster or slower slot. A cell whose run dir
already has oracle.json is skipped (restart-safe).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = Path.home() / "mlsys_runs" / "runs"
LOG = Path.home() / "mlsys_runs" / "launch"
N_SLOTS = 5


def main(cells_file, slots):
    LOG.mkdir(parents=True, exist_ok=True)
    cells = [l.split() for l in Path(cells_file).read_text().splitlines() if l.strip() and not l.startswith("#")]
    def live(c):
        """A cell already running elsewhere (another queue): (True, its slot)."""
        m = RUNS / c[0] / c[1] / f"rep{c[2]}" / "RUNNING"
        try:
            d = json.loads(m.read_text())
            os.kill(d["pid"], 0)
            return True, d["slot"]
        except (OSError, ValueError, KeyError):
            return False, None

    done = lambda c: (RUNS / c[0] / c[1] / f"rep{c[2]}" / "oracle.json").exists()
    pending = [c for c in cells if not done(c)]
    running = {}
    while pending or running:
        external = {}  # cells started by another queue: skip them, and treat their key slot as busy
        for c in pending:
            on, sl = live(c)
            if on:
                external[sl] = c
        pending = [c for c in pending if not done(c)]
        for s, (p, c) in list(running.items()):
            if p.poll() is not None:
                print(time.strftime("%H:%M:%S"), "done", " ".join(c), "rc", p.returncode, flush=True)
                del running[s]
        for s in slots:
            todo = [c for c in pending if c not in external.values()]
            if s not in running and s not in external and todo:
                c = todo[0]
                pending.remove(c)
                lf = open(LOG / f"{c[0]}_{c[1]}_{c[2]}.log", "w")
                running[s] = (subprocess.Popen([sys.executable, str(HERE / "run_one.py"), c[0], c[1], c[2], str(s)],
                                               stdout=lf, stderr=subprocess.STDOUT, cwd=str(HERE)), c)
                print(time.strftime("%H:%M:%S"), "start", " ".join(c), "slot", s, flush=True)
        time.sleep(20)
    print(time.strftime("%H:%M:%S"), "queue empty", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else list(range(N_SLOTS)))
