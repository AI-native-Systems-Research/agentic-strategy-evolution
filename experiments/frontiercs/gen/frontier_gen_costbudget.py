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

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")
NOUS_BIN = os.environ.get("NOUS_BIN", os.path.expanduser("~/nous_repo/.venv/bin/nous"))
NOUS_REPO = os.environ.get("NOUS_REPO", os.path.expanduser("~/nous_repo"))
SEED = "#include <bits/stdc++.h>\nusing namespace std;\nint main(){return 0;}\n"

# Engram-style reimplementation: the "Struggle Protocol" prompt block is Engram's key behavioral
# lever (mit-nms/Engram, arXiv 2603.21321) — it stops the agent abandoning a principled method
# after one bad score, which is what lets it reach solver-based solutions instead of plateauing on
# shallow heuristics.
STRUGGLE_PROTOCOL = (
    "STRUGGLE PROTOCOL (follow strictly):\n"
    "- If a promising approach fails or plateaus, do NOT abandon it on the first failure. First "
    "diagnose WHY it underperformed (bug? too slow so it times out? weak on a specific case class?), "
    "then fix that specific cause.\n"
    "- Do NOT downgrade from a principled/exact method (exact solver, ILP, DP, flow) to a trivial "
    "heuristic just because the first attempt scored low. A low score usually means a bug or a "
    "too-slow implementation, not a wrong idea. A timeout means 'too slow', not 'wrong'.\n"
    "- Prefer deepening one strong idea over sampling many shallow ones.\n"
)


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
    import urllib.request, urllib.error, time as _t, random
    base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    body = json.dumps({"model": model, "max_tokens": 8000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    # Retry with exponential backoff on rate limits / transient errors — the litellm gateway is
    # shared (multiple concurrent runs), so 429s are expected and must NOT kill the run.
    last = None
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            return d["choices"][0]["message"]["content"] or "", (d.get("usage") or {})
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                wait = min(90, 5 * (2 ** attempt)) + random.uniform(0, 5)
                print(f"    [claude_text] HTTP {e.code}; backoff {wait:.0f}s (attempt {attempt+1}/8)")
                _t.sleep(wait); continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            wait = min(90, 5 * (2 ** attempt)) + random.uniform(0, 5)
            print(f"    [claude_text] {type(e).__name__}; backoff {wait:.0f}s (attempt {attempt+1}/8)")
            _t.sleep(wait); continue
    raise RuntimeError(f"claude_text failed after retries: {last}")


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


def run_claude(pid, stmt, sol_path, model, logdir, label, rounds=6,
               cost_budget=None, ceiling=100.0, patience_rounds=3):
    """Driver-controlled iterative refinement: the driver evaluates each solution and feeds the
    score back to the model for the next round, keeping the best. With cost_budget set, 'rounds' is a
    cap and we early-stop on ceiling, cost budget, or plateau (no improvement for patience_rounds
    rounds after a positive score) — the same budget+early-stop rule as Nous/Engram."""
    sol_path = Path(sol_path)
    best_code, best_score = None, None
    history = []
    tok_in = tok_out = 0
    def cur_cost():
        return round(tok_in / 1e6 * 15 + tok_out / 1e6 * 75, 4)
    prev_code, prev_score = None, None
    no_improve = 0; r = 0; stop_reason = "max_rounds"
    while r < rounds:
        start_best = best_score if best_score is not None else -1.0
        prompt = gen_prompt(pid, stmt, prev_code, prev_score, best_score)
        reply, usage = claude_text(prompt, model)
        tok_in += usage.get("prompt_tokens", 0) or 0
        tok_out += usage.get("completion_tokens", 0) or 0
        code = _extract_cpp(reply)
        if not code:
            history.append({"round": r, "score": None, "status": "no_code"}); r += 1
            if cost_budget and cur_cost() >= cost_budget: stop_reason = "cost_budget"; break
            continue
        sol_path.write_text(code)
        score, status, _ = evaluate(pid, sol_path)
        history.append({"round": r, "score": score, "status": status})
        print(f"  [claude round {r}] score={score} status={status} cost=${cur_cost()}")
        prev_code, prev_score = code, score
        if score is not None and (best_score is None or score > best_score):
            best_code, best_score = code, score
        r += 1
        cur = best_score if best_score is not None else -1.0
        if cur > 0 and cur <= start_best + 1e-9: no_improve += 1
        else: no_improve = 0
        if best_score is not None and best_score >= ceiling - 0.5: stop_reason = "ceiling"; break
        if cost_budget and cur_cost() >= cost_budget: stop_reason = "cost_budget"; break
        if no_improve >= patience_rounds: stop_reason = "plateau"; break
    if best_code is not None:
        sol_path.write_text(best_code)
    (Path(logdir) / f"frontier_{pid}_{label}.history.json").write_text(json.dumps(history, indent=2))
    print(f"  [claude DONE] best={best_score} cost=${cur_cost()} rounds_run={r} stop={stop_reason}")
    return best_score, {"history": history, "input_tokens": tok_in, "output_tokens": tok_out,
                        "cost_usd_est": cur_cost(), "rounds_run": r, "stop_reason": stop_reason}


def _extract_plan(text):
    m = re.search(r"MY PLAN:\s*(.+)", text or "")
    return m.group(1).strip()[:300] if m else None


def _engram_init_prompt(pid, stmt, journal_text, best_code, best_score, agent_idx, total_agents):
    """First prompt for a FRESH Engram agent. Prior work reaches it ONLY through the on-disk journal
    (structured reasoning digest) + the best artifact so far — the agent's own context starts empty,
    which is Engram's mechanism for dodging the single-agent 'coherence ceiling'."""
    role = (f"You are Research Specialist #{agent_idx + 1} of {total_agents} in an ongoing effort to "
            f"MAXIMIZE the judge score on Frontier-CS algorithmic problem #{pid}. You have a FRESH "
            f"context: everything earlier agents learned is in the research journal below.\n\n")
    task = (f"Scoring is CONTINUOUS partial credit 0..100 (higher is better); MAXIMIZE it with the best "
            f"algorithm/heuristic you can. Output a single self-contained C++17 program.\n\n"
            f"PROBLEM STATEMENT:\n{stmt}\n")
    mem = ""
    if journal_text.strip():
        mem += ("\nRESEARCH JOURNAL (accumulated insights from PRIOR agents — read this FIRST, build on "
                "what worked, and do NOT repeat approaches already shown to fail):\n"
                f"{journal_text}\n")
    if best_code:
        mem += (f"\nBEST SOLUTION SO FAR (score {best_score}/100). Build on it or beat it:\n"
                f"```cpp\n{best_code}\n```\n")
    plan = ("\nBefore writing code, state exactly one line beginning 'MY PLAN:' describing the approach "
            "you will try and why. Then output the C++17 solution in a single ```cpp code block.")
    return role + task + mem + "\n" + STRUGGLE_PROTOCOL + plan


def _engram_refine_prompt(pid, prev_code, prev_score, best_score):
    return (f"Your last solution scored {prev_score}/100 (best this run so far {best_score}). "
            f"Diagnose what limited the score (correctness? hard-case coverage? time limit? heuristic "
            f"quality?), then output an IMPROVED full C++17 solution.\n\n" + STRUGGLE_PROTOCOL +
            f"\nPrevious solution:\n```cpp\n{prev_code}\n```\n"
            f"Output ONLY the improved C++17 code in a single ```cpp code block.")


def _engram_summary_prompt(pid, tried):
    lines = "\n".join(f"- plan: {t['plan']} | score: {t['score']} | status: {t['status']}" for t in tried) or "(no successful attempts)"
    return ("Write a handoff summary for the NEXT research agent, who starts fresh and will see ONLY "
            "this summary (plus the archive). Use EXACTLY these sections and be concrete:\n"
            "## Summary for Next Agent\n"
            "**Best Result** — score and a one-line description of the approach that got it.\n"
            "**What I Tried** — per approach: the idea, why, and the measured result.\n"
            "**Key Insights** — what actually moves the score on this problem.\n"
            "**Approaches That Didn't Work (and Why)** — so the next agent won't repeat them.\n"
            "**Recommended Next Steps** — the most promising unexplored direction.\n\n"
            f"Your attempts this run (problem #{pid}):\n{lines}\n")


def run_engram(pid, stmt, sol_path, model, logdir, label, agents=3, rounds_per_agent=3,
               cost_budget=None, ceiling=100.0, patience_agents=2):
    """Engram-style (faithful reimplementation of mit-nms/Engram, arXiv 2603.21321), adapted to the
    driver-controlled loop + our judge as the simulator.

    Faithful to Engram's two ablation-verified mechanisms:
      1. Sequential identical agents, each with a FRESH context (decouples context from memory to
         beat the single-agent coherence ceiling).
      2. On-disk memory persisted across handoffs: a Research Journal (accumulating structured
         reasoning digest, injected into the next agent) + a Knowledgebase archive (raw per-experiment
         records). We persist *reasoning*, not just scores, which is Engram's lever against the
         evolutionary-neighborhood bias of score-only methods.
    Plus the Struggle Protocol prompt. The driver runs the judge and feeds the score back within an
    agent (same seam as run_claude), so the model only emits code + plan + summary."""
    sol_path = Path(sol_path)
    workdir = Path(logdir) / f"frontier_{pid}_{label}_engram"
    kb = workdir / "knowledgebase"
    kb.mkdir(parents=True, exist_ok=True)
    journal_path = workdir / "research_journal.md"
    journal_path.write_text(f"# Research Journal — Frontier-CS #{pid}\n")
    best_code, best_score = None, None
    tok_in = tok_out = 0
    history, agent_summaries = [], []
    def cur_cost():
        return round(tok_in / 1e6 * 15 + tok_out / 1e6 * 75, 4)
    # 'agents' is the CAP; with cost_budget set we early-stop on ceiling, cost, or plateau
    # (best not improving for patience_agents consecutive agents) — same budget+early-stop rule
    # we apply to Nous, so the comparison is "given equal cost with early-stop, how far can it push".
    no_improve = 0; ai = 0; stop_reason = "max_agents"
    while ai < agents:
        start_best = best_score if best_score is not None else -1.0
        journal_text = journal_path.read_text()
        agent_dir = kb / f"agent_{ai}"
        agent_dir.mkdir(parents=True, exist_ok=True)
        prev_code, prev_score, tried = None, None, []
        hit = None
        for r in range(rounds_per_agent):
            if r == 0:
                prompt = _engram_init_prompt(pid, stmt, journal_text, best_code, best_score, ai, agents)
            else:
                prompt = _engram_refine_prompt(pid, prev_code, prev_score, best_score)
            reply, usage = claude_text(prompt, model)
            tok_in += usage.get("prompt_tokens", 0) or 0
            tok_out += usage.get("completion_tokens", 0) or 0
            plan = _extract_plan(reply)
            code = _extract_cpp(reply)
            if not code:
                history.append({"agent": ai, "round": r, "score": None, "status": "no_code", "plan": plan})
                continue
            sol_path.write_text(code)
            score, status, _ = evaluate(pid, sol_path)
            history.append({"agent": ai, "round": r, "score": score, "status": status, "plan": plan})
            tried.append({"plan": plan or "(none stated)", "score": score, "status": status})
            (agent_dir / f"exp_{r}.json").write_text(json.dumps(
                {"round": r, "plan": plan, "score": score, "status": status, "code": code}, indent=2))
            print(f"  [engram a{ai} r{r}] score={score} status={status} cost=${cur_cost()} plan={plan}")
            prev_code, prev_score = code, score
            if score is not None and (best_score is None or score > best_score):
                best_code, best_score = code, score
            if best_score is not None and best_score >= ceiling - 0.5:
                hit = "ceiling"; break
            if cost_budget and cur_cost() >= cost_budget:
                hit = "cost_budget"; break
        # Handoff: dedicated summary call -> append to journal (methodology overhead).
        summ, usage = claude_text(_engram_summary_prompt(pid, tried), model)
        tok_in += usage.get("prompt_tokens", 0) or 0
        tok_out += usage.get("completion_tokens", 0) or 0
        agent_summaries.append(summ)
        with open(journal_path, "a") as jf:
            jf.write(f"\n## Agent {ai} handoff (global best so far: {best_score})\n{summ}\n\n---\n")
        ai += 1
        cur = best_score if best_score is not None else -1.0
        # only count a plateau once we actually have a positive score; while stuck at 0 (no valid
        # solution yet) keep spending budget to find one, don't give up early.
        if cur > 0 and cur <= start_best + 1e-9:
            no_improve += 1
        else:
            no_improve = 0
        if hit:
            stop_reason = hit; break
        if cost_budget and cur_cost() >= cost_budget:
            stop_reason = "cost_budget"; break
        if no_improve >= patience_agents:
            stop_reason = "plateau"; break
    if best_code is not None:
        sol_path.write_text(best_code)
    (Path(logdir) / f"frontier_{pid}_{label}.history.json").write_text(json.dumps(history, indent=2))
    print(f"  [engram DONE] best={best_score} cost=${cur_cost()} agents_run={ai} stop={stop_reason}")
    return best_score, {"history": history, "input_tokens": tok_in, "output_tokens": tok_out,
                        "cost_usd_est": cur_cost(), "agents_run": ai, "rounds_per_agent": rounds_per_agent,
                        "code_generations": len([h for h in history if h.get("status") == "success"]),
                        "stop_reason": stop_reason, "journal": str(journal_path)}


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
    cmd = [NOUS_BIN, "run", str(camp), "--auto-approve", "--agent", "sdk", "--sandbox", "bypass",
           "--max-iterations", str(nous_iters), "--timeout", "2400"]
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
    ap.add_argument("--agent", choices=["claude", "nous", "engram"], default="claude")
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default=None)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    ap.add_argument("--nous-iters", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=6, help="claude iterative-refinement rounds")
    ap.add_argument("--agents", type=int, default=3, help="engram: number of sequential fresh-context agents")
    ap.add_argument("--rounds-per-agent", type=int, default=3, help="engram: code-generation rounds per agent")
    ap.add_argument("--cost-budget", type=float, default=None,
                    help="engram: $ budget; keep spawning agents (up to --agents cap) until cost>=budget, "
                         "ceiling, or plateau. Set --agents high (e.g. 40) as the cap.")
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
    elif args.agent == "engram":
        sol = Path(args.logdir) / f"frontier_{pid}_{label}.solution.cpp"
        sol.write_text(SEED)
        best_score, info = run_engram(pid, stmt, sol, args.model, args.logdir, label,
                                      agents=args.agents, rounds_per_agent=args.rounds_per_agent,
                                      cost_budget=args.cost_budget)
        final_score, status, _ = evaluate(pid, sol)
        meta.update(final_score=final_score, status=status, solution=str(sol), best_score=best_score,
                    method="Engram-style (reimplementation)", agents_run=info["agents_run"],
                    rounds_per_agent=args.rounds_per_agent, code_generations=info["code_generations"],
                    cost_budget=args.cost_budget, stop_reason=info["stop_reason"],
                    history=info["history"], input_tokens=info["input_tokens"],
                    output_tokens=info["output_tokens"], cost_usd_est=info["cost_usd_est"],
                    journal=info["journal"])
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
