"""WP-A: what a certificate CLAIMS (spec 2026-10-17-certification-soundness.md).

Behavioral only: every test drives real campaigns through the synthetic
harness (zero LLM calls, no subprocess) and asserts on report.json /
confirmation.json, or on the pure arithmetic of ``certificate``.

A1  certified needs R_model_outside + R_terminal <= epsilon (the delta_s half)
A2  alpha-spending over confirm looks, refill look included
A3  the known_valid_baseline is a permanent reference finalist; gain + CI
A4  the certificate's scope (held factors) is recorded
"""
from __future__ import annotations

import dataclasses
import json
import random
from pathlib import Path

from orchestrator.optimize import certificate
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES

SEEDS = range(1, 9)


def _confirmations(work_dir) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(
        Path(work_dir).glob("runs/iter-*/confirmation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


def _false_cert(res) -> bool:
    eps = res.report.get("epsilon")
    return bool(res.report.get("certified")) and eps is not None and res.true_gap > eps + 1e-9


# ── A1 ───────────────────────────────────────────────────────────────────────

def test_a_wide_model_bound_withholds_the_certificate(tmp_path):
    """Before WP-A, bowl at 8x noise, seed 27, certified a configuration 0.50
    below the optimum (epsilon 0.40) on R_terminal = 0.34 alone, while the
    model bound over the candidates screening did not shortlist was 1.39. The
    delta_s half of the claim was never read. Now it is: withheld, named."""
    s = dataclasses.replace(SURFACES["bowl"](), noise_sd=0.4)
    r = run_synthetic_campaign(s, seed=27, parent_dir=tmp_path)
    assert r.true_gap > r.report["epsilon"]
    assert not r.report["certified"]
    assert "model_bound_above_epsilon" in r.report["certification_withheld"]
    gb = _confirmations(r.work_dir)[-1]["global_bound"]
    assert gb["value"] == gb["residual_regret_model_outside"] + gb["residual_regret_terminal"]
    assert gb["value"] > r.report["epsilon"]


def test_a_certificate_states_both_halves_within_epsilon(tmp_path):
    """Every certificate on a surface the model describes carries a global
    bound at or below epsilon, with the fitted argmax measured this round."""
    n = 0
    for seed in SEEDS:
        r = run_synthetic_campaign(SURFACES["bowl"](), seed=seed,
                                   parent_dir=tmp_path / str(seed))
        assert not _false_cert(r)
        if r.report["certified"]:
            n += 1
            gb = _confirmations(r.work_dir)[-1]["global_bound"]
            assert gb["x_hat_key"] is not None
            assert gb["value"] <= r.report["epsilon"]
    assert n >= 6


def test_the_model_bound_outside_a_shortlist_drops_only_measured_members():
    prof = {"top": [{"levels": {"A": 1}, "bound": 0.9},
                    {"levels": {"A": 2}, "bound": 0.3}], "rest": 0.1, "challengers": 5}
    assert certificate.model_bound_outside(prof, [{"A": 1}]) == 0.3
    assert certificate.model_bound_outside(prof, [{"A": 1}, {"A": 2}]) == 0.1
    assert certificate.model_bound_outside(prof, []) == 0.9
    assert certificate.model_bound_outside(
        {"top": [{"levels": {"A": 1}, "bound": -2.0}], "rest": None, "challengers": 1},
        []) == 0.0


# ── A2 ───────────────────────────────────────────────────────────────────────

def test_every_confirm_look_is_charged(tmp_path):
    """confirm_max_rounds: 4 used to judge EVERY round at the full
    delta_terminal (4 looks at 0.05 certified wrongly at 0.108 in the stage-0
    Monte Carlo). Each look is now taken at delta_terminal / 4."""
    r = run_synthetic_campaign(
        dataclasses.replace(SURFACES["additive"](), noise_sd=0.4), seed=1,
        parent_dir=tmp_path, campaign_overrides={"policy": {"confirm_max_rounds": 4}},
        max_iterations=10)
    confs = _confirmations(r.work_dir)
    assert confs
    for c in confs:
        assert c["alpha_spending"]["looks"] == 4
        assert c["delta_terminal"] == c["terminal_bound"]["delta"] == 0.05 / 4


def test_the_refill_look_is_charged_before_it_is_taken(tmp_path):
    """A constrained campaign registers the refill branch, which buys one
    look beyond the round cap; the per-look level is fixed up front."""
    ov = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                       "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]}}
    r = run_synthetic_campaign(SURFACES["sla"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides=ov)
    for c in _confirmations(r.work_dir):
        assert c["alpha_spending"]["looks"] == 2
        assert c["delta_terminal"] == 0.05 / 2


def test_spending_holds_the_sequential_error_at_delta():
    """The arithmetic the looks rely on: two finalists a hair more than
    epsilon apart, n=3, Gaussian, up to 4 looks, certify on the first look
    whose bound is within epsilon. At delta/looks the family-wise false
    certification stays at or below delta (stage-0: 0.108 at full delta)."""
    rng = random.Random(7)
    eps, delta, looks, trials, wrong = 0.5, 0.05, 4, 4000, 0
    for _ in range(trials):
        for _look in range(looks):
            s = {"a": [rng.gauss(0.0, 1.0) for _ in range(3)],
                 "b": [rng.gauss(eps + 1e-3, 1.0) for _ in range(3)]}
            best = max(s, key=lambda k: sum(s[k]))
            b = certificate.terminal_regret_bound(s, best, delta=delta / looks,
                                                  direction="maximize", paired=False)
            if b.value is not None and b.value <= eps:
                wrong += best == "a"
                break
    assert wrong / trials <= delta


# ── A3 ───────────────────────────────────────────────────────────────────────

def test_the_baseline_is_a_reference_finalist_with_a_gain_interval(tmp_path):
    """known_valid_baseline is seated in every round beside the shortlist and
    report.json carries the winner's gain over it as a selection-proof
    interval, from the confirm replicates, that covers the truth. (Unpaired
    here: the synthetic target's seeded workload draw is identical across
    finalists, so its paired differences have zero spread and the interval
    is correctly reported as not estimable.)"""
    s = dataclasses.replace(SURFACES["bowl"](), noise_sd=0.4)
    base = {"A": 2, "B": 2}
    covered = 0
    for seed in SEEDS:
        r = run_synthetic_campaign(
            s, seed=seed, parent_dir=tmp_path / str(seed),
            campaign_overrides={"known_valid_baseline": base})
        conf = _confirmations(r.work_dir)[-1]
        assert any(f["levels"] == base for f in conf["finalists"])
        assert len(conf["finalists"]) == 4          # 3 seats + the reference
        g = r.report["gain_over_baseline"]
        assert g["method"] == "simultaneous_two_sided_welch_t"
        true = s.fn(r.recommendation) - s.fn(base)
        covered += g["low"] <= true <= g["high"]
    assert covered >= 7


def test_no_baseline_means_no_reference_seat(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    assert len(_confirmations(r.work_dir)[-1]["finalists"]) == 3
    assert "gain_over_baseline" not in r.report


# ── A4 ───────────────────────────────────────────────────────────────────────

def test_the_certificate_scope_names_the_held_factors(tmp_path):
    """additive holds its choice factor C at the screen's best for refine, so
    the model half ranged over the C=on slice only, and report.json says so."""
    r = run_synthetic_campaign(SURFACES["additive"](), seed=1, parent_dir=tmp_path)
    sc = r.report["certificate_scope"]
    assert sc["region"] == "slice"
    assert sc["held_fixed"] == {"C": "on"}
    assert "NOT covered" in sc["statement"]
    from orchestrator.optimize.report_md import write_report_markdown

    write_report_markdown(r.work_dir)
    md = (Path(r.work_dir) / "report.md").read_text()
    assert "Certificate scope:" in md and "`C=on`" in md


def test_a_full_space_fit_is_scoped_to_the_declared_space(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    assert r.report["certificate_scope"]["region"] == "declared_space"
    assert r.report["certificate_scope"]["held_fixed"] == {}


# ── INV-SEM20 ────────────────────────────────────────────────────────────────

def test_inv_sem20_holds_on_oracle_campaigns_and_has_teeth(tmp_path):
    from orchestrator.optimize.invariants import check_certificate_global_bound as chk

    for name in ("bowl", "additive", "sla"):
        r = run_synthetic_campaign(SURFACES[name](), seed=1, parent_dir=tmp_path / name)
        for c in _confirmations(r.work_dir):
            assert chk(c) == [], (name, chk(c))
    good = {"certified": True, "epsilon": 0.4, "delta_terminal": 0.025,
            "alpha_spending": {"delta_terminal_declared": 0.05, "looks": 2,
                               "per_look": 0.025, "rule": ""},
            "global_bound": {"value": 0.3, "residual_regret_model_outside": 0.2,
                             "residual_regret_terminal": 0.1, "x_hat_key": "f0"}}
    assert chk(good) == []
    assert chk({**good, "global_bound": None})
    assert chk({**good, "epsilon": 0.2})
    assert chk({**good, "delta_terminal": 0.05})
    assert chk({**good, "global_bound": {**good["global_bound"], "x_hat_key": None}})
    assert chk({**good, "alpha_spending": {**good["alpha_spending"], "per_look": 0.05},
                "delta_terminal": 0.05})


def test_the_gain_interval_reports_the_coverage_it_guarantees_after_stopping(tmp_path):
    """The interval is computed at the per-look level, but the round reported
    is the one the campaign STOPPED at, and stopping depends on that round's
    data: over 4 registered looks only 1 - delta_terminal is guaranteed, not
    1 - delta_terminal/4. report.md must print the guaranteed level."""
    from orchestrator.optimize.report_md import render_report_markdown

    s = dataclasses.replace(SURFACES["bowl"](), noise_sd=0.4)
    r = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={"known_valid_baseline": {"A": 2, "B": 2},
                            "policy": {"confirm_max_rounds": 4}})
    g = r.report["gain_over_baseline"]
    delta_t = json.loads((r.work_dir / "policy.json").read_text())["objective"]["delta_terminal"]
    assert g["delta_guaranteed"] == delta_t
    assert g["delta_per_look"] < delta_t          # spent across the looks
    md = render_report_markdown(r.work_dir)
    assert f"coverage >= {1 - delta_t:.3g}" in md
    assert f"{1 - g['delta_per_look']:.3g} interval" not in md
