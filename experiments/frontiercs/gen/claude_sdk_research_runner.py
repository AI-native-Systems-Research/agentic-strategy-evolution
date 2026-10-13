#!/usr/bin/env python3
"""Claude baseline for research tasks on the SAME stack as Nous: claude_agent_sdk + its bundled CLI.

Identical to Nous on everything generic (model, CLI binary/version, permission mode, disallowed web tools,
default effort/settings, sandbox + access rule, judge daemon, exploit audit, cost ruler); differs only in
what is being tested: Claude Code's default system prompt and one plain task prompt instead of Nous's
methodology and loop. Stops at $50 (shared ruler, gen/cost_meter.py) or max score.

Usage:
  claude_sdk_research_runner.py grammar_fuzzing/seed/sql --slug gf_csdk46 --model claude-opus-4-6 \
     --out-dir runs/gf/claude_sdk_e46 --out artifacts/preds/gf_seed_sql.claude_sdk.e46.json
"""
import argparse, glob, json, os, re, shutil, signal, subprocess, sys, threading, time
from pathlib import Path

import access_rule as A
import cost_meter as C
import nous_research_isolated as N

HERE = Path(__file__).resolve().parent
PY = os.path.expanduser("~/nous_repo/.venv/bin/python")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid"); ap.add_argument("--slug", required=True)
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--budget", type=float, default=50.0)
    ap.add_argument("--max-score", type=float, default=100.0)
    ap.add_argument("--max-turns", type=int, default=400)
    ap.add_argument("--out-dir", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(); pid = a.pid
    run = Path(a.out_dir).resolve(); run.mkdir(parents=True, exist_ok=True)
    (run / "trials").mkdir(exist_ok=True)
    measured = run / "measured"
    djroot = f"/tmp/fcs_rjudge_csdk/{a.slug}"; shutil.rmtree(djroot, ignore_errors=True)
    stop = threading.Event(); N.start_daemon(pid, djroot, stop, measured)

    measure = run / "measure.sh"
    measure.write_text("#!/bin/bash\n"
        f'IN="{djroot}/inbox"; OUT="{djroot}/outbox"\n'
        f'tok="m$$_$RANDOM"\ncp "$1" "$IN/$tok{N.ext(pid)}"\n'
        f'for i in $(seq 1 {1200 if A.is_algo(pid) else 600}); do\n'
        '  if [ -f "$OUT/$tok.score" ]; then cat "$OUT/$tok.score"; rm -f "$OUT/$tok.score"; exit 0; fi\n'
        '  sleep 1\ndone\necho "SCORE: 0.0"\n')
    measure.chmod(0o755)
    sol = N.sol_name(pid)
    if not (run / sol).exists():
        (run / sol).write_text(N.seed_for(pid))
    for f in ("claude_sdk_driver.py", "cost_meter.py"):
        shutil.copy(HERE / f, run / f)

    if A.is_algo(pid):
        prompt = (
            f"Solve Frontier-CS algorithmic problem #{pid} (statement below). Write a C++17 solution in "
            f"solution.cpp in this directory.\n\n"
            f"Measure your score with: `bash {measure} $PWD/solution.cpp` (prints 'SCORE: <0-100>', higher is "
            f"better).\n\nMaximize the score. Keep improving until you are stopped.\n\n"
            f"{A.prompt_rules(pid)}\n\nPROBLEM STATEMENT:\n{A.statement(pid)}")
    else:
      prompt = (
        f"Solve Frontier-CS research problem '{pid}' (README below). Implement `class Solution` in solution.py "
        f"in this directory, exactly per the README API.\n\n"
        f"Measure your score with: `bash {measure} $PWD/solution.py` (prints 'SCORE: <n>', higher is better).\n\n"
        f"Maximize the score. Keep improving until you are stopped.\n\n"
        f"{A.prompt_rules(pid)}\n\nPROBLEM README:\n{A.probdir(pid).joinpath('readme').read_text()}")
    # a session that ends on its own is resumed in the same conversation with no new information
    cont = "Continue."
    (run / "driver_cfg.json").write_text(json.dumps({"run_dir": str(run), "model": a.model, "max_turns": a.max_turns,
        "max_score": a.max_score, "budget": a.budget, "prompt": prompt, "continue": cont}))

    home = os.path.expanduser("~"); rr = os.path.realpath
    paper = rr(HERE.parents[3])
    deny = [f"{home}/frontier", paper, f"{home}/engram_repo", f"{home}/.claude/projects"]
    allow = [rr(run), rr(Path(PY).parents[1])]
    sb = run / "sandbox.sb"
    sb.write_text("(version 1)\n(allow default)\n"
                  + "".join(f'(deny file-read* (subpath "{rr(d)}"))\n' for d in deny)
                  + "".join(f'(allow file-read* (subpath "{p_}"))\n' for p_ in allow)
                  + f'(allow file-read* (regex #"^{re.escape(rr(home))}/\\.claude/projects/{re.escape(C.project_key(run))}"))\n'
                  + A.sbpl_task_access(pid)
                  + A.sbpl_judge_tmp(djroot)
                  + "(allow file-read-metadata)\n")

    env = dict(os.environ); env.pop("ANTHROPIC_AUTH_TOKEN", None)
    t0 = time.time(); capped = False
    with open(run / "driver.log", "a") as dl:
        p = subprocess.Popen(["sandbox-exec", "-f", str(sb), PY, "-u", str(run / "claude_sdk_driver.py"), str(run / "driver_cfg.json")],
                             cwd=str(run), env=env, stdout=dl, stderr=subprocess.STDOUT, start_new_session=True)
        print(f"[csdk] driver pid={p.pid} task={pid} model={a.model} budget=${a.budget} run={run}", flush=True)
        while p.poll() is None:
            time.sleep(15)
            cost = C.transcript_cost(run)
            mfiles = glob.glob(str(measured / f"*{N.ext(pid)}"))
            best = max([float(m.group(1)) for f in mfiles
                        if (m := re.search(r"_score([0-9.]+)\.(py|cpp)$", f))], default=-1.0)
            print(f"[csdk {time.strftime('%H:%M:%S')}] cost=${cost:.2f} best={best} measured={len(mfiles)}", flush=True)
            if cost >= a.budget or best >= a.max_score:
                capped = cost >= a.budget
                print(f"[csdk] stop: cost=${cost:.2f} best={best}", flush=True)
                os.killpg(p.pid, signal.SIGTERM); time.sleep(8)
                if p.poll() is None: os.killpg(p.pid, signal.SIGKILL)
                break
    # SDK `claude` children can outlive the driver; kill any still working in this run dir
    for pid_ in subprocess.run(["pgrep", "-f", "_bundled/claude"], capture_output=True, text=True).stdout.split():
        cwd = subprocess.run(["lsof", "-p", pid_, "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if str(run) in cwd: subprocess.run(["kill", "-9", pid_])
    stop.set()
    cost = C.transcript_cost(run)

    seen, ev, rejected, best, bestf = set(), [], [], -1.0, None
    for f in sorted(glob.glob(str(run / "trials" / f"*{N.ext(pid)}"))) + N._top_measured(measured, 10) + [str(run / sol)]:
        if not Path(f).exists(): continue
        code = Path(f).read_text(errors="ignore")
        if code in seen: continue
        seen.add(code)
        sc, hits = N.judge_clean(pid, code)
        tag = str(Path(f).relative_to(run))
        if hits: rejected.append({"file": tag, "exploits": hits}); continue
        ev.append({"file": tag, "score": sc})
        if sc > best: best, bestf = sc, tag
    pred = {"problem_id": pid, "track": "algorithmic" if A.is_algo(pid) else "research", "agent": "claude-code-sdk", "label": a.slug, "model": a.model,
            "final_score": round(best, 2) if best >= 0 else None, "best_file": bestf,
            "cost_usd_tokenbased": round(cost, 2), "cost_capped": capped, "n_clean": len(ev), "n_rejected": len(rejected),
            "stack": "claude_agent_sdk (same as Nous), Claude Code preset system prompt, bypassPermissions, WebSearch/WebFetch disallowed",
            "isolation": "sandbox-exec: task readme+resources readable (resources/datasets hidden); evaluator, other runs, transcripts denied; sandboxed judge daemon; exploit audit",
            "clean_evidence": ev, "rejected_exploit_candidates": rejected, "elapsed_s": round(time.time() - t0, 1)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(pred, indent=2))
    print(f"CLAUDE-SDK DONE {pid}: final_clean={best} cost=${cost:.2f} -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
