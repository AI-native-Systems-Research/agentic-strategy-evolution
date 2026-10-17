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
    r = run_synthetic_campaign(_ramp(8.0), seed=2, parent_dir=tmp_path,
                               campaign_overrides=_SCREEN_CONFIRM)
    assert not r.report["certified"]
    assert r.report["certification_withheld"] == ["heteroscedastic_pure_error"]
    het = _confirmations(r.work_dir)[-1]["global_bound"]["heteroscedasticity"]
    assert het["rejected"] is True and het["p"] < het["alpha"] == 0.05
    assert het["pure_error_cells"] >= 1 and len(het["finalists"]) >= 2


def test_homoscedastic_campaigns_still_certify(tmp_path):
    for seed in (1, 2, 3, 4):
        r = run_synthetic_campaign(_ramp(0.0), seed=seed, parent_dir=tmp_path,
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
    """Structural zeros removed (Hines & O'Hara Hines 2000): at one centre
    cell of 4 and three finalists of 3, the plain median-centred test never
    rejects; this one holds its size and sees a 9x sd ratio."""
    from orchestrator.optimize.noise import brown_forsythe

    rng = random.Random(5)

    def rate(sds, n=2000):
        sizes = [4, 3, 3, 3]
        return sum(
            (brown_forsythe([[s * rng.gauss(0, 1) for _ in range(k)]
                             for s, k in zip(sds, sizes)])["p"] or 1.0) < 0.05
            for _ in range(n)) / n

    assert rate([1, 1, 1, 1]) <= 0.07
    assert rate([0.5, 0.5, 4.5, 0.6]) >= 0.25


def test_brown_forsythe_names_why_it_cannot_run():
    from orchestrator.optimize.noise import brown_forsythe

    assert brown_forsythe([[1.0, 2.0]])["reason"] == "fewer_than_two_groups"
    assert brown_forsythe([[1.0, 1.0], [2.0, 2.0]])["reason"] in (
        "zero_spread", "no_within_group_df")
