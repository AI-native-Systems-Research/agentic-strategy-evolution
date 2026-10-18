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

import json

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
        certificate,
        constraint_models,
        decide,
        design,
        effects,
        exclusions,
        noise,
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
        "certificate.REGION_NODE_BUDGET": _get(certificate, "REGION_NODE_BUDGET"),
        "certificate.REGION_WORK_BUDGET": _get(certificate, "REGION_WORK_BUDGET"),
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
        "noise.SKEW_NULL_DRAWS": _get(noise, "SKEW_NULL_DRAWS"),
        "noise.SKEW_NULL_SEED": _get(noise, "SKEW_NULL_SEED"),
        "noise.BOOT_RESAMPLES": _get(noise, "BOOT_RESAMPLES"),
        "noise.BOOT_SEED": _get(noise, "BOOT_SEED"),
        "noise.SIGN_FLIP_MC_SEED": _get(noise, "SIGN_FLIP_MC_SEED"),
        "noise.SIGN_FLIP_MC_DRAWS": _get(noise, "SIGN_FLIP_MC_DRAWS"),
        "noise.SIGN_FLIP_EXACT_MAX_N": _get(noise, "SIGN_FLIP_EXACT_MAX_N"),
    }


def _allocate_constants(work_dir: Path) -> dict:
    """WP-D D1: the allocator's constants, recorded only when the epoch's
    policy registers the opt-in allocate branch (so every other report is
    byte-identical). Selection only; no bound reads them."""
    from orchestrator.optimize import allocate_seat
    from orchestrator.optimize.policy import read_policy

    pol = read_policy(Path(work_dir))
    return allocate_seat.constants() if pol and allocate_seat.seats_declared(pol) else {}


#: The per-iteration inputs every fitted artifact is derived from: the rows,
#: the registered design, and the test verdicts verify reconciled; and, only
#: when the opt-in allocate branch wrote one, the seats round r registered for
#: round r+1 (``allocation.json``, WP-D D1 / P6b review H1).
INPUT_FILES = ("runs.jsonl", "design_matrix.json", "relations.json", "allocation.json")


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
    # Held-out-seed rows (#321): measured after the decisions, before report.json.
    for p in sorted(Path(work_dir).glob("held_out_seeds.epoch-*.jsonl")):
        out[p.name] = sha256_file(p)
    # WP-D D2: an accepted plan-next boundary (an override's reason lives here).
    for p in sorted(Path(work_dir).glob("epoch_end.planned-*.json")):
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

    from orchestrator.optimize.build_scope import build_declared

    try:
        built = build_declared(campaign or {}) or (wd / "pre_build_tests.json").exists()
    except (TypeError, ValueError, AttributeError):
        # A campaign that cannot be read cannot rule a build out: assume one ran,
        # so every missing record is listed rather than silently omitted (C7).
        built = True
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
        from orchestrator.optimize import gate_records as _gr

        for name in (*_gr.BUILD_RECORDS, *_gr.VERIFY_RECORDS, *_gr.TREE_RECORDS):
            st = _gr.check(wd, name)
            if st not in ("ok", "absent"):
                out.append({"gate": "gate_record_seal", "reason": f"{name} seal {st}",
                            "note": "the record cannot be shown to be what Nous wrote"})
        be, _ = _read("baseline_equivalence.json")
        if be and be.get("armed") is False and not be.get("waived"):
            out.append({"gate": "oracle_2c_baseline", "reason": "not armed",
                        "note": str(be.get("unarmed_because") or be.get("pre_unavailable"))})
        at, _ = _read("authored_tests.json")
        for t, e in sorted(((at or {}).get("tests") or {}).items()):
            ev = (e or {}).get("evidence")
            if ev in ("pre_build_failure_unclassified", "declared_preexisting_behaviour"):
                out.append({"gate": "oracle_2d_authored_tests", "reason": ev, "note": t})
        pr, _ = _read("clean_tree.probe.json")
        for np_ in (pr or {}).get("not_probed") or []:
            out.append({"gate": "clean_tree_import_probe", "reason": "not probed",
                        "note": f"{np_.get('command', '')[:60]}: {np_.get('reason')}"})
        sm = ((at or {}).get("mutant") or {}).get("stub_mutant")
        if at is not None and (not sm or not sm.get("ran")):
            out.append({"gate": "oracle_2d_stub_mutant", "reason": "not run",
                        "note": str((sm or {}).get("skipped_because") or "not recorded")})
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


def model_record(work_dir: Path) -> dict:
    """Which model authored what (audit Q10): the kind's configured default,
    and for every plan/build attempt in ``llm_metrics.jsonl`` the ID REQUESTED
    and the ID the SDK reported SERVING it (``model_resolved``; None when the
    SDK reported none, e.g. a row written by an older Nous).

    ``OPTIMIZATION_MODEL`` is an ALIAS. No dated snapshot of it could be
    verified when this was written, so none is pinned (inventing one would
    make every build call fail, or worse, silently resolve elsewhere); the
    resolved ID per call is the record of what actually ran. ``snapshot_pinned``
    says which of the two situations a report is in."""
    import json

    from orchestrator.campaign import OPTIMIZATION_MODEL

    calls: list[dict] = []
    p = Path(work_dir) / "llm_metrics.jsonl"
    if p.exists():
        for ln in p.read_text().splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("phase") in ("plan", "build") and r.get("model"):
                calls.append({"phase": r["phase"], "requested": r["model"],
                              "resolved": r.get("model_resolved")})
    return {
        "configured_default": OPTIMIZATION_MODEL,
        "snapshot_pinned": False,
        "pin_note": ("the configured default is an alias with no verifiable dated "
                     "snapshot; each call's resolved ID is recorded instead"),
        "calls": calls,
    }


def manipulation_evidence(campaign: dict | None) -> list[dict]:
    """Per factor: does its manipulation predicate read a TARGET-emitted field
    or only Nous's echo of what it set (``applied.*``)? Echo-only means the
    check shows the lever was SENT, never that it was RECEIVED (#321)."""
    from orchestrator.optimize.factors import manipulation_evidence as _ev

    opt = ((campaign or {}).get("optimization") or {}) if isinstance(campaign, dict) else {}
    out = []
    for f in opt.get("factors") or []:
        if not isinstance(f, dict):
            continue
        man = f.get("manipulation") or {}
        out.append({"factor": str(f.get("id")),
                    "observable": man.get("observable") or man.get("metric"),
                    "evidence": _ev(man),
                    "required": man.get("evidence") or "any"})
    return out


def build_provenance(work_dir: Path, policy_hash: str, *, campaign: dict | None = None) -> dict:
    out = {
        "nous": nous_version_info(),
        "runtime": runtime_versions(),
        "policy_hash": policy_hash,
        "inputs": input_hashes(work_dir),
        "analysis_constants": {**analysis_constants(), **_allocate_constants(work_dir)},
        "waivers": waivers(work_dir, campaign),
        "model": model_record(work_dir),
        "manipulation_evidence": manipulation_evidence(campaign),
    }
    # WP-D D2 (#320): an epoch started by an accepted `nous plan-next`
    # decision records what was chosen, the scored choice, and any override
    # with its reason. Present only then, so other reports are byte-identical.
    planned = _planner_provenance(work_dir)
    if planned is not None:
        out["planner"] = planned
    return out


def planned_boundary_path(work_dir: Path, epoch: int) -> Path:
    """``epoch_end.planned-<e>.json``: an accepted ``nous plan-next`` decision
    ending epoch ``e`` (WP-D D2). Counted by ``stage_runner._epoch_index`` like
    every ``epoch_end*.json``; NOT ``epoch_end-<e>.json`` (a semantic exception)."""
    return Path(work_dir) / f"epoch_end.planned-{epoch}.json"


def _planner_provenance(work_dir: Path) -> dict | None:
    """``report.json`` ``provenance.planner`` for an epoch that an accepted
    plan-next decision started: the choice, the scored choice, the basis, any
    override with its reason, and whether the compiled campaign is the accepted
    proposal. A read of a JSON record only: the report path never imports the
    planner (tests/test_optimize_bo_proposer.py enforces it)."""
    from orchestrator.optimize.policy import read_policy

    pol = read_policy(Path(work_dir))
    if pol is None or int(pol.get("epoch", 1)) < 2:
        return None
    e = int(pol["epoch"])
    p = planned_boundary_path(work_dir, e - 1)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text())
    except ValueError as exc:
        return {"record": p.name, "chosen": None, "unreadable": str(exc)}
    compiled = (pol.get("compiled_from") or {}).get("campaign_hash")
    return {"record": p.name, "planned_in_epoch": e - 1, "chosen": rec.get("chosen"),
            "scored_choice": rec.get("scored_choice"),
            "decision_basis": rec.get("decision_basis"), "override": rec.get("override"),
            "decision": rec.get("decision"), "decision_sha256": rec.get("decision_sha256"),
            "compiled_matches_accepted": (compiled == rec.get("proposed_campaign_hash")
                                          if rec.get("proposed_campaign_hash") else None)}


def _epoch_deltas(work_dir: Path, epoch: int, current_policy: dict) -> tuple[float, ...] | None:
    """``(delta_screen, delta_terminal, delta_constraint, delta_feasibility)``
    epoch ``epoch`` was compiled with (absent terms are 0).

    The current epoch's come from its policy. An earlier epoch's policy.json
    has been overwritten by the recompile, so its deltas are recovered by
    recompiling the campaign that epoch registered (``campaign.epoch-<e>.yaml``,
    written beside every compile). Recompiling is a pure function of that file.
    """
    if epoch == int(current_policy.get("epoch", 1)):
        o = current_policy["objective"]
        return (float(o["delta_screen"]), float(o["delta_terminal"]),
                float(o.get("delta_constraint") or 0.0),
                float(o.get("delta_feasibility") or 0.0))
    p = Path(work_dir) / f"campaign.epoch-{epoch}.yaml"
    if not p.exists():
        return None
    try:
        import yaml

        from orchestrator.optimize.policy import compile_policy

        pol = compile_policy(yaml.safe_load(p.read_text()), epoch=epoch)
        o = pol["objective"]
        return (float(o["delta_screen"]), float(o["delta_terminal"]),
                float(o.get("delta_constraint") or 0.0),
                float(o.get("delta_feasibility") or 0.0))
    except Exception as exc:  # noqa: BLE001 -- recorded, not hidden
        logger.warning("could not recover epoch %d's deltas from %s: %s", epoch, p.name, exc)
        return None


def record_continue_gate_stop(work_dir: Path, *, iteration: int) -> None:
    """Append the stop to ``delta_ledger.jsonl`` with the epoch's share (#321
    item 7). The share stays spent; the row only makes the stop visible in
    ``error_budget``. A no-op without a compiled policy."""
    from orchestrator.optimize.policy import delta_stated, read_policy

    pol = read_policy(Path(work_dir))
    if pol is None:
        return
    row = {"event": "stopped_at_continue_gate", "iteration": int(iteration),
           "epoch": int(pol.get("epoch", 1)), "charged": delta_stated(pol)}
    with (Path(work_dir) / "delta_ledger.jsonl").open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _declared_campaign_totals(work_dir: Path, current: int, cd: dict | None) -> dict:
    """``{epoch: total}`` for every epoch that declared ``campaign_delta``,
    read from the campaigns each epoch registered (declarations, not data)."""
    out: dict[int, float] = {}
    for e in range(1, current):
        p = Path(work_dir) / f"campaign.epoch-{e}.yaml"
        if not p.exists():
            continue
        try:
            import yaml

            c = yaml.safe_load(p.read_text()) or {}
            spec = (((c.get("optimization") or {}).get("policy") or {})
                    .get("campaign_delta"))
            if spec and spec.get("total") is not None:
                out[e] = float(spec["total"])
        except Exception as exc:  # noqa: BLE001 -- recorded, not hidden
            logger.warning("could not read epoch %d's campaign_delta from %s: %s",
                           e, p.name, exc)
    if cd and cd.get("total") is not None:
        out[current] = float(cd["total"])
    return out


def campaign_delta_exceeded(work_dir: Path, pol: dict) -> bool:
    """True when a charged campaign-wide budget is declared and the cumulative
    spend exceeds it: the epoch then certifies nothing (P2 review M2)."""
    eb = error_budget(work_dir, pol)
    return eb.get("mode") == "charged" and not eb.get("within_total", True)


def error_budget(work_dir: Path, pol: dict) -> dict:
    """The cumulative (union-bound) error budget over every epoch so far."""
    current = int(pol.get("epoch", 1))
    epochs, total, unknown = [], 0.0, []
    for e in range(1, current + 1):
        d = _epoch_deltas(work_dir, e, pol)
        if d is None:
            unknown.append(e)
            epochs.append({"epoch": e, "delta_screen": None, "delta_terminal": None,
                           "delta_constraint": None, "spent": None})
            continue
        spent = d[0] + d[1] + d[2] + d[3]
        total += spent
        epochs.append({"epoch": e, "delta_screen": d[0], "delta_terminal": d[1],
                       "delta_constraint": d[2],
                       **({"delta_feasibility": d[3]} if d[3] else {}),
                       "spent": spent,
                       "compiled_after_data": e > 1,
                       # An earlier epoch's policy.json was overwritten by the
                       # recompile, so its deltas are re-derived from its
                       # registered campaign by the compile_policy of the Nous
                       # writing THIS report, not the one that ran that epoch.
                       "deltas_from": ("this epoch's policy.json" if e == current
                                       else f"campaign.epoch-{e}.yaml recompiled by "
                                            f"the current Nous")})
    cd = (pol.get("objective") or {}).get("campaign_delta")
    declared = _declared_campaign_totals(work_dir, current, cd)
    charged = {}
    if declared:
        # P2 review M2: the mode, once declared in ANY epoch, stays charged,
        # and binds at the SMALLEST total ever declared -- a later epoch
        # cannot raise it or drop the block to escape it.
        binding_total = min(declared.values())
        # #321 item 7: the CHARGED mode. Each epoch's share is spent when the
        # epoch is compiled (pre-registered), whatever happens after: an epoch
        # that certified, ended on an exception, or was STOPPED at a continue
        # gate (recorded in delta_ledger.jsonl) is charged the same share.
        stops = []
        led = Path(work_dir) / "delta_ledger.jsonl"
        if led.exists():
            for ln in led.read_text().splitlines():
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if row.get("event") == "stopped_at_continue_gate":
                    stops.append(row)
        charged = {"mode": "charged", "binding": True,
                   "campaign_total": binding_total,
                   "declared_totals": {str(k): v for k, v in sorted(declared.items())},
                   "schedule": (cd or {}).get("schedule", "geometric"),
                   "within_total": total <= binding_total + 1e-12,
                   "stops_at_continue_gate": stops,
                   "exhausted": bool((cd or {}).get("exhausted"))}
    return {
        "epochs": epochs,
        "this_epoch": epochs[-1]["spent"] if epochs else None,
        "cumulative": total,
        **charged,
        # A lower bound when an earlier epoch's deltas could not be recovered.
        "cumulative_is_lower_bound": bool(unknown),
        "unrecovered_epochs": unknown,
        "accounting": ("union (Bonferroni) bound over epochs: each epoch spends "
                       "delta_screen + delta_terminal (+ delta_constraint when "
                       "constraint-model exclusion is registered, + delta_feasibility "
                       "when a mean/chance constraint is), and epochs after the first "
                       "were compiled after earlier epochs' data were seen, so the "
                       "family-wise probability that ANY epoch's decision is wrong "
                       "is at most the sum. Certification is still judged per "
                       "epoch at that epoch's deltas; this figure is informational "
                       "unless optimization.policy.campaign_delta is declared, "
                       "when each epoch's deltas ARE its share of that total and "
                       "the sum is binding (mode: charged)."),
    }
