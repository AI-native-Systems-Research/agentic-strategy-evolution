"""Item 3 of #321: run-order concealment.

The run-order seed used to be the iteration index, so every campaign's
iteration-2 screen ran its rows in the SAME order: a periodic environmental
effect (a nightly job, a thermal cycle) would line up across campaigns. The
seed is now sha256(policy hash, iteration), and the policy hash covers a random
salt drawn at compile and recorded, so the orders differ between campaigns and
are still reproducible from the record. Policies compiled before this keep
derivation 1. Behavioral, zero LLM.
"""
from __future__ import annotations

import json

import pytest

from orchestrator.optimize import policy as policy_mod
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.reanalyze import reanalyze
from orchestrator.optimize.synthetic import SURFACES


def _orders(work_dir):
    return {p.parent.name: json.loads(p.read_text())["run_order"]
            for p in sorted(work_dir.glob("runs/iter-*/design_matrix.json"))}


def _salted(salt):
    c = synthetic_campaign(SURFACES["bowl"]())
    return {"policy": {**(c["optimization"].get("policy") or {}), "run_order_salt": salt}}


def test_two_campaigns_differing_only_in_salt_run_rows_in_different_orders(tmp_path):
    """Pre-fix both campaigns' screens shared seed = iteration, so the orders
    were identical; this is the concrete input that broke concealment."""
    a = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path / "a",
                               campaign_overrides=_salted("0" * 32))
    b = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path / "b",
                               campaign_overrides=_salted("f" * 32))
    oa, ob = _orders(a.work_dir), _orders(b.work_dir)
    assert oa.keys() == ob.keys() and oa
    assert oa["iter-2"] != ob["iter-2"], "the screen's run order is not concealed"
    seed = json.loads((a.work_dir / "runs/iter-2/design_matrix.json").read_text())["run_order_seed"]
    assert seed != 2


def test_the_salt_is_in_the_policy_and_covered_by_its_hash(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=3, parent_dir=tmp_path,
                               campaign_overrides=_salted("ab" * 16))
    pol = json.loads((r.work_dir / "policy.json").read_text())
    assert pol["run_order"] == {"derivation": 2, "salt": "ab" * 16}
    rec = json.loads((r.work_dir / "run_order.epoch-1.json").read_text())
    assert rec["salt"] == "ab" * 16 and rec["source"] == "declared"
    # The recorded seed is recomputable from the policy alone.
    dm = json.loads((r.work_dir / "runs/iter-2/design_matrix.json").read_text())
    assert dm["run_order_seed"] == policy_mod.run_order_seed(pol, 2)
    # Swapping the salt changes the hash, so it cannot be changed silently.
    forged = {**pol, "run_order": {"derivation": 2, "salt": "cd" * 16}}
    assert policy_mod.policy_hash(forged) != policy_mod.policy_hash(pol)


def test_an_undeclared_salt_is_random_per_campaign_and_recorded(tmp_path):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import _compile_and_write_policy

    c = synthetic_campaign(SURFACES["bowl"]())
    salts = []
    for name in ("x", "y"):
        import os

        os.environ["NOUS_CAMPAIGN_PARENT"] = str(tmp_path / name)
        try:
            wd = setup_work_dir(f"r-{name}", repo_path=None, campaign=c)
        finally:
            os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        pol = _compile_and_write_policy(c, wd)
        rec = json.loads((wd / "run_order.epoch-1.json").read_text())
        assert rec["source"] == "random" and rec["salt"] == pol["run_order"]["salt"]
        # Recompiling the same epoch reads the recorded salt back: same hash.
        assert policy_mod.policy_hash(_compile_and_write_policy(c, wd)) == \
            policy_mod.policy_hash(pol)
        salts.append(rec["salt"])
    assert salts[0] != salts[1]


def test_a_campaign_compiled_before_concealment_still_reanalyzes_by_the_old_rule(
        tmp_path, monkeypatch):
    """A work_dir an older Nous wrote has no salt record and no run_order block:
    its seeds were the iteration. Reanalysis must reproduce it with that rule."""
    from orchestrator.optimize import stage_runner

    monkeypatch.setattr(stage_runner, "_run_order_salt", lambda *a, **k: None)
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=5, parent_dir=tmp_path)
    monkeypatch.undo()
    assert "run_order" not in json.loads((r.work_dir / "policy.json").read_text())
    assert not list(r.work_dir.glob("run_order.epoch-*.json"))
    dm = json.loads((r.work_dir / "runs/iter-2/design_matrix.json").read_text())
    assert dm["run_order_seed"] == 2
    res = reanalyze(r.work_dir)
    assert res.identical, res.differences


def test_a_concealed_campaign_reanalyzes_identically(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=5, parent_dir=tmp_path)
    assert json.loads((r.work_dir / "policy.json").read_text())["run_order"]["derivation"] == 2
    res = reanalyze(r.work_dir)
    assert res.identical, res.differences


def test_an_edited_salt_record_is_a_reanalysis_difference(tmp_path):
    r = run_synthetic_campaign(SURFACES["bowl"](), seed=5, parent_dir=tmp_path)
    p = r.work_dir / "run_order.epoch-1.json"
    rec = json.loads(p.read_text())
    rec["salt"] = "1" * 32
    p.write_text(json.dumps(rec))
    res = reanalyze(r.work_dir)
    assert not res.identical
    assert any(d["file"] == "policy.json" for d in res.differences)


@pytest.mark.parametrize("it", [1, 2, 7])
def test_derivation_one_is_the_iteration(it):
    assert policy_mod.run_order_seed({}, it) == it
