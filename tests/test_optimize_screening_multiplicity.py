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
    assert eb["union_term"] is False and "decide NOTHING downstream" in eb["statement"]


def test_a_screen_to_confirm_certificate_names_its_model_class(tmp_path):
    """refine not in stages: the model half is the first-order + 2fi screen
    model and the scope names model class 1. choice_x_numeric has ONE
    refinable factor (its quadratic is the centre contrast itself, tested at
    full power by lack of fit), so it may certify; additive has two, whose
    quadratics could cancel, so it is withheld (model_class_unchecked)."""
    ov = {"stages": ["verify", "screen", "confirm"]}
    one = run_synthetic_campaign(SURFACES["choice_x_numeric"](), seed=1,
                                 parent_dir=tmp_path / "one", campaign_overrides=ov)
    sc = one.report["certificate_scope"]
    assert sc["fitting_stage"] == "screen" and sc["screening"]["model_class"] == 1
    assert "first-order + 2fi" in sc["statement"]
    assert "model_class_unchecked" not in (one.report.get("certification_withheld") or [])
    two = run_synthetic_campaign(SURFACES["additive"](), seed=1,
                                 parent_dir=tmp_path / "two", campaign_overrides=ov)
    assert "model_class_unchecked" in two.report["certification_withheld"]


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


# ── #321 P4 review HIGH 1: a Type II screen drop must not cost validity ─────

def _false(r) -> bool:
    eps = r.report.get("epsilon")
    return bool(r.report.get("certified")) and eps is not None and r.true_gap > eps + 1e-9


def test_a_masked_saddle_is_never_falsely_certified(tmp_path):
    """f = 10 + xa^2 - xb^2 + 0.036 xb: the pure quadratics cancel, so the
    screen's centre contrast is blind and both main effects are ~0. On
    17b067c the Holm screen dropped both, skipped refine, and certified the
    first-order answer (x_A at the centre, the worst place along A): 12/24
    false over 40 seeds (gap 0.96 vs eps 0.20). Now refine runs whenever a
    refinable factor exists, and nothing is falsely certified."""
    from orchestrator.optimize.synthetic import masked_saddle

    false = refined = 0
    for seed in range(1, 13):
        r = run_synthetic_campaign(masked_saddle(), seed=seed, parent_dir=tmp_path / str(seed))
        false += _false(r)
        refined += "refine" in r.path
    assert false == 0
    assert refined == 12


def test_the_route_is_refine_unless_shown_inert_and_recorded(tmp_path):
    """Holm labels both factors inactive on seed 1 of the masked saddle, yet
    refine runs; the record says the labels decided nothing."""
    from orchestrator.optimize.synthetic import masked_saddle

    r = run_synthetic_campaign(masked_saddle(), seed=1, parent_dir=tmp_path)
    sel = json.loads(sorted(r.work_dir.glob("runs/iter-*/recommendation.json"),
                            key=lambda p: int(p.parent.name.split("-")[1]))[0].read_text())[
        "screen_selection"]
    assert sel["routing"]["rule"] == "refine_unless_shown_inert"
    assert sel["routing"]["refinable"] == ["A", "B"] and sel["routing"]["shown_inert"] == []
    assert sel["m_declared"] == 2
    assert "refine" in r.path


def test_a_screen_only_certificate_with_a_refinable_factor_is_withheld(tmp_path):
    """stages: verify, screen, confirm on the masked saddle -- the model half
    can only be the first-order + 2fi screen model, whose curvature check is
    blind here. On 17b067c this certified falsely; now it is withheld as
    model_class_unchecked, and the terminal bound is still reported."""
    from orchestrator.optimize.synthetic import masked_saddle

    for seed in (1, 2, 3, 4):
        r = run_synthetic_campaign(masked_saddle(), seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides={"stages": ["verify", "screen", "confirm"]})
        assert not r.report.get("certified")
        assert "model_class_unchecked" in (r.report.get("certification_withheld") or [])
        assert r.report.get("residual_regret_terminal") is not None


def test_no_refinable_factor_keeps_screen_only_certification(tmp_path):
    """drift (two two-level numerics: nothing refinable, no curvature to miss)
    still certifies on the screen -> confirm path, never model_class_unchecked."""
    certified = 0
    for seed in range(1, 5):
        r = run_synthetic_campaign(SURFACES["drift"](), seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides={"stages": ["verify", "screen", "confirm"]})
        assert "model_class_unchecked" not in (r.report.get("certification_withheld") or [])
        certified += bool(r.report.get("certified"))
    assert certified >= 1
