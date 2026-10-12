#!/usr/bin/env python3
"""Claude Code AGENT baseline for RESEARCH tasks (the correct baseline: the same off-the-shelf agent
Nous wraps, minus the Nous methodology). This is `claude -p` with Bash/Read/Write/Edit iterating on a
Python solution.py, NOT a chat-only api loop. Mirrors claude_code_runner.py (algorithmic) but for
research problems scored by the problem's own .evalvenv evaluator.

Isolation (symmetric with nous_research_isolated.py so Nous-vs-Claude is apples-to-apples):
  - the agent runs under sandbox-exec with ~/frontier/Frontier-CS/{research,datasets} reads DENIED, so
    it cannot read the evaluator, reference solutions, or labeled datasets at generation time;
  - scoring goes through an OUT-OF-SANDBOX daemon thread in THIS process: fmeasure.sh drops solution.py
    into an inbox, the daemon scores it with the problem's evaluator and writes the score to an outbox.
    The daemon returns 0 for any solution bearing an exploit signature (import-hook / dataset read /
    engine-internal), so gaming earns no feedback;
  - post-harvest: re-judge every saved trial, reject exploit-signature ones, report best CLEAN score.

Cost: tokens x FIXED $15/$75 (cache-aware), model-INDEPENDENT, identical to claude_code_runner.py and
nous_research_cap.py -> iso-$50 is the same ruler for every arm and tier. Stop at $50 or score ceiling.

Usage:
  claude_code_research_runner.py grammar_fuzzing/seed/sql --slug gf_s45 --model aws/claude-sonnet-4-5 \
    --budget 50 --out-dir runs/gf/claude_s45 --out artifacts/preds/gf_seed_sql.claude.s45.json
"""
import argparse, glob, json, os, re, shlex, shutil, subprocess, tempfile, threading, time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FR_ROOT = FRONTIER
CLI = os.environ.get("CLAUDE_CLI_PATH", os.path.expanduser(
    "~/nous_repo/.venv/lib/python3.11/site-packages/claude_agent_sdk/_bundled/claude"))
R_IN, R_OUT, R_CW, R_CR = 15/1e6, 75/1e6, 18.75/1e6, 1.5/1e6  # same fixed rates as the other arms

EXPLOIT_SIGS = [
    (r"sys\.meta_path", "import-hook (sys.meta_path)"),
    (r"find_spec\s*\(", "import-hook (find_spec)"),
    (r"importlib\.util\.find_spec|exec_module|module_from_spec", "import machinery to reach internals"),
    (r"sql_engine\.(parser|tokenizer|ast_nodes)", "direct engine-internal access"),
    (r"\b_match\b|TokenType\.", "parser/tokenizer internals"),
    (r"routerbench", "reads labeled RouterBench dataset"),
    (r"reference_data\.csv", "reads reference_data.csv (labels)"),
    (r"_test\.csv|routerbench_0shot_test", "reads labeled test split"),
    (r"read_csv|read_pickle|read_parquet", "reads a data file (possible label leak)"),
    (r"/datasets/|resources/datasets", "accesses datasets directory"),
]
def exploit_hits(code):
    return [d for pat, d in EXPLOIT_SIGS if re.search(pat, code)]

def probdir(pid): return Path(FRONTIER) / "research" / "problems" / str(pid)
def evalpy(pid):  return probdir(pid) / ".evalvenv" / "bin" / "python3"
def statement(pid):
    p = probdir(pid) / "readme"; return p.read_text() if p.exists() else f"(research problem {pid})"


def transcript_cost(cfg_dir):
    cost = 0.0; turns = 0
    for f in glob.glob(f"{cfg_dir}/projects/**/*.jsonl", recursive=True):
        for ln in open(f, errors="ignore"):
            try: d = json.loads(ln)
            except Exception: continue
            u = (d.get("message") or {}).get("usage") if isinstance(d.get("message"), dict) else None
            if not u: continue
            cost += (u.get("input_tokens", 0)*R_IN + u.get("output_tokens", 0)*R_OUT
                     + u.get("cache_creation_input_tokens", 0)*R_CW + u.get("cache_read_input_tokens", 0)*R_CR)
            turns += 1
    return round(cost, 4), turns


def judge_clean(pid, sol_path, timeout=600):
    """Re-judge a solution file ONLY if no exploit signatures; return (score_or_None, hits)."""
    try: code = Path(sol_path).read_text(errors="ignore")
    except Exception: return None, ["unreadable"]
    hits = exploit_hits(code)
    if hits: return None, hits
    pd = probdir(pid)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of: out = of.name
    try:
        subprocess.run(f"{shlex.quote(str(evalpy(pid)))} {shlex.quote(str(pd/'evaluator.py'))} "
                       f"--solution {shlex.quote(str(Path(sol_path).resolve()))} --out {shlex.quote(out)}",
                       shell=True, cwd=str(pd), capture_output=True, text=True, timeout=timeout)
        d = json.loads(Path(out).read_text())
        s = float(d.get("score", 0.0)) if (not d.get("error") and d.get("runs_successfully", 0.0) == 1.0) else 0.0
    except Exception: s = 0.0
    finally:
        try: os.unlink(out)
        except OSError: pass
    return s, []


def start_daemon(pid, root, stop_evt):
    inbox = Path(root)/"inbox"; outbox = Path(root)/"outbox"
    inbox.mkdir(parents=True, exist_ok=True); outbox.mkdir(parents=True, exist_ok=True)
    pd = probdir(pid)
    def score_file(f):
        try:
            if exploit_hits(Path(f).read_text(errors="ignore")): return 0.0
        except Exception: pass
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of: out = of.name
        try:
            subprocess.run(f"{shlex.quote(str(evalpy(pid)))} {shlex.quote(str(pd/'evaluator.py'))} "
                           f"--solution {shlex.quote(str(f))} --out {shlex.quote(out)}",
                           shell=True, cwd=str(pd), capture_output=True, text=True, timeout=600)
            d = json.loads(Path(out).read_text())
            return d.get("score", 0.0) if (not d.get("error") and d.get("runs_successfully", 0.0) == 1.0) else 0.0
        except Exception: return 0.0
        finally:
            try: os.unlink(out)
            except OSError: pass
    def loop():
        while not stop_evt.is_set():
            for f in sorted(glob.glob(str(inbox/"*.py"))):
                tok = Path(f).stem
                try: s = score_file(f)
                except Exception: s = 0.0
                (outbox/f"{tok}.score").write_text(f"SCORE: {s}\n")
                try: os.unlink(f)
                except OSError: pass
            time.sleep(1)
    threading.Thread(target=loop, daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--model", default="aws/claude-opus-5")
    ap.add_argument("--budget", type=float, default=50.0)
    ap.add_argument("--max-score", type=float, default=100.0)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pid = a.pid
    run = Path(a.out_dir).resolve(); run.mkdir(parents=True, exist_ok=True)
    cfg = run/"cfg"; cfg.mkdir(exist_ok=True)
    trials = run/"trials"; trials.mkdir(exist_ok=True)
    stmt = statement(pid)

    # out-of-sandbox scoring daemon
    djroot = f"/tmp/fcs_rjudge_claude/{a.slug}"; stop = threading.Event(); start_daemon(pid, djroot, stop)

    # sandbox: deny the benchmark research tree + datasets; allow the agent's own run dir + /tmp
    sb = run/"sandbox.sb"
    sb.write_text("(version 1)\n(allow default)\n"
                  f'(deny file-read* (subpath "{FR_ROOT}/research"))\n'
                  f'(deny file-read* (subpath "{FR_ROOT}/datasets"))\n')
    sandbox_prefix = ([] if os.environ.get("NOUS_FCS_NO_SANDBOX") else ["sandbox-exec", "-f", str(sb)])

    # fmeasure: inbox/outbox handshake (no direct ~/frontier access)
    measure = run/"measure.sh"
    measure.write_text("#!/bin/bash\n"
        "# fmeasure: score solution.py via the out-of-sandbox judge daemon -> prints 'SCORE: <n>'\n"
        f'IN="{djroot}/inbox"; OUT="{djroot}/outbox"\n'
        'tok="m$$_$RANDOM"\n'
        'cp "$1" "$IN/$tok.py"\n'
        'for i in $(seq 1 600); do\n'
        '  if [ -f "$OUT/$tok.score" ]; then cat "$OUT/$tok.score"; rm -f "$OUT/$tok.score"; exit 0; fi\n'
        '  sleep 1\n'
        'done\necho "SCORE: 0.0"\n')
    measure.chmod(0o755)
    (run/"solution.py").write_text("class Solution:\n    def solve(self, *a, **k):\n        raise NotImplementedError\n")

    prompt = (
        f"You are solving Frontier-CS research problem '{pid}'. Read the README below: it states the exact "
        f"objective, the scoring metric, and the required Solution API. Edit solution.py in THIS directory to "
        f"implement `class Solution` EXACTLY per the README API (same method name/signature/return type).\n\n"
        f"MEASURE your score with this ONE command: `bash {measure} $PWD/solution.py` -> prints 'SCORE: <n>' "
        f"(higher is better). Iterate: improve solution.py and re-measure to MAXIMIZE the score. Do NOT stop "
        f"until SCORE reaches {a.max_score:g}; while below it, keep trying new strategies.\n\n"
        f"PERSIST EVERY ATTEMPT: right after each measure, copy the exact solution.py you scored to "
        f"trials/attempt_<N>_score_<SCORE>.py (N=1,2,3...). Create trials/ if needed; never overwrite earlier ones.\n\n"
        f"RULES (enforced by a sandbox): you CANNOT read the problem's internal files (engine source, "
        f"evaluator, datasets, reference solutions). Solve legitimately: your code must do the real work. Do NOT "
        f"use import hooks / sys.meta_path, call engine internals, or read dataset/label files - such solutions "
        f"are rejected and score 0.\n\nPROBLEM README:\n{stmt}")
    cont = ("Your current solution.py scored {score} on `bash " + str(measure) + " $PWD/solution.py`, below the "
            "ceiling, so you are NOT finished. Try a genuinely different/improved approach, edit solution.py, "
            "re-measure, and save the attempt to trials/. Keep pushing the score up.")

    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(cfg)
    for k in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"):
        env[k] = "1"
    env.setdefault("CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS", "90000")
    env.setdefault("API_TIMEOUT_MS", "300000")
    env.setdefault("CLAUDE_STREAM_IDLE_TIMEOUT_MS", "300000")
    env.setdefault("BUN_FEATURE_FLAG_DISABLE_IO_POOL", "1")
    env.setdefault("CLAUDE_CODE_MAX_RETRIES", "40")
    env.setdefault("CLAUDE_CODE_CONNECT_TIMEOUT_MS", "20000")
    base_flags = ["--output-format", "stream-json", "--verbose", "--model", a.model,
                  "--permission-mode", "bypassPermissions",
                  "--allowedTools", "Bash", "Read", "Write", "Edit",
                  "--disallowedTools", "WebSearch", "WebFetch",
                  "--max-turns", str(a.max_turns)]

    def best_trial():
        best = -1.0
        for f in glob.glob(str(trials/"*.py")):
            s, _ = judge_clean(pid, f)
            if s is not None and s > best: best = s
        return best

    t0 = time.time(); stop_reason = None; session = 0; refuse = 0; cost = 0.0; turns = 0; best = -1.0
    while True:
        if best >= a.max_score: stop_reason = "max_score"; break
        if cost >= a.budget: stop_reason = "budget"; break
        if refuse >= 5: stop_reason = "agent_will_not_continue"; break
        session += 1; cost_before = cost
        if session == 1:
            cmd = sandbox_prefix + [CLI, "-p", prompt] + base_flags
        else:
            msg = cont.format(score=f"{best:g}" if best >= 0 else "0")
            cmd = sandbox_prefix + [CLI, "--continue", "-p", msg] + base_flags
        with open(run/"stream.jsonl", "a") as log:
            proc = subprocess.Popen(cmd, cwd=str(run), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            print(f"[claude-research] session={session} pid={proc.pid} task={pid} budget=${a.budget} best={best}", flush=True)
            killed = False
            while proc.poll() is None:
                time.sleep(10)
                cost, turns = transcript_cost(cfg)
                print(f"[cr {time.strftime('%H:%M')}] s{session} turns={turns} cost=${cost} best={best}", flush=True)
                if cost >= a.budget:
                    proc.terminate()
                    try: proc.wait(10)
                    except Exception: proc.kill()
                    killed = True; break
        cost, turns = transcript_cost(cfg)
        b = best_trial()
        if b > best: best = b
        print(f"[claude-research] session={session} ended best={best} cost=${cost}", flush=True)
        refuse = refuse + 1 if (cost - cost_before) < 0.05 else 0
        if killed: stop_reason = "budget"; break
    stop.set()

    # harvest: re-judge every trial (clean), audit exploits
    ev = []; rejected = []; final = -1.0; bestf = None
    for f in sorted(glob.glob(str(trials/"*.py"))) + [str(run/"solution.py")]:
        if not Path(f).exists(): continue
        s, hits = judge_clean(pid, f)
        tag = os.path.basename(f)
        if hits: rejected.append({"file": tag, "exploits": hits})
        else:
            ev.append({"file": tag, "score": s})
            if s is not None and s > final: final = s; bestf = tag
    pred = {"problem_id": pid, "track": "research", "agent": "claude-code", "label": a.slug, "model": a.model,
            "final_score": (round(final, 2) if final >= 0 else None), "cost_usd_tokenbased": round(cost, 2),
            "cost_rates_per_mtok": {"in": R_IN*1e6, "out": R_OUT*1e6}, "stop_reason": stop_reason,
            "sessions": session, "best_file": bestf, "n_clean": len(ev), "n_rejected": len(rejected),
            "isolation": "claude -p agent under sandbox-exec deny ~/frontier/{research,datasets}; measure only via out-of-sandbox judge daemon; post-harvest exploit audit",
            "rejected_exploit_candidates": rejected, "clean_evidence": ev, "elapsed_s": round(time.time()-t0, 1)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(pred, indent=2))
    print(f"CLAUDE-RESEARCH DONE {pid}: final_clean={final} cost=${cost} sessions={session} "
          f"rejected={len(rejected)} stop={stop_reason} -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
