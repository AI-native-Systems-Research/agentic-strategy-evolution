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


def _extract_cpp(text):
    """Pull the C++ source from a model reply (```cpp block, or raw if it looks like code)."""
    m = re.search(r"```(?:cpp|c\+\+)?\s*\n(.*?)```", text or "", re.DOTALL)
    if m:
        return m.group(1).strip() + "\n"
    if text and ("#include" in text or "int main" in text):
        return text.strip() + "\n"
    return None


def claude_text(prompt, model, timeout=600):
    """Pure code generation via the litellm chat API (no agentic CLI, no tools). The driver runs
    the judge and feeds the score back, so the model only needs to emit code. Using the CLI here
    is a trap: without --allowedTools it enables ALL tools and tries to orchestrate the slow
    frontier-eval/docker loop itself, which hangs."""
    import urllib.request
    base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    body = json.dumps({"model": model, "max_tokens": 8000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
        "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"] or "", (d.get("usage") or {})


def gen_prompt(pid, stmt, prev_code, prev_score, best_score):
    base = (f"You are solving competitive-programming optimization problem Frontier-CS algorithmic #{pid}. "
            f"Scoring is CONTINUOUS partial credit 0..100 (higher is better); MAXIMIZE it with the best "
            f"algorithm/heuristic you can. Output a single self-contained C++17 program.\n\n"
            f"PROBLEM STATEMENT:\n{stmt}\n\n")
    if prev_code is None:
        return base + "Output ONLY the C++17 code in a single ```cpp code block."
    return (base + f"Your previous solution scored {prev_score}/100 (best so far {best_score}). "
            f"Previous solution:\n```cpp\n{prev_code}\n```\n"
            f"Diagnose what limited the score and output an IMPROVED full C++17 solution. "
            f"Output ONLY the C++17 code in a single ```cpp code block.")


def run_claude(pid, stmt, sol_path, model, logdir, label, rounds=6):
    """Driver-controlled iterative refinement: the driver evaluates each solution and feeds the
    score + judge detail back to the model for the next round, keeping the best. Mirrors the
    submit.sh iterative-feedback protocol, but the harness (not the agent) drives the judge."""
    sol_path = Path(sol_path)
    best_code, best_score = None, None
    history = []
    tok_in = tok_out = 0
    prev_code, prev_score = None, None
    for r in range(rounds):
        prompt = gen_prompt(pid, stmt, prev_code, prev_score, best_score)
        reply, usage = claude_text(prompt, model)
        tok_in += usage.get("prompt_tokens", 0) or 0
        tok_out += usage.get("completion_tokens", 0) or 0
        code = _extract_cpp(reply)
        if not code:
            history.append({"round": r, "score": None, "status": "no_code"})
            continue
        sol_path.write_text(code)
        score, status, _ = evaluate(pid, sol_path)
        history.append({"round": r, "score": score, "status": status})
        print(f"  [claude round {r}] score={score} status={status}")
        prev_code, prev_score = code, score
        if score is not None and (best_score is None or score > best_score):
            best_code, best_score = code, score
    if best_code is not None:
        sol_path.write_text(best_code)
    (Path(logdir) / f"frontier_{pid}_{label}.history.json").write_text(json.dumps(history, indent=2))
    # Opus 4.6 approx pricing ($/1M tok): input 15, output 75 (adjust if gateway differs)
    cost = round(tok_in / 1e6 * 15 + tok_out / 1e6 * 75, 4)
    return best_score, {"history": history, "input_tokens": tok_in, "output_tokens": tok_out, "cost_usd_est": cost}


def run_nous(pid, stmt, ws, model, logdir, nous_iters, label):
    import yaml
    ws = Path(ws); ws.mkdir(parents=True, exist_ok=True)
    (ws / "solution.cpp").write_text(SEED)
    sh("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed", cwd=str(ws))
    # Clean measure wrapper: the executor runs ONE simple command that prints just "SCORE: <n>",
    # instead of orchestrating `frontier eval` + JSON parsing itself (which is slow/error-prone).
    fmeasure = ws.parent / f"fmeasure_{pid}.sh"
    fmeasure.write_text(
        "#!/bin/bash\n"
        "# Usage: fmeasure.sh <solution.cpp> -> prints 'SCORE: <n>' (judge score 0-100, higher is better)\n"
        f"cd {FRONTIER} || exit 2\n"
        'export PATH="$HOME/.local/bin:$PATH"\n'
        f'out=$({FEVAL} eval algorithmic {pid} "$1" --json 2>/dev/null)\n'
        "s=$(printf '%s' \"$out\" | python3 -c \"import sys,re;t=sys.stdin.read();m=re.findall(r'\\\"score\\\"\\s*:\\s*([0-9.]+)',t);print(m[-1] if m else 'ERR')\")\n"
        'echo "SCORE: $s"\n')
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
    # harvest candidate solutions from every place Nous persists an arm:
    #  - per-arm worktrees at <repo_path>/.nous-experiments/<run>/<arm>/ (issue #133)
    #  - the campaign's per-arm saved inputs (runs/iter-*/inputs/<arm>-solution.cpp) — robust even
    #    if the worktrees are cleaned or the run is interrupted before completion
    #  - the final workspace copy
    camp_dir = ws.parent / "nous_runs" / f"frontier-{pid}"
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
    ap.add_argument("--agent", choices=["claude", "nous"], default="claude")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--nous-iters", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=6, help="claude iterative-refinement rounds")
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
        best_score, info = run_claude(pid, stmt, sol, args.model, args.logdir, label, rounds=args.rounds)
        final_score, status, _ = evaluate(pid, sol)
        meta.update(final_score=final_score, status=status, solution=str(sol),
                    best_score=best_score, rounds=len(info["history"]), history=info["history"],
                    input_tokens=info["input_tokens"], output_tokens=info["output_tokens"],
                    cost_usd_est=info["cost_usd_est"])
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
