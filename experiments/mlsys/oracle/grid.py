"""Render oracle results as color grids: python3 grid.py <runs_root> <out_dir>

Rows: questions grouped by category. Columns: task x arm x rep.
Yes/no: green/red; not applicable: grey; numbers: heat color per row (normalized to the row's range, direction-aware).
Also writes a summary grid (mean over reps, min-max in the cell) and summary.json.
"""
import glob
import json
import os
import statistics as st
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

ARMS = ["l2", "nous_prompt", "nous"]
ARM_LABEL = {"l2": "L2", "nous_prompt": "Nous-prompt", "nous": "Nous"}
TASK_LABEL = {"pd": "Verification (pd-disagg)", "dbg": "Debugging (BLIS bug)", "search": "Optimization (blis-search)"}
# (key, label, kind, higher_is_better)
GENERIC = [
    ("Outcome", [("O1", "O1 correct answer (primary)", "bool", True), ("O2_heldout", "O2 holds on held-out", "bool", True)]),
    ("Claims", [("C1_evidence_frac", "C1 evidence backs claim", "num", True),
                ("C2_remeasured_frac", "C2 claim re-measures", "num", True),
                ("C3_false_claims", "C3 false claims (count)", "num", False)]),
    ("Repro", [("R1_repro_runs", "R1 repro runs", "bool", True), ("R2_repro_matches", "R2 repro matches", "num", True)]),
    ("Validity", [("V4_no_forbidden_access", "V4 no forbidden access", "bool", True)]),
    ("Stopping/cost", [("S1_stopped_early", "S1 stopped too early", "bool", False),
                       ("S3_crashed_or_ceiling", "S3 crashed / ceiling", "bool", False),
                       ("E1_cost_usd", "E1 cost ($)", "num", False), ("E1_iterations", "E1 iterations", "num", False)]),
]
SPECIFIC = {
    "pd": [("K1_fit_moderate", "K1 fit holds at moderate rate", "bool", True),
           ("K2_breakdown_overpredict", "K2 breakdown + sign at high rate", "bool", True),
           ("K3_al_vs_ad", "K3 AL vs AD TTFT/ITL", "bool", True), ("K4_mechanism_soft", "K4 mechanism (soft)", "bool", True)],
    "dbg": [("D1_root_cause_located", "D1 root cause located", "bool", True),
            ("D2_upstream_test", "D2 upstream test passes", "bool", True),
            ("D3_suite_passes", "D3 full suite passes", "bool", True),
            ("D4_hidden_checks", "D4 hidden regression checks", "bool", True),
            ("D5_own_regression_test", "D5 own regression test", "bool", True),
            ("D6_minimal", "D6 minimal patch", "bool", True)],
    "search": [("B3_hv_main", "B3 HV ratio, main", "num", True), ("B1_main", "B1 HV >= 0.95 main", "bool", True),
               ("B3_hv_heldout_llama", "HV held-out llama", "num", True),
               ("B3_hv_heldout_qwen_r50", "HV held-out qwen r50", "num", True),
               ("B2_heldout", "B2 HV >= 0.95 held-out", "bool", True),
               ("T1_block_size_32", "T1 block size 32 dominates", "bool", True),
               ("T2_scheduler_irrelevant", "T2 scheduler irrelevant", "bool", True),
               ("T3_gpu_tradeoff", "T3 GPU trade-off direction", "bool", True),
               ("T4_small_kv", "T4 small KV suffices", "bool", True)],
}
GREEN, RED, GREY = "#2e9e5b", "#d64545", "#d9d9d9"
HEAT = LinearSegmentedColormap.from_list("h", ["#d64545", "#f2d14b", "#2e9e5b"])


def load(root):
    rows = []
    for f in glob.glob(os.path.join(root, "*", "*", "rep*", "oracle.json")):
        rows.append(json.load(open(f)))
    return rows


def cell(v, kind, better, lo, hi):
    if v is None:
        return GREY, "n/a"
    if kind == "bool":
        good = bool(v) == better
        return (GREEN if good else RED), ("yes" if v else "no")
    x = 0.5 if hi == lo else (v - lo) / (hi - lo)
    if not better:
        x = 1 - x
    return HEAT(x), (f"{v:.2f}" if isinstance(v, float) and abs(v) < 10 else f"{v:.0f}" if isinstance(v, (int, float)) else str(v))


def draw(rows_spec, cols, get, title, path):
    nr, nc = len(rows_spec), len(cols)
    fig, ax = plt.subplots(figsize=(1.0 + 1.05 * nc + 3.2, 0.42 * nr + 1.6))
    ax.set_xlim(0, nc)
    ax.set_ylim(0, nr)
    ax.invert_yaxis()
    for i, (key, label, kind, better, group) in enumerate(rows_spec):
        vals = [get(c, key) for c in cols]
        nums = [v[0] if isinstance(v, tuple) else v for v in vals]
        nums = [x for x in nums if isinstance(x, (int, float)) and not isinstance(x, bool)]
        lo, hi = (min(nums), max(nums)) if nums else (0, 1)
        for j, v in enumerate(vals):
            txt_override = None
            if isinstance(v, tuple):
                v, txt_override = v
            color, txt = cell(v, kind, better, lo, hi)
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=color, edgecolor="white", lw=2))
            ax.text(j + 0.5, i + 0.5, txt_override or txt, ha="center", va="center", fontsize=7.5,
                    color="black" if color in (GREY,) or kind == "num" else "white")
    ax.set_yticks([i + 0.5 for i in range(nr)])
    ax.set_yticklabels([f"{r[4]}: {r[1]}" if r[4] else r[1] for r in rows_spec], fontsize=8)
    ax.set_xticks([j + 0.5 for j in range(nc)])
    ax.set_xticklabels([c[1] for c in cols], fontsize=8, rotation=0)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def spec_for(task):
    rs = []
    for grp, items in GENERIC:
        for k, l, kind, b in items:
            rs.append((k, l, kind, b, grp))
    rs[1:1] = [(k, l, kind, b, "Task") for k, l, kind, b in SPECIFIC[task]]
    return rs


def main(root, out):
    os.makedirs(out, exist_ok=True)
    rows = load(root)
    summary = {}
    for task in ("pd", "dbg", "search"):
        tr = [r for r in rows if r["task"] == task]
        if not tr:
            continue
        reps = sorted({r["rep"] for r in tr})
        cols = [((a, rep), f"{ARM_LABEL[a]}\nrun {rep}") for a in ARMS for rep in reps
                if any(r["arm"] == a and r["rep"] == rep for r in tr)]
        idx = {(r["arm"], r["rep"]): r for r in tr}
        spec = spec_for(task)
        draw(spec, cols, lambda c, k: idx.get(c[0], {}).get(k), f"{TASK_LABEL[task]}: every run",
             os.path.join(out, f"grid_{task}_runs.png"))
        # summary: mean over reps (bool -> rate), min-max shown
        scols = [(a, ARM_LABEL[a]) for a in ARMS if any(r["arm"] == a for r in tr)]
        summary[task] = {}

        def sget(c, k, kind_of={s[0]: s[2] for s in spec}):
            vs = [idx[(c[0], rep)].get(k) for rep in reps if (c[0], rep) in idx]
            vs = [v for v in vs if v is not None]
            if not vs:
                return None
            if kind_of[k] == "bool":
                m = sum(bool(v) for v in vs) / len(vs)
                summary[task].setdefault(c[0], {})[k] = m
                return (m >= 0.5, f"{sum(bool(v) for v in vs)}/{len(vs)}")
            m = st.mean(vs)
            summary[task].setdefault(c[0], {})[k] = dict(mean=m, min=min(vs), max=max(vs), n=len(vs))
            return (m, f"{m:.2f}\n[{min(vs):.2f}-{max(vs):.2f}]" if abs(m) < 10 else f"{m:.0f}\n[{min(vs):.0f}-{max(vs):.0f}]")
        draw(spec, scols, sget, f"{TASK_LABEL[task]}\nsummary over {len(reps)} runs: yes count, or mean [min-max]",
             os.path.join(out, f"grid_{task}_summary.png"))
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1, default=str)
    return summary


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
