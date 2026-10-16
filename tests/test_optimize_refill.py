"""The registered REFILL branch: ``confirm -> confirm`` once, after vacated seats.

``policy.REFILL_ACCOUNTING``. Field case: a Go campaign's confirm (one round,
three finalists) measured two finalists infeasible; the survivor's
``R_terminal = 0`` bounded it against no feasible rival, so certification was
rightly withheld -- and two thirds of the budget bought nothing, because a
single-round epoch never refills a seat. Zero LLM calls: every campaign is a
synthetic surface with a known constrained optimum.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import orchestrator.optimize.policy as policy
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.policy import REFILL_ACCOUNTING, compile_policy
from orchestrator.optimize.synthetic import SURFACES

SEEDS = range(1, 9)
SLA = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                    "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]}}
STOCH = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                      "constraints": [{"metric": "stall_ms", "op": "<=", "value": 10}]}}
CORNER = {"response": {"primary": {"metric": "m", "direction": "maximize"},
                       "constraints": [{"metric": "p99_ms", "op": "<=", "value": 90}]}}


def _run(name, seed, ov, tmp, *, refill: bool, monkeypatch):
    monkeypatch.setattr(policy, "_REFILL_VACATED", refill)
    return run_synthetic_campaign(SURFACES[name](), seed=seed,
                                  parent_dir=tmp / f"{name}-{seed}-{refill}",
                                  campaign_overrides=ov)


def _confirmations(work_dir):
    return [json.loads(p.read_text()) for p in sorted(
        Path(work_dir).glob("runs/iter-*/confirmation.json"),
        key=lambda p: int(p.parent.name.split("-")[1]))]


def _refills(work_dir):
    lines = (Path(work_dir) / "transitions.jsonl").read_text().splitlines()
    return sum(1 for ln in lines if ln.strip()
               and (json.loads(ln).get("rule") or {}).get("accounting") == REFILL_ACCOUNTING)


def _false_certified(res, surface) -> bool:
    eps = res.report.get("epsilon") or 0.0
    return bool(res.report.get("certified")) and (
        res.true_gap > eps or bool(surface.invalid and surface.invalid(res.recommendation)))


def test_the_refill_round_reaches_two_feasible_finalists_where_one_round_withheld(
        tmp_path, monkeypatch):
    """``sla`` at the default single round: the model's top candidates all sit
    past the p99 constraint. Without the branch every seed ends on ONE feasible
    finalist (``no_feasible_rival``); with it, the one refill round seats
    candidates whose nearest measured neighbour is admissible, ends with >= 2
    feasible finalists on every seed, never certifies falsely, and the answer
    is never worse (here 1.2 -> 0.4 below the constrained optimum)."""
    s = SURFACES["sla"]()
    for seed in SEEDS:
        old = _run("sla", seed, SLA, tmp_path, refill=False, monkeypatch=monkeypatch)
        new = _run("sla", seed, SLA, tmp_path, refill=True, monkeypatch=monkeypatch)
        assert "no_feasible_rival" in old.report["certification_withheld"], seed
        last = _confirmations(new.work_dir)[-1]
        assert sum(1 for f in last["finalists"] if f["status"] == "ok") >= 2, seed
        assert _refills(new.work_dir) == 1, seed
        assert not s.invalid(new.recommendation), seed
        assert new.true_gap <= old.true_gap + 1e-9, seed
        assert not _false_certified(new, s), seed


def test_the_refill_never_certifies_falsely_on_a_stochastic_boundary(tmp_path, monkeypatch):
    s = SURFACES["stochastic_constraint_boundary"]()
    for seed in SEEDS:
        new = _run("stochastic_constraint_boundary", seed, STOCH, tmp_path,
                   refill=True, monkeypatch=monkeypatch)
        assert _refills(new.work_dir) <= 1, seed
        assert not _false_certified(new, s), seed


def test_the_refill_is_capped_at_one_round_whatever_the_round_cap(tmp_path, monkeypatch):
    """D5: on ``stochastic_constraint_boundary`` the refill round ITSELF
    vacates seats again on most seeds, so a cap that is not enforced would
    refill again. Exactly one refill wherever it fires, at round cap 1 and 3."""
    for rounds in (1, 3):
        ov = {**STOCH, "policy": {"confirm_max_rounds": rounds}}
        fired = 0
        for seed in SEEDS:
            res = _run("stochastic_constraint_boundary", seed, ov, tmp_path / str(rounds),
                       refill=True, monkeypatch=monkeypatch)
            n = _refills(res.work_dir)
            assert n <= 1, (rounds, seed, n)
            fired += n
        assert fired >= 4, (rounds, fired)


def test_the_refill_round_never_certifies_and_halves_delta(tmp_path, monkeypatch):
    """D4 (single-objective): on sla seeds 1-8 the refill round is withheld as
    shortlist_refilled, and its terminal delta is delta_terminal / round."""
    for seed in SEEDS:
        res = _run("sla", seed, SLA, tmp_path, refill=True, monkeypatch=monkeypatch)
        last = _confirmations(res.work_dir)[-1]
        assert last["round"] == 2 and last["certified"] is False, seed
        assert "shortlist_refilled" in last["certification_withheld"], seed
        assert last["delta_terminal"] == pytest.approx(0.05 / 2), seed


def test_the_refill_pool_never_offers_a_measured_inadmissible_configuration(
        tmp_path, monkeypatch):
    """D10, on the candidate list itself (``_add`` would also refuse them, so a
    seat-level check cannot see a pool that offers them -- but
    refill_available would then fire a refill with nothing new to measure)."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import (
        _measured_infeasible,
        _measured_infeasible_contains,
        _refill_candidates,
    )

    for seed in (1, 2, 3):
        res = _run("stochastic_constraint_boundary", seed, STOCH, tmp_path,
                   refill=True, monkeypatch=monkeypatch)
        factors = parse_factors(list(SURFACES["stochastic_constraint_boundary"]().factors))
        cands = _refill_candidates(res.work_dir, factors)
        invalid = _measured_infeasible(res.work_dir)
        assert invalid
        assert not any(_measured_infeasible_contains(res.work_dir, c, invalid=invalid)
                       for c in cands), seed


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items()
                if k not in ("policy_hash", "duration_ms", "last_attempt_ms")}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


@pytest.mark.parametrize("seed", SEEDS)
def test_nothing_vacated_means_nothing_changes(seed, tmp_path, monkeypatch):
    """Metamorphic: on ``infeasible_corner_interior`` no finalist is vacated,
    so every artifact is identical with and without the branch except the
    compiled policy (one more registered rule) and the hash that cites it."""
    runs = {}
    for refill in (False, True):
        res = _run("infeasible_corner_interior", seed, CORNER, tmp_path,
                   refill=refill, monkeypatch=monkeypatch)
        wd, out = Path(res.work_dir), {}
        for p in sorted(wd.rglob("*")):
            rel = str(p.relative_to(wd))
            if p.suffix == ".json" and p.name not in (
                    "policy.json", "refill_pool.json", "state.json") and (
                    "runs/" in rel or p.name == "report.json"):
                out[rel] = _strip(json.loads(p.read_text()))
            elif p.name in ("runs.jsonl", "transitions.jsonl"):
                out[rel] = [_strip(json.loads(ln)) for ln in p.read_text().splitlines()
                            if ln.strip()]
        runs[refill] = out
    assert runs[False] == runs[True]


def test_only_a_constrained_policy_registers_the_branch_and_it_comes_first():
    from orchestrator.optimize import invariants as inv

    plain = compile_policy(synthetic_campaign(SURFACES["sla"]()))
    assert not any(t.get("accounting") == REFILL_ACCOUNTING for t in plain["transitions"])
    con = compile_policy(synthetic_campaign(SURFACES["sla"](), **SLA))
    rules = [t for t in con["transitions"] if t["from"] == "confirm" and "when" in t]
    i = next(k for k, t in enumerate(rules) if t.get("accounting") == REFILL_ACCOUNTING)
    assert all("certified" not in r["when"] and r["to"] != "report" for r in rules[:i])
    assert inv.check_refill_branch(con) == []
