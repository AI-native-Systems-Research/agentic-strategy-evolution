#!/usr/bin/env python3
"""Claude baseline = the plain Claude Code CLI attacking a Frontier-CS problem, single session.

Design (see experiments/frontiercs/README.md):
- No Nous loop, no Engram harness. One `claude -p` session, opus-4-6, with Bash/Read/Write/Edit tools
  and a measure.sh that runs the official judge. The agent iterates to maximize the 0-100 score.
- Self-contained run folder (isolation + debug + persist): only statement.txt + measure.sh are placed
  in the agent's cwd. Everything (solution, transcript, cost, pred) stays in that folder.
- Live $50 cap: Claude Code writes a per-turn transcript jsonl (full usage incl cache) under
  CLAUDE_CONFIG_DIR; we tail it, accumulate cost, and KILL the CLI the instant it crosses the budget.
- Auth: it's the bundled CLI, so we strip the inherited ANTHROPIC_AUTH_TOKEN (else gateway 401/hang).
- Audit: the transcript logs every bash command; we grep it for testdata/.ans/gen_logs to prove the
  run didn't cheat.

Usage:
  env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=.. ANTHROPIC_API_KEY=.. \
    python claude_code_runner.py <pid> --budget 50 --out-dir experiments/frontiercs/runs/p<pid>/claude
"""
import argparse, glob, json, os, re, shutil, subprocess, time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")
CLI = os.environ.get("CLAUDE_CLI_PATH", os.path.expanduser(
    "~/nous_repo/.venv/lib/python3.11/site-packages/claude_agent_sdk/_bundled/claude"))
# Anthropic opus pricing (cache-aware) for the live estimate; final official cost = CLI total_cost_usd.
R_IN, R_OUT, R_CW, R_CR = 15/1e6, 75/1e6, 18.75/1e6, 1.5/1e6


def transcript_cost(cfg_dir):
    """Sum per-turn usage from the CLI transcript -> live cost estimate (cache-aware)."""
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
            cost += (u.get("input_tokens", 0) * R_IN + u.get("output_tokens", 0) * R_OUT
                     + u.get("cache_creation_input_tokens", 0) * R_CW
                     + u.get("cache_read_input_tokens", 0) * R_CR)
            turns += 1
    return round(cost, 4), turns


def judge(pid, sol):
    r = subprocess.run(f"{FEVAL} eval algorithmic {pid} {sol} --json", shell=True,
                       capture_output=True, text=True, cwd=FRONTIER, timeout=900)
    best = None
    for m in re.findall(r'"score"\s*:\s*([0-9.]+)', r.stdout + r.stderr):
        v = float(m); best = v if best is None else max(best, v)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int)
    ap.add_argument("--budget", type=float, default=50.0)
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    run = Path(args.out_dir).resolve(); run.mkdir(parents=True, exist_ok=True)
    cfg = run / "cfg"; cfg.mkdir(exist_ok=True)
    stmt_src = Path(FRONTIER) / "algorithmic" / "problems" / str(args.pid) / "statement.txt"
    shutil.copy(stmt_src, run / "statement.txt")
    measure = run / "measure.sh"
    measure.write_text(
        "#!/bin/bash\n# Official judge for this problem. Prints SCORE: <0-100>. Higher is better.\n"
        f'out=$({FEVAL} eval algorithmic {args.pid} "{run}/solution.cpp" --json 2>/dev/null)\n'
        'echo "$out" | python3 -c "import sys,re;t=sys.stdin.read();m=re.findall(r\'\\"score\\"\\s*:\\s*([0-9.]+)\',t);print(\'SCORE:\', m[-1] if m else \'ERR\')"\n')
    measure.chmod(0o755)
    (run / "solution.cpp").write_text("// write your C++17 solution here\n")

    prompt = (
        f"You are solving competitive-programming optimization problem Frontier-CS algorithmic #{args.pid}. "
        "Read statement.txt in this directory. Write your C++17 solution to solution.cpp here. "
        "To check your score, run `./measure.sh` — it compiles solution.cpp, runs the OFFICIAL judge, "
        "and prints `SCORE: <0-100>` (higher is better; continuous partial credit). "
        "Iterate: try algorithms/optimizations and re-run ./measure.sh to maximize the score. "
        "Keep working and trying new ideas until you genuinely cannot improve further. "
        "RULES: solve it algorithmically; do NOT read, open, or use the judge's hidden test data or "
        "answer files anywhere on the system, and do NOT copy any pre-existing solution. "
        "Leave your best solution in solution.cpp when finished.")

    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(cfg)
    for k in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
              "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
        env[k] = "1"
    cmd = [CLI, "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", args.model,
           "--permission-mode", "bypassPermissions", "--allowedTools", "Bash", "Read", "Write", "Edit",
           "--max-turns", str(args.max_turns)]
    t0 = time.time()
    log = open(run / "stream.jsonl", "w")
    proc = subprocess.Popen(cmd, cwd=str(run), env=env, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT)
    print(f"[claude] pid={proc.pid} task=p{args.pid} budget=${args.budget} dir={run}", flush=True)
    stop = "completed"
    while proc.poll() is None:
        time.sleep(10)
        cost, turns = transcript_cost(cfg)
        print(f"[claude {time.strftime('%H:%M')}] turns={turns} cost=${cost}", flush=True)
        if cost >= args.budget:
            print(f"[claude] cost ${cost} >= ${args.budget} -> KILL", flush=True)
            proc.terminate();
            try: proc.wait(10)
            except Exception: proc.kill()
            stop = "budget"
            break
    cost, turns = transcript_cost(cfg)
    # official cost from the CLI's own result message
    official = None
    for ln in open(run / "stream.jsonl", errors="ignore"):
        try:
            d = json.loads(ln)
            if d.get("type") == "result" and d.get("total_cost_usd") is not None:
                official = d["total_cost_usd"]
        except Exception:
            pass
    score = judge(args.pid, str(run / "solution.cpp"))
    # cheating audit: grep transcript for forbidden access
    tx = ""
    for f in glob.glob(f"{cfg}/projects/**/*.jsonl", recursive=True):
        tx += open(f, errors="ignore").read()
    flags = sorted(set(re.findall(r"testdata|\.ans\b|gen_logs|nous_runs|/problems/\d+/testdata", tx)))
    pred = {"pid": args.pid, "agent": "claude-code", "model": args.model,
            "final_score": score, "cost_est_cacheaware": cost, "cost_cli_total_usd": official,
            "turns": turns, "elapsed_sec": round(time.time() - t0, 1), "stop_reason": stop,
            "budget": args.budget, "cheat_audit_hits": flags, "run_dir": str(run)}
    (run / "pred.json").write_text(json.dumps(pred, indent=2))
    print(f"[claude] DONE score={score} cost_est=${cost} cli_cost=${official} stop={stop} "
          f"audit={'CLEAN' if not flags else flags}", flush=True)


if __name__ == "__main__":
    main()
