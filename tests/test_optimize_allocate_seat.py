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

#: Policy hashes compiled by the code immediately BEFORE P6b merged (nousko
#: 2c2e294, i.e. with P4 merged; re-pinned at the P6b merge -- P4 changed every
#: policy legitimately). Any change to an undeclared campaign's policy -- a new
#: key, a new transition, a moved divisor -- changes these, so the test fails
#: on a non-additive change. Verified equal on 2c2e294 and on the merge.
PRE_P6B_HASHES = {
    "bowl": "29ce74bbc27957ccb85e4378bef0ee8c5bd7152edc4295a8c3eba58773503f78",
    "sla_constrained": "bad9a20d0c9bea24dc83130f5414d6923d5a960885001c88cc3df733656946fc",
    "pareto_convex": "c1f405ab4aed730ca35c4c786f9b6ba12516e026a3421df974939da4eaba05b1",
    "pareto_with_constraint": "ef3a3cfa066f8e8823206ef9418cdd5958c9c80b907ed23b3eb30b723aba7645",
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
    assert not any(k.startswith("allocate.")
                   for k in r.report["provenance"]["analysis_constants"])


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

DISCRETE_SEEDS = (1, 3, 5, 6)


@pytest.fixture(scope="module")
def discrete_front(tmp_path_factory):
    """``pareto_three_discrete`` (levels-only knobs, 64 configurations) at
    shortlist 5, two rounds, with and without allocate. Seeds 1, 3, 5, 6 (the
    seeds whose gap-fill round leaves a free seat; seed 2 declines
    ``no_free_seat``, seeds 4 and 8 ``model_inadequate``)."""
    s = ALLOCATE_SURFACES["pareto_three_discrete"]()
    out = {}
    for seed in DISCRETE_SEEDS:
        for on in (False, True):
            d = copy.deepcopy(synthetic_campaign(s)["optimization"]["design"])
            d["confirm"]["shortlist_size"] = 5
            if on:
                d["confirm"]["allocate"] = {"seats": 2}
            out[(seed, on)] = evaluate_pareto_campaign(
                s, seed=seed, parent_dir=tmp_path_factory.mktemp(f"d{seed}{int(on)}"),
                campaign_overrides={"design": d, "policy": {"confirm_max_rounds": 2}})
    return out


def test_recombination_seats_a_configuration_no_measured_point_had(discrete_front):
    for seed in DISCRETE_SEEDS:
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
    """Measured (seeds 1, 3, 5, 6): hv_ratio 0.943 / 0.908 / 0.924 / 0.972
    without, 0.977 / 0.967 / 0.969 / 0.991 with allocate; every run
    certifies, none falsely. Allocator seats come after the gap fills and the
    in-contention front points (review M2), so this is net of displacement."""
    for seed in DISCRETE_SEEDS:
        base, on = discrete_front[(seed, False)], discrete_front[(seed, True)]
        assert on["hv_ratio"] > base["hv_ratio"], (seed, base["hv_ratio"], on["hv_ratio"])
        assert not on["false_certified"] and not base["false_certified"]
        assert on["n_confident_off_front"] == 0
        assert on["certified"]


def test_single_objective_seats_a_new_configuration_and_judges_it_freshly(tmp_path):
    """saddle seed 1: the round at the cap does not certify, the allocator
    (knowledge gradient per run, positive) seats two configurations the
    campaign never ran, and the allocate round measures them with the floor's
    replicates like every other finalist."""
    s = SURFACES["saddle"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    trans = _transitions(r.work_dir)
    assert [t["rule"].get("accounting") for t in trans].count(ALLOCATE_ACCOUNTING) == 1
    c1, c2 = _confirmations(r.work_dir)[:2]
    seats = c1["allocation"]["seats"]
    assert seats and c1["allocation"]["declined"] is None
    assert all(x["score"] > 0 for x in seats)
    assert c1["allocation"]["method"]["score"] == "knowledge_gradient_per_run"
    before = _levels_measured_before(r.work_dir, c2["iteration"])
    fin = {json.dumps(f["levels"], sort_keys=True): f for f in c2["finalists"]}
    for x in seats:
        k = json.dumps(x["levels"], sort_keys=True)
        assert k not in before and fin[k]["n"] == 7 and fin[k]["why"].startswith("allocate:")
    assert c2["alpha_spending"]["looks"] == 2       # the look the branch registered
    # Not vacuous (review M3): this run ends UNcertified, so state that, and
    # the answer is still within epsilon of the truth.
    assert r.report["certified"] is False
    assert r.true_gap <= r.report["epsilon"]


def test_a_model_that_expects_no_gain_spends_no_round(tmp_path):
    """bowl seed 3: every seatable candidate's KG per run is zero, so the
    branch declines ``no_expected_value`` and the campaign ends at the cap."""
    s = SURFACES["bowl"]()
    r = run_synthetic_campaign(s, seed=3, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    a = _confirmations(r.work_dir)[0]["allocation"]
    assert a["declined"] == "no_expected_value" and a["seats"] == []
    assert not any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
                   for t in _transitions(r.work_dir))


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
    records = 0
    for seed in seeds:
        r = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path / str(seed),
                                   campaign_overrides=_with_allocate(s))
        for c in _confirmations(r.work_dir):
            a = c.get("allocation")
            if a is None:
                continue
            records += 1
            if a["declined"] is None:
                assert a["seats"]
            else:
                assert a["declined"] in NAMED and a["detail"] and a["seats"] == []
    assert records >= 1, f"{name}: no allocation record was written on any seed"


# ── allocation cannot leak into inference ───────────────────────────────────

def test_rewriting_every_predicted_number_leaves_every_bound_unchanged(tmp_path, monkeypatch):
    """Same seats, every SCORE and RATIONALE in the allocation record (ranked
    candidates and seats) and the whole ``method`` block scrambled: every
    bound, certificate and recommendation on disk is identical, over the same
    number of rounds, with the allocate rule firing in both arms. Only the
    seats' fresh replicates reach inference. (The seats' levels are kept: a
    different seat is a different experiment, not a leak.)"""
    s = SURFACES["saddle"]()
    a = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path / "a",
                               campaign_overrides=_with_allocate(s))
    assert any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
               for t in _transitions(a.work_dir))          # the round ran
    real = allocate_seat.plan

    def scrambled(*args, **kw):
        out = real(*args, **kw)
        for x in out.get("ranked_top") or []:
            x["score"], x["rationale"] = -1e9, "scrambled"
        for x in out.get("seats") or []:
            x["why"], x["score"] = "allocate: scrambled", 1e9
        out["method"] = {"scrambled": True}
        return out

    monkeypatch.setattr(allocate_seat, "plan", scrambled)
    b = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path / "b",
                               campaign_overrides=_with_allocate(s))
    assert any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
               for t in _transitions(b.work_dir))
    assert len(_confirmations(a.work_dir)) == len(_confirmations(b.work_dir)) >= 2
    keys = ("certified", "residual_regret_terminal", "residual_regret_model",
            "epsilon", "recommendation", "certification_withheld", "global_bound")
    assert {k: a.report.get(k) for k in keys} == {k: b.report.get(k) for k in keys}
    for ca, cb in zip(_confirmations(a.work_dir), _confirmations(b.work_dir)):
        for k in ("bounds", "terminal_bound", "residual_regret_terminal", "certified",
                  "delta_terminal", "global_bound"):
            assert ca.get(k) == cb.get(k), k


def test_allocated_seats_never_displace_a_challenger_still_in_contention(tmp_path):
    """P6b review H1. Take saddle seed 1 to the allocate round, then make one
    round-1 challenger's bound exceed epsilon (still in contention) and
    rebuild the allocate round's shortlist: the challenger is re-seated, and
    the allocator's picks fill only the slot left (shortlist_size 3)."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _confirm_rows

    s = SURFACES["saddle"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s, seats=2),
                               max_iterations=4)        # stop before the allocate round runs
    wd = r.work_dir
    trans = _transitions(wd)
    assert trans[-1]["rule"].get("accounting") == ALLOCATE_ACCOUNTING
    p1 = sorted(wd.glob("runs/iter-*/confirmation.json"))[-1]
    c1 = json.loads(p1.read_text())
    key = next(k for k in c1["bounds"] if k != c1["best"])
    c1["bounds"][key] = 10.0 * c1["epsilon"]            # in contention
    p1.write_text(json.dumps(c1))
    challenger = next(f["levels"] for f in c1["finalists"] if f["key"] == key)
    pol = json.loads((wd / "policy.json").read_text())
    factors = parse_factors(synthetic_campaign(s)["optimization"]["factors"])
    _rows, payload = _confirm_rows(pol, wd, factors, "m", "maximize", 99)
    seated = [f["levels"] for f in payload["finalists"]]
    whys = [f["why"] for f in payload["finalists"]]
    assert challenger in seated, whys
    assert sum(w.startswith("allocate:") for w in whys) == 1, whys


def test_the_allocator_constants_are_recorded_when_declared(tmp_path):
    s = SURFACES["saddle"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    c = r.report["provenance"]["analysis_constants"]
    assert c["allocate.POOL_CAP"] == allocate.POOL_CAP
    assert c["allocate.MC_SEED"] == allocate.MC_SEED


# ── P6b review fix round ─────────────────────────────────────────────────────

def _to_allocate_round(s, tmp_path, seed=1, **design_over):
    """Run ``s`` until the allocate rule has fired (the allocate round not yet
    run); returns the work_dir. saddle seed 1 reaches it at iteration 4."""
    r = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s, **design_over),
                               max_iterations=4)
    assert _transitions(r.work_dir)[-1]["rule"].get("accounting") == ALLOCATE_ACCOUNTING
    return r.work_dir


def test_edited_registered_seats_are_refused_not_measured(tmp_path):
    """Review H1 (probe tamper.py). Edit the seats round r registered: the
    allocate round refuses to measure them (naming the file), and the edit is
    visible to the provenance input hashes."""
    from orchestrator.optimize import provenance
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import OptimizationGateFailed, _confirm_rows

    s = SURFACES["saddle"]()
    wd = _to_allocate_round(s, tmp_path)
    h0 = provenance.input_hashes(wd)
    assert any(k.endswith("/allocation.json") for k in h0)
    p1 = sorted(wd.glob("runs/iter-*/confirmation.json"),
                key=lambda p: int(p.parent.name.split("-")[1]))[-1]
    c1 = json.loads(p1.read_text())
    c1["allocation"]["seats"] = [{"levels": {"A": 9, "B": 2}, "why": "allocate: hand-picked",
                                  "score": 1.0}]
    p1.write_text(json.dumps(c1))
    a1 = p1.parent / "allocation.json"
    a1.write_text(json.dumps(c1["allocation"]))
    assert provenance.input_hashes(wd) != h0
    pol = json.loads((wd / "policy.json").read_text())
    factors = parse_factors(synthetic_campaign(s)["optimization"]["factors"])
    with pytest.raises(OptimizationGateFailed, match=p1.parent.name + "/confirmation.json"):
        _confirm_rows(pol, wd, factors, "m", "maximize", 99)


def test_edited_registered_seats_are_refused_multi_objective(tmp_path):
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import OptimizationGateFailed, _confirm_rows

    s = ALLOCATE_SURFACES["pareto_three_discrete"]()
    d = copy.deepcopy(synthetic_campaign(s)["optimization"]["design"])
    d["confirm"]["shortlist_size"] = 5
    d["confirm"]["allocate"] = {"seats": 2}
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path, max_iterations=4,
                               campaign_overrides={"design": d,
                                                   "policy": {"confirm_max_rounds": 2}})
    wd = r.work_dir
    p1 = sorted(wd.glob("runs/iter-*/confirmation.json"),
                key=lambda p: int(p.parent.name.split("-")[1]))[-1]
    c1 = json.loads(p1.read_text())
    assert c1["allocation"]["seats"]
    c1["allocation"]["seats"][0]["levels"] = {"A": 2, "B": 2, "C": 2}
    p1.write_text(json.dumps(c1))
    pol = json.loads((wd / "policy.json").read_text())
    factors = parse_factors(synthetic_campaign(s)["optimization"]["factors"])
    with pytest.raises(OptimizationGateFailed, match="confirmation.json"):
        _confirm_rows(pol, wd, factors, "f1", "maximize", 99)


def test_an_allocate_campaign_reanalyzes_identically(tmp_path):
    """allocation.json is a hashed input; replaying the campaign re-derives it
    (and every other artifact) identically."""
    from orchestrator.optimize.reanalyze import reanalyze

    s = SURFACES["saddle"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    assert any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
               for t in _transitions(r.work_dir))
    res = reanalyze(r.work_dir)
    assert res.identical, (res.differences, res.input_changes)


def test_an_allocate_round_with_no_free_seat_is_not_spent(tmp_path):
    """Review M1 (probe zero_seat.py). When the next round's carry-over (the
    winner, the fitted argmax, every challenger still in contention) fills
    shortlist_size, the branch declines ``no_free_seat`` and does not fire;
    report.md says why."""
    from orchestrator.optimize.factors import parse_factors

    s = SURFACES["saddle"]()
    wd = _to_allocate_round(s, tmp_path / "a")
    pol = json.loads((wd / "policy.json").read_text())
    c1 = _confirmations(wd)[-1]
    rec = json.loads(sorted(wd.glob("runs/iter-*/recommendation.json"))[-1].read_text())
    for k in c1["bounds"]:
        if k != c1["best"]:
            c1["bounds"][k] = 10.0 * c1["epsilon"]            # every rival in contention
    out = allocate_seat.plan(pol, wd, parse_factors(
        synthetic_campaign(s)["optimization"]["factors"]), c1, rec)
    assert out["declined"] == "no_free_seat" and out["seats"] == [] and out["free_seats"] == 0
    assert "no_free_seat" in NAMED
    # End to end: shortlist_size 1 -- the carried winner fills it, so the
    # branch never fires (seats 1 <= shortlist 1 passes validation).
    s2 = SURFACES["saddle"]()
    r = run_synthetic_campaign(s2, seed=1, parent_dir=tmp_path / "b",
                               campaign_overrides=_with_allocate(s2, seats=1,
                                                                 shortlist_size=1))
    from orchestrator.optimize.report_md import render_report_markdown

    allocs = [c["allocation"] for c in _confirmations(r.work_dir) if "allocation" in c]
    assert allocs
    for a in allocs:
        assert a["declined"] or len(a["seats"]) <= a["free_seats"]
    assert allocs[-1]["declined"] == "no_free_seat", allocs[-1]
    assert not any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
                   for t in _transitions(r.work_dir))
    md = render_report_markdown(r.work_dir)
    assert "declined `no_free_seat`" in md and "carry-over" in md


def test_every_registered_seat_is_measured_in_the_allocate_round(tmp_path):
    """Review M1 (probe seat_probe.py): wherever the rule fired, every seat it
    registered was seated (none silently squeezed out)."""
    fired = 0
    for name, seed in (("saddle", 1), ("saddle", 3)):
        s = SURFACES[name]()
        r = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path / f"{name}{seed}",
                                   campaign_overrides=_with_allocate(s))
        if not any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
                   for t in _transitions(r.work_dir)):
            continue
        fired += 1
        cs = _confirmations(r.work_dir)
        reg = cs[-2]["allocation"]["seats"]
        seated = [f for f in cs[-1]["finalists"] if f["why"].startswith("allocate:")]
        assert len(seated) == len(reg) >= 1
    assert fired


def test_mo_allocated_seats_never_displace_gap_fills_or_contested_front_points(tmp_path):
    """Review M2: the MO counterpart of the SO no-displacement test. Take
    pareto_three_discrete to the gap-fill round with seats registered, mark a
    front point ``possibly_dominated`` (in contention), and rebuild the next
    shortlist: the preferred point, every gap fill and the contested point are
    all seated ahead of the allocator's picks, which fill only what is left."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _confirm_rows

    s = ALLOCATE_SURFACES["pareto_three_discrete"]()
    d = copy.deepcopy(synthetic_campaign(s)["optimization"]["design"])
    d["confirm"]["shortlist_size"] = 5
    d["confirm"]["allocate"] = {"seats": 2}
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path, max_iterations=4,
                               campaign_overrides={"design": d,
                                                   "policy": {"confirm_max_rounds": 2}})
    wd = r.work_dir
    pol = json.loads((wd / "policy.json").read_text())
    factors = parse_factors(synthetic_campaign(s)["optimization"]["factors"])
    c1 = _confirmations(wd)[-1]
    assert c1["allocation"]["seats"]
    _rows, payload = _confirm_rows(pol, wd, factors, "f1", "maximize", 99)
    whys = [f["why"] for f in payload["finalists"]]
    first_alloc = next(i for i, w in enumerate(whys) if w.startswith("allocate:"))
    assert all(not w.startswith(("gap fill", "front point still")) for w in whys[first_alloc:]), whys
    assert any(w.startswith("gap fill") for w in whys), whys
    # In contention: one confident front point made possibly_dominated. The
    # seats' digest is untouched, so the round still verifies.
    p1 = sorted(wd.glob("runs/iter-*/confirmation.json"),
                key=lambda p: int(p.parent.name.split("-")[1]))[-1]
    chosen = c1["pareto"]["preference"]["chosen"]
    tgt = next(f for f in c1["pareto"]["front"] if f["levels"] != chosen)
    tgt["status"] = "possibly_dominated"
    p1.write_text(json.dumps(c1))
    _rows, payload = _confirm_rows(pol, wd, factors, "f1", "maximize", 99)
    seated = [f["levels"] for f in payload["finalists"]]
    whys = [f["why"] for f in payload["finalists"]]
    assert tgt["levels"] in seated, whys
    k = whys.index("front point still possibly dominated")
    assert all(not w.startswith("allocate:") for w in whys[:k]), whys


def test_an_allocator_crash_is_a_named_decline_not_a_lost_round(tmp_path, monkeypatch):
    """Review L5: an exception inside the allocator is recorded as
    ``allocator_error`` and the measured round is kept (confirmation.json and
    the report are written; the branch does not fire)."""
    from orchestrator.optimize import allocate as alloc_mod

    def boom(**kw):
        raise RuntimeError("synthetic allocator failure")

    monkeypatch.setattr(alloc_mod, "allocate", boom)
    s = SURFACES["saddle"]()
    r = run_synthetic_campaign(s, seed=1, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    a = _confirmations(r.work_dir)[0]["allocation"]
    assert a["declined"] == "allocator_error" and "synthetic allocator failure" in a["detail"]
    assert a["seats"] == [] and "allocator_error" in NAMED
    assert r.report.get("recommendation")
    assert not any(t["rule"].get("accounting") == ALLOCATE_ACCOUNTING
                   for t in _transitions(r.work_dir))


@pytest.mark.parametrize("seed", [3, 4])
def test_the_allocate_round_itself_certifies_soundly(seed, tmp_path):
    """Review M3: a case where the ALLOCATE ROUND is the round that certifies.
    saddle at half the noise: round 1 does not certify, the allocate rule
    fires, and the allocate round (with its model-chosen seats measured
    freshly) certifies -- within epsilon of the true optimum."""
    import dataclasses

    s = dataclasses.replace(SURFACES["saddle"](), noise_sd=0.025)
    r = run_synthetic_campaign(s, seed=seed, parent_dir=tmp_path,
                               campaign_overrides=_with_allocate(s))
    trans = _transitions(r.work_dir)
    i = next(k for k, t in enumerate(trans)
             if t["rule"].get("accounting") == ALLOCATE_ACCOUNTING)
    after = trans[i + 1]
    assert after["from"] == "confirm" and after["observations"]["certified"] is True
    cs = _confirmations(r.work_dir)
    assert cs[0]["certified"] is False and cs[-1]["certified"] is True
    assert any(f["why"].startswith("allocate:") for f in cs[-1]["finalists"])
    assert r.report["certified"] is True                       # non-vacuous
    assert not (r.report["certified"] and r.true_gap > r.report["epsilon"] + 1e-9)
