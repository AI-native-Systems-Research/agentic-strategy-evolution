"""#321 P4 item 1: the screen's main-effect drops are ONE registered family.

Behavioral: the survivor rule is exercised on real fits of the real screen
design (no LLM, no subprocess), and on synthetic campaigns through the harness;
assertions are on what the rule decides and on what lands on disk.
"""
from __future__ import annotations

import json
import random

import pytest

from orchestrator.optimize.design import fractional_factorial, with_center_points
from orchestrator.optimize.effects import fit_effects, holm, screening_family
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.stage import decide_after_screen
from orchestrator.optimize.synthetic import SURFACES, _numeric


def test_holm_matches_the_textbook_step_down():
    """Holm (1979): sorted p (0.01, 0.015, 0.03, 0.2) at alpha 0.05 against
    0.0125, 0.0167, 0.025, 0.05 -- the first two rejected, then stop at 0.03
    (and 0.2 is not rejected even though a later threshold is larger)."""
    assert holm([0.03, 0.01, 0.2, 0.015], 0.05) == [False, True, False, True]
    assert holm([0.03, 0.01, 0.2, 0.02], 0.05) == [False, True, False, False]
    assert holm([0.04, 0.04], 0.05) == [False, False]       # 0.04 > 0.025
    assert holm([], 0.05) == []


def test_the_screen_holds_its_family_wise_error_under_the_global_null():
    """Six inert factors, resolution-V 2^(6-1) + 4 centres (36 runs, pure-error
    df 3), the real fit and the real survivor rule. Per-term alpha 0.05 keeps
    at least one inert factor in ~17% of screens (measured 0.173 over 2000);
    the registered Holm family holds it at 0.05 (measured 0.031). This test
    fails on the per-term rule."""
    ids = tuple(f"X{i}" for i in range(6))
    d = with_center_points(fractional_factorial(ids, 5), 4)
    facs = parse_factors([_numeric(i) for i in ids])
    rng = random.Random(6)
    n, per_test, family = 600, 0, 0
    for _ in range(n):
        fit = fit_effects(d, [rng.gauss(0, 1) for _ in d.points], factor_ids=ids)
        per_test += bool(decide_after_screen(fit, facs).surviving)
        sel = screening_family(fit, ids)
        family += bool(decide_after_screen(fit, facs, selection=sel).surviving)
        assert sel["family_size"] == 6 and sel["method"] == "holm"
    assert per_test / n > 0.10
    # Binomial(600, 0.05): sd 0.009, so 0.075 is ~2.8 sd above the level.
    assert family / n <= 0.075


def test_the_family_is_recorded_and_a_dropped_factor_is_never_held(tmp_path):
    """bowl seed 1: Holm drops A at screen (p 0.27). Refine still varies A
    (its composite spans every refinable factor), nothing is held, and
    report.json says so in certificate_scope.screening and error_budget."""
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    recs = sorted(r.work_dir.glob("runs/iter-*/recommendation.json"),
                  key=lambda p: int(p.parent.name.split("-")[1]))
    screen = json.loads(recs[0].read_text())
    sel = screen["screen_selection"]
    assert sel["method"] == "holm" and sel["family_size"] == 2 and sel["alpha"] == 0.05
    assert "A" in sel["dropped"]
    assert sel["factors"]["A"]["p_adjusted"] >= sel["factors"]["A"]["p"]
    refine = [json.loads(p.read_text()) for p in recs
              if json.loads(p.read_text())["stage"] == "refine"][-1]
    assert "A" in refine["fitted_ids"] and refine["held_fixed"] == {}
    sc = r.report["certificate_scope"]["screening"]
    assert sc["dropped"] == sel["dropped"] and sc["held_because_dropped"] == []
    assert sc["model_class"] == 2
    eb = r.report["error_budget"]["screening"]
    assert eb["union_term"] is False and "never held" in eb["statement"]


def test_a_screen_to_confirm_certificate_names_its_model_class(tmp_path):
    """choice_x_numeric routes screen -> confirm (no refinable survivor, no lack
    of fit). The certificate rests on the first-order + 2fi model, and the
    scope says so beside the drop."""
    r = run_synthetic_campaign(SURFACES["choice_x_numeric"](), seed=1, parent_dir=tmp_path)
    sc = r.report["certificate_scope"]
    assert sc["fitting_stage"] == "screen" and sc["screening"]["model_class"] == 1
    assert "first order + 2fi" in sc["statement"]


def test_per_test_is_a_registered_alternative_and_changes_the_hash():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, policy_hash

    a = synthetic_campaign(SURFACES["bowl"]())
    b = synthetic_campaign(SURFACES["bowl"](), design={
        "screen": {"resolution": 5, "center_points": 4, "multiplicity": "per_test"},
        "refine": {"kind": "central_composite", "center_points": 4}})
    pa, pb = compile_policy(a), compile_policy(b)
    assert pa["states"]["screen"]["selection"]["method"] == "holm"
    assert pb["states"]["screen"]["selection"]["method"] == "per_test"
    assert policy_hash(pa) != policy_hash(pb)
