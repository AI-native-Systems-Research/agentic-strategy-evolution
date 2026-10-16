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
    assert out.startswith("REPRODUCIBLE")


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
