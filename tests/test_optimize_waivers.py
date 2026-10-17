"""report.json's provenance.waivers is read from the GATE ARTIFACTS, so a
report never claims a check that did not run (review R1). Asserted through
report.json of a built campaign driven to its report, not by calling the
helper directly. Real git repo; fake build agent; no LLM."""
from __future__ import annotations

import json
from pathlib import Path

from tests.test_optimize_build_oracles import (
    _build_campaign,
    _declared_ids,
    _fake_build,
    _git_repo,
    _strict_runner,
)


def _report(tmp_path, monkeypatch, *, build_checks=None, pre_runner=None, tamper=None):
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s, c = _build_campaign(tmp_path, repo)
    c["optimization"]["build_checks"] = {"mechanism_paths": ["mech.py"], **(build_checks or {})}
    wd = setup_work_dir("waive", repo_path=str(repo), campaign=c)
    runner = make_synthetic_runner(s, seed=3)
    ids = _declared_ids(c)
    for i in range(1, 12):
        out = run_stage(c, wd, iteration=i,
                        config_runner=(pre_runner or runner) if i == 1 else runner,
                        test_results={t: i > 1 for t in ids},
                        sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
        if i == 2 and tamper:
            tamper(Path(wd))
        if out == IterationOutcome.COMPLETED:
            break
        eng = Engine(wd)
        if eng.phase != "DONE":
            eng.transition("DONE")
        eng.transition("DESIGN")
    return json.loads((Path(wd) / "report.json").read_text())["provenance"]["waivers"]


def _gates(ws):
    return {(w["gate"], w["reason"]) for w in ws}


def test_the_report_lists_the_auto_review_and_unclassified_test_evidence(tmp_path, monkeypatch):
    ws = _report(tmp_path, monkeypatch)
    g = _gates(ws)
    assert ("build_review", "auto-approved") in g
    # Verdicts were injected with no test output: 2(d) accepted them unclassified.
    assert ("oracle_2d_authored_tests", "pre_build_failure_unclassified") in g


def test_a_waived_unarmed_baseline_reaches_the_report(tmp_path, monkeypatch):
    ws = _report(tmp_path, monkeypatch, pre_runner=_strict_runner,
                 build_checks={"allow_unarmed_baseline": "harness authored by the build"})
    assert ("oracle_2c_baseline", "harness authored by the build") in _gates(ws)


def test_a_build_record_missing_at_report_time_is_a_waiver_entry(tmp_path, monkeypatch):
    ws = _report(tmp_path, monkeypatch,
                 tamper=lambda wd: (wd / "build_review.json").unlink())
    assert ("build_review", "record missing") in _gates(ws)


def test_a_campaign_waiver_key_alone_does_not_appear_without_the_artifact(tmp_path, monkeypatch):
    """The config says a waiver is ALLOWED; only the artifact says it was USED."""
    ws = _report(tmp_path, monkeypatch,
                 build_checks={"allow_out_of_scope_writes": "never needed"})
    assert not any(w["reason"] == "never needed" for w in ws), ws


def test_a_record_edited_after_verify_shows_as_a_broken_seal_in_the_report(tmp_path, monkeypatch):
    def tamper(wd):
        p = wd / "authored_tests.json"
        rec = json.loads(p.read_text())
        rec["ok"] = True
        p.write_text(json.dumps(rec) + " ")
    ws = _report(tmp_path, monkeypatch, tamper=tamper)
    assert ("gate_record_seal", "authored_tests.json seal broken") in _gates(ws)
