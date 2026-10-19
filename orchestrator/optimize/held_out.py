"""What the held-out metrics say about the configurations the report names.

Why this module exists
----------------------
``response.held_out`` is the campaign's generalization check: metrics recorded
on every row but structurally split off the response (``runner._split_held_out``)
so no fitting, ranking, or certification input can ever read them. That split
is enforced. What was missing is the other half -- READING them. The values
sat in ``runs.jsonl`` and no artifact summarised them, so a campaign that
declared a held-out metric and one that did not produced the same report. The
first end-to-end campaign of this kind showed exactly that.

This is a pure read, after every decision is made: ``report.json`` is written
from the ladder first, and this summary is attached beside it. It decides
nothing and feeds nothing -- that is what keeps it a held-out check rather
than a second objective. For each configuration the report names (the
recommendation, then each finalist) it gives the held-out mean over the
epoch's ``complete`` rows at exactly those levels, and the primary metric's
mean over the SAME rows, so a reader can compare the two on equal footing.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean


def _rows(work_dir: Path, iterations) -> list[dict]:
    out: list[dict] = []
    for it in sorted(iterations):
        path = Path(work_dir) / "runs" / f"iter-{it}" / "runs.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _summarise(rows: list[dict], levels: dict, metrics: list[str],
               primary: str) -> dict:
    at = [r for r in rows
          if r.get("status") == "complete" and r.get("levels") == levels]
    entry: dict = {"levels": dict(levels), "n_rows": len(at), "metrics": {}}
    for m in metrics:
        pairs = [(r["held_out"][m], (r.get("response") or {}).get(primary))
                 for r in at if _numeric((r.get("held_out") or {}).get(m))]
        held = [h for h, _ in pairs]
        prim = [p for _, p in pairs if _numeric(p)]
        entry["metrics"][m] = {
            "n": len(held),
            "mean": fmean(held) if held else None,
            "primary_mean_same_rows": fmean(prim) if prim else None,
        }
    return entry


def held_out_summary(work_dir: Path, *, iterations, held_out: list[str],
                     primary: str, recommendation: dict,
                     finalists: list[dict]) -> dict | None:
    """The ``report.json`` ``held_out`` block, or None when none is declared."""
    metrics = [str(m) for m in (held_out or [])]
    if not metrics:
        return None
    rows = _rows(work_dir, iterations)
    out = {
        "metrics": metrics,
        "recommendation": _summarise(rows, recommendation or {}, metrics, primary),
        "finalists": [],
    }
    for f in finalists or []:
        lv = f.get("levels") if isinstance(f, dict) else None
        if isinstance(lv, dict):
            out["finalists"].append(
                {"key": f.get("key"), **_summarise(rows, lv, metrics, primary)})
    return out


# ── held-out SEEDS on the winner (#321) ──────────────────────────────────────
#
# ``response.held_out`` above is a different METRIC on the same rows. This is
# the other half of a generalization check: the same metric on workload draws
# the campaign never measured. After the report ladder has fixed the answer,
# the winner and the known_valid_baseline are each run once per declared
# held-out seed (paired: both arms share a seed), and the gain is reported with
# its own interval. The rows go to ``held_out_seeds.epoch-<e>.jsonl`` at the
# work_dir root, OUTSIDE ``runs/iter-*``: nothing that fits, ranks, budgets or
# certifies reads that tree's complement, so the block cannot feed back. The
# seeds are pre-registered: ``policy.json`` copies ``optimization.workload``,
# so they are inside ``policy.sha256`` before the first benchmark run.

HELD_OUT_SEEDS_FILE = "held_out_seeds.epoch-{epoch}.jsonl"
ROW_BASE = -100_000   # negative: never a design row (cf. build.baseline_runs)


def _seeds_seen(work_dir: Path) -> set[int]:
    """Every workload seed any registered row of this work_dir carried."""
    seen: set[int] = set()
    for p in Path(work_dir).glob("runs/iter-*/design_matrix.json"):
        try:
            ws = json.loads(p.read_text()).get("workload_seeds") or {}
        except (OSError, ValueError):
            continue
        seen.update(int(v) for v in ws.values() if isinstance(v, int))
    be = Path(work_dir) / "baseline_equivalence.json"
    if be.exists():
        try:
            seen.update(int(v) for v in json.loads(be.read_text()).get("workload_seeds") or []
                        if isinstance(v, int))
        except (OSError, ValueError):
            pass
    return seen


def held_out_seed_cost(campaign: dict) -> int:
    """Runs the block spends after the report: two per declared seed (winner +
    baseline), and zero when it cannot run (no baseline, multi-objective)."""
    opt = (campaign or {}).get("optimization") or {}
    seeds = ((opt.get("workload") or {}).get("held_out_seeds")) or []
    if not seeds or not opt.get("known_valid_baseline") or (opt.get("response") or {}).get(
            "objectives"):
        return 0
    return 2 * len(seeds)


# A recorded decline (#321 review M3): the post-measurement checks
# (clean tree, surviving processes) and a mid-block failure are facts about the
# MEASUREMENT, so they are written into the rows file -- one line with
# ``{"declined": ...}`` -- and replay / resume read them back instead of
# re-judging an empty block as clean.
def record_decline(work_dir: Path, pol: dict, reason: str, detail: str) -> None:
    path = Path(work_dir) / HELD_OUT_SEEDS_FILE.format(epoch=int(pol.get("epoch", 1)))
    with open(path, "a") as fh:
        fh.write(json.dumps({"declined": reason, "detail": detail}, sort_keys=True) + "\n")


def _decline(seeds, reason: str, detail: str) -> dict:
    return {"seeds": list(seeds), "declined": reason, "detail": detail,
            "feeds_certification": False}


def held_out_seed_block(work_dir: Path, *, pol: dict, campaign: dict, levels: dict,
                        basis: str, metric: str, direction: str, runner,
                        replay: bool, in_sample_gain: dict | None) -> dict | None:
    """The ``report.json`` ``held_out_seeds`` block, or None when undeclared.

    Every branch that does not measure returns ``declined`` with a named reason.
    ``replay`` (``nous reanalyze``) re-reads the recorded rows instead of
    measuring. Never raises for a measurement problem: a failed row is a row
    without a pair, recorded as such.
    """
    import math

    from orchestrator.optimize import factors as factors_mod
    from orchestrator.optimize import matrix

    wl = (pol or {}).get("workload") or {}
    seeds = [int(s) for s in (wl.get("held_out_seeds") or [])]
    if not seeds:
        return None
    base = (pol or {}).get("known_valid_baseline")
    if (pol.get("objective") or {}).get("objectives"):
        return _decline(seeds, "multi_objective",
                        "held-out seeds are measured for a single winner and the "
                        "baseline; a front has no single winner")
    if not base:
        return _decline(seeds, "no_baseline",
                        "no known_valid_baseline to pair the winner with")
    if not levels or basis in ("none", "baseline"):
        return _decline(seeds, "no_winner",
                        f"the report's answer is on basis {basis!r}, so there is no "
                        f"winner distinct from the baseline to measure")
    if dict(levels) == dict(base):
        return _decline(seeds, "winner_is_baseline",
                        "the recommendation IS the baseline: its gain is zero by "
                        "construction")
    seen = _seeds_seen(work_dir)
    overlap = sorted(set(seeds) & seen)
    path = Path(work_dir) / HELD_OUT_SEEDS_FILE.format(epoch=int(pol.get("epoch", 1)))
    arms = {"winner": dict(levels), "baseline": dict(base)}
    recorded: list[dict] = []
    if path.exists():
        lines = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        recorded = [r for r in lines if "declined" not in r]
        verdicts = [r for r in lines if "declined" in r]
        if recorded and {json.dumps(r.get("levels"), sort_keys=True)
                         for r in recorded} != {
                json.dumps(v, sort_keys=True) for v in arms.values()}:
            recorded = []           # an earlier answer's rows: measure afresh
        elif verdicts:
            # (also a measurement that failed before writing any row)
            # The block was measured and declined then; that stands on resume
            # and on replay, so tainted rows are never accepted later.
            v = verdicts[-1]
            return {**_decline(seeds, v["declined"], v.get("detail", "")),
                    "file": path.name}
    if not recorded:
        if replay:
            return _decline(seeds, "not_in_record",
                            f"{path.name} is not in the record, so there is nothing "
                            f"to replay")
        if runner is None:
            return _decline(seeds, "no_runner", "no config_runner to measure with")
        from orchestrator.optimize import runner as runner_mod

        fs = factors_mod.parse_factors((campaign.get("optimization") or {})["factors"])
        rows = []
        for k, s in enumerate(seeds):
            # Alternate which arm runs first, so a drift within the block loads
            # both arms equally.
            for j, arm in enumerate(("winner", "baseline") if k % 2 == 0
                                    else ("baseline", "winner")):
                ap = matrix.render_apply(fs, arms[arm])
                ap = {**ap, "env": {**(ap.get("env") or {}), wl["seed_env"]: s},
                      "held_out_arm": arm, "held_out_seed": s}
                rows.append(matrix.ConfigRow(row_index=ROW_BASE - 2 * k - j,
                                             levels=dict(arms[arm]), role="held_out_seed",
                                             replicate=k, apply=ap))
        opt = campaign.get("optimization") or {}
        outcomes = runner_mod.execute_design(
            rows, runner=runner, response_spec=opt.get("response") or {},
            invariants=((opt.get("design_space") or {}).get("invariants")) or [],
            factors=fs)
        by_idx = {r.row_index: r for r in rows}
        recorded = [{"row_index": o.row_index, "arm": by_idx[o.row_index].apply["held_out_arm"],
                     "seed": by_idx[o.row_index].apply["held_out_seed"],
                     "levels": by_idx[o.row_index].levels, "status": o.status,
                     "response": dict(o.response or {}),
                     **({"error": o.error} if o.error else {})}
                    for o in outcomes]
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in recorded))
    sign = 1.0 if direction == "maximize" else -1.0
    val = {(r["arm"], r["seed"]): (r.get("response") or {}).get(metric)
           for r in recorded if r.get("status") == "complete"}
    pairs = []
    for s in seeds:
        w, b = val.get(("winner", s)), val.get(("baseline", s))
        ok = _numeric(w) and _numeric(b)
        pairs.append({"seed": s, "winner": w if _numeric(w) else None,
                      "baseline": b if _numeric(b) else None,
                      "gain": sign * (w - b) if ok else None})
    d = [p["gain"] for p in pairs if p["gain"] is not None]
    delta = float((pol.get("objective") or {}).get("delta_terminal", 0.05))
    gain = {"estimate": fmean(d) if d else None, "low": None, "high": None,
            "level": 1.0 - delta, "n_pairs": len(d),
            "method": "two-sided paired t on winner - baseline (signed so positive "
                      "is better), one interval, not part of certification"}
    if len(d) >= 2:
        from scipy.stats import t as student_t

        m = fmean(d)
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1))
        half = float(student_t.ppf(1 - delta / 2, len(d) - 1)) * sd / math.sqrt(len(d))
        gain["low"], gain["high"] = m - half, m + half
    else:
        gain["no_interval_because"] = f"{len(d)} complete pair(s); an interval needs 2"
    return {
        "seeds": seeds, "declined": None, "feeds_certification": False,
        "winner": arms["winner"], "baseline": arms["baseline"], "basis": basis,
        "unseen": not overlap, "overlap_with_measured_seeds": overlap,
        "runs": len(recorded), "file": path.name, "pairs": pairs, "gain": gain,
        "in_sample_gain": ({k: in_sample_gain.get(k) for k in ("estimate", "low", "high")}
                           if in_sample_gain else None),
    }
