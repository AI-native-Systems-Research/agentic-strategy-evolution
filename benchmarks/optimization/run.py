"""Matched-budget benchmark of Nous ``kind: optimization`` against random
search, Latin hypercube and GP-BO. Zero LLM tokens: every campaign is the
in-process synthetic harness.

    .venv/bin/python -m benchmarks.optimization.run                 # full suite
    .venv/bin/python -m benchmarks.optimization.run --audit-repro   # audit Q6 setup
    .venv/bin/python -m benchmarks.optimization.run --surfaces bowl --seeds 1 --mults 1

Protocol, per (surface, noise multiplier, seed):

1. Run the Nous campaign through ``harness.run_synthetic_campaign`` and count
   every row it measured (all ``runs/iter-*/runs.jsonl``). That count is the
   BUDGET.
2. Give every baseline exactly that budget on the same surface, noise model
   and candidate axes.
3. Judge every recommendation on the NOISELESS surface: true regret =
   f(true optimum) - f(recommendation); an infeasible or missing
   recommendation is charged the regret of the worst admissible point.

Outputs ``docs/benchmarks/optimization-benchmark.json`` (every row) and the
generated tables inside ``docs/benchmarks/optimization-benchmark.md``
(between the GENERATED markers; the hand-written interpretation outside them
is preserved).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.optimization import surfaces as S  # noqa: E402
from benchmarks.optimization.baselines import METHODS, run_method  # noqa: E402

DEFAULT_OUT = REPO / "docs" / "benchmarks"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"

#: Surfaces excluded from the default suite, with the reason.
EXCLUDED = {
    "bowl_out_of_hull": "its optimum is outside the declared hull by construction; "
                        "every method's regret is the hull-edge regret",
}

DEFAULT_SURFACES = [n for n in S.ALL if n not in EXCLUDED]

AUDIT_SURFACES = ["additive", "bowl", "bowl_centred", "saddle", "choice_x_numeric",
                  "geometric_knob", "two_peaks", "step_cliff", "ridge_cubic"]


def run_nous(name: str, mult: float, seed: int, scratch: str) -> dict:
    logging.disable(logging.CRITICAL)
    from orchestrator.optimize.harness import run_synthetic_campaign

    s = S.get(name, mult)
    tr = S.truth(s)
    t0, c0 = time.perf_counter(), time.process_time()
    with tempfile.TemporaryDirectory(dir=scratch) as d:
        try:
            r = run_synthetic_campaign(s, seed=seed, parent_dir=Path(d),
                                       campaign_overrides=S.campaign_overrides(name))
        except Exception as exc:  # noqa: BLE001 -- a crash is a data point
            return {"surface": name, "mult": mult, "seed": seed,
                    "error": f"{type(exc).__name__}: {exc}"[:300]}
        runs = sum(sum(1 for ln in p.read_text().splitlines() if ln.strip())
                   for p in Path(r.work_dir).glob("runs/iter-*/runs.jsonl"))
        rep = r.report
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    regret, status = S.true_regret(s, r.recommendation, tr)
    eps = rep.get("epsilon")
    cert = bool(rep.get("certified"))
    return {"surface": name, "mult": mult, "seed": seed, "budget": runs,
            "regret": regret, "status": status, "certified": cert,
            "epsilon": eps, "basis": r.basis, "path_tail": (r.path or [""])[-1],
            "false_cert": cert and (status != "ok" or (eps is not None and regret > eps + 1e-9)),
            "wall_s": wall, "cpu_s": cpu, "rec": r.recommendation}


def run_baseline(method: str, name: str, mult: float, seed: int, budget: int) -> dict:
    s = S.get(name, mult)
    tr = S.truth(s)
    t0, c0 = time.perf_counter(), time.process_time()
    recs, used = run_method(method, s, name, budget, seed)
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    out = {"surface": name, "mult": mult, "seed": seed, "method": method,
           "budget": budget, "used": used, "wall_s": wall, "cpu_s": cpu}
    for rule, rec in recs.items():
        reg, st = S.true_regret(s, rec, tr)
        out[f"regret_{rule}"], out[f"status_{rule}"] = reg, st
    return out


def _nous_job(a):
    return run_nous(*a)


def _base_job(a):
    return run_baseline(*a)


def _cached_map(fn, jobs, workers, cache: Path | None, key):
    """``[fn(j) for j in jobs]`` in a process pool, with every finished result
    appended to ``cache`` (JSONL) as it lands, and results already in the
    cache reused: a killed run resumes where it stopped."""
    from concurrent.futures import as_completed

    done: dict[str, dict] = {}
    if cache is not None and cache.exists():
        for ln in cache.read_text().splitlines():
            if ln.strip():
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    continue  # a torn last line from a kill
                done[r["_key"]] = r
    todo = [j for j in jobs if key(j) not in done]
    if todo:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fn, j): j for j in todo}
            for f in as_completed(futs):
                r = {**f.result(), "_key": key(futs[f])}
                done[r["_key"]] = r
                if cache is not None:
                    with open(cache, "a") as fh:
                        fh.write(json.dumps(r, default=str) + "\n")
    out = []
    for j in jobs:
        r = dict(done[key(j)])
        r.pop("_key", None)
        out.append(r)
    return out


def run_suite(names, mults, seeds, methods, workers, scratch, cache_dir: Path | None = None):
    jobs = [(n, m, s, scratch) for n in names for m in mults for s in seeds]
    nous = _cached_map(_nous_job, jobs, workers,
                       cache_dir / "nous.jsonl" if cache_dir else None,
                       key=lambda j: f"{j[0]}|{j[1]}|{j[2]}")
    bjobs = [(meth, r["surface"], r["mult"], r["seed"], r["budget"])
             for r in nous if "error" not in r for meth in methods]
    # Longest (GP-BO on the biggest budgets) first, for load balance.
    bjobs.sort(key=lambda j: -(j[4] * (10 if j[0] == "GP-BO" else 1)))
    base = _cached_map(_base_job, bjobs, workers,
                       cache_dir / "baselines.jsonl" if cache_dir else None,
                       key=lambda j: f"{j[0]}|{j[1]}|{j[2]}|{j[3]}|{j[4]}")
    return nous, base


# ── aggregation ─────────────────────────────────────────────────────────────
PRIMARY_RULE = {"RS": "best_observed", "LHS": "best_observed",
                "GP-BO": "gp_mean", "GP-BO-crude": "gp_mean"}


def head_to_head(nous, base, method, rule, tol_eps=False):
    nm = {(r["surface"], r["mult"], r["seed"]): r for r in nous if "error" not in r}
    w = t = l = 0
    for b in base:
        if b["method"] != method:
            continue
        n = nm[(b["surface"], b["mult"], b["seed"])]
        tol = 1e-9
        if tol_eps and n.get("epsilon") is not None:
            tol = float(n["epsilon"])
        g, h = n["regret"], b[f"regret_{rule}"]
        if abs(g - h) <= tol:
            t += 1
        elif g < h:
            w += 1
        else:
            l += 1
    return w, t, l


def _mean(v):
    return statistics.fmean(v) if v else float("nan")


def summarize(nous, base, methods):
    nm = {(r["surface"], r["mult"], r["seed"]): r for r in nous if "error" not in r}
    cells = {}
    for r in nous:
        if "error" in r:
            continue
        c = cells.setdefault((r["surface"], r["mult"]), {"nous": [], "base": {}})
        c["nous"].append(r)
    for b in base:
        cells[(b["surface"], b["mult"])]["base"].setdefault(b["method"], []).append(b)
    rows = []
    for (name, mult), c in sorted(cells.items(), key=lambda kv: (list(S.ALL).index(kv[0][0]), kv[0][1])):
        ns = c["nous"]
        row = {"surface": name, "family": S.FAMILY[name], "mult": mult,
               "seeds": len(ns), "budget": sorted({r["budget"] for r in ns}),
               "nous_regret": _mean([r["regret"] for r in ns]),
               "nous_certified": sum(r["certified"] for r in ns),
               "nous_false_cert": sum(r["false_cert"] for r in ns),
               "nous_wall_s": statistics.median([r["wall_s"] for r in ns]),
               "nous_cpu_s": statistics.median([r["cpu_s"] for r in ns])}
        for m in methods:
            bs = c["base"].get(m, [])
            for rule in ("best_observed", "gp_mean"):
                row[f"{m}:{rule}"] = _mean([b[f"regret_{rule}"] for b in bs])
            row[f"{m}:cpu_s"] = statistics.median([b["cpu_s"] for b in bs]) if bs else None
        rows.append(row)
    h2h = {m: {rule: {"exact": head_to_head(nous, base, m, rule),
                      "within_epsilon": head_to_head(nous, base, m, rule, tol_eps=True)}
               for rule in ("best_observed", "gp_mean")} for m in methods}
    fam = {}
    for fname in ("shipped", "non-quadratic", "many-knob sparse"):
        keys = {k for k, r in nm.items() if S.FAMILY[k[0]] == fname}
        fb = [b for b in base if (b["surface"], b["mult"], b["seed"]) in keys]
        fn = [nm[k] for k in keys]
        fam[fname] = {m: {"exact": head_to_head(fn, fb, m, PRIMARY_RULE[m]),
                          "within_epsilon": head_to_head(fn, fb, m, PRIMARY_RULE[m], True)}
                      for m in methods}
    errors = [r for r in nous if "error" in r]
    return {"rows": rows, "head_to_head": h2h, "by_family": fam, "errors": errors}


def _f(v, nd=3):
    if v is None or v != v:
        return "–"
    return f"{v:.{nd}f}"


def render_markdown(summary, meta, methods) -> str:
    out = [f"_Generated by `python -m benchmarks.optimization.run {meta['argv']}` "
           f"on Nous {meta['nous_version']} ({meta['git_commit'] or 'no git'}); "
           f"seeds {meta['seeds']}, noise multipliers {meta['mults']}._", ""]
    hdr = ["surface", "noise", "N", "Nous", "cert/false", *[
        f"{m} ({'obs' if PRIMARY_RULE[m] == 'best_observed' else 'GP mean'})" for m in methods],
        *[f"{m} ({'GP mean' if PRIMARY_RULE[m] == 'best_observed' else 'obs'})" for m in methods]]
    out.append("### Mean true regret per cell (lower is better)")
    out.append("")
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "---|" * len(hdr))
    for r in summary["rows"]:
        prim, sec = [], []
        for m in methods:
            p = PRIMARY_RULE[m]
            o = "gp_mean" if p == "best_observed" else "best_observed"
            prim.append(_f(r[f"{m}:{p}"]))
            sec.append(_f(r[f"{m}:{o}"]))
        n = r["budget"]
        nstr = f"{n[0]}" if len(n) == 1 else f"{n[0]}-{n[-1]}"
        out.append(f"| {r['surface']} | ×{r['mult']:g} | {nstr} | {_f(r['nous_regret'])} | "
                   f"{r['nous_certified']}/{r['nous_false_cert']} of {r['seeds']} | "
                   + " | ".join(prim + sec) + " |")
    out += ["", "### Head-to-head (Nous better / tie / worse), every cell pooled", "",
            "| baseline | rule | exact tie | tie = within Nous's ε |", "|---|---|---|---|"]
    for m in methods:
        for rule in ("best_observed", "gp_mean"):
            e, w = (summary["head_to_head"][m][rule][k] for k in ("exact", "within_epsilon"))
            out.append(f"| {m} | {rule} | {e[0]} / {e[1]} / {e[2]} | {w[0]} / {w[1]} / {w[2]} |")
    out += ["", "### Head-to-head by surface family (primary rule)", "",
            "| family | " + " | ".join(methods) + " |", "|---|" + "---|" * len(methods)]
    for fam, d in summary["by_family"].items():
        out.append(f"| {fam} (exact) | " + " | ".join(
            "{} / {} / {}".format(*d[m]["exact"]) for m in methods) + " |")
        out.append(f"| {fam} (within ε) | " + " | ".join(
            "{} / {} / {}".format(*d[m]["within_epsilon"]) for m in methods) + " |")
    out += ["", "### Median CPU seconds per campaign", "",
            "| surface | noise | Nous | " + " | ".join(methods) + " |",
            "|---|---|---|" + "---|" * len(methods)]
    for r in summary["rows"]:
        out.append(f"| {r['surface']} | ×{r['mult']:g} | {_f(r['nous_cpu_s'], 2)} | "
                   + " | ".join(_f(r[f'{m}:cpu_s'], 2) for m in methods) + " |")
    if summary["errors"]:
        out += ["", "### Nous campaigns that raised", ""]
        for e in summary["errors"]:
            out.append(f"- {e['surface']} ×{e['mult']:g} seed {e['seed']}: `{e['error']}`")
    return "\n".join(out) + "\n"


def write_markdown(path: Path, generated: str, section: str):
    begin, end = f"{BEGIN[:-4]} {section} -->", f"{END[:-4]} {section} -->"
    text = path.read_text() if path.exists() else ""
    block = f"{begin}\n{generated}{end}"
    if begin in text and end in text:
        pre, rest = text.split(begin, 1)
        _, post = rest.split(end, 1)
        text = pre + block + post
    else:
        text = text + ("\n" if text else "") + block + "\n"
    path.write_text(text)


def _meta(argv, seeds, mults):
    from orchestrator.optimize.provenance import nous_version_info
    v = nous_version_info()
    return {"argv": " ".join(argv), "nous_version": v["package_version"],
            "git_commit": v.get("git_commit"), "seeds": list(seeds), "mults": list(mults)}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--surfaces", nargs="*", default=None)
    ap.add_argument("--seeds", type=int, nargs="*", default=list(range(1, 9)))
    ap.add_argument("--mults", type=float, nargs="*", default=[1.0, 4.0])
    ap.add_argument("--methods", nargs="*", default=list(METHODS))
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--audit-repro", action="store_true",
                    help="the stage-0 audit's Q6 setup: its 9 surfaces, seeds 1-20, noise x1/x8")
    ap.add_argument("--no-markdown", action="store_true")
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="resume directory: finished campaigns are appended "
                         "here and reused by a re-run with the same arguments")
    a = ap.parse_args(argv)
    if a.audit_repro:
        names, seeds, mults, section = AUDIT_SURFACES, list(range(1, 21)), [1.0, 8.0], "audit-repro"
    else:
        names, seeds, mults, section = a.surfaces or DEFAULT_SURFACES, a.seeds, a.mults, "suite"
    a.out.mkdir(parents=True, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="nous-bench-")
    t0 = time.time()
    cache_dir = None
    if a.cache_dir is not None:
        cache_dir = a.cache_dir / section
        cache_dir.mkdir(parents=True, exist_ok=True)
    nous, base = run_suite(names, mults, seeds, a.methods, a.workers, scratch, cache_dir)
    summary = summarize(nous, base, a.methods)
    meta = {**_meta(argv, seeds, mults), "elapsed_s": time.time() - t0,
            "excluded": EXCLUDED, "primary_rule": PRIMARY_RULE}
    stem = "optimization-benchmark" + ("-audit-repro" if a.audit_repro else "")
    (a.out / f"{stem}.json").write_text(json.dumps(
        {"meta": meta, "summary": summary, "nous": nous, "baselines": base},
        indent=1, default=str))
    md = render_markdown(summary, meta, a.methods)
    if not a.no_markdown:
        write_markdown(a.out / "optimization-benchmark.md", md, section)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
