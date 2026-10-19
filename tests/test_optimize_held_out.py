"""response.held_out is surfaced in report.json -- and still decides nothing.

The held-out metric is the campaign's generalization check. It was recorded on
every row but no artifact summarised it, so declaring one changed nothing a
reader could see. Asserted metamorphically: shifting the held-out metric by a
constant must shift its reported mean by exactly that constant and leave every
DECISION in the report unchanged -- which is what "held out" means.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.report_md import render_report_markdown
from orchestrator.optimize.synthetic import SURFACES

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "orchestrator"
                     / "schemas" / "report.schema.json").read_text())


def _run(tmp_path, shift: float, *, surface="bowl", seed=3):
    base = SURFACES[surface]()
    s = dataclasses.replace(
        base,
        extra_observables=lambda lv, _b=base: {
            **_b.extra_observables(lv), "ho": _b.fn(lv) * 0.5 + shift},
    )
    response = dict(synthetic_campaign(base)["optimization"]["response"])
    response["held_out"] = ["ho"]
    return run_synthetic_campaign(
        s, seed=seed, parent_dir=tmp_path / f"shift{shift}",
        campaign_overrides={"response": response},
    )


@pytest.mark.parametrize("surface,seed", [("bowl", 3), ("sla", 5)])
def test_held_out_is_reported_and_shifting_it_changes_no_decision(
        tmp_path, surface, seed):
    a = _run(tmp_path, 0.0, surface=surface, seed=seed)
    b = _run(tmp_path, 100.0, surface=surface, seed=seed)
    for r in (a, b):
        jsonschema.validate(r.report, SCHEMA)
    ha, hb = a.report["held_out"]["recommendation"], b.report["held_out"]["recommendation"]
    assert ha["n_rows"] > 0, "the recommended configuration's rows were not found"
    assert hb["metrics"]["ho"]["mean"] == pytest.approx(ha["metrics"]["ho"]["mean"] + 100.0)
    # `provenance` is a RECORD of the inputs, not a decision: it hashes the
    # runs.jsonl bytes, which carry the shifted held-out values.
    strip = lambda rep: {k: v for k, v in rep.items()  # noqa: E731
                         if k not in ("held_out", "provenance")}
    assert strip(a.report) == strip(b.report), "a held-out metric moved a decision"


def test_report_md_shows_the_held_out_table(tmp_path):
    r = _run(tmp_path, 0.0)
    md = render_report_markdown(r.work_dir)
    assert "## Held-out check" in md and "`ho`" in md


def test_no_held_out_declared_means_no_block(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path)
    assert "held_out" not in r.report
