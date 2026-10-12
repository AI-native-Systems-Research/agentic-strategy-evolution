"""Frontier-CS algorithmic track: Nous (as-is) launcher, judged on our go-judge.

Driven by nous_cap_launch.py (token-based $50 cap). Nous runs under sandbox-exec (Frontier-CS tree
denied) and scores only via the out-of-sandbox judge daemon (judge_server.py).

Usage:
  python frontier_gen_costbudget.py <problem_id> --agent nous --out preds/<id>.nous.json --nous-iters 12
"""
import argparse, json, os, re, shlex, subprocess, tempfile, time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")
NOUS_BIN = os.environ.get("NOUS_BIN", os.path.expanduser("~/nous_repo/.venv/bin/nous"))
NOUS_REPO = os.environ.get("NOUS_REPO", os.path.expanduser("~/nous_repo"))
SEED = "#include <bits/stdc++.h>\nusing namespace std;\nint main(){return 0;}\n"


def sh(cmd, timeout=None, cwd=None, env=None):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout, cwd=cwd, env=env)


def statement(pid):
    p = Path(FRONTIER) / "algorithmic" / "problems" / str(pid) / "statement.txt"
    return p.read_text() if p.exists() else sh(f"{FEVAL} show algorithmic {pid}").stdout


def evaluate(pid, sol_path, timeout=600):
    """Return (score, status, raw) by invoking the judge on sol_path."""
    r = sh(f"{FEVAL} eval algorithmic {pid} {shlex.quote(str(sol_path))} --json", timeout=timeout, cwd=FRONTIER)
    blob = r.stdout + "\n" + r.stderr
    # the JSON object may be embedded among log lines; grab the last {...} with "score"
    best = None
    for m in re.finditer(r"\{[^{}]*\"score\"[^{}]*\}", blob):
        try:
            best = json.loads(m.group(0))
        except Exception:
            pass
    if best is None:  # try a looser whole-line parse
        for line in reversed(blob.splitlines()):
            line = line.strip()
            if line.startswith("{") and "score" in line:
                try:
                    best = json.loads(line); break
                except Exception:
                    pass
    if best is None:
        return None, "parse_error", blob[-500:]
    return best.get("score"), best.get("status", "?"), best



def run_nous(pid, stmt, ws, model, logdir, nous_iters, label):
    import yaml
    ws = Path(ws); ws.mkdir(parents=True, exist_ok=True)
    (ws / "solution.cpp").write_text(SEED)
    sh("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed", cwd=str(ws))
    # Clean measure wrapper: the executor runs ONE simple command that prints just "SCORE: <n>",
    # instead of orchestrating `frontier eval` + JSON parsing itself (which is slow/error-prone).
    # ISOLATION: the agent runs under sandbox-exec with reads of the benchmark tree (~/frontier/
    # Frontier-CS, which holds testdata/*.ans answer files) DENIED. So scoring canNOT call `frontier
    # eval` in-process (it needs testdata). Instead fmeasure drops solution.cpp to the OUT-OF-SANDBOX
    # judge daemon (gen/judge_server.py, started separately) and reads back the score — identical to
    # the Claude baseline's measure.sh. This closes the gap where algorithmic Nous (sandbox:bypass)
    # could `ls .../testdata/` and read answers.
    JUDGE_ROOT = os.environ.get("FCS_JUDGE_ROOT", "/tmp/fcs_judge")
    fmeasure = ws.parent / f"fmeasure_{pid}.sh"
    fmeasure.write_text(
        "#!/bin/bash\n"
        "# Usage: fmeasure.sh <solution.cpp> -> prints 'SCORE: <n>' via the out-of-sandbox judge daemon.\n"
        f'JR="{JUDGE_ROOT}"\n'
        f'tok="p{pid}__$(date +%s%N)_$RANDOM"\n'
        'cp "$1" "$JR/inbox/$tok.cpp"\n'
        'for i in $(seq 1 1200); do\n'
        '  if [ -f "$JR/outbox/$tok.score" ]; then\n'
        '    cat "$JR/outbox/$tok.score"; rm -f "$JR/outbox/$tok.score"; exit 0\n'
        '  fi\n'
        '  sleep 0.5\n'
        'done\n'
        'echo "SCORE: ERR (judge timeout)"\n')
    fmeasure.chmod(0o755)
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
        f"PROBLEM STATEMENT:\n{stmt}"
    )
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"frontier-{pid}-{label}").strip("-")
    spec = {
        "research_question": f"What algorithm maximizes the Frontier-CS judge score for algorithmic problem #{pid}?",
        "run_id": run_slug,
        "max_iterations": nous_iters,
        "sandbox": "bypass",
        # #205 live watchdog. This litellm->Bedrock backend has very slow time-to-first-byte on the
        # large (~200KB) subagent requests: measured 45-696s via a logging proxy. A short threshold
        # (we tried 90s) aborts those slow-but-valid responses and fails the turn after 11 retries.
        # Set to 900s so legitimate slow responses (incl. the observed 696s gap) are tolerated; the
        # original Oct-1 runs completed under the 600s default for the same reason.
        "sdk_timeouts": {"turn_silence_threshold_seconds": 900},
        "target_system": {
            "name": f"frontier-cs::algorithmic::{pid}",
            "description": desc,
            "repo_path": str(ws),
            "observable_metrics": ["score"],
            "controllable_knobs": ["solution_cpp"],
        },
        "objective": {"weights": {"score": 1.0}},
        "models": {"design": model, "execute_analyze": model, "report": model},
        "prompts": {"methodology_layer": f"{NOUS_REPO}/prompts/methodology", "domain_adapter_layer": None},
    }
    # Optional per-phase SDK reasoning effort (low|medium|high|xhigh|max), gated on env vars so the
    # default path is unchanged. effort can only be set via the campaign spec (defaults.yaml is not
    # consulted by _effort_for), so inject it here when requested.
    _eff_d = os.environ.get("NOUS_DESIGN_EFFORT")
    _eff_e = os.environ.get("NOUS_EXECUTE_EFFORT")
    if _eff_d or _eff_e:
        spec["sdk_options"] = {
            "design": {"effort": _eff_d} if _eff_d else {},
            "execute_analyze": {"effort": _eff_e} if _eff_e else {},
        }
    camp = ws.parent / f"campaign_{pid}.yaml"
    camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    env = dict(os.environ)
    env["NOUS_CAMPAIGN_PARENT"] = str(ws.parent / "nous_runs")
    log = Path(logdir) / f"frontier_{pid}_{label}.nous.log"
    # OS-level isolation (matches the Claude baseline): deny the agent reads of the benchmark tree
    # (statements + hidden testdata + .ans answers). SBPL last-match-wins: allow default, then deny
    # the Frontier-CS subpath. Scoring is unaffected because fmeasure.sh routes through the
    # out-of-sandbox judge daemon. Writes/git/worktrees (under logdir, not Frontier-CS) stay allowed.
    sb_profile = ws.parent / f"nous_sandbox_{pid}.sb"
    fcs_tree = os.path.realpath(FRONTIER)
    sb_profile.write_text("(version 1)\n(allow default)\n"
                          f'(deny file-read* (subpath "{fcs_tree}"))\n')
    sandbox_prefix = ([] if os.environ.get("NOUS_FCS_NO_SANDBOX")
                      else ["sandbox-exec", "-f", str(sb_profile)])
    cmd = sandbox_prefix + [NOUS_BIN, "run", str(camp), "--auto-approve", "--agent", "sdk",
           "--sandbox", "bypass", "--max-iterations", str(nous_iters), "--timeout", "2400"]
    with open(log, "w") as lf:
        subprocess.run(cmd, cwd=NOUS_REPO, env=env, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=14400)
    # harvest candidate solutions from every place Nous persists an arm:
    #  - per-arm worktrees at <repo_path>/.nous-experiments/<run>/<arm>/ (issue #133)
    #  - the campaign's per-arm saved inputs (runs/iter-*/inputs/<arm>-solution.cpp) — robust even
    #    if the worktrees are cleaned or the run is interrupted before completion
    #  - the final workspace copy
    camp_dir = ws.parent / "nous_runs" / run_slug
    seen, cands = set(), []
    globbed = (list((ws / ".nous-experiments").glob("**/solution.cpp"))
               + list(camp_dir.glob("runs/iter-*/inputs/*solution.cpp"))
               + [ws / "solution.cpp"])
    for sc in globbed:
        if not sc.exists():
            continue
        body = sc.read_text()
        key = body.strip()
        if not key or body == SEED or key in seen:
            continue
        seen.add(key)
        cands.append(sc)
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id")
    ap.add_argument("--agent", choices=["nous"], default="nous")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--nous-iters", type=int, default=5)
    ap.add_argument("--cost-budget", type=float, default=None, help="ignored; the cap is enforced by nous_cap_launch.py")
    args = ap.parse_args()
    pid = args.problem_id
    label = args.label or args.agent
    Path(args.logdir).mkdir(parents=True, exist_ok=True)
    stmt = statement(pid)
    meta = {"problem_id": pid, "agent": args.agent, "label": label, "model": args.model}
    t0 = time.time()
    ws = Path(args.logdir) / f"frontier_{pid}_{label}_ws"
    cands = run_nous(pid, stmt, ws, args.model, args.logdir, args.nous_iters, label)
    scored = []
    for c in cands:
        s, st, _ = evaluate(pid, c)
        scored.append({"path": str(c), "score": s, "status": st})
        print("CAND", c, "score=", s, st)
    scored = [x for x in scored if isinstance(x["score"], (int, float))]
    best = max(scored, key=lambda x: x["score"], default=None)
    meta["candidates"] = scored
    meta["final_score"] = best["score"] if best else None
    meta["solution"] = best["path"] if best else None
    meta["seconds"] = round(time.time() - t0, 1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(meta, indent=2))
    print("RESULT", json.dumps({k: meta.get(k) for k in ("problem_id", "label", "final_score", "seconds")}))


if __name__ == "__main__":
    main()
