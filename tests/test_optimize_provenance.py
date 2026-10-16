"""report.json records what it rests on (audit Q7): code version, input
hashes, analysis constants, and the cross-epoch error budget.

Behavioral: every assertion reads report.json / report.md off disk after a
real synthetic campaign. Zero LLM.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES

SCHEMA = json.loads((Path(__file__).resolve().parents[1]
                     / "orchestrator" / "schemas" / "report.schema.json").read_text())


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_report_hashes_every_runs_file_and_design_matrix_it_rests_on(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=4, parent_dir=tmp_path)
    rep = json.loads((res.work_dir / "report.json").read_text())
    jsonschema.validate(rep, SCHEMA)
    inputs = rep["provenance"]["inputs"]
    on_disk = sorted([str(p.relative_to(res.work_dir))
                      for name in ("runs.jsonl", "design_matrix.json", "relations.json")
                      for p in res.work_dir.glob(f"runs/iter-*/{name}")]
                     + [p.name for p in res.work_dir.glob("campaign.epoch-*.yaml")])
    assert "runs/iter-1/relations.json" in on_disk and "campaign.epoch-1.yaml" in on_disk
    assert sorted(inputs) == on_disk and on_disk, (inputs, on_disk)
    for rel, digest in inputs.items():
        assert _sha(res.work_dir / rel) == digest, rel
    assert rep["provenance"]["policy_hash"] == rep["policy_hash"]
    assert rep["provenance"]["nous"]["package_version"]


def test_analysis_constants_are_read_from_the_live_modules(tmp_path, monkeypatch):
    """A constant changed between two Nous versions must show up in the record
    (the audit's 'an upgrade changes the analysis under the same hash')."""
    from orchestrator.optimize import decide

    monkeypatch.setattr(decide, "SEARCH_SAMPLE", 1234)
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=4, parent_dir=tmp_path)
    consts = res.report["provenance"]["analysis_constants"]
    assert consts["decide.SEARCH_SAMPLE"] == 1234
    assert consts["decide.CANDIDATE_CAP"] == decide.CANDIDATE_CAP
    assert consts["effects.fit_effects.alpha"] == 0.05


def _two_epochs(tmp_path, monkeypatch):
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.harness import _all_pass, synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))

    def _drive(campaign, work_dir, runner, first, last):
        for i in range(first, last):
            out = run_stage(campaign, work_dir, iteration=i, config_runner=runner,
                            test_results=_all_pass(campaign), auto_approve=True)
            if out == IterationOutcome.COMPLETED:
                return
            eng = Engine(work_dir)
            if eng.phase != "DONE":
                eng.transition("DONE")
            eng.transition("DESIGN")

    broken = SURFACES["nan_at_corner"]()
    c1 = synthetic_campaign(broken)
    wd = setup_work_dir(c1["run_id"], repo_path=None, campaign=c1)
    _drive(c1, wd, make_synthetic_runner(broken, seed=50), 1, 6)
    first = json.loads((wd / "report.json").read_text())
    fixed = SURFACES["drift"]()
    c2 = synthetic_campaign(fixed, policy={"delta_screen": 0.02, "delta_terminal": 0.03})
    c2["run_id"] = c1["run_id"]
    eng = Engine(wd)
    if eng.phase != "DONE":
        eng.transition("DONE")
    eng.transition("DESIGN")
    _drive(c2, wd, make_synthetic_runner(fixed, seed=51), 6, 12)
    return wd, first


def test_the_error_budget_accumulates_across_epochs(tmp_path, monkeypatch):
    wd, first = _two_epochs(tmp_path, monkeypatch)
    assert first["error_budget"]["cumulative"] == first["delta_screen"] + first["delta_terminal"]
    rep = json.loads((wd / "report.json").read_text())
    jsonschema.validate(rep, SCHEMA)
    eb = rep["error_budget"]
    assert rep["epoch"] == 2
    e1, e2 = eb["epochs"]
    assert e1["spent"] == first["delta_screen"] + first["delta_terminal"]
    # Epoch 2 was re-registered with different deltas; each epoch is charged
    # its own, recovered from the campaign it registered.
    assert (e2["delta_screen"], e2["delta_terminal"]) == (0.02, 0.03)
    assert (rep["delta_screen"], rep["delta_terminal"]) == (0.02, 0.03)
    assert e2["compiled_after_data"] is True and e1["compiled_after_data"] is False
    assert abs(eb["cumulative"] - (e1["spent"] + e2["spent"])) < 1e-12
    assert eb["cumulative"] > eb["this_epoch"]
    assert eb["cumulative_is_lower_bound"] is False

    from orchestrator.optimize.report_md import render_report_markdown

    md = render_report_markdown(wd)
    assert "## Error budget across epochs" in md
    assert f"Cumulative (union bound over epochs): {eb['cumulative']:.6g}" in md


def test_an_unrecoverable_earlier_epoch_makes_the_budget_a_lower_bound(tmp_path, monkeypatch):
    wd, _ = _two_epochs(tmp_path, monkeypatch)
    (wd / "campaign.epoch-1.yaml").unlink()
    from orchestrator.optimize.policy import read_policy
    from orchestrator.optimize.provenance import error_budget

    eb = error_budget(wd, read_policy(wd))
    assert eb["cumulative_is_lower_bound"] is True and eb["unrecovered_epochs"] == [1]


def test_the_record_names_its_runtime_and_source_scope(tmp_path):
    res = run_synthetic_campaign(SURFACES["bowl"](), seed=4, parent_dir=tmp_path)
    prov = res.report["provenance"]
    assert prov["runtime"]["python"] and "scipy" in prov["runtime"]
    assert "orchestrator/**/*.py" in prov["nous"]["source_scope"]
    assert "schemas" in prov["nous"]["source_scope"] or ".json" in prov["nous"]["source_scope"]


def test_an_earlier_epochs_deltas_say_how_they_were_recovered(tmp_path, monkeypatch):
    wd, _ = _two_epochs(tmp_path, monkeypatch)
    e1, e2 = json.loads((wd / "report.json").read_text())["error_budget"]["epochs"]
    assert "recompiled by the current Nous" in e1["deltas_from"]
    assert e2["deltas_from"] == "this epoch's policy.json"
