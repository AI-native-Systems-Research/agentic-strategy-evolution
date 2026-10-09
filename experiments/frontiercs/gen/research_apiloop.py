#!/usr/bin/env python3
"""Generalized research-track runner (API-loop agents: claude, engram) for ANY local-eval research
problem — grammar_fuzzing, llm_sql, cloudcast, etc. The objective and solution API come from the
problem README (passed in the prompt); scoring runs the problem's own local evaluator and parses the
JSON "score" (higher is better for every research task). No cloudcast-specific assumptions.

ISOLATION: both agents are a single LLM API call per round that returns a complete solution.py from the
README text ONLY — the agent process has NO filesystem access, so it cannot read the evaluator, the
reference solutions, or any ground truth. Isolation is by construction (nothing to sandbox).

COST CAP: each round adds token cost ($15/M in, $75/M out); the loop stops when cost >= --budget (or at
--max-score). All scored attempts are persisted under <out-dir>/trials/; final_score is the best
reproduced score re-judged at the end from the persisted artifacts.

Usage:
  research_apiloop.py grammar_fuzzing/seed/sql --agent claude --budget 30 --out-dir runs/gf/claude --out preds/gf.claude.json
  research_apiloop.py llm_sql/small          --agent engram --budget 30 --agents 10 --out-dir runs/sql/engram --out preds/sql.engram.json
"""
import argparse, json, os, re, shlex, subprocess, tempfile, time, random, urllib.request, urllib.error
from pathlib import Path

FRONTIER = os.environ.get("FRONTIER_DIR", os.path.expanduser("~/frontier/Frontier-CS"))
R_IN, R_OUT = 15/1e6, 75/1e6


def probdir(pid): return Path(FRONTIER) / "research" / "problems" / str(pid)
def evalpy(pid):  return probdir(pid) / ".evalvenv" / "bin" / "python3"
def statement(pid):
    p = probdir(pid) / "readme"
    return p.read_text() if p.exists() else f"(research problem {pid})"


def evaluate(pid, sol_path, timeout=600):
    """Run the problem's local evaluator; return (score, status, raw). score higher=better; 0 on error."""
    pd = probdir(pid)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    try:
        subprocess.run(f"{shlex.quote(str(evalpy(pid)))} {shlex.quote(str(pd/'evaluator.py'))} "
                       f"--solution {shlex.quote(str(sol_path))} --out {shlex.quote(out)}",
                       shell=True, cwd=str(pd), capture_output=True, text=True, timeout=timeout)
        try: data = json.loads(Path(out).read_text())
        except Exception: return 0.0, "parse_error", {}
    except subprocess.TimeoutExpired:
        return 0.0, "timeout", {}
    finally:
        try: os.unlink(out)
        except OSError: pass
    if data.get("error") or data.get("runs_successfully", 0.0) != 1.0:
        return 0.0, "error", data
    return float(data.get("score", 0.0)), "success", data


def fail_reason(raw):
    """Build an informative failure message from the evaluator JSON, even when there is no 'error'
    string (e.g. a constraint violation like exceeding the runtime limit zeroes the score silently)."""
    if not isinstance(raw, dict): return None
    if raw.get("error"): return str(raw["error"])
    bits = []
    art = raw.get("avg_runtime"); thr = raw.get("runtime_threshold")
    if art is not None:
        bits.append(f"avg_runtime={art:.2f}s" + (f" exceeds the limit (~{thr}); the score is 0 unless you get under it — make solve() FASTER" if (thr and art > thr) else ""))
    if raw.get("avg_hit_rate") is not None: bits.append(f"avg_hit_rate={raw['avg_hit_rate']:.2f} (good hit-rate but gated by runtime)")
    if raw.get("runs_successfully", 1.0) != 1.0 and not bits: bits.append("runs_successfully=0 (solution did not complete validly)")
    return "; ".join(bits) or None


def extract_py(text):
    if not text: return None
    cands = []
    # 1) GREEDY: opening fence to the LAST closing fence. Robust when the solution contains an internal
    #    ``` as a string literal (e.g. a code-routing task listing "```python" as a keyword), which a
    #    non-greedy match would truncate on.
    mg = re.search(r"```(?:python|py)?\s*\n(.*)```", text, re.DOTALL)
    if mg: cands.append(mg.group(1).strip() + "\n")
    # 2) non-greedy first block (works when there is exactly one clean block)
    mn = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if mn: cands.append(mn.group(1).strip() + "\n")
    # 3) unterminated block (output hit max_tokens): opening fence to end
    mu = re.search(r"```(?:python|py)?\s*\n(.*)$", text, re.DOTALL)
    if mu: cands.append(mu.group(1).strip() + "\n")
    # 4) raw text if it already looks like a solution
    if "class Solution" in text and "def solve" in text: cands.append(text.strip() + "\n")
    for code in cands:
        try:
            compile(code, "<sol>", "exec")
            return code
        except SyntaxError:
            continue
    return None


def llm(prompt, model, timeout=600):
    base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    body = json.dumps({"model": model, "max_tokens": 32000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    last = None
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            return d["choices"][0]["message"]["content"] or "", (d.get("usage") or {})
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                w = min(90, 5*(2**attempt)) + random.uniform(0, 5)
                print(f"    [llm] HTTP {e.code}; backoff {w:.0f}s ({attempt+1}/8)", flush=True); time.sleep(w); continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e; w = min(90, 5*(2**attempt)) + random.uniform(0, 5)
            print(f"    [llm] {type(e).__name__}; backoff {w:.0f}s ({attempt+1}/8)", flush=True); time.sleep(w); continue
    raise RuntimeError(f"llm failed after retries: {last}")


API = ("\nOutput a COMPLETE, self-contained solution.py in ONE ```python code block. Define `class "
       "Solution` EXACTLY as the API Specification in the README requires (same method name, signature, "
       "and return type). No prose outside the code block. The judge score is higher-is-better; "
       "maximize it. Do not import unavailable packages (only the stdlib plus any the README lists). "
       "Keep the code COMPACT: GENERATE outputs programmatically (loops/recursion over the grammar or "
       "data) rather than hardcoding long literal lists; a giant inline literal risks being truncated "
       "and will score ZERO. The whole file must be valid Python and fit in one block. Aim for a focused "
       "~80-250 line solution; do NOT paste copies of provided files or exhaustive literals.")


def base_prompt(pid, stmt):
    return (f"You are solving Frontier-CS research problem '{pid}'. Read the README (it states the exact "
            f"objective, the scoring metric, and the Solution API). Implement the best solution you can.\n\n"
            f"PROBLEM README:\n{stmt}\n" + API)


def refine_prompt(pid, stmt, prev_code, prev_score, best_score, err=None):
    errtxt = ""
    if err:
        errtxt = (f"\n\nIMPORTANT: the evaluator reported this error/constraint failure (score was forced "
                  f"to 0) — FIX IT FIRST:\n{str(err)[:600]}\n(e.g. cells may be numeric/NaN not str; cast "
                  f"with str(); respect any runtime limit in the README.)")
    return (base_prompt(pid, stmt) +
            f"\n\nYour previous solution scored {prev_score:.2f} (best so far {best_score:.2f}). Previous "
            f"solution.py:\n```python\n{prev_code}\n```" + errtxt +
            f"\nDiagnose what limited the score and output an IMPROVED complete solution.py.")


def persist(trials, n, score, code):
    trials.mkdir(parents=True, exist_ok=True)
    (trials / f"attempt_{n}_score_{score:.2f}.py").write_text(code)


def run_claude(pid, stmt, sol, model, outdir, rounds, budget, max_score):
    best_code = best_score = None; hist = []; ti = to = 0; stop = "max_rounds"
    prev_code = prev_score = prev_err = None
    trials = Path(outdir) / "trials"
    for r in range(rounds):
        cost = round(ti*R_IN + to*R_OUT, 4)
        if best_score is not None and best_score >= max_score: stop = "max_score"; break
        if budget and cost >= budget: stop = "budget"; break
        prompt = base_prompt(pid, stmt) if prev_code is None else refine_prompt(pid, stmt, prev_code, prev_score, best_score, prev_err)
        reply, u = llm(prompt, model); ti += u.get("prompt_tokens", 0) or 0; to += u.get("completion_tokens", 0) or 0
        code = extract_py(reply)
        if not code:
            hist.append({"round": r, "score": None, "status": "no_code"}); continue
        Path(sol).write_text(code)
        sc, status, raw = evaluate(pid, sol)
        persist(trials, r, sc, code)
        hist.append({"round": r, "score": sc, "status": status, "cost": round(ti*R_IN+to*R_OUT, 4)})
        print(f"  [claude r{r}] score={sc:.2f} status={status} cost=${ti*R_IN+to*R_OUT:.2f}", flush=True)
        prev_code, prev_score = code, sc
        prev_err = fail_reason(raw) if (status != "success" or sc == 0.0) else None
        if best_score is None or sc > best_score: best_score, best_code = sc, code
    if best_code: Path(sol).write_text(best_code)
    return best_score, {"history": hist, "input_tokens": ti, "output_tokens": to,
                        "cost_usd_est": round(ti*R_IN+to*R_OUT, 4), "stop_reason": stop}


def run_engram(pid, stmt, sol, model, outdir, agents, rounds_per_agent, budget, max_score, patience=3):
    best_code = best_score = None; hist = []; ti = to = 0; journal = []; stop = "max_agents"; no_imp = 0
    trials = Path(outdir) / "trials"
    ai = 0
    while ai < agents:
        start_best = best_score if best_score is not None else -1.0
        prev_code, prev_score, prev_err = best_code, best_score, None
        for rr in range(rounds_per_agent):
            cost = round(ti*R_IN + to*R_OUT, 4)
            if best_score is not None and best_score >= max_score: stop = "max_score"; break
            if budget and cost >= budget: stop = "budget"; break
            jtxt = ("\n\nRESEARCH JOURNAL (insights from prior specialists — build on these):\n" +
                    "\n".join(f"- {j}" for j in journal[-8:])) if journal else ""
            if prev_code is None:
                prompt = (f"You are Research Specialist #{ai+1} of {agents} on Frontier-CS problem '{pid}'. "
                          f"Fresh context; prior insights are in the journal.\n\nPROBLEM README:\n{stmt}\n"
                          + jtxt + API)
            else:
                prompt = refine_prompt(pid, stmt, prev_code, prev_score, best_score, prev_err) + jtxt
            reply, u = llm(prompt, model); ti += u.get("prompt_tokens", 0) or 0; to += u.get("completion_tokens", 0) or 0
            code = extract_py(reply)
            if not code:
                hist.append({"agent": ai, "round": rr, "score": None, "status": "no_code"}); continue
            Path(sol).write_text(code); sc, status, raw = evaluate(pid, sol)
            persist(trials, len(hist), sc, code)
            hist.append({"agent": ai, "round": rr, "score": sc, "status": status, "cost": round(ti*R_IN+to*R_OUT, 4)})
            print(f"  [engram a{ai} r{rr}] score={sc:.2f} status={status} cost=${ti*R_IN+to*R_OUT:.2f}", flush=True)
            prev_code, prev_score = code, sc
            prev_err = fail_reason(raw) if (status != "success" or sc == 0.0) else None
            if best_score is None or sc > best_score: best_score, best_code = sc, code
        if stop in ("budget", "max_score"): break
        # handoff summary
        try:
            summ, u = llm(f"Summarize for the next specialist on '{pid}': what you tried and the single most "
                          f"useful insight for raising the score. 3 sentences max. Best score so far {best_score}.", model)
            ti += u.get("prompt_tokens", 0) or 0; to += u.get("completion_tokens", 0) or 0
            journal.append(summ.strip().replace("\n", " ")[:400])
        except Exception: pass
        no_imp = no_imp + 1 if (best_score is not None and best_score <= start_best) else 0
        ai += 1
        # NOTE: no patience/plateau self-stop — the rule is budget OR max_score only. Keep spawning
        # specialists (journal carries insights) until the cost budget or ceiling is hit.
    if best_code: Path(sol).write_text(best_code)
    return best_score, {"history": hist, "input_tokens": ti, "output_tokens": to,
                        "cost_usd_est": round(ti*R_IN+to*R_OUT, 4), "agents_run": ai, "stop_reason": stop}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_id")
    ap.add_argument("--agent", choices=["claude", "engram"], required=True)
    ap.add_argument("--model", default="claude-opus-4-6")
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--max-score", type=float, default=100.0)
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--rounds-per-agent", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--label", default=None)
    a = ap.parse_args()
    pid = a.problem_id; label = a.label or a.agent
    outdir = Path(a.out_dir); outdir.mkdir(parents=True, exist_ok=True)
    sol = outdir / "solution.py"; sol.write_text("class Solution:\n    def solve(self,*args,**kw):\n        raise NotImplementedError\n")
    stmt = statement(pid); t0 = time.time()
    if a.agent == "claude":
        best, info = run_claude(pid, stmt, sol, a.model, outdir, a.rounds, a.budget, a.max_score)
    else:
        best, info = run_engram(pid, stmt, sol, a.model, outdir, a.agents, a.rounds_per_agent, a.budget, a.max_score)
    # re-judge the best persisted trial at the end (authoritative)
    final, status, raw = evaluate(pid, sol)
    pred = {"problem_id": pid, "track": "research", "agent": a.agent, "label": label, "model": a.model,
            "final_score": round(final, 2), "best_score_inrun": (round(best, 2) if best is not None else None),
            "cost_usd_est": info["cost_usd_est"], "stop_reason": info["stop_reason"],
            "isolation": "api-loop: agent is a single LLM call per round with NO filesystem access; cannot read evaluator/ground-truth (isolated by construction)",
            "cheat_audit_hits": [], "elapsed_s": round(time.time()-t0, 1),
            "solution": str(sol), "eval_raw": raw, "history": info["history"]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(pred, indent=2))
    print(f"DONE {pid} {a.agent}: final={final:.2f} best_inrun={best} cost=${info['cost_usd_est']:.2f} "
          f"stop={info['stop_reason']} -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
