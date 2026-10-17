"""Stage-1d (round 5) fixes for mixed-level factors (nous-e2e/audit/
stage1d-mixed-round5-fixes.md). Each Q-test FAILS on a5470ec and passes after."""
from __future__ import annotations

import json

from orchestrator.optimize import invariants as inv
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import Surface, _choice, _numeric

SCREEN_CONFIRM = {"stages": ["verify", "screen", "confirm"]}


def _recs(res):
    return [json.loads(p.read_text())
            for p in sorted(res.work_dir.glob("runs/iter-*/recommendation.json"),
                            key=lambda p: int(p.parent.name.split("-")[1]))]


def _finalists(res):
    out = []
    for p in res.work_dir.glob("runs/iter-*/shortlist.json"):
        out += json.loads(p.read_text())["finalists"]
    return out


def _centre_only_best():
    return Surface(name="q1", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B"),
                            _choice("POL", levels=("lru", "lfu", "arc"))),
                   fn=lambda lv: (10 + 0.1 * lv["A"] - 0.05 * (lv["B"] - 9) ** 2
                                  + {"lru": 0.0, "lfu": 2.0, "arc": 6.0}[lv["POL"]]),
                   fails_at=lambda lv: lv["POL"] == "arc" and lv["A"] != 9)


def test_Q1_the_bar_survives_refine(tmp_path):
    """screen -> refine -> confirm: refine holds POL fixed and loses nothing
    itself, but arc (lost at the screen's corners) is still never seated or
    recommended, and refine's recommendation.json carries it forward."""
    res = run_synthetic_campaign(
        _centre_only_best(), seed=1, parent_dir=tmp_path,
        campaign_overrides={"design": {"screen": {"resolution": 5, "center_points": 6},
                                       "refine": {"kind": "central_composite",
                                                  "center_points": 4},
                                       "confirm": {"replicates": 3}}})
    assert "refine" in res.path, res.path
    recs = _recs(res)
    assert all(r.get("lost_levels") == {"POL": ["arc"]} for r in recs), \
        [r.get("lost_levels") for r in recs]
    assert all(f["levels"]["POL"] != "arc" for f in _finalists(res))
    assert res.report["recommendation"]["levels"]["POL"] != "arc"
    conf = json.loads(sorted(res.work_dir.glob("runs/iter-*/confirmation.json"))[-1].read_text())
    assert inv.check_recommendation_avoids_lost_levels(recs[-1], res.report, conf) == []


def test_Q2_lost_plus_inadmissible_covering_a_factor_does_not_empty_the_space(tmp_path):
    """C = {a, b, c}: a lost (every run fails), b and c inadmissible
    everywhere. Before: all three excluded -> a false 'measured infeasible'
    abort. After: only the lost a is excluded, b/c stay candidates, recorded
    as all_levels_inadmissible."""
    def lat(lv):
        return (30.0 if lv["C"] in ("b", "c") else 10.0) + 0.1 * float(lv["A"])

    s = Surface(name="q2", noise_sd=0.05,
                factors=(_numeric("A"), _numeric("B"), _choice("C", levels=("a", "b", "c"))),
                fn=lambda lv: 10 + 0.1 * lv["A"] + {"a": 0, "b": 1, "c": 2}[lv["C"]],
                fails_at=lambda lv: lv["C"] == "a",
                constraints=({"metric": "lat_ms", "op": "<=", "value": 20.0},),
                noisy_observables=lambda lv, rng: {"lat_ms": lat(lv) + rng.gauss(0, 0.3)})
    res = run_synthetic_campaign(
        s, seed=1, parent_dir=tmp_path,
        campaign_overrides={**SCREEN_CONFIRM, "response": {
            "primary": {"metric": "m", "direction": "maximize"},
            "constraints": [dict(c) for c in s.constraints]}})
    assert not any(str(p).startswith("aborted") for p in res.path), res.path
    rec = _recs(res)[0]
    assert rec["lost_levels"] == {"C": ["a"]}
    assert rec["all_levels_inadmissible"] == ["C"]
    assert rec["levels"]["C"] in ("b", "c")
    assert inv.check_recommendation_avoids_lost_levels(rec) == []


def _q3_work_dir(tmp_path, n_iter=50, n_rows=40):
    """50 iterations x 40 complete rows, each iteration with a
    recommendation.json that loses POL=arc: 2000 rows, 1000 distinct
    configurations (A in 1..500 x POL in {lru, lfu}), none at arc."""
    for it in range(1, n_iter + 1):
        d = tmp_path / "runs" / f"iter-{it}"
        d.mkdir(parents=True)
        rows = []
        for r in range(n_rows):
            k = (it - 1) * n_rows + r
            lv = {"A": k % 500 + 1, "POL": ("lru", "lfu")[k // 500 % 2]}
            rows.append(json.dumps({"row_index": r, "status": "complete",
                                    "role": "corner", "levels": lv,
                                    "response": {"m": float(k)}}))
        (d / "runs.jsonl").write_text("\n".join(rows) + "\n")
        (d / "recommendation.json").write_text(json.dumps({
            "stage": "screen", "iteration": it, "levels": {"A": 1, "POL": "lfu"},
            "lost_levels": {"POL": ["arc"]}}))
    return tmp_path


def test_Q3_admissibility_loops_are_work_bounded(tmp_path):
    """Behavioural, work-bound (stage-1d Q3): the measured selectors over a
    2000-row, 50-iteration epoch return all 1000 admissible configurations,
    none at the lost level, in well under a second of CPU. Reading the bar
    once per ROW (re-reading 50 recommendation.json files 2000 times) is far
    over the bound."""
    import time

    from orchestrator.optimize.stage_runner import _admissible_configurations, _top_measured

    wd = _q3_work_dir(tmp_path)
    t0 = time.process_time()
    top = _top_measured(wd, "m", k=5000)
    adm = _admissible_configurations(wd)
    elapsed = time.process_time() - t0
    assert len(top) == 1000 and len(adm) == 1000
    assert not any(c["levels"]["POL"] == "arc" for c in top)
    assert not any(c["POL"] == "arc" for c in adm)
    assert elapsed < 1.0, f"{elapsed:.2f}s CPU for 2 x 2000 rows"


def test_Q4_the_known_valid_baseline_is_exempt_and_the_exemption_is_recorded(tmp_path):
    """Every ranked candidate names the lost level arc, and so does the
    declared baseline. Before: confirm refused the baseline too (no finalist,
    and an abort saying there was no known_valid_baseline) although the report
    ladder's baseline rung would return it. After: the baseline is seated,
    exempt, and the exemption is in its provenance; INV-SEM19 exempts it."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy
    from orchestrator.optimize.stage_runner import _confirm_rows

    s = Surface(name="q4", fn=lambda lv: 0.0,
                factors=(_numeric("A", levels=(2, 16)),
                         _choice("POL", levels=("lru", "lfu", "arc"))))
    c = synthetic_campaign(s, known_valid_baseline={"A": 2, "POL": "arc"})
    pol = compile_policy(c)
    base = pol["known_valid_baseline"]
    it = tmp_path / "runs" / "iter-2"
    it.mkdir(parents=True)
    (it / "runs.jsonl").write_text("")    # an iteration of THIS epoch
    arc = {"A": 16, "POL": "arc"}
    (it / "recommendation.json").write_text(json.dumps({
        "stage": "screen", "iteration": 2, "levels": arc, "predicted": 1.0,
        "top_candidates": [{"levels": arc, "predicted": 1.0}],
        "model_adequate": True, "lost_levels": {"POL": ["arc"]}}))
    _rows, payload = _confirm_rows(pol, tmp_path, parse_factors(c["optimization"]["factors"]),
                                   "m", "maximize", 3)
    seated = [f for f in payload["finalists"] if f["levels"] == base]
    assert seated and "baseline exempt" in seated[0]["why"]
    assert all(f["levels"] == base for f in payload["finalists"])
    # (the hand-written recommendation above names arc on purpose; judge only
    # the report and the finalists here)
    report = {"recommendation": {"levels": base}, "known_valid_baseline": base}
    assert inv.check_recommendation_avoids_lost_levels(
        {"lost_levels": {"POL": ["arc"]}}, report, payload) == []


def test_Q5_an_exact_rejection_sets_the_lack_of_fit_trigger():
    from orchestrator.optimize.design import full_factorial, with_center_points
    from orchestrator.optimize.effects import fit_effects
    from orchestrator.optimize.stage import Trigger, decide_after_screen, observations_from_decision

    d = with_center_points(full_factorial(["A", "B"]), 3)
    ys = [1 + 2 * p.coded[0] - p.coded[1] + (1.0 if p.role == "center" else 0.0)
          for p in d.points]
    fit = fit_effects(d, ys, factor_ids=["A", "B"])
    assert fit.lof_exact == "rejected"
    dec = decide_after_screen(fit, [])
    assert Trigger.LACK_OF_FIT in dec.triggers
    obs = observations_from_decision(dec, fit)
    assert obs["lack_of_fit"] is True and obs["model_adequate"] is False


def test_Q6_report_schema_text_on_inadmissible_levels():
    from pathlib import Path

    d = json.loads((Path(__file__).resolve().parents[1] / "orchestrator" / "schemas"
                    / "report.schema.json").read_text())["properties"]["inadmissible_levels"]
    assert "all_levels_inadmissible" in d["description"]


def test_R1_the_bar_is_epoch_scoped(tmp_path):
    """Epoch 1's refine lost POL=arc. Epoch 2 (a recompiled policy, a new
    policy_hash) has written no recommendation yet: arc must NOT be barred --
    the new epoch has not measured it."""
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, policy_hash, write_policy
    from orchestrator.optimize.stage_runner import _barred_levels, _config_admissible

    s = Surface(name="r1", fn=lambda lv: 0.0,
                factors=(_numeric("A"), _choice("POL", levels=("lru", "lfu", "arc"))))
    pol1 = compile_policy(synthetic_campaign(s))
    it = tmp_path / "runs" / "iter-3"
    it.mkdir(parents=True)
    (it / "runs.jsonl").write_text("")
    (it / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol1)}))
    (it / "recommendation.json").write_text(json.dumps({
        "stage": "refine", "iteration": 3, "levels": {"A": 9, "POL": "lfu"},
        "lost_levels": {"POL": ["arc"]}}))
    write_policy(tmp_path, pol1)
    assert _barred_levels(tmp_path) == {"POL": ["arc"]}       # epoch 1: barred
    pol2 = dict(pol1, epoch=2)
    assert policy_hash(pol2) != policy_hash(pol1)
    write_policy(tmp_path, pol2)
    assert _barred_levels(tmp_path) == {}
    assert _config_admissible(tmp_path, {"A": 9, "POL": "arc"})


def test_R2_report_md_names_a_recommended_baseline_at_a_barred_level(tmp_path):
    from orchestrator.optimize.report_md import render_report_markdown
    from orchestrator.optimize.synthetic import SURFACES

    res = run_synthetic_campaign(SURFACES["bowl"](), seed=1, parent_dir=tmp_path,
                                 campaign_overrides={"stages": ["verify", "screen"]})
    rp = res.work_dir / "report.json"
    rep = json.loads(rp.read_text())
    rep["recommendation_names_barred_level"] = {"POL": "arc"}
    rp.write_text(json.dumps(rep))
    md = render_report_markdown(res.work_dir)
    assert ("Recommended baseline names lost/inadmissible level(s):** POL=arc "
            "(the declared known_valid_baseline is exempt)") in md


def test_R4_report_level_facts_are_epoch_scoped(tmp_path):
    """Epoch 1's screen lost POL=arc; the policy is recompiled (epoch 2) and
    epoch 2 ends before writing any recommendation, with a measured run at
    arc. Before: report.json still said 'lost: arc' (copied from the
    non-epoch-scoped latest recommendation) while the measured rung could
    recommend arc with no exemption line. After: no epoch-1 level facts, and
    whatever is recommended is consistent with the (empty) epoch-2 bar."""
    from types import SimpleNamespace

    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, policy_hash, write_policy
    from orchestrator.optimize.stage_runner import _run_report

    s = Surface(name="r4", fn=lambda lv: 0.0,
                factors=(_numeric("A"), _choice("POL", levels=("lru", "lfu", "arc"))))
    camp = synthetic_campaign(s)
    pol1 = compile_policy(camp)
    it1 = tmp_path / "runs" / "iter-2"
    it1.mkdir(parents=True)
    (it1 / "runs.jsonl").write_text("")
    (it1 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol1)}))
    (it1 / "recommendation.json").write_text(json.dumps({
        "stage": "screen", "iteration": 2, "levels": {"A": 9, "POL": "lfu"},
        "lost_levels": {"POL": ["arc"]}, "inadmissible_levels": {"POL": ["lru"]},
        "all_levels_inadmissible": ["POL"]}))
    pol2 = dict(pol1, epoch=2)
    write_policy(tmp_path, pol2)
    it3 = tmp_path / "runs" / "iter-3"
    it3.mkdir(parents=True)
    (it3 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol2)}))
    (it3 / "runs.jsonl").write_text(json.dumps({
        "row_index": 0, "status": "complete", "role": "corner",
        "levels": {"A": 16, "POL": "arc"}, "response": {"m": 99.0}}) + "\n")

    class _Eng(SimpleNamespace):
        def transition(self, *_a, **_k):
            pass

    _run_report(_Eng(), camp, tmp_path, 3, pol2, recommendation_levels=None)
    rep = json.loads((tmp_path / "report.json").read_text())
    for k in ("lost_levels", "inadmissible_levels", "all_levels_inadmissible"):
        assert k not in rep, (k, rep.get(k))
    assert "recommendation_names_barred_level" not in rep
    # The answer is THIS epoch's: with no epoch-2 fitting record the model rung
    # has nothing to offer, so the report falls to the measured rung (the one
    # epoch-2 row at arc), never to epoch 1's fitted pick (lfu).
    assert rep["recommendation"]["basis"] == "measured", rep["recommendation"]
    assert rep["recommendation"]["levels"] == {"A": 16, "POL": "arc"}


def test_R4_the_measured_rung_can_recommend_the_level_without_a_stale_lost_line(tmp_path):
    """Epoch 2 has no recommendation; epoch 1's record names arc lost. The
    answer comes from epoch 2's own measurement (basis measured) and
    report.json must not then claim arc is lost."""
    from types import SimpleNamespace

    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, policy_hash, write_policy
    from orchestrator.optimize.report_md import render_report_markdown
    from orchestrator.optimize.stage_runner import _run_report

    s = Surface(name="r4b", fn=lambda lv: 0.0,
                factors=(_numeric("A"), _choice("POL", levels=("lru", "lfu", "arc"))))
    camp = synthetic_campaign(s)
    pol1 = compile_policy(camp)
    it1 = tmp_path / "runs" / "iter-2"
    it1.mkdir(parents=True)
    (it1 / "runs.jsonl").write_text("")
    (it1 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol1)}))
    (it1 / "recommendation.json").write_text(json.dumps({
        "stage": "screen", "iteration": 2, "levels": {"A": 16, "POL": "arc"},
        "lost_levels": {"POL": ["arc"]}}))
    pol2 = dict(pol1, epoch=2)
    write_policy(tmp_path, pol2)
    it3 = tmp_path / "runs" / "iter-3"
    it3.mkdir(parents=True)
    (it3 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol2)}))
    (it3 / "runs.jsonl").write_text(json.dumps({
        "row_index": 0, "status": "complete", "role": "corner",
        "levels": {"A": 16, "POL": "arc"}, "response": {"m": 99.0}}) + "\n")

    class _Eng(SimpleNamespace):
        def transition(self, *_a, **_k):
            pass

    _run_report(_Eng(), camp, tmp_path, 3, pol2, recommendation_levels=None)
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep["recommendation"]["basis"] == "measured", rep["recommendation"]
    assert rep["recommendation"]["levels"]["POL"] == "arc"
    assert "lost_levels" not in rep
    assert "Levels lost" not in render_report_markdown(tmp_path)


def test_R5_report_adequacy_and_coverage_facts_are_epoch_scoped_too(tmp_path):
    """Same shape as R4, for the adequacy/coverage facts: epoch 1 recorded an
    unknown model, untested curvature and unassessed aliases; epoch 2 ends
    before writing a recommendation. The epoch-2 report must not carry epoch
    1's adequacy verdict as its own."""
    from types import SimpleNamespace

    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, policy_hash, write_policy
    from orchestrator.optimize.stage_runner import _run_report

    s = Surface(name="r5", fn=lambda lv: 0.0,
                factors=(_numeric("A"), _choice("POL", levels=("lru", "lfu", "arc"))))
    camp = synthetic_campaign(s)
    pol1 = compile_policy(camp)
    it1 = tmp_path / "runs" / "iter-2"
    it1.mkdir(parents=True)
    (it1 / "runs.jsonl").write_text("")
    (it1 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol1)}))
    (it1 / "recommendation.json").write_text(json.dumps({
        "stage": "screen", "iteration": 2, "levels": {"A": 9, "POL": "lfu"},
        "model_adequate": None, "model_adequate_basis": "curvature_untested",
        "curvature_untested_levels": {"POL": ["arc"]},
        "aliases_not_assessed": ["AB~POL[1]"]}))
    pol2 = dict(pol1, epoch=2)
    write_policy(tmp_path, pol2)
    it3 = tmp_path / "runs" / "iter-3"
    it3.mkdir(parents=True)
    (it3 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol2)}))
    (it3 / "runs.jsonl").write_text(json.dumps({
        "row_index": 0, "status": "complete", "role": "corner",
        "levels": {"A": 16, "POL": "lfu"}, "response": {"m": 1.0}}) + "\n")

    class _Eng(SimpleNamespace):
        def transition(self, *_a, **_k):
            pass

    _run_report(_Eng(), camp, tmp_path, 3, pol2, recommendation_levels=None)
    rep = json.loads((tmp_path / "report.json").read_text())
    for k in ("model_adequate", "model_adequate_basis", "curvature_untested_levels",
              "aliases_not_assessed"):
        assert k not in rep, (k, rep.get(k))


def test_R6_an_epoch_without_a_fit_never_reports_the_previous_epochs_model(tmp_path):
    """Merge-gate probe: epoch 1's record carries a REJECTED model with its
    pick, prediction (123), model bound (7) and epsilon (5). Epoch 2 ends
    before fitting. The report must not present epoch 1's fitted pick and
    bound as epoch 2's answer (while omitting that the model was rejected)."""
    from types import SimpleNamespace

    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, policy_hash, write_policy
    from orchestrator.optimize.stage_runner import _run_report

    s = Surface(name="r6", fn=lambda lv: 0.0,
                factors=(_numeric("A"), _choice("POL", levels=("lru", "lfu", "arc"))))
    camp = synthetic_campaign(s)
    pol1 = compile_policy(camp)
    it1 = tmp_path / "runs" / "iter-2"
    it1.mkdir(parents=True)
    (it1 / "runs.jsonl").write_text("")
    (it1 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol1)}))
    (it1 / "recommendation.json").write_text(json.dumps({
        "stage": "screen", "iteration": 2, "levels": {"A": 2, "POL": "lfu"},
        "predicted": 123.0, "model_adequate": False,
        "residual_regret_model": {"value": 7.0}, "epsilon": 5.0}))
    pol2 = dict(pol1, epoch=2)
    write_policy(tmp_path, pol2)
    it3 = tmp_path / "runs" / "iter-3"
    it3.mkdir(parents=True)
    (it3 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol2)}))
    (it3 / "runs.jsonl").write_text(json.dumps({
        "row_index": 0, "status": "complete", "role": "corner",
        "levels": {"A": 16, "POL": "arc"}, "response": {"m": 1.0}}) + "\n")

    class _Eng(SimpleNamespace):
        def transition(self, *_a, **_k):
            pass

    _run_report(_Eng(), camp, tmp_path, 3, pol2, recommendation_levels=None)
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep["recommendation"]["basis"] != "model", rep["recommendation"]
    assert rep["recommendation"].get("value") != 123.0
    assert rep.get("residual_regret_model") in (None, {}), rep.get("residual_regret_model")
    assert rep.get("epsilon") != 5.0


def test_R7_an_earlier_epochs_certificate_never_answers_for_a_recompiled_epoch(tmp_path):
    """Merge-gate probe: epoch 1 certified lfu (mean 99). Epoch 2 was recompiled
    and ended before confirming. A recompiled epoch is a new pre-registration
    with its own error budget, so the report must not claim epoch 1's
    certificate as its own."""
    from types import SimpleNamespace

    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.policy import compile_policy, policy_hash, write_policy
    from orchestrator.optimize.stage_runner import _run_report

    s = Surface(name="r7", fn=lambda lv: 0.0,
                factors=(_numeric("A"), _choice("POL", levels=("lru", "lfu", "arc"))))
    camp = synthetic_campaign(s)
    pol1 = compile_policy(camp)
    it1 = tmp_path / "runs" / "iter-4"
    it1.mkdir(parents=True)
    (it1 / "runs.jsonl").write_text("")
    (it1 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol1)}))
    (it1 / "confirmation.json").write_text(json.dumps({
        "certified": True, "confirmed_at_levels": {"A": 2, "POL": "lfu"},
        "winner": {"levels": {"A": 2, "POL": "lfu"}, "mean": 99.0},
        "finalists": [{"key": "f0", "levels": {"A": 2, "POL": "lfu"}, "mean": 99.0}],
        "residual_regret_terminal": 0.1, "epsilon": 2.0,
        "certification_withheld": []}))
    pol2 = dict(pol1, epoch=2)
    write_policy(tmp_path, pol2)
    it5 = tmp_path / "runs" / "iter-5"
    it5.mkdir(parents=True)
    (it5 / "design_matrix.json").write_text(json.dumps({"policy_hash": policy_hash(pol2)}))
    (it5 / "runs.jsonl").write_text(json.dumps({
        "row_index": 0, "status": "complete", "role": "corner",
        "levels": {"A": 16, "POL": "arc"}, "response": {"m": 1.0}}) + "\n")

    class _Eng(SimpleNamespace):
        def transition(self, *_a, **_k):
            pass

    _run_report(_Eng(), camp, tmp_path, 5, pol2, recommendation_levels=None)
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep["certified"] is False
    assert rep["recommendation"]["basis"] != "certified", rep["recommendation"]
    assert rep["recommendation"].get("value") != 99.0
    assert rep["finalists"] == []
    assert rep["certification_withheld"] == ["no_terminal_discrimination"]
