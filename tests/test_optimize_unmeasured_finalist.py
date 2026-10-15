"""An unmeasured finalist makes R_terminal unknown, and the report says why it is uncertified.

Spec §3.5: ``R_t = max_{z in S} U_t(z, x)`` over the shortlist. A finalist the
instrument never measured is an admissible member of ``S`` whose ``U_t`` is
unknown, so the max is unknown -- an unknown is not a zero (INV-SEM02). The
defect this pins: on ``fails_at_one_level`` the unmeasured finalist IS the true
optimum, and ``report.json`` read ``residual_regret_terminal: 0.0`` next to
``certified: false`` with no reason given, i.e. a bound that understated the
regret against exactly the rival nobody measured.

All tests drive the zero-token synthetic harness and assert artifacts on disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.report_md import render_report_markdown
from orchestrator.optimize.synthetic import SURFACES

_SCHEMAS = Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"


def _validator(name: str):
    return jsonschema.Draft202012Validator(
        json.loads((_SCHEMAS / name).read_text()))


def _latest_confirmation(work_dir: Path) -> dict | None:
    confs = sorted(Path(work_dir).glob("runs/iter-*/confirmation.json"),
                   key=lambda p: int(p.parent.name.split("-")[1]))
    return json.loads(confs[-1].read_text()) if confs else None


@pytest.mark.parametrize("seed", [0, 11])
def test_unmeasured_finalist_nulls_the_terminal_bound_and_names_the_reason(
    tmp_path, seed,
):
    res = run_synthetic_campaign(SURFACES["fails_at_one_level"](), seed=seed,
                                 parent_dir=tmp_path)
    rep = json.loads((res.work_dir / "report.json").read_text())
    _validator("report.schema.json").validate(rep)
    statuses = [f["status"] for f in rep["finalists"]]
    assert "unmeasured" in statuses, statuses  # the scenario under test

    assert rep["certified"] is False
    assert rep["residual_regret_terminal"] is None, (
        "an unmeasured rival makes the max over the shortlist unknown, not 0"
    )
    assert "finalist_unmeasured" in rep["certification_withheld"]
    # Not mislabelled as a constraint violation: nothing was inadmissible.
    assert "finalist_measured_infeasible" not in rep["certification_withheld"]

    conf = _latest_confirmation(res.work_dir)
    _validator("confirmation.schema.json").validate(conf)
    assert conf["residual_regret_terminal"] is None
    assert conf["terminal_bound"]["value"] is None
    # The survivors-only comparison that genuinely happened is kept, by a name
    # that says what it covers.
    assert conf["terminal_bound_measured_only"]["value"] is not None

    md = render_report_markdown(res.work_dir)
    assert "finalist_unmeasured" in md


@pytest.mark.parametrize("name", sorted(SURFACES))
@pytest.mark.parametrize("seed", [0, 11])
def test_report_certification_is_explained_and_never_outruns_its_evidence(
    tmp_path, name, seed,
):
    """Invariants over every synthetic surface:

    * certified  <=> certification_withheld is empty;
    * certified  =>  every finalist measured (status ok, n >= 2) and R_t <= eps;
    * any finalist unmeasured => R_terminal is None (unknown, never a number
      that silently skips the unmeasured rival).
    """
    res = run_synthetic_campaign(SURFACES[name](), seed=seed, parent_dir=tmp_path)
    rep = json.loads((res.work_dir / "report.json").read_text())
    _validator("report.schema.json").validate(rep)

    withheld = rep["certification_withheld"]
    assert rep["certified"] == (withheld == []), rep
    if rep["certified"]:
        assert rep["finalists"]
        assert all(f["status"] == "ok" and f["n"] >= 2 for f in rep["finalists"])
        assert rep["residual_regret_terminal"] is not None
        assert rep["residual_regret_terminal"] <= rep["epsilon"]
    if any(f["status"] == "unmeasured" for f in rep["finalists"]):
        assert rep["residual_regret_terminal"] is None, rep
        assert "finalist_unmeasured" in withheld


def _drive_confirm(tmp_path, monkeypatch, tag: str, *, fail_finalist: int | None):
    """Run verify/screen/confirm on ``additive``; optionally make every confirm
    replicate of finalist ``fail_finalist`` fail to measure. Returns the
    confirmation record."""
    from orchestrator.engine import Engine
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.harness import _all_pass, synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    surface = SURFACES["additive"]()
    campaign = synthetic_campaign(surface, stages=["verify", "screen", "confirm"])
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / tag))
    inner = make_synthetic_runner(surface, seed=5)

    def runner(row):
        apply = getattr(row, "apply", None) or {}
        if fail_finalist is not None and apply.get("finalist") == fail_finalist:
            raise RuntimeError("synthetic timeout injected at confirm")
        return inner(row)

    wd = setup_work_dir(f"unmeasured-{tag}", repo_path=None, campaign=campaign)
    run_stage(campaign, wd, iteration=1, stage="verify", config_runner=runner,
              test_results=_all_pass(campaign), auto_approve=True)
    run_stage(campaign, wd, iteration=2, stage="screen", config_runner=runner,
              test_results=_all_pass(campaign), auto_approve=True)
    eng = Engine(wd)
    if eng.phase != "DONE":
        eng.transition("DONE")
    eng.transition("DESIGN")
    run_stage(campaign, wd, iteration=3, stage="confirm", config_runner=runner,
              test_results=_all_pass(campaign), auto_approve=True)
    return json.loads((Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text())


def test_making_a_finalist_unmeasurable_never_decreases_the_terminal_bound(
    tmp_path, monkeypatch,
):
    """METAMORPHIC: the same campaign with one finalist's confirm replicates
    failing must not report a SMALLER residual regret. Under the
    unknown-dominates order (None is above every number) the treated bound is
    None, and certification is withheld for that named reason."""
    control = _drive_confirm(tmp_path, monkeypatch, "control", fail_finalist=None)
    assert control["residual_regret_terminal"] is not None
    keys = [f["key"] for f in control["finalists"]]
    assert len(keys) >= 3, keys

    for victim in keys:
        if victim == control["best"]:
            continue
        idx = int(victim[1:])
        treated = _drive_confirm(tmp_path, monkeypatch, f"t{idx}", fail_finalist=idx)
        _validator("confirmation.schema.json").validate(treated)
        st = {f["key"]: f["status"] for f in treated["finalists"]}
        assert st[victim] == "unmeasured", st
        assert treated["residual_regret_terminal"] is None, treated["terminal_bound"]
        assert treated["certified"] is False
        assert "finalist_unmeasured" in treated["certification_withheld"]
        assert "finalist_measured_infeasible" not in treated["certification_withheld"]
