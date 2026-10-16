"""``nous reanalyze``: re-derive every fitted artifact from the recorded runs.

Zero tokens and zero measurements. A third party holding a work_dir can ask
"does this report follow from these rows under this code?" without trusting
the process that wrote it (audit Q7).

How
---
The ANALYSIS of a ``kind: optimization`` campaign is a deterministic function
of (the registered campaign of each epoch, the measured rows, the code). So
reanalysis re-drives the real ``stage_runner.run_stage`` -- not a parallel
re-implementation that could disagree with it -- over a FRESH scratch work_dir,
iteration by iteration, with:

* the campaign each epoch registered (``campaign.epoch-<e>.yaml``), with
  ``target_system.repo_path`` removed so nothing can reach the target;
* a ``config_runner`` that REPLAYS the original iteration's ``runs.jsonl``:
  each requested row is answered with the observation recorded for the same
  ``row_index`` (and must ask for the same levels, else it is a replay
  mismatch); a row recorded as failed raises again, so retries and exclusions
  replay as they happened. Nothing is executed.
* the per-iteration test verdicts recorded in ``relations.json``.

``plan`` and ``build`` iterations are agent calls and the build oracles
(2(b), 2(c), 2(d), the write-scope gate, the build review) are MEASUREMENTS of the
target tree; none of them is re-run. Their records are left out of the
comparison and listed as such. ``mechanism.sha256`` is carried into the scratch
dir so the recompiled policy hashes to the registered one.

Then every derived artifact (policy, transitions, design matrices, fits,
recommendations, shortlists, confirmations, the report and report.md) is
compared with the original after removing volatile fields (timestamps,
durations, attempt counts, absolute paths, the Nous version stamp). Identical
means the ANALYSIS is re-derived from its rows (the measurements are not re-run,
and row attempt counts and durations are not replayed); every difference is
listed. Exit 2 when the work_dir cannot be reanalysed at all.
Before any of that, the input hashes ``report.json`` recorded
(``provenance.inputs``) are checked against the files on disk, so a row edited
after the report was written is reported as such.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

#: Keys whose values legitimately differ between two derivations.
VOLATILE_KEYS = frozenset({
    "timestamp", "captured_at", "started_at", "finished_at", "work_dir",
    "duration_ms", "last_attempt_ms", "attempts", "elapsed_ms", "wall_clock_s",
})

#: Original-only files that are measurements or agent output, never derived.
NOT_DERIVED = frozenset({
    "pre_build_tests.json", "baseline_equivalence.json", "build_review.json",
    "authored_tests.json", "build_scope.json", "adapter_contract.json",
    "mechanism_plan.json", "reanalysis.json",
})

#: Build-gate records carried into the scratch dir (report.json's waivers are
#: read from them); they are measurements of the target, never re-derived.
CARRIED_RECORDS = ("pre_build_tests.json", "baseline_equivalence.json",
                   "authored_tests.json", "build_scope.json", "build_review.json")

#: Bookkeeping files outside the analysis (engine state, ledgers, logs).
IGNORED = frozenset({
    "state.json", "ledger.json", "best_found.json", "retry_log.jsonl",
    "llm_metrics.jsonl", "principles.json", "meta_findings.json",
})


class ReplayMismatch(RuntimeError):
    """The re-derived design asked for a row the original never measured."""


@dataclass
class Reanalysis:
    identical: bool
    differences: list[dict] = field(default_factory=list)
    input_changes: list[dict] = field(default_factory=list)
    replay_mismatches: list[str] = field(default_factory=list)
    compared: list[str] = field(default_factory=list)
    not_rederived: list[str] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    skipped_iterations: list[dict] = field(default_factory=list)
    nous_then: dict | None = None
    nous_now: dict | None = None
    scratch_dir: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class ReplayRunner:
    """``config_runner`` answering from one iteration's recorded rows."""

    def __init__(self, runs_path: Path):
        from orchestrator.optimize import artifacts

        self.by_index: dict[int, dict] = {}
        if runs_path.exists():
            for r in artifacts.read_runs(runs_path.parent):
                if isinstance(r.get("row_index"), int):
                    # The LAST record of a row index wins: that is the
                    # measurement the original fit read.
                    self.by_index[r["row_index"]] = r
        self.mismatches: list[str] = []
        self.where = runs_path

    def __call__(self, row) -> dict:
        from orchestrator.optimize.matrix import ConfigRow  # noqa: F401  (type only)

        rec = self.by_index.get(getattr(row, "row_index", None))
        if rec is None:
            msg = (f"{self.where}: the re-derived design asked for row "
                   f"{getattr(row, 'row_index', '?')} at {getattr(row, 'levels', {})}, "
                   f"which was never measured")
            self.mismatches.append(msg)
            raise ReplayMismatch(msg)
        if _norm(rec.get("levels")) != _norm(dict(getattr(row, "levels", {}) or {})):
            msg = (f"{self.where}: row {row.row_index} asked for {row.levels} but the "
                   f"recorded row measured {rec.get('levels')}")
            self.mismatches.append(msg)
            raise ReplayMismatch(msg)
        if rec.get("status") in ("failed", "timeout", "error") or not rec.get("response"):
            raise RuntimeError(f"replayed failure: {rec.get('error') or rec.get('status')}")
        return json.loads(json.dumps(rec["response"]))


def _norm(v):
    """JSON round-trip with numbers compared as floats (2 == 2.0)."""
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def _scrub(v, roots: list[str]):
    if isinstance(v, dict):
        return {k: _scrub(x, roots) for k, x in v.items() if k not in VOLATILE_KEYS}
    if isinstance(v, list):
        return [_scrub(x, roots) for x in v]
    if isinstance(v, str):
        for r in roots:
            v = v.replace(r, "<work_dir>")
        return v
    return v


def _load(path: Path, roots: list[str]):
    if path.suffix == ".jsonl":
        rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
        out = []
        for r in rows:
            r = _scrub(r, roots)
            if isinstance(r, dict) and r.get("status") in ("failed", "timeout"):
                r.pop("error", None)
                r.pop("failure_kind", None)
            out.append(r)
        return out
    if path.suffix == ".json":
        doc = _scrub(json.loads(path.read_text()), roots)
        if path.name == "report.json" and isinstance(doc, dict):
            # The version stamp is compared separately (format_result), and
            # the input hashes are checked against the ORIGINAL files by
            # check_inputs: re-derived runs.jsonl differ in volatile fields
            # (durations, attempts), so their bytes never hash alike.
            (doc.get("provenance") or {}).pop("nous", None)
            (doc.get("provenance") or {}).pop("inputs", None)
        return doc
    text = path.read_text()
    for r in roots:
        text = text.replace(r, "<work_dir>")
    if path.name == "report.md":
        # The Nous version line is a stamp, not an analysis result.
        text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("- **Nous:**"))
    return text


def _first_diff(a, b, path="") -> str:
    if type(a) is not type(b):
        return f"{path or '<root>'}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}.{k}: only in reanalysis"
            if k not in b:
                return f"{path}.{k}: only in original"
            if a[k] != b[k]:
                return _first_diff(a[k], b[k], f"{path}.{k}")
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path or '<root>'}: {len(a)} vs {len(b)} entries"
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _first_diff(x, y, f"{path}[{i}]")
    s1, s2 = repr(a), repr(b)
    return f"{path or '<root>'}: {s1[:120]} (original) vs {s2[:120]} (reanalysis)"


def _iter_numbers(work_dir: Path) -> list[int]:
    out = []
    for d in (work_dir / "runs").glob("iter-*"):
        try:
            out.append(int(d.name.split("-")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(out)


def _epoch_campaigns(work_dir: Path, fallback: dict | None
                     ) -> tuple[dict[int, dict], list[dict]]:
    """``({epoch: campaign}, problems)``. An epoch file that does not parse is
    a PROBLEM (recorded as a difference), never silently replaced by another
    epoch's campaign."""
    out, problems = {}, []
    for p in work_dir.glob("campaign.epoch-*.yaml"):
        try:
            e = int(p.stem.split("-")[-1])
        except ValueError:
            problems.append({"file": p.name, "difference": "epoch file name is not campaign.epoch-<int>.yaml"})
            continue
        try:
            doc = yaml.safe_load(p.read_text())
        except (OSError, yaml.YAMLError) as exc:
            problems.append({"file": p.name, "difference": f"registered campaign does not parse: {exc}"})
            continue
        if not isinstance(doc, dict):
            problems.append({"file": p.name, "difference": "registered campaign is not a mapping"})
            continue
        out[e] = doc
    if not out and not problems and fallback is not None:
        out[1] = fallback
    return out, problems


def _iteration_epochs(work_dir: Path, iters: list[int], n_epochs: int) -> dict[int, int]:
    """Which epoch each iteration belongs to: from transitions.jsonl; an
    iteration with no transition row (a pre-epoch stage) joins the epoch of
    the next iteration that has one."""
    known: dict[int, int] = {}
    t = work_dir / "transitions.jsonl"
    if t.exists():
        for ln in t.read_text().splitlines():
            if ln.strip():
                r = json.loads(ln)
                if isinstance(r.get("iteration"), int):
                    known[r["iteration"]] = int(r.get("epoch", 1))
    out, nxt = {}, n_epochs
    for i in reversed(iters):
        if i in known:
            nxt = known[i]
        out[i] = known.get(i, nxt)
    return out


def _test_results(iter_dir: Path) -> dict[str, bool] | None:
    p = iter_dir / "relations.json"
    if not p.exists():
        return None
    doc = json.loads(p.read_text())
    return {v["native_test"]: bool(v["passed"]) for v in doc.get("verdicts") or []}


def check_inputs(work_dir: Path) -> list[dict]:
    """Input files whose bytes no longer match the hashes report.json recorded."""
    from orchestrator.optimize.provenance import input_hashes

    rep = work_dir / "report.json"
    if not rep.exists():
        return [{"file": "report.json", "change": "absent: inputs_unchecked (no recorded "
                 "hashes to compare the rows against)"}]
    recorded = ((json.loads(rep.read_text()).get("provenance") or {}).get("inputs")) or {}
    if not recorded:
        return [{"file": "report.json", "change": "no provenance.inputs recorded "
                 "(written by a Nous older than the provenance block)"}]
    now = input_hashes(work_dir)
    out = []
    for rel in sorted(set(recorded) | set(now)):
        if rel not in now:
            out.append({"file": rel, "change": "missing now"})
        elif rel not in recorded:
            out.append({"file": rel, "change": "added after the report was written"})
        elif recorded[rel] != now[rel]:
            out.append({"file": rel, "change": "content changed after the report was written"})
    return out


def _skip_pre_epoch(engine, work_dir: Path, iteration: int) -> None:
    from orchestrator.iteration import _enter_phase

    for ph in ("DESIGN", "HUMAN_DESIGN_GATE", "EXECUTE_ANALYZE", "HUMAN_FINDINGS_GATE"):
        _enter_phase(engine, ph, work_dir)


def reanalyze(work_dir: Path, *, campaign: dict | None = None,
              keep: bool = False) -> Reanalysis:
    """Re-derive ``work_dir``'s analysis from its rows and diff it."""
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize import policy as policy_mod
    from orchestrator.optimize.provenance import nous_version_info
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage

    orig = Path(work_dir).resolve()
    result = Reanalysis(identical=False)
    result.input_changes = check_inputs(orig)
    try:
        result.nous_then = ((json.loads((orig / "report.json").read_text())
                             .get("provenance") or {}).get("nous"))
    except (OSError, ValueError):
        result.nous_then = None
    result.nous_now = nous_version_info()

    campaigns, problems = _epoch_campaigns(orig, campaign)
    if problems:
        result.differences.extend(problems)
        result.identical = False
        return result
    if not campaigns:
        raise ValueError(f"{orig} has no campaign.epoch-*.yaml and no campaign was given")
    iters = _iter_numbers(orig)
    epoch_of = _iteration_epochs(orig, iters, max(campaigns))
    run_id = (campaigns[min(campaigns)] or {}).get("run_id") or orig.name

    parent = Path(tempfile.mkdtemp(prefix="nous-reanalyze-"))
    prior = os.environ.get("NOUS_CAMPAIGN_PARENT")
    os.environ["NOUS_CAMPAIGN_PARENT"] = str(parent)
    replays: list[ReplayRunner] = []
    try:
        def _detached(c: dict) -> dict:
            c = json.loads(json.dumps(c))
            c.setdefault("target_system", {})["repo_path"] = None
            return c

        new = setup_work_dir(run_id, repo_path=None,
                             campaign=_detached(campaigns[min(campaigns)]))
        # build_review.json is a record of a human decision that report.json's
        # provenance.waivers reads; it is carried, not re-derived.
        for name in ("mechanism.sha256", "mechanism.patch", *CARRIED_RECORDS):
            if (orig / name).exists():
                shutil.copy2(orig / name, new / name)
        last = iters[-1] if iters else 0
        for i in iters:
            e = epoch_of.get(i, max(campaigns))
            c = _detached(campaigns.get(e) or campaigns[max(k for k in campaigns if k <= e)])
            pre = policy_mod.pre_epoch_stages(c)
            engine = Engine(new)
            if i <= len(pre) and pre[i - 1] in ("plan", "build") and e == min(campaigns):
                _skip_pre_epoch(engine, new, i)
                result.skipped_iterations.append(
                    {"iteration": i, "stage": pre[i - 1],
                     "why": "agent call; its oracles are measurements of the target tree"})
            else:
                rr = ReplayRunner(orig / "runs" / f"iter-{i}" / "runs.jsonl")
                replays.append(rr)
                try:
                    out = run_stage(c, new, iteration=i, config_runner=rr,
                                    test_results=_test_results(orig / "runs" / f"iter-{i}"),
                                    auto_approve=True, reanalysis=True)
                except OptimizationAborted as exc:
                    result.differences.append(
                        {"file": f"runs/iter-{i}", "difference": f"reanalysis aborted: {exc}"})
                    break
                if out == IterationOutcome.COMPLETED and i == last:
                    break
            engine = Engine(new)
            if engine.phase != "DONE":
                engine.transition("DONE")
            engine.transition("DESIGN")

        if (orig / "report.md").exists() and (new / "report.json").exists():
            from orchestrator.optimize.report_md import write_report_markdown

            write_report_markdown(new)
        result.replay_mismatches = [m for r in replays for m in r.mismatches]

        roots = [str(orig), str(new), str(Path(work_dir))]

        def _files(root: Path, excluded: list | None = None) -> set[str]:
            out = set()
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(root).as_posix()
                why = None
                if ".claude" in p.parts or p.name == "CLAUDE.md":
                    why = "session configuration"
                elif p.suffix not in (".json", ".jsonl", ".sha256", ".md", ".patch"):
                    why = f"not an analysis artifact type ({p.suffix or 'no suffix'})"
                elif p.name in IGNORED:
                    why = "bookkeeping, outside the analysis"
                elif "failed_runs" in p.parts or p.name in ("build_summary.md",):
                    why = "a measurement or agent log"
                elif p.name.startswith("gate_summary") or p.name in (
                        "halt.json", "halt_history.jsonl", "progress.json"):
                    why = "written by the campaign loop, not by the stage runner"
                if why:
                    if excluded is not None:
                        excluded.append({"file": rel, "why": why})
                    continue
                out.add(rel)
            return out

        a, b = _files(orig, result.excluded), _files(new)
        for rel in sorted(a | b):
            name = rel.rsplit("/", 1)[-1]
            if name in NOT_DERIVED:
                result.not_rederived.append(rel)
                continue
            if rel not in b:
                if name in NOT_DERIVED:
                    result.not_rederived.append(rel)
                else:
                    result.differences.append({"file": rel, "difference": "not re-derived"})
                continue
            if rel not in a:
                result.differences.append({"file": rel, "difference": "only in reanalysis"})
                continue
            result.compared.append(rel)
            x, y = _load(orig / rel, roots), _load(new / rel, roots)
            if x != y:
                result.differences.append({"file": rel, "difference": _first_diff(x, y)})
        result.identical = not (result.differences or result.input_changes
                                or result.replay_mismatches)
        if keep:
            result.scratch_dir = str(new)
    finally:
        if prior is None:
            os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        else:
            os.environ["NOUS_CAMPAIGN_PARENT"] = prior
        if not keep:
            shutil.rmtree(parent, ignore_errors=True)
    return result


def format_result(r: Reanalysis) -> str:
    lines = [("ANALYSIS RE-DERIVED: every re-derived artifact matches the recorded one "
              "(the measurements themselves were not re-run)."
              if r.identical else "ANALYSIS NOT RE-DERIVED IDENTICALLY: differences below."),
             f"  compared {len(r.compared)} derived artifact(s)"]
    if r.excluded:
        lines.append(f"  excluded from the comparison: {len(r.excluded)} file(s): "
                     + ", ".join(f"{e['file']} ({e['why']})" for e in r.excluded[:12])
                     + (" ..." if len(r.excluded) > 12 else ""))
    then, now = r.nous_then or {}, r.nous_now or {}
    if then:
        same = then.get("source_sha256") == now.get("source_sha256")
        lines.append(f"  code: recorded {then.get('package_version')} "
                     f"{(then.get('source_sha256') or '')[:12]}, now "
                     f"{now.get('package_version')} {(now.get('source_sha256') or '')[:12]}"
                     + ("" if same else "  (DIFFERENT CODE)"))
    for s in r.skipped_iterations:
        lines.append(f"  iteration {s['iteration']} ({s['stage']}) not re-run: {s['why']}")
    if r.not_rederived:
        lines.append("  not re-derived (measurements or agent output): "
                     + ", ".join(r.not_rederived))
    for c in r.input_changes:
        lines.append(f"  INPUT {c['file']}: {c['change']}")
    for m in r.replay_mismatches:
        lines.append(f"  REPLAY MISMATCH {m}")
    for d in r.differences:
        lines.append(f"  DIFF {d['file']}: {d['difference']}")
    if r.scratch_dir:
        lines.append(f"  re-derived work_dir kept at {r.scratch_dir}")
    return "\n".join(lines)
