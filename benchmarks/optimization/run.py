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
from benchmarks.optimization import stats as ST  # noqa: E402
from benchmarks.optimization.measured import measured_rows, spent_under  # noqa: E402
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


#: Budget fractions of N at which every method's anytime regret is recorded.
FRACTIONS = (0.1, 0.2, 0.4, 0.6, 0.8, 1.0)


def anytime_counts(budget: int) -> list[int]:
    """The run counts ``FRACTIONS`` of ``budget`` map to (each at least 1)."""
    return [max(1, int(round(f * budget))) for f in FRACTIONS] if budget else []


# ── Nous arms (single-objective and multi-objective) ────────────────────────
#: The guide's documented example (docs/optimization-campaign-guide.md), fixed
#: before any run: nothing here is tuned on the benchmark surfaces.
ALLOCATE_SEATS = 2

ARMS = ("nous", "nous+alloc", "nous+alloc+bo", "nous-order")

ARM_DOC = {
    "nous": "the default campaign",
    "nous+alloc": f"design.confirm.allocate: {{seats: {ALLOCATE_SEATS}}} (WP-D D1), "
                  "confirm replicates at the raised floor",
    "nous+alloc+bo": "as nous+alloc, plus planner.bo (the optional TPE proposer, "
                     "module defaults); BO proposals reach only the allocate pool",
    "nous-order": "run-order randomization OFF: every design and confirm block "
                  "executes in design order (the drift ablation)",
}


def arm_unavailable(arm: str) -> str | None:
    """Why ``arm`` cannot run on this checkout, or ``None``."""
    if arm in ("nous+alloc", "nous+alloc+bo"):
        from orchestrator.optimize import policy as _p

        if not hasattr(_p, "ALLOCATE_ACCOUNTING"):
            return "design.confirm.allocate is not in this checkout (WP-D P6b)"
    if arm == "nous+alloc+bo":
        try:
            import optuna  # noqa: F401
        except ImportError:
            return "the nous[bo] extra (Optuna) is not installed"
    return None


def arm_overrides(arm: str, surface, base: dict | None) -> dict | None:
    """The ``optimization`` overrides of ``arm`` on top of the surface's own."""
    import copy

    from orchestrator.optimize.harness import synthetic_campaign

    o = dict(base or {})
    if arm in ("nous+alloc", "nous+alloc+bo"):
        d = copy.deepcopy(synthetic_campaign(surface, **o)["optimization"]["design"])
        d["confirm"]["allocate"] = {"seats": ALLOCATE_SEATS}
        if not surface.objectives:
            # What an author following the guide writes: the raised floor.
            d["confirm"].pop("replicates", None)
        o["design"] = d
    if arm == "nous+alloc+bo":
        o["planner"] = {"bo": {}}
    return o or None


class _InDesignOrder:
    """Context manager: ``matrix.randomized_run_order`` returns the identity
    (the drift ablation). Every caller looks it up on the module at call time."""

    def __enter__(self):
        from orchestrator.optimize import matrix

        self._m, self._f = matrix, matrix.randomized_run_order
        matrix.randomized_run_order = lambda n, seed: list(range(n))
        return self

    def __exit__(self, *exc):
        self._m.randomized_run_order = self._f
        return False


def _arm_context(arm: str):
    import contextlib

    return _InDesignOrder() if arm == "nous-order" else contextlib.nullcontext()


def _measured_rows(work_dir) -> list[dict]:
    return measured_rows(work_dir)


def best_so_far(rows: list[dict], metric: str = "m", direction: str = "maximize") -> dict | None:
    """The always-admissible measured configuration with the best mean
    ``metric`` over ``rows``: Nous's anytime answer after those rows. A row
    is admissible when it completed with a finite metric. A row the runner
    marked ``infeasible`` (a constraint failed) or ``rejected`` (a manipulation
    or invariant check failed) strikes its configuration for good, the same
    sticky rule the baselines apply; a ``failed`` row (no measurement) only
    contributes nothing."""
    import math as _m

    g: dict = {}
    for r in rows:
        k = tuple(sorted(r["levels"].items()))
        e = g.setdefault(k, {"lv": r["levels"], "ys": [], "ok": True})
        y = (r.get("response") or {}).get(metric)
        if r.get("status") != "complete" or not isinstance(y, (int, float)) or not _m.isfinite(y):
            if r.get("status") in ("infeasible", "rejected"):
                e["ok"] = False
            continue
        e["ys"].append(float(y))
    c = [e for e in g.values() if e["ok"] and e["ys"]]
    if not c:
        return None
    s = -1.0 if direction == "minimize" else 1.0
    return max(c, key=lambda e: s * sum(e["ys"]) / len(e["ys"]))["lv"]


def nous_anytime(rows: list[dict], surface, tr: dict, budget: int) -> list[float]:
    return [S.true_regret(surface, best_so_far(rows[:n], direction=surface.direction), tr)[0]
            for n in anytime_counts(budget)]


def run_nous(name: str, mult: float, seed: int, scratch: str, arm: str = "nous") -> dict:
    logging.disable(logging.CRITICAL)
    from orchestrator.optimize.harness import run_synthetic_campaign

    s = S.get(name, mult)
    tr = S.truth(s)
    t0, c0 = time.perf_counter(), time.process_time()
    head = {"surface": name, "mult": mult, "seed": seed, "arm": arm,
            "norm": tr["best"] - tr["worst"], "code": _nous_digest()}
    why = arm_unavailable(arm)
    if why:
        return {**head, "status": "unavailable", "unavailable": why}
    with tempfile.TemporaryDirectory(dir=scratch) as d:
        try:
            with _arm_context(arm):
                r = run_synthetic_campaign(
                    s, seed=seed, parent_dir=Path(d),
                    campaign_overrides=arm_overrides(arm, s, S.campaign_overrides(name)))
        except Exception as exc:  # noqa: BLE001 -- a crash is a data point
            # CHARGED, not dropped (review B2): a campaign that crashed returned
            # no answer, so it scores the worst admissible regret, and the runs
            # it spent before crashing are the budget its baselines get.
            spent = spent_under(d)
            regret, status = S.true_regret(s, None, tr)
            return {**head, "budget": spent,
                    "regret": regret, "status": "error", "certified": False,
                    "false_cert": False, "epsilon": None,
                    "anytime": [regret] * len(anytime_counts(spent)),
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                    "wall_s": time.perf_counter() - t0, "cpu_s": time.process_time() - c0}
        rows = _measured_rows(r.work_dir)
        runs = len(rows)
        rep = r.report
        anytime = nous_anytime(rows, s, tr, runs)
        transitions = []
        tp = Path(r.work_dir) / "transitions.jsonl"
        if tp.exists():
            transitions = [json.loads(ln)["rule"].get("accounting", "")
                           for ln in tp.read_text().splitlines() if ln.strip()]
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    regret, status = S.true_regret(s, r.recommendation, tr)
    eps = rep.get("epsilon")
    cert = bool(rep.get("certified"))
    return {**head, "budget": runs,
            "regret": regret, "status": status, "certified": cert,
            "epsilon": eps, "basis": r.basis, "path_tail": (r.path or [""])[-1],
            "false_cert": cert and (status != "ok" or (eps is not None and regret > eps + 1e-9)),
            "allocate_fired": any(a.startswith("allocate round") for a in transitions),
            "withheld": list(rep.get("certification_withheld") or []),
            "anytime": anytime,
            "wall_s": wall, "cpu_s": cpu, "rec": r.recommendation}


def _nous_digest() -> str:
    """The Nous source digest the row was produced under (review B3)."""
    from orchestrator.optimize.provenance import nous_version_info

    return nous_version_info()["source_sha256"][:16]


def _bench_digest() -> str:
    """Digest of the benchmark's own code (surfaces, GP, baselines)."""
    import hashlib

    h = hashlib.sha256()
    for f in sorted(Path(__file__).parent.glob("*.py")):
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:16]


def run_baseline(method: str, name: str, mult: float, seed: int, budget: int) -> dict:
    s = S.get(name, mult)
    tr = S.truth(s)
    t0, c0 = time.perf_counter(), time.process_time()
    recs, used = run_method(method, s, name, budget, seed)
    log = recs.pop("log", None)
    gp_seed = recs.pop("gp_seed", 0)
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    out = {"surface": name, "mult": mult, "seed": seed, "method": method,
           "budget": budget, "used": used, "wall_s": wall, "cpu_s": cpu,
           "norm": tr["best"] - tr["worst"], "code": _bench_digest()}
    out["dead_fallbacks"] = recs.pop("dead_fallbacks", 0)
    for rule, rec in recs.items():
        reg, st = S.true_regret(s, rec, tr)
        out[f"regret_{rule}"], out[f"status_{rule}"] = reg, st
    out["anytime"] = baseline_anytime(method, s, log, tr, budget,
                                      out[f"regret_{PRIMARY_RULE[method]}"], gp_seed)
    return out


def baseline_anytime(method, surface, log, tr, budget, final, gp_seed: int = 0) -> list[float]:
    """The method's PRIMARY-rule regret on each prefix of its own
    measurements (``anytime_counts(budget)``). A prefix of a run planned for N
    is what the method would hold had it been stopped there (GP-BO's initial
    design is sized for N; a Latin hypercube prefix is a subset of N strata).
    The last point is the method's recorded answer at N. The prefix GP is
    fitted with the SAME seed as the run's own final GP-mean pick
    (``gp_seed``), so the curve's last point and the recorded answer come
    from one fitting procedure."""
    from benchmarks.optimization import baselines as B

    if log is None:
        return []
    coder = B.Coder(surface)
    rule = PRIMARY_RULE[method]
    out = []
    counts = anytime_counts(budget)
    for i, n in enumerate(counts):
        if i == len(counts) - 1 and n == budget:
            out.append(final)
            continue
        pre = B.prefix(log, n)
        if rule == "best_observed":
            rec = B.best_observed(pre)
        elif method == "GP-BO-crude":
            rec = B.crude_mean_recommendation(pre, coder)
        else:
            rec = B.gp_mean_recommendation(pre, coder, gp_seed)
        out.append(S.true_regret(surface, rec, tr)[0])
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
    if todo and workers == 1:
        # In-process: no pool, so one worker costs one process, not two.
        for j in todo:
            r = {**fn(j), "_key": key(j)}
            done[r["_key"]] = r
            if cache is not None:
                with open(cache, "a") as fh:
                    fh.write(json.dumps(r, default=str) + "\n")
    elif todo:
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


def planned_budget(name: str, mult: float) -> int:
    """The run count the campaign's registered design PLANS (design preview),
    used when every seed of a cell crashed before measuring (round 3, E2)."""
    try:
        from orchestrator.optimize.harness import synthetic_campaign
        from orchestrator.optimize.preview import build_preview

        c = synthetic_campaign(S.get(name, mult), **(S.campaign_overrides(name) or {}))
        pv = build_preview(c, noise_sd=None, mean=None, run_secs=None)
        return int(pv.guaranteed_runs)
    except Exception:  # noqa: BLE001 -- no plan: the cell is listed instead
        return 0


def _budget_for(r: dict, nous: list[dict]) -> int:
    """The budget a Nous row's baselines get. A campaign that crashed before
    measuring anything (budget 0) still counts in the head-to-heads (review C6):
    its baselines get the median budget of the cell's other seeds, or the
    design's planned run count when every seed of the cell crashed (E2)."""
    if r.get("budget"):
        return int(r["budget"])
    cell = [x["budget"] for x in nous if x["surface"] == r["surface"]
            and x["mult"] == r["mult"] and x.get("budget")]
    if cell:
        return int(statistics.median(cell))
    return planned_budget(r["surface"], r["mult"])


def _nous_key(nd, bd, arm):
    # The default arm keeps the pre-P7 key shape (the code digests are what
    # invalidate it); every other arm is named in its key.
    if arm == "nous":
        return lambda j: f"{nd}|{bd}|{j[0]}|{j[1]}|{j[2]}"
    return lambda j: f"{nd}|{bd}|{arm}|{j[0]}|{j[1]}|{j[2]}"


def run_suite(names, mults, seeds, methods, workers, scratch, cache_dir: Path | None = None):
    # The CODE DIGEST is part of every cache key (review C6): a row produced by
    # different Nous or benchmark code is never silently reused.
    nd, bd = _nous_digest(), _bench_digest()
    jobs = [(n, m, s, scratch) for n in names for m in mults for s in seeds]
    nous = _cached_map(_nous_job, jobs, workers,
                       cache_dir / "nous.jsonl" if cache_dir else None,
                       key=_nous_key(nd, bd, "nous"))
    bjobs = [(meth, r["surface"], r["mult"], r["seed"], _budget_for(r, nous))
             for r in nous if _budget_for(r, nous) for meth in methods]
    # Longest (GP-BO on the biggest budgets) first, for load balance.
    bjobs.sort(key=lambda j: -(j[4] * (10 if j[0] == "GP-BO" else 1)))
    base = _cached_map(_base_job, bjobs, workers,
                       cache_dir / "baselines.jsonl" if cache_dir else None,
                       key=lambda j: f"{bd}|{j[0]}|{j[1]}|{j[2]}|{j[3]}|{j[4]}")
    return nous, base


# ── ablations (D4) ──────────────────────────────────────────────────────────
#: Fixed before any run. Smooth: the low-order surfaces Nous was built for;
#: non-quadratic: the audit's three; drift: the one surface the previous doc
#: credited to blocked, randomized run order (plus two smooth controls, so a
#: cost of switching randomization off elsewhere is visible too).
ABLATION_SO = {
    "nous+alloc": ["additive", "bowl", "saddle", "geometric_knob_log",
                   "step_cliff", "ridge_cubic", "two_peaks"],
    "nous+alloc+bo": ["additive", "bowl", "saddle", "geometric_knob_log",
                      "step_cliff", "ridge_cubic", "two_peaks"],
    "nous-order": ["drift", "bowl", "additive"],
}


def _arm_job(a):
    return run_nous(*a)


def run_ablations(mults, seeds, workers, scratch, cache_dir: Path | None = None,
                  plan: dict | None = None):
    """Every non-default single-objective arm in ``plan`` (default
    ``ABLATION_SO``). Rows of an unavailable arm are kept, marked."""
    nd, bd = _nous_digest(), _bench_digest()
    out = []
    for arm, names in (plan or ABLATION_SO).items():
        jobs = [(n, m, s, scratch, arm) for n in names for m in mults for s in seeds]
        out += _cached_map(_arm_job, jobs, workers,
                           cache_dir / "ablations.jsonl" if cache_dir else None,
                           key=_nous_key(nd, bd, arm))
    return out


# ── multi-objective arm ─────────────────────────────────────────────────────
MO_ARMS = ("nous", "nous+alloc", "nous+alloc+bo")
MO_METHOD_NAMES = ("RS", "LHS", "ParEGO")


def run_nous_mo(name: str, seed: int, scratch: str, arm: str = "nous") -> dict:
    logging.disable(logging.CRITICAL)
    from benchmarks.optimization import mo as MO
    from orchestrator.optimize.harness import evaluate_pareto_campaign

    head = {"surface": name, "seed": seed, "arm": arm, "code": _nous_digest()}
    why = arm_unavailable(arm)
    if why is None and name not in S.mo_surfaces():
        why = f"surface {name} is not in this checkout"
    if why:
        return {**head, "status": "unavailable", "unavailable": why}
    s = S.get_mo(name)
    truth = MO.HVTruth(s)
    t0, c0 = time.perf_counter(), time.process_time()
    with tempfile.TemporaryDirectory(dir=scratch) as d:
        try:
            with _arm_context(arm):
                r = evaluate_pareto_campaign(
                    s, seed=seed, parent_dir=Path(d),
                    campaign_overrides=arm_overrides(arm, s, None))
        except Exception as exc:  # noqa: BLE001 -- charged, as single-objective
            spent = spent_under(d)
            return {**head, "status": "error", "budget": spent, "hv_regret": 1.0,
                    "certified": False, "false_cert": False,
                    "anytime": [1.0] * len(anytime_counts(spent)),
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                    "wall_s": time.perf_counter() - t0, "cpu_s": time.process_time() - c0}
        rep = json.loads((Path(r["work_dir"]) / "report.json").read_text()) \
            if (Path(r["work_dir"]) / "report.json").exists() else {}
        front = [dict(f["levels"]) for f in (rep.get("pareto") or {}).get("front") or []]
        rows = MO.nous_mo_rows(r["work_dir"], s)
        trans = Path(r["work_dir"]) / "transitions.jsonl"
        acc = ([json.loads(ln)["rule"].get("accounting", "")
                for ln in trans.read_text().splitlines() if ln.strip()]
               if trans.exists() else [])
    budget = len(rows)
    return {**head, "status": "ok", "budget": budget,
            "hv_regret": truth.regret(front), "n_front": len(front),
            "certified": bool(r["certified"]), "false_cert": bool(r["false_certified"]),
            "n_confident_off_front": r["n_confident_off_front"],
            "allocate_fired": any(a.startswith("allocate round") for a in acc),
            "anytime": MO.anytime_hv(rows, s, anytime_counts(budget), truth),
            "wall_s": time.perf_counter() - t0, "cpu_s": time.process_time() - c0}


def run_baseline_mo(method: str, name: str, seed: int, budget: int) -> dict:
    from benchmarks.optimization import mo as MO

    s = S.get_mo(name)
    truth = MO.HVTruth(s)
    t0, c0 = time.perf_counter(), time.process_time()
    rows, used = MO.run_mo_method(method, s, name, budget, seed)
    final = truth.regret(MO.measured_front(rows, s.objectives))
    return {"surface": name, "seed": seed, "method": method, "budget": budget,
            "used": used, "hv_regret": final,
            "anytime": MO.anytime_hv(rows, s, anytime_counts(budget), truth),
            "wall_s": time.perf_counter() - t0, "cpu_s": time.process_time() - c0,
            "code": _bench_digest()}


def _mo_nous_job(a):
    return globals()["run_nous_mo"](*a)


def _mo_base_job(a):
    return globals()["run_baseline_mo"](*a)


def run_mo(names, seeds, workers, scratch, cache_dir: Path | None = None,
           arms=MO_ARMS, methods=MO_METHOD_NAMES):
    nd, bd = _nous_digest(), _bench_digest()
    nous = []
    for arm in arms:
        jobs = [(n, s, scratch, arm) for n in names for s in seeds]
        nous += _cached_map(_mo_nous_job, jobs, workers,
                            cache_dir / "mo_nous.jsonl" if cache_dir else None,
                            key=lambda j, arm=arm: f"{nd}|{bd}|mo|{arm}|{j[0]}|{j[1]}")
    # Matched budget: every arm's run count on the same (surface, seed) gets
    # its own baseline runs, so each arm is compared at ITS budget.
    bjobs = sorted({(m, r["surface"], r["seed"], int(r["budget"])) for r in nous
                    if r.get("budget") for m in methods})
    bjobs.sort(key=lambda j: -(j[3] * (10 if j[0] == "ParEGO" else 1)))
    base = _cached_map(_mo_base_job, bjobs, workers,
                       cache_dir / "mo_baselines.jsonl" if cache_dir else None,
                       key=lambda j: f"{bd}|mo|{j[0]}|{j[1]}|{j[2]}|{j[3]}")
    return nous, base


# ── aggregation ─────────────────────────────────────────────────────────────
PRIMARY_RULE = {"RS": "best_observed", "LHS": "best_observed",
                "GP-BO": "gp_mean", "GP-BO-crude": "gp_mean"}


def head_to_head(nous, base, method, rule, tol_eps=False):
    nm = {(r["surface"], r["mult"], r["seed"]): r for r in nous if "regret" in r}
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
    nm = {(r["surface"], r["mult"], r["seed"]): r for r in nous if "regret" in r}
    cells = {}
    for r in nous:
        if "regret" not in r:
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
    # Only rows that were actually charged (legacy error rows carry no regret).
    errors = [r for r in nous if "error" in r and "regret" in r]
    codes = {"nous": sorted({r.get("code", "unrecorded") for r in nous}),
             "baselines": sorted({b.get("code", "unrecorded") for b in base})}
    # Cells with no baseline at all (every seed crashed and no planned budget):
    # listed, never silently missing from the head-to-heads (E2).
    with_base = {(b["surface"], b["mult"]) for b in base}
    uncompared = sorted({(r["surface"], r["mult"]) for r in nous} - with_base)
    dead = sum(int(b.get("dead_fallbacks") or 0) for b in base)
    # Intervals (pre-declared in the doc header): per-cell bootstrap of the
    # mean over seeds; the family primary (normalised regret, Nous minus each
    # baseline, per seed); Wilson on the head-to-head proportions; anytime.
    for row in rows:
        ns = cells[(row["surface"], row["mult"])]["nous"]
        row["nous_ci"] = list(ST.bootstrap_mean_ci([r["regret"] for r in ns]))[1:]
        for m in methods:
            bs = cells[(row["surface"], row["mult"])]["base"].get(m, [])
            row[f"{m}:ci"] = list(ST.bootstrap_mean_ci(
                [b[f"regret_{PRIMARY_RULE[m]}"] for b in bs]))[1:]
    wilson = {}
    for m in methods:
        wilson[m] = {}
        for kind in ("exact", "within_epsilon"):
            w, t_, l = h2h[m][PRIMARY_RULE[m]][kind]
            n = w + t_ + l
            wilson[m][kind] = {"n": n, "better": ST.wilson_ci(w, n), "worse": ST.wilson_ci(l, n)}
        for fname, d in fam.items():
            for kind in ("exact", "within_epsilon"):
                w, t_, l = d[m][kind]
                d[m][kind + "_wilson"] = {"better": ST.wilson_ci(w, w + t_ + l),
                                          "worse": ST.wilson_ci(l, w + t_ + l)}
    withheld: dict = {}
    for r in nous:
        if r.get("certified") or "regret" not in r:
            continue
        fam_w = withheld.setdefault(S.FAMILY.get(r["surface"], "?"), {})
        for w in r.get("withheld") or ["(none recorded)"]:
            fam_w[w] = fam_w.get(w, 0) + 1
    return {"rows": rows, "head_to_head": h2h, "by_family": fam, "errors": errors,
            "code_digests": codes, "uncompared_cells": uncompared,
            "dead_fallbacks": dead, "wilson": wilson, "withheld": withheld,
            "primary": family_primary(nous, base, methods),
            "anytime": anytime_summary(nous, base, methods),
            "certificates": certificate_counts(nous)}


def _norm_regret(r: dict, key: str = "regret") -> float:
    n = float(r.get("norm") or 0.0)
    return float(r[key]) / n if n > 0 else 0.0


def family_primary(nous, base, methods) -> dict:
    """The PRE-DECLARED primary: per family, the mean over seeds of (mean over
    the family's cells of normalised regret, Nous minus baseline under
    ``PRIMARY_RULE``), with a seeded bootstrap 95% interval over seeds and the
    t interval beside it. Negative favours Nous."""
    nm = {(r["surface"], r["mult"], r["seed"]): r for r in nous if "regret" in r}
    out = {}
    for fname in ("shipped", "non-quadratic", "many-knob sparse"):
        out[fname] = {}
        for m in methods:
            per_seed: dict = {}
            for b in base:
                if b["method"] != m or S.FAMILY.get(b["surface"]) != fname:
                    continue
                n = nm.get((b["surface"], b["mult"], b["seed"]))
                if n is None:
                    continue
                per_seed.setdefault(b["seed"], []).append(
                    _norm_regret(n) - _norm_regret(b, f"regret_{PRIMARY_RULE[m]}"))
            vals = [statistics.fmean(v) for _, v in sorted(per_seed.items())]
            if vals:
                out[fname][m] = {"seeds": len(vals),
                                 "bootstrap": ST.bootstrap_mean_ci(vals),
                                 "t": ST.t_mean_ci(vals)}
    return out


def _curve(rows, fam, key="anytime"):
    """Mean normalised anytime regret per fraction: per seed the mean over the
    family's cells, then the bootstrap over seeds."""
    per_seed: dict = {}
    for r in rows:
        if S.FAMILY.get(r["surface"]) != fam or not r.get(key) or len(r[key]) != len(FRACTIONS):
            continue
        n = float(r.get("norm") or 0.0)
        per_seed.setdefault(r["seed"], []).append(
            [v / n if n > 0 else 0.0 for v in r[key]])
    if not per_seed:
        return None
    pts = []
    for i in range(len(FRACTIONS)):
        vals = [statistics.fmean(c[i] for c in cs) for _, cs in sorted(per_seed.items())]
        pts.append(ST.bootstrap_mean_ci(vals))
    return pts


def anytime_summary(nous, base, methods) -> dict:
    out = {}
    for fname in ("shipped", "non-quadratic", "many-knob sparse"):
        d = {"Nous": _curve([r for r in nous if "regret" in r], fname)}
        for m in methods:
            d[m] = _curve([b for b in base if b["method"] == m], fname)
        out[fname] = {k: v for k, v in d.items() if v is not None}
    return out


def certificate_counts(rows) -> dict:
    """``{arm: {campaigns, certified, false}}`` -- the soundness check."""
    out: dict = {}
    for r in rows:
        if r.get("status") == "unavailable":
            continue
        a = out.setdefault(r.get("arm", "nous"), {"campaigns": 0, "certified": 0, "false": 0})
        a["campaigns"] += 1
        a["certified"] += bool(r.get("certified"))
        a["false"] += bool(r.get("false_cert"))
    return out


def summarize_ablations(default_rows, arm_rows, previous: dict | None = None) -> dict:
    """Each arm against the default on the SAME (surface, mult, seed): paired
    normalised regret difference (arm minus default; negative favours the
    arm), budget, certificates, false certificates, how often allocate fired."""
    base = {(r["surface"], r["mult"], r["seed"]): r for r in default_rows if "regret" in r}
    out: dict = {}
    for r in arm_rows:
        a = out.setdefault(r["arm"], {"unavailable": None, "cells": {}})
        if r.get("status") == "unavailable":
            a["unavailable"] = r["unavailable"]
            continue
        d = base.get((r["surface"], r["mult"], r["seed"]))
        if d is None or "regret" not in r:
            continue
        c = a["cells"].setdefault(f"{r['surface']}|{r['mult']:g}", {
            "family": S.FAMILY.get(r["surface"]), "diff": [], "seeds": [],
            "arm_budget": [], "def_budget": [], "arm_cert": 0, "def_cert": 0,
            "arm_false": 0, "def_false": 0, "fired": 0, "arm_regret": [], "def_regret": []})
        c["diff"].append(_norm_regret(r) - _norm_regret(d))
        c["seeds"].append(r["seed"])
        c["arm_regret"].append(r["regret"])
        c["def_regret"].append(d["regret"])
        c["arm_budget"].append(r["budget"])
        c["def_budget"].append(d["budget"])
        c["arm_cert"] += bool(r["certified"])
        c["def_cert"] += bool(d["certified"])
        c["arm_false"] += bool(r["false_cert"])
        c["def_false"] += bool(d["false_cert"])
        c["fired"] += bool(r.get("allocate_fired"))
    for arm, a in out.items():
        pooled: dict = {}
        for c in a["cells"].values():
            for s, v in zip(c["seeds"], c["diff"]):
                pooled.setdefault(c["family"], []).append((s, v))
        a["pooled"] = {f: _per_seed_ci(v) for f, v in pooled.items()}
        rows_ = [r for r in arm_rows if r.get("arm") == arm and "regret" in r]
        dd = [base[(r["surface"], r["mult"], r["seed"])] for r in rows_
              if (r["surface"], r["mult"], r["seed"]) in base]
        a["runs"] = {"arm": statistics.fmean(r["budget"] for r in rows_) if rows_ else None,
                     "default": statistics.fmean(r["budget"] for r in dd) if dd else None}
        a["certified"] = {"arm": sum(bool(r["certified"]) for r in rows_),
                          "default": sum(bool(r["certified"]) for r in dd),
                          "arm_false": sum(bool(r["false_cert"]) for r in rows_),
                          "default_false": sum(bool(r["false_cert"]) for r in dd),
                          "n": len(rows_)}
    for a in out.values():
        for c in a["cells"].values():
            c["diff_ci"] = ST.bootstrap_mean_ci(c.pop("diff"))
            c["arm_regret"] = statistics.fmean(c["arm_regret"])
            c["def_regret"] = statistics.fmean(c["def_regret"])
            c["arm_budget"] = statistics.fmean(c["arm_budget"])
            c["def_budget"] = statistics.fmean(c["def_budget"])
            c["n"] = len(c.pop("seeds"))
    return out


def summarize_mo(nous, base, methods=MO_METHOD_NAMES) -> dict:
    """Per (surface, arm): mean HV regret with a bootstrap CI, and each
    baseline at THAT arm's budgets (matched), certificates and false ones;
    pooled anytime curves per arm and per baseline (at the default arm's N)."""
    bm = {(b["method"], b["surface"], b["seed"], b["budget"]): b for b in base}
    rows, unavailable = [], {}
    surfaces = list(dict.fromkeys(r["surface"] for r in nous))
    for arm in dict.fromkeys(r["arm"] for r in nous):
        for name in surfaces:
            rs = [r for r in nous if r["arm"] == arm and r["surface"] == name]
            un = [r for r in rs if r.get("status") == "unavailable"]
            if un:
                unavailable[f"{arm}|{name}"] = un[0]["unavailable"]
                continue
            if not rs:
                continue
            row = {"surface": name, "arm": arm, "seeds": len(rs),
                   "budget": sorted({r["budget"] for r in rs}),
                   "nous": ST.bootstrap_mean_ci([r["hv_regret"] for r in rs]),
                   "certified": sum(r["certified"] for r in rs),
                   "false_cert": sum(r["false_cert"] for r in rs),
                   "fired": sum(bool(r.get("allocate_fired")) for r in rs)}
            for m in methods:
                bs = [bm.get((m, name, r["seed"], r["budget"])) for r in rs]
                bs = [b for b in bs if b is not None]
                row[m] = ST.bootstrap_mean_ci([b["hv_regret"] for b in bs])
                w = sum(1 for r in rs if (b := bm.get((m, name, r["seed"], r["budget"])))
                        and r["hv_regret"] < b["hv_regret"] - 1e-9)
                lo = sum(1 for r in rs if (b := bm.get((m, name, r["seed"], r["budget"])))
                         and r["hv_regret"] > b["hv_regret"] + 1e-9)
                row[f"{m}:h2h"] = (w, len(bs) - w - lo, lo)
            rows.append(row)
    curves = {}
    for arm in dict.fromkeys(r["arm"] for r in nous):
        curves[arm] = _mo_curve([r for r in nous if r["arm"] == arm])
    dflt = {(r["surface"], r["seed"]): r["budget"] for r in nous if r["arm"] == "nous"
            and r.get("budget")}
    for m in methods:
        curves[m] = _mo_curve([b for b in base if b["method"] == m
                               and dflt.get((b["surface"], b["seed"])) == b["budget"]])
    return {"rows": rows, "unavailable": unavailable,
            "anytime": {k: v for k, v in curves.items() if v},
            "pooled": mo_pooled(nous, base, methods),
            "certificates": certificate_counts(nous)}


def _per_seed_ci(pairs) -> tuple:
    """``pairs``: ``(seed, value)``; the mean per seed, then the bootstrap."""
    per: dict = {}
    for s, v in pairs:
        per.setdefault(s, []).append(v)
    return ST.bootstrap_mean_ci([statistics.fmean(v) for _, v in sorted(per.items())])


def mo_pooled(nous, base, methods=MO_METHOD_NAMES) -> dict:
    """Pooled over surfaces, per seed then bootstrapped: each arm's mean HV
    regret; each arm minus the default arm (paired); the default arm minus
    each baseline at the default arm's budget (paired)."""
    ok = [r for r in nous if r.get("status") != "unavailable" and "hv_regret" in r]
    by = {(r["arm"], r["surface"], r["seed"]): r for r in ok}
    bm = {(b["method"], b["surface"], b["seed"], b["budget"]): b for b in base}
    out = {"arm_mean": {}, "arm_minus_default": {}, "default_minus_baseline": {}}
    for arm in dict.fromkeys(r["arm"] for r in ok):
        rs = [r for r in ok if r["arm"] == arm]
        out["arm_mean"][arm] = _per_seed_ci((r["seed"], r["hv_regret"]) for r in rs)
        out["arm_mean"][arm + ":runs"] = statistics.fmean(r["budget"] for r in rs)
        if arm != "nous":
            out["arm_minus_default"][arm] = _per_seed_ci(
                (r["seed"], r["hv_regret"] - by[("nous", r["surface"], r["seed"])]["hv_regret"])
                for r in rs if ("nous", r["surface"], r["seed"]) in by)
    for m in methods:
        pairs = [(r["seed"], r["hv_regret"] - bm[(m, r["surface"], r["seed"], r["budget"])]["hv_regret"])
                 for r in ok if r["arm"] == "nous" and (m, r["surface"], r["seed"], r["budget"]) in bm]
        if pairs:
            out["default_minus_baseline"][m] = _per_seed_ci(pairs)
    return out


def _mo_curve(rows):
    per_seed: dict = {}
    for r in rows:
        if r.get("anytime") and len(r["anytime"]) == len(FRACTIONS):
            per_seed.setdefault(r["seed"], []).append(r["anytime"])
    if not per_seed:
        return None
    return [ST.bootstrap_mean_ci([statistics.fmean(c[i] for c in cs)
                                  for _, cs in sorted(per_seed.items())])
            for i in range(len(FRACTIONS))]


def _f(v, nd=3):
    if v is None or v != v:
        return "–"
    return f"{v:.{nd}f}"


def render_markdown(summary, meta, methods) -> str:
    cd = summary.get("code_digests") or {}
    out = [f"_Tables aggregated by `python -m benchmarks.optimization.run {meta['argv']}` "
           f"at checkout {meta['git_commit'] or 'no git'} (Nous {meta['nous_version']}); "
           f"seeds {meta['seeds']}, noise multipliers {meta['mults']}. Rows come from "
           f"the resume cache and record the code they were produced under: Nous "
           f"source digest(s) {', '.join(cd.get('nous') or [])}; benchmark code "
           f"digest(s) {', '.join(cd.get('baselines') or [])}. "
           f"{_rss_line(meta)}_", ""]
    out += render_primary(summary, methods)
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
    if summary["rows"] and "nous_ci" in summary["rows"][0]:
        out += ["", "### 95% bootstrap intervals of the per-cell means (over seeds; "
                    "primary rule for baselines)", "",
                "| surface | noise | Nous | " + " | ".join(methods) + " |",
                "|---|---|---|" + "---|" * len(methods)]
        for r in summary["rows"]:
            out.append(f"| {r['surface']} | ×{r['mult']:g} | {_ci(r['nous_ci'])} | "
                       + " | ".join(_ci(r[f'{m}:ci']) for m in methods) + " |")
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
    if summary.get("wilson"):
        out += ["", "### Wilson 95% intervals on the pooled head-to-head proportions "
                    "(primary rule)", "",
                "Conditional on THESE surfaces and noise levels: each campaign is one "
                "trial, the surfaces are a fixed, non-random selection, and campaigns "
                "of one cell are not independent of each other's surface. The interval "
                "says nothing about other surfaces.", "",
                "| baseline | n | P(Nous better), exact | P(Nous worse), exact | "
                "P(better), within ε | P(worse), within ε |", "|---|---|---|---|---|---|"]
        for m in methods:
            w = summary["wilson"][m]
            out.append(f"| {m} | {w['exact']['n']} | {_pci(w['exact']['better'])} | "
                       f"{_pci(w['exact']['worse'])} | {_pci(w['within_epsilon']['better'])} | "
                       f"{_pci(w['within_epsilon']['worse'])} |")
    out += render_anytime(summary.get("anytime") or {}, methods)
    out += ["", "### Median CPU seconds per campaign", "",
            "| surface | noise | Nous | " + " | ".join(methods) + " |",
            "|---|---|---|" + "---|" * len(methods)]
    for r in summary["rows"]:
        out.append(f"| {r['surface']} | ×{r['mult']:g} | {_f(r['nous_cpu_s'], 2)} | "
                   + " | ".join(_f(r[f'{m}:cpu_s'], 2) for m in methods) + " |")
    if summary.get("withheld"):
        out += ["", "### Why uncertified campaigns were withheld (reasons per campaign; one "
                    "campaign can carry several)", "",
                "| family | reason | campaigns |", "|---|---|---|"]
        for fam, d in summary["withheld"].items():
            for w, n in sorted(d.items(), key=lambda kv: -kv[1]):
                out.append(f"| {fam} | `{w}` | {n} |")
    if summary.get("uncompared_cells"):
        out += ["", "### Cells with no baseline (every seed crashed, no planned budget)", ""]
        out += [f"- {n} ×{m:g}" for n, m in summary["uncompared_cells"]]
    out += ["", f"_GP-BO had to re-pick an only-failed configuration "
                f"{summary.get('dead_fallbacks', 0)} time(s) (every candidate had "
                f"failed)._"]
    if summary["errors"]:
        out += ["", "### Nous campaigns that raised (charged the worst admissible regret)", ""]
        for e in summary["errors"]:
            out.append(f"- {e['surface']} ×{e['mult']:g} seed {e['seed']}: `{e['error']}`")
    return "\n".join(out) + "\n"


def _rss_line(meta: dict) -> str:
    r = meta.get("peak_rss") or {}
    if not r:
        return ""
    return (f"Wall {meta.get('elapsed_s', 0) / 60:.1f} min; peak RSS: largest worker "
            f"{r.get('largest_worker_gb')} GB, parent {r.get('self_gb')} GB.")


def _ci(v, nd=3):
    """``(lo, hi)`` or ``(est, lo, hi)`` as ``[lo, hi]``."""
    if not v:
        return "–"
    lo, hi = (v[1], v[2]) if len(v) == 3 else (v[0], v[1])
    return f"[{_f(lo, nd)}, {_f(hi, nd)}]"


def _eci(v, nd=3):
    """``(est, lo, hi)`` as ``est [lo, hi]``."""
    if not v:
        return "–"
    return f"{_f(v[0], nd)} {_ci(v, nd)}"


def _pci(v):
    if not v or v[0] != v[0]:
        return "–"
    return f"{v[0]:.2f} [{v[1]:.2f}, {v[2]:.2f}]"


def render_primary(summary, methods) -> list[str]:
    pr = summary.get("primary") or {}
    if not pr:
        return []
    out = ["### PRIMARY (pre-declared): mean normalised regret difference, Nous minus "
           "baseline, per family", "",
           "Normalised regret = regret / (f_best - f_worst admissible). Per seed: the "
           "mean over the family's cells; then the mean over seeds with a seeded "
           f"percentile bootstrap ({ST.BOOT_RESAMPLES} resamples, seed {ST.BOOT_SEED}) "
           "and the t interval. Negative favours Nous.", "",
           "| family | baseline | seeds | mean [bootstrap 95%] | t 95% |", "|---|---|---|---|---|"]
    for fam, d in pr.items():
        for m in methods:
            if m in d:
                out.append(f"| {fam} | {m} | {d[m]['seeds']} | {_eci(d[m]['bootstrap'], 4)} | "
                           f"{_ci(d[m]['t'], 4)} |")
    certs = summary.get("certificates") or {}
    if certs:
        out += ["", "**Certification soundness:** " + "; ".join(
            f"{a}: {c['certified']} certified of {c['campaigns']}, **{c['false']} false**"
            for a, c in certs.items()) + "."]
    return out + [""]


def render_anytime(any_, methods, label="Nous") -> list[str]:
    if not any_:
        return []
    out = ["", "### Anytime regret (mean normalised regret at fractions of N, "
               "bootstrap 95% over seeds)", "",
           "Nous: the best-so-far always-admissible measured configuration after its "
           "first n runs (its campaign is NOT stopped there: this is where its run "
           "sequence stands). Baselines: their primary-rule pick on the prefix of "
           "their own measurements. N is Nous's own stopping budget.", "",
           "| family | method | " + " | ".join(f"{f:.0%} N" for f in FRACTIONS) + " |",
           "|---|---|" + "---|" * len(FRACTIONS)]
    for fam, d in any_.items():
        for m in [label, *methods]:
            if m in d:
                out.append(f"| {fam} | {m} | " + " | ".join(_eci(v) for v in d[m]) + " |")
    return out


def render_ablations(ab: dict) -> str:
    out = ["### Ablations: each arm against the default on the same seeds", "",
           "Δ = mean paired normalised regret, arm minus default, bootstrap 95% over "
           "seeds; negative favours the arm. N = mean runs. cert/false per arm.", ""]
    for arm, a in ab.items():
        out.append(f"**{arm}** — {ARM_DOC.get(arm, arm)}.")
        if a.get("unavailable"):
            out += ["", f"_Unavailable on this checkout: {a['unavailable']}._", ""]
            continue
        rn, ce = a.get("runs") or {}, a.get("certified") or {}
        if rn.get("arm") is not None:
            out += ["", f"Over its {ce['n']} campaigns: mean runs {rn['default']:.1f} (default) → "
                        f"{rn['arm']:.1f} (arm); certified {ce['default']} → {ce['arm']}; false "
                        f"certificates {ce['default_false']} → {ce['arm_false']}. Pooled Δ by "
                        "family: " + "; ".join(f"{f} {_eci(v, 4)}"
                                                for f, v in (a.get("pooled") or {}).items()) + "."]
        out += ["", "| surface | noise | n | regret default → arm | Δ [95%] | N default → arm "
                "| cert/false default | cert/false arm | allocate fired |",
                "|---|---|---|---|---|---|---|---|---|"]
        for k, c in a["cells"].items():
            name, mult = k.split("|")
            out.append(f"| {name} | ×{mult} | {c['n']} | {_f(c['def_regret'])} → "
                       f"{_f(c['arm_regret'])} | {_eci(c['diff_ci'], 4)} | "
                       f"{c['def_budget']:.1f} → {c['arm_budget']:.1f} | "
                       f"{c['def_cert']}/{c['def_false']} | {c['arm_cert']}/{c['arm_false']} | "
                       f"{c['fired']} |")
        out.append("")
    return "\n".join(out) + "\n"


def render_mo(mo: dict, meta: dict, methods=MO_METHOD_NAMES) -> str:
    out = [f"_Generated by `python -m benchmarks.optimization.run {meta['argv']}` at "
           f"checkout {meta['git_commit'] or 'no git'}; seeds {meta['seeds']}; Nous digest(s) "
           f"{', '.join(meta.get('nous_digests') or [])}, benchmark digest(s) "
           f"{', '.join(meta.get('bench_digests') or [])}. {_rss_line(meta)}_", "",
           "### Hypervolume regret at the matched budget (mean [bootstrap 95%]; lower is "
           "better)", "",
           "Each baseline row is at the SAME arm's per-seed budget. h2h = arm better / tie "
           "/ worse than the baseline.", "",
           "| surface | arm | N | Nous | cert/false | " + " | ".join(methods) + " | "
           + " | ".join(f"h2h {m}" for m in methods) + " |",
           "|---|---|---|---|---|" + "---|" * (2 * len(methods))]
    for r in mo["rows"]:
        n = r["budget"]
        nstr = f"{n[0]}" if len(n) == 1 else f"{n[0]}-{n[-1]}"
        out.append(f"| {r['surface']} | {r['arm']} | {nstr} | {_eci(r['nous'])} | "
                   f"{r['certified']}/{r['false_cert']} of {r['seeds']} | "
                   + " | ".join(_eci(r[m]) for m in methods) + " | "
                   + " | ".join("{} / {} / {}".format(*r[f'{m}:h2h']) for m in methods) + " |")
    if mo.get("unavailable"):
        out += ["", "Unavailable arms / surfaces on this checkout:", ""]
        out += [f"- {k}: {v}" for k, v in mo["unavailable"].items()]
    if mo.get("anytime"):
        out += ["", "### Anytime HV regret, pooled over surfaces (bootstrap 95% over seeds)",
                "", "Baselines at the default arm's N.", "",
                "| method | " + " | ".join(f"{f:.0%} N" for f in FRACTIONS) + " |",
                "|---|" + "---|" * len(FRACTIONS)]
        for k, v in mo["anytime"].items():
            out.append(f"| {k} | " + " | ".join(_eci(x) for x in v) + " |")
    pl = mo.get("pooled") or {}
    if pl:
        out += ["", "### Pooled over surfaces (per seed, then bootstrap 95% over seeds)", "",
                "| quantity | mean [95%] |", "|---|---|"]
        for k, v in pl["arm_mean"].items():
            if not k.endswith(":runs"):
                out.append(f"| HV regret, {k} (mean runs {pl['arm_mean'][k + ':runs']:.1f}) "
                           f"| {_eci(v, 4)} |")
        for k, v in pl["arm_minus_default"].items():
            out.append(f"| {k} minus nous (paired; negative favours the arm) | {_eci(v, 4)} |")
        for k, v in pl["default_minus_baseline"].items():
            out.append(f"| nous minus {k} at nous's N (paired; negative favours Nous) "
                       f"| {_eci(v, 4)} |")
    certs = mo.get("certificates") or {}
    if certs:
        out += ["", "**Certification soundness (front certificates):** " + "; ".join(
            f"{a}: {c['certified']} certified of {c['campaigns']}, **{c['false']} false**"
            for a, c in certs.items()) + "."]
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
    shown, skip = [], False
    for tok in argv:
        if skip:
            shown.append("<cache-dir>")
            skip = False
            continue
        skip = tok == "--cache-dir"
        shown.append("--cache-dir=<cache-dir>" if tok.startswith("--cache-dir=") else tok)
    return {"argv": " ".join(shown), "nous_version": v["package_version"],
            "git_commit": v.get("git_commit"), "seeds": list(seeds), "mults": list(mults)}


#: Hard cap on parallel benchmark workers (memory safety on shared machines).
MAX_WORKERS = 3


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--surfaces", nargs="*", default=None)
    ap.add_argument("--seeds", type=int, nargs="*", default=list(range(1, 9)))
    ap.add_argument("--mults", type=float, nargs="*", default=[1.0, 4.0])
    ap.add_argument("--methods", nargs="*", default=list(METHODS))
    # Default 2, hard cap MAX_WORKERS: eight workers at 28-40 GB each froze a
    # 64 GB machine (2026-10-16). Run under nous-e2e/bin/heavy for the
    # machine-wide lock and the memory watchdog.
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--audit-repro", action="store_true",
                    help="the stage-0 audit's Q6 setup: its 9 surfaces, seeds 1-20, noise x1/x8")
    ap.add_argument("--ablations", action="store_true",
                    help="the D4 ablations (ABLATION_SO) against the default arm, "
                         "same seeds and noise multipliers as the suite")
    ap.add_argument("--mo", action="store_true",
                    help="the multi-objective arm: Nous (default / allocate / allocate+BO) "
                         "against RS, LHS and ParEGO on PARETO_SURFACES + pareto_three_discrete")
    ap.add_argument("--plan", action="store_true",
                    help="print the job counts this invocation would run, then exit")
    ap.add_argument("--render-only", action="store_true",
                    help="re-aggregate and re-render this section from its JSON "
                         "(no campaign runs; the rows keep the digests they record)")
    ap.add_argument("--no-markdown", action="store_true")
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="resume directory: finished campaigns are appended "
                         "here and reused by a re-run with the same arguments")
    a = ap.parse_args(argv)
    if not 1 <= a.workers <= MAX_WORKERS:
        ap.error(f"--workers must be 1..{MAX_WORKERS} (each worker can hold several GB; "
                 f"see the module docstring)")
    if a.audit_repro:
        names, seeds, mults, section = AUDIT_SURFACES, list(range(1, 21)), [1.0, 8.0], "audit-repro"
    elif a.ablations:
        names, seeds, mults, section = None, a.seeds, a.mults, "ablations"
    elif a.mo:
        names, seeds, mults, section = a.surfaces or S.MO_WANTED, a.seeds, [1.0], "mo"
    else:
        names, seeds, mults, section = a.surfaces or DEFAULT_SURFACES, a.seeds, a.mults, "suite"
    if a.plan:
        print(json.dumps(plan_size(section, names, seeds, mults, a.methods), indent=1))
        return 0
    if a.render_only:
        return render_only(section, a.out, a.methods, a.no_markdown)
    a.out.mkdir(parents=True, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="nous-bench-")
    t0 = time.time()
    cache_dir = None
    if a.cache_dir is not None:
        cache_dir = a.cache_dir / section
        cache_dir.mkdir(parents=True, exist_ok=True)
    md_path = a.out / "optimization-benchmark.md"
    if section == "ablations":
        plan = ABLATION_SO
        dnames = sorted({n for v in plan.values() for n in v}, key=list(S.ALL).index)
        # The default arm's rows come from the SUITE cache when it is there
        # (same key, same code): the ablation never re-runs them.
        suite_cache = a.cache_dir / "suite" if a.cache_dir is not None else None
        if suite_cache is not None:
            suite_cache.mkdir(parents=True, exist_ok=True)
        nd, bd = _nous_digest(), _bench_digest()
        default = _cached_map(_nous_job, [(n, m, s, scratch) for n in dnames for m in mults
                                          for s in seeds], a.workers,
                              suite_cache / "nous.jsonl" if suite_cache else None,
                              key=_nous_key(nd, bd, "nous"))
        arms = run_ablations(mults, seeds, a.workers, scratch, cache_dir, plan)
        ab = summarize_ablations(default, arms)
        meta = {**_meta(argv, seeds, mults), "elapsed_s": time.time() - t0, "peak_rss": peak_rss_gb(),
                "arms": ARM_DOC, "plan": plan, "boot": [ST.BOOT_RESAMPLES, ST.BOOT_SEED],
                "nous_digests": sorted({r["code"] for r in default + arms})}
        (a.out / "optimization-benchmark-ablations.json").write_text(json.dumps(
            {"meta": meta, "summary": ab, "certificates": certificate_counts(default + arms),
             "default": default, "arms": arms}, indent=1, default=str))
        md = (f"_Generated by `python -m benchmarks.optimization.run {meta['argv']}` at checkout "
              f"{meta['git_commit'] or 'no git'}; seeds {seeds}, noise {mults}; Nous digest(s) "
              f"{', '.join(meta['nous_digests'])}, benchmark digest {bd}. {_rss_line(meta)}_\n\n"
              + render_ablations(ab) + "\n**Certification soundness:** " + "; ".join(
                  f"{k}: {c['certified']} certified of {c['campaigns']}, **{c['false']} false**"
                  for k, c in certificate_counts(default + arms).items()) + ".\n")
    elif section == "mo":
        nous, base = run_mo(names, seeds, a.workers, scratch, cache_dir)
        mo = summarize_mo(nous, base)
        meta = {**_meta(argv, seeds, mults), "elapsed_s": time.time() - t0, "peak_rss": peak_rss_gb(),
                "arms": {k: ARM_DOC[k] for k in MO_ARMS}, "boot": [ST.BOOT_RESAMPLES, ST.BOOT_SEED],
                "nous_digests": sorted({r["code"] for r in nous}),
                "bench_digests": sorted({b["code"] for b in base})}
        (a.out / "optimization-benchmark-mo.json").write_text(json.dumps(
            {"meta": meta, "summary": mo, "nous": nous, "baselines": base},
            indent=1, default=str))
        md = render_mo(mo, meta)
    else:
        nous, base = run_suite(names, mults, seeds, a.methods, a.workers, scratch, cache_dir)
        summary = summarize(nous, base, a.methods)
        meta = {**_meta(argv, seeds, mults), "elapsed_s": time.time() - t0, "peak_rss": peak_rss_gb(),
                "excluded": EXCLUDED, "primary_rule": PRIMARY_RULE,
                "fractions": list(FRACTIONS), "boot": [ST.BOOT_RESAMPLES, ST.BOOT_SEED]}
        stem = "optimization-benchmark" + ("-audit-repro" if a.audit_repro else "")
        (a.out / f"{stem}.json").write_text(json.dumps(
            {"meta": meta, "summary": summary, "nous": nous, "baselines": base},
            indent=1, default=str))
        md = render_markdown(summary, meta, a.methods)
    if not a.no_markdown:
        write_markdown(md_path, md, section)
    print(md)
    return 0


def render_only(section, out: Path, methods, no_markdown=False) -> int:
    stem = {"suite": "optimization-benchmark", "audit-repro": "optimization-benchmark-audit-repro",
            "ablations": "optimization-benchmark-ablations", "mo": "optimization-benchmark-mo"}
    path = out / f"{stem[section]}.json"
    d = json.loads(path.read_text())
    meta = d["meta"]
    if section == "ablations":
        ab = summarize_ablations(d["default"], d["arms"])
        certs = certificate_counts(d["default"] + d["arms"])
        d["summary"], d["certificates"] = ab, certs
        md = (f"_Generated by `python -m benchmarks.optimization.run {meta['argv']}` at checkout "
              f"{meta['git_commit'] or 'no git'}; seeds {meta['seeds']}, noise {meta['mults']}; "
              f"Nous digest(s) {', '.join(meta['nous_digests'])}. {_rss_line(meta)}_\n\n"
              + render_ablations(ab) + "\n**Certification soundness:** " + "; ".join(
                  f"{k}: {c['certified']} certified of {c['campaigns']}, **{c['false']} false**"
                  for k, c in certs.items()) + ".\n")
    elif section == "mo":
        d["summary"] = summarize_mo(d["nous"], d["baselines"])
        md = render_mo(d["summary"], meta)
    else:
        d["summary"] = summarize(d["nous"], d["baselines"], methods)
        md = render_markdown(d["summary"], meta, methods)
    path.write_text(json.dumps(d, indent=1, default=str))
    if not no_markdown:
        write_markdown(out / "optimization-benchmark.md", md, section)
    print(md)
    return 0


def peak_rss_gb() -> dict:
    """Peak resident set size of this process and of its largest finished
    child (a pool worker), in GB. ``ru_maxrss`` is bytes on macOS and KiB on
    Linux. Recorded in every section's JSON meta (P7 review M4)."""
    import resource

    unit = 1.0 if sys.platform == "darwin" else 1024.0
    me = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit / 1e9
    kid = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * unit / 1e9
    return {"self_gb": round(me, 3), "largest_worker_gb": round(kid, 3)}


def plan_size(section, names, seeds, mults, methods) -> dict:
    """Job counts of one invocation (sized BEFORE anything is enumerated)."""
    if section == "ablations":
        arms = sum(len(v) for v in ABLATION_SO.values()) * len(mults) * len(seeds)
        dflt = len({n for v in ABLATION_SO.values() for n in v}) * len(mults) * len(seeds)
        return {"section": section, "nous_arm_campaigns": arms,
                "default_campaigns_reused_from_suite": dflt}
    if section == "mo":
        n = len(names) * len(seeds)
        return {"section": section, "nous_campaigns": n * len(MO_ARMS),
                "baseline_runs_at_most": n * len(MO_ARMS) * len(MO_METHOD_NAMES)}
    n = len(names) * len(mults) * len(seeds)
    return {"section": section, "nous_campaigns": n, "baseline_runs": n * len(methods)}


if __name__ == "__main__":
    sys.exit(main())
