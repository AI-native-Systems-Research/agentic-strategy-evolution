"""Item 4 of #321: held-out seeds on the winner.

Before: every number in report.json came from workload draws the campaign also
selected on, so a mechanism (or a build agent) tuned to those draws looked as
good as one that generalises. Now ``workload.held_out_seeds`` runs the winner
and the baseline, paired, on seeds no measured row used, AFTER the answer is
fixed, and reports that gain separately; it never feeds a decision.

The concrete breaking input: a target where the winner's advantage exists only
on the seeds the campaign measured (an overfit). In-sample gain is large; the
held-out gain must expose it, and nothing else in the report may move.
Behavioral, zero LLM.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize import harness
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.preview import build_preview, format_preview
from orchestrator.optimize.reanalyze import reanalyze
from orchestrator.optimize.report_md import render_report_markdown
from orchestrator.optimize.synthetic import SURFACES
from orchestrator.validate import validate_optimization_campaign

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "orchestrator"
                     / "schemas" / "report.schema.json").read_text())
BASE = {"A": 2, "B": 2}
HELD = [900001, 900002, 900003, 900004]
_REAL_RUNNER = harness.make_synthetic_runner


def _wl(held=HELD):
    return {"seed_env": "NOUS_WORKLOAD_SEED", **({"held_out_seeds": held} if held else {})}


def _overfit_target(monkeypatch, *, penalty: float):
    """Wrap the synthetic runner: per-(config, seed) noise so paired gains have
    spread, and `penalty` subtracted from every NON-baseline configuration on a
    held-out seed (the winner only looks good on draws it was selected on)."""
    real = _REAL_RUNNER

    def make(surface, *, seed, seed_env=None, **kw):
        inner = real(surface, seed=seed, seed_env=seed_env, **kw)

        def run(row):
            obs = dict(inner(row))
            s = ((getattr(row, "apply", None) or {}).get("env") or {}).get(seed_env)
            h = hashlib.sha256(f"{sorted(row.levels.items())}|{s}".encode()).digest()
            obs["m"] = obs["m"] + (h[0] / 255.0 - 0.5) * 0.2
            if s in HELD and dict(row.levels) != BASE:
                obs["m"] -= penalty
            return obs
        return run

    monkeypatch.setattr(harness, "make_synthetic_runner", make)


def _run(tmp_path, monkeypatch, *, penalty=0.0, held=HELD, baseline=BASE, name="r"):
    _overfit_target(monkeypatch, penalty=penalty)
    ov = {"workload": _wl(held)}
    if baseline:
        ov["known_valid_baseline"] = baseline
    return run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path / name,
                                  campaign_overrides=ov)


def test_the_winner_is_measured_on_unseen_seeds_after_the_answer(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch)
    jsonschema.validate(r.report, SCHEMA)
    hs = r.report["held_out_seeds"]
    assert hs["declined"] is None and hs["feeds_certification"] is False
    assert hs["unseen"] is True and hs["seeds"] == HELD
    assert hs["winner"] == r.report["recommendation"]["levels"] and hs["baseline"] == BASE
    rows = [json.loads(ln) for ln in
            (r.work_dir / hs["file"]).read_text().splitlines()]
    assert len(rows) == 2 * len(HELD) == hs["runs"]
    assert {(x["arm"], x["seed"]) for x in rows} == {
        (a, s) for a in ("winner", "baseline") for s in HELD}
    g = hs["gain"]
    assert g["n_pairs"] == 4 and g["low"] < g["estimate"] < g["high"]
    # Not one held-out row is inside runs/iter-*: nothing that fits reads them.
    for p in r.work_dir.glob("runs/iter-*/runs.jsonl"):
        assert not any(json.loads(ln)["row_index"] <= -100_000
                       for ln in p.read_text().splitlines() if ln.strip())
    assert "## Held-out seeds" in render_report_markdown(r.work_dir)


def test_an_overfit_winner_is_exposed_and_no_decision_moves(tmp_path, monkeypatch):
    clean = _run(tmp_path, monkeypatch, penalty=0.0, name="clean")
    over = _run(tmp_path, monkeypatch, penalty=50.0, name="over")
    gc, go = clean.report["held_out_seeds"]["gain"], over.report["held_out_seeds"]["gain"]
    assert go["estimate"] == pytest.approx(gc["estimate"] - 50.0)
    assert go["high"] < 0 < over.report["gain_over_baseline"]["low"], \
        "the in-sample gain is positive while the held-out gain is negative"
    strip = lambda rep: {k: v for k, v in rep.items()  # noqa: E731
                         if k not in ("held_out_seeds", "provenance")}
    assert strip(clean.report) == strip(over.report), "a held-out seed moved a decision"


def test_reanalysis_replays_the_block_and_executes_nothing(tmp_path, monkeypatch):
    import subprocess

    r = _run(tmp_path, monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("shelled out")))
    res = reanalyze(r.work_dir)
    assert res.identical, res.differences
    assert any(f.startswith("held_out_seeds.epoch-") for f in res.not_rederived)


def test_a_reanalysis_without_the_rows_declines_by_name(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch)
    (r.work_dir / r.report["held_out_seeds"]["file"]).unlink()
    res = reanalyze(r.work_dir)
    assert not res.identical
    assert any(d["file"] == "report.json" for d in res.differences)


def test_no_baseline_declines_with_a_named_reason(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, baseline=None)
    hs = r.report["held_out_seeds"]
    assert hs["declined"] == "no_baseline" and "known_valid_baseline" in hs["detail"]
    assert not list(r.work_dir.glob("held_out_seeds.epoch-*.jsonl"))


def test_undeclared_means_no_block(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, held=None)
    assert "held_out_seeds" not in r.report


def test_validation_rejects_held_out_seeds_that_are_also_measured_seeds():
    c = synthetic_campaign(SURFACES["bowl"](), known_valid_baseline=BASE,
                           workload={"seed_env": "S", "seeds": [1, 2, 900001],
                                     "held_out_seeds": [900001, 5]})
    errs = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN")]
    assert any("[900001] also appear in workload.seeds" in e for e in errs), errs


def test_validation_warns_when_nothing_can_be_paired():
    c = synthetic_campaign(SURFACES["bowl"](), workload=_wl())
    assert any(e.startswith("WARN") and "no known_valid_baseline" in e
               for e in validate_optimization_campaign(c))


def test_the_preview_shows_the_cost():
    c = synthetic_campaign(SURFACES["bowl"](), known_valid_baseline=BASE, workload=_wl())
    pv = build_preview(c, noise_sd=1.0, mean=10.0, run_secs=[1.0])
    st = {s.stage: s for s in pv.stages}["held-out seeds"]
    assert st.runs == 8 and not st.conditional
    assert "unseen workload seed" in "\n".join(format_preview(pv))
