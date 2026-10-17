"""#321 P2: certification-soundness follow-ups to WP-A / WP-B.

Behavioral only: real campaigns through the synthetic harness (zero LLM
calls, no subprocess), asserting on confirmation.json / report.json, or on the
pure arithmetic of ``certificate``.
"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import PARETO_SURFACES, Surface, _numeric, _obj, _unit


def _confirmations(work_dir) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(
        Path(work_dir).glob("runs/iter-*/confirmation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


# ── item 5: the Pareto path reads model_adequate (WP-B limit 10) ─────────────

def _pareto_cubic() -> Surface:
    """A two-objective surface whose f1 is cubic in A: screen rejects on lack
    of fit, refine's validation check rejects, and the epoch's model_adequate
    is False -- yet each objective model is `modelled` at refine."""
    def x(lv):
        return (float(lv["A"]) - 9.0) / 7.0

    def f1(lv):
        return 12.0 - 6.0 * x(lv) ** 3 - 2.0 * x(lv) ** 2 + 1.5 * x(lv) + 0.5 * _unit(lv, "B")

    def f2(lv):
        return 10.0 + 4.0 * _unit(lv, "A") ** 2 + 1.0 * _unit(lv, "B")

    return Surface(name="pareto_cubic", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B")), fn=f1,
                   objectives=(_obj("f1", f1), _obj("f2", f2)))


def test_a_rejected_model_seats_no_predicted_front_point(tmp_path):
    """Before #321 the multi-objective shortlist seated the rejected model's
    predicted extremes, its predicted preferred point and predicted spread,
    so the comparison was anchored on a surface the data refused. (Its
    predictions stay as RIVALS in the front statuses: a rival can only remove
    confidence, which is the conservative direction.)"""
    r = run_synthetic_campaign(_pareto_cubic(), seed=1, parent_dir=tmp_path)
    recs = [json.loads(p.read_text()) for p in r.work_dir.glob("runs/iter-*/recommendation.json")]
    assert recs and recs[-1]["model_adequate"] is False
    confs = _confirmations(r.work_dir)
    assert confs
    for c in confs:
        whys = [f.get("why") or "" for f in c["finalists"]]
        assert not any(w.startswith(("predicted extreme", "preferred point of the "
                                     "predicted")) for w in whys), whys
        assert "model_inadequate" in c["certification_withheld"]
    first = [f.get("why") or "" for f in confs[0]["finalists"]]
    measured = [w for w in first if w.startswith(("best measured", "measured nondominated"))]
    assert len(measured) >= 2, first           # measured points anchor it


def test_an_adequate_model_still_seats_predicted_points(tmp_path):
    r = run_synthetic_campaign(PARETO_SURFACES["pareto_convex"](), seed=1,
                               parent_dir=tmp_path)
    whys = [f.get("why") or "" for f in _confirmations(r.work_dir)[0]["finalists"]]
    assert any("predict" in w for w in whys), whys


# ── item 3: the constraint-exclusion delta is in the stated budget ──────────

_CORNER_OV = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                           "constraints": [{"metric": "p99_ms", "op": "<=", "value": 90}]},
              "stages": ["verify", "screen", "confirm"]}


def _recommendations(work_dir) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(
        Path(work_dir).glob("runs/iter-*/recommendation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


def test_constraint_exclusion_is_a_third_union_term(tmp_path):
    """Before #321 constraint-model exclusion spent delta_screen on a family
    distinct from E_s while the stated budget was delta_screen +
    delta_terminal. The term is now registered, used, and summed."""
    from orchestrator.optimize.synthetic import SURFACES

    ov = dict(_CORNER_OV, policy={"delta_constraint": 0.02})
    r = run_synthetic_campaign(SURFACES["infeasible_corner_interior"](), seed=1,
                               parent_dir=tmp_path, campaign_overrides=ov)
    assert r.report["delta_constraint"] == 0.02
    eb = r.report["error_budget"]["epochs"][-1]
    assert eb["delta_constraint"] == 0.02
    assert abs(eb["spent"] - (r.report["delta_screen"] + r.report["delta_terminal"]
                              + 0.02)) < 1e-12
    cm = [e for e in _recommendations(r.work_dir)[-1]["constraint_models"] if e["modelled"]]
    assert cm and all(abs(e["delta"] - 0.02 / len(cm)) < 1e-12 for e in cm)


def test_an_unconstrained_campaign_spends_two_terms(tmp_path):
    from orchestrator.optimize.synthetic import SURFACES

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    assert "delta_constraint" not in r.report
    eb = r.report["error_budget"]["epochs"][-1]
    assert eb["spent"] == r.report["delta_screen"] + r.report["delta_terminal"]


def test_delta_constraint_is_range_checked():
    from orchestrator.validate import _rule14_policy_ranges

    assert _rule14_policy_ranges({"policy": {"delta_constraint": 0.7}})
    assert not _rule14_policy_ranges({"policy": {"delta_constraint": 0.01}})
