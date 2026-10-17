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
