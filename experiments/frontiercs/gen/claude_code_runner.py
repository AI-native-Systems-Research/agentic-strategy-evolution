#!/usr/bin/env python3
"""Claude baseline = the plain Claude Code CLI attacking a Frontier-CS problem, single session.

Design (see experiments/frontiercs/README.md):
- No Nous loop, no Engram harness. The plain `claude -p` CLI, opus-4-6, with Bash/Read/Write/Edit
  tools and a measure.sh that runs the official judge. The agent iterates to maximize the 0-100 score.
- Stopping rule = budget OR max score, nothing else. We run until cumulative cost >= $50 OR the judge
  score reaches the ceiling (--max-score, default 100; gates are all-or-nothing but still top out at
  100). The agent is NOT allowed to self/plateau-stop: when a `claude -p` session yields below the
  ceiling with budget remaining, we RESUME it (`--continue`) with a push prompt and keep going. (A
  safety valve stops only an agent that will not engage at all -- a session adding ~no cost -- which
  is distinct from a plateau: an agent that keeps spending but can't improve runs on to the budget.)
- Self-contained run folder (isolation + debug + persist): only statement.txt + measure.sh are placed
  in the agent's cwd. Everything (solution, transcript, cost, pred) stays in that folder.
- Trial persistence: every scored solution is copied to trials/t<n>.score<s>.cpp and logged to
  trials.jsonl; the best-scoring one is kept as solution.best.cpp and is what pred.json reports.
- Live $50 cap: Claude Code writes a per-turn transcript jsonl (full usage incl cache) under
  CLAUDE_CONFIG_DIR; we tail it, accumulate cost (cumulative across resumed sessions), and KILL the
  CLI the instant it crosses the budget.
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
    ap.add_argument("--max-score", type=float, default=100.0,
                    help="stop early only when the judge score reaches this ceiling")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    run = Path(args.out_dir).resolve(); run.mkdir(parents=True, exist_ok=True)
    cfg = run / "cfg"; cfg.mkdir(exist_ok=True)
    stmt_src = Path(FRONTIER) / "algorithmic" / "problems" / str(args.pid) / "statement.txt"
    shutil.copy(stmt_src, run / "statement.txt")
    # ISOLATED judge: measure.sh does NOT touch the benchmark tree. It submits solution.cpp to the
    # out-of-sandbox judge daemon (gen/judge_server.py) via a plain file drop and reads back the SCORE.
    # The agent runs under sandbox-exec with ~/frontier reads DENIED, so it cannot see hidden testdata.
    JUDGE_ROOT = os.environ.get("FCS_JUDGE_ROOT", "/tmp/fcs_judge")
    for sub in ("inbox", "outbox", "done"):
        Path(JUDGE_ROOT, sub).mkdir(parents=True, exist_ok=True)
    measure = run / "measure.sh"
    measure.write_text(
        "#!/bin/bash\n"
        "# Submit solution.cpp to the official judge and print SCORE: <0-100> (higher is better).\n"
        f'JR="{JUDGE_ROOT}"\n'
        f'tok="p{args.pid}__$(date +%s%N)_$RANDOM"\n'
        f'cp "{run}/solution.cpp" "$JR/inbox/$tok.cpp"\n'
        'for i in $(seq 1 1200); do\n'
        '  if [ -f "$JR/outbox/$tok.score" ]; then\n'
        '    cat "$JR/outbox/$tok.score"; rm -f "$JR/outbox/$tok.score"; exit 0\n'
        '  fi\n'
        '  sleep 0.5\n'
        'done\n'
        'echo "SCORE: ERR (judge timeout)"\n')
    measure.chmod(0o755)
    # sandbox profile: deny the agent ALL reads under ~/frontier (hidden testdata + answer files +
    # prior solutions under gen_logs/nous_runs all live there). Everything else stays allowed.
    sb_profile = run / "sandbox.sb"
    frontier_root = os.path.realpath(os.path.expanduser("~/frontier"))
    sb_profile.write_text("(version 1)\n(allow default)\n"
                          f'(deny file-read* (subpath "{frontier_root}"))\n')
    sandbox_prefix = ([] if os.environ.get("NOUS_FCS_NO_SANDBOX")
                      else ["sandbox-exec", "-f", str(sb_profile)])
    (run / "solution.cpp").write_text("// write your C++17 solution here\n")

    prompt = (
        f"You are solving competitive-programming optimization problem Frontier-CS algorithmic #{args.pid}. "
        "Read statement.txt in this directory. Write your C++17 solution to solution.cpp here. "
        "To check your score, run `./measure.sh` — it compiles solution.cpp, runs the OFFICIAL judge, "
        "and prints `SCORE: <0-100>` (higher is better; continuous partial credit). "
        "Iterate: try algorithms/optimizations and re-run ./measure.sh to maximize the score. "
        f"Do NOT stop until you reach SCORE: {args.max_score:g} (the ceiling). As long as the score is "
        "below the ceiling there is always more to try: a better algorithm, a tighter heuristic, a "
        "parameter sweep, an edge-case fix. Never conclude the solution is 'good enough' or that you "
        "'cannot improve' — keep generating and testing new ideas. "
        "PERSIST EVERY ATTEMPT: immediately after each `./measure.sh` run, copy the exact solution.cpp "
        "you just scored into the `trials/` directory, named `trials/attempt_<N>_score_<SCORE>.cpp` "
        "(N = 1,2,3... in order; SCORE = the number measure.sh printed). Create `trials/` if needed and "
        "NEVER delete or overwrite earlier attempts. This is required so every score can be reproduced. "
        "RULES: solve it algorithmically; do NOT read, open, or use the judge's hidden test data or "
        "answer files anywhere on the system, and do NOT copy any pre-existing solution. "
        "Leave your best solution in solution.cpp.")
    # Continuation push used to resume the SAME session when the agent yields below the ceiling+budget.
    cont_prompt = (
        f"Your current solution.cpp scores {{score}}/{args.max_score:g} on ./measure.sh, which is below "
        "the ceiling, so you are NOT finished. Do not stop. Try a genuinely different or improved "
        "approach now (new algorithm, stronger heuristic, parameter tuning, or fixing a weak case), "
        "edit solution.cpp, and re-run ./measure.sh. Save each scored attempt to "
        "`trials/attempt_<N>_score_<SCORE>.cpp` as before. Keep pushing the score up.")

    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(cfg)
    for k in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
              "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
        env[k] = "1"
    # Root cause of the CLI hang (diagnosed 2026-10-06, same bug as the Nous "SDK hang"): FRESH
    # connections to the gateway are fast (curl: 3 trivial streaming probes 1.4-2.2s; 166KB req and
    # max_tokens=64000 <5s), but the CLI reuses a keep-alive socket that the gateway/LB silently drops
    # while local tools/compile run between turns. The next request reuses the dead socket and hangs
    # with NO response (api_retry error "unknown", status null). A 900s timeout makes each dead socket
    # cost 15 min before it is shed; a 60s timeout churns during the gateway's occasional genuine slow
    # windows (one trivial probe hit 35s). Middle ground: a 90s first-byte timeout sheds a dead socket
    # in ~90s so the retry dials a fresh (fast) connection, while still clearing the worst slow window
    # observed (35s). Keep idle/API generous since a flowing stream is healthy. If this still churns
    # while fresh curl is fast, the next lever is upgrading the bundled CLI (newer undici retry/keep-
    # alive handling) -- but that also changes the Nous binary, so re-baseline Nous if we do it.
    env.setdefault("CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS", "90000")
    env.setdefault("API_TIMEOUT_MS", "300000")
    env.setdefault("CLAUDE_STREAM_IDLE_TIMEOUT_MS", "300000")
    # THE key fix (verified 2026-10-06): the bundled CLI is a Bun binary; its HTTP connection pool
    # reuses a keep-alive socket that the gateway/LB silently drops between turns (during local tool
    # execution). The next request reuses the dead socket and the retries never recover, even though
    # fresh curl connections stay fast -- every run wedged at ~turn 5. Disabling Bun's IO/connection
    # pool forces a fresh connection per request and fixed it: p0 (wedged at t=5 across ~6 relaunches)
    # crossed t=6+ with ZERO retries once this was set, while a pool-enabled control stayed stuck.
    # MAX_RETRIES raised so a run survives the gateway's slow windows instead of dying at the default
    # 10. (Likely also fixes the Nous "SDK hang" -- same Bun binary; apply there too.)
    env.setdefault("BUN_FEATURE_FLAG_DISABLE_IO_POOL", "1")
    env.setdefault("CLAUDE_CODE_MAX_RETRIES", "40")
    env.setdefault("CLAUDE_CODE_CONNECT_TIMEOUT_MS", "20000")
    base_flags = ["--output-format", "stream-json", "--verbose", "--model", args.model,
                  "--permission-mode", "bypassPermissions",
                  "--allowedTools", "Bash", "Read", "Write", "Edit",
                  "--max-turns", str(args.max_turns)]
    t0 = time.time()
    sol = run / "solution.cpp"
    trials_dir = run / "trials"; trials_dir.mkdir(exist_ok=True)
    trials_log = run / "trials.jsonl"
    best_path = run / "solution.best.cpp"
    best_score = -1.0
    # Stopping rule (per README §1): run until cumulative cost >= budget OR score hits the ceiling
    # (max_score, 100 for every algorithmic task incl. the all-or-nothing gates). The agent is NOT
    # allowed to self/plateau-stop: when a `claude -p` session yields below the ceiling with budget
    # left, we RESUME it (`--continue`) with a push prompt and keep going. `refuse` is a safety valve
    # ONLY for an agent that will not engage at all (a session that adds ~no cost); it is deliberately
    # distinct from a plateau (an agent that keeps spending but can't improve runs on to the budget).
    stop = None; session = 0; refuse = 0; cost = 0.0; turns = 0
    while True:
        if best_score >= args.max_score:
            stop = "max_score"; break
        if cost >= args.budget:
            stop = "budget"; break
        if refuse >= 5:
            stop = "agent_will_not_continue"; break
        session += 1
        cost_before = cost
        if session == 1:
            cmd = sandbox_prefix + [CLI, "-p", prompt] + base_flags
        else:
            msg = cont_prompt.format(score=f"{best_score:g}" if best_score >= 0 else "0")
            cmd = sandbox_prefix + [CLI, "--continue", "-p", msg] + base_flags
        with open(run / "stream.jsonl", "a") as log:
            proc = subprocess.Popen(cmd, cwd=str(run), env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT)
            print(f"[claude] session={session} pid={proc.pid} task=p{args.pid} "
                  f"budget=${args.budget} best={best_score} dir={run}", flush=True)
            killed_budget = False
            while proc.poll() is None:
                time.sleep(10)
                cost, turns = transcript_cost(cfg)
                print(f"[claude {time.strftime('%H:%M')}] s{session} turns={turns} "
                      f"cost=${cost} best={best_score}", flush=True)
                if cost >= args.budget:
                    print(f"[claude] cost ${cost} >= ${args.budget} -> KILL", flush=True)
                    proc.terminate()
                    try: proc.wait(10)
                    except Exception: proc.kill()
                    killed_budget = True
                    break
        cost, turns = transcript_cost(cfg)
        # score + persist this trial (every scored solution is kept for later reuse)
        score = judge(args.pid, str(sol))
        if score is not None:
            dst = trials_dir / f"t{session}.score{score:g}.cpp"
            try: shutil.copy(sol, dst)
            except Exception: pass
            with open(trials_log, "a") as tl:
                tl.write(json.dumps({"session": session, "score": score, "cost_cumulative": cost,
                                     "turns": turns, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
            if score > best_score:
                best_score = score
                try: shutil.copy(sol, best_path)
                except Exception: pass
        print(f"[claude] session={session} ended score={score} best={best_score} cost=${cost}",
              flush=True)
        # refusal detection: a session that added negligible cost means the agent would not engage;
        # this is NOT a plateau (a working-but-stuck agent still spends and runs to budget).
        refuse = refuse + 1 if (cost - cost_before) < 0.05 else 0
        if killed_budget:
            stop = "budget"; break

    # official cost from the CLI's own result messages (best-effort; cost_est is authoritative)
    official = None
    for ln in open(run / "stream.jsonl", errors="ignore"):
        try:
            d = json.loads(ln)
            if d.get("type") == "result" and d.get("total_cost_usd") is not None:
                official = d["total_cost_usd"]
        except Exception:
            pass
    # EVIDENCE: independently re-judge every persisted attempt (agent-saved trials/attempt_*.cpp and
    # our session snapshots) on our go-judge. We never trust the agent's self-reported score; the saved
    # .cpp files are the evidence and this is their reproduction. final_score = best re-judged solution.
    evidence = []
    best_file = None
    for cpp in sorted(trials_dir.glob("*.cpp")):
        sc = judge(args.pid, str(cpp))
        evidence.append({"file": cpp.name, "rejudged_score": sc})
        if sc is not None and sc > best_score:
            best_score = sc
            best_file = cpp
    # also re-judge the final solution.cpp
    sc_final = judge(args.pid, str(sol))
    evidence.append({"file": "solution.cpp", "rejudged_score": sc_final})
    if sc_final is not None and sc_final > best_score:
        best_score = sc_final
        best_file = sol
    (run / "trials_rejudged.json").write_text(json.dumps(evidence, indent=2))
    reproduced_best = best_score if best_score >= 0 else sc_final
    # leave the best (independently re-judged) solution in solution.best.cpp and solution.cpp
    if best_file is not None:
        try:
            shutil.copy(best_file, best_path)
            shutil.copy(best_file, sol)
        except Exception:
            pass
    # What the AGENT CLAIMED (its own ./measure.sh SCORE outputs in the transcript). We do NOT credit a
    # claim we cannot reproduce from a persisted artifact; if the agent claimed higher than we can
    # reproduce, that reproducibility gap is itself a Claude-baseline limitation (Nous always leaves a
    # reproducible artifact). We report the reproduced best; the gap is recorded for the paper.
    claimed = []
    for ln in open(run / "stream.jsonl", errors="ignore"):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if d.get("type") == "user":
            for c in (d.get("message", {}).get("content") or []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    s = c.get("content"); s = s if isinstance(s, str) else json.dumps(s)
                    claimed += [float(x) for x in re.findall(r"SCORE:\s*([0-9.]+)", s)]
    agent_claimed_best = max(claimed) if claimed else None
    repro_gap = (round(agent_claimed_best - reproduced_best, 3)
                 if (agent_claimed_best is not None and reproduced_best is not None
                     and agent_claimed_best > reproduced_best) else 0.0)
    # final_score = the score we can REPRODUCE from a persisted artifact (the trusted number)
    final_score = reproduced_best
    # cheating audit: grep transcript for forbidden access
    tx = ""
    for f in glob.glob(f"{cfg}/projects/**/*.jsonl", recursive=True):
        tx += open(f, errors="ignore").read()
    flags = sorted(set(re.findall(r"testdata|\.ans\b|gen_logs|nous_runs|/problems/\d+/testdata", tx)))
    pred = {"pid": args.pid, "agent": "claude-code", "model": args.model,
            "final_score": final_score, "reproduced_best": reproduced_best,
            "agent_claimed_best": agent_claimed_best, "repro_gap": repro_gap,
            "cost_est_cacheaware": cost, "cost_cli_total_usd": official,
            "turns": turns, "sessions": session,
            "trials_rejudged": len(evidence), "best_file": best_file.name if best_file else None,
            "elapsed_sec": round(time.time() - t0, 1), "stop_reason": stop,
            "budget": args.budget, "max_score": args.max_score,
            "cheat_audit_hits": flags, "run_dir": str(run)}
    (run / "pred.json").write_text(json.dumps(pred, indent=2))
    print(f"[claude] DONE best_score={final_score} cost_est=${cost} cli_cost=${official} "
          f"sessions={session} stop={stop} audit={'CLEAN' if not flags else flags}", flush=True)


if __name__ == "__main__":
    main()
