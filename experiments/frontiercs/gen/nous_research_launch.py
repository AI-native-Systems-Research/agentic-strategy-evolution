#!/usr/bin/env python3
"""Generalized NOUS research-track launcher for local-eval problems (grammar_fuzzing, llm_sql, ...).

Builds a task-correct campaign: a valid seed solution.py, an API-contract description from the README,
and an fmeasure.sh that scores via the problem's own evaluator (evaluator.py --solution --out; NO
cloudcast --spec) printing 'SCORE: <n>' (higher better). Runs Nous (SDK), then harvests the best
solution.py it produced by RE-JUDGING every persisted candidate on the same evaluator, writes a pred,
and runs a cheat audit over the Nous transcripts (flags any read of evaluator.py / reference solutions /
baseline_cache.json / results internals). Cost is iteration-capped (reported actual, kept < $50).

Usage:
  nous_research_launch.py grammar_fuzzing/seed/sql --slug gf_seed_sql --niters 8 \
    --out preds/gf_seed_sql.nous.research.json --logdir ~/frontier/gen_logs
"""
import argparse, json, os, re, shlex, subprocess, time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
NOUS_REPO = os.path.expanduser("~/nous_repo")
NOUS_BIN = f"{NOUS_REPO}/.venv/bin/nous"


def probdir(pid): return Path(FRONTIER) / "research" / "problems" / str(pid)
def evalpy(pid):  return probdir(pid) / ".evalvenv" / "bin" / "python3"
def statement(pid):
    p = probdir(pid) / "readme"
    return p.read_text() if p.exists() else f"(research problem {pid})"


# Minimal valid seeds per solution API (so the campaign starts from a scored baseline).
SEEDS = {
    "grammar_fuzzing/fuzzer": (
        "class Solution:\n"
        "    def solve(self, resources_path: str) -> dict:\n"
        "        return {'code': "
        "\"def fuzz(parse_sql):\\n    parse_sql(['SELECT 1;', 'SELECT * FROM t;', 'INSERT INTO t VALUES (1);'])\\n\""
        "}\n"),
    "grammar_fuzzing": (
        "class Solution:\n"
        "    def solve(self, resources_path: str):\n"
        "        return ['SELECT 1;', 'SELECT * FROM t;', 'INSERT INTO t VALUES (1);']\n"),
    "llm_sql": (
        "import pandas as pd\n"
        "class Solution:\n"
        "    def solve(self, df, early_stop=100000, row_stop=4, col_stop=2, col_merge=None,\n"
        "              one_way_dep=None, distinct_value_threshold=0.7, parallel=True):\n"
        "        return df\n"),
    "llm_router": (
        "class Solution:\n"
        "    def solve(self, query, eval_name, candidate_models):\n"
        "        return candidate_models[0] if candidate_models else 'cheap'\n"),
}


def seed_for(pid):
    for k, v in SEEDS.items():
        if str(pid).startswith(k): return v
    return "class Solution:\n    def solve(self, *a, **k):\n        raise NotImplementedError\n"


def evaluate(pid, sol_path, timeout=600):
    pd = probdir(pid)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf: out = tf.name
    try:
        subprocess.run(f"{shlex.quote(str(evalpy(pid)))} {shlex.quote(str(pd/'evaluator.py'))} "
                       f"--solution {shlex.quote(str(sol_path))} --out {shlex.quote(out)}",
                       shell=True, cwd=str(pd), capture_output=True, text=True, timeout=timeout)
        try: data = json.loads(Path(out).read_text())
        except Exception: return 0.0, {}
    except subprocess.TimeoutExpired:
        return 0.0, {}
    finally:
        try: os.unlink(out)
        except OSError: pass
    if data.get("error") or data.get("runs_successfully", 0.0) != 1.0: return 0.0, data
    return float(data.get("score", 0.0)), data


CHEAT_PATTERNS = ["evaluator.py", "/solutions/", "baseline_cache.json", "results.json", "ground_truth", ".ans"]


def cheat_audit(camp_dir, ws):
    hits = []
    for log in list(Path(camp_dir).rglob("*.md")) + list(Path(camp_dir).rglob("*.jsonl")) + list(Path(ws).rglob("executor_log*")):
        try: txt = log.read_text(errors="ignore")
        except Exception: continue
        for pat in CHEAT_PATTERNS:
            if pat in txt:
                hits.append({"file": str(log).replace(os.path.expanduser("~"), "~"), "pattern": pat})
    return hits


def main():
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--niters", type=int, default=8)
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True)
    ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    a = ap.parse_args()
    pid = a.problem_id; stmt = statement(pid)
    Path(a.logdir).mkdir(parents=True, exist_ok=True)
    ws = Path(a.logdir) / f"research_{a.slug}_ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "solution.py").write_text(seed_for(pid))
    subprocess.run("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed",
                   shell=True, cwd=str(ws))
    pd = probdir(pid)
    fmeasure = ws.parent / f"fmeasure_{a.slug}.sh"
    fmeasure.write_text(
        "#!/bin/bash\n"
        "# fmeasure.sh <solution.py> -> 'SCORE: <n>' (higher better) via the problem's own evaluator\n"
        f"cd {shlex.quote(str(pd))} || exit 2\n"
        "tmp=$(mktemp)\n"
        f"{shlex.quote(str(evalpy(pid)))} {shlex.quote(str(pd/'evaluator.py'))} --solution \"$1\" --out \"$tmp\" >/dev/null 2>&1\n"
        "s=$(python3 -c \"import json;d=json.load(open('$tmp'));print(d.get('score',0.0) if not d.get('error') and d.get('runs_successfully',0.0)==1.0 else 0.0)\" 2>/dev/null)\n"
        "rm -f \"$tmp\"; echo \"SCORE: ${s:-0.0}\"\n")
    fmeasure.chmod(0o755)
    desc = (
        f"You are solving Frontier-CS research problem '{pid}'. Read the README below: it states the exact "
        f"objective, the scoring metric, and the required Solution API. Your working directory is a git "
        f"worktree containing 'solution.py'. Edit solution.py to implement `class Solution` EXACTLY as the "
        f"README's API Specification requires (same method name/signature/return type).\n\n"
        f"MEASURE the objective with this ONE command only (do not invoke the evaluator any other way, and "
        f"do not read the evaluator source or any reference solution):\n"
        f"    bash {fmeasure} $PWD/solution.py\n"
        f"It prints 'SCORE: <n>' (higher is better). Record that number in finding metadata under key "
        f"'score'. Each experiment arm should try a DISTINCT strategy and report its measured score.\n\n"
        f"PROBLEM README:\n{stmt}")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{a.slug}").strip("-")
    spec = {
        "research_question": f"What solution maximizes the judge score for research problem '{pid}'?",
        "run_id": slug, "max_iterations": a.niters, "sandbox": "bypass",
        "target_system": {"name": f"frontier-cs::research::{pid}", "description": desc,
                          "repo_path": str(ws), "observable_metrics": ["score"],
                          "controllable_knobs": ["solution_py"]},
        "objective": {"weights": {"score": 1.0}},
        "models": {"design": a.model, "execute_analyze": a.model, "report": a.model},
        "prompts": {"methodology_layer": f"{NOUS_REPO}/prompts/methodology", "domain_adapter_layer": None},
    }
    camp = ws.parent / f"campaign_{a.slug}.yaml"; camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    env = dict(os.environ); env["NOUS_CAMPAIGN_PARENT"] = str(ws.parent / "nous_runs")
    log = Path(a.logdir) / f"research_{a.slug}.nous.log"
    cmd = [NOUS_BIN, "run", str(camp), "--auto-approve", "--agent", "sdk", "--sandbox", "bypass",
           "--max-iterations", str(a.niters), "--timeout", "2400"]
    t0 = time.time()
    with open(log, "w") as lf:
        try: subprocess.run(cmd, cwd=NOUS_REPO, env=env, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=14400)
        except subprocess.TimeoutExpired: pass
    camp_dir = ws.parent / "nous_runs" / slug
    # harvest: re-judge every persisted solution.py candidate
    seed = seed_for(pid)
    cands, seen = [], set()
    for sc in (list((ws / ".nous-experiments").rglob("solution.py")) +
               list(camp_dir.rglob("solution.py")) + [ws / "solution.py"]):
        if not sc.exists(): continue
        body = sc.read_text()
        if not body.strip() or body == seed or body in seen: continue
        seen.add(body); cands.append(sc)
    best = -1.0; bestf = None; ev = []
    for f in cands:
        s, _ = evaluate(pid, f); ev.append({"file": str(f).replace(os.path.expanduser("~"), "~"), "score": s})
        if s > best: best, bestf = s, f
    # cost from campaign llm_metrics
    import glob as _g
    cost = 0.0
    for mf in set(_g.glob(str(camp_dir) + "/**/llm_metrics.jsonl", recursive=True)):
        for l in open(mf, errors="ignore"):
            try: cost += json.loads(l).get("cost_usd", 0) or 0
            except Exception: pass
    hits = cheat_audit(camp_dir, ws)
    pred = {"problem_id": pid, "track": "research", "agent": "nous", "label": a.slug, "model": a.model,
            "final_score": (round(best, 2) if best >= 0 else None), "cost_usd": round(cost, 2),
            "n_candidates": len(cands), "best_file": (str(bestf).replace(os.path.expanduser("~"), "~") if bestf else None),
            "cheat_audit_hits": hits, "elapsed_s": round(time.time()-t0, 1),
            "isolation": "nous SDK in isolated git worktree; sanctioned scoring via fmeasure only; cheat-audited",
            "evidence": ev}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(pred, indent=2))
    print(f"NOUS DONE {pid}: best={best} cost=${cost:.2f} cands={len(cands)} cheat_hits={len(hits)} -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
