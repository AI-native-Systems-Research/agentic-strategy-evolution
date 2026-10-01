"""Frontier-CS (RESEARCH track) generation: plain Claude vs Engram vs Nous, same scorer.

Research-track variant of frontier_gen_costbudget.py. The "target" is a Python `solution.py`
(a `Solution` class whose `solve()` returns `{"code": "<algorithm source>"}`), scored by the
problem's own local evaluator (no Docker, no GPU for cloudcast): lower total transfer cost =>
higher score, where score = 100 / (1 + total_cost). We MAXIMIZE score (== minimize cost).

Scoring runs locally in a per-problem venv built once:
  python3 -m venv research/problems/<pid>/.evalvenv
  research/problems/<pid>/.evalvenv/bin/pip install networkx numpy colorama pandas graphviz

Both agents get the SAME problem readme (API spec), the SAME eval as feedback, the SAME model,
and the SAME seed. Deliverable = highest-scoring solution.py, re-evaluated independently by us.

Usage (run from ~/frontier/Frontier-CS):
  python frontier_research_gen.py cloudcast --agent claude --rounds 30 --out preds/cloudcast.claude.json
  python frontier_research_gen.py cloudcast --agent engram --agents 40 --cost-budget 30 --out preds/cloudcast.engram.json
  python frontier_research_gen.py cloudcast --agent nous   --nous-iters 3 --out preds/cloudcast.nous.json
"""
import argparse, json, os, re, shlex, subprocess, tempfile, time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
NOUS_BIN = os.environ.get("NOUS_BIN", os.path.expanduser("~/nous_repo/.venv/bin/nous"))
NOUS_REPO = os.environ.get("NOUS_REPO", os.path.expanduser("~/nous_repo"))

# Valid baseline solution.py: Dijkstra shortest-cost tree (the problem's own initial_program),
# wrapped in the required Solution-class-returns-code contract. Round-0 scores a real number.
SEED = r'''import networkx as nx


class Solution:
    def solve(self, spec_path: str = None) -> dict:
        return {"code": r"""
import networkx as nx


class BroadCastTopology:
    def __init__(self, src, dsts, num_partitions):
        self.src = src
        self.dsts = dsts
        self.num_partitions = int(num_partitions)
        self.paths = {dst: {str(i): None for i in range(self.num_partitions)} for dst in dsts}

    def append_dst_partition_path(self, dst, partition, path):
        partition = str(partition)
        if self.paths[dst][partition] is None:
            self.paths[dst][partition] = []
        self.paths[dst][partition].append(path)

    def set_dst_partition_paths(self, dst, partition, paths):
        self.paths[dst][str(partition)] = paths

    def set_num_partitions(self, num_partitions):
        self.num_partitions = num_partitions


def search_algorithm(src, dsts, G, num_partitions):
    h = G.copy()
    h.remove_edges_from(list(h.in_edges(src)) + list(nx.selfloop_edges(h)))
    bc = BroadCastTopology(src, dsts, num_partitions)
    for dst in dsts:
        path = nx.dijkstra_path(h, src, dst, weight="cost")
        for i in range(len(path) - 1):
            s, t = path[i], path[i + 1]
            for j in range(bc.num_partitions):
                bc.append_dst_partition_path(dst, j, [s, t, G[s][t]])
    return bc
"""}
'''

STRUGGLE_PROTOCOL = (
    "STRUGGLE PROTOCOL (follow strictly):\n"
    "- If a promising approach fails or plateaus, do NOT abandon it on the first failure. First "
    "diagnose WHY it underperformed (bug? invalid paths so it errors? weak on a specific network?), "
    "then fix that specific cause.\n"
    "- Do NOT downgrade from a principled method (multi-path load balancing, Steiner-tree / "
    "cost-aware routing, LP) to a trivial shortest-path heuristic just because the first attempt "
    "scored low. A low score usually means a bug or an unbalanced topology, not a wrong idea.\n"
    "- Prefer deepening one strong idea over sampling many shallow ones.\n"
)

API_CONTRACT = (
    "OUTPUT CONTRACT (strict): output ONE complete Python file in a single ```python code block. "
    "It must define `class Solution` with a method `solve(self, spec_path: str = None) -> dict` that "
    "returns `{\"code\": \"<algorithm source as a string>\"}`. The algorithm source string must "
    "itself define a `BroadCastTopology` class (same API as the statement) AND a function "
    "`search_algorithm(src, dsts, G, num_partitions)` that returns a populated BroadCastTopology. "
    "Do not read any external files. Output ONLY the code block."
)


def sh(cmd, timeout=None, cwd=None, env=None):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout, cwd=cwd, env=env)


def _probdir(pid):
    return Path(FRONTIER) / "research" / "problems" / str(pid)


def _evalpy(pid):
    return _probdir(pid) / ".evalvenv" / "bin" / "python3"


def statement(pid):
    p = _probdir(pid) / "readme"
    return p.read_text() if p.exists() else f"(research problem {pid})"


def evaluate(pid, sol_path, timeout=900):
    """Return (score, status, raw) by running the problem's local evaluator on sol_path.
    score = 100/(1+total_cost) (higher is better); raw carries total_cost + metrics."""
    pd = _probdir(pid)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    try:
        r = sh(f"{_evalpy(pid)} {shlex.quote(str(pd / 'evaluator.py'))} "
               f"--solution {shlex.quote(str(sol_path))} "
               f"--spec {shlex.quote(str(pd / 'resources' / 'submission_spec.json'))} "
               f"--out {shlex.quote(out)}", timeout=timeout, cwd=str(pd))
        try:
            data = json.loads(Path(out).read_text())
        except Exception:
            return 0.0, "parse_error", {"stderr": (r.stderr or "")[-500:]}
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass
    if data.get("error") or data.get("runs_successfully", 0.0) != 1.0:
        return 0.0, "error", data
    return float(data.get("score", 0.0)), "success", data


def _extract_py(text):
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.DOTALL)
    if m:
        return m.group(1).strip() + "\n"
    if text and ("class Solution" in text and "def solve" in text):
        return text.strip() + "\n"
    return None


def claude_text(prompt, model, timeout=600):
    import urllib.request, urllib.error, time as _t, random
    base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    body = json.dumps({"model": model, "max_tokens": 8000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
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


def _cost_of(raw):
    try:
        return round(float(raw.get("total_cost")), 1)
    except Exception:
        return None


def gen_prompt(pid, stmt, prev_code, prev_score, prev_cost, best_score):
    base = (f"You are solving Frontier-CS research problem '{pid}'. The objective is to MINIMIZE the "
            f"total transfer cost of a multi-cloud broadcast; the judge reports a score "
            f"= 100/(1+total_cost), so LOWER cost => HIGHER score. Maximize the score.\n\n"
            f"PROBLEM README (API spec):\n{stmt}\n\n")
    if prev_code is None:
        return base + API_CONTRACT
    return (base + f"Your previous solution scored {prev_score} (total_cost={prev_cost}; best score so "
            f"far {best_score}). Previous solution.py:\n```python\n{prev_code}\n```\n"
            f"Diagnose what kept the cost high (unbalanced load causing bottlenecks? ignoring cheaper "
            f"multi-hop routes? not splitting partitions across paths?) and output an IMPROVED full "
            f"solution.py.\n" + API_CONTRACT)


def run_claude(pid, stmt, sol_path, model, logdir, label, rounds=6,
               cost_budget=None, ceiling=100.0, patience_rounds=3):
    sol_path = Path(sol_path)
    best_code, best_score = None, None
    history = []
    tok_in = tok_out = 0
    def cur_cost():
        return round(tok_in / 1e6 * 15 + tok_out / 1e6 * 75, 4)
    prev_code, prev_score, prev_tcost = None, None, None
    no_improve = 0; r = 0; stop_reason = "max_rounds"
    while r < rounds:
        start_best = best_score if best_score is not None else -1.0
        prompt = gen_prompt(pid, stmt, prev_code, prev_score, prev_tcost, best_score)
        reply, usage = claude_text(prompt, model)
        tok_in += usage.get("prompt_tokens", 0) or 0
        tok_out += usage.get("completion_tokens", 0) or 0
        code = _extract_py(reply)
        if not code:
            history.append({"round": r, "score": None, "status": "no_code"}); r += 1
            if cost_budget and cur_cost() >= cost_budget: stop_reason = "cost_budget"; break
            continue
        sol_path.write_text(code)
        score, status, raw = evaluate(pid, sol_path)
        tcost = _cost_of(raw)
        history.append({"round": r, "score": score, "status": status, "total_cost": tcost})
        print(f"  [claude round {r}] score={score} total_cost={tcost} status={status} cost=${cur_cost()}")
        prev_code, prev_score, prev_tcost = code, score, tcost
        if score is not None and (best_score is None or score > best_score):
            best_code, best_score = code, score
        r += 1
        cur = best_score if best_score is not None else -1.0
        if cur > 0 and cur <= start_best + 1e-12: no_improve += 1
        else: no_improve = 0
        if best_score is not None and best_score >= ceiling - 0.5: stop_reason = "ceiling"; break
        if cost_budget and cur_cost() >= cost_budget: stop_reason = "cost_budget"; break
        if no_improve >= patience_rounds: stop_reason = "plateau"; break
    if best_code is not None:
        sol_path.write_text(best_code)
    (Path(logdir) / f"research_{pid}_{label}.history.json").write_text(json.dumps(history, indent=2))
    print(f"  [claude DONE] best={best_score} cost=${cur_cost()} rounds_run={r} stop={stop_reason}")
    return best_score, {"history": history, "input_tokens": tok_in, "output_tokens": tok_out,
                        "cost_usd_est": cur_cost(), "rounds_run": r, "stop_reason": stop_reason}


def _extract_plan(text):
    m = re.search(r"MY PLAN:\s*(.+)", text or "")
    return m.group(1).strip()[:300] if m else None


def _engram_init_prompt(pid, stmt, journal_text, best_code, best_score, agent_idx, total_agents):
    role = (f"You are Research Specialist #{agent_idx + 1} of {total_agents} in an ongoing effort to "
            f"MAXIMIZE the judge score (== minimize total transfer cost) on Frontier-CS research "
            f"problem '{pid}'. You have a FRESH context: everything earlier agents learned is in the "
            f"research journal below.\n\n")
    task = (f"Objective: minimize total broadcast cost; score = 100/(1+total_cost), higher is better.\n\n"
            f"PROBLEM README (API spec):\n{stmt}\n")
    mem = ""
    if journal_text.strip():
        mem += ("\nRESEARCH JOURNAL (accumulated insights from PRIOR agents — read this FIRST, build on "
                "what worked, and do NOT repeat approaches already shown to fail):\n"
                f"{journal_text}\n")
    if best_code:
        mem += (f"\nBEST SOLUTION SO FAR (score {best_score}). Build on it or beat it:\n"
                f"```python\n{best_code}\n```\n")
    plan = ("\nBefore writing code, state exactly one line beginning 'MY PLAN:' describing the approach "
            "you will try and why. Then output the full solution.py.\n" + API_CONTRACT)
    return role + task + mem + "\n" + STRUGGLE_PROTOCOL + plan


def _engram_refine_prompt(pid, prev_code, prev_score, prev_cost, best_score):
    return (f"Your last solution scored {prev_score} (total_cost={prev_cost}; best this run {best_score}). "
            f"Diagnose what kept the cost high, then output an IMPROVED full solution.py.\n\n"
            + STRUGGLE_PROTOCOL +
            f"\nPrevious solution.py:\n```python\n{prev_code}\n```\n" + API_CONTRACT)


def _engram_summary_prompt(pid, tried):
    lines = "\n".join(f"- plan: {t['plan']} | score: {t['score']} | cost: {t['total_cost']} | status: {t['status']}" for t in tried) or "(no successful attempts)"
    return ("Write a handoff summary for the NEXT research agent, who starts fresh and sees ONLY this "
            "summary. Use EXACTLY these sections and be concrete:\n"
            "## Summary for Next Agent\n"
            "**Best Result** — score/cost and a one-line description of the approach that got it.\n"
            "**What I Tried** — per approach: the idea, why, and the measured result.\n"
            "**Key Insights** — what actually lowers the cost on this problem.\n"
            "**Approaches That Didn't Work (and Why)**.\n"
            "**Recommended Next Steps**.\n\n"
            f"Your attempts this run (problem '{pid}'):\n{lines}\n")


def run_engram(pid, stmt, sol_path, model, logdir, label, agents=3, rounds_per_agent=3,
               cost_budget=None, ceiling=100.0, patience_agents=2):
    sol_path = Path(sol_path)
    workdir = Path(logdir) / f"research_{pid}_{label}_engram"
    kb = workdir / "knowledgebase"
    kb.mkdir(parents=True, exist_ok=True)
    journal_path = workdir / "research_journal.md"
    journal_path.write_text(f"# Research Journal — Frontier-CS research '{pid}'\n")
    best_code, best_score = None, None
    tok_in = tok_out = 0
    history, agent_summaries = [], []
    def cur_cost():
        return round(tok_in / 1e6 * 15 + tok_out / 1e6 * 75, 4)
    no_improve = 0; ai = 0; stop_reason = "max_agents"
    while ai < agents:
        start_best = best_score if best_score is not None else -1.0
        journal_text = journal_path.read_text()
        agent_dir = kb / f"agent_{ai}"
        agent_dir.mkdir(parents=True, exist_ok=True)
        prev_code, prev_score, prev_tcost, tried = None, None, None, []
        hit = None
        for r in range(rounds_per_agent):
            if r == 0:
                prompt = _engram_init_prompt(pid, stmt, journal_text, best_code, best_score, ai, agents)
            else:
                prompt = _engram_refine_prompt(pid, prev_code, prev_score, prev_tcost, best_score)
            reply, usage = claude_text(prompt, model)
            tok_in += usage.get("prompt_tokens", 0) or 0
            tok_out += usage.get("completion_tokens", 0) or 0
            plan = _extract_plan(reply)
            code = _extract_py(reply)
            if not code:
                history.append({"agent": ai, "round": r, "score": None, "status": "no_code", "plan": plan})
                continue
            sol_path.write_text(code)
            score, status, raw = evaluate(pid, sol_path)
            tcost = _cost_of(raw)
            history.append({"agent": ai, "round": r, "score": score, "status": status, "total_cost": tcost, "plan": plan})
            tried.append({"plan": plan or "(none stated)", "score": score, "status": status, "total_cost": tcost})
            (agent_dir / f"exp_{r}.json").write_text(json.dumps(
                {"round": r, "plan": plan, "score": score, "status": status, "total_cost": tcost, "code": code}, indent=2))
            print(f"  [engram a{ai} r{r}] score={score} total_cost={tcost} status={status} cost=${cur_cost()} plan={plan}")
            prev_code, prev_score, prev_tcost = code, score, tcost
            if score is not None and (best_score is None or score > best_score):
                best_code, best_score = code, score
            if best_score is not None and best_score >= ceiling - 0.5:
                hit = "ceiling"; break
            if cost_budget and cur_cost() >= cost_budget:
                hit = "cost_budget"; break
        summ, usage = claude_text(_engram_summary_prompt(pid, tried), model)
        tok_in += usage.get("prompt_tokens", 0) or 0
        tok_out += usage.get("completion_tokens", 0) or 0
        agent_summaries.append(summ)
        with open(journal_path, "a") as jf:
            jf.write(f"\n## Agent {ai} handoff (global best so far: {best_score})\n{summ}\n\n---\n")
        ai += 1
        cur = best_score if best_score is not None else -1.0
        if cur > 0 and cur <= start_best + 1e-12:
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
    (Path(logdir) / f"research_{pid}_{label}.history.json").write_text(json.dumps(history, indent=2))
    print(f"  [engram DONE] best={best_score} cost=${cur_cost()} agents_run={ai} stop={stop_reason}")
    return best_score, {"history": history, "input_tokens": tok_in, "output_tokens": tok_out,
                        "cost_usd_est": cur_cost(), "agents_run": ai, "rounds_per_agent": rounds_per_agent,
                        "code_generations": len([h for h in history if h.get("status") == "success"]),
                        "stop_reason": stop_reason, "journal": str(journal_path)}


def run_nous(pid, stmt, ws, model, logdir, nous_iters, label):
    import yaml
    ws = Path(ws); ws.mkdir(parents=True, exist_ok=True)
    (ws / "solution.py").write_text(SEED)
    sh("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed", cwd=str(ws))
    pd = _probdir(pid)
    fmeasure = ws.parent / f"fmeasure_{pid}.sh"
    fmeasure.write_text(
        "#!/bin/bash\n"
        "# Usage: fmeasure.sh <solution.py> -> prints 'SCORE: <n>' (score=100/(1+total_cost), higher better)\n"
        f"cd {shlex.quote(str(pd))} || exit 2\n"
        "tmp=$(mktemp)\n"
        f"{shlex.quote(str(_evalpy(pid)))} {shlex.quote(str(pd / 'evaluator.py'))} "
        f"--solution \"$1\" --spec {shlex.quote(str(pd / 'resources' / 'submission_spec.json'))} "
        "--out \"$tmp\" >/dev/null 2>&1\n"
        "s=$(python3 -c \"import json,sys;d=json.load(open('$tmp'));print(d.get('score',0.0) if not d.get('error') and d.get('runs_successfully',0.0)==1.0 else 0.0)\" 2>/dev/null)\n"
        "rm -f \"$tmp\"\n"
        'echo "SCORE: ${s:-0.0}"\n')
    fmeasure.chmod(0o755)
    desc = (
        f"You are solving Frontier-CS research problem '{pid}'. The objective is to MINIMIZE the total "
        f"multi-cloud broadcast transfer cost; the judge reports score = 100/(1+total_cost) (higher is "
        f"better), so lower cost means higher score. MAXIMIZE the score.\n\n"
        f"Your working directory is a git worktree containing 'solution.py'. It must define `class "
        f"Solution` with `solve(self, spec_path=None)` returning {{'code': '<algorithm source>'}}, where "
        f"the algorithm source defines a `BroadCastTopology` class and `search_algorithm(src, dsts, G, "
        f"num_partitions)`. Edit solution.py with your algorithm, then measure.\n\n"
        f"MEASURE the objective with this ONE command (do not run the evaluator any other way):\n"
        f"    bash {fmeasure} $PWD/solution.py\n"
        f"It prints a single line 'SCORE: <n>' (0-100, higher is better). Record that number in the "
        f"finding metadata under key 'score'. Each experiment arm should try a distinct routing "
        f"strategy (shortest-cost tree, multi-path partition splitting, Steiner/relay routing, "
        f"load-balancing to avoid bandwidth bottlenecks) and report its measured score.\n\n"
        f"PROBLEM README:\n{stmt}"
    )
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{pid}-{label}").strip("-")
    spec = {
        "research_question": f"What routing algorithm minimizes total broadcast cost (maximizes judge score) for research problem '{pid}'?",
        "run_id": run_slug,
        "max_iterations": nous_iters,
        "sandbox": "bypass",
        "target_system": {
            "name": f"frontier-cs::research::{pid}",
            "description": desc,
            "repo_path": str(ws),
            "observable_metrics": ["score"],
            "controllable_knobs": ["solution_py"],
        },
        "objective": {"weights": {"score": 1.0}},
        "models": {"design": model, "execute_analyze": model, "report": model},
        "prompts": {"methodology_layer": f"{NOUS_REPO}/prompts/methodology", "domain_adapter_layer": None},
    }
    camp = ws.parent / f"campaign_{pid}.yaml"
    camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    env = dict(os.environ)
    env["NOUS_CAMPAIGN_PARENT"] = str(ws.parent / "nous_runs")
    log = Path(logdir) / f"research_{pid}_{label}.nous.log"
    cmd = [NOUS_BIN, "run", str(camp), "--auto-approve", "--agent", "sdk", "--sandbox", "bypass",
           "--max-iterations", str(nous_iters), "--timeout", "2400"]
    with open(log, "w") as lf:
        subprocess.run(cmd, cwd=NOUS_REPO, env=env, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=14400)
    camp_dir = ws.parent / "nous_runs" / run_slug
    seen, cands = set(), []
    globbed = (list((ws / ".nous-experiments").glob("**/solution.py"))
               + list(camp_dir.glob("runs/iter-*/inputs/*solution*.py"))
               + [ws / "solution.py"])
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
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--agents", type=int, default=3)
    ap.add_argument("--rounds-per-agent", type=int, default=3)
    ap.add_argument("--cost-budget", type=float, default=None)
    args = ap.parse_args()
    pid = args.problem_id
    label = args.label or args.agent
    Path(args.logdir).mkdir(parents=True, exist_ok=True)
    stmt = statement(pid)
    meta = {"problem_id": pid, "track": "research", "agent": args.agent, "label": label, "model": args.model}
    t0 = time.time()

    if args.agent == "claude":
        sol = Path(args.logdir) / f"research_{pid}_{label}.solution.py"
        sol.write_text(SEED)
        best_score, info = run_claude(pid, stmt, sol, args.model, args.logdir, label, rounds=args.rounds,
                                      cost_budget=args.cost_budget)
        final_score, status, raw = evaluate(pid, sol)
        meta.update(final_score=final_score, status=status, solution=str(sol), total_cost=_cost_of(raw),
                    best_score=best_score, rounds=len(info["history"]), history=info["history"],
                    input_tokens=info["input_tokens"], output_tokens=info["output_tokens"],
                    cost_usd_est=info["cost_usd_est"], stop_reason=info["stop_reason"])
    elif args.agent == "engram":
        sol = Path(args.logdir) / f"research_{pid}_{label}.solution.py"
        sol.write_text(SEED)
        best_score, info = run_engram(pid, stmt, sol, args.model, args.logdir, label,
                                      agents=args.agents, rounds_per_agent=args.rounds_per_agent,
                                      cost_budget=args.cost_budget)
        final_score, status, raw = evaluate(pid, sol)
        meta.update(final_score=final_score, status=status, solution=str(sol), total_cost=_cost_of(raw),
                    best_score=best_score, method="Engram-style (reimplementation)",
                    agents_run=info["agents_run"], rounds_per_agent=args.rounds_per_agent,
                    code_generations=info["code_generations"], cost_budget=args.cost_budget,
                    stop_reason=info["stop_reason"], history=info["history"],
                    input_tokens=info["input_tokens"], output_tokens=info["output_tokens"],
                    cost_usd_est=info["cost_usd_est"], journal=info["journal"])
    else:
        ws = Path(args.logdir) / f"research_{pid}_{label}_ws"
        cands = run_nous(pid, stmt, ws, args.model, args.logdir, args.nous_iters, label)
        scored = []
        for c in cands:
            s, st, raw = evaluate(pid, c)
            scored.append({"path": str(c), "score": s, "status": st, "total_cost": _cost_of(raw)})
            print("CAND", c, "score=", s, st)
        scored = [x for x in scored if isinstance(x["score"], (int, float))]
        best = max(scored, key=lambda x: x["score"], default=None)
        meta["candidates"] = scored
        meta["final_score"] = best["score"] if best else None
        meta["total_cost"] = best["total_cost"] if best else None
        meta["solution"] = best["path"] if best else None

    meta["seconds"] = round(time.time() - t0, 1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(meta, indent=2))
    print("RESULT", json.dumps({k: meta.get(k) for k in ("problem_id", "label", "final_score", "total_cost", "status", "seconds")}))


if __name__ == "__main__":
    main()
