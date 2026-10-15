"""Behavioral tests for the AUTHORING half of multi-objective (Pareto) support.

Contract: docs/superpowers/specs/2026-10-15-pareto-front-design.md. Covered
here: the schema (``response.objectives`` / ``preference``, map-form
``policy.epsilon`` and ``noise_estimate_pct``), the validator rules, ``--smoke``
and ``--liveness`` on a two-objective campaign (per-objective tables, trade-off
candidates, constant-objective warning, per-objective MDE in the design
preview), constraint metrics in liveness, and ``create-campaign --objectives``.
Every CLI check runs the real entry point against a tiny tmp target; no LLM.
"""
from __future__ import annotations

import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from orchestrator.validate import validate_optimization_campaign
from tests.test_optimization_authoring import RELATIONS, _nous, fill_subs

ROOT = Path(__file__).resolve().parents[1]
OPT_GOLDEN = Path(__file__).parent / "fixtures" / "create_campaign_optimization_golden"
SCHEMA = yaml.safe_load(
    (ROOT / "orchestrator" / "schemas" / "campaign.schema.yaml").read_text())

# Two objectives that TRADE on `knob` (score up, memory up) and a constraint
# metric `ratio` moved only by `mode`. Env switches make the variants:
#   MEM_CONST=1          mem_mib never moves (constant objective)
#   SCORE_IGNORES_MODE=1 `mode` moves only `ratio`, not the objective
ADAPTER = r'''
import argparse, json, os, random
ap = argparse.ArgumentParser()
ap.add_argument("--knob", type=int, required=True)
ap.add_argument("--mode", choices=["off", "on"], required=True)
a = ap.parse_args()
seed = int(os.environ.get("NOUS_WORKLOAD_SEED", "0"))
rng = random.Random(seed)
noise = rng.gauss(0, float(os.environ.get("NOISE_SD", "1.0")))
mode_gain = 0.0 if os.environ.get("SCORE_IGNORES_MODE") else 10.0
score = 100.0 + 5.0 * a.knob + (mode_gain if a.mode == "on" else 0.0) + noise
mem = 50.0 if os.environ.get("MEM_CONST") else 50.0 + 8.0 * a.knob + 0.5 * rng.gauss(0, 1)
ratio = 3.0 + (1.0 if a.mode == "on" else 0.0) + 0.01 * rng.gauss(0, 1)
print(json.dumps({"score": score, "mem_mib": mem, "ratio": ratio,
                  "latency_ms": 10.0, "completed": True, "label": "x",
                  "holdout_score": score,
                  "cfg": {"knob": a.knob, "mode": a.mode, "size": 4}}))
'''


def _target(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    (repo / "tests").mkdir(parents=True)
    (repo / "adapter.py").write_text(ADAPTER)
    (repo / "tests" / "test_relations.py").write_text(RELATIONS)
    return repo


def _single(tmp_path: Path, capsys) -> tuple[Path, dict]:
    """A filled, valid single-objective campaign over the two-metric target."""
    repo = _target(tmp_path)
    camp = tmp_path / "campaign.yaml"
    code, _o, err = _nous(["create-campaign", "--kind", "optimization", "--to",
                           str(camp), "--target-repo-path", str(repo)], capsys)
    assert code == 0, err
    text = camp.read_text()
    for a, b in fill_subs():
        text = text.replace(a, b)
    camp.write_text(text)
    return camp, yaml.safe_load(text)


def _multi_doc(doc: dict, **response) -> dict:
    resp = doc["optimization"]["response"]
    resp.pop("primary", None)
    resp["objectives"] = [{"metric": "score", "direction": "maximize"},
                          {"metric": "mem_mib", "direction": "minimize"}]
    resp.update(response)
    return doc


def _write(camp: Path, doc: dict) -> Path:
    camp.write_text(yaml.safe_dump(doc, sort_keys=False))
    return camp


def _multi(tmp_path, capsys, *, epsilon=None, **response) -> Path:
    camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc, **response)
    if epsilon is not None:
        doc["optimization"]["policy"]["epsilon"] = epsilon
    return _write(camp, doc)


def _schema_errors(doc: dict) -> list[str]:
    v = jsonschema.Draft202012Validator(SCHEMA)
    return [".".join(map(str, e.absolute_path)) + ": " + e.message
            for e in v.iter_errors(doc)]


def _hard(items: list[str]) -> list[str]:
    return [i for i in items if not i.startswith("WARN:")]


# ── schema ───────────────────────────────────────────────────────────────────


def test_schema_accepts_objectives_preference_and_map_forms(tmp_path, capsys):
    _camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc, preference={"method": "weights",
                                "weights": {"score": 1.0, "mem_mib": 0.5}},
               noise_estimate_pct={"score": 2.0, "mem_mib": 1.0})
    doc["optimization"]["policy"]["epsilon"] = {"score": {"pct": 2},
                                                "mem_mib": {"abs": 5}}
    assert _schema_errors(doc) == []


@pytest.mark.parametrize("mutate", [
    # both primary and objectives
    lambda r: r.update(primary={"metric": "score", "direction": "maximize"}),
    # neither
    lambda r: r.pop("objectives"),
    # one objective is not a front
    lambda r: r.update(objectives=[{"metric": "score", "direction": "maximize"}]),
    lambda r: r["objectives"][1].update(direction="up"),
    lambda r: r.update(preference={"method": "pareto"}),
    lambda r: r.update(preference={"method": "weights", "weights": {"score": 0}}),
    lambda r: r.update(noise_estimate_pct={"score": -1}),
])
def test_schema_rejects_malformed_multi_objective_response(tmp_path, capsys, mutate):
    _camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc)
    mutate(doc["optimization"]["response"])
    assert _schema_errors(doc), doc["optimization"]["response"]


def test_schema_rejects_malformed_epsilon_map(tmp_path, capsys):
    _camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc)
    doc["optimization"]["policy"]["epsilon"] = {"score": {"pct": -2}}
    assert _schema_errors(doc)
    doc["optimization"]["policy"]["epsilon"] = {"pct": 2.0, "score": {"abs": 1}}
    assert _schema_errors(doc)


def test_single_objective_scaffold_is_byte_identical(tmp_path, capsys):
    camp = tmp_path / "c.yaml"
    for extra in ([], ["--objectives", "1"]):
        code, out, _ = _nous(["create-campaign", "--kind", "optimization",
                              "--to", str(camp), "--target-repo-path",
                              "/GOLDEN_REPO", "--force", *extra], capsys)
        assert code == 0
        assert camp.read_text() == (OPT_GOLDEN / "campaign.yaml").read_text()
        assert out.replace(str(camp), "FILE") == (OPT_GOLDEN / "stdout.txt").read_text()


# ── validator rules ──────────────────────────────────────────────────────────


def test_valid_two_objective_campaign_has_no_rule_errors(tmp_path, capsys):
    _camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc, preference={"method": "lexicographic",
                                "order": ["mem_mib", "score"]})
    assert _hard(validate_optimization_campaign(doc)) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda o: o["response"].update(
        primary={"metric": "score", "direction": "maximize"}),
     "mutually exclusive"),
    (lambda o: o["response"].pop("objectives"), "neither primary nor objectives"),
    (lambda o: o["response"]["objectives"][1].update(metric=" SCORE"),
     "same metric"),
    (lambda o: o["response"]["constraints"].append(
        {"metric": "mem_mib", "op": "<=", "value": 500}),
     "also one of response.objectives"),
    (lambda o: o["response"].update(held_out=["mem_mib"]),
     "collides with the response.objectives metric"),
    (lambda o: o["response"]["self_check"].append(
        {"metric": "mem_mib", "op": ">", "value": 0}),
     "which is one of response.objectives"),
    (lambda o: o["response"].update(preference={"method": "weights"}),
     "no weights are declared"),
    (lambda o: o["response"].update(preference={
        "method": "weights", "weights": {"score": 1, "latency": 1}}),
     "'latency', which is not an objective metric"),
    (lambda o: o["response"].update(preference={
        "method": "knee", "weights": {"score": 1}}),
     "which ignores it"),
    (lambda o: o["response"].update(preference={"method": "lexicographic"}),
     "no order is declared"),
    (lambda o: o["response"].update(preference={
        "method": "lexicographic", "order": ["score", "score"]}),
     "must be a permutation"),
    (lambda o: o["policy"].update(epsilon={"score": {"pct": 2},
                                           "memory": {"abs": 5}}),
     "policy.epsilon.memory"),
    (lambda o: o["policy"].update(epsilon={"score": {"pct": 2, "abs": 1},
                                           "mem_mib": {"abs": 5}}),
     "policy.epsilon.score declares"),
    (lambda o: o["response"].update(noise_estimate_pct={"rss": 1.0}),
     "noise_estimate_pct.rss"),
])
def test_each_multi_objective_rule_fires(tmp_path, capsys, mutate, needle):
    _camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc)
    mutate(doc["optimization"])
    errs = _hard(validate_optimization_campaign(doc))
    assert any(needle in e for e in errs), errs


def test_epsilon_map_omitting_an_objective_warns_not_fails(tmp_path, capsys):
    _camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc)
    doc["optimization"]["policy"]["epsilon"] = {"score": {"pct": 2}}
    items = validate_optimization_campaign(doc)
    assert _hard(items) == []
    assert any(i.startswith("WARN:") and "omits objective(s) mem_mib" in i
               for i in items)


@pytest.mark.parametrize("mutate,needle", [
    (lambda o: o["response"].update(preference={"method": "knee"}),
     "preference is declared without response.objectives"),
    (lambda o: o["policy"].update(epsilon={"score": {"pct": 2}}),
     "per-objective map"),
    (lambda o: o["response"].update(noise_estimate_pct={"score": 2}),
     "noise_estimate_pct is a per-objective map"),
])
def test_multi_objective_forms_are_refused_on_a_single_objective(
        tmp_path, capsys, mutate, needle):
    _camp, doc = _single(tmp_path, capsys)
    mutate(doc["optimization"])
    assert any(needle in e for e in _hard(validate_optimization_campaign(doc)))


def test_single_objective_campaign_gains_no_new_findings(tmp_path, capsys):
    _camp, doc = _single(tmp_path, capsys)
    assert _hard(validate_optimization_campaign(doc)) == []


def test_cli_validate_reports_both_forms_once_each_and_exits_1(tmp_path, capsys):
    camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc)
    doc["optimization"]["response"]["primary"] = {"metric": "score",
                                                  "direction": "maximize"}
    _write(camp, doc)
    code, _o, err = _nous(["validate", "campaign", str(camp)], capsys)
    assert code == 1
    assert "[schema] optimization.response" in err
    assert err.count("are mutually exclusive") == 1


# ── --smoke ──────────────────────────────────────────────────────────────────


def test_smoke_checks_every_objective_is_present_and_numeric(tmp_path, capsys):
    camp = _multi(tmp_path, capsys)
    code, out, err = _nous(["validate", "campaign", str(camp), "--smoke"], capsys)
    assert code == 0, err + out
    assert re.search(r"smoke: objectives at this corner: score=[0-9.]+, "
                     r"mem_mib=[0-9.]+", out), out


def test_smoke_fails_on_a_missing_and_a_non_numeric_objective(tmp_path, capsys):
    camp, doc = _single(tmp_path, capsys)
    _multi_doc(doc)
    doc["optimization"]["response"]["objectives"] = [
        {"metric": "score", "direction": "maximize"},
        {"metric": "nope", "direction": "minimize"},
        {"metric": "label", "direction": "minimize"},
    ]
    _write(camp, doc)
    code, out, err = _nous(["validate", "campaign", str(camp), "--smoke"], capsys)
    assert code == 1
    assert "response.objectives metric 'nope' is absent" in err
    assert "response.objectives metric 'label' is 'x' (str), not a number" in err


# ── --liveness ───────────────────────────────────────────────────────────────


def _liveness(camp, capsys) -> str:
    code, out, err = _nous(["validate", "campaign", str(camp), "--liveness"], capsys)
    assert code == 0, err + out
    return out


def test_liveness_prints_a_table_per_objective_and_flags_the_trade_off(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "parent"))
    out = _liveness(_multi(tmp_path, capsys), capsys)
    assert "mean score=" in out and "mean mem_mib=" in out
    assert "effect (objective score (maximize) range" in out
    assert "effect (objective mem_mib (minimize) range" in out
    # knob raises score AND memory: the trade-off the front is made of.
    m = re.search(r"(\d+) trade-off candidate\(s\).*?\n((?:    .*\n)+)", out)
    assert m, out
    cands = m.group(2)
    assert re.search(r"A=\d+ -> A=\d+ improves score by [0-9.]+ \(maximize\) "
                     r"but worsens objective mem_mib", cands), cands
    assert not re.search(r"^\s+B\s", cands, re.M)
    # B moves score but not memory: live (for ANY objective), not droppable.
    assert "NOT demonstrably live" not in out
    mem_table = out.split("objective mem_mib (minimize) range")[1].split("liveness:")[0]
    assert re.search(r"B\s+effect: .*not demonstrably live on this objective",
                     mem_table), mem_table


def test_liveness_warns_on_a_constant_objective(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("MEM_CONST", "1")
    out = _liveness(_multi(tmp_path, capsys), capsys)
    assert "WARNING — objective mem_mib was constant (50)" in out
    assert "no trade-off to discover on it" in out
    assert "no trade-off candidate" in out


def test_preview_prints_screen_mde_per_objective_vs_its_epsilon(
        tmp_path, capsys, monkeypatch):
    camp = _multi(tmp_path, capsys, epsilon={"score": {"abs": 1000.0},
                                             "mem_mib": {"abs": 0.001}})
    out = _liveness(camp, capsys)
    assert "screen MDE per objective: t(0.975, df=2)=4.303" in out
    score = re.search(r"score\s+\(maximize\) sd [0-9.e-]+ -> MDE ([0-9.e+-]+); "
                      r"epsilon \{'abs': 1000.0\} -> 1000(.*)", out)
    mem = re.search(r"mem_mib\s+\(minimize\) sd [0-9.e-]+ -> MDE ([0-9.e+-]+); "
                    r"epsilon \{'abs': 0.001\} -> 0.001(.*)", out)
    assert score and mem, out
    assert "below MDE" not in score.group(2) and "below MDE" in mem.group(2)
    assert "objective mem_mib: epsilon (0.001) is below the screen's minimum" in out
    assert "objective score: epsilon" not in out
    # latency_ms is a constraint: admissibility, no MDE.
    assert "constraint metric(s) latency_ms: no MDE needed" in out


def test_liveness_keeps_a_factor_that_only_moves_a_constraint(
        tmp_path, capsys, monkeypatch):
    """Single objective: B moves only the constraint metric `ratio`. It must be
    labelled keep (it decides feasibility), never 'drop it'."""
    monkeypatch.setenv("SCORE_IGNORES_MODE", "1")
    camp, doc = _single(tmp_path, capsys)
    doc["optimization"]["response"]["constraints"] = [
        {"metric": "ratio", "op": ">=", "value": 3.0}]
    out = _liveness(_write(camp, doc), capsys)
    assert "mean ratio=" in out and "(constraint metric)" in out
    assert "effect (constraint metric ratio range" in out
    obj_table = out.split("effect (objective range")[1].split("liveness:")[0]
    assert re.search(r"B\s+effect: .*drives constraint `ratio` only — keep "
                     r"\(it decides feasibility\)", obj_table), obj_table
    assert "NOT demonstrably live" not in out
    assert "move no objective beyond noise but DO move a constraint metric (B)" in out


def test_liveness_still_flags_a_factor_dead_for_objective_and_constraints(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SCORE_IGNORES_MODE", "1")
    camp, _doc = _single(tmp_path, capsys)   # constraint: latency_ms (constant)
    out = _liveness(camp, capsys)
    assert re.search(r"1 factor\(s\) NOT demonstrably live \(B\)", out), out


# ── scaffold --objectives ────────────────────────────────────────────────────


def test_scaffold_objectives_2_validates_after_filling(tmp_path, capsys):
    repo = _target(tmp_path)
    camp = tmp_path / "multi.yaml"
    code, _o, err = _nous(["create-campaign", "--kind", "optimization",
                           "--objectives", "2", "--to", str(camp),
                           "--target-repo-path", str(repo)], capsys)
    assert code == 0, err
    text = camp.read_text()
    assert "# preference:" in text and "#   method: weights" in text
    doc = yaml.safe_load(text)
    assert "primary" not in doc["optimization"]["response"]
    assert [o["metric"] for o in doc["optimization"]["response"]["objectives"]] \
        == ["TODO-objective-1-metric", "TODO-objective-2-metric"]
    code, _o, err = _nous(["validate", "campaign", str(camp)], capsys)
    assert code == 1
    assert "[placeholder] optimization.response.objectives[1].metric" in err
    assert "[schema]" not in err

    text = text.replace("TODO-objective-1-metric", "score").replace(
        "TODO-objective-2-metric", "mem_mib")
    text = text.replace(
        "TODO-what is the trade-off frontier between the objectives over the "
        "declared knobs, subject to the constraints?", "Score vs memory?")
    for a, b in fill_subs():
        text = text.replace(a, b)
    camp.write_text(text)
    code, out, err = _nous(["validate", "campaign", str(camp)], capsys)
    assert code == 0, err
    assert "OK — no errors" in out


def test_scaffold_objectives_3_writes_three(tmp_path, capsys):
    camp = tmp_path / "c.yaml"
    code, _o, _e = _nous(["create-campaign", "--kind", "optimization",
                          "--objectives", "3", "--to", str(camp)], capsys)
    assert code == 0
    objs = yaml.safe_load(camp.read_text())["optimization"]["response"]["objectives"]
    assert len(objs) == 3


@pytest.mark.parametrize("argv", [
    ["--objectives", "0", "--kind", "optimization"],
    ["--objectives", "2"],   # reflective
])
def test_scaffold_objectives_bad_usage_exits_2(tmp_path, capsys, argv):
    code, _o, err = _nous(["create-campaign", "--to", str(tmp_path / "c.yaml"),
                           *argv], capsys)
    assert code == 2 and "--objectives" in err


def test_preview_is_unchanged_for_single_objective_without_constraints():
    """build_preview on a single-objective campaign: no per-objective block."""
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.preview import build_preview, format_preview
    from orchestrator.optimize.synthetic import SURFACES

    campaign = synthetic_campaign(SURFACES["additive"]())
    pv = build_preview(campaign, noise_sd=1.0, mean=100.0, run_secs=[1.0])
    text = "\n".join(format_preview(pv))
    assert pv.per_objective == []
    assert "screen MDE: t(0.975" in text and "per objective" not in text
