#!/usr/bin/env python3
"""Real Engram (mit-nms, agentic_handoff, as-is) on a Frontier-CS research task, capped at $50.

Engram's agents already run isolated (file tools rooted at their workspace, shell inside a Docker
container). Scoring goes through the same out-of-process judge daemon as the Nous/Claude arms
(local problem evaluator, exploit solutions scored 0, every measured solution archived), via the
FCS_JUDGE_ROOT hook in ~/engram_repo/SystemBench/FrontierCS/evaluator.py. Cost is metered per LLM
response by a local pass-through proxy (token_meter_proxy.py, same $15/$75 cache-aware ruler as
Nous/Claude), because Engram itself only logs cost every 5 iterations; killed at the first poll >= budget.

Usage:
  engram_research_cap.py grammar_fuzzing/seed/sql --slug gf_e46 --out artifacts/preds/gf_seed_sql.engram.o46.json
"""
import argparse, glob, json, os, re, signal, subprocess, threading, time
from pathlib import Path

import nous_research_isolated as N
import token_meter_proxy as TM

ENGRAM = Path(os.path.expanduser("~/engram_repo"))


def engram_cost(results_dir):
    best = 0.0
    for f in glob.glob(f"{results_dir}/**/*usage_stats.json", recursive=True):
        try: best = max(best, float(json.load(open(f)).get("total_cost", 0) or 0))
        except (ValueError, OSError, json.JSONDecodeError): pass
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid"); ap.add_argument("--slug", required=True)
    ap.add_argument("--budget", type=float, default=50.0)
    ap.add_argument("--max-agents", type=int, default=20)
    ap.add_argument("--agent-timeout", type=int, default=120)
    ap.add_argument("--out", required=True)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    a = ap.parse_args(); pid = a.pid
    root = f"/tmp/fcs_rjudge_engram/{a.slug}"
    measured = Path(a.logdir) / f"research_{a.slug}_measured_{time.strftime('%Y%m%d_%H%M%S')}"
    stop = threading.Event(); N.start_daemon(pid, root, stop, measured)
    log = Path(a.logdir) / f"engram_{a.slug}.log"
    _, meter, proxy = TM.start(os.environ["OPENAI_BASE_URL"])
    env = dict(os.environ, FCS_JUDGE_ROOT=root, OPENAI_BASE_URL=proxy, OPENAI_API_BASE=proxy)
    cmd = (f"cd {ENGRAM} && source .venv/bin/activate && exec python -u examples/handoff_example_usage.py "
           f"--problem_name fcs_res_{pid} --model claude-opus-4-6 --max_agents {a.max_agents} "
           f"--agent_timeout {a.agent_timeout} --num_runs 1")
    t0 = time.time()
    lf = open(log, "w")
    p = subprocess.Popen(["bash", "-c", cmd], env=env, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
    print(f"[ecap] engram pid={p.pid} task={pid} budget=${a.budget} log={log} measured={measured}", flush=True)
    rd, cost, ecost, capped = None, 0.0, 0.0, False
    while p.poll() is None:
        time.sleep(20)
        if rd is None:
            m = re.findall(r"Results Directory: (.*)", log.read_text(errors="ignore"))
            rd = m[-1].strip() if m else None
        if rd:
            ecost = engram_cost(rd)
        cost = meter.cost
        n = len(list(measured.glob("*.py")))
        print(f"[ecap {time.strftime('%H:%M:%S')}] cost=${cost:.2f} (calls={meter.calls}; engram-logged ${ecost:.2f}) measured={n}", flush=True)
        if cost >= a.budget:
            capped = True
            print(f"[ecap] cost ${cost:.2f} >= ${a.budget} -> kill", flush=True)
            os.killpg(p.pid, signal.SIGTERM); time.sleep(10)
            if p.poll() is None: os.killpg(p.pid, signal.SIGKILL)
            break
    p.wait(); stop.set()
    cost = meter.cost
    if rd: ecost = engram_cost(rd)
    best, bestsrc, ev, rejected = -1.0, None, [], []
    for f in N._top_measured(measured, 10):
        sc, hits = N.judge_clean(pid, Path(f).read_text(errors="ignore"))
        tag = f.replace(os.path.expanduser("~"), "~")
        if hits: rejected.append({"src": tag, "exploits": hits}); continue
        ev.append({"src": tag, "score": sc})
        if sc > best: best, bestsrc = sc, tag
    pred = {"problem_id": pid, "track": "research", "agent": "engram", "label": a.slug,
            "model": "claude-opus-4-6", "method": "real Engram agentic_handoff (as-is)",
            "final_score": round(best, 2) if best >= 0 else None, "cost_usd_tokenbased": round(cost, 2), "llm_calls": meter.calls,
            "cost_engram_logged": round(ecost, 2),
            "cost_capped": capped, "n_measured": len(list(measured.glob("*.py"))),
            "n_clean_candidates": len(ev), "n_rejected_exploits": len(rejected), "best_source": bestsrc,
            "clean_evidence": ev, "rejected_exploit_candidates": rejected,
            "isolation": "Engram agents: workspace-rooted FS + Docker shell; scoring via out-of-process judge daemon (exploits=0); post-harvest exploit audit + re-judge",
            "engram_results_dir": rd, "elapsed_s": round(time.time() - t0, 1)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(pred, indent=2))
    print(f"ENGRAM-RES DONE {pid}: best_clean={best} cost=${cost:.2f} measured={pred['n_measured']} -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
