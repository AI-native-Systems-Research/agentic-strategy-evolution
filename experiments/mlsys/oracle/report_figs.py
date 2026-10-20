"""Summary figures and tables for REPORT.md: python3 report_figs.py <runs_root> <out_dir>

Writes: fig_o1.png (O1 success per task x arm), fig_cost.png (cost per run, every point), fig_cost_vs_o1.png,
fig_secondary.png (secondary checks heat grid), and results.json (every run's key fields, for the tables).
"""
import glob
import json
import os
import statistics as st
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ARMS = ["l2", "nous_prompt", "nous"]
LAB = {"l2": "L2", "nous_prompt": "Nous-prompt", "nous": "Nous"}
COL = {"l2": "#7f7f7f", "nous_prompt": "#4c78a8", "nous": "#e45756"}
TASKS = ["dbg", "pd", "search"]
TLAB = {"dbg": "Debugging", "pd": "Verification", "search": "Optimization"}


def load(root):
    rows = []
    for f in sorted(glob.glob(os.path.join(root, "*", "*", "rep*", "oracle.json"))):
        o = json.load(open(f))
        o.pop("runs", None)
        rows.append(o)
    return rows


def main(root, out):
    os.makedirs(out, exist_ok=True)
    rows = load(root)
    by = {(t, a): [r for r in rows if r["task"] == t and r["arm"] == a] for t in TASKS for a in ARMS}

    # O1 success (k of n), bars with run dots
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    w = 0.26
    for i, a in enumerate(ARMS):
        xs, ys, ns = [], [], []
        for j, t in enumerate(TASKS):
            rs = by[(t, a)]
            k = sum(bool(r["O1"]) for r in rs)
            xs.append(j + (i - 1) * w)
            ys.append(k / len(rs) if rs else 0)
            ns.append(f"{k}/{len(rs)}")
        bars = ax.bar(xs, ys, w * 0.92, color=COL[a], label=LAB[a])
        for b, n in zip(bars, ns):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02, n, ha="center", fontsize=8)
    ax.set_xticks(range(len(TASKS)))
    ax.set_xticklabels([TLAB[t] for t in TASKS])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("O1 correct answer (share of runs)")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_o1.png"), dpi=170)
    plt.close(fig)

    # cost per run (every point) + O1 marker
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    for i, a in enumerate(ARMS):
        for j, t in enumerate(TASKS):
            for k, r in enumerate(by[(t, a)]):
                x = j + (i - 1) * w + (k - 1) * 0.05
                ax.scatter(x, r["E1_cost_usd"], s=36, color=COL[a], marker="o" if r["O1"] else "x",
                           label=LAB[a] if (j == 0 and k == 0) else None)
    ax.set_xticks(range(len(TASKS)))
    ax.set_xticklabels([TLAB[t] for t in TASKS])
    ax.set_ylabel("cost per run ($)")
    ax.set_title("each point is one run; o = O1 correct, x = O1 wrong", fontsize=8, loc="left")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_cost.png"), dpi=170)
    plt.close(fig)

    # secondary checks: share of runs passing, per task x arm
    checks = {"dbg": [("D5_own_regression_test", "own test catches bug"), ("D6_minimal", "minimal patch")],
              "pd": [("K1_fit_moderate", "K1 fit at moderate rate"), ("K2_breakdown_overpredict", "K2 breakdown + sign"),
                     ("K3_al_vs_ad", "K3 AL vs AD"), ("K4_mechanism_soft", "K4 mechanism (soft)")],
              "search": [("B1_main", "HV >= 0.95 main"), ("B2_heldout", "HV >= 0.95 held-out"),
                         ("T1_block_size_32", "T1 block 32"), ("T2_scheduler_irrelevant", "T2 scheduler"),
                         ("T3_gpu_tradeoff", "T3 GPU trade-off"), ("T4_small_kv", "T4 small KV")]}
    generic = [("R1_repro_runs", "repro runs"), ("S3_crashed_or_ceiling", "crashed/ceiling (lower better)")]
    rowspec = [(t, k, l) for t in TASKS for k, l in checks[t] + generic]
    fig, ax = plt.subplots(figsize=(6.4, 0.32 * len(rowspec) + 1.2))
    for i, (t, k, l) in enumerate(rowspec):
        for j, a in enumerate(ARMS):
            rs = [r for r in by[(t, a)] if r.get(k) is not None]
            v = sum(bool(r.get(k)) for r in rs) / len(rs) if rs else None
            good = (1 - v) if (v is not None and k == "S3_crashed_or_ceiling") else v
            c = "#d9d9d9" if v is None else plt.cm.RdYlGn(0.15 + 0.7 * good)
            ax.add_patch(plt.Rectangle((j, i), 1, 1, color=c, ec="white", lw=1.5))
            txt = "n/a" if v is None else f"{sum(bool(r.get(k)) for r in rs)}/{len(rs)}"
            ax.text(j + 0.5, i + 0.5, txt, ha="center", va="center", fontsize=7.5)
    ax.set_xlim(0, len(ARMS))
    ax.set_ylim(0, len(rowspec))
    ax.invert_yaxis()
    ax.set_xticks([j + 0.5 for j in range(len(ARMS))])
    ax.set_xticklabels([LAB[a] for a in ARMS], fontsize=8)
    ax.set_yticks([i + 0.5 for i in range(len(rowspec))])
    ax.set_yticklabels([f"{TLAB[t]}: {l}" for t, k, l in rowspec], fontsize=7.5)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_secondary.png"), dpi=170)
    plt.close(fig)

    keys = ["task", "arm", "rep", "O1", "E1_cost_usd", "E1_wall_min", "E1_iterations", "status", "C1_evidence_frac",
            "C2_remeasured_frac", "C3_false_claims", "R1_repro_runs", "R2_repro_matches", "V4_no_forbidden_access",
            "S1_stopped_early", "S3_crashed_or_ceiling", "D2_upstream_test", "D4_hidden_checks", "D5_own_regression_test",
            "D6_nontest_lines", "K1_fit_moderate", "K2_breakdown_overpredict", "K3_al_vs_ad", "K4_mechanism_soft",
            "B3_hv_main", "B3_hv_heldout_llama", "B3_hv_heldout_qwen_r50", "T_score"]
    res = [{k: r.get(k) for k in keys} for r in rows]
    summ = {}
    for t in TASKS:
        for a in ARMS:
            rs = by[(t, a)]
            if not rs:
                continue
            c = [r["E1_cost_usd"] for r in rs]
            summ[f"{t}/{a}"] = dict(n=len(rs), o1=sum(bool(r["O1"]) for r in rs), cost_mean=round(st.mean(c), 2),
                                    cost_min=round(min(c), 2), cost_max=round(max(c), 2),
                                    iters_mean=round(st.mean(r["E1_iterations"] or 0 for r in rs), 2))
    json.dump(dict(runs=res, summary=summ), open(os.path.join(out, "results.json"), "w"), indent=1, default=str)
    return summ


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2]), indent=1))
