"""policy.json is DATA: compiled by pure Python, schema-validated, hashed.

Behavioural: assert the compiled object, its schema conformance, its hash
stability, and the structural checks — never how compile_policy is written.
"""
from __future__ import annotations

import json

import jsonschema
import pytest

from orchestrator.optimize.policy import (
    COMPARISON_OPS, OBSERVATION_KEYS, POLICY_SCHEMA_PATH, check_policy,
    compile_policy, policy_hash, pre_epoch_stages, read_policy, write_policy,
)
from orchestrator.optimize.synthetic import SURFACES
from orchestrator.optimize.harness import synthetic_campaign


def _campaign(**over):
    return synthetic_campaign(SURFACES["additive"](), **over)


def test_compiled_policy_validates_against_its_schema():
    pol = compile_policy(_campaign())
    schema = json.loads(POLICY_SCHEMA_PATH.read_text())
    jsonschema.validate(pol, schema)


def test_default_policy_has_the_documented_states_and_initial():
    pol = compile_policy(_campaign())
    assert pol["initial"] == "screen"
    assert set(pol["states"]) == {"screen", "refine", "confirm", "report", "exception"}
    assert pol["states"]["report"]["terminal"] and not pol["states"]["report"]["spends"]
    assert pol["states"]["exception"]["ends_epoch"] is True


def test_refine_is_omitted_when_no_factor_is_refinable():
    s = SURFACES["interaction_only"]()          # all two-level numerics
    pol = compile_policy(synthetic_campaign(s))
    assert "refine" not in pol["states"]
    default = [t for t in pol["transitions"] if t["from"] == "screen" and "default" in t]
    assert default and default[0]["default"] == "confirm"


def test_legacy_stages_list_controls_pre_epoch_and_enabled_states():
    c = _campaign(stages=["build", "verify", "screen"])
    assert pre_epoch_stages(c) == ["build", "verify"]
    pol = compile_policy(c)
    assert "confirm" not in pol["states"] and "refine" not in pol["states"]
    default = [t for t in pol["transitions"] if t["from"] == "screen" and "default" in t]
    assert default[0]["default"] == "report"


def test_every_conditional_transition_names_accounting_and_known_keys():
    pol = compile_policy(_campaign())
    for t in pol["transitions"]:
        if "when" in t:
            assert t.get("accounting"), t
            assert set(t["when"]) <= OBSERVATION_KEYS, t


def test_hash_is_stable_and_changes_with_the_mechanism_patch():
    a = compile_policy(_campaign(), mechanism_patch_hash="abc")
    b = compile_policy(_campaign(), mechanism_patch_hash="abc")
    c = compile_policy(_campaign(), mechanism_patch_hash="def")
    assert policy_hash(a) == policy_hash(b) != policy_hash(c)


def test_write_and_read_round_trip_with_sidecar_hash(tmp_path):
    pol = compile_policy(_campaign())
    p = write_policy(tmp_path, pol)
    assert p.name == "policy.json"
    assert (tmp_path / "policy.sha256").read_text().strip() == policy_hash(pol)
    assert read_policy(tmp_path) == pol
    assert read_policy(tmp_path / "nowhere") is None


def test_check_policy_rejects_structural_defects():
    pol = compile_policy(_campaign())
    bad = json.loads(json.dumps(pol))
    bad["transitions"].append({"from": "screen", "when": {"unicorn": True}, "to": "report"})
    errs = check_policy(bad)
    assert any("unicorn" in e for e in errs)
    assert any("accounting" in e for e in errs)
    bad2 = json.loads(json.dumps(pol))
    bad2["transitions"] = [t for t in bad2["transitions"] if not (t["from"] == "screen" and "default" in t)]
    assert any("no default" in e for e in check_policy(bad2))
    assert check_policy(pol) == []


def test_check_policy_rejects_an_unknown_comparison_operator():
    """An operator step() cannot interpret strands the branch it guards.

    Nothing else in the pipeline reports it: the policy compiles, hashes,
    schema-validates and writes, and the registered branch is simply never
    reachable. So check_policy is the only place it can be caught.
    """
    pol = compile_policy(_campaign())
    bad = json.loads(json.dumps(pol))
    bad["transitions"].append({"from": "screen", "when": {"round": {"unicorn": 3}},
                               "to": "report", "accounting": "a"})
    errs = check_policy(bad)
    assert any("unknown operator" in e and "unicorn" in e for e in errs), errs
    # the KEY was legitimate, so this must not be reported as an unknown key
    assert not any("unknown observation key" in e for e in errs), errs


def test_check_policy_rejects_vacuous_and_malformed_predicates():
    pol = compile_policy(_campaign())

    empty_when = json.loads(json.dumps(pol))
    empty_when["transitions"].append({"from": "screen", "when": {}, "to": "report", "accounting": "a"})
    assert any("match unconditionally" in e for e in check_policy(empty_when))

    empty_pred = json.loads(json.dumps(pol))
    empty_pred["transitions"].append({"from": "screen", "when": {"round": {}},
                                      "to": "report", "accounting": "a"})
    assert any("empty predicate" in e for e in check_policy(empty_pred))

    two_ops = json.loads(json.dumps(pol))
    two_ops["transitions"].append({"from": "screen", "when": {"round": {">": 1, "<": 9}},
                                   "to": "report", "accounting": "a"})
    assert any("exactly one" in e for e in check_policy(two_ops))


def test_every_emitted_operator_is_in_the_closed_vocabulary():
    """The compiler must never emit something its own checker rejects."""
    for stages in (None, ["verify", "screen", "confirm"], ["verify", "screen"]):
        c = _campaign() if stages is None else _campaign(stages=stages)
        pol = compile_policy(c)
        assert check_policy(pol) == []
        for t in pol["transitions"]:
            for spec in (t.get("when") or {}).values():
                if isinstance(spec, dict):
                    assert set(spec) <= COMPARISON_OPS, t
                else:
                    assert isinstance(spec, (bool, int, float)), t
