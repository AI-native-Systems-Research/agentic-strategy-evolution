"""Confirm reserves a seat for the best candidate whose feasibility the EVIDENCE supports.

The defect (observed on two real campaigns): confirm's shortlist is seeded from
measured leaders and filled from the model's ranking. Constraint models remove
only CONFIDENTLY infeasible candidates, so on a constraint-bound frontier the
ranking prefers higher-predicted candidates of UNCERTAIN feasibility; they are
measured infeasible, and a feasible improvement inside the region the campaign
had already measured admissible is never tested.
``SURFACES["deterministic_constraint_axis"]`` reproduces it in closed form.

Layers, all zero-token:

  * ORACLE -- on the defect surface the answer is feasible, beats every
    configuration measured before confirm, and a supported-feasible finalist is
    seated (several seeds).
  * METAMORPHIC -- with no declared constraints the shortlist and
    ``recommendation.json`` are byte-identical with the seat on or off; on the
    constrained oracle surfaces the seat is never worse against the truth.
  * PROPERTY -- every candidate ``supported_feasible`` returns satisfies the
    rule, restated here from its definition, and every candidate that
    satisfies it is returned.
  * UNIT -- ``_confirm_rows`` placement: never a duplicate, never displacing a
    measured seat, round-r top-up skips a pool member an earlier round measured.
"""
from __future__ import annotations

import json
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy.stats import t as student_t

from orchestrator.optimize import constraint_models as cm
from orchestrator.optimize import stage_runner
from orchestrator.optimize.decide import Candidate
from orchestrator.optimize.design import full_factorial, with_center_points
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.invariants import check_supported_feasible_candidate
from orchestrator.optimize.synthetic import SURFACES, _choice, _numeric

_AXIS = ("deterministic_constraint_axis", {"metric": "backlog", "op": "<=", "value": 7})
_CONSTRAINED = {
    "sla": {"metric": "p99_ms", "op": "<=", "value": 40},
    "infeasible_corner_interior": {"metric": "p99_ms", "op": "<=", "value": 90},
    "stochastic_constraint_boundary": {"metric": "stall_ms", "op": "<=", "value": 10},
    "deterministic_constraint_axis": _AXIS[1],
}
_NO_REFINE = {"drift", "interaction_only", "infeasible_corner_interior"}


def _overrides(name: str, *, constrained: bool) -> dict | None:
    s = SURFACES[name]()
    ov: dict = {}
    if constrained and name in _CONSTRAINED:
        ov["response"] = {"primary": {"metric": "m", "direction": s.direction},
                          "constraints": [_CONSTRAINED[name]]}
    if name in _NO_REFINE:
        ov["stages"] = ["verify", "screen", "confirm"]
    return ov or None


def _run(name, seed, tmp_path, monkeypatch, *, on: bool, constrained: bool = True):
    monkeypatch.setattr(stage_runner, "_SUPPORTED_FEASIBLE_SEAT", on)
    return run_synthetic_campaign(
        SURFACES[name](), seed=seed,
        parent_dir=tmp_path / f"{name}-{seed}-{'on' if on else 'off'}",
        campaign_overrides=_overrides(name, constrained=constrained),
        max_iterations=12,
    )


def _iter_dirs(work_dir):
    return sorted((work_dir / "runs").glob("iter-*"), key=lambda p: int(p.name[5:]))


def _shortlists(work_dir) -> list:
    """Every confirm round's finalists (levels + provenance), in round order."""
    out = []
    for d in _iter_dirs(work_dir):
        p = d / "design_matrix.json"
        if p.exists():
            dm = json.loads(p.read_text())
            if dm.get("kind") == "shortlist_replicate":
                out.append(dm["finalists"])
    return out


def _pre_confirm_best(work_dir) -> float:
    """Best primary over COMPLETE rows measured before the first confirm round."""
    best = -math.inf
    for d in _iter_dirs(work_dir):
        if (d / "confirmation.json").exists():
            break
        p = d / "runs.jsonl"
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("status") == "complete":
                best = max(best, float(row["response"]["m"]))
    return best


# ─── (1) oracle: the defect surface ───────────────────────────────────────


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_a_supported_feasible_finalist_finds_the_improvement_the_ranking_missed(
    seed, tmp_path, monkeypatch,
):
    """WITHOUT the seat every model-ranked finalist is infeasible and the measured
    leader wins; WITH it the answer is feasible and beats everything measured
    before confirm, because a candidate inside the measured-admissible region
    was finally put on trial."""
    name, _ = _AXIS
    s = SURFACES[name]()
    off = _run(name, seed, tmp_path, monkeypatch, on=False)
    on = _run(name, seed, tmp_path, monkeypatch, on=True)
    assert off.true_gap > 0.5, off.recommendation       # the defect reproduces

    assert on.recommendation and not s.invalid(on.recommendation)
    assert s.fn(on.recommendation) > _pre_confirm_best(on.work_dir) + 0.5
    assert on.true_gap < off.true_gap
    whys = [f["why"] for rnd in _shortlists(on.work_dir) for f in rnd]
    assert any("supported-feasible" in w for w in whys), whys

    rec_paths = [d / "recommendation.json" for d in _iter_dirs(on.work_dir)
                 if (d / "recommendation.json").exists()]
    rec = json.loads(rec_paths[-1].read_text())
    sf = rec["supported_feasible_candidate"]
    assert sf["levels"] is not None and not s.invalid(sf["levels"])
    assert check_supported_feasible_candidate(rec) == []


# ─── (2) metamorphic ──────────────────────────────────────────────────────


_UNCONSTRAINED = sorted(set(SURFACES) - set(_CONSTRAINED))


@pytest.mark.parametrize("name", _UNCONSTRAINED)
@pytest.mark.parametrize("seed", [1, 2])
def test_with_no_constraints_the_shortlist_is_byte_identical(
    name, seed, tmp_path, monkeypatch,
):
    off = _run(name, seed, tmp_path, monkeypatch, on=False, constrained=False)
    on = _run(name, seed, tmp_path, monkeypatch, on=True, constrained=False)
    assert json.dumps(_shortlists(on.work_dir)) == json.dumps(_shortlists(off.work_dir))
    for a, b in zip(_iter_dirs(on.work_dir), _iter_dirs(off.work_dir)):
        ra, rb = a / "recommendation.json", b / "recommendation.json"
        assert ra.exists() == rb.exists()
        if ra.exists():
            assert ra.read_bytes() == rb.read_bytes()
            assert "supported_feasible_candidate" not in json.loads(ra.read_text())
    assert (on.recommendation, on.basis) == (off.recommendation, off.basis)


@pytest.mark.parametrize("name", sorted(_CONSTRAINED))
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_the_seat_is_never_worse_on_the_constrained_oracle(
    name, seed, tmp_path, monkeypatch,
):
    s = SURFACES[name]()
    off = _run(name, seed, tmp_path, monkeypatch, on=False)
    on = _run(name, seed, tmp_path, monkeypatch, on=True)
    assert on.true_gap <= off.true_gap + 1e-9, (on.recommendation, off.recommendation)
    if on.recommendation:
        assert s.invalid is None or not s.invalid(on.recommendation)
    for d in _iter_dirs(on.work_dir):
        p = d / "recommendation.json"
        if p.exists():
            assert check_supported_feasible_candidate(json.loads(p.read_text())) == []


# ─── (3) property: (a) and (b), restated from the definition ──────────────


def _factor_set():
    return parse_factors([_numeric("A"), _numeric("B", levels=(2, 16)), _choice("C")])


def _real_model(b0, ba, bb, noise, op, value):
    d = with_center_points(full_factorial(["A", "B"]), 4)
    ys, ci = [], 0
    for p in d.points:
        a, b = p.coded
        if p.role == "center":
            ys.append(b0 + noise[ci])
            ci += 1
        else:
            ys.append(b0 + ba * a + bb * b)
    records = [("complete", {"q": y}) for y in ys]
    return cm.fit_constraint_models([{"metric": "q", "op": op, "value": value}], d,
                                    records, fitted_ids=["A", "B"])[0]


def _cands():
    out = []
    for a in (2, 4, 8, 16):
        for b in (2, 16):
            for c in ("off", "on"):
                coded = {"A": (a - 9) / 7.0, "B": (b - 9) / 7.0}
                out.append(Candidate(levels={"A": a, "B": b, "C": c}, coded=coded,
                                     predicted=float(a + b)))
    return out


_level_sets = st.lists(
    st.fixed_dictionaries({"A": st.sampled_from([2, 4, 8, 16]),
                           "B": st.sampled_from([2, 16]),
                           "C": st.sampled_from(["off", "on"])}),
    min_size=0, max_size=5,
)


@settings(max_examples=80, deadline=None)
@given(
    b0=st.floats(-50, 50), ba=st.floats(-30, 30), bb=st.floats(-30, 30),
    noise=st.lists(st.floats(-5, 5), min_size=4, max_size=4).filter(
        lambda xs: max(xs) - min(xs) > 1e-3),
    op=st.sampled_from(["<", "<=", ">", ">="]), value=st.floats(-60, 60),
    delta=st.sampled_from([0.01, 0.05, 0.2]),
    with_unmodelled=st.booleans(), admissible=_level_sets,
)
def test_every_supported_candidate_satisfies_the_rule_and_none_is_missed(
    b0, ba, bb, noise, op, value, delta, with_unmodelled, admissible,
):
    modelled = _real_model(b0, ba, bb, noise, op, value)
    models = [modelled]
    if with_unmodelled:
        models.append(cm.ConstraintModel("w", "<=", 7, None, "deterministic"))
    region = cm.admissible_region(admissible, _factor_set())
    cands = _cands()
    got = cm.supported_feasible(cands, models, delta=delta, region=region)
    got_levels = [c.levels for c, _ in got]

    # The rule, restated: Bonferroni over the MODELLED constraints, the
    # satisfying-side one-sided bound inside the threshold, and -- only when a
    # constraint is unmodelled -- every level inside the per-factor span of the
    # measured-admissible configurations.
    d_each = delta / max(1, sum(1 for m in models if m.modelled))
    expected = []
    for c in cands:
        ok = True
        if modelled.modelled:
            y, se = cm.predicted_with_se(modelled.fit, c.coded)
            half = float(student_t.ppf(1 - d_each, modelled.fit.pure_error_df)) * se
            ok = {"<=": y + half <= value, "<": y + half < value,
                  ">=": y - half >= value, ">": y - half > value}[op]
        if ok and (with_unmodelled or not modelled.modelled):
            ok = bool(admissible) and all(
                (min(x[f] for x in admissible) <= c.levels[f]
                 <= max(x[f] for x in admissible)) if f != "C"
                else c.levels[f] in {x[f] for x in admissible}
                for f in ("A", "B", "C")
            )
        if ok:
            expected.append(c.levels)
    assert got_levels == expected          # sound AND complete, order preserved
    for c, verdicts in got:
        assert len(verdicts) == len(models)
        assert all(v["verdict"] in ("feasible", "inside_admissible_region")
                   for v in verdicts)


def test_admissible_region_numeric_span_and_choice_levels():
    f = _factor_set()
    region = cm.admissible_region(
        [{"A": 4, "B": 2, "C": "off"}, {"A": 8.0, "B": 2, "C": "off"}], f)
    assert region["A"] == {"kind": "range", "min": 4, "max": 8.0}
    assert region["C"] == {"kind": "levels", "levels": ["off"]}
    assert cm.in_admissible_region({"A": 6, "B": 2, "C": "off"}, region)
    assert not cm.in_admissible_region({"A": 16, "B": 2, "C": "off"}, region)
    assert not cm.in_admissible_region({"A": 6, "B": 2, "C": "on"}, region)
    assert not cm.in_admissible_region({"A": 6, "B": 2, "C": "off", "D": 1}, region)
    assert cm.admissible_region([], f) == {}
    assert cm.supported_feasible(_cands(), [cm.ConstraintModel("w", "<=", 7, None, "x")],
                                 delta=0.05, region={}) == []


# ─── (4) unit: placement in `_confirm_rows` ───────────────────────────────


def _confirm_fixture(tmp_path, *, k, model_adequate, pool, rows=(), rounds=None):
    from orchestrator.optimize.policy import compile_policy

    s = SURFACES["deterministic_constraint_axis"]()
    camp = synthetic_campaign(
        s, response={"primary": {"metric": "m", "direction": "maximize"},
                     "constraints": [_AXIS[1]]},
        design={"screen": {"resolution": 5, "center_points": 4},
                "refine": {"kind": "central_composite", "center_points": 4},
                "confirm": {"replicates": 2, "shortlist_size": k}},
    )
    pol = compile_policy(camp)
    wd = tmp_path / "wd"
    it = wd / "runs" / "iter-2"
    it.mkdir(parents=True)
    it.joinpath("runs.jsonl").write_text("".join(
        json.dumps({"row_index": i, "status": st_, "levels": lv,
                    "response": {"m": m, "backlog": lv["C"] - 1}}) + "\n"
        for i, (lv, st_, m) in enumerate(rows)))
    top = [{"levels": {"A": 16, "B": 16, "C": c}, "coded": {}, "predicted": 30.0 - i}
           for i, c in enumerate((64, 45, 32, 23, 16, 11))]
    it.joinpath("recommendation.json").write_text(json.dumps({
        "stage": "screen", "levels": top[0]["levels"], "top_candidates": top,
        "model_adequate": model_adequate,
        "supported_feasible_candidate": {
            "levels": pool[0] if pool else None, "pool": [
                {"levels": lv, "coded": {}, "predicted": 20.0} for lv in pool],
        },
    }))
    return pol, wd, parse_factors(list(s.factors))


_LEADER = {"A": 16, "B": 16, "C": 1}
_SUPPORTED = {"A": 16, "B": 16, "C": 8}
_ROWS = [(_LEADER, "complete", 17.2), ({"A": 9, "B": 9, "C": 8}, "complete", 16.0),
         ({"A": 2, "B": 2, "C": 64}, "infeasible", 14.0)]


def test_round_one_seats_the_supported_candidate_after_the_anchors(tmp_path):
    pol, wd, f = _confirm_fixture(tmp_path, k=3, model_adequate=True,
                                  pool=[_SUPPORTED], rows=_ROWS)
    _rows, payload = stage_runner._confirm_rows(pol, wd, f, "m", "maximize", 3)
    fins = [(x["levels"], x["why"]) for x in payload["finalists"]]
    assert [lv for lv, _ in fins] == [{"A": 16, "B": 16, "C": 64}, _LEADER, _SUPPORTED]
    assert "supported-feasible" in fins[2][1]


def test_at_two_seats_the_seat_displaces_the_model_pick_never_a_measured_one(tmp_path):
    for adequate in (True, False):
        pol, wd, f = _confirm_fixture(tmp_path / str(adequate), k=2,
                                      model_adequate=adequate, pool=[_SUPPORTED],
                                      rows=_ROWS)
        _rows, payload = stage_runner._confirm_rows(pol, wd, f, "m", "maximize", 3)
        lvs = [x["levels"] for x in payload["finalists"]]
        assert _LEADER in lvs and _SUPPORTED in lvs and len(lvs) == 2, (adequate, lvs)


def test_the_seat_never_duplicates_and_needs_two_seats(tmp_path):
    pol, wd, f = _confirm_fixture(tmp_path / "dup", k=3, model_adequate=True,
                                  pool=[_LEADER], rows=_ROWS)
    _rows, payload = stage_runner._confirm_rows(pol, wd, f, "m", "maximize", 3)
    lvs = [json.dumps(x["levels"], sort_keys=True) for x in payload["finalists"]]
    assert len(lvs) == len(set(lvs)) == 3
    pol, wd, f = _confirm_fixture(tmp_path / "one", k=1, model_adequate=True,
                                  pool=[_SUPPORTED], rows=_ROWS)
    _rows, payload = stage_runner._confirm_rows(pol, wd, f, "m", "maximize", 3)
    assert [x["levels"] for x in payload["finalists"]] == [{"A": 16, "B": 16, "C": 64}]


def test_round_r_top_up_seats_the_next_supported_candidate_not_a_retired_one(tmp_path):
    from orchestrator.optimize.policy import append_transition

    second = {"A": 16, "B": 9, "C": 8}
    pol, wd, f = _confirm_fixture(tmp_path, k=3, model_adequate=True,
                                  pool=[_SUPPORTED, second], rows=_ROWS)
    # Round 1 measured the supported candidate, it lost and its bound retired it.
    (wd / "runs" / "iter-3").mkdir()
    (wd / "runs" / "iter-3" / "confirmation.json").write_text(json.dumps({
        "round": 1, "best": "f0", "epsilon": 0.5, "bounds": {"f1": 0.1},
        "finalists": [
            {"key": "f0", "levels": _LEADER, "status": "ok"},
            {"key": "f1", "levels": _SUPPORTED, "status": "ok"},
        ],
    }))
    append_transition(wd, {"iteration": 3, "from": "confirm", "to": "confirm",
                           "rule": {}, "observations": {}, "policy_hash": ""})
    _rows, payload = stage_runner._confirm_rows(pol, wd, f, "m", "maximize", 4)
    fins = payload["finalists"]
    lvs = [x["levels"] for x in fins]
    assert _SUPPORTED not in lvs
    assert lvs[:2] == [_LEADER, second], lvs
    assert "supported-feasible" in fins[1]["why"]
