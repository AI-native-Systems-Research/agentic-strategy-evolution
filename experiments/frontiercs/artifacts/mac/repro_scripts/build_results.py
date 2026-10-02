#!/usr/bin/env python3
"""Harvest the Mac Frontier-CS matrix: re-eval each best solution 3x (judge has ~+-5 noise),
group by (task, agent) across seeds, emit results.csv + RESULTS.md. Also copy nous best
solutions into artifacts/mac/nous/ with embedded .git stripped (so they don't commit as gitlinks)."""
import json, os, re, shlex, shutil, statistics, subprocess, sys
from pathlib import Path

WT = "/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/asr-frontier-mac"
FRONTIER = os.path.expanduser("~/frontier/Frontier-CS")
FEVAL = f"{FRONTIER}/.venv/bin/frontier"
ART = Path(WT) / "experiments/frontiercs/artifacts/mac"
PREDS = ART / "preds"
NOUS_ART = ART / "nous"
REEVAL_N = 3

AGENT_LABEL = {"claude": "vanilla Claude", "engram": "Engram-style (reimpl.)", "nous": "Nous"}


def eval_once(pid, sol):
    r = subprocess.run(f"{FEVAL} eval algorithmic {pid} {shlex.quote(str(sol))} --json",
                       shell=True, text=True, capture_output=True, cwd=FRONTIER, timeout=900)
    blob = r.stdout + "\n" + r.stderr
    best = None
    for m in re.finditer(r"\{[^{}]*\"score\"[^{}]*\}", blob):
        try:
            best = json.loads(m.group(0))
        except Exception:
            pass
    if best is None:
        return None
    return best.get("score")


def reeval(pid, sol, n=REEVAL_N):
    xs = []
    for _ in range(n):
        s = eval_once(pid, sol)
        if isinstance(s, (int, float)):
            xs.append(float(s))
    return xs


def agent_of(label):
    for a in ("claude", "engram", "nous"):
        if label.startswith(a):
            return a
    return label


def main():
    rows = []  # per-run
    for pj in sorted(PREDS.glob("p*.json")):
        meta = json.loads(pj.read_text())
        pid = str(meta.get("problem_id"))
        label = meta.get("label", pj.stem)
        agent = agent_of(label)
        seed_m = re.search(r"s(\d+)", label)
        seed = seed_m.group(1) if seed_m else "?"
        sol = meta.get("solution")
        reevals = reeval(pid, sol) if sol and Path(sol).exists() else []
        tin = meta.get("input_tokens") or 0
        tout = meta.get("output_tokens") or 0
        # Uniform cost across agents from exact token counts (opus-4-6 $15/M in, $75/M out) so the
        # cost column is apples-to-apples regardless of each agent's own price table.
        cost_uniform = round(tin / 1e6 * 15 + tout / 1e6 * 75, 4)
        row = {
            "task": pid, "agent": agent, "seed": seed,
            "reported_final": meta.get("final_score"),
            "reeval_scores": reevals,
            "reeval_mean": round(statistics.mean(reevals), 3) if reevals else None,
            "seconds": meta.get("seconds"),
            "cost_usd_reported": meta.get("cost_usd_est"),
            "cost_usd_uniform": cost_uniform,
            "input_tokens": tin,
            "output_tokens": tout,
            "solution": sol,
        }
        rows.append(row)
        # archive nous best solution (strip .git handled below at commit time)
        if agent == "nous" and sol and Path(sol).exists():
            dst = NOUS_ART / f"p{pid}_s{seed}"
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy(sol, dst / "best_solution.cpp")
        print(f"  reeval p{pid} {agent} s{seed}: reported={row['reported_final']} reeval={reevals} mean={row['reeval_mean']}")

    (ART / "results_runs.json").write_text(json.dumps(rows, indent=2))

    # group by (task, agent)
    groups = {}
    for r in rows:
        groups.setdefault((r["task"], r["agent"]), []).append(r)

    # CSV
    csv_lines = ["task,agent,n_seeds,score_mean,score_sd,time_mean_s,cost_mean_usd,cost_total_usd"]
    md = ["# Frontier-CS Mac results (new tasks 8, 174) — 3 agents x 3 seeds\n",
          "Model: claude-opus-4-6. Judge: local Docker (arm64). Final score = mean of "
          f"{REEVAL_N} independent judge re-evals per solution; table shows mean +/- sd across seeds.\n",
          "| task | agent | score (mean±sd) | time (mean s) | cost (mean $) |",
          "|------|-------|-----------------|---------------|---------------|"]
    for (task, agent) in sorted(groups, key=lambda k: (int(k[0]) if k[0].isdigit() else 0, k[1])):
        g = groups[(task, agent)]
        means = [x["reeval_mean"] for x in g if x["reeval_mean"] is not None]
        times = [x["seconds"] for x in g if isinstance(x["seconds"], (int, float))]
        costs = [x["cost_usd_uniform"] for x in g if isinstance(x["cost_usd_uniform"], (int, float))]
        smean = round(statistics.mean(means), 3) if means else None
        ssd = round(statistics.pstdev(means), 3) if len(means) > 1 else 0.0
        tmean = round(statistics.mean(times), 0) if times else None
        cmean = round(statistics.mean(costs), 3) if costs else None
        ctot = round(sum(costs), 3) if costs else None
        csv_lines.append(f"{task},{agent},{len(means)},{smean},{ssd},{tmean},{cmean},{ctot}")
        disp = AGENT_LABEL.get(agent, agent)
        md.append(f"| {task} | {disp} | {smean} ± {ssd} | {tmean} | {cmean} |")

    (ART / "results.csv").write_text("\n".join(csv_lines) + "\n")
    (ART / "RESULTS.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
