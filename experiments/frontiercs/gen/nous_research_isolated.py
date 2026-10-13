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
    any that contain exploit signatures (sys.meta_path/import-hook, reading routerbench/test-split/
    test CSVs, direct sql_engine internal calls), and report the best CLEAN candidate's reproduced score.

Usage:
  nous_research_isolated.py grammar_fuzzing/seed/sql --slug gf_seed_sql_iso --niters 8 \
     --out preds/gf_seed_sql.nous.research.json
"""
import argparse, glob, json, os, re, shlex, subprocess, tempfile, threading, time
from pathlib import Path

import judge_sandbox as J
import access_rule as A

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
NOUS_REPO = os.path.expanduser("~/nous_repo"); NOUS_BIN = f"{NOUS_REPO}/.venv/bin/nous"
FR_ROOT = os.path.expanduser("~/frontier/Frontier-CS")

FEVAL = os.environ.get("FEVAL_BIN", f"{FRONTIER}/.venv/bin/frontier")
probdir, statement, is_algo = A.probdir, A.statement, A.is_algo
def evalpy(pid):  return probdir(pid) / ".evalvenv" / "bin" / "python3"
def ext(pid): return ".cpp" if is_algo(pid) else ".py"
def sol_name(pid): return "solution" + ext(pid)
ALGO_SEED = "#include <bits/stdc++.h>\nusing namespace std;\nint main(){return 0;}\n"

SEEDS = {
    "grammar_fuzzing/fuzzer": "class Solution:\n    def solve(self, resources_path):\n        return {'code': \"def fuzz(parse_sql):\\n    parse_sql(['SELECT 1;'])\\n\"}\n",
    "grammar_fuzzing": "class Solution:\n    def solve(self, resources_path):\n        return ['SELECT 1;', 'SELECT * FROM t;', 'INSERT INTO t VALUES (1);']\n",
    "llm_router": "class Solution:\n    def solve(self, query, eval_name, candidate_models):\n        return candidate_models[0] if candidate_models else 'cheap'\n",
}
def seed_for(pid):
    if is_algo(pid): return ALGO_SEED
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
    (r"_test\.csv|routerbench_0shot_test", "reads the labeled test split"),
    # cloudcast: the evaluator prices transfers from the edge data the solution returns, so a
    # solution that rewrites edge cost/throughput fakes a cheap topology instead of finding one
    (r"""\[\s*['"](cost|throughput)['"]\s*\]\s*=(?!=)""", "rewrites edge cost/throughput in returned paths"),
    (r"fmeasure|measure\.sh|fcs_rjudge", "calls the scoring judge from inside the solution"),
    (r"""['"](cost|throughput)['"]\s*:\s*0(\.0*)?\b""", "sets edge cost/throughput to zero in returned paths"),
    (r"/datasets/|resources/datasets", "accesses the datasets directory directly"),
]
ALGO_EXPLOIT_SIGS = [
    (r"testdata|\.ans\b|/problems/\d+", "reads judge test data or answer files"),
    (r"/frontier/|Frontier-CS", "accesses the benchmark tree"),
    (r"fmeasure|measure\.sh|fcs_", "calls the scoring judge from inside the solution"),
]
def exploit_hits(code, pid=None):
    hits = []
    for pat, desc in (ALGO_EXPLOIT_SIGS if pid is not None and is_algo(pid) else EXPLOIT_SIGS):
        if re.search(pat, code): hits.append(desc)
    return hits

def judge_clean(pid, code, timeout=600):
    """Judge a solution ONLY if it has no exploit signatures; return (score, hits)."""
    hits = exploit_hits(code, pid)
    if hits: return None, hits
    if is_algo(pid): return algo_score(pid, code, timeout), []
    return J.score(evalpy(pid), probdir(pid), code, timeout), []

def algo_score(pid, code, timeout=900):
    """Score a C++ solution with the official go-judge (outside any agent sandbox)."""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as f:
        f.write(code); path = f.name
    try:
        r = subprocess.run(f"{FEVAL} eval algorithmic {pid} {shlex.quote(path)} --json", shell=True,
                           capture_output=True, text=True, cwd=FRONTIER, timeout=timeout)
        ms = re.findall(r'"score"\s*:\s*([0-9.]+)', r.stdout + r.stderr)
        return max((float(m) for m in ms), default=0.0)
    except subprocess.TimeoutExpired:
        return 0.0
    finally:
        os.unlink(path)

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
def start_daemon(pid, root, stop_evt, archive):
    inbox = Path(root)/"inbox"; outbox = Path(root)/"outbox"
    inbox.mkdir(parents=True, exist_ok=True); outbox.mkdir(parents=True, exist_ok=True)
    # Nous deletes arm worktrees and its patches miss untracked files, so keep every measured solution here.
    archive = Path(archive); archive.mkdir(parents=True, exist_ok=True)
    pd = probdir(pid)
    def score_file(f):
        code = Path(f).read_text(errors="ignore")
        # reject gaming IN-LOOP so the agent gets 0 feedback for exploits and pursues legit solutions
        if exploit_hits(code, pid): return 0.0
        if is_algo(pid): return algo_score(pid, code)
        return J.score(evalpy(pid), pd, code)
    def loop():
        while not stop_evt.is_set():
            for f in sorted(glob.glob(str(inbox/f"*{ext(pid)}"))):
                tok = Path(f).stem
                try: s = score_file(f)
                except Exception: s = 0.0
                try:
                    n = len(list(archive.glob(f"*{ext(pid)}")))
                    Path(archive/f"m{n:04d}_{time.strftime('%H%M%S')}_score{s:.2f}{ext(pid)}").write_text(Path(f).read_text(errors="ignore"))
                except OSError: pass
                (outbox/f"{tok}.score").write_text(f"SCORE: {s}\n")
                try: os.unlink(f)
                except OSError: pass
            time.sleep(1)
    t = threading.Thread(target=loop, daemon=True); t.start(); return t

def _top_measured(d, k):
    def sc(p):
        m = re.search(r"_score([0-9.]+)\.(py|cpp)$", p); return float(m.group(1)) if m else -1.0
    files = glob.glob(str(Path(d)/"*.py")) + glob.glob(str(Path(d)/"*.cpp"))
    return sorted(files, key=sc, reverse=True)[:k]

def main():
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id"); ap.add_argument("--slug", required=True)
    ap.add_argument("--niters", type=int, default=8)
    ap.add_argument("--design-profile", choices=["standard", "lightweight", "v4"], default="lightweight"); ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--out", required=True); ap.add_argument("--logdir", default=os.path.expanduser("~/frontier/gen_logs"))
    a = ap.parse_args(); pid = a.problem_id; stmt = statement(pid)
    Path(a.logdir).mkdir(parents=True, exist_ok=True)
    ws = Path(a.logdir) / f"research_{a.slug}_ws"; ws.mkdir(parents=True, exist_ok=True)
    (ws/sol_name(pid)).write_text(seed_for(pid))
    subprocess.run("git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -q -m seed", shell=True, cwd=str(ws))
    # daemon
    djroot = f"/tmp/fcs_rjudge2/{a.slug}"; stop = threading.Event()
    measured = Path(a.logdir)/f"research_{a.slug}_measured_{time.strftime('%Y%m%d_%H%M%S')}"
    start_daemon(pid, djroot, stop, measured)
    # sandbox profile
    prof = Path(a.logdir)/f"sandbox_{a.slug}.sb"
    # Deny the benchmark, other runs' artifacts/transcripts, experiment results and other agents' repos;
    # re-allow only this run's workspace, campaign dir, scripts and transcripts (SBPL: last match wins).
    home = os.path.expanduser("~"); rr = os.path.realpath
    run_slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{a.slug}").strip("-")
    deny = [f"{home}/frontier", rr(Path(__file__).resolve().parents[1]), f"{home}/engram_repo", f"{home}/.claude/projects"]
    allow = [rr(ws), rr(ws.parent/"nous_runs"/run_slug), rr(ws.parent/f"fmeasure_{a.slug}.sh"),
             rr(ws.parent/f"campaign_{a.slug}.yaml"), rr(prof)]
    proj_key = re.sub(r"[^A-Za-z0-9]", "-", rr(ws))
    prof.write_text('(version 1)\n(allow default)\n'
                    + "".join(f'(deny file-read* (subpath "{rr(d)}"))\n' for d in deny)
                    + "".join(f'(allow file-read* (subpath "{p_}"))\n' for p_ in allow)
                    + f'(allow file-read* (regex #"^{re.escape(rr(home))}/\\.claude/projects/{re.escape(proj_key)}"))\n'
                    # git worktree add must stat parent dirs; metadata only (no file contents)
                    + A.sbpl_task_access(pid)
                    + '(allow file-read-metadata)\n')
    # fmeasure: inbox/outbox handshake (no direct ~/frontier access)
    fm = ws.parent/f"fmeasure_{a.slug}.sh"
    fm.write_text("#!/bin/bash\n"
        f"# fmeasure.sh <{sol_name(pid)}> -> 'SCORE: <n>' via the out-of-sandbox judge daemon\n"
        f'IN="{djroot}/inbox"; OUT="{djroot}/outbox"\n'
        'tok="m$$_$RANDOM"\n'
        f'cp "$1" "$IN/$tok{ext(pid)}"\n'
        f'for i in $(seq 1 {1200 if is_algo(pid) else 600}); do\n'
        '  if [ -f "$OUT/$tok.score" ]; then cat "$OUT/$tok.score"; rm -f "$OUT/$tok.score"; exit 0; fi\n'
        '  sleep 1\n'
        'done\n'
        'echo "SCORE: 0.0"\n')
    fm.chmod(0o755)
    if is_algo(pid):
        desc = (f"You are solving Frontier-CS algorithmic problem #{pid}. Scoring is continuous partial credit "
                f"from 0 to 100 (higher is better); maximize it. Your working directory is a git worktree "
                f"containing solution.cpp (a C++17 stub). Edit solution.cpp with your algorithm.\n\n"
                f"{A.prompt_rules(pid)}\n\n"
                f"MEASURE only with this command: bash {fm} $PWD/solution.cpp  (prints 'SCORE: <n>'; one call "
                f"takes roughly 30-60s). Record it in finding metadata under key 'score'.\n\nPROBLEM STATEMENT:\n{stmt}")
    else:
      desc = (f"You are solving Frontier-CS research problem '{pid}'. Read the README below (objective, "
            f"scoring metric, and the required Solution API). Edit solution.py in your working directory to "
            f"implement `class Solution` EXACTLY per the README API.\n\n"
            f"{A.prompt_rules(pid)} Your solution must do the real work (generate SQL / choose a route).\n\n"
            f"MEASURE only with this command: bash {fm} $PWD/solution.py  (prints 'SCORE: <n>', higher is "
            f"better). Record it in finding metadata under key 'score'.\n\nPROBLEM README:\n{stmt}")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"research-{a.slug}").strip("-")
    track = "algorithmic" if is_algo(pid) else "research"
    spec = {"research_question": f"What legitimate solution maximizes the score for '{pid}'?",
            "run_id": slug, "max_iterations": a.niters, "sandbox": "bypass",
            "target_system": {"name": f"frontier-cs::{track}::{pid}", "description": desc,
                              "repo_path": str(ws), "observable_metrics": ["score"],
                              "controllable_knobs": ["solution_cpp" if is_algo(pid) else "solution_py"]},
            "objective": {"weights": {"score": 1.0}},
            "design_profile": a.design_profile,
            "models": {"design": a.model, "execute_analyze": a.model, "report": a.model},
            "prompts": {"methodology_layer": f"{NOUS_REPO}/prompts/methodology", "domain_adapter_layer": None}}
    camp = ws.parent/f"campaign_{a.slug}.yaml"; camp.write_text(yaml.safe_dump(spec, sort_keys=False))
    env = dict(os.environ); env["NOUS_CAMPAIGN_PARENT"] = str(ws.parent/"nous_runs")
    # agents call `nous validate`; make sure it is this Nous checkout, not another one on PATH
    env["PATH"] = f"{NOUS_REPO}/.venv/bin:" + env.get("PATH", "")
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
    extra = (sorted(glob.glob(str(camp_dir)+f"/runs/iter-*/inputs/*{ext(pid)}")) + _top_measured(measured, 10)
             + [str(ws/sol_name(pid))])
    cand_sources += [(p, Path(p).read_text(errors="ignore")) for p in extra if Path(p).exists()]
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
    pred = {"problem_id": pid, "track": track, "agent": "nous", "label": a.slug, "model": a.model,
            "final_score": (round(best, 2) if best >= 0 else None), "cost_usd": round(cost, 2),
            "n_clean_candidates": len(ev), "n_rejected_exploits": len(rejected),
            "best_source": bestsrc, "isolation": "sandbox-exec deny ~/frontier/{research,datasets} + out-of-sandbox judge daemon; measure only via fmeasure; post-harvest exploit audit",
            "rejected_exploit_candidates": rejected, "clean_evidence": ev,
            "elapsed_s": round(time.time()-t0, 1)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(pred, indent=2))
    print(f"NOUS-ISO DONE {pid}: best_clean={best} cost=${cost:.2f} clean={len(ev)} rejected={len(rejected)} -> {a.out}", flush=True)

if __name__ == "__main__":
    main()
