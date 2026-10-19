"""Item 5 of #321: manipulation checks beyond echo.

A predicate over ``applied.*`` reads Nous's own record of the level it set, so
it passes even when the target ignored the flag. Before this, such a check was
reported exactly like a target-emitted one. Now it is flagged echo-only in the
preview, report.json and report.md, and ``evidence: target`` makes it a
validation error. Behavioral, zero LLM.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.preview import build_preview, format_preview
from orchestrator.optimize.report_md import render_report_markdown
from orchestrator.optimize.synthetic import SURFACES
from orchestrator.validate import validate_optimization_campaign

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "orchestrator"
                     / "schemas" / "report.schema.json").read_text())


def _echo_factors(*, evidence=None):
    c = synthetic_campaign(SURFACES["bowl"]())
    fs = copy.deepcopy(c["optimization"]["factors"])
    man = {"observable": "applied.A", "op": "==", "value": "{level}"}
    if evidence:
        man["evidence"] = evidence
    fs[0]["manipulation"] = man
    return fs


def test_an_echo_only_check_is_flagged_in_report_and_report_md(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path,
                               campaign_overrides={"factors": _echo_factors()})
    jsonschema.validate(r.report, SCHEMA)
    ev = {m["factor"]: m for m in r.report["provenance"]["manipulation_evidence"]}
    assert ev["A"]["evidence"] == "echo" and ev["A"]["observable"] == "applied.A"
    assert ev["B"]["evidence"] == "target"
    md = render_report_markdown(r.work_dir)
    assert "echo-only" in md and "`A` (`applied.A`)" in md
    assert "`B`" not in md.split("echo-only", 1)[1].split("\n", 1)[0]


def test_a_target_only_campaign_flags_nothing(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path)
    assert all(m["evidence"] == "target"
               for m in r.report["provenance"]["manipulation_evidence"])
    assert "echo-only" not in render_report_markdown(r.work_dir)


def test_the_preview_warns_about_echo_only_checks():
    c = synthetic_campaign(SURFACES["bowl"](), factors=_echo_factors())
    out = "\n".join(format_preview(build_preview(c, noise_sd=1.0, mean=10.0,
                                                 run_secs=[1.0])))
    assert "A read only `applied.*`" in out and "SENT" in out


@pytest.mark.parametrize("root", ["applied.A", "applied_env.X", "applied_args",
                                  "applied_patches.A.value"])
def test_evidence_target_on_an_echo_predicate_fails_validation(root):
    fs = _echo_factors(evidence="target")
    fs[0]["manipulation"]["observable"] = root
    c = synthetic_campaign(SURFACES["bowl"](), factors=fs)
    errs = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN")]
    assert any("manipulation.evidence is 'target'" in e for e in errs), errs
    with pytest.raises(ValueError, match="evidence is 'target'"):
        parse_factors(fs)


def test_evidence_target_on_a_target_field_validates_and_runs(tmp_path):
    c = synthetic_campaign(SURFACES["bowl"]())
    fs = copy.deepcopy(c["optimization"]["factors"])
    fs[0]["manipulation"] = {**fs[0]["manipulation"], "evidence": "target"}
    c2 = synthetic_campaign(SURFACES["bowl"](), factors=fs)
    assert not [e for e in validate_optimization_campaign(c2)
                if "evidence" in e and not e.startswith("WARN")]
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path,
                               campaign_overrides={"factors": fs})
    ev = {m["factor"]: m for m in r.report["provenance"]["manipulation_evidence"]}
    assert ev["A"] == {**ev["A"], "evidence": "target", "required": "target"}


def test_an_unknown_evidence_value_is_rejected():
    fs = _echo_factors(evidence="maybe")
    with pytest.raises(ValueError, match="'target' or 'any'"):
        parse_factors(fs)
