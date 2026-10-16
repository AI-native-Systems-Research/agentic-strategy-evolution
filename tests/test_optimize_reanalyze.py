"""``nous reanalyze``: every fitted artifact is re-derived from the recorded
rows, with nothing executed, and diffed against disk (audit Q7).

Behavioral: real synthetic campaigns, then the CLI / ``reanalyze`` over their
work_dirs; assertions read the verdict and the listed differences. Zero LLM.
"""
from __future__ import annotations

import json
import sys

import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.reanalyze import reanalyze
from orchestrator.optimize.synthetic import SURFACES


def _cli(monkeypatch, *argv):
    from orchestrator import cli

    monkeypatch.setattr(sys, "argv", ["nous", "reanalyze", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


@pytest.fixture
def campaign(tmp_path):
    return run_synthetic_campaign(SURFACES["bowl"](), seed=7, parent_dir=tmp_path / "c")


def test_an_untouched_campaign_reanalyzes_identically(campaign, monkeypatch, capsys):
    assert _cli(monkeypatch, str(campaign.work_dir)) == 0
    out = capsys.readouterr().out
    assert out.startswith("ANALYSIS RE-DERIVED")


def test_reanalysis_compares_every_fitted_artifact(campaign):
    res = reanalyze(campaign.work_dir)
    assert res.identical, res.differences
    for must in ("report.json", "policy.json", "transitions.jsonl",
                 "runs/iter-2/effects.json", "runs/iter-2/recommendation.json",
                 "runs/iter-3/effects.json", "runs/iter-4/confirmation.json"):
        assert must in res.compared, (must, res.compared)


def test_reanalysis_executes_nothing(campaign, monkeypatch):
    """The replay runner answers every row; a measurement would need a
    runner or a subprocess, and neither is reachable."""
    import subprocess

    def _boom(*a, **k):
        raise AssertionError(f"reanalysis shelled out: {a}")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    assert reanalyze(campaign.work_dir).identical


def test_an_edited_measurement_is_detected_twice(campaign, monkeypatch, capsys):
    """Change one recorded response: the input hash no longer matches the
    report's record, and the re-derived fit no longer matches the recorded one."""
    p = campaign.work_dir / "runs" / "iter-2" / "runs.jsonl"
    rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    rows[0]["response"]["m"] += 5.0
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    res = reanalyze(campaign.work_dir)
    assert not res.identical
    assert any(c["file"] == "runs/iter-2/runs.jsonl" for c in res.input_changes)
    assert not any(d["file"] == "runs/iter-2/runs.jsonl" for d in res.differences)
    assert "runs/iter-2/effects.json" in {d["file"] for d in res.differences}
    assert _cli(monkeypatch, str(campaign.work_dir)) == 1
    assert "INPUT runs/iter-2/runs.jsonl" in capsys.readouterr().out


def test_an_edited_conclusion_is_detected(campaign):
    """The rows are untouched, the report was rewritten: only the report differs."""
    p = campaign.work_dir / "report.json"
    rep = json.loads(p.read_text())
    rep["residual_regret_terminal"] = 123.0
    p.write_text(json.dumps(rep))
    res = reanalyze(campaign.work_dir)
    assert not res.identical and not res.input_changes
    files = {d["file"] for d in res.differences}
    assert files == {"report.json"}, res.differences
    assert "residual_regret_terminal" in res.differences[0]["difference"]


def test_a_changed_analysis_constant_is_reported(campaign, monkeypatch):
    """Same rows, different code: the provenance record says so."""
    from orchestrator.optimize import decide

    monkeypatch.setattr(decide, "SEARCH_SAMPLE", decide.SEARCH_SAMPLE + 1)
    res = reanalyze(campaign.work_dir)
    assert not res.identical
    assert any("SEARCH_SAMPLE" in d["difference"] for d in res.differences), res.differences


def test_a_constrained_campaign_with_fallback_rungs_reproduces(tmp_path):
    res = run_synthetic_campaign(
        SURFACES["stochastic_constraint_boundary"](), seed=2, parent_dir=tmp_path,
        campaign_overrides={"response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [{"metric": "stall_ms", "op": "<=", "value": 10}]}})
    out = reanalyze(res.work_dir)
    assert out.identical, out.differences


def test_a_two_epoch_campaign_reproduces_each_epoch_from_its_own_registration(
        tmp_path, monkeypatch):
    from tests.test_optimize_provenance import _two_epochs

    wd, _ = _two_epochs(tmp_path, monkeypatch)
    res = reanalyze(wd)
    assert res.identical, res.differences
    assert "epoch_end-1.json" in res.compared


def test_a_built_campaign_reanalyzes_without_rerunning_the_build(tmp_path, monkeypatch):
    """The build is an agent call and its oracles are measurements: they are
    named as not re-run, and every derived artifact still reproduces."""
    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    from tests.test_optimize_build_oracles import (
        _build_campaign, _declared_ids, _fake_build, _git_repo)

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("built", repo_path=str(repo), campaign=c)
    runner = make_synthetic_runner(s, seed=3)
    ids = _declared_ids(c)
    for i in range(1, 10):
        out = run_stage(c, wd, iteration=i, config_runner=runner,
                        test_results={t: i > 1 for t in ids},
                        sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
        if out == IterationOutcome.COMPLETED:
            break
        eng = Engine(wd)
        if eng.phase != "DONE":
            eng.transition("DONE")
        eng.transition("DESIGN")
    assert (wd / "report.json").exists()
    res = reanalyze(wd)
    assert res.identical, res.differences
    assert [s_["stage"] for s_ in res.skipped_iterations] == ["build"]
    assert "build_review.json" in res.not_rederived
    assert "report.json" in res.compared


# ─── review R2: every way the record can disagree with its rows is caught ───


def _rows(p):
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def test_a_flipped_transition_decision_is_a_difference(campaign):
    p = campaign.work_dir / "transitions.jsonl"
    rows = _rows(p)
    rows[0]["to"] = "report"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    res = reanalyze(campaign.work_dir)
    assert not res.identical
    assert "transitions.jsonl" in {d["file"] for d in res.differences}


def test_a_deleted_derived_artifact_is_a_difference(campaign):
    (campaign.work_dir / "runs" / "iter-3" / "effects.json").unlink()
    res = reanalyze(campaign.work_dir)
    assert {"file": "runs/iter-3/effects.json", "difference": "only in reanalysis"} in res.differences


def test_an_extra_derived_artifact_is_a_difference(campaign):
    (campaign.work_dir / "runs" / "iter-2" / "planted.json").write_text("{}")
    res = reanalyze(campaign.work_dir)
    assert {"file": "runs/iter-2/planted.json", "difference": "not re-derived"} in res.differences


def test_rows_added_after_the_report_are_an_input_change(campaign):
    p = campaign.work_dir / "runs" / "iter-2" / "runs.jsonl"
    rows = _rows(p)
    extra = dict(rows[0], row_index=999)
    p.write_text(p.read_text() + json.dumps(extra) + "\n")
    res = reanalyze(campaign.work_dir)
    assert not res.identical
    assert {"file": "runs/iter-2/runs.jsonl",
            "change": "content changed after the report was written"} in res.input_changes


def test_a_recorded_row_at_other_levels_is_a_replay_mismatch(campaign):
    p = campaign.work_dir / "runs" / "iter-2" / "runs.jsonl"
    rows = _rows(p)
    rows[0]["levels"] = {k: (v if not isinstance(v, (int, float)) else v + 1)
                         for k, v in rows[0]["levels"].items()}
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    res = reanalyze(campaign.work_dir)
    assert not res.identical and res.replay_mismatches, res


def test_an_unparseable_epoch_campaign_is_a_difference_not_a_substitution(campaign):
    (campaign.work_dir / "campaign.epoch-1.yaml").write_text("optimization: [unclosed\n")
    res = reanalyze(campaign.work_dir)
    assert not res.identical
    assert any(d["file"] == "campaign.epoch-1.yaml" for d in res.differences)


def test_a_missing_report_means_inputs_unchecked(campaign):
    (campaign.work_dir / "report.json").unlink()
    res = reanalyze(campaign.work_dir)
    assert not res.identical
    assert any("inputs_unchecked" in c["change"] for c in res.input_changes)


def test_excluded_files_are_listed(campaign):
    (campaign.work_dir / "notes.txt").write_text("hand notes")
    res = reanalyze(campaign.work_dir)
    assert res.identical
    assert any(e["file"] == "notes.txt" for e in res.excluded)


def test_a_work_dir_that_cannot_be_reanalysed_exits_2(tmp_path, monkeypatch, capsys):
    wd = tmp_path / "bare"
    wd.mkdir()
    (wd / "state.json").write_text("{}")
    assert _cli(monkeypatch, str(wd)) == 2


def test_a_missing_epoch_campaign_is_a_difference_not_a_substitution(tmp_path, monkeypatch):
    from tests.test_optimize_provenance import _two_epochs

    wd, _ = _two_epochs(tmp_path, monkeypatch)
    (wd / "campaign.epoch-2.yaml").unlink()
    res = reanalyze(wd)
    assert not res.identical
    assert any(d["file"] == "campaign.epoch-2.yaml" and "missing" in d["difference"]
               for d in res.differences), res.differences


def test_a_broken_build_record_seal_is_a_reanalysis_difference(tmp_path, monkeypatch):
    from tests.test_optimize_waivers import _report

    _report(tmp_path, monkeypatch)
    wd = tmp_path / "waive"
    p = wd / "authored_tests.json"
    p.write_text(p.read_text() + " ")
    res = reanalyze(wd)
    assert {"file": "authored_tests.json", "difference": "build record seal broken"} in res.differences
