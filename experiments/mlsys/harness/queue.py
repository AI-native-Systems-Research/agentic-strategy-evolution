"""Run a list of cells across the 5 LLM key slots, one cell per slot at a time.

  queue.py <cells_file>      one cell per line: "<task> <arm> <rep>"; lines starting with # are skipped

Arms are interleaved in the cells file so no arm systematically gets a faster or slower slot. A cell whose run dir
already has oracle.json is skipped (restart-safe).
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = Path.home() / "mlsys_runs" / "runs"
LOG = Path.home() / "mlsys_runs" / "launch"
N_SLOTS = 5


def main(cells_file):
    LOG.mkdir(parents=True, exist_ok=True)
    cells = [l.split() for l in Path(cells_file).read_text().splitlines() if l.strip() and not l.startswith("#")]
    pending = [c for c in cells if not (RUNS / c[0] / c[1] / f"rep{c[2]}" / "oracle.json").exists()]
    running = {}
    while pending or running:
        for s, (p, c) in list(running.items()):
            if p.poll() is not None:
                print(time.strftime("%H:%M:%S"), "done", " ".join(c), "rc", p.returncode, flush=True)
                del running[s]
        for s in range(N_SLOTS):
            if s not in running and pending:
                c = pending.pop(0)
                lf = open(LOG / f"{c[0]}_{c[1]}_{c[2]}.log", "w")
                running[s] = (subprocess.Popen([sys.executable, str(HERE / "run_one.py"), c[0], c[1], c[2], str(s)],
                                               stdout=lf, stderr=subprocess.STDOUT, cwd=str(HERE)), c)
                print(time.strftime("%H:%M:%S"), "start", " ".join(c), "slot", s, flush=True)
        time.sleep(20)
    print(time.strftime("%H:%M:%S"), "queue empty", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
