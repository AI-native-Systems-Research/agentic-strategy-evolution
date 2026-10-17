"""#321 P3: noise and data-quality checks.

Behavioral only: real campaigns through the synthetic harness (zero LLM calls,
no subprocess), asserting on confirmation.json / report.json, or on the pure
arithmetic of ``orchestrator.optimize.noise``.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import Surface, _numeric


def _confirmations(work_dir) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(
        Path(work_dir).glob("runs/iter-*/confirmation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


# ── item 1: Brown-Forsythe check of M3 ───────────────────────────────────────

def _ramp(h: float, sd0: float = 0.05) -> Surface:
    """A linear ramp whose optimum is the (16, 16) corner, with noise sd
    growing from sd0 at the centre to sd0 * (1 + h) at the corners: the
    pure error (centre replicates) understates the variance exactly where
    the finalists sit, which is the M3 violation."""
    def u(lv, k):
        return (float(lv[k]) - 9.0) / 7.0
    return Surface(
        name="ramp_het", noise_sd=sd0, factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 10 + 0.5 * lv["A"] + 0.3 * lv["B"],
        noise_sd_at=lambda lv: sd0 * (1 + h * (u(lv, "A") ** 2 + u(lv, "B") ** 2) / 2))


_SCREEN_CONFIRM = {"stages": ["verify", "screen", "confirm"]}


def test_heteroscedastic_pure_error_withholds_the_model_half(tmp_path):
    """Before P3 nothing compared the centre replicates' spread with the
    finalists', so this campaign certified: every other gate passes and
    heteroscedastic_pure_error is its ONLY withheld reason."""
    r = run_synthetic_campaign(_ramp(8.0), seed=4, parent_dir=tmp_path,
                               campaign_overrides=_SCREEN_CONFIRM)
    assert not r.report["certified"]
    assert r.report["certification_withheld"] == ["heteroscedastic_pure_error"]
    het = _confirmations(r.work_dir)[-1]["global_bound"]["heteroscedasticity"]
    assert het["rejected"] is True and het["p"] < het["alpha"] == 0.05
    # The SAME seed without the M3 violation certifies: the check, not the
    # draw, is what withheld.
    r0 = run_synthetic_campaign(_ramp(0.0), seed=4, parent_dir=tmp_path / "h0",
                                campaign_overrides=_SCREEN_CONFIRM)
    assert r0.report["certified"], r0.report["certification_withheld"]
    assert het["pure_error_cells"] >= 1 and len(het["finalists"]) >= 2


def test_homoscedastic_campaigns_still_certify(tmp_path):
    for seed in (1, 2, 3, 4):
        r = run_synthetic_campaign(_ramp(0.0), seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides=_SCREEN_CONFIRM)
        assert r.report["certified"], (seed, r.report["certification_withheld"])
        het = _confirmations(r.work_dir)[-1]["global_bound"]["heteroscedasticity"]
        assert het["rejected"] is False


def test_the_check_is_registered_in_the_policy(tmp_path):
    from orchestrator.optimize.policy import compile_policy
    from orchestrator.optimize.harness import synthetic_campaign

    pol = compile_policy(synthetic_campaign(_ramp(0.0)))
    assert pol["objective"]["heteroscedasticity"]["alpha"] == 0.05


def test_brown_forsythe_size_and_power_at_confirm_group_sizes():
    """The one-sided contrast (finalists vs pure error, structural zeros
    removed) holds its size under equal variances and sees a 9x sd ratio at
    confirm's default group sizes (one centre cell of 4, three finalists of
    6); the omnibus F at the same sizes rejects only ~14%."""
    from orchestrator.optimize.noise import brown_forsythe_contrast

    rng = random.Random(5)

    def rate(ratio, n=2000):
        return sum(
            (brown_forsythe_contrast(
                [[rng.gauss(0, 1) for _ in range(4)]],
                [[ratio * rng.gauss(0, 1) for _ in range(6)] for _ in range(3)])["p"]
             or 1.0) < 0.05 for _ in range(n)) / n

    assert rate(1.0) <= 0.05 + 2 * (0.05 * 0.95 / 2000) ** 0.5
    assert rate(9.0) >= 0.6
    assert rate(1 / 3) <= 0.01       # one-sided: a LOUDER centre is safe


def test_brown_forsythe_names_why_it_cannot_run():
    from orchestrator.optimize.noise import brown_forsythe

    assert brown_forsythe([[1.0, 2.0]])["reason"] == "fewer_than_two_groups"
    assert brown_forsythe([[1.0, 1.0], [2.0, 2.0]])["reason"] in (
        "zero_spread", "no_within_group_df")


# ── A5 condition: pre-P3 policies reproduce ──────────────────────────────────

def test_a_pre_p3_policy_reanalyzes_identically(tmp_path):
    """A campaign compiled the way pre-P3 Nous compiled it (no
    terminal_robustness / heteroscedasticity keys, confirm replicates 3) is
    re-derived byte-identically by the current code: reanalysis recognises the
    old policy and recompiles it as registered."""
    from orchestrator.optimize import policy as policy_mod
    from orchestrator.optimize.reanalyze import reanalyze
    from orchestrator.optimize.synthetic import SURFACES

    tok = policy_mod.LEGACY_PRE_P3.set(True)
    try:
        r = run_synthetic_campaign(SURFACES["bowl"](), seed=7, parent_dir=tmp_path)
    finally:
        policy_mod.LEGACY_PRE_P3.reset(tok)
    pol = json.loads((r.work_dir / "policy.json").read_text())
    assert "terminal_robustness" not in pol["objective"]
    assert pol["states"]["confirm"]["design"]["replicates"] == 3
    res = reanalyze(r.work_dir)
    assert res.legacy_pre_p3 and res.identical, res.differences


def test_the_default_confirm_replicates_is_the_floor_and_the_preview_shows_it():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, replicate_floor
    from orchestrator.optimize.preview import build_preview
    from orchestrator.optimize.synthetic import SURFACES

    c = synthetic_campaign(SURFACES["bowl"]())
    pol = compile_policy(c)
    assert replicate_floor(c["optimization"]) == 6
    assert pol["states"]["confirm"]["design"]["replicates"] == 6
    assert pol["objective"]["terminal_robustness"]["floor"] == 6
    pv = build_preview(c, noise_sd=None, mean=None, run_secs=None)
    conf = next(s for s in pv.stages if s.stage == "confirm")
    assert conf.runs == 18 and "x 6 replicate(s)" in conf.note


def test_a_budget_that_cannot_cover_one_confirm_round_fails_validation():
    from orchestrator.validate import _rule32_confirm_replicate_floor

    opt = {"response": {"primary": {"metric": "m"}},
           "design": {"max_runs": 17}}
    errs = _rule32_confirm_replicate_floor(opt)
    assert any("cannot cover one confirm round" in e and not e.startswith("WARN")
               for e in errs), errs
    assert not _rule32_confirm_replicate_floor(
        {"response": {"primary": {"metric": "m"}}, "design": {"max_runs": 60}})
    warn = _rule32_confirm_replicate_floor(
        {"response": {"primary": {"metric": "m"}}, "design": {"confirm": {"replicates": 3}}})
    assert warn and warn[0].startswith("WARN") and "below the replicate floor 6" in warn[0]


# ── item 2 (A5): diagnostics, floor, robust bound ───────────────────────────

def test_a_campaign_below_the_replicate_floor_withholds_by_name(tmp_path):
    """Before P3 a 3-replicate confirm certified this bowl; at n = 3 no
    terminal bound holds its level under skewed heteroscedastic noise
    (Monte Carlo 0.13 for Welch), so it is now withheld, named."""
    from orchestrator.optimize.synthetic import SURFACES

    ov = {"design": {"screen": {"resolution": 5, "center_points": 4},
                     "refine": {"kind": "central_composite", "center_points": 4},
                     "confirm": {"replicates": 3}}}
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides=ov)
    assert r.report["certification_withheld"] == ["replicates_below_floor"]
    diag = _confirmations(r.work_dir)[-1]["noise_diagnostics"]
    assert diag["floor"] == 6 and diag["n_min"] == 3
    f = diag["finalists"]["f0"]
    assert f["n"] == 3 and f["variance"] > 0 and f["skewness"] is not None
    assert diag["variance_ratio"] >= 1.0


def test_the_default_campaign_records_its_diagnostics_and_certifies(tmp_path):
    from orchestrator.optimize.synthetic import SURFACES

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    assert r.report["certified"], r.report["certification_withheld"]
    c = _confirmations(r.work_dir)[-1]
    diag = c["noise_diagnostics"]
    assert diag["withheld"] == [] and diag["n_min"] == 6
    assert c["terminal_bound"]["method"] == "bonferroni_max_welch_bootstrap_t"
    for k, v in diag["per_challenger"].items():
        assert c["residual_regret_terminal"] >= max(v["t"], v["robust"]) - 1e-12 \
            or c["residual_regret_terminal"] == 0.0


def test_skewed_replicates_withhold_noise_skewed():
    """A finalist set whose replicates are visibly right-skewed (one large
    value per finalist, n = 8) passes the t bound but is withheld."""
    from orchestrator.optimize.certificate import (robust_terminal_bound,
                                                   terminal_regret_bound)

    rng = random.Random(3)
    s = {f"f{i}": [mu + rng.expovariate(1.0) ** 3 for _ in range(8)]
         for i, mu in enumerate((10.0, 9.0, 8.0))}
    best = max(s, key=lambda k: sum(s[k]))
    rb, rec = robust_terminal_bound(s, best, delta=0.05, direction="maximize",
                                    paired=False, rule={"floor": 6, "skew_alpha": 0.25})
    assert "noise_skewed" in rec["withheld"], rec["skewness_test"]
    assert terminal_regret_bound(s, best, delta=0.05, direction="maximize",
                                 paired=False).value is not None


def test_the_sign_flip_bound_is_exact_for_symmetric_differences():
    """Hartigan (1969): coverage of the k-th largest subset mean is exactly
    1 - k 2^-n for continuous symmetric errors -- here Laplace, n = 6,
    alpha = 0.05 -> k = 3, nominal 1 - 3/64 = 0.953."""
    from orchestrator.optimize.noise import sign_flip_upper

    rng = random.Random(9)
    n_trials, miss = 4000, 0
    for _ in range(n_trials):
        d = [rng.choice((-1, 1)) * rng.expovariate(1.0) for _ in range(6)]
        miss += sign_flip_upper(d, 0.05) < 0.0
    se = (3 / 64 * (1 - 3 / 64) / n_trials) ** 0.5
    assert abs(miss / n_trials - 3 / 64) <= 3 * se
    assert sign_flip_upper([1.0] * 4, 0.05) is None     # 2^-4 > 0.05: no bound
