"""Centre-point curvature routes screen -> refine (and never certifies blind).

The defect this file pins: a response with an INTERIOR optimum has ~zero main
effects at a 2-level screen's corners, so no numeric factor survives the
screen, while the screen's centre points show strong curvature (the
lack-of-fit F on pure error rejects). The compiled policy's only screen ->
refine route was ``refinable_survivors > 0``, so such a screen went straight
to confirm, seated a shortlist from the corners and the centre, and CERTIFIED
the best of an uninformed shortlist -- 26% below the true optimum on
``geometric_knob`` (linear coding) on every seed.

Centre points exist to detect exactly this, and the textbook response is to
augment to a second-order design over the refinable factors. Curvature from a
2-level design's centre points is a single contrast that cannot be attributed
to any one factor, so refine must span EVERY refinable factor (which
``_build_design`` already does).

Behavioural only, per CLAUDE.md: assert what step() returns, what the campaign
recommends, and what report.json / confirmation.json claim -- never which
helper ran. Zero LLM: the harness drives the real run_stage over closed-form
surfaces.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.optimize import invariants as inv
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.policy import check_policy, compile_policy, step
from orchestrator.optimize.synthetic import SURFACES

#: The default policy epsilon is 2% of the reference; judge certificates
#: against that width of the TRUE best.
_EPS_PCT = 2.0

_SCREEN_OBS = {
    "correctness_failed": False, "nan_response": False,
    "alias_consequential": False, "foldover_affordable": True,
    "all_within_noise": True, "refinable_survivors": 0,
}


def _eps(res) -> float:
    return abs(res.true_best) * _EPS_PCT / 100.0


def _latest_fitting_recommendation(work_dir: Path) -> dict:
    runs = sorted((d for d in (work_dir / "runs").iterdir() if d.name.startswith("iter-")),
                  key=lambda d: int(d.name.split("-")[1]))
    for it in reversed(runs):
        p = it / "recommendation.json"
        if p.exists():
            return json.loads(p.read_text())
    return {}


# ── the registered branch, at the policy level ─────────────────────────────

@pytest.mark.parametrize("state", ["screen", "foldover"])
def test_lack_of_fit_with_no_refinable_survivor_routes_to_refine(state):
    pol = compile_policy(synthetic_campaign(SURFACES["geometric_knob"]()))
    assert check_policy(pol) == []
    nxt, rule = step(pol, state, {**_SCREEN_OBS, "lack_of_fit": True})
    assert nxt == "refine", rule
    # A registered branch names its inferential accounting rule (spec §5).
    acct = rule["accounting"].lower()
    assert "lack-of-fit" in acct and "pure error" in acct and "alpha=0.05" in acct
    # Metamorphic partner: the same screen with no curvature still confirms.
    nxt, _ = step(pol, state, {**_SCREEN_OBS, "lack_of_fit": False})
    assert nxt == "confirm"


def test_a_consequential_alias_is_still_resolved_before_curvature_is_chased():
    pol = compile_policy(synthetic_campaign(SURFACES["geometric_knob"]()))
    nxt, _ = step(pol, "screen", {**_SCREEN_OBS, "lack_of_fit": True,
                                  "alias_consequential": True})
    assert nxt == "foldover"


def test_no_curvature_branch_is_registered_when_nothing_is_refinable():
    """All-2-level factors: there is no second-order design to augment to."""
    pol = compile_policy(synthetic_campaign(SURFACES["interaction_only"]()))
    assert not any((t.get("when") or {}).get("lack_of_fit") for t in pol["transitions"])
    nxt, _ = step(pol, "screen", {**_SCREEN_OBS, "lack_of_fit": True})
    assert nxt == "confirm"


# ── the oracle: the answer, judged against the truth ───────────────────────

@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_geometric_knob_linear_refines_and_never_certifies_a_large_gap(tmp_path, seed):
    res = run_synthetic_campaign(SURFACES["geometric_knob"](), seed=seed, parent_dir=tmp_path)
    assert "refine" in res.path, res.path
    assert not (res.report.get("certified") and res.true_gap > _eps(res)), (
        res.true_gap, res.recommendation, res.path)


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_pure_curvature_bowl_refines_and_lands_on_the_optimum(tmp_path, seed):
    """Symmetric bowl centred on the design centre: zero main effects anywhere."""
    res = run_synthetic_campaign(SURFACES["bowl_centred"](), seed=seed, parent_dir=tmp_path)
    assert "refine" in res.path, res.path
    assert res.true_gap <= _eps(res), (res.true_gap, res.recommendation)
    # The choice factor refine held fixed is part of the answer.
    assert res.recommendation.get("C") == "on", res.recommendation


# ── certification needs an adequate model behind the shortlist ─────────────

@pytest.mark.parametrize("name", sorted(SURFACES))
def test_no_certificate_rests_on_a_model_the_data_rejected(tmp_path, name):
    over = ({"stages": ["verify", "screen", "confirm"]}
            if name in ("drift", "interaction_only") else None)
    res = run_synthetic_campaign(SURFACES[name](), seed=3, parent_dir=tmp_path,
                                 campaign_overrides=over)
    rec = _latest_fitting_recommendation(res.work_dir)
    assert inv.check_certificate_rests_on_adequate_model(res.report, rec) == []
    if rec.get("model_adequate") is False and res.report.get("recommendation", {}).get(
            "basis") in ("certified", "terminal_best"):
        assert "model_inadequate" in res.report.get("certification_withheld", []), res.report
