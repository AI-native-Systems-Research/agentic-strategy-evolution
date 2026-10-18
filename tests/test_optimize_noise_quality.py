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
        r = run_synthetic_campaign(SURFACES["bowl"](), seed=7, parent_dir=tmp_path,
                                   campaign_overrides={"design": {
                                       "screen": {"resolution": 5, "center_points": 4},
                                       "refine": {"kind": "central_composite",
                                                  "center_points": 4},
                                       "confirm": {"replicates": 3}}})
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


# ── item 4: CRN verification ────────────────────────────────────────────────

_WL = {"workload": {"seed_env": "NOUS_WORKLOAD_SEED"}}


def test_a_seed_the_target_ignores_fails_verify(tmp_path):
    """Before P3 nothing checked that seed_env reached the target: a target
    that ignores it ran a campaign recording paired: true for comparisons
    that paired nothing. Verify now probes and refuses, named."""
    from orchestrator.optimize.synthetic import SURFACES

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides=_WL,
                               runner_options={"workload_sd": 1.0, "ignore_seed": True})
    assert r.path and r.path[0].startswith("aborted:") and "DECORATIVE" in r.path[0]
    probe = json.loads((r.work_dir / "crn_probe.json").read_text())
    assert probe["verdict"] == "decorative" and probe["seeds"] == 4
    assert not _confirmations(r.work_dir)


def test_a_seed_that_drives_the_workload_passes_and_pairs_with_spread(tmp_path):
    """End to end, paired gain intervals with NONZERO spread: a workload term
    (sd 1.0) shared by every finalist at a seed, plus independent run noise.
    The probe passes; confirm pairs; the paired differences have spread, and
    the baseline-gain interval is a real interval, not a point."""
    from orchestrator.optimize.synthetic import SURFACES

    ov = dict(_WL, known_valid_baseline={"A": 2, "B": 2})
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path,
                               campaign_overrides=ov,
                               runner_options={"workload_sd": 1.0})
    probe = json.loads((r.work_dir / "crn_probe.json").read_text())
    assert probe["verdict"] == "real" and probe["p"] < 0.05
    c = _confirmations(r.work_dir)[-1]
    assert c["paired"] is True
    assert c["terminal_bound"]["method"].endswith("paired_sign_flip")
    g = c["gain_over_baseline"]
    assert g["method"] == "simultaneous_two_sided_paired_t"
    assert g["high"] - g["low"] > 1e-6          # nonzero spread
    true_gain = SURFACES["bowl"]().fn(c["confirmed_at_levels"]) - SURFACES["bowl"]().fn({"A": 2, "B": 2})
    assert g["low"] <= true_gain <= g["high"]
    # The workload term is 20x the run noise; unpaired, the interval would be
    # an order of magnitude wider.
    fin = {f["key"]: f["samples"] for f in c["finalists"]}
    from statistics import stdev
    d = [a - b for a, b in zip(fin[g["winner_key"]], fin[g["baseline_key"]])]
    assert stdev(d) < 0.5 * stdev(fin[g["baseline_key"]])


def test_the_probe_verdict_is_an_anova_on_the_seed():
    from orchestrator.optimize.noise import crn_probe_verdict

    assert crn_probe_verdict([(1.0, 1.0), (2.0, 2.0)])["verdict"] == "real"
    assert crn_probe_verdict([(1.0, 1.0), (1.0, 1.0)])["verdict"] == "decorative"
    assert crn_probe_verdict([(1.0, 1.1)])["verdict"] == "not_testable"
    v = crn_probe_verdict([(0.0, 0.1), (5.0, 5.1), (-3.0, -2.9), (8.0, 8.2)])
    assert v["verdict"] == "real" and v["df"] == [3, 4]
    v = crn_probe_verdict([(0.0, 1.0), (1.0, 0.0), (0.5, -0.5), (-0.5, 0.5)])
    assert v["verdict"] == "decorative"


def test_the_probe_can_be_waived_in_writing(tmp_path):
    from orchestrator.optimize.synthetic import SURFACES

    ov = {"workload": {"seed_env": "NOUS_WORKLOAD_SEED", "probe": False}}
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                               campaign_overrides=ov,
                               runner_options={"workload_sd": 1.0, "ignore_seed": True})
    assert not r.path[0].startswith("aborted:")
    assert json.loads((r.work_dir / "crn_probe.json").read_text())["waived"]


# ── item 5: oracle 2(c) as TOST ──────────────────────────────────────────────

def test_the_old_relative_mean_rule_passed_an_undecidable_control():
    """The concrete input that makes the old rule false: 3 replicates per side,
    run-to-run sd 3x the tolerance, means 1% apart. The old rule declared the
    control unchanged (|1%| <= 5%); the evidence cannot exclude a 5% shift in
    either direction, so the TOST does not show equivalence."""
    from orchestrator.optimize.noise import tost_ratio
    from orchestrator.optimize.stage_runner import _baseline_equivalent

    pre = [100.0, 85.0, 115.0]
    post = [101.0, 86.0, 116.0]
    assert _baseline_equivalent(sum(pre) / 3, sum(post) / 3, 5.0) is True   # old
    r = tost_ratio(pre, post, margin_frac=0.05, paired=False)
    assert r["equivalent"] is False and r["p"] > 0.05


def test_tost_ratio_holds_its_size_at_the_margin_and_pairs_under_crn():
    from orchestrator.optimize.noise import tost_ratio

    rng = random.Random(4)

    def rate(shift, paired, n=6, trials=4000):
        ok = 0
        for _ in range(trials):
            w = [20.0 * rng.gauss(0, 1) for _ in range(n)]       # workload draw
            pre = [100 + wi + rng.gauss(0, 1) for wi in w]
            post = [100 * (1 + shift) + (wi if paired else 20.0 * rng.gauss(0, 1))
                    + rng.gauss(0, 1) for wi in w]
            ok += tost_ratio(pre, post, margin_frac=0.03, paired=paired)["equivalent"] is True
        return ok / trials

    se = (0.05 * 0.95 / 4000) ** 0.5
    for paired in (False, True):
        assert rate(0.03, paired) <= 0.05 + 2 * se          # size at the margin
    # A workload term 20x the run noise: unpaired cannot show equivalence,
    # paired (CRN) can -- the reason the paired form exists.
    assert rate(0.0, paired=True) >= 0.95
    assert rate(0.0, paired=False) <= 0.10


def test_a_pre_p3_build_record_keeps_the_old_rule(tmp_path, monkeypatch):
    """Reproducibility: a baseline_equivalence.json written before P3 carries
    no `equivalence` key, and verify judges it by the relative-mean rule it
    registered."""
    from orchestrator.optimize.stage_runner import _check_baseline_equivalence
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    from orchestrator.optimize.factors import parse_factors

    s = SURFACES["bowl"]()
    c = {"optimization": {"response": {"primary": {"metric": "m"}},
                          "factors": list(s.factors)}}
    (tmp_path / "baseline_equivalence.json").write_text(json.dumps(
        {"levels": {"A": 2, "B": 2}, "pre": [13.55, 13.6, 13.5],
         "pre_mean": 13.55, "tolerance_pct": 5.0}))
    _check_baseline_equivalence(c, tmp_path, parse_factors(list(s.factors)),
                                make_synthetic_runner(s, seed=1))
    rec = json.loads((tmp_path / "baseline_equivalence.json").read_text())
    assert rec["ok"] is True and "tost" not in rec and "equivalence" not in rec


# ── item 3 (A6): outliers, censoring, constraint semantics ──────────────────

def _bowl_with_spike(spike_run: int, size: float):
    """A planted outlier: the bowl, with run number `spike_run` shifted."""
    import orchestrator.optimize.synthetic as S

    orig = S._observe

    def obs(surface, levels, *, rng, run_counter):
        o = orig(surface, levels, rng=rng, run_counter=run_counter)
        if run_counter == spike_run and isinstance(o.get("m"), float):
            o["m"] += size
        return o
    return orig, obs


def test_a_planted_outlier_is_flagged_never_deleted_with_a_sensitivity_refit(
        tmp_path, monkeypatch):
    """Before P3 effects.json carried no outlier flag at all: a 60-sd spike in
    one refine row went into every coefficient unremarked. It is now flagged
    by its externally studentized residual (Bonferroni), kept in the fit, and
    a refit without it records whether the recommendation changes."""
    import orchestrator.optimize.synthetic as S
    from orchestrator.optimize.synthetic import SURFACES

    _orig, spiked = _bowl_with_spike(17, 3.0)
    monkeypatch.setattr(S, "_observe", spiked)
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    eff = [json.loads(p.read_text()) for p in r.work_dir.glob("runs/iter-*/effects.json")]
    refine = next(e for e in eff if e["stage"] == "refine")
    o = refine["outliers"]
    assert o["flagged_rows"] and o["deleted"] is False
    assert o["threshold"] > 3.0              # Bonferroni, not a per-row 1.96
    flagged = o["flagged_rows"][0]
    assert abs(o["studentized"][flagged]) > o["threshold"]
    assert refine["n_runs"] == len(o["studentized"])     # nothing deleted
    sens = o["sensitivity"]
    assert sens["rows_dropped"] == o["flagged_rows"]
    assert isinstance(sens["decision_changes"], bool)


def test_no_flag_on_clean_rows_and_no_flag_on_misfit(tmp_path):
    from orchestrator.optimize.synthetic import SURFACES

    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    eff = {e["stage"]: e for e in (json.loads(p.read_text())
                                   for p in r.work_dir.glob("runs/iter-*/effects.json"))}
    assert eff["refine"]["outliers"]["flagged_rows"] == []
    # The 2^2 screen of a bowl rejects its first-order model: the corner
    # residuals ARE the curvature, so the test declines, named.
    assert eff["screen"]["outliers"]["reason"] == "lack_of_fit_rejected"
    assert eff["screen"]["outliers"]["flagged_rows"] == []


def test_the_bonferroni_flag_holds_its_family_wise_level():
    from orchestrator.optimize.noise import studentized_outliers

    rng = random.Random(8)
    n, trials, hits = 13, 2000, 0
    xs = [(-1, -1), (1, -1), (-1, 1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)] + [(0, 0)] * 5
    cols = [[1.0] * n, [float(a) for a, _ in xs], [float(b) for _, b in xs],
            [float(a * b) for a, b in xs], [float(a * a) for a, _ in xs],
            [float(b * b) for _, b in xs]]
    for _ in range(trials):
        ys = [rng.gauss(0, 1) for _ in range(n)]
        hits += bool(studentized_outliers(cols, ys)["flagged"])
    assert hits / trials <= 0.05 + 2 * (0.05 * 0.95 / trials) ** 0.5


def test_a_timeout_is_right_censored_never_imputed(tmp_path, monkeypatch):
    """Before P3 a timed-out row was 'failed' with nothing saying what it
    implied. It now records right-censoring at run_timeout_sec and the bound,
    is never imputed, and the finalist it hit still withholds."""
    from orchestrator.optimize import runner as runner_mod
    from orchestrator.optimize import synthetic as S
    from orchestrator.optimize.synthetic import SURFACES

    real = S.make_synthetic_runner

    def timing_out(surface, **kw):
        run = real(surface, **kw)

        def r(row):
            if getattr(row, "role", "") == "finalist" or (row.apply or {}).get("finalist") == 0:
                if row.replicate == 1:
                    raise runner_mod.ConfigRunFailure("killed at the ceiling", kind="timeout")
            return run(row)
        return r
    monkeypatch.setattr("orchestrator.optimize.harness.make_synthetic_runner", timing_out)
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path)
    rows = [json.loads(ln) for p in r.work_dir.glob("runs/iter-*/runs.jsonl")
            for ln in p.read_text().splitlines() if ln.strip()]
    cens = [x for x in rows if x.get("failure_kind") == "timeout"]
    assert cens and all(x["censored"]["censored"] == "right" and x["censored"]["imputed"] is False
                        and x["censored"]["at_sec"] for x in cens)
    assert all(x["response"] == {} for x in cens)                 # no value imputed
    c = _confirmations(r.work_dir)[0]
    assert c["censored_replicates"] and "finalist_unmeasured" in c["certification_withheld"]


def _stall_campaign(semantics: str | None, tmp_path, seed=1, value=10.0, **extra):
    from orchestrator.optimize.synthetic import SURFACES

    c = {"metric": "stall_ms", "op": "<=", "value": value}
    if semantics:
        c["semantics"] = semantics
    ov = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                       "constraints": [c]},
          "stages": ["verify", "screen", "confirm"], **extra}
    return run_synthetic_campaign(SURFACES["stochastic_constraint_boundary"](), seed=seed,
                                  parent_dir=tmp_path / f"{semantics}-{seed}-{value}",
                                  campaign_overrides=ov, max_iterations=12)


def test_mean_semantics_judges_the_configuration_not_one_run(tmp_path):
    """Before P3 a constraint could only mean 'every replicate passes'. With
    stall_ms ~ N(10.3, 1) in the high region and a threshold of 12.5, one of
    seven replicates of a finalist lands above it and every_replicate strikes
    the finalist off (withheld). Under `mean` the configuration's mean is
    SHOWN below the threshold by a one-sided t bound at delta_feasibility /
    (S C L), and the campaign certifies -- with the term in the stated budget."""
    old = _stall_campaign(None, tmp_path, seed=1, value=12.5)
    assert "finalist_measured_infeasible" in old.report["certification_withheld"]
    r = _stall_campaign("mean", tmp_path, seed=1, value=12.5)
    assert r.report["certified"], r.report["certification_withheld"]
    c = _confirmations(r.work_dir)[0]
    df = c["distributional_feasibility"]
    assert df["delta_feasibility"] == r.report["delta_feasibility"] == 0.05
    assert abs(df["per_test_level"] - 0.05 / (len(c["finalists"]) * df_looks(r))) < 1e-12
    for k, v in df["finalists"].items():
        assert v["shown_feasible"]
        (cv,) = v["constraints"]
        assert cv["method"] == "one_sided_t_on_the_mean" and cv["bound"] < 12.5
    eb = r.report["error_budget"]["epochs"][-1]
    assert abs(eb["spent"] - (r.report["delta_screen"] + r.report["delta_terminal"]
                              + (r.report.get("delta_constraint") or 0.0) + 0.05)) < 1e-12
    assert eb["delta_feasibility"] == 0.05


def df_looks(r):
    pol = json.loads((r.work_dir / "policy.json").read_text())
    from orchestrator.optimize.policy import confirm_looks
    return confirm_looks(pol)


def test_chance_semantics_is_a_clopper_pearson_bound():
    from orchestrator.optimize.noise import feasibility_shown

    c = {"metric": "x", "op": "<=", "value": 1.0, "semantics": "chance:0.2"}
    v = feasibility_shown(c, [0.0] * 6, level=0.05)
    # 0 violations of 6: CP upper = 1 - 0.05^(1/6) = 0.393 > 0.2 -> not shown.
    assert abs(v["upper"] - (1 - 0.05 ** (1 / 6))) < 1e-9 and v["shown"] is False
    assert v["min_replicates"] == 14
    v = feasibility_shown(c, [0.0] * 14, level=0.05)
    assert v["shown"] is True and v["violations"] == 0
    v = feasibility_shown(c, [0.0] * 13 + [2.0], level=0.05)
    assert v["violations"] == 1 and v["shown"] is False


def test_every_replicate_stays_the_default_and_is_unchanged(tmp_path):
    from orchestrator.optimize.policy import compile_policy
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    camp = synthetic_campaign(SURFACES["stochastic_constraint_boundary"](),
                              response={"primary": {"metric": "m", "direction": "maximize"},
                                        "constraints": [{"metric": "stall_ms", "op": "<=",
                                                         "value": 10}]})
    assert "delta_feasibility" not in compile_policy(camp)["objective"]
