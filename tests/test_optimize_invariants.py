"""The invariant registry: anti-drift, teeth, and the universally-quantified properties.

Three jobs, in descending order of how much they matter.

1. ANTI-DRIFT. Every ID in ``docs/optimization-invariants.md`` exists in
   ``orchestrator.optimize.invariants.REGISTRY`` and vice versa, and the
   document's generated counts match the registry. This is what keeps the
   inventory ALIVE rather than archaeological: a document alone rots, and an
   inventory that has silently diverged from the code is worse than none,
   because a reader takes it for a description.

2. TEETH. Every checker fails on a constructed violation. A checker that
   cannot fail is prose with parentheses. Where a checker's teeth are
   asserted, the test constructs the violation the historical defect actually
   produced rather than an arbitrary bad value.

3. PROPERTIES. ``hypothesis`` over the naturally universally-quantified ones,
   ``derandomize=True`` so a failure is reproducible from the seed in the
   report, with ``@example`` pinning every historical-defect case as
   always-run.

Behavioral throughout: these assert what the checkers RETURN and what the
artifacts CONTAIN, never which method was called on what.

Cross-reference: `tests/test_optimize_metamorphic.py`,
`test_optimize_state_machine.py`, `test_optimize_boundaries.py` and the other
technique files own the generative STRATEGIES; this file owns the inventory and
its enforcement. Where they overlap they cite invariant IDs rather than
restating the invariant.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from orchestrator.optimize import invariants as inv
from orchestrator.optimize.certificate import RegretBound, terminal_regret_bound
from orchestrator.optimize.design import full_factorial, fractional_factorial
from orchestrator.optimize.effects import Effect, fit_effects
from orchestrator.optimize.harness import synthetic_campaign
from orchestrator.optimize.policy import (
    COMPARISON_OPS, OBSERVATION_KEYS, compile_policy, policy_hash, write_policy,
)
from orchestrator.optimize.synthetic import SURFACES

DOC = Path(__file__).resolve().parents[1] / "docs" / "optimization-invariants.md"

#: The observation keys the document justifies as deliberately non-branching or
#: as magnitudes behind a derived verdict. Passed in rather than hardcoded in
#: the checker, so that adding one is a visible edit to the inventory instead of
#: an invisible edit to a Python literal (see INV-VOC04).
DOCUMENTED_NON_BRANCHING = frozenset({
    "behavioral_violation",         # reporting key, deliberately never branched
    "runs_needed_foldover",         # magnitude behind foldover_affordable
    "runs_needed_confirm",          # magnitude behind confirm_affordable
    "residual_regret", "epsilon",   # reported into report.json
    "model_adequate",               # read by _confirm_rows, not by a `when`
    "all_within_noise", "lack_of_fit",   # reach findings.json / effects.json
    "correctness_failed",           # set explicitly; abort happens upstream
    "certified",                    # reported; Task 9 owns making it True
    "round", "budget_remaining",    # read by guards on some policies only
})


def _campaign(**over):
    return synthetic_campaign(SURFACES["additive"](), **over)


# ══════════════════════════════════════════════════════════════════════════
#  1. ANTI-DRIFT — the test that keeps the inventory alive
# ══════════════════════════════════════════════════════════════════════════

def _documented_ids() -> list[str]:
    """Every invariant ID the document declares in a table row.

    Parses table rows specifically (``| `INV-XXnn` | ...``) rather than every
    mention of an ID, because the document also cites IDs in prose and in the
    behaviors section — a citation is a cross-reference, a table row is a
    declaration, and only the second should have to exist in the registry.
    """
    rows = re.findall(r"^\|\s*`(INV-[A-Z]+\d+)`\s*\|", DOC.read_text(), re.M)
    return rows


def test_document_and_registry_do_not_drift():
    """INV inventory: every documented ID is registered and vice versa.

    THE POINT OF THIS TEST. A document alone rots. The 128 invariant-flavored
    statements this inventory was built from were all true when written and
    several were false by the time a field test found them. The only durable
    defence is a test that fails when the prose and the code disagree, so the
    disagreement is a red build rather than a discovery two weeks later.
    """
    documented = _documented_ids()
    assert documented, f"no invariant table rows parsed out of {DOC}"

    dupes = sorted({i for i in documented if documented.count(i) > 1})
    assert not dupes, (
        f"{DOC.name} declares these IDs in more than one table row: {dupes}. "
        f"An ID must have exactly one declaration or a reader cannot tell which "
        f"row is authoritative."
    )

    doc_set, reg_set = set(documented), set(inv.REGISTRY)
    assert doc_set == reg_set, (
        f"the inventory document and the registry have drifted.\n"
        f"  documented but NOT registered (no checker, no classification, "
        f"invisible to every seam): {sorted(doc_set - reg_set)}\n"
        f"  registered but NOT documented (a reviewer reading the checklist "
        f"would never learn it exists): {sorted(reg_set - doc_set)}"
    )


def test_documented_type_and_level_match_the_registry():
    """A row's own TYPE and LEVEL columns agree with the registry entry.

    Set membership is not enough: an entry can be present in both places while
    the document calls it `artifact`-level and the registry calls it
    `function`-level — and the LEVEL is what tells a reviewer where to look for
    the violation, so a disagreement there is a live defect in the checklist.
    """
    text = DOC.read_text()
    mismatches = []
    for m in re.finditer(
        r"^\|\s*`(INV-[A-Z]+\d+)`\s*\|(.*?)\|\s*(\w+)\s*\|", text, re.M,
    ):
        iid, _statement, level = m.group(1), m.group(2), m.group(3)
        entry = inv.REGISTRY[iid]
        if level != entry.level:
            mismatches.append(f"{iid}: document says level {level!r}, registry says {entry.level!r}")
        prefix = iid[len("INV-"):].rstrip("0123456789")
        if prefix != entry.type:
            mismatches.append(f"{iid}: id prefix {prefix!r} vs registry type {entry.type!r}")
    assert not mismatches, "\n".join(mismatches)


def test_document_counts_match_the_registry():
    """The §9 counts table is generated from the registry, so it must agree.

    A stale count is the cheapest possible drift and the most misleading: a
    reader who trusts "44 always-checked" and finds 50 has no reason to trust
    the rest of the table either.
    """
    text = DOC.read_text()
    m = re.search(r"^\|\s*\*\*Total\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|", text, re.M)
    assert m, "no **Total** row found in the counts table"
    assert int(m.group(1)) == len(inv.REGISTRY), (
        f"counts table says {m.group(1)} invariants, registry has "
        f"{len(inv.REGISTRY)}. Regenerate §9 from the registry."
    )
    for cls in (inv.ALWAYS, inv.TEST, inv.AUDIT, inv.PARANOID):
        n = len(inv.by_enforcement(cls))
        assert f"`{cls}`" in text or n == 0, f"enforcement class {cls} is not described in the document"


def test_every_registry_entry_is_classified_and_traced():
    """Each entry names its evidence, and each unchecked one says why.

    An invariant with no evidence is a plausible-sounding assertion, which is
    exactly what this inventory was built to avoid. An unchecked invariant with
    no note is indistinguishable from one somebody forgot to finish.
    """
    problems = []
    for i in inv.REGISTRY.values():
        if not i.evidence.strip():
            problems.append(f"{i.id} cites no evidence (file, docstring, or spec section)")
        if not i.statement.strip():
            problems.append(f"{i.id} has an empty statement")
        if i.checker is None and not i.note.strip():
            problems.append(
                f"{i.id} has no checker and no note saying why it resists one",
            )
        if i.open_violation and not i.violated_by.strip():
            problems.append(
                f"{i.id} is flagged as an open violation but names no evidence for it",
            )
    assert not problems, "\n".join(problems)


def test_open_violations_are_disclosed_in_the_document():
    """Every open violation is visible in the checklist, not only in the code.

    A disclosed violation is more useful than a hidden one. If the registry knows
    the code breaks an invariant, a reviewer reading the document must learn it
    there — otherwise the document advertises a guarantee the code does not
    deliver, which is worse than saying nothing.
    """
    text = DOC.read_text()
    for i in inv.open_violations():
        # The row must be marked, and the ID must appear in prose explaining it.
        row = re.search(rf"^\|\s*`{re.escape(i.id)}`\s*\|.*$", text, re.M)
        assert row, f"{i.id} has no table row"
        assert "**yes**" in row.group(0) or "VIOLATED" in row.group(0), (
            f"{i.id} is an OPEN VIOLATION in the registry but its document row "
            f"does not flag it:\n  {row.group(0)}"
        )


def test_assert_invariant_rejects_an_unregistered_id():
    """An assertion against an unregistered ID is a typo and must fail loudly."""
    with pytest.raises(KeyError):
        inv.assert_invariant("INV-ST99", {})


# ══════════════════════════════════════════════════════════════════════════
#  2. TEETH — every checker fails on the violation it exists for
# ══════════════════════════════════════════════════════════════════════════

def test_every_checkable_invariant_has_a_teeth_test():
    """Each checker is exercised by at least one test in THIS file.

    Mutation-adjacent rather than mutation itself: it does not prove the checker
    is correct, it proves no checker was added without a test that drives it.
    The set below is maintained by hand deliberately — the failure mode it guards
    is "a checker landed with no test", and deriving the set automatically from
    what the tests happen to call would make it vacuous.
    """
    exercised = {
        "check_policy_structure", "check_comparison_ops_subset",
        "check_observation_keys_consumed", "check_vocabulary_produced_equals_consumed",
        "check_schema_declares_written_fields", "check_held_out_split",
        "check_failure_kind_agrees_with_status", "check_report_bounds_separate",
        "check_exception_removes_only_model_rung", "check_bound_unknown_is_not_zero",
        "check_alias_sign_preserved", "check_behavioral_not_folded_into_correctness",
        "check_declared_relation_absent_is_failure", "check_fit_has_no_nan",
        "check_one_coefficient_per_alias_class", "check_bound_nonnegative",
        "check_exclusions_recorded", "check_exclusions_independent_of_levels",
        "check_preregistration_precedes_measurement", "check_provenance_pair",
        "check_policy_provenance", "check_transitions_epoch_scoped",
        "check_audit_trail_records_spending", "check_duration_reserved_zero",
        "check_no_model_call_reachable_from_epoch", "check_compile_policy_is_pure",
    }
    registered = {i.checker.__name__ for i in inv.checkable()}
    assert registered <= exercised, (
        f"checker(s) registered with no teeth test in this file: "
        f"{sorted(registered - exercised)}"
    )


# ── structural / vocabulary ───────────────────────────────────────────────

def test_policy_structure_checker_catches_a_missing_default():
    """INV-ST01: teeth. A state with no default transition is a dead end."""
    pol = compile_policy(_campaign())
    assert inv.check_policy_structure(pol) == []
    mutated = dict(pol)
    mutated["transitions"] = [t for t in pol["transitions"] if "default" not in t]
    errs = inv.check_policy_structure(mutated)
    assert any("no default transition" in e for e in errs), errs


def test_policy_structure_checker_catches_an_unknown_observation_key():
    """INV-VOC01: teeth. A key outside the closed vocabulary is a dead branch."""
    pol = compile_policy(_campaign())
    mutated = json.loads(json.dumps(pol))
    for t in mutated["transitions"]:
        if "when" in t:
            t["when"] = {"throughput_looks_nice": True}
            break
    errs = inv.check_policy_structure(mutated)
    assert any("unknown observation key" in e for e in errs), errs


def test_policy_structure_checker_catches_an_uninterpretable_operator():
    """INV-VOC02: teeth. `==` is deliberately NOT in COMPARISON_OPS.

    `predicates.OPS` carries it for manipulation checks; the compiled policy's
    grammar is narrower on purpose, and `check_policy` must refuse what `step`
    cannot drive.
    """
    pol = compile_policy(_campaign())
    mutated = json.loads(json.dumps(pol))
    for t in mutated["transitions"]:
        if "when" in t:
            t["when"] = {"round": {"==": 3}}
            break
    errs = inv.check_policy_structure(mutated)
    assert any("unknown operator" in e for e in errs), errs
    assert "==" not in COMPARISON_OPS


def test_policy_structure_checker_catches_an_unaccounted_branch():
    """INV-SEM05: teeth. An adaptive branch with no accounting rule does not ship."""
    pol = compile_policy(_campaign())
    mutated = json.loads(json.dumps(pol))
    for t in mutated["transitions"]:
        if "when" in t:
            t.pop("accounting", None)
            break
    errs = inv.check_policy_structure(mutated)
    assert any("accounting" in e for e in errs), errs


def test_comparison_ops_are_a_subset_of_the_predicate_callables():
    """INV-VOC03: the shipped invariant holds, and the checker has teeth."""
    assert inv.check_comparison_ops_subset() == []
    # Teeth: an op with no callable behind it must be reported.
    import orchestrator.optimize.policy as P
    original = P.COMPARISON_OPS
    try:
        P.COMPARISON_OPS = frozenset(original | {"~="})
        errs = inv.check_comparison_ops_subset()
        assert any("~=" in e for e in errs), errs
    finally:
        P.COMPARISON_OPS = original


def test_observation_keys_have_no_dead_vocabulary():
    """INV-VOC04: every key branches, or is a documented exemption.

    `runs_needed_confirm` was dead vocabulary for six tasks: its producing
    comment claimed a compiled guard that did not exist. The exemption set lives
    in the test, so adding one is a visible edit.
    """
    pol = compile_policy(_campaign())
    assert inv.check_observation_keys_consumed(
        pol, documented_non_branching=DOCUMENTED_NON_BRANCHING,
    ) == []
    # Teeth: with no exemptions at all, the non-branching keys must be reported.
    errs = inv.check_observation_keys_consumed(pol, documented_non_branching=())
    assert any("behavioral_violation" in e for e in errs), errs


def test_behavioral_violation_is_never_branched_on():
    """INV-VOC07: it is a REPORTING key, and adding a guard reverses a decision.

    `stage.decide_after_screen` states the intent in its own words: "Behavioral
    violations are reported but never block advancement: a monotonicity break is
    a discovery, not a reason to stop."
    """
    assert "behavioral_violation" in OBSERVATION_KEYS
    for name in ("additive", "bowl", "sla", "interaction_only"):
        pol = compile_policy(synthetic_campaign(SURFACES[name]()))
        for t in pol["transitions"]:
            assert "behavioral_violation" not in (t.get("when") or {}), (
                f"a `when` clause on {name} reads behavioral_violation; that "
                f"reverses a design decision rather than completing it"
            )


def test_vocabulary_drift_checker_catches_the_n_excluded_defect_class():
    """INV-VOC08: teeth, against the exact shape of the real regression.

    The producer emitted "ok"/"infeasible"/"unmeasured"; the consumer compared
    against the retired "excluded". `n_excluded` silently became 0, nothing
    withheld certification, and the sla surface certified an answer 6.12% off
    the true constrained optimum.
    """
    produced = {"ok", "infeasible", "unmeasured"}

    # The defect: a consumer comparing against a literal no producer can emit.
    errs = inv.check_vocabulary_produced_equals_consumed(
        name="finalist status", produced=produced, consumed={"ok", "excluded"},
    )
    assert any("'excluded'" in e and "can never fire" in e for e in errs), errs

    # The other direction: a produced value no consumer handles.
    errs = inv.check_vocabulary_produced_equals_consumed(
        name="finalist status", produced=produced, consumed={"ok", "infeasible"},
    )
    assert any("'unmeasured'" in e and "unhandled" in e for e in errs), errs

    # The fix: `!= "ok"` consumes every non-ok value.
    assert inv.check_vocabulary_produced_equals_consumed(
        name="finalist status", produced=produced, consumed=produced,
    ) == []


def test_report_basis_vocabulary_matches_its_schema_enum():
    """INV-VOC08 applied to `recommendation.basis`, which HAS a schema enum.

    The enum is a second declaration the producer can be validated against,
    which is what makes this vocabulary less exposed than the finalist statuses
    were — and is an argument for giving the others one.
    """
    schema_path = (
        Path(__file__).resolve().parents[1] / "orchestrator" / "schemas" / "report.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    enum = set(
        schema["properties"]["recommendation"]["properties"]["basis"]["enum"]
    )
    assert inv.check_vocabulary_produced_equals_consumed(
        name="recommendation.basis", produced=enum, consumed=set(inv._BASES),
    ) == []


def test_failure_kinds_match_the_runs_row_schema_enum():
    """INV-VOC05: the closed Python set and the schema enum are the same set."""
    from orchestrator.optimize.runner import FAILURE_KINDS

    schema_path = (
        Path(__file__).resolve().parents[1] / "orchestrator" / "schemas" / "runs_row.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    enum = set(schema["properties"]["failure_kind"]["enum"]) - {""}
    assert inv.check_vocabulary_produced_equals_consumed(
        name="failure_kind", produced=set(FAILURE_KINDS), consumed=enum,
    ) == []


def test_schema_declares_every_field_the_producer_writes():
    """INV-ST10: teeth, against the real runs_row defect shape.

    `runs_row.schema.json` was `additionalProperties: false` while `_run_row`
    always wrote `held_out`/`manipulation`/`invariants`, so EVERY real row on
    disk was schema-invalid — and the existing test passed the whole time
    because it validated dicts it had built itself.
    """
    schema = {
        "properties": {"row_index": {}, "status": {}},
        "required": ["row_index", "status"],
        "additionalProperties": False,
    }
    real_row = {"row_index": 0, "status": "complete", "held_out": {},
                "manipulation": [], "invariants": []}
    errs = inv.check_schema_declares_written_fields(schema, real_row, where="runs.jsonl")
    assert {"held_out", "manipulation", "invariants"} <= {
        e.split("field ")[1].split("'")[1] for e in errs
    }, errs
    # And a required field the producer omits is the other direction.
    errs = inv.check_schema_declares_written_fields(schema, {"row_index": 0})
    assert any("'status'" in e and "required" in e for e in errs), errs
    # Clean case.
    assert inv.check_schema_declares_written_fields(
        schema, {"row_index": 0, "status": "complete"},
    ) == []


def test_held_out_split_is_structural():
    """INV-ST07: teeth. A leak makes `response` no longer fitting-safe."""
    assert inv.check_held_out_split({"tput": 1.0}, {"val_acc": 0.9}) == []
    errs = inv.check_held_out_split({"tput": 1.0, "val_acc": 0.9}, {"val_acc": 0.9})
    assert any("val_acc" in e for e in errs), errs


@pytest.mark.parametrize(
    "status,kind,should_fail",
    [
        ("complete", "", False),
        ("complete", "timeout", True),        # a clean row must not name a cause
        ("failed", "timeout", False),
        ("failed", "", True),                 # a failure with no closed label
        ("failed", "went_wrong_somehow", True),   # outside FAILURE_KINDS
        ("infeasible", "constraint_violated", False),
    ],
)
def test_failure_kind_agrees_with_status(status, kind, should_fail):
    """INV-ST08 / INV-VOC05/06: teeth across the taxonomy's boundary cases."""
    errs = inv.check_failure_kind_agrees_with_status(status, kind)
    assert bool(errs) is should_fail, (status, kind, errs)


# ── semantic / accounting ─────────────────────────────────────────────────

def _report(**over):
    base = {
        "recommendation": {"levels": {"A": 1}, "basis": "model"},
        "residual_regret_model": 0.1,
        "residual_regret_terminal": None,
        "delta_screen": 0.05,
        "delta_terminal": 0.05,
    }
    base.update(over)
    return base


def test_the_two_bounds_are_never_collapsed():
    """INV-SEM01/03: teeth. A merged field advertises the wrong guarantee.

    `Pr(wrong global decision) <= delta_s + delta_t` is only meaningful while
    the two numbers stay apart: one merged "regret" number would advertise the
    assumption-light guarantee while delivering the model-dependent one.
    """
    assert inv.check_report_bounds_separate(_report()) == []

    collapsed = _report()
    del collapsed["residual_regret_terminal"]
    collapsed["residual_regret"] = 0.1
    errs = inv.check_report_bounds_separate(collapsed)
    assert any("collapsed" in e for e in errs), errs
    assert any("residual_regret_terminal" in e and "missing" in e for e in errs), errs


def test_a_null_bound_is_reported_and_is_not_a_zero():
    """INV-SEM02: `None` for residual_regret_terminal is legitimate, not missing.

    A null bound means "the variance was not estimable". The invariant is that
    the FIELD is present; its value being null is the honest answer.
    """
    assert inv.check_report_bounds_separate(
        _report(residual_regret_terminal=None, residual_regret_model=None),
    ) == []


def test_report_always_names_a_basis_from_the_closed_ladder():
    """INV-ST09: teeth. The report must ALWAYS act, on a named rung."""
    errs = inv.check_report_bounds_separate(
        _report(recommendation={"levels": {}, "basis": "looked_good"}),
    )
    assert any("basis" in e and "six declared values" in e for e in errs), errs


def test_semantic_exception_removes_only_the_model_rung():
    """INV-SEM04: teeth, both directions.

    The fitted surface is what the exception impeached, so `model` is
    unavailable — but rungs 1/2 are measurements of a shortlist against itself
    and are NOT suppressed, and the report still names an action.
    """
    errs = inv.check_exception_removes_only_model_rung(
        _report(epoch_ended="screen: {\"nan_response\": true}"),
    )
    assert any("epoch_ended" in e and "model" in e for e in errs), errs

    # Terminal rungs survive an exception: not a violation.
    for basis in ("certified", "terminal_best", "measured", "baseline", "none"):
        r = _report(epoch_ended="screen: ...",
                    recommendation={"levels": {}, "basis": basis})
        assert inv.check_exception_removes_only_model_rung(r) == [], basis

    # And a report with no basis at all fails: the ladder must always act.
    errs = inv.check_exception_removes_only_model_rung({"recommendation": {}})
    assert any("ALWAYS act" in e for e in errs), errs


def test_alias_sign_is_load_bearing():
    """INV-SEM08: teeth. A sign outside {+1, -1} is not a column relationship.

    Re-labelling `AB`'s estimate as `C` while keeping the sign claims `C` pushes
    the response DOWN when it pushes it up.
    """
    good = Effect(label="AB", terms=("A", "B"), estimate=-2.0,
                  aliased_with=((("C",), -1.0),))
    assert inv.check_alias_sign_preserved(good) == []
    bad = Effect(label="AB", terms=("A", "B"), estimate=-2.0,
                 aliased_with=((("C",), 0.5),))
    errs = inv.check_alias_sign_preserved(bad)
    assert any("load-bearing" in e for e in errs), errs


def _verdict(rid, kind, passed, native_test="t::x"):
    from orchestrator.optimize.relations import RelationVerdict

    return RelationVerdict(relation_id=rid, factor_id="A", kind=kind,
                           native_test=native_test, passed=passed, detail="")


def test_off_vocabulary_relation_kind_is_reported():
    """INV-SEM09: teeth, and it names the real gap.

    `classify_failures` puts a `kind="perf"` verdict in NEITHER bucket, so the
    failure would vanish. Unreachable through the real path -- `factors`
    validation rejects any kind but correctness/behavioral at parse time -- but
    `classify_failures` is public, so the property is a claim about its CALLER's
    validation, which the checker states as a dependency rather than assuming.
    """
    assert inv.check_behavioral_not_folded_into_correctness(
        [_verdict("R1", "correctness", True), _verdict("R2", "behavioral", False)],
    ) == []
    errs = inv.check_behavioral_not_folded_into_correctness(
        [_verdict("R3", "perf", False)],
    )
    assert any("NEITHER bucket" in e for e in errs), errs


def test_classify_failures_really_drops_an_off_vocabulary_kind():
    """INV-SEM09: the gap is in the CODE, not only in a hypothetical.

    Asserts the current behaviour so the dependency claim is grounded: a
    `kind="perf"` failure lands in neither returned bucket and would vanish.
    """
    from orchestrator.optimize.relations import classify_failures

    corr, beh = classify_failures([_verdict("R3", "perf", False)])
    assert corr == [] and beh == [], (
        "if this fails, classify_failures now handles off-vocabulary kinds "
        "itself and INV-SEM09's note should be updated"
    )


def test_declared_but_unexecuted_relation_may_not_look_satisfied():
    """INV-SEM10: teeth against the load-bearing case.

    A relation whose `native_test` identifier does not appear in the results at
    all must be `passed=False`: a typo'd identifier must not silently disable a
    correctness gate, since if nothing ever ran it the mechanism was never
    verified.
    """
    from orchestrator.optimize.factors import parse_factors

    factors = parse_factors([{
        "id": "A", "type": "numeric", "levels": [1, 4], "apply": "--a={level}",
        "manipulation": {"observable": "cfg.a", "op": "==", "value": "{level}"},
        "relations": [{"id": "R1", "kind": "correctness",
                       "native_test": "tests/test_a.py::test_a",
                       "statement": "a holds"}],
    }])

    # Executed and passing: clean.
    assert inv.check_declared_relation_absent_is_failure(
        factors, {"tests/test_a.py::test_a": True},
    ) == []
    # Executed and failing: a real failure, not this invariant's concern.
    assert inv.check_declared_relation_absent_is_failure(
        factors, {"tests/test_a.py::test_a": False},
    ) == []
    # NEVER RUN (a typo'd identifier): reconcile must record passed=False, and
    # it does -- so the checker confirms the shipped behaviour rather than
    # flagging it.
    assert inv.check_declared_relation_absent_is_failure(factors, {}) == []

    from orchestrator.optimize.relations import reconcile

    v = reconcile(factors, {"tests/test_a.py::test_TYPO": True})
    assert len(v) == 1 and v[0].passed is False and "not executed" in v[0].detail, v


# ── statistical ───────────────────────────────────────────────────────────

def test_nan_poison_checker_catches_spec_d2():
    """INV-STAT02: teeth against D2's exact verified numbers.

    One NaN row turned `[0.1875, -0.5625, -0.0625, 0.1875]` into
    `[nan, nan, nan, nan]` with nothing raised and nothing logged.
    """
    ids = ["A", "B"]
    design = full_factorial(ids)
    clean = fit_effects(design, [1.0, 2.0, 3.0, 4.0], factor_ids=ids)
    assert inv.check_fit_has_no_nan(clean) == []
    assert [round(e.estimate, 4) for e in clean.effects] == [1.0, 0.5, 0.0]

    # THE MODULE BOUNDARY NOW REFUSES IT. `fit_effects` raises rather than
    # returning an all-NaN Fit, so D2 is closed at the boundary and not only at
    # the `stage_runner` caller. The message names the caller's obligation
    # (decide admissibility, record the exclusions), which is what keeps the
    # division of labour explicit rather than implied.
    with pytest.raises(ValueError, match="are NaN"):
        fit_effects(design, [1.0, float("nan"), 3.0, 4.0], factor_ids=ids)

    # The checker still has teeth against a Fit constructed with a NaN, which is
    # the shape any FUTURE fitting path could still produce.
    from orchestrator.optimize.effects import Fit

    poisoned = Fit(
        intercept=float("nan"),
        effects=(Effect(label="A", terms=("A",), estimate=float("nan")),),
        n_runs=4,
    )
    errs = inv.check_fit_has_no_nan(poisoned)
    assert any("intercept is NaN" in e for e in errs), errs
    assert any("'A'" in e and "NaN" in e for e in errs), errs


@pytest.mark.parametrize("k,resolution", [(5, 4), (6, 4), (7, 4), (8, 4), (5, 5), (7, 3)])
def test_one_coefficient_per_alias_class(k, resolution):
    """INV-STAT01: spec §4 D1's exact reproduction set, now fitting cleanly.

    Every tabulated resolution-IV screen (k=5..8) crashed with "design matrix is
    singular" because one column per two-factor interaction coincides under
    aliasing.
    """
    ids = [chr(65 + i) for i in range(k)]
    design = fractional_factorial(ids, resolution)
    ys = [sum(p.coded) + 0.3 * p.coded[0] * p.coded[1] for p in design.points]
    fit = fit_effects(design, ys, factor_ids=ids)
    assert inv.check_one_coefficient_per_alias_class(fit) == []
    assert inv.check_fit_has_no_nan(fit) == []


def test_alias_class_checker_has_teeth_on_a_duplicate_label():
    """INV-STAT01: teeth. A duplicate label IS the singular-column condition."""
    from orchestrator.optimize.effects import Fit

    dup = Fit(
        intercept=0.0,
        effects=(Effect(label="AB", terms=("A", "B"), estimate=1.0),
                 Effect(label="AB", terms=("C", "D"), estimate=2.0)),
        n_runs=16,
    )
    errs = inv.check_one_coefficient_per_alias_class(dup)
    assert any("ALIAS CLASS" in e for e in errs), errs


def test_bound_nonnegativity_checker():
    """INV-STAT03: teeth. `None` is fine; a negative value is not."""
    assert inv.check_bound_nonnegative(RegretBound(0.0, None, 0.05, "trivial", "")) == []
    assert inv.check_bound_nonnegative(RegretBound(None, None, 0.05, "none", "")) == []
    errs = inv.check_bound_nonnegative(RegretBound(-0.5, None, 0.05, "x", ""))
    assert any("cannot be negative" in e for e in errs), errs


def test_zero_variance_bound_must_not_certify():
    """INV-SEM02 / INV-STAT05: the OPEN violation, asserted as open.

    Spec §3.5, measured on a real campaign: four centre points returned
    bit-identical values, so `pure_error = 0` and every interval came back
    `None`. `terminal_regret_bound` does not do that — on bit-identical
    replicates it returns `value=0.0` with `method="bonferroni_one_sided_t_paired"`,
    a claim of exact ε-optimality from zero information wearing the label of a
    real t-based certificate.

    This test asserts the CURRENT (wrong) behaviour and that the checker catches
    it, so the day `terminal_regret_bound` grows the guard its sibling already
    has, this test fails and points at INV-SEM02's `open_violation` flag.
    """
    deterministic = {"f1": [5.0] * 4, "f2": [5.0] * 4}
    bound = terminal_regret_bound(
        deterministic, "f1", delta=0.05, direction="maximize", paired=True,
    )
    assert bound.value == 0.0 and bound.method == "bonferroni_one_sided_t_paired", (
        "if this fails, terminal_regret_bound has been fixed — clear "
        "INV-SEM02/INV-STAT05's open_violation flag and invert this assertion"
    )
    errs = inv.check_bound_unknown_is_not_zero(bound)
    assert any("unknown is not a zero" in e for e in errs), errs

    # The sibling gets it right, which is what makes the asymmetry a defect
    # rather than a design choice.
    from orchestrator.optimize.certificate import model_regret_bound
    from orchestrator.optimize.effects import Fit

    no_error = Fit(intercept=1.0, effects=(Effect("A", ("A",), 1.0),),
                   n_runs=4, pure_error_df=0)
    mb = model_regret_bound(no_error, [], None, delta=0.05, direction="maximize")
    assert mb.value is None and mb.method == "none"
    assert inv.check_bound_unknown_is_not_zero(mb) == []


def test_exclusions_must_be_recorded():
    """INV-STAT09: teeth. An unrecorded exclusion makes the resolution invisible."""
    assert inv.check_exclusions_recorded(12, 12, None) == []
    errs = inv.check_exclusions_recorded(18, 15, None)
    assert any("no fit_exclusions.json" in e for e in errs), errs
    errs = inv.check_exclusions_recorded(
        18, 15, {"excluded_row_indices": [3], "reason": "x"},
    )
    assert any("names 1 excluded row" in e for e in errs), errs
    assert inv.check_exclusions_recorded(
        18, 15, {"excluded_row_indices": [3, 7, 11], "reason": "not complete"},
    ) == []


def test_level_correlated_exclusions_are_detected():
    """INV-STAT08: historical defect 6, the perfect 2x2 separation.

    Two wall-clock timeouts landed on the SAME corner of the factor space (one
    factor's level) while the other level at that identical corner completed,
    and nothing detected it. Delegates to `orchestrator.optimize.exclusions`.
    """
    # Rows are (levels, excluded, bias_relevant) triples.
    nothing_excluded = [
        ({"A": a, "B": b}, False, False)
        for a in (1, 2) for b in (1, 2) for _ in range(2)
    ]
    assert inv.check_exclusions_independent_of_levels(nothing_excluded, ["A", "B"]) == []

    # Exclusions spread across BOTH levels of A: reduced, not confounded.
    spread = [
        ({"A": 1, "B": 1}, True, True), ({"A": 2, "B": 2}, True, True),
        ({"A": 1, "B": 2}, False, False), ({"A": 2, "B": 1}, False, False),
        ({"A": 1, "B": 1}, False, False), ({"A": 2, "B": 2}, False, False),
        ({"A": 1, "B": 2}, False, False), ({"A": 2, "B": 1}, False, False),
    ]
    assert inv.check_exclusions_independent_of_levels(spread, ["A", "B"]) == []

    # Defect 6's exact shape: every exclusion on ONE level of A, and the lost
    # cell has a completed sibling differing only in A.
    separated = [
        ({"A": 1, "B": 1}, True, True), ({"A": 1, "B": 2}, True, True),
        ({"A": 2, "B": 1}, False, False), ({"A": 2, "B": 2}, False, False),
        ({"A": 2, "B": 1}, False, False), ({"A": 2, "B": 2}, False, False),
    ]
    errs = inv.check_exclusions_independent_of_levels(separated, ["A", "B"])
    assert errs, "a perfect level separation went undetected"
    # BOTH findings are asserted separately, not with an `or`. They are different
    # facts and either one alone would let a mutation that silenced the other
    # survive -- which is exactly what a first version of this test did.
    assert any("correlated with factor 'A'" in e for e in errs), (
        f"the FLAGGED-FACTOR finding is missing: {errs}"
    )
    assert any("2x2 separation" in e for e in errs), (
        f"the CELL-HOLE finding is missing: {errs}"
    )


# ── temporal / provenance ─────────────────────────────────────────────────

def test_preregistration_must_exist_at_the_observation_boundary(tmp_path):
    """INV-TMP01: teeth. A row measured before the policy hash is uncovered."""
    errs = inv.check_preregistration_precedes_measurement(tmp_path)
    assert len(errs) == 2, errs
    pol = compile_policy(_campaign())
    write_policy(tmp_path, pol)
    assert inv.check_preregistration_precedes_measurement(tmp_path) == []


def test_provenance_pair_requires_the_sidecar_not_merely_its_agreement(tmp_path):
    """INV-PROV01: teeth against the verified conditional hole.

    The shipped guard is `if recorded.exists() and ...`, so deleting
    `policy.sha256` disables it. Verified end to end: a tampered policy then ran
    to a `report.json` claiming `basis: model` with terminal discrimination
    silently skipped. A pre-registration whose only proof of integrity can be
    removed by deleting a file is not a pre-registration.
    """
    pol = compile_policy(_campaign())
    write_policy(tmp_path, pol)
    assert inv.check_policy_provenance(tmp_path) == []

    # The hole: sidecar deleted.
    (tmp_path / "policy.sha256").unlink()
    errs = inv.check_policy_provenance(tmp_path)
    assert any("ABSENCE" in e for e in errs), errs

    # And disagreement, the direction the shipped guard does catch.
    (tmp_path / "policy.sha256").write_text("0" * 64 + "\n")
    errs = inv.check_policy_provenance(tmp_path)
    assert any("edited after compilation" in e for e in errs), errs

    # A work-dir with no policy at all is a different state, not a violation.
    for f in ("policy.json", "policy.sha256"):
        (tmp_path / f).unlink(missing_ok=True)
    assert inv.check_policy_provenance(tmp_path) == []


def test_the_shipped_guard_refuses_a_policy_whose_sidecar_was_deleted(tmp_path):
    """INV-PROV01: FIXED, and this asserts the fix BEHAVIOURALLY.

    This test replaces one that grepped `_load_or_compile_policy`'s source for
    the substring `"recorded.exists() and"`. That test was fragile in a way worth
    recording, because it demonstrates the rule: after the guard was fixed, the
    string still appeared -- in the COMMENT explaining what the old guard used to
    do -- so the source test kept passing while asserting nothing. A behavioural
    test cannot be defeated by prose.

    The defect it guards: the check read `if recorded.exists() and <mismatch>`,
    so DELETING `policy.sha256` made the condition False and skipped verification
    entirely, and nothing regenerates the sidecar. Verified end to end at the
    time: with the sidecar removed and `screen`'s default transition rewritten
    from `confirm` to `report`, the epoch ran to completion, skipped terminal
    discrimination, wrote no `confirmation.json`, emitted `report.json` with
    `basis: model`, and recorded the TAMPERED hash in `transitions.jsonl` as
    though it were the registration.

    Both directions are asserted, because the absent sidecar and the disagreeing
    one are the same failure -- this epoch's policy cannot be shown to be the one
    it registered -- and only one of them used to abort.
    """
    from orchestrator.optimize.stage_runner import (
        OptimizationAborted, _load_or_compile_policy,
    )

    campaign = _campaign()
    pol = compile_policy(campaign)
    write_policy(tmp_path, pol)

    # Baseline: an intact pair loads.
    assert _load_or_compile_policy(campaign, tmp_path) is not None

    # (1) sidecar DELETED -- used to skip the check silently.
    (tmp_path / "policy.sha256").unlink()
    with pytest.raises(OptimizationAborted) as exc:
        _load_or_compile_policy(campaign, tmp_path)
    msg = str(exc.value)
    assert "policy.sha256" in msg, msg
    assert "pre-register" in msg or "registered" in msg, msg

    # (2) sidecar DISAGREES -- the direction that always aborted.
    (tmp_path / "policy.sha256").write_text("0" * 64 + "\n")
    with pytest.raises(OptimizationAborted) as exc2:
        _load_or_compile_policy(campaign, tmp_path)
    assert "hash mismatch" in str(exc2.value), str(exc2.value)


def test_transitions_rows_carry_epoch_and_policy_hash():
    """INV-TMP02 / INV-PROV04: teeth.

    Without the per-row `epoch` a recompiled epoch reads its predecessor's rows
    as its own and resumes at the terminal `exception` it was recompiled to
    escape. Without `policy_hash`, "which policy scheduled this design?" stops
    being answerable for any epoch but the current one.
    """
    good = [{"epoch": 1, "policy_hash": "abc", "from": "screen", "to": "confirm"}]
    assert inv.check_transitions_epoch_scoped(good) == []
    errs = inv.check_transitions_epoch_scoped([{"from": "screen", "to": "confirm"}])
    assert any("no policy_hash" in e for e in errs), errs
    assert any("no epoch" in e for e in errs), errs


def test_audit_trail_records_a_spending_epoch(tmp_path):
    """INV-TMP08: teeth against defect 7's reproduced shape.

    Measured: five iterations, 60 benchmark runs spent, `transitions.jsonl`
    never created. The trigger is one failed row of twelve, not the
    `len(keep) < 2` abort.
    """
    # No rows spent: nothing to record, not a violation.
    assert inv.check_audit_trail_records_spending(tmp_path) == []

    iter_dir = tmp_path / "runs" / "iter-2"
    iter_dir.mkdir(parents=True)
    iter_dir.joinpath("runs.jsonl").write_text(
        "\n".join(json.dumps({"row_index": i, "status": "complete"}) for i in range(12)),
    )
    errs = inv.check_audit_trail_records_spending(tmp_path)
    assert any("audit trail records nothing" in e for e in errs), errs
    assert "12 benchmark row(s)" in errs[0], errs

    (tmp_path / "transitions.jsonl").write_text(
        json.dumps({"epoch": 1, "from": "screen", "to": "exception"}) + "\n",
    )
    assert inv.check_audit_trail_records_spending(tmp_path) == []


def test_audit_work_dir_reports_every_failing_audit_invariant(tmp_path):
    """`audit_work_dir` returns all findings, not only the first."""
    iter_dir = tmp_path / "runs" / "iter-2"
    iter_dir.mkdir(parents=True)
    iter_dir.joinpath("runs.jsonl").write_text('{"row_index": 0}\n')
    found = inv.audit_work_dir(tmp_path)
    assert "INV-TMP08" in found, found


# ── resource / economic ───────────────────────────────────────────────────

def test_duration_zero_is_reserved_for_did_not_run():
    """INV-RES06: teeth against defect 3's exact shape.

    `duration_ms` was declared, schema-valid, and structurally ALWAYS 0 — never
    assigned at any of nine construction sites. Now floored at 1ms precisely so
    `0` keeps its meaning.
    """
    class O:
        def __init__(self, d, last=0):
            self.duration_ms, self.last_attempt_ms = d, last

    assert inv.check_duration_reserved_zero(O(1)) == []
    assert inv.check_duration_reserved_zero(O(5000, 5000)) == []
    errs = inv.check_duration_reserved_zero(O(0))
    assert any("RESERVED" in e for e in errs), errs
    errs = inv.check_duration_reserved_zero(O(-3))
    assert any("never be negative" in e for e in errs), errs
    errs = inv.check_duration_reserved_zero(O(100, 500))
    assert any("exceeds duration_ms" in e for e in errs), errs


def test_no_model_dispatcher_is_reachable_from_an_epoch_state():
    """INV-ECO01: CLAUDE.md's "single most important invariant in the kind".

    The static half of the check: the only dispatcher import anywhere in the
    package is function-local inside `build.run_build`, and `build` is not an
    epoch state. A dynamic tripwire over all six epoch states (with a live
    negative control that fires when `build` IS declared) verified the same
    thing independently.
    """
    assert inv.check_no_model_call_reachable_from_epoch() == []


def test_model_call_checker_has_teeth(tmp_path, monkeypatch):
    """INV-ECO01: teeth. A dispatcher import in an epoch module must be reported."""
    pkg = tmp_path / "optimize"
    pkg.mkdir()
    (pkg / "stage_runner.py").write_text(
        "from orchestrator.sdk_dispatch import SDKDispatcher\n",
    )
    monkeypatch.setattr(inv, "__file__", str(pkg / "invariants.py"))
    errs = inv.check_no_model_call_reachable_from_epoch()
    assert any("imports a model dispatcher" in e for e in errs), errs


def test_compile_policy_purity_checker_has_teeth(monkeypatch):
    """INV-ECO02: teeth. An impure compile must be reported.

    The checker compares two hashes, so the mutation that would silence it is
    dropping the comparison. Simulated by making `compile_policy` return
    something different each call, which is precisely the failure mode: a policy
    that is not a pure function of the campaign cannot be a pre-registration,
    because the hash would describe the run rather than the plan.
    """
    import itertools

    import orchestrator.optimize.policy as P

    counter = itertools.count()
    real = P.compile_policy
    monkeypatch.setattr(
        P, "compile_policy",
        lambda camp, **kw: {**real(camp, **kw), "epoch": 1 + next(counter)},
    )
    errs = inv.check_compile_policy_is_pure(_campaign())
    assert any("not a pure function" in e for e in errs), errs


def test_invariant_id_prefix_must_match_its_declared_type():
    """The registry's own guard: the ID prefix IS the classification.

    A reader classifies a violation from the ID alone, so an entry whose prefix
    and `type` disagree would misfile every violation it reports. Also covers the
    malformed-ID case.
    """
    with pytest.raises(ValueError, match="disagrees with type"):
        inv.Invariant("INV-ST42", "s", "SEM", "function", "e", inv.TEST)
    with pytest.raises(ValueError, match="must be INV-"):
        inv.Invariant("ST42", "s", "ST", "function", "e", inv.TEST)
    with pytest.raises(ValueError, match="level"):
        inv.Invariant("INV-ST42", "s", "ST", "galaxy", "e", inv.TEST)
    with pytest.raises(ValueError, match="enforcement"):
        inv.Invariant("INV-ST42", "s", "ST", "function", "e", "sometimes")


def test_assert_invariant_raises_on_a_violation_and_names_the_id():
    """The seam helper must actually raise, and the error must be attributable.

    A violation that surfaced as a bare AssertionError with no ID would send a
    reader back to grepping docstrings, which is the state this whole inventory
    replaces.
    """
    bad_report = {"recommendation": {"levels": {}, "basis": "vibes"}}
    with pytest.raises(inv.InvariantViolation) as exc:
        inv.assert_invariant("INV-ST09", bad_report)
    assert exc.value.invariant_id == "INV-ST09"
    assert "INV-ST09" in str(exc.value)
    assert "docs/optimization-invariants.md" in str(exc.value)
    assert exc.value.violations

    # And it must NOT raise when the invariant holds.
    inv.assert_invariant("INV-ST09", _report())


def test_paranoid_class_checks_are_skipped_unless_enabled(monkeypatch):
    """PARANOID is opt-in: `assert_invariant` returns without running the checker.

    No entry is currently PARANOID-class, so this asserts the MECHANISM against a
    constructed entry rather than a registered one -- the class exists for checks
    that duplicate a guard one layer down, and the gate has to work before one is
    added.
    """
    calls = []

    entry = inv.Invariant(
        "INV-ST42", "constructed", "ST", "function", "test", inv.PARANOID,
        lambda *_a, **_k: (calls.append(1), ["boom"])[1],
    )
    monkeypatch.setitem(inv.REGISTRY, "INV-ST42", entry)

    monkeypatch.delenv(inv.PARANOID_ENV, raising=False)
    inv.assert_invariant("INV-ST42")               # skipped: no raise, no call
    assert calls == []

    monkeypatch.setenv(inv.PARANOID_ENV, "1")
    assert inv.paranoid_enabled()
    with pytest.raises(inv.InvariantViolation):
        inv.assert_invariant("INV-ST42")
    assert calls == [1]


def test_compile_policy_is_a_pure_function_of_the_campaign():
    """INV-ECO02: same input, same hash. `T_compile = 0`."""
    for name in ("additive", "bowl", "sla", "nan_at_corner"):
        camp = synthetic_campaign(SURFACES[name]())
        assert inv.check_compile_policy_is_pure(camp) == [], name


# ══════════════════════════════════════════════════════════════════════════
#  3. PROPERTIES — hypothesis over the universally-quantified invariants
#
#  derandomize=True so a failure is reproducible from the report alone, and
#  @example pins every historical-defect case as always-run rather than
#  hoping the generator finds it.
# ══════════════════════════════════════════════════════════════════════════

def _welch_df_underflows(samples: dict[str, list[float]]) -> bool:
    """Whether `terminal_regret_bound`'s unpaired branch will raise on these samples.

    Used by the properties below to `assume` away the input class that
    `test_welch_df_underflows_on_subnormal_variance` asserts directly. Excluding
    it there and asserting it here keeps the two findings distinct: the
    properties are about the bound's shape, this is about a crash.
    """
    from statistics import variance

    for v in samples.values():
        if len(v) < 2:
            return False
    vs = [variance(v) / len(v) for v in samples.values()]
    if not any(x > 0 for x in vs):
        return False
    return sum(vs) > 0 and any(x ** 2 == 0.0 and x > 0 for x in vs)


def test_welch_df_underflows_on_subnormal_variance():
    """INV-STAT12: the terminal bound must not RAISE on any admissible sample.

    A checker cannot express this one, because the failure is an exception
    rather than a value -- so it is asserted directly, and recorded in the
    registry as an open violation with no checker.

    Found by the hypothesis properties below rather than by construction. The
    Welch degrees-of-freedom denominator is

        (vk**2)/(nk-1) + (vb**2)/(nb-1)

    guarded only by `if (vk + vb) > 0`. For subnormal-magnitude variances that
    guard passes while `vk**2` UNDERFLOWS to exactly 0.0, so the denominator is
    zero and the bound raises `ZeroDivisionError` on the certification path.
    Minimal input: two finalists whose replicates are
    `[-3.117993501313441e-82, 0.0]`, giving `vk == vb == 2.43e-164` and
    `vk**2 == 0.0`.

    A campaign reporting an objective in tiny absolute units (a fraction, a
    normalized rate) can reach this, and the consequence is an unhandled
    exception where the honest answer is a bound of `None` -- the same "not
    estimable" verdict spec 3.5 requires for a variance it cannot obtain. The
    guard should test the DENOMINATOR, not the sum of the variances.
    """
    tiny = -3.117993501313441e-82
    samples = {"f1": [tiny, 0.0], "f2": [tiny, 0.0]}
    assert _welch_df_underflows(samples)
    with pytest.raises(ZeroDivisionError):
        terminal_regret_bound(
            samples, "f1", delta=0.05, direction="maximize", paired=False,
        )
    # The paired branch divides by `n` rather than by a squared variance, so it
    # survives the same input -- which is what localises the defect.
    ok = terminal_regret_bound(
        samples, "f1", delta=0.05, direction="maximize", paired=True,
    )
    assert ok.value is not None


_DETERMINISTIC = settings(
    derandomize=True, max_examples=120, deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_samples = st.lists(
    st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False),
    min_size=2, max_size=8,
)


@_DETERMINISTIC
@given(a=_samples, b=_samples)
@example(a=[5.0, 5.0, 5.0, 5.0], b=[5.0, 5.0, 5.0, 5.0])          # spec 3.5 deterministic target
@example(a=[10.0, 10.2, 9.8, 10.1], b=[10.0, 10.1, 9.9, 10.05])   # near-tied finalists
def test_property_bound_is_never_negative(a, b):
    """INV-STAT03 as a property: `x_hat` is the argmax, so the gap floors at 0."""
    assume(len(a) == len(b))
    samples = {"f1": a, "f2": b}
    assume(not _welch_df_underflows(samples))      # INV-STAT12, asserted separately
    best = max(samples, key=lambda k: sum(samples[k]) / len(samples[k]))
    for paired in (True, False):
        bound = terminal_regret_bound(
            samples, best, delta=0.05, direction="maximize", paired=paired,
        )
        assert inv.check_bound_nonnegative(bound) == []


@_DETERMINISTIC
@given(a=_samples, b=_samples)
@example(a=[10.0, 10.2, 9.8, 10.1], b=[10.0, 10.1, 9.9, 10.05])
def test_property_bound_widens_as_delta_shrinks(a, b):
    """INV-STAT04: a stronger confidence requirement cannot narrow a certificate.

    Verified on the pinned example: delta 0.5 -> 0.001 gives
    [0.0, 0.02928, 0.05742, 0.08798, 0.18137, 0.42362].
    """
    assume(len(a) == len(b))
    samples = {"f1": a, "f2": b}
    best = max(samples, key=lambda k: sum(samples[k]) / len(samples[k]))
    vals = []
    for delta in (0.5, 0.2, 0.1, 0.05, 0.01):
        v = terminal_regret_bound(
            samples, best, delta=delta, direction="maximize", paired=True,
        ).value
        if v is not None:
            vals.append(v)
    assert all(x <= y + 1e-9 for x, y in zip(vals, vals[1:])), vals


@_DETERMINISTIC
@given(a=_samples, b=_samples)
@example(a=[10.0, 10.2, 9.8, 10.1], b=[10.0, 10.1, 9.9, 10.05])
def test_property_sign_symmetry(a, b):
    """INV-STAT11 (metamorphic): negate every response, flip direction, same bound.

    The bound must depend on the geometry of the comparison, not on the sign
    convention a campaign happens to report its objective in.
    """
    assume(len(a) == len(b))
    samples = {"f1": a, "f2": b}
    negated = {k: [-x for x in v] for k, v in samples.items()}
    best = max(samples, key=lambda k: sum(samples[k]) / len(samples[k]))
    up = terminal_regret_bound(samples, best, delta=0.05, direction="maximize", paired=True)
    down = terminal_regret_bound(negated, best, delta=0.05, direction="minimize", paired=True)
    if up.value is None or down.value is None:
        assert up.value is None and down.value is None
    else:
        assert math.isclose(up.value, down.value, rel_tol=1e-9, abs_tol=1e-12)


def test_crn_tightening_is_a_TENDENCY_not_an_invariant():
    """INV-STAT07 was REFUTED and is deliberately NOT in the registry.

    It was stated three ways and hypothesis refuted all three, which is the most
    useful single result of this work:

      1. "a paired (CRN) bound is never wider than the unpaired one" -- refuted
         at n=2 (paired 6.3137 vs unpaired 2.0647);
      2. "...at n >= 4" -- refuted at n=7 (0.4240 vs 0.3601);
      3. "...under an actually shared seed effect" -- refuted at n=4 even with a
         shared component (0.006767 vs 0.001870).

    The mechanism: pairing removes the shared seed effect from the variance (the
    benefit) AND collapses the df from Welch's `~n_k + n_b - 2` to `n - 1` (the
    cost). Which dominates depends on the RATIO of shared to independent
    variance, so no unconditional statement over n or over "shared seeds" is
    true. Measured across regimes, 600 trials each, fraction of cases where the
    paired bound is WIDER:

        shared_sd  noise_sd   n=4      n=8      n=16
              3.0       0.3    2/600    0/600     0/600
              3.0       1.0   19/600    3/600     0/600
              1.0       1.0  179/600   75/600    24/600
              0.3       3.0  360/600  338/600   323/600

    So CRN pays when the shared component DOMINATES the independent noise, and
    is a net loss when it does not -- 60% of the time in the last regime. That is
    a real and useful engineering fact, and it is exactly what spec 3.8's flat
    claim ("an unpaired comparison on a noisy server needs an order of magnitude
    more runs for the same bound") does not say.

    Recorded in docs/optimization-invariants.md 10 as prose that is not an
    invariant, with the table above, rather than as a registry entry a checker
    would have to lie about. This test asserts the REFUTATION so the demotion
    cannot be quietly reverted.
    """
    # Regime where CRN pays: shared effect dominates.
    shared = [0.0, 3.0, -3.0, 1.5, -1.5, 2.0]
    tight = {"f1": [s + 0.05 for s in shared], "f2": [s - 0.05 for s in shared]}
    p = terminal_regret_bound(tight, "f1", delta=0.05, direction="maximize", paired=True)
    u = terminal_regret_bound(tight, "f1", delta=0.05, direction="maximize", paired=False)
    assert p.value is not None and u.value is not None
    assert p.value < u.value, "CRN should pay when the shared component dominates"

    # Regime where it does not: independent samples, any n.
    loose = {"f1": [810.3947659829726, 176.29313368683665],
             "f2": [1.9925981701064827e-53, 531.1923973964424]}
    p2 = terminal_regret_bound(loose, "f1", delta=0.05, direction="maximize", paired=True)
    u2 = terminal_regret_bound(loose, "f1", delta=0.05, direction="maximize", paired=False)
    assert p2.value > u2.value, (
        "the refutation no longer reproduces -- re-derive whether CRN tightening "
        "has become an invariant before promoting it back into the registry"
    )
    assert "INV-STAT07" not in inv.REGISTRY, (
        "INV-STAT07 was refuted as an invariant and demoted to the document's "
        "10 (prose that is not an invariant). Re-adding it needs a checker that "
        "can express the shared-to-independent variance ratio it depends on."
    )


@_DETERMINISTIC
@given(
    obs=st.dictionaries(
        st.sampled_from(sorted(OBSERVATION_KEYS)),
        st.one_of(st.booleans(), st.integers(min_value=-5, max_value=20),
                  st.floats(min_value=0, max_value=10, allow_nan=False), st.none()),
        max_size=8,
    ),
)
@example(obs={})                                        # totality at the empty dict
@example(obs={k: None for k in sorted(OBSERVATION_KEYS)})   # unknown is not a fact
def test_property_step_is_total_and_never_matches_on_unknown(obs):
    """INV-SEM06 + spec §3.2 totality: `step` is defined for EVERY observation.

    Including the empty dict and an all-`None` dict. A `None` observation never
    matches a guard — unknown is not a fact — so an all-`None` observation must
    take the default transition out of every state.
    """
    from orchestrator.optimize.policy import step

    pol = compile_policy(_campaign())
    for state, spec in pol["states"].items():
        if spec.get("terminal"):
            continue
        nxt, rule = step(pol, state, obs)
        assert nxt in pol["states"], (state, obs, nxt)
        if all(v is None for v in obs.values()):
            assert "default" in rule, (
                f"an all-None observation matched conditional rule {rule} out of "
                f"{state!r}; unknown is not a fact"
            )


@_DETERMINISTIC
@given(surface=st.sampled_from(sorted(SURFACES)))
def test_property_every_compiled_policy_is_structurally_valid(surface):
    """INV-ST01..06, INV-VOC01/02, INV-SEM05 over every synthetic surface.

    The nine surfaces are each named for a past real bug, so this is the
    oracle-first discipline applied to the policy's structure rather than to the
    response.
    """
    pol = compile_policy(synthetic_campaign(SURFACES[surface]()))
    assert inv.check_policy_structure(pol) == []
    assert inv.check_compile_policy_is_pure(synthetic_campaign(SURFACES[surface]())) == []


@_DETERMINISTIC
@given(
    produced=st.sets(st.sampled_from(["ok", "infeasible", "unmeasured", "excluded", "pending"]),
                     min_size=1, max_size=5),
    consumed=st.sets(st.sampled_from(["ok", "infeasible", "unmeasured", "excluded", "pending"]),
                     min_size=1, max_size=5),
)
@example(produced={"ok", "infeasible", "unmeasured"}, consumed={"ok", "excluded"})
def test_property_vocabulary_drift_is_symmetric_and_exact(produced, consumed):
    """INV-VOC08: the checker reports exactly the two set differences.

    A checker that over-reports would be ignored; one that under-reports would
    have missed the `n_excluded` defect. The property is that the finding set is
    precisely the symmetric difference.
    """
    errs = inv.check_vocabulary_produced_equals_consumed(
        name="v", produced=produced, consumed=consumed,
    )
    assert len(errs) == len(consumed - produced) + len(produced - consumed)
    assert (not errs) == (produced == consumed)
