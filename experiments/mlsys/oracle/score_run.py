"""Score one finished run: python3 score_run.py <run_dir>

<run_dir>/meta.json: {"task": "pd|dbg|search", "arm": ..., "rep": ..., "status": ..., "cost_usd": ...,
                      "iterations_used": ..., "max_iterations": ..., "hit_ceiling": ..., "transcripts": [...]}
<run_dir>/ws: the arm's final repository (the oracle copies it; never modifies it).
<run_dir>/snapshots/iter-N/final/answer.json (optional): answer after each iteration, for S1/S2.
Writes <run_dir>/oracle.json.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

TASKS = {}


def task_mod(task):
    if task not in TASKS:
        TASKS[task] = __import__({"pd": "pd", "dbg": "dbg", "search": "search"}[task])
    return TASKS[task]


def answer_text(a):
    if not a:
        return ""
    parts = [str(a.get("answer", ""))]
    for c in a.get("claims", []):
        if isinstance(c, dict):
            parts.append(" ".join(str(c.get(k, "")) for k in ("metric", "condition", "value")))
    return re.sub(r"\s+", " ", "\n".join(parts)).lower()


def task_score(task, ws, a):
    m = task_mod(task)
    t = answer_text(a)
    if task == "pd":
        return m.score(a, t)
    return m.score(ws, a, t)


def score(run_dir):
    meta = json.load(open(os.path.join(run_dir, "meta.json")))
    ws = os.path.join(run_dir, "ws")
    task = meta["task"]
    a, status = common.load_answer(ws)
    out = {"task": task, "arm": meta["arm"], "rep": meta["rep"], "contract": status}
    res = task_score(task, ws, a)
    out.update(res)
    claims = [c for c in (a or {}).get("claims", []) if isinstance(c, dict)]
    out["n_claims"] = len(claims)
    out["C1_evidence_frac"] = common.fraction([common.claim_evidence_ok(ws, c) for c in claims]) if claims else None
    # R1/R2 reproducibility in a fresh copy
    if a and a.get("repro"):
        cp = common.fresh_copy(ws)
        ok, log = common.run_repro(cp, a["repro"])
        out["R1_repro_runs"] = ok
        if ok and claims:
            out["R2_repro_matches"] = common.fraction([common.claim_evidence_ok(cp, c) for c in claims])
        else:
            out["R2_repro_matches"] = 0.0 if claims else None
    else:
        out["R1_repro_runs"], out["R2_repro_matches"] = False, None
    # V4 forbidden access
    hits = common.forbidden_access(meta.get("transcripts", []))
    out["V4_no_forbidden_access"] = not hits
    out["V4_hits"] = hits
    # stopping: O1 per iteration snapshot (S1 too early, S2 waste after first solved)
    snaps = sorted([d for d in os.listdir(os.path.join(run_dir, "snapshots"))] if os.path.isdir(os.path.join(run_dir, "snapshots")) else [],
                   key=lambda s: int(re.sub(r"\D", "", s) or 0))
    first_solved = None
    if task != "search":  # search re-runs the delivered script; per-iteration snapshots scored only for pd/dbg
        for i, s in enumerate(snaps, 1):
            sw = os.path.join(run_dir, "snapshots", s)
            sa, _ = common.load_answer(sw)
            if task == "pd" and sa and task_mod("pd").score(sa, answer_text(sa)).get("O1"):
                first_solved = i
                break
    out["first_solved_iter"] = first_solved
    used = meta.get("iterations_used")
    out["S1_stopped_early"] = bool(meta.get("declared_done") and not out.get("O1"))
    out["S2_iters_after_solved"] = (used - first_solved) if (first_solved and used) else None
    out["S3_crashed_or_ceiling"] = bool(meta.get("status") not in ("done", "max_iterations") or meta.get("hit_ceiling"))
    out["E1_cost_usd"] = meta.get("cost_usd")
    out["E1_wall_min"] = meta.get("wall_min")
    out["E1_iterations"] = used
    out["status"] = meta.get("status")
    json.dump(out, open(os.path.join(run_dir, "oracle.json"), "w"), indent=1, default=str)
    return out


if __name__ == "__main__":
    print(json.dumps(score(sys.argv[1]), indent=1, default=str))
