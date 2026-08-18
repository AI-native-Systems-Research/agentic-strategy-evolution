"""policy.json is DATA: compiled by pure Python, schema-validated, hashed.

Behavioural: assert the compiled object, its schema conformance, its hash
stability, and the structural checks — never how compile_policy is written.
"""
from __future__ import annotations

import json

import jsonschema
import pytest

from orchestrator.optimize.policy import (
    COMPARISON_OPS, OBSERVATION_KEYS, POLICY_SCHEMA_PATH, append_transition,
    check_policy, compile_policy, current_state, enumerate_paths, is_terminal,
    longest_path, policy_hash, pre_epoch_stages, read_policy, read_transitions,
    step, write_policy,
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
    """The state set of spec §3.3's table, `foldover` included.

    `foldover` joined the default set with the registered-foldover work: the
    branch has to be registered at COMPILE time, because whether the aliasing
    turns out consequential is a fact about measurements and a policy that read
    a measurement would not be a pre-registration. It is gated at runtime by
    `alias_consequential` / `foldover_affordable` instead, and removed entirely
    by `optimization.policy.foldover: false`.
    """
    pol = compile_policy(_campaign())
    assert pol["initial"] == "screen"
    assert set(pol["states"]) == {
        "screen", "foldover", "refine", "confirm", "report", "exception",
    }
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


def test_write_policy_rejects_a_schema_invalid_document(tmp_path):
    """POLICY_SCHEMA_PATH existed since Task 4; nothing called jsonschema.validate
    against it in production until now. ``check_policy`` covers the closed
    observation/operator vocabulary and reachability, not the schema's own shape
    constraints — so a policy that violates the schema but satisfies
    ``check_policy`` (e.g. a bogus ``policy_version``) must still be caught here,
    at the one place every compiled policy is persisted.
    """
    pol = compile_policy(_campaign())
    bad = json.loads(json.dumps(pol))
    bad["policy_version"] = 2          # schema pins this to the const 1
    assert check_policy(bad) == []     # check_policy has no opinion on this field
    with pytest.raises(ValueError, match="policy_version"):
        write_policy(tmp_path, bad)
    assert not (tmp_path / "policy.json").exists()


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


def test_step_takes_the_first_matching_rule_then_the_default():
    pol = compile_policy(_campaign())
    nxt, rule = step(pol, "screen", {"correctness_failed": False, "nan_response": False,
                                     "refinable_survivors": 2})
    assert nxt == "refine" and rule["to"] == "refine"
    nxt, rule = step(pol, "screen", {"correctness_failed": False, "nan_response": False,
                                     "refinable_survivors": 0})
    assert nxt == "confirm" and "default" in rule
    nxt, _ = step(pol, "screen", {"correctness_failed": True})
    assert nxt == "exception"


def test_a_nan_response_at_confirm_ends_the_epoch_like_every_other_spending_state():
    """`confirm` must not be the one spending state a NaN cannot escape.

    `screen`/`foldover`/`refine` each register `nan_response: True -> exception`
    immediately after their `correctness_failed` rule. Without the matching
    rule for `confirm`, a NaN observed there falls through to `confirm`'s own
    `"default": "confirm"` — and the caller that reports a NaN at confirm
    hardcodes `round: 0` (there is no fit, so there is no round to report), so
    the round-cap guard `{"round": {">=": max_rounds}}` never fires either.
    The epoch would self-loop at `confirm` until `max_iterations` cuts it off
    from OUTSIDE the compiled policy — the one outcome `run_campaign` does not
    register as reachable.
    """
    pol = compile_policy(_campaign())
    nxt, rule = step(pol, "confirm", {"correctness_failed": False, "nan_response": True,
                                       "round": 0, "budget_remaining": 5, "certified": False})
    assert nxt == "exception", (nxt, rule)


def test_confirm_declines_a_round_it_cannot_afford_before_the_budget_is_gone():
    """`budget_remaining < 1` is too late to be the only resource guard.

    The blunt guard fires only once literally nothing is left, so "2 runs
    remain but the next confirm round needs 9" falls through to
    `"default": "confirm"` — the epoch enters a round it cannot complete and
    the shortfall shows up as failed runs rather than as a registered
    decline. `confirm_affordable` is the same derived boolean
    `foldover_affordable` already is (a `when` predicate compares an
    observation against a CONSTANT, never against another observation), and
    it must be registered BEFORE the blunter guards so the specific reason
    reaches `transitions.jsonl`.

    Ends at `report` uncertified, not `exception`: a budget that cannot pay
    for more discrimination is a decline, exactly like the round cap — the
    campaign still has an answer, just not a certificate.
    """
    pol = compile_policy(_campaign())
    base = {"correctness_failed": False, "nan_response": False, "certified": False,
            "round": 0}
    nxt, rule = step(pol, "confirm", {
        **base, "budget_remaining": 2, "runs_needed_confirm": 9,
        "confirm_affordable": False,
    })
    assert nxt == "report", (nxt, rule)
    assert rule["when"] == {"confirm_affordable": False}, rule
    assert rule["accounting"], rule
    # The specific guard, not the blunt one: 2 runs DO remain, so
    # `budget_remaining < 1` cannot be what fired.
    assert rule["when"] != {"budget_remaining": {"<": 1}}
    # Affordable -> the round actually happens.
    nxt, _ = step(pol, "confirm", {
        **base, "budget_remaining": 20, "runs_needed_confirm": 9,
        "confirm_affordable": True,
    })
    assert nxt == "confirm"


def test_confirm_affordable_is_registered_before_the_blunter_budget_guards():
    """Order is the whole point: `step` takes the FIRST matching rule.

    Registered after `round >= max_rounds` / `budget_remaining < 1`, the
    affordability decline could never be the reported reason in the one case
    where both match, and `transitions.jsonl` would attribute a shortfall to
    an exhausted budget that still had runs in it.
    """
    pol = compile_policy(_campaign())
    confirm_rules = [t for t in pol["transitions"] if t["from"] == "confirm"]
    keys = [tuple(sorted(t["when"])) if "when" in t else ("__default__",)
            for t in confirm_rules]
    i_afford = keys.index(("confirm_affordable",))
    assert i_afford < keys.index(("round",))
    assert i_afford < keys.index(("budget_remaining",))
    # ...and after the semantic exceptions, which outrank any resource fact.
    assert i_afford > keys.index(("correctness_failed",))
    assert i_afford > keys.index(("nan_response",))


def test_step_treats_a_missing_observation_as_not_matching():
    pol = compile_policy(_campaign())
    nxt, _ = step(pol, "screen", {})            # nothing known -> default
    assert nxt == "confirm"


def test_step_supports_comparator_dicts_and_none_never_matches():
    pol = compile_policy(_campaign())
    nxt, _ = step(pol, "confirm", {"correctness_failed": False, "certified": None,
                                   "round": 1, "budget_remaining": 50})
    assert nxt == "report"                       # round >= max_rounds(1)


def test_step_never_interprets_an_operator_check_policy_would_reject():
    """The interpreter's vocabulary is COMPARISON_OPS, not predicates.OPS.

    `predicates.OPS` supplies the comparison callables, but it also carries
    `==` / `!=`, which `check_policy` rejects in a `when` predicate. If
    `step` honoured them, a hand-written policy the checker refuses could
    still drive the epoch — checker and interpreter would disagree on the
    language, and "no free-form expressions" would stop being a property of
    the module and become a property of who happened to call the checker.
    """
    pol = compile_policy(_campaign())
    bad = json.loads(json.dumps(pol))
    bad["transitions"].insert(0, {"from": "screen", "when": {"round": {"==": 1}},
                                  "to": "report", "accounting": "a"})
    assert any("unknown operator" in e for e in check_policy(bad))
    nxt, _ = step(bad, "screen", {"round": 1})
    assert nxt == "confirm"                      # the `==` rule did not fire


def test_every_enumerated_path_terminates_and_exception_is_reachable_everywhere():
    pol = compile_policy(_campaign())
    paths = enumerate_paths(pol)
    assert paths and all(is_terminal(pol, p[-1]) for p in paths)
    spending = {s for s, v in pol["states"].items() if v["spends"]}
    for s in spending:
        assert any(s in p and p[-1] == "exception" for p in paths), s
    assert longest_path(pol) >= 3               # screen, refine, confirm


def test_transitions_log_round_trips_and_current_state_follows_it(tmp_path):
    pol = compile_policy(_campaign())
    assert current_state(pol, tmp_path) == "screen"
    append_transition(tmp_path, {"iteration": 2, "from": "screen", "to": "refine",
                                 "rule": {"to": "refine"}, "observations": {}})
    assert read_transitions(tmp_path)[0]["to"] == "refine"
    assert current_state(pol, tmp_path) == "refine"


def test_observations_from_decision_maps_triggers_to_the_closed_vocabulary():
    from orchestrator.optimize.stage import (
        Stage, StageDecision, Trigger, observations_from_decision,
    )
    from orchestrator.optimize.effects import Fit
    d = StageDecision(next_stage=Stage.REFINE, triggers=(Trigger.LACK_OF_FIT,),
                      surviving=("A", "B"), dropped=("C",), rationale="x")
    obs = observations_from_decision(d, Fit(intercept=0.0, effects=(), n_runs=8), refinable_survivors=1)
    assert obs["lack_of_fit"] is True and obs["all_within_noise"] is False
    assert obs["refinable_survivors"] == 1 and obs["stationary_in_hull"] is None
    assert set(obs) <= OBSERVATION_KEYS
