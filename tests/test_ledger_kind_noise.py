"""The ledger does not warn about artifacts a kind never writes.

A kind: optimization run printed "No findings.json for iteration 1" and "No
bundle.yaml ... family='unknown'" as WARNINGs on every iteration (twice each).
Neither file exists in that kind by design, so the warnings were pure noise --
and noise is what trains authors to skip the warnings that matter.
"""
from __future__ import annotations

import json
import logging

from orchestrator.ledger import append_ledger_row


def _iteration(tmp_path, *, optimization: bool, findings: bool):
    wd = tmp_path / "wd"
    it = wd / "runs" / "iter-2"
    it.mkdir(parents=True)
    if optimization:
        (wd / "policy.json").write_text("{}")
    if findings:
        (it / "findings.json").write_text(json.dumps({"iteration": 2, "arms": []}))
    return wd


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
            and r.name == "orchestrator.ledger"]


def test_an_optimization_iteration_appends_quietly(tmp_path, caplog):
    wd = _iteration(tmp_path, optimization=True, findings=True)
    with caplog.at_level(logging.DEBUG):
        append_ledger_row(wd, 2)
        append_ledger_row(wd, 3)  # verify-shaped: no findings.json
    assert not any("bundle.yaml" in m or "findings.json" in m for m in _warnings(caplog))
    assert json.loads((wd / "ledger.json").read_text())["iterations"]


def test_a_reflective_iteration_still_warns(tmp_path, caplog):
    wd = _iteration(tmp_path, optimization=False, findings=True)
    with caplog.at_level(logging.DEBUG):
        append_ledger_row(wd, 2)
    assert any("bundle.yaml" in m for m in _warnings(caplog))


def test_a_pre_policy_optimization_iteration_appends_quietly(tmp_path, caplog):
    """plan/build run before verify compiles policy.json; the campaign copy
    still says what kind this is."""
    wd = _iteration(tmp_path, optimization=False, findings=False)
    (wd / "campaign.yaml").write_text("kind: optimization\n")
    with caplog.at_level(logging.DEBUG):
        append_ledger_row(wd, 1)
    assert not any("findings.json" in m for m in _warnings(caplog))
