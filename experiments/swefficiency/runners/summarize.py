"""Summarize SWE-fficiency head-to-head from per-task validation reports.
Run from ~/nous_swe/swefficiency. Usage: python summarize.py <iid1> <iid2> ...
Reads g_/c_/n_<iid> runs; SR = raw_speedup/gold_speedup if correctness==100%, else nullified (1.0)."""
import collections, glob, json, sys


def load(run):
    fs = glob.glob(f"logs/run_evaluation/{run}/*/validation_report_{run}.json")
    if not fs:
        return None
    d = json.load(open(fs[0]))
    k = list(d)[0]
    p = d[k].get("perf_report") or {}
    cr = d[k].get("correctness_report") or {}
    c = collections.Counter((cr.get("test_results") or {}).values())
    return {
        "impr": p.get("improvement"),
        "cpct": cr.get("correctness_pct"),
        "failed": c.get("FAILED", 0),
        "passed": c.get("PASSED", 0),
    }


def sr(pred, gold):
    if not pred or not gold or not pred.get("impr") or not gold.get("impr"):
        return None
    correct = (pred.get("cpct") or 0) >= 0.999
    return round(pred["impr"] / gold["impr"], 3) if correct else 1.0  # nullified if not 100%


def main():
    tasks = sys.argv[1:]
    print(f"{'task':<28} {'gold_x':>7} | {'claude_raw':>10} {'cl_ok':>5} {'cl_SR':>6} | {'nous_raw':>9} {'no_ok':>5} {'no_SR':>6}")
    print("-" * 100)
    for iid in tasks:
        g = load(f"g_{iid}"); cl = load(f"c_{iid}"); no = load(f"n_{iid}")
        gx = round(g["impr"], 2) if g and g.get("impr") else None
        def cell(x):
            if not x:
                return ("--", "--")
            raw = round(x["impr"], 2) if x.get("impr") else None
            ok = "Y" if (x.get("cpct") or 0) >= 0.999 else f"N({x['failed']}f)"
            return (raw, ok)
        cr, cok = cell(cl); nr, nok = cell(no)
        print(f"{iid:<28} {str(gx):>7} | {str(cr):>10} {cok:>5} {str(sr(cl,g)):>6} | {str(nr):>9} {nok:>5} {str(sr(no,g)):>6}")


if __name__ == "__main__":
    main()
