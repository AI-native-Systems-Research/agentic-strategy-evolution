"""What a ``report.json`` rests on, recorded so a third party can re-derive it.

Two blocks, both pure reads of the work_dir and the running code:

``provenance`` (audit Q7)
    * ``nous`` -- the package version, the git commit (read from .git, no
      subprocess) and a sha256 over the package source, so uncommitted edits
      are visible too;
    * ``inputs`` -- the sha256 of every ``runs/iter-*/runs.jsonl`` and
      ``design_matrix.json`` on disk when the report was written, so a
      changed row is detectable without trusting the writer;
    * ``policy_hash`` -- the pre-registration (``policy.sha256``);
    * ``analysis_constants`` -- the module-level numbers and switches that
      change the analysis without changing the policy hash (candidate cap,
      search sample and restarts, the alphas, the stage_runner/policy
      feature switches). They are READ from the live modules rather than
      copied here, so the record cannot drift from the code it describes.

``error_budget`` (audit Q7 forking paths)
    Each compiled epoch spends ``delta_screen + delta_terminal``, and every
    epoch after the first is compiled AFTER the earlier epochs' data were
    seen. The figure a reader needs is therefore the union (Bonferroni) bound
    over every epoch on this work_dir, not this epoch's sum. This module only
    RECORDS that figure; it does not change what ``certified`` means.

Hashes are of the bytes on disk. ``nous reanalyze`` (``reanalyze.py``)
compares them against the files it re-reads before trusting anything else.
"""
from __future__ import annotations

import hashlib
import functools
import inspect
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_dir(root: Path) -> Path | None:
    g = root / ".git"
    if g.is_dir():
        return g
    if g.is_file():  # a worktree: "gitdir: <path>"
        txt = g.read_text().strip()
        if txt.startswith("gitdir:"):
            p = Path(txt.split(":", 1)[1].strip())
            return p if p.is_absolute() else (root / p).resolve()
    return None


def _read_git_head(root: Path) -> str | None:
    """HEAD's commit, read from the git files directly -- no subprocess, so the
    zero-subprocess synthetic harness stays zero-subprocess."""
    try:
        gd = _git_dir(root)
        if gd is None:
            return None
        head = (gd / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head.split(":", 1)[1].strip()
        common = gd
        if (gd / "commondir").exists():
            common = (gd / (gd / "commondir").read_text().strip()).resolve()
        for base in (gd, common):
            if (base / ref).exists():
                return (base / ref).read_text().strip() or None
        packed = common / "packed-refs"
        if packed.exists():
            for line in packed.read_text().splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0]
    except OSError:
        return None
    return None


#: What ``source_sha256`` covers, stated in the record itself.
SOURCE_SCOPE = ("orchestrator/**/*.py, orchestrator/**/*.json, orchestrator/**/*.yaml "
                "(code, schemas, templates, defaults) and prompts/**/*.md when present")


@functools.lru_cache(maxsize=1)
def _source_digest(pkg_root: str) -> str:
    """sha256 over the files ``SOURCE_SCOPE`` names (path + bytes): identifies
    the exact analysis code even when the checkout is dirty or not git."""
    h = hashlib.sha256()
    root = Path(pkg_root)
    files = [p for pat in ("*.py", "*.json", "*.yaml") for p in root.rglob(pat)]
    prompts = root.parent / "prompts"
    if prompts.is_dir():
        files += list(prompts.rglob("*.md"))
    for p in sorted(set(files)):
        if "__pycache__" in p.parts:
            continue
        h.update(p.relative_to(root.parent).as_posix().encode() + b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()


def runtime_versions() -> dict:
    """Interpreter and numerical-library versions the analysis ran under
    (read from package metadata; nothing is imported)."""
    import importlib.metadata as md
    import platform

    out = {"python": platform.python_version()}
    for pkg in ("scipy", "numpy", "jsonschema", "pyyaml"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    return out


def nous_version_info() -> dict:
    """``{"package_version", "git_commit", "source_sha256", "source_scope"}``.
    ``git_commit`` is None for an installed wheel; ``source_sha256`` identifies
    the code that ran (uncommitted edits included) over ``source_scope``."""
    import importlib.metadata as md

    try:
        version = md.version("nous")
    except md.PackageNotFoundError:
        version = None
    pkg = Path(__file__).resolve().parents[1]
    return {"package_version": version,
            "git_commit": _read_git_head(pkg.parent),
            "source_sha256": _source_digest(str(pkg)),
            "source_scope": SOURCE_SCOPE}


def analysis_constants() -> dict:
    """The analysis switches and constants outside the policy hash, read live."""
    from orchestrator.optimize import (
        constraint_models,
        decide,
        design,
        effects,
        exclusions,
        pareto,
        pareto_stage,
        policy,
        stage,
        stage_runner,
    )

    def _default(fn, name):
        try:
            return inspect.signature(fn).parameters[name].default
        except (KeyError, TypeError, ValueError):
            return None

    def _get(mod, name):
        return getattr(mod, name, None)

    return {
        "decide.CANDIDATE_CAP": _get(decide, "CANDIDATE_CAP"),
        "decide.SEARCH_SAMPLE": _get(decide, "SEARCH_SAMPLE"),
        "decide.SEARCH_SEED": _get(decide, "SEARCH_SEED"),
        "decide.SEARCH_STARTS": _get(decide, "SEARCH_STARTS"),
        "decide.SEARCH_STARTS_WEIGHTED": _get(decide, "SEARCH_STARTS_WEIGHTED"),
        "design._RESTARTS": _get(design, "_RESTARTS"),
        "effects.fit_effects.alpha": _default(effects.fit_effects, "alpha"),
        "stage._LOF_ALPHA": _get(stage, "_LOF_ALPHA"),
        "constraint_models.LACK_OF_FIT_ALPHA": _get(constraint_models, "LACK_OF_FIT_ALPHA"),
        "pareto.LACK_OF_FIT_ALPHA": _get(pareto, "LACK_OF_FIT_ALPHA"),
        "pareto.HV_MC_SAMPLES": _get(pareto, "HV_MC_SAMPLES"),
        "pareto.HV_MC_SEED": _get(pareto, "HV_MC_SEED"),
        "exclusions.MIN_ROWS_AT_LEVEL": _get(exclusions, "MIN_ROWS_AT_LEVEL"),
        "stage_runner._MODEL_CONSTRAINTS": _get(stage_runner, "_MODEL_CONSTRAINTS"),
        "stage_runner._SUPPORTED_FEASIBLE_SEAT": _get(stage_runner, "_SUPPORTED_FEASIBLE_SEAT"),
        "stage_runner._INFEASIBLE_FINALIST_CAVEAT": _get(stage_runner, "_INFEASIBLE_FINALIST_CAVEAT"),
        "stage_runner._REFILL_POOL": _get(stage_runner, "_REFILL_POOL"),
        "stage_runner.DEFAULT_BASELINE_TOLERANCE_PCT": _get(stage_runner, "DEFAULT_BASELINE_TOLERANCE_PCT"),
        "stage_runner.DEFAULT_BASELINE_REPLICATES": _get(stage_runner, "DEFAULT_BASELINE_REPLICATES"),
        "policy._REFILL_VACATED": _get(policy, "_REFILL_VACATED"),
        "pareto_stage._FRONT_GAP_FILL": _get(pareto_stage, "_FRONT_GAP_FILL"),
    }


#: The per-iteration inputs every fitted artifact is derived from: the rows,
#: the registered design, and the test verdicts verify reconciled.
INPUT_FILES = ("runs.jsonl", "design_matrix.json", "relations.json")


def input_hashes(work_dir: Path) -> dict[str, str]:
    """``{"runs/iter-N/<file>": sha256}`` for every input file on disk, in
    numeric iteration order."""
    runs = Path(work_dir) / "runs"
    out: dict[str, str] = {}
    if not runs.exists():
        return out
    dirs = sorted((d for d in runs.iterdir() if d.is_dir() and d.name.startswith("iter-")),
                  key=lambda d: int(d.name.split("-")[1]) if d.name.split("-")[1].isdigit() else 0)
    for d in dirs:
        for name in INPUT_FILES:
            p = d / name
            if p.exists():
                out[f"runs/{d.name}/{name}"] = sha256_file(p)
    # The campaign each epoch registered: the analysis is a function of it too.
    for p in sorted(Path(work_dir).glob("campaign.epoch-*.yaml")):
        out[p.name] = sha256_file(p)
    return out


def waivers(work_dir: Path, campaign: dict | None) -> list[dict]:
    """Every gate that did not run as a full check, read FROM THE GATE
    ARTIFACTS the oracles wrote (what was actually waived, skipped or left
    unclassified), with the campaign's waiver keys used only as a cross-check.
    A build record that is missing or unreadable is itself an entry: a record
    must never claim more than was checked."""
    import json

    wd = Path(work_dir)
    out: list[dict] = []
    opt = ((campaign or {}).get("optimization") or {}) if isinstance(campaign, dict) else {}
    bc = opt.get("build_checks") if isinstance(opt.get("build_checks"), dict) else {}

    def _read(name):
        p = wd / name
        if not p.exists():
            return None, "missing"
        try:
            return json.loads(p.read_text()), None
        except (OSError, ValueError):
            return None, "unreadable"

    try:
        from orchestrator.optimize.build_scope import build_declared

        built = build_declared(campaign or {}) or (wd / "pre_build_tests.json").exists()
    except Exception:  # noqa: BLE001 -- a malformed campaign is not a build
        built = (wd / "pre_build_tests.json").exists()
    if built:
        for name, gate in (("baseline_equivalence.json", "oracle_2c_baseline"),
                           ("authored_tests.json", "oracle_2d_authored_tests"),
                           ("build_scope.json", "build_write_scope"),
                           ("build_review.json", "build_review")):
            doc, problem = _read(name)
            if problem:
                out.append({"gate": gate, "reason": f"record {problem}",
                            "note": f"{name} is {problem}; the gate's outcome is not on record"})
                continue
            if doc.get("waived"):
                out.append({"gate": gate, "reason": str(doc["waived"]),
                            "note": "waived by the campaign"
                                    + ("" if any(bc.get(k) == doc["waived"] for k in WAIVER_KEYS)
                                       else " (the waiver is not in this campaign's build_checks)")})
        be, _ = _read("baseline_equivalence.json")
        if be and be.get("armed") is False and not be.get("waived"):
            out.append({"gate": "oracle_2c_baseline", "reason": "not armed",
                        "note": str(be.get("unarmed_because") or be.get("pre_unavailable"))})
        at, _ = _read("authored_tests.json")
        for t, e in sorted(((at or {}).get("tests") or {}).items()):
            ev = (e or {}).get("evidence")
            if ev in ("pre_build_failure_unclassified", "declared_preexisting_behaviour"):
                out.append({"gate": "oracle_2d_authored_tests", "reason": ev, "note": t})
        if (at or {}).get("mutant", {}).get("unavailable"):
            out.append({"gate": "oracle_2d_authored_tests", "reason": "mutant unavailable",
                        "note": str(at["mutant"]["unavailable"])})
        sc, _ = _read("build_scope.json")
        if sc and sc.get("applicable") is False:
            out.append({"gate": "build_write_scope", "reason": "not applicable",
                        "note": str(sc.get("why_not") or "no diff to check")})
        rv, _ = _read("build_review.json")
        if rv and rv.get("auto"):
            out.append({"gate": "build_review", "reason": "auto-approved",
                        "note": "no human reviewed the built mechanism"})
        if bc.get("allow_preexisting_tests") is True:
            out.append({"gate": "oracle_2b_preexisting_tests",
                        "reason": "build_checks.allow_preexisting_tests: true",
                        "note": "tests that passed before the build were accepted"})
    unverified = opt.get("unverified_locks")
    if isinstance(unverified, dict):
        for k, reason in sorted(unverified.items()):
            out.append({"gate": f"locked_parameters.{k}", "reason": str(reason),
                        "note": "lock declared but NOT verified at run time"})
    return out


#: ``build_checks`` keys whose (non-empty string) value waives a hard gate.
WAIVER_KEYS = ("allow_unarmed_baseline", "allow_nondiscriminating_tests",
               "allow_out_of_scope_writes")


def build_provenance(work_dir: Path, policy_hash: str, *, campaign: dict | None = None) -> dict:
    return {
        "nous": nous_version_info(),
        "runtime": runtime_versions(),
        "policy_hash": policy_hash,
        "inputs": input_hashes(work_dir),
        "analysis_constants": analysis_constants(),
        "waivers": waivers(work_dir, campaign),
    }


def _epoch_deltas(work_dir: Path, epoch: int, current_policy: dict) -> tuple[float, float] | None:
    """``(delta_screen, delta_terminal)`` epoch ``epoch`` was compiled with.

    The current epoch's come from its policy. An earlier epoch's policy.json
    has been overwritten by the recompile, so its deltas are recovered by
    recompiling the campaign that epoch registered (``campaign.epoch-<e>.yaml``,
    written beside every compile). Recompiling is a pure function of that file.
    """
    if epoch == int(current_policy.get("epoch", 1)):
        o = current_policy["objective"]
        return float(o["delta_screen"]), float(o["delta_terminal"])
    p = Path(work_dir) / f"campaign.epoch-{epoch}.yaml"
    if not p.exists():
        return None
    try:
        import yaml

        from orchestrator.optimize.policy import compile_policy

        pol = compile_policy(yaml.safe_load(p.read_text()), epoch=epoch)
        o = pol["objective"]
        return float(o["delta_screen"]), float(o["delta_terminal"])
    except Exception as exc:  # noqa: BLE001 -- recorded, not hidden
        logger.warning("could not recover epoch %d's deltas from %s: %s", epoch, p.name, exc)
        return None


def error_budget(work_dir: Path, pol: dict) -> dict:
    """The cumulative (union-bound) error budget over every epoch so far."""
    current = int(pol.get("epoch", 1))
    epochs, total, unknown = [], 0.0, []
    for e in range(1, current + 1):
        d = _epoch_deltas(work_dir, e, pol)
        if d is None:
            unknown.append(e)
            epochs.append({"epoch": e, "delta_screen": None, "delta_terminal": None,
                           "spent": None})
            continue
        spent = d[0] + d[1]
        total += spent
        epochs.append({"epoch": e, "delta_screen": d[0], "delta_terminal": d[1],
                       "spent": spent,
                       "compiled_after_data": e > 1,
                       # An earlier epoch's policy.json was overwritten by the
                       # recompile, so its deltas are re-derived from its
                       # registered campaign by the compile_policy of the Nous
                       # writing THIS report, not the one that ran that epoch.
                       "deltas_from": ("this epoch's policy.json" if e == current
                                       else f"campaign.epoch-{e}.yaml recompiled by "
                                            f"the current Nous")})
    return {
        "epochs": epochs,
        "this_epoch": epochs[-1]["spent"] if epochs else None,
        "cumulative": total,
        # A lower bound when an earlier epoch's deltas could not be recovered.
        "cumulative_is_lower_bound": bool(unknown),
        "unrecovered_epochs": unknown,
        "accounting": ("union (Bonferroni) bound over epochs: each epoch spends "
                       "delta_screen + delta_terminal, and epochs after the first "
                       "were compiled after earlier epochs' data were seen, so the "
                       "family-wise probability that ANY epoch's decision is wrong "
                       "is at most the sum. Certification is still judged per "
                       "epoch at that epoch's deltas; this figure is informational."),
    }
