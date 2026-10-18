"""WP-D D1 / P6b: the opt-in ALLOCATE confirm round (``design.confirm.allocate``).

Behavioral: every campaign runs through the synthetic harness (zero LLM calls,
no subprocess) and the assertions read what lands on disk -- policy.json,
transitions.jsonl, confirmation.json, report.json -- or what the pure seams
(``compile_policy``, ``replicate_floor``, the validator) return.

Oracles (spec wp-d-decision-theoretic-allocation.md D4):
1. recombination seats a configuration no measured point had, and the front
   improves over the same campaign without allocate;
2. an inadequate model declines (``model_inadequate``) and seats nothing;
3. certification soundness under adaptive allocation (the heavy sweep; a
   small in-suite subset here);
4. the policy hash is unchanged when allocate is not declared.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orchestrator.optimize import allocate, allocate_seat
from orchestrator.optimize.harness import (
    evaluate_pareto_campaign,
    run_synthetic_campaign,
    synthetic_campaign,
)
from orchestrator.optimize.policy import (
    ALLOCATE_ACCOUNTING,
    compile_policy,
    confirm_looks,
    policy_hash,
    replicate_floor,
)
from orchestrator.optimize.synthetic import ALLOCATE_SURFACES, PARETO_SURFACES, SURFACES

NAMED = {**allocate.DECLINE_REASONS, **allocate_seat.SEAT_DECLINE_REASONS}


def _with_allocate(surface, seats=2, **design_over):
    """The campaign's own design block with ``confirm.allocate`` declared and,
    single-objective, the confirm replicates OMITTED (the default is the
    raised floor -- what an author following the guide writes)."""
    d = copy.deepcopy(synthetic_campaign(surface)["optimization"]["design"])
    d["confirm"]["allocate"] = {"seats": seats}
    if not surface.objectives:
        d["confirm"].pop("replicates", None)
    d["confirm"].update(design_over)
    return {"design": d}


def _confirmations(work_dir) -> list[dict]:
    ps = sorted(Path(work_dir).glob("runs/iter-*/confirmation.json"),
                key=lambda p: int(p.parent.name.split("-")[1]))
    return [json.loads(p.read_text()) for p in ps]


def _transitions(work_dir) -> list[dict]:
    p = Path(work_dir) / "transitions.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def _levels_measured_before(work_dir, iteration: int) -> set[str]:
    out = set()
    for p in Path(work_dir).glob("runs/iter-*/runs.jsonl"):
        if int(p.parent.name.split("-")[1]) >= iteration:
            continue
        for ln in p.read_text().splitlines():
            if ln.strip():
                out.add(json.dumps(json.loads(ln)["levels"], sort_keys=True))
    return out


# ── oracle 4: nothing changes unless the branch is declared ─────────────────

#: Policy hashes compiled by the code BEFORE P6b (nousko 022d09b). Any change
#: to an undeclared campaign's policy -- a new key, a new transition, a moved
#: divisor -- changes these, so the test fails on a non-additive change.
PRE_P6B_HASHES = {
    "bowl": "2a01e97976490de645fde7912e5a2dc525614fc15fe1be81c5ec6ff05025e3e5",
    "sla_constrained": "00e6e6f9fa4e19764bc87cc535f2eabb39ddc96efd5d8537a6fedd1f58af591d",
    "pareto_convex": "67cb865a472dbb186c32c948920e2b6b1c75579ec1975e1db3f54b48f8d5eb61",
    "pareto_with_constraint": "60c66d5fc8de9f96fa1337409b7c87e03725edec721b30462b631259a5a68cfe",
}


def _shapes():
    return {
        "bowl": synthetic_campaign(SURFACES["bowl"]()),
        "sla_constrained": synthetic_campaign(
            SURFACES["sla"](), response={
                "primary": {"metric": "m", "direction": "maximize"},
                "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]}),
        "pareto_convex": synthetic_campaign(PARETO_SURFACES["pareto_convex"]()),
        "pareto_with_constraint": synthetic_campaign(
            PARETO_SURFACES["pareto_with_constraint"]()),
    }


@pytest.mark.parametrize("shape", sorted(PRE_P6B_HASHES))
def test_the_policy_hash_is_unchanged_when_allocate_is_not_declared(shape):
    c = _shapes()[shape]
    assert policy_hash(compile_policy(c)) == PRE_P6B_HASHES[shape]
    # ... and declaring it is a different, hashed pre-registration.
    c["optimization"]["design"]["confirm"]["allocate"] = {"seats": 1}
    assert policy_hash(compile_policy(c)) != PRE_P6B_HASHES[shape]


def test_an_undeclared_campaign_never_sees_the_branch(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path)
    assert all("allocation" not in c for c in _confirmations(r.work_dir))
    assert all("allocate_available" not in t["observations"]
               for t in _transitions(r.work_dir))
    assert "allocate.POOL_CAP" in r.report["provenance"]["analysis_constants"]


# ── registration and the extra look ─────────────────────────────────────────

def test_the_branch_is_registered_with_its_accounting_and_one_extra_look():
    for s in (SURFACES["bowl"](), PARETO_SURFACES["pareto_convex"]()):
        base = synthetic_campaign(s)
        on = synthetic_campaign(s, **_with_allocate(s, seats=2))
        pb, po = compile_policy(base), compile_policy(on)
        rules = [t for t in po["transitions"] if t.get("accounting") == ALLOCATE_ACCOUNTING]
        assert len(rules) == 1 and rules[0]["from"] == rules[0]["to"] == "confirm"
        assert rules[0]["when"]["allocate_available"] is True
        assert po["states"]["confirm"]["design"]["allocate"] == {"seats": 2}
        assert confirm_looks(po) == confirm_looks(pb) + 1


def test_the_replicate_floor_rises_when_allocate_is_declared():
    """P3's floor uses the registered looks; the allocate look must be in it."""
    s = SURFACES["bowl"]()
    opt = synthetic_campaign(s)["optimization"]
    on = synthetic_campaign(s, **_with_allocate(s))["optimization"]
    assert replicate_floor(opt) == 6 and replicate_floor(on) == 7
    pol = compile_policy({**synthetic_campaign(s), "optimization": on})
    tr = pol["objective"]["terminal_robustness"]
    assert tr["floor"] == 7
    # delta_t / (looks (S - 1)) = 0.05 / (2 x 2): the round cap 1 plus the
    # allocate look, over 2 challengers (0.05 / 2 and floor 6 without it).
    assert tr["level_for_floor"] == pytest.approx(0.05 / 4)
    assert pol["states"]["confirm"]["design"]["replicates"] == 7  # the default is the floor


def test_every_confirm_divisor_charges_the_look_even_when_unspent(tmp_path):
    """Round 1 of a 1-round campaign with allocate declared is judged at
    delta_terminal / 2 whether or not the allocate round ever runs; the
    multi-objective certificate at delta_terminal / (rounds + 1)."""
    s = SURFACES["bowl"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path / "so",
                               campaign_overrides=_with_allocate(s))
    c1 = _confirmations(r.work_dir)[0]
    assert c1["alpha_spending"]["looks"] == 2
    assert c1["delta_terminal"] == pytest.approx(0.05 / 2)
    assert "allocate" in c1["alpha_spending"]["rule"]
    m = PARETO_SURFACES["pareto_convex"]()
    rm = evaluate_pareto_campaign(m, seed=1, parent_dir=tmp_path / "mo",
                                  campaign_overrides=_with_allocate(m))
    par = _confirmations(rm["work_dir"])[0]["pareto"]
    assert par["delta_certification"] == pytest.approx(0.05 / 3)   # 2 rounds + allocate


def test_validation_refuses_a_declared_replicate_count_the_look_makes_uncertifiable():
    from orchestrator.validate import validate_optimization_campaign

    s = SURFACES["bowl"]()
    c = synthetic_campaign(s, **_with_allocate(s, replicates=6))
    errs = validate_optimization_campaign(c)
    assert any("allocate_look_below_replicate_floor" in e for e in errs), errs
    ok = synthetic_campaign(s, **_with_allocate(s))           # replicates omitted
    assert not any("allocate" in e for e in validate_optimization_campaign(ok))
    big = synthetic_campaign(s, **_with_allocate(s, seats=4))  # shortlist 3
    assert any("allocate_seats_exceed_shortlist" in e
               for e in validate_optimization_campaign(big))


def test_the_charged_campaign_delta_mode_still_certifies_at_the_defaults(tmp_path):
    """Under ``campaign_delta`` and the P3 floor the extra look raises the
    floor 7 -> 8, which the default replicates take, so certification stays
    possible (measured: bowl seeds 1, 6 certify with and without it)."""
    s = SURFACES["bowl"]()
    over = {**_with_allocate(s), "policy": {"campaign_delta": {"total": 0.1}}}
    certified = 0
    for seed in (1, 6):
        r = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides=over)
        pol = json.loads((r.work_dir / "policy.json").read_text())
        assert pol["objective"]["terminal_robustness"]["floor"] == 8
        assert pol["states"]["confirm"]["design"]["replicates"] == 8
        certified += bool(r.report.get("certified"))
    assert certified == 2


# ── oracle 1: recombination finds what no measured point had ────────────────

@pytest.fixture(scope="module")
def discrete_front(tmp_path_factory):
    """``pareto_three_discrete`` (levels-only knobs, 64 configurations) at a
    tight shortlist, with and without allocate, seeds 1-3."""
    s = ALLOCATE_SURFACES["pareto_three_discrete"]()
    out = {}
    for seed in (1, 2, 3):
        for on in (False, True):
            d = copy.deepcopy(synthetic_campaign(s)["optimization"]["design"])
            d["confirm"]["shortlist_size"] = 4
            if on:
                d["confirm"]["allocate"] = {"seats": 2}
            out[(seed, on)] = evaluate_pareto_campaign(
                s, seed=seed, parent_dir=tmp_path_factory.mktemp(f"d{seed}{int(on)}"),
                campaign_overrides={"design": d, "policy": {"confirm_max_rounds": 2}})
    return out


def test_recombination_seats_a_configuration_no_measured_point_had(discrete_front):
    for seed in (1, 2, 3):
        r = discrete_front[(seed, True)]
        confs = _confirmations(r["work_dir"])
        alloc = confs[0]["allocation"]
        assert alloc["declined"] is None
        recomb = [x for x in alloc["seats"] if x["source"] == "front_recombination"]
        assert recomb, alloc["seats"]
        # ... a configuration whose every knob value some measured front point
        # had, but which no row had measured before the allocate round.
        basis = alloc["method"]["pool"]["disagreeing_knobs"]
        it2 = confs[1]["iteration"]
        before = _levels_measured_before(r["work_dir"], it2)
        for x in recomb:
            assert json.dumps(x["levels"], sort_keys=True) not in before
            assert any(x["levels"][k] in v for k, v in basis.items())
        # The next round measured it on fresh replicates (it is a finalist).
        fin = {json.dumps(f["levels"], sort_keys=True): f for f in confs[1]["finalists"]}
        for x in recomb:
            f = fin[json.dumps(x["levels"], sort_keys=True)]
            assert f["why"].startswith("allocate:") and f["n"] >= 3


def test_the_front_improves_and_stays_sound_with_allocate(discrete_front):
    """Measured: hv_ratio 0.887 / 0.964 / 0.908 without, 0.967 / 0.972 /
    0.972 with allocate (seeds 1-3); every run certifies, none falsely."""
    for seed in (1, 2, 3):
        base, on = discrete_front[(seed, False)], discrete_front[(seed, True)]
        assert on["hv_ratio"] > base["hv_ratio"], (seed, base["hv_ratio"], on["hv_ratio"])
        assert not on["false_certified"] and not base["false_certified"]
        assert on["n_confident_off_front"] == 0
        assert on["certified"]


def test_single_objective_seats_a_new_configuration_and_judges_it_freshly(tmp_path):
    """bowl seed 3: the first round does not certify at the cap, the allocator
    seats two configurations the campaign never ran, the allocate round
    measures them with the floor's replicates, and the campaign certifies."""
    s = SURFACES["bowl"]()
    r = run_synthetic_campaign(s, seed=3, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    trans = _transitions(r.work_dir)
    assert [t["rule"].get("accounting") for t in trans].count(ALLOCATE_ACCOUNTING) == 1
    c1, c2 = _confirmations(r.work_dir)[:2]
    seats = c1["allocation"]["seats"]
    assert seats and c1["allocation"]["declined"] is None
    before = _levels_measured_before(r.work_dir, c2["iteration"])
    fin = {json.dumps(f["levels"], sort_keys=True): f for f in c2["finalists"]}
    for x in seats:
        k = json.dumps(x["levels"], sort_keys=True)
        assert k not in before and fin[k]["n"] == 7
    assert r.report["certified"] and r.true_gap <= r.report["epsilon"]


# ── oracle 2 + every decline named ──────────────────────────────────────────

def test_an_inadequate_model_declines_and_seats_nothing(tmp_path):
    """bowl seed 2: the epoch's model is rejected. The allocate record names
    ``model_inadequate``, seats nothing, and the branch never fires."""
    s = SURFACES["bowl"]()
    r = run_synthetic_campaign(s, seed=2, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    assert r.report["model_adequate"] is False
    allocs = [c["allocation"] for c in _confirmations(r.work_dir) if "allocation" in c]
    assert allocs and all(a["declined"] == "model_inadequate" and a["seats"] == []
                          for a in allocs)
    assert not any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
                   for t in _transitions(r.work_dir))
    assert all(t["observations"].get("allocate_available") in (None, False)
               for t in _transitions(r.work_dir))


def test_an_unknown_adequacy_verdict_declines_with_its_own_name(tmp_path):
    s = SURFACES["bowl"]()
    r = run_synthetic_campaign(s, seed=3, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    pol = json.loads((r.work_dir / "policy.json").read_text())
    c1 = _confirmations(r.work_dir)[0]
    from orchestrator.optimize.factors import parse_factors

    rec = {"model_adequate": None, "iteration": 2}
    out = allocate_seat.plan(pol, r.work_dir, parse_factors(
        synthetic_campaign(s)["optimization"]["factors"]), c1, rec)
    assert out["declined"] == "model_adequacy_unknown" and out["seats"] == []


@pytest.mark.parametrize("name,seeds", [("bowl", (1, 2, 3)), ("step_cliff", (1, 2))])
def test_every_decline_is_named(name, seeds, tmp_path):
    from orchestrator.optimize.synthetic import NON_QUADRATIC

    s = (SURFACES.get(name) or NON_QUADRATIC[name])()
    for seed in seeds:
        r = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides=_with_allocate(s))
        for c in _confirmations(r.work_dir):
            a = c.get("allocation")
            if a is None:
                continue
            if a["declined"] is None:
                assert a["seats"]
            else:
                assert a["declined"] in NAMED and a["detail"] and a["seats"] == []


# ── allocation cannot leak into inference ───────────────────────────────────

def test_rewriting_every_predicted_number_leaves_every_bound_unchanged(tmp_path, monkeypatch):
    """Same seats, scrambled predictions / scores / rationales in the record:
    every bound, certificate and recommendation on disk is identical. Only the
    seats' fresh replicates reach inference."""
    s = SURFACES["bowl"]()
    a = run_synthetic_campaign(s, seed=3, parent_dir=tmp_path / "a",
                               campaign_overrides=_with_allocate(s))
    real = allocate_seat.plan

    def scrambled(*args, **kw):
        out = real(*args, **kw)
        for x in out.get("ranked_top") or []:
            x["score"], x["rationale"] = -1e9, "scrambled"
        for x in out.get("seats") or []:
            x["why"] = "allocate: scrambled"
        out["method"] = {"scrambled": True}
        return out

    monkeypatch.setattr(allocate_seat, "plan", scrambled)
    b = run_synthetic_campaign(s, seed=3, parent_dir=tmp_path / "b",
                               campaign_overrides=_with_allocate(s))
    keys = ("certified", "residual_regret_terminal", "residual_regret_model",
            "epsilon", "recommendation", "certification_withheld", "global_bound")
    assert {k: a.report.get(k) for k in keys} == {k: b.report.get(k) for k in keys}
    for ca, cb in zip(_confirmations(a.work_dir), _confirmations(b.work_dir)):
        for k in ("bounds", "terminal_bound", "residual_regret_terminal", "certified",
                  "delta_terminal", "global_bound"):
            assert ca.get(k) == cb.get(k), k
