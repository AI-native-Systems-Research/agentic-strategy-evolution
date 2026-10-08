#!/usr/bin/env python3
"""Claude baseline for the RESEARCH track (cloudcast): plain Claude Code CLI, sandbox-isolated, scored
by the problem's local evaluator via the research judge daemon (research_judge_server.py).

Mirrors claude_code_runner.py but: solution is solution.py (a `Solution` class), the metric is
total_cost ($, LOWER is better; score = 100/(1+total_cost), which we MAXIMIZE), and the agent is told
to minimize cost. Same isolation (sandbox-exec deny ~/frontier + out-of-sandbox daemon), same
budget-or-max loop, same persist-every-attempt + re-judge-at-end-from-persisted-artifacts policy.

Usage: python claude_research_runner.py cloudcast --budget 50 --out-dir runs/cloudcast/claude
"""
import argparse, glob, json, os, re, shlex, shutil, subprocess, tempfile, time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
CLI = os.environ.get("CLAUDE_CLI_PATH", os.path.expanduser(
    "~/nous_repo/.venv/lib/python3.11/site-packages/claude_agent_sdk/_bundled/claude"))
R_IN, R_OUT, R_CW, R_CR = 15/1e6, 75/1e6, 18.75/1e6, 1.5/1e6
JUDGE_ROOT = "/tmp/fcs_rjudge"


def transcript_cost(cfg_dir):
    cost = 0.0; turns = 0
    for f in glob.glob(f"{cfg_dir}/projects/**/*.jsonl", recursive=True):
        for ln in open(f, errors="ignore"):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            u = (d.get("message") or {}).get("usage") if isinstance(d.get("message"), dict) else None
            if not u:
                continue
            cost += (u.get("input_tokens", 0)*R_IN + u.get("output_tokens", 0)*R_OUT
                     + u.get("cache_creation_input_tokens", 0)*R_CW + u.get("cache_read_input_tokens", 0)*R_CR)
            turns += 1
    return round(cost, 4), turns


def judge_local(pid, sol_py, timeout=900):
    """Our authoritative re-judge (runner is NOT sandboxed): returns (score, total_cost)."""
    pd = Path(FRONTIER) / "research" / "problems" / pid
    evalpy = pd / ".evalvenv" / "bin" / "python3"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    try:
        subprocess.run(f"{shlex.quote(str(evalpy))} {shlex.quote(str(pd/'evaluator.py'))} "
                       f"--solution {shlex.quote(str(sol_py))} "
                       f"--spec {shlex.quote(str(pd/'resources'/'submission_spec.json'))} "
                       f"--out {shlex.quote(out)}", shell=True, capture_output=True, text=True,
                       timeout=timeout, cwd=str(pd))
        try:
            data = json.loads(Path(out).read_text())
        except Exception:
            return None, None
    finally:
        try: os.unlink(out)
        except OSError: pass
    if data.get("error") or data.get("runs_successfully", 0.0) != 1.0:
        return 0.0, data.get("total_cost")
    return float(data.get("score", 0.0)), data.get("total_cost")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")                       # research problem name, e.g. cloudcast
    ap.add_argument("--budget", type=float, default=50.0)
    ap.add_argument("--max-score", type=float, default=100.0)  # 100/(1+cost): ~unreachable -> runs to budget
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    run = Path(args.out_dir).resolve(); run.mkdir(parents=True, exist_ok=True)
    cfg = run / "cfg"; cfg.mkdir(exist_ok=True)
    pd = Path(FRONTIER) / "research" / "problems" / args.pid
    shutil.copy(pd / "readme", run / "statement.txt")
    sol = run / "solution.py"
    sol.write_text("# Implement the Solution class here (see statement.txt).\n")
    trials_dir = run / "trials"; trials_dir.mkdir(exist_ok=True)
    best_path = run / "solution.best.py"
    for sub in ("inbox", "outbox", "done"):
        Path(JUDGE_ROOT, sub).mkdir(parents=True, exist_ok=True)

    measure = run / "measure.sh"
    measure.write_text(
        "#!/bin/bash\n"
        "# Submit solution.py to the research judge; prints SCORE (higher better) and COST ($, LOWER better).\n"
        f'JR="{JUDGE_ROOT}"\n'
        f'tok="{args.pid}__$(date +%s%N)_$RANDOM"\n'
        f'cp "{run}/solution.py" "$JR/inbox/$tok.py"\n'
        'for i in $(seq 1 2400); do\n'
        '  if [ -f "$JR/outbox/$tok.score" ]; then cat "$JR/outbox/$tok.score"; rm -f "$JR/outbox/$tok.score"; exit 0; fi\n'
        '  sleep 0.5\n'
        'done\n'
        'echo "SCORE: ERR"; echo "COST: ERR"\n')
    measure.chmod(0o755)

    sb_profile = run / "sandbox.sb"
    frontier_root = os.path.realpath(os.path.expanduser("~/frontier"))
    sb_profile.write_text("(version 1)\n(allow default)\n"
                          f'(deny file-read* (subpath "{frontier_root}"))\n')
    sandbox_prefix = ([] if os.environ.get("NOUS_FCS_NO_SANDBOX")
                      else ["sandbox-exec", "-f", str(sb_profile)])

    prompt = (
        f"You are solving Frontier-CS RESEARCH problem '{args.pid}'. Objective: MINIMIZE the total "
        "transfer cost ($) of a multi-cloud broadcast. Read statement.txt in this directory for the full "
        "spec and API. Write your solution to solution.py: a `Solution` class whose "
        "solve(spec_path=None) returns {\"code\": \"<python source>\"}, where the source implements "
        "search_algorithm(src, dsts, G, num_partitions) -> BroadCastTopology (see statement.txt). "
        "To evaluate, run `./measure.sh` — it prints `SCORE: <v>` and `COST: <v>`. COST is the total "
        "transfer cost in $ and is what matters: LOWER COST IS BETTER (SCORE = 100/(1+COST), so higher "
        "SCORE = lower cost). Iterate to drive COST as low as possible. "
        "PERSIST EVERY ATTEMPT: right after each ./measure.sh, copy solution.py to "
        "trials/attempt_<N>_cost_<COST>.py (N=1,2,3...; create trials/ if needed; never delete earlier "
        "attempts) so every result can be reproduced. "
        "Do NOT conclude you 'cannot improve' — keep trying better routing/MILP/Steiner formulations. "
        "RULES: solve it yourself; do NOT read, open, or copy any file under ~/frontier (reference "
        "solutions, evaluator, test data). Leave your lowest-COST solution in solution.py.")
    cont_prompt = (
        "Your current solution.py scored COST={cost} (SCORE={score}). Lower COST is better and you are "
        "not done. Try a genuinely better approach (stronger MILP/Steiner-arborescence formulation, "
        "better partition routing, tighter bandwidth use), edit solution.py, re-run ./measure.sh, and "
        "save the attempt to trials/. Keep driving COST down.")

    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(cfg)
    for k in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER", "DISABLE_TELEMETRY",
              "DISABLE_ERROR_REPORTING"):
        env[k] = "1"
    env.setdefault("CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS", "90000")
    env.setdefault("API_TIMEOUT_MS", "300000")
    env.setdefault("CLAUDE_STREAM_IDLE_TIMEOUT_MS", "300000")
    env.setdefault("BUN_FEATURE_FLAG_DISABLE_IO_POOL", "1")
    env.setdefault("CLAUDE_CODE_MAX_RETRIES", "40")
    env.setdefault("CLAUDE_CODE_CONNECT_TIMEOUT_MS", "20000")
    base_flags = ["--output-format", "stream-json", "--verbose", "--model", args.model,
                  "--permission-mode", "bypassPermissions",
                  "--allowedTools", "Bash", "Read", "Write", "Edit", "--max-turns", str(args.max_turns)]

    t0 = time.time()
    best_score = -1.0; best_cost = None
    stop = None; session = 0; refuse = 0; cost = 0.0; turns = 0
    while True:
        if best_score >= args.max_score:
            stop = "max_score"; break
        if cost >= args.budget:
            stop = "budget"; break
        if refuse >= 5:
            stop = "agent_will_not_continue"; break
        session += 1; cost_before = cost
        if session == 1:
            cmd = sandbox_prefix + [CLI, "-p", prompt] + base_flags
        else:
            msg = cont_prompt.format(score=f"{best_score:g}" if best_score >= 0 else "?",
                                     cost=f"{best_cost:g}" if best_cost is not None else "?")
            cmd = sandbox_prefix + [CLI, "--continue", "-p", msg] + base_flags
        with open(run / "stream.jsonl", "a") as log:
            proc = subprocess.Popen(cmd, cwd=str(run), env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT)
            print(f"[research] session={session} pid={proc.pid} task={args.pid} budget=${args.budget} "
                  f"best_cost={best_cost} dir={run}", flush=True)
            killed = False
            while proc.poll() is None:
                time.sleep(10)
                cost, turns = transcript_cost(cfg)
                print(f"[research {time.strftime('%H:%M')}] s{session} turns={turns} cost=${cost} "
                      f"best_cost={best_cost}", flush=True)
                if cost >= args.budget:
                    print(f"[research] cost ${cost} >= ${args.budget} -> KILL", flush=True)
                    proc.terminate()
                    try: proc.wait(10)
                    except Exception: proc.kill()
                    killed = True; break
        cost, turns = transcript_cost(cfg)
        score, tcost = judge_local(args.pid, str(sol))
        if score is not None:
            tag = ("%g" % tcost) if tcost is not None else "ERR"
            try: shutil.copy(sol, trials_dir / f"s{session}.cost{tag}.py")
            except Exception: pass
            with open(run / "trials.jsonl", "a") as tl:
                tl.write(json.dumps({"session": session, "score": score, "total_cost": tcost,
                                     "cost_spent": cost, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
            if score > best_score:
                best_score = score; best_cost = tcost
                try: shutil.copy(sol, best_path)
                except Exception: pass
        print(f"[research] session={session} ended score={score} cost=${cost} total_cost={tcost} "
              f"best_cost={best_cost}", flush=True)
        refuse = refuse + 1 if (cost - cost_before) < 0.05 else 0
        if killed:
            stop = "budget"; break

    official = None
    for ln in open(run / "stream.jsonl", errors="ignore"):
        try:
            d = json.loads(ln)
            if d.get("type") == "result" and d.get("total_cost_usd") is not None:
                official = d["total_cost_usd"]
        except Exception:
            pass

    # EVIDENCE: re-judge every persisted attempt; report the lowest-cost (best-score) reproducible one.
    evidence = []; rb_score = -1.0; rb_cost = None; best_file = None
    for py in sorted(trials_dir.glob("*.py")):
        s, c = judge_local(args.pid, str(py))
        evidence.append({"file": py.name, "rejudged_score": s, "total_cost": c})
        if s is not None and s > rb_score:
            rb_score = s; rb_cost = c; best_file = py
    s, c = judge_local(args.pid, str(sol))
    evidence.append({"file": "solution.py", "rejudged_score": s, "total_cost": c})
    if s is not None and s > rb_score:
        rb_score = s; rb_cost = c; best_file = sol
    (run / "trials_rejudged.json").write_text(json.dumps(evidence, indent=2))
    if best_file is not None:
        try:
            shutil.copy(best_file, best_path); shutil.copy(best_file, sol)
        except Exception: pass

    tx = ""
    for f in glob.glob(f"{cfg}/projects/**/*.jsonl", recursive=True):
        tx += open(f, errors="ignore").read()
    flags = sorted(set(re.findall(r"testdata|\.ans\b|gen_logs|nous_runs|research/solutions", tx)))
    pred = {"pid": args.pid, "track": "research", "agent": "claude-code", "model": args.model,
            "metric": "total_cost ($) lower=better", "valid": (not flags),
            "final_total_cost": rb_cost, "final_score": (round(rb_score, 4) if rb_score >= 0 else None),
            "cost_est_cacheaware": cost, "cost_cli_total_usd": official,
            "turns": turns, "sessions": session, "stop_reason": stop,
            "budget": args.budget, "best_file": (best_file.name if best_file else None),
            "n_trials_rejudged": len(evidence),
            "cheat_audit_hits": flags, "run_dir": str(run)}
    (run / "pred.json").write_text(json.dumps(pred, indent=2))
    print(f"[research] DONE total_cost={rb_cost} score={rb_score} cost_est=${cost} stop={stop} "
          f"audit={'CLEAN' if not flags else flags}", flush=True)


if __name__ == "__main__":
    main()
