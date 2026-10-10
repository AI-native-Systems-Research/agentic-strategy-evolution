#!/usr/bin/env python3
"""Hardened, SANDBOXED Nous research launcher. Prevents the two exploits seen in the un-sandboxed run:
  (1) grammar_fuzzing: import-hook that calls sql_engine internals directly to game coverage;
  (2) llm_router: reading the labeled test CSV to return a per-query oracle.

Isolation design (mirrors the algorithmic judge-daemon pattern):
  - The Nous `nous run` subprocess (and its SDK claude children) run under `sandbox-exec` with a profile
    that DENIES file-read of ~/frontier/Frontier-CS/research and .../datasets. So the agent cannot read
    the engine source, the evaluator, reference solutions, or the labeled datasets at generation time.
  - Scoring still works via an OUT-OF-SANDBOX daemon thread in THIS (unsandboxed) launcher process: the
    sandboxed agent drops solution.py into an inbox; the daemon scores it with the problem's own
    .evalvenv evaluator and writes the score to an outbox. fmeasure.sh (the only sanctioned measure)
    does the inbox/outbox handshake and never touches ~/frontier directly.
  - Post-harvest EXPLOIT AUDIT: reconstruct every iteration's solution from its stored git patch, reject
    any that contain exploit signatures (sys.meta_path/import-hook, reading routerbench/reference_data/
    test CSVs, direct sql_engine internal calls), and report the best CLEAN candidate's reproduced score.

Usage:
  nous_research_isolated.py grammar_fuzzing/seed/sql --slug gf_seed_sql_iso --niters 8 \
     --out preds/gf_seed_sql.nous.research.json
"""
import argparse, glob, json, os, re, shlex, subprocess, tempfile, threading, time
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
NOUS_REPO = os.path.expanduser("~/nous_repo"); NOUS_BIN = f"{NOUS_REPO}/.venv/bin/nous"
FR_ROOT = os.path.expanduser("~/frontier/Frontier-CS")

def probdir(pid): return Path(FRONTIER) / "research" / "problems" / str(pid)
def evalpy(pid):  return probdir(pid) / ".evalvenv" / "bin" / "python3"
def statement(pid):
    p = probdir(pid) / "readme"; return p.read_text() if p.exists() else f"(research problem {pid})"

SEEDS = {
    "grammar_fuzzing/fuzzer": "class Solution:\n    def solve(self, resources_path):\n        return {'code': \"def fuzz(parse_sql):\\n    parse_sql(['SELECT 1;'])\\n\"}\n",
    "grammar_fuzzing": "class Solution:\n    def solve(self, resources_path):\n        return ['SELECT 1;', 'SELECT * FROM t;', 'INSERT INTO t VALUES (1);']\n",
    "llm_router": "class Solution:\n    def solve(self, query, eval_name, candidate_models):\n        return candidate_models[0] if candidate_models else 'cheap'\n",
}
def seed_for(pid):
    for k, v in SEEDS.items():
        if str(pid).startswith(k): return v
    return "class Solution:\n    def solve(self, *a, **k):\n        raise NotImplementedError\n"

# Exploit signatures that invalidate a research solution (gaming, not solving).
EXPLOIT_SIGS = [
    (r"sys\.meta_path", "import-hook (sys.meta_path)"),
    (r"find_spec\s*\(", "import-hook (find_spec)"),
    (r"importlib\.util\.find_spec|exec_module|module_from_spec", "import machinery to reach internals"),
    (r"sql_engine\.(parser|tokenizer|ast_nodes)", "direct engine-internal access"),
    (r"\b_match\b|TokenType\.", "calling parser/tokenizer internals directly"),
    (r"routerbench", "reads the labeled RouterBench dataset"),
    (r"reference_data\.csv", "reads reference_data.csv (labels)"),
    (r"_test\.csv|routerbench_0shot_test", "reads the labeled test split"),
    (r"read_csv|read_pickle|read_parquet", "reads a data file from disk (possible label leak)"),
    (r"/datasets/|resources/datasets", "accesses the datasets directory directly"),
]
def exploit_hits(code):
    hits = []
    for pat, desc in EXPLOIT_SIGS:
        if re.search(pat, code): hits.append(desc)
    return hits

def judge_clean(pid, code, timeout=600):
    """Judge a solution ONLY if it has no exploit signatures; return (score, hits)."""
    hits = exploit_hits(code)
    if hits: return None, hits
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as tf:
        tf.write(code); sp = tf.name
    pd = probdir(pid)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of: out = of.name
    try:
        subprocess.run(f"{shlex.quote(str(evalpy(pid)))} {shlex.quote(str(pd/'evaluator.py'))} "
                       f"--solution {shlex.quote(sp)} --out {shlex.quote(out)}",
                       shell=True, cwd=str(pd), capture_output=True, text=True, timeout=timeout)
        try: data = json.loads(Path(out).read_text())
        except Exception: return 0.0, []
    except subprocess.TimeoutExpired:
        return 0.0, []
    finally:
        for f in (sp, out):
            try: os.unlink(f)
            except OSError: pass
    if data.get("error") or data.get("runs_successfully", 0.0) != 1.0: return 0.0, []
    return float(data.get("score", 0.0)), []

def reconstruct(patch):
    lines = Path(patch).read_text(errors="ignore").splitlines()
    i = 0
    while i < len(lines) and not lines[i].startswith("@@"): i += 1
    res = []
    for l in lines[i+1:]:
        if l.startswith(("+++", "---", "diff ", "index ", "@@")): continue
        if l.startswith("+"): res.append(l[1:])
        elif l.startswith(" "): res.append(l[1:])
    return "\n".join(res) + "\n"

# ---- out-of-sandbox scoring daemon (thread) ----
def start_daemon(pid, root, stop_evt):
    inbox = Path(root)/"inbox"; outbox = Path(root)/"outbox"
    inbox.mkdir(parents=True, exist_ok=True); outbox.mkdir(parents=True, exist_ok=True)
    pd = probdir(pid)
    def score_file(f):
        try:  # reject gaming IN-LOOP so the agent gets 0 feedback for exploits and pursues legit solutions
            if exploit_hits(Path(f).read_text(errors="ignore")): return 0.0
        except Exception: pass
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as of: out = of.name
        try:
            subprocess.run(f"{shlex.quote(str(evalpy(pid)))} {shlex.quote(str(pd/'evaluator.py'))} "
                           f"--solution {shlex.quote(str(f))} --out {shlex.quote(out)}",
                           shell=True, cwd=str(pd), capture_output=True, text=True, timeout=600)
            d = json.loads(Path(out).read_text())
            s = d.get("score", 0.0) if (not d.get("error") and d.get("runs_successfully", 0.0) == 1.0) else 0.0
        except Exception: s = 0.0
        finally:
            try: os.unlink(out)
            except OSError: pass
        return s
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
    t = threading.Thread(target=loop, daemon=True); t.start(); return t

def main():
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id"); ap.add_argument("--slug", required=True)
    ap.add_argument("--niters", type=int, default=8); ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True); ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    a = ap.parse_args(); pid = a.problem_id; stmt = statement(pid)
    Path(a.logdir).mkdir(parents=True, exist_ok=True)
    ws = Path(a.logdir) / f"research_{a.slug}_ws"; ws.mkdir(parents=True, exist_ok=True)
    (ws/"solution.py").write_text(seed_for(pid))
    subprocess.run("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed", shell=True, cwd=str(ws))
    # daemon
    djroot = f"/tmp/fcs_rjudge2/{a.slug}"; stop = threading.Event(); start_daemon(pid, djroot, stop)
    # sandbox profile
    prof = Path(a.logdir)/f"sandbox_{a.slug}.sb"
    prof.write_text('(version 1)\n(allow default)\n'
                    f'(deny file-read* (subpath "{FR_ROOT}/research"))\n'
                    f'(deny file-read* (subpath "{FR_ROOT}/datasets"))\n')
    # fmeasure: inbox/outbox handshake (no direct ~/frontier access)
    fm = ws.parent/f"fmeasure_{a.slug}.sh"
    fm.write_text("#!/bin/bash\n"
        "# fmeasure.sh <solution.py> -> 'SCORE: <n>' via the out-of-sandbox judge daemon\n"
        f'IN="{djroot}/inbox"; OUT="{djroot}/outbox"\n'
        'tok="m$$_$RANDOM"\n'
        'cp "$1" "$IN/$tok.py"\n'
        'for i in $(seq 1 600); do\n'
        '  if [ -f "$OUT/$tok.score" ]; then cat "$OUT/$tok.score"; rm -f "$OUT/$tok.score"; exit 0; fi\n'
        '  sleep 1\n'
        'done\n'
        'echo "SCORE: 0.0"\n')
    fm.chmod(0o755)
    desc = (f"You are solving Frontier-CS research problem '{pid}'. Read the README below (objective, "
            f"scoring metric, and the required Solution API). Edit solution.py in your working directory to "
            f"implement `class Solution` EXACTLY per the README API.\n\n"
            f"RULES (enforced): you are sandboxed and CANNOT read the problem's internal files (engine "
            f"source, evaluator, datasets, reference solutions). Solve the task legitimately: your solution "
            f"must do the real work (generate SQL / choose a route). Do NOT use import hooks, sys.meta_path, "
            f"or call engine internals, and do NOT read dataset/label files from disk — such solutions are "
            f"rejected.\n\n"
            f"MEASURE only with this command: bash {fm} $PWD/solution.py  (prints 'SCORE: <n>', higher is "
            f"better). Record it in finding metadata under key 'score'.\n\nPROBLEM README:\n{stmt}")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{a.slug}").strip("-")
    spec = {"research_question": f"What legitimate solution maximizes the score for '{pid}'?",
            "run_id": slug, "max_iterations": a.niters, "sandbox": "bypass",
            "target_system": {"name": f"frontier-cs::research::{pid}", "description": desc,
                              "repo_path": str(ws), "observable_metrics": ["score"], "controllable_knobs": ["solution_py"]},
            "objective": {"weights": {"score": 1.0}},
            "models": {"design": a.model, "execute_analyze": a.model, "report": a.model},
            "prompts": {"methodology_layer": f"{NOUS_REPO}/prompts/methodology", "domain_adapter_layer": None}}
    camp = ws.parent/f"campaign_{a.slug}.yaml"; camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    env = dict(os.environ); env["NOUS_CAMPAIGN_PARENT"] = str(ws.parent/"nous_runs")
    log = Path(a.logdir)/f"research_{a.slug}.nous.log"
    cmd = ["sandbox-exec", "-f", str(prof), NOUS_BIN, "run", str(camp), "--auto-approve", "--agent", "sdk",
           "--sandbox", "bypass", "--max-iterations", str(a.niters), "--timeout", "2400"]
    t0 = time.time()
    with open(log, "w") as lf:
        try: subprocess.run(cmd, cwd=NOUS_REPO, env=env, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=14400)
        except subprocess.TimeoutExpired: pass
    stop.set()
    # harvest: reconstruct every iter's solution from patches; audit + judge CLEAN ones
    camp_dir = ws.parent/"nous_runs"/slug
    patches = sorted(glob.glob(str(camp_dir)+"/runs/iter-*/patches/*.patch"))
    best = -1.0; bestsrc = None; ev = []; rejected = []
    seen = set()
    cand_sources = [(p, reconstruct(p)) for p in patches if not p.endswith("cumulative.patch")]
    # also the final ws solution.py
    if (ws/"solution.py").exists(): cand_sources.append((str(ws/"solution.py"), (ws/"solution.py").read_text()))
    for src, code in cand_sources:
        if not code.strip() or code in seen: continue
        seen.add(code)
        sc, hits = judge_clean(pid, code)
        tag = src.replace(os.path.expanduser("~"), "~")
        if hits: rejected.append({"src": tag, "exploits": hits})
        else: ev.append({"src": tag, "score": sc});
        if sc is not None and sc > best: best = sc; bestsrc = tag
    cost = 0.0
    for mf in set(glob.glob(str(camp_dir)+"/**/llm_metrics.jsonl", recursive=True)):
        for l in open(mf, errors="ignore"):
            try: cost += json.loads(l).get("cost_usd", 0) or 0
            except Exception: pass
    pred = {"problem_id": pid, "track": "research", "agent": "nous", "label": a.slug, "model": a.model,
            "final_score": (round(best, 2) if best >= 0 else None), "cost_usd": round(cost, 2),
            "n_clean_candidates": len(ev), "n_rejected_exploits": len(rejected),
            "best_source": bestsrc, "isolation": "sandbox-exec deny ~/frontier/{research,datasets} + out-of-sandbox judge daemon; measure only via fmeasure; post-harvest exploit audit",
            "rejected_exploit_candidates": rejected, "clean_evidence": ev,
            "elapsed_s": round(time.time()-t0, 1)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(pred, indent=2))
    print(f"NOUS-ISO DONE {pid}: best_clean={best} cost=${cost:.2f} clean={len(ev)} rejected={len(rejected)} -> {a.out}", flush=True)

if __name__ == "__main__":
    main()
