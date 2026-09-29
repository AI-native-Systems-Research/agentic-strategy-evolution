"""Frontier-CS (algorithmic track) generation: plain Claude vs Nous, same scorer.

Runs on the VM host (Nous, Claude CLI, and the `frontier` judge all live here; the judge
auto-starts a Docker sidecar). Unlike SWE-fficiency there is no per-task container: the
"target" is a single C++17 solution file, and the objective is the judge score
(0-100, higher is better, deterministic quality-based scoring, ~30s/eval).

Both agents get the SAME problem statement, the SAME eval command as feedback, the SAME
model, and the SAME seed solution. Deliverable = the highest-scoring solution the agent
produced, re-evaluated independently by us (so the number is trustworthy).

Usage (on the VM):
  python frontier_gen.py <problem_id> --agent claude --out preds/<id>.claude.json
  python frontier_gen.py <problem_id> --agent nous   --out preds/<id>.nous.json --nous-iters 5
"""
import argparse, json, os, re, shlex, subprocess, tempfile, time
from pathlib import Path

FRONTIER = os.path.expanduser("~/frontier/Frontier-CS")
FEVAL = f"{FRONTIER}/.venv/bin/frontier"
NOUS_BIN = os.path.expanduser("~/nous_repo/.venv/bin/nous")
NOUS_REPO = os.path.expanduser("~/nous_repo")
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


def build_prompt(pid, stmt, sol_path):
    return f"""You are solving a competitive-programming optimization problem (Frontier-CS algorithmic #{pid}).
Scoring is PARTIAL CREDIT and CONTINUOUS: a judge returns a score from 0 to 100, higher is better.
Your job is to MAXIMIZE the score, not just to be correct.

PROBLEM STATEMENT:
{stmt}

RULES:
- Write a single self-contained C++17 file to: {sol_path}
- Test/score your solution AS OFTEN AS YOU LIKE with:
    {FEVAL} eval algorithmic {pid} {sol_path} --json
  (run it from {FRONTIER}). It prints JSON with a "score" field (0-100). Use that feedback to iterate.
- Keep improving the algorithm to push the score higher. A better heuristic or exact algorithm
  scores more. Aim well above a naive baseline.
- When you are done, ensure your best solution is saved at {sol_path}.

Start by reading the statement, write a first correct solution, score it, then iterate to improve."""


def run_claude(pid, stmt, sol_path, model, logdir, label):
    prompt = build_prompt(pid, stmt, sol_path)
    (Path(logdir) / f"frontier_{pid}_{label}.prompt.txt").write_text(prompt)
    cc = subprocess.run(
        ["claude", "-p", "--model", model, "--permission-mode", "bypassPermissions",
         "--allowedTools", "Bash", "Write", "Read", "Edit", "--output-format", "text"],
        input=prompt, text=True, capture_output=True, timeout=7200,
    )
    (Path(logdir) / f"frontier_{pid}_{label}.agent.log").write_text((cc.stdout or "") + "\n---STDERR---\n" + (cc.stderr or ""))
    return cc.returncode


def run_nous(pid, stmt, ws, model, logdir, nous_iters, label):
    import yaml
    ws = Path(ws); ws.mkdir(parents=True, exist_ok=True)
    (ws / "solution.cpp").write_text(SEED)
    sh("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed", cwd=str(ws))
    desc = (
        f"You are solving Frontier-CS algorithmic problem #{pid}. Scoring is CONTINUOUS partial "
        f"credit from 0 to 100 (higher is better); MAXIMIZE it. Your working directory is a git "
        f"worktree containing 'solution.cpp' (a C++17 stub). Edit solution.cpp with your algorithm.\n\n"
        f"MEASURE the objective (the judge score) by running from {FRONTIER}:\n"
        f"    {FEVAL} eval algorithmic {pid} $PWD/solution.cpp --json\n"
        f"It prints JSON with a 'score' field (0-100). Record that score in the finding metadata "
        f"under key 'score'. Each experiment arm should try a distinct algorithmic strategy "
        f"(different heuristic, exact method, or optimization) and report its measured score.\n\n"
        f"PROBLEM STATEMENT:\n{stmt}"
    )
    spec = {
        "research_question": f"What algorithm maximizes the Frontier-CS judge score for algorithmic problem #{pid}?",
        "run_id": f"frontier-{pid}",
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
        "prompts": {"methodology_layer": f"{NOUS_REPO}/prompts/methodology", "domain_adapter_layer": None},
    }
    camp = ws.parent / f"campaign_{pid}.yaml"
    camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    env = dict(os.environ)
    env["NOUS_CAMPAIGN_PARENT"] = str(ws.parent / "nous_runs")
    log = Path(logdir) / f"frontier_{pid}_{label}.nous.log"
    cmd = [NOUS_BIN, "run", str(camp), "--auto-approve", "--agent", "sdk", "--sandbox", "bypass",
           "--max-iterations", str(nous_iters), "--timeout", "2400"]
    with open(log, "w") as lf:
        subprocess.run(cmd, cwd=NOUS_REPO, env=env, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=14400)
    # harvest candidate solutions: every per-arm worktree's solution.cpp + the final workspace copy.
    # Nous worktrees live at <repo_path>/.nous-experiments/<run>/<arm>/ (issue #133).
    seen, cands = set(), []
    globbed = list((ws / ".nous-experiments").glob("**/solution.cpp")) + [ws / "solution.cpp"]
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
    ap.add_argument("--agent", choices=["claude", "nous"], default="claude")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--nous-iters", type=int, default=5)
    args = ap.parse_args()
    pid = args.problem_id
    label = args.label or args.agent
    Path(args.logdir).mkdir(parents=True, exist_ok=True)
    stmt = statement(pid)
    meta = {"problem_id": pid, "agent": args.agent, "label": label, "model": args.model}
    t0 = time.time()

    if args.agent == "claude":
        sol = Path(args.logdir) / f"frontier_{pid}_{label}.solution.cpp"
        sol.write_text(SEED)
        meta["rc"] = run_claude(pid, stmt, sol, args.model, args.logdir, label)
        final_score, status, _ = evaluate(pid, sol)
        meta.update(final_score=final_score, status=status, solution=str(sol))
    else:
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
    print("RESULT", json.dumps({k: meta.get(k) for k in ("problem_id", "label", "final_score", "status", "seconds")}))


if __name__ == "__main__":
    main()
