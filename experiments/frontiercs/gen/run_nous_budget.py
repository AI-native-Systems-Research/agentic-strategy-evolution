#!/usr/bin/env python3
"""Run Nous on a Frontier-CS algorithmic task under a DOLLAR budget with a score stop.

Nous has no native cost cap (`--max-iterations` is the only lever, `resume` extends it). This driver
wraps that: set up the campaign once, then loop  run -> (re-judge harvested candidates + sum
cost_usd) -> resume with a higher iteration cap, until either the best *judge* score reaches
--stop-score (~100) or cumulative cost reaches --budget-usd. No early plateau stop: we keep resuming
while under budget and below the score target.

Best score is the ground truth from the go-judge (re-judging harvested candidate solutions), not
Nous's internal best_found.json (which has been unreliable for this benchmark).

Reuses frontier_gen for the judge + campaign-setup contract. LLM goes DIRECT to litellm over VPN via
the Agent SDK (ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN); never the tunnel.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frontier_gen as fg  # statement, evaluate, SEED, OUTPUT_FORMAT_NOTE, FRONTIER, FEVAL, NOUS_BIN, NOUS_REPO


def build_campaign(pid, ws: Path, model, nous_iters):
    """Replicates frontier_gen.run_nous setup: worktree seed, fmeasure wrapper, campaign.yaml."""
    import yaml
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "solution.cpp").write_text(fg.SEED)
    fg.sh("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed", cwd=str(ws))
    fmeasure = ws.parent / f"fmeasure_{pid}.sh"
    fmeasure.write_text(
        "#!/bin/bash\n"
        "# Usage: fmeasure.sh <solution.cpp> -> prints 'SCORE: <n>' (judge score 0-100, higher is better)\n"
        f"cd {fg.FRONTIER} || exit 2\n"
        'export PATH="$HOME/.local/bin:$PATH"\n'
        f'out=$({fg.FEVAL} eval algorithmic {pid} "$1" --json 2>/dev/null)\n'
        "s=$(printf '%s' \"$out\" | python3 -c \"import sys,re;t=sys.stdin.read();m=re.findall(r'\\\"score\\\"\\s*:\\s*([0-9.]+)',t);print(m[-1] if m else 'ERR')\")\n"
        'echo "SCORE: $s"\n')
    fmeasure.chmod(0o755)
    stmt = fg.statement(pid)
    desc = (
        f"You are solving Frontier-CS algorithmic problem #{pid}. Scoring is CONTINUOUS partial "
        f"credit from 0 to 100 (higher is better); MAXIMIZE it. Your working directory is a git "
        f"worktree containing 'solution.cpp' (a C++17 stub). Edit solution.cpp with your algorithm, "
        f"then compile-check and measure.\n\n"
        f"MEASURE the objective (the judge score) with this ONE command (do not run the judge any "
        f"other way):\n"
        f"    bash {fmeasure} $PWD/solution.cpp\n"
        f"It prints a single line 'SCORE: <n>' where n is the judge score (0-100). Record that "
        f"number in the finding metadata under key 'score'. Each experiment arm should try a "
        f"distinct algorithmic strategy (different heuristic, exact method, or optimization) and "
        f"report its measured score. The judge call takes ~30-60s; call it once per arm.\n\n"
        + fg.OUTPUT_FORMAT_NOTE +
        f"\nPROBLEM STATEMENT:\n{stmt}")
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"frontier-{pid}-nousbudget").strip("-")
    spec = {
        "research_question": f"What algorithm maximizes the Frontier-CS judge score for algorithmic problem #{pid}?",
        "run_id": run_slug,
        "max_iterations": nous_iters,
        "sandbox": "bypass",
        "target_system": {
            "name": f"frontier-cs::algorithmic::{pid}",
            "description": desc,
            "repo_path": str(ws),
            "observable_metrics": ["score"],
            "controllable_knobs": ["solution_cpp"],
        },
        "objective": {"weights": {"score": 1.0}},
        "models": {"design": model, "execute_analyze": model, "report": model},
        "prompts": {"methodology_layer": f"{fg.NOUS_REPO}/prompts/methodology", "domain_adapter_layer": None},
    }
    camp = ws.parent / f"campaign_{pid}.yaml"
    camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    return camp, run_slug, fmeasure


def sum_cost(camp_dir: Path):
    """Cumulative cost_usd + token/call tally from the campaign metrics ledger."""
    cost = tin = tout = ncalls = 0.0
    p = camp_dir / "llm_metrics.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            cost += e.get("cost_usd", 0) or 0
            tin += e.get("input_tokens", 0) or 0
            tout += e.get("output_tokens", 0) or 0
            ncalls += 1
    return cost, int(tin), int(tout), int(ncalls)


def harvest_candidates(ws: Path, camp_dir: Path):
    globbed = (list((ws / ".nous-experiments").glob("**/solution.cpp"))
               + list(camp_dir.glob("runs/iter-*/inputs/*solution.cpp"))
               + [ws / "solution.cpp"])
    seen, cands = set(), []
    for sc in globbed:
        if not sc.exists():
            continue
        body = sc.read_text().strip()
        if not body or body == fg.SEED.strip() or body in seen:
            continue
        seen.add(body)
        cands.append(sc)
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--budget-usd", type=float, default=50.0)
    ap.add_argument("--stop-score", type=float, default=99.5)
    ap.add_argument("--chunk", type=int, default=2, help="iterations added per run/resume phase")
    ap.add_argument("--start-iters", type=int, default=2)
    ap.add_argument("--phase-timeout", type=int, default=2400, help="nous per-phase --timeout (s)")
    ap.add_argument("--proc-timeout", type=int, default=36000, help="subprocess hard timeout per phase (s)")
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--progress", default=None, help="jsonl trajectory out (default: alongside --out)")
    args = ap.parse_args()

    logdir = Path(args.logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    ws = logdir / f"frontier_{args.pid}_nousbudget_ws"
    camp, run_slug, fmeasure = build_campaign(args.pid, ws, args.model, args.start_iters)
    camp_dir = ws.parent / "nous_runs" / run_slug

    env = dict(os.environ)
    env["NOUS_CAMPAIGN_PARENT"] = str(ws.parent / "nous_runs")
    env["NOUS_REPO"] = os.environ.get("NOUS_REPO", fg.NOUS_REPO)
    env["NOUS_BIN"] = os.environ.get("NOUS_BIN", fg.NOUS_BIN)
    env["PATH"] = os.path.expanduser("~/.local/bin") + ":" + env.get("PATH", "")

    progress_path = Path(args.progress) if args.progress else Path(args.out).with_suffix(".progress.jsonl")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    phase_log = logdir / f"frontier_{args.pid}_nousbudget.nous.log"

    judged = {}          # body-hash -> (score, status, path)
    best_score, best_path = None, None
    traj = []
    cum_iters = args.start_iters
    prev_cost = -1.0
    stall = 0
    t0 = time.time()
    phase = 0

    while True:
        phase += 1
        if phase == 1:
            cmd = [env["NOUS_BIN"], "run", str(camp), "--auto-approve", "--agent", "sdk",
                   "--sandbox", "bypass", "--max-iterations", str(cum_iters),
                   "--timeout", str(args.phase_timeout)]
        else:
            cmd = [env["NOUS_BIN"], "resume", str(camp_dir), "--auto-approve", "--agent", "sdk",
                   "--max-iterations", str(cum_iters), "--timeout", str(args.phase_timeout)]
        print(f"[phase {phase}] cum_iters={cum_iters} :: {' '.join(cmd)}", flush=True)
        with open(phase_log, "a") as lf:
            lf.write(f"\n\n===== PHASE {phase} cum_iters={cum_iters} =====\n")
            try:
                subprocess.run(cmd, cwd=env["NOUS_REPO"], env=env, stdout=lf,
                               stderr=subprocess.STDOUT, text=True, timeout=args.proc_timeout)
            except subprocess.TimeoutExpired:
                lf.write("\n[phase hit subprocess proc-timeout]\n")

        # ---- ground-truth score: judge any newly-harvested candidates ----
        for sc in harvest_candidates(ws, camp_dir):
            key = sc.read_text().strip()
            if key in judged:
                continue
            try:
                score, status, _ = fg.evaluate(args.pid, sc, timeout=900)
            except Exception as e:
                score, status = None, f"judge_exc:{type(e).__name__}"
            judged[key] = (score, status, str(sc))
            if score is not None and (best_score is None or score > best_score):
                best_score, best_path = score, sc

        cost, tin, tout, ncalls = sum_cost(camp_dir)
        row = {"phase": phase, "cum_iters": cum_iters, "cost_usd": round(cost, 4),
               "best_score": best_score, "n_candidates": len(judged),
               "llm_calls": ncalls, "in_tok": tin, "out_tok": tout,
               "elapsed_s": round(time.time() - t0, 1)}
        traj.append(row)
        with open(progress_path, "a") as pf:
            pf.write(json.dumps(row) + "\n")
        print(f"[phase {phase}] cost=${cost:.2f} best={best_score} cands={len(judged)} "
              f"calls={ncalls} elapsed={row['elapsed_s']}s", flush=True)

        # ---- stop conditions ----
        if best_score is not None and best_score >= args.stop_score:
            print(f"STOP reason=score best={best_score} >= {args.stop_score}", flush=True)
            break
        if cost >= args.budget_usd:
            print(f"STOP reason=budget cost=${cost:.2f} >= ${args.budget_usd}", flush=True)
            break
        # guard against a resume that does nothing (Nous can't/won't continue): if cost didn't move
        # for two phases in a row, we can't honor "no early stop" indefinitely -> stop & report.
        if abs(cost - prev_cost) < 1e-6:
            stall += 1
            if stall >= 2:
                print(f"STOP reason=stalled (cost flat at ${cost:.2f}; Nous not advancing)", flush=True)
                break
        else:
            stall = 0
        prev_cost = cost
        cum_iters += args.chunk

    # ---- persist best solution + pred ----
    if best_path is not None:
        (ws / "solution.cpp").write_text(best_path.read_text())
    cost, tin, tout, ncalls = sum_cost(camp_dir)
    pred = {
        "pid": args.pid, "agent": "nous", "mode": "budget", "model": args.model,
        "final_score": best_score, "cost_usd": round(cost, 4),
        "budget_usd": args.budget_usd, "stop_score": args.stop_score,
        "phases": phase, "final_cum_iters": cum_iters,
        "in_tok": tin, "out_tok": tout, "llm_calls": ncalls,
        "elapsed_s": round(time.time() - t0, 1),
        "n_candidates": len(judged), "trajectory": traj,
        "best_solution_path": str(ws / "solution.cpp"),
        "campaign_dir": str(camp_dir),
    }
    Path(args.out).write_text(json.dumps(pred, indent=2))
    print(f"RESULT pid={args.pid} agent=nous final_score={best_score} cost=${cost:.2f} "
          f"phases={phase} elapsed={pred['elapsed_s']}s -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
