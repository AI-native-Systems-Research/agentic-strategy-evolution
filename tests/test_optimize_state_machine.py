"""State-transition invariants for the compiled epoch.

The epoch is an INTERPRETED STATE MACHINE, not Python control flow: spec §3.2
makes ``policy.step(policy, state, observations) -> (next_state, rule)`` the
only thing that decides what happens next inside an epoch, and documents it as
PURE, TOTAL, and DETERMINISTIC. Those three words are testable claims, and this
file tests them as claims rather than sampling a few hand-written examples.

Three layers, weakest to strongest:

  1. structural properties of every compilable policy shape (``check_policy``
     agrees with what ``step`` can actually drive);
  2. ``step``'s own algebra — totality over an arbitrary observation dict,
     determinism, first-match-wins ordering;
  3. a hypothesis ``RuleBasedStateMachine`` that walks real epochs through
     ``step`` and the real ``transitions.jsonl`` writer, asserting the audit
     trail reads back exactly what was written.

Layer 3 exists because of a specific field failure: EVERY iteration of a real
14-hour campaign aborted BEFORE the fit, so no ``step()`` ever ran and
``transitions.jsonl`` was completely EMPTY after 18 valid rows of measurement.
The terminal states were never reached, so no example-based test noticed — the
bug was a PATH through the machine nobody had exercised. A stateful walk
explores paths nobody wrote down, which is the only technique that would have
flagged it.
"""
from __future__ import annotations

import itertools
import json

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine, initialize, invariant, precondition, rule,
)

from orchestrator.optimize import policy as policy_mod
from orchestrator.optimize.policy import (
    COMPARISON_OPS, OBSERVATION_KEYS, append_transition, check_policy,
    compile_policy, current_state, enumerate_paths, epoch_transitions,
    is_terminal, longest_path, policy_hash, read_transitions, step,
)
from orchestrator.optimize.synthetic import _choice, _numeric

pytestmark = pytest.mark.statemachine

DET = settings(derandomize=True, deadline=None, max_examples=100,
               suppress_health_check=[HealthCheck.function_scoped_fixture,
                                      HealthCheck.too_slow])

TERMINALS = ("report", "exception")


# ── campaign shapes: every policy the compiler can emit ────────────────────
#
# The structural claims below must hold for EVERY compilable campaign, not for
# one. `compile_policy` branches on four independent switches (foldover on/off,
# refine present-and-refinable, confirm present, confirm_max_rounds), so the
# shape space is small enough to enumerate exhaustively — which is better than
# sampling it.


def _campaign(*, stages=("verify", "screen", "refine", "confirm"),
              foldover=True, refinable=True, confirm_max_rounds=1,
              shortlist_size=3, replicates=3, **policy_extra) -> dict:
    """A minimal valid `kind: optimization` campaign for policy compilation.

    Only the `optimization` block matters here: `compile_policy` reads nothing
    else, which is itself part of why it can be a pure function.
    """
    factors = [
        _numeric("A", levels=(2, 4, 8, 16) if refinable else (2, 16)),
        _choice("B", levels=("off", "on")),
    ]
    pol = {"foldover": foldover, "confirm_max_rounds": confirm_max_rounds}
    pol.update(policy_extra)
    return {
        "kind": "optimization",
        "run_id": "sm",
        "research_question": "q",
        "target_system": {"name": "t", "description": "d"},
        "optimization": {
            "stages": list(stages),
            "response": {"primary": {"metric": "m", "direction": "maximize"}},
            "factors": factors,
            "design": {
                "screen": {"resolution": 5, "center_points": 4},
                "refine": {"kind": "central_composite", "center_points": 4},
                "confirm": {"shortlist_size": shortlist_size,
                            "replicates": replicates},
            },
            "policy": pol,
        },
    }


_SHAPES: dict[str, dict] = {}
for _fold, _refine, _confirm, _rounds in itertools.product(
        (True, False), (True, False), (True, False), (1, 3)):
    _stages = ["verify", "screen"]
    if _refine:
        _stages.append("refine")
    if _confirm:
        _stages.append("confirm")
    _SHAPES[f"fold={_fold},refine={_refine},confirm={_confirm},rounds={_rounds}"] = (
        _campaign(stages=tuple(_stages), foldover=_fold, refinable=_refine,
                  confirm_max_rounds=_rounds)
    )
# A campaign whose `refine` stage is declared but whose factors are all
# two-level: `compile_policy` drops the state (nothing is refinable), which is a
# distinct shape from omitting the stage.
_SHAPES["refine-declared-but-nothing-refinable"] = _campaign(refinable=False)

SHAPE_IDS = sorted(_SHAPES)


@pytest.fixture(params=SHAPE_IDS)
def shape(request):
    return compile_policy(_SHAPES[request.param])


# ── Layer 1: structural properties of every compilable policy ──────────────


def test_every_compilable_shape_passes_its_own_structural_check(shape):
    """`check_policy` must accept everything `compile_policy` emits.

    A compiler that can emit a document its own checker rejects would make the
    checker unrunnable in production — the abort would fire on a legitimate
    campaign — so the two have to agree across the whole shape space.
    """
    assert check_policy(shape) == []


@pytest.mark.mutation_sentinel
def test_no_non_terminal_state_lacks_a_default_transition(shape):
    """TOTALITY, structurally: `step` falls back to the default, so a state
    without one raises instead of transitioning.

    `check_policy` claims to enforce this. Verified here INDEPENDENTLY of
    `check_policy` — asserting it by calling the checker would only prove the
    checker agrees with itself.

    Cross-reference: `docs/optimization-invariants.md` INV-ST01 — the statement of
    record lives there; this test is the executable check.
    """
    states = shape["states"]
    have_default = {t["from"] for t in shape["transitions"] if "default" in t}
    for name, st_ in states.items():
        if st_.get("terminal"):
            continue
        assert name in have_default, (
            f"non-terminal state {name!r} has no default transition, so "
            f"step() raises for any observation that matches no guard"
        )


@pytest.mark.mutation_sentinel
def test_every_when_clause_speaks_only_the_closed_vocabularies(shape):
    """Closed observation keys and closed comparison operators (spec §3.2).

    `==` / `!=` are deliberately ABSENT from `COMPARISON_OPS` even though
    `predicates.OPS` carries them: an equality test on a float measurement is
    not a decision rule anyone can defend, and the compiled policy's grammar
    must stay narrower than the general-purpose one.

    Cross-reference: `docs/optimization-invariants.md` INV-ST06 — the statement of
    record lives there; this test is the executable check.
    """
    assert COMPARISON_OPS == frozenset({">", ">=", "<", "<="})
    assert "==" not in COMPARISON_OPS and "!=" not in COMPARISON_OPS
    for t in shape["transitions"]:
        if "when" not in t:
            continue
        for key, spec in t["when"].items():
            assert key in OBSERVATION_KEYS, (
                f"transition {t['from']}->{t.get('to')} reads {key!r}, which is "
                f"outside the closed observation vocabulary"
            )
            if isinstance(spec, dict):
                assert set(spec) <= COMPARISON_OPS, (
                    f"{t['from']}->{t.get('to')} uses operator(s) "
                    f"{sorted(set(spec) - COMPARISON_OPS)} on {key!r}"
                )
                assert len(spec) == 1, "a predicate takes exactly one operator"


def test_every_conditional_transition_names_an_inferential_accounting_rule(shape):
    """Spec §3.2: an adaptive branch with no named accounting rule does not ship.

    The `accounting` string is the whole reason a registered branch is legitimate
    rather than p-hacking — it says under which inferential rule the branch's
    extra look at the data is paid for.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM05 — the statement of
    record lives there; this test is the executable check.
    """
    for t in shape["transitions"]:
        if "when" in t:
            assert t.get("accounting"), (
                f"conditional transition {t['from']}->{t.get('to')} names no "
                f"accounting rule"
            )


def test_every_spending_state_can_reach_the_semantic_exception(shape):
    """A state that takes measurements must be able to end the epoch.

    A spending state with no route to `exception` would have to interpret an
    uninterpretable measurement — which is the one thing spec §3.2 forbids,
    since interpreting it is what would require a model call inside the epoch.

    Cross-reference: `docs/optimization-invariants.md` INV-ST04 — the statement of
    record lives there; this test is the executable check.
    """
    for name, st_ in shape["states"].items():
        if not st_.get("spends"):
            continue
        assert any(t.get("from") == name and t.get("to") == "exception"
                   for t in shape["transitions"]), (
            f"spending state {name!r} cannot reach exception"
        )


@pytest.mark.mutation_sentinel
def test_every_state_reaches_a_terminal_and_no_path_runs_forever(shape):
    """TERMINALITY: from the initial state, every enumerated path ends terminal.

    `enumerate_paths` walks SIMPLE paths (each transition used at most once), so
    finiteness is structural. The `confirm` self-loop is the one cycle in the
    machine and it is bounded by the registered `max_rounds` cap, which
    `longest_path` accounts for — so an epoch's iteration count has a
    compile-time upper bound, which is what makes budget exhaustion a decision
    rather than an accident.
    """
    paths = enumerate_paths(shape)
    assert paths, "no path from the initial state at all"
    for p in paths:
        assert p[0] == shape["initial"]
        assert is_terminal(shape, p[-1]), f"path {p} does not end in a terminal state"
    assert longest_path(shape) >= max(len(p) for p in paths)
    rounds = max((int((v.get("design") or {}).get("max_rounds", 1))
                  for v in shape["states"].values() if v.get("spends")), default=1)
    if rounds > 1:
        assert longest_path(shape) > max(len(p) for p in paths), (
            "a registered self-loop round is not counted in the epoch's bound"
        )


def test_both_terminals_are_reachable_from_the_initial_state(shape):
    """`report` and `exception` are both live in every shape.

    A machine that could not reach `exception` would have nowhere to put a
    semantic exception; one that could not reach `report` could never name an
    action, and the report ALWAYS names an action (spec §3.6).
    """
    reached = {s for p in enumerate_paths(shape) for s in p}
    assert "report" in reached
    assert "exception" in reached


# ── Layer 1b: the checker actually refuses what it claims to refuse ────────


def _mutate(policy: dict) -> dict:
    return json.loads(json.dumps(policy))


def test_check_policy_rejects_an_observation_key_outside_the_vocabulary():
    pol = _mutate(compile_policy(_campaign()))
    pol["transitions"].insert(0, {"from": "screen", "when": {"vibes_good": True},
                                  "to": "report", "accounting": "hunch"})
    errs = check_policy(pol)
    assert any("unknown observation key" in e for e in errs), errs


@pytest.mark.mutation_sentinel
def test_check_policy_rejects_equality_as_a_comparison_operator():
    """`==` must not be interpretable, even though `predicates.OPS` has it.

    If `==` were admitted, `step` would happily drive a rule comparing a float
    measurement for exact equality — a branch that fires essentially never, i.e.
    a registered branch that is dead. `check_policy` is what keeps the
    interpreter's language and the checker's language identical.
    """
    for bad_op in ("==", "!="):
        pol = _mutate(compile_policy(_campaign()))
        pol["transitions"].insert(0, {"from": "screen",
                                      "when": {"round": {bad_op: 1}},
                                      "to": "report", "accounting": "x"})
        errs = check_policy(pol)
        assert any("unknown operator" in e for e in errs), (bad_op, errs)


def test_check_policy_rejects_a_conditional_transition_with_no_accounting_rule():
    pol = _mutate(compile_policy(_campaign()))
    pol["transitions"].insert(0, {"from": "screen", "when": {"certified": True},
                                  "to": "report"})
    assert any("accounting" in e for e in check_policy(pol))


@pytest.mark.mutation_sentinel
def test_check_policy_rejects_a_non_terminal_state_with_no_default():
    """The totality guard, from the checker's side."""
    pol = _mutate(compile_policy(_campaign()))
    pol["transitions"] = [t for t in pol["transitions"]
                          if not (t.get("from") == "screen" and "default" in t)]
    errs = check_policy(pol)
    assert any("no default transition" in e for e in errs), errs


def test_check_policy_rejects_an_empty_when_clause_that_would_shadow_every_rule():
    pol = _mutate(compile_policy(_campaign()))
    pol["transitions"].insert(0, {"from": "screen", "when": {}, "to": "report",
                                  "accounting": "x"})
    assert any("empty `when`" in e for e in check_policy(pol))


# ── Layer 2: step()'s algebra ──────────────────────────────────────────────


_OBS_VALUES = st.one_of(
    st.booleans(),
    st.integers(min_value=-5, max_value=50),
    st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    st.none(),
)


@pytest.mark.mutation_sentinel
@given(obs=st.dictionaries(st.sampled_from(sorted(OBSERVATION_KEYS)), _OBS_VALUES,
                           max_size=6))
@DET
def test_step_is_total_over_the_whole_observation_vocabulary(obs):
    """TOTALITY: `step` returns for EVERY state and EVERY observation dict.

    Including the empty dict, and including observations whose values are `None`
    (a measurement that could not be computed). "Total" is what makes the
    interpreter safe to run inside a stage: a `step` that could raise would turn
    an unusual-but-valid measurement into a crash mid-epoch, after the runs were
    already paid for.

    Cross-reference: `docs/optimization-invariants.md` INV-ST05 — the statement of
    record lives there; this test is the executable check.
    """
    for shape_id in SHAPE_IDS:
        pol = compile_policy(_SHAPES[shape_id])
        for state, st_ in pol["states"].items():
            if st_.get("terminal"):
                continue
            nxt, rule = step(pol, state, obs)
            assert nxt in pol["states"], (shape_id, state, obs, nxt)
            assert isinstance(rule, dict)


@pytest.mark.mutation_sentinel
def test_step_is_total_for_the_empty_observation_dict_specifically():
    """The empty dict is the case the field failure would have produced.

    An iteration that aborts before the fit computes NO observations. Whatever
    the runtime then does, `step({}, ...)` must be defined — it is the default
    transition, by construction.
    """
    for shape_id in SHAPE_IDS:
        pol = compile_policy(_SHAPES[shape_id])
        for state, st_ in pol["states"].items():
            if st_.get("terminal"):
                continue
            nxt, rule = step(pol, state, {})
            assert "default" in rule, (
                f"{shape_id}: an empty observation matched a CONDITIONAL rule "
                f"({rule}) — a guard fired on no evidence at all"
            )
            assert nxt in pol["states"]


@given(obs=st.dictionaries(st.sampled_from(sorted(OBSERVATION_KEYS)), _OBS_VALUES,
                           max_size=6))
@DET
def test_step_is_deterministic(obs):
    """Same (policy, state, observations) -> same (next_state, rule), always."""
    pol = compile_policy(_campaign())
    for state in ("screen", "foldover", "refine", "confirm"):
        if state not in pol["states"]:
            continue
        first = step(pol, state, dict(obs))
        for _ in range(3):
            assert step(pol, state, dict(obs)) == first


@pytest.mark.mutation_sentinel
def test_a_missing_or_none_observation_never_satisfies_a_guard():
    """"Unknown is not a fact" (spec §3.2), stated as a property.

    A `None` residual regret means the variance was not estimable. If `None`
    could match `certified: True` the epoch would certify a recommendation whose
    bound it failed to compute — the single most dangerous confusion in the kind.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM06 — the statement of
    record lives there; this test is the executable check.
    """
    pol = compile_policy(_campaign())
    baseline, rule = step(pol, "confirm", {})
    assert "default" in rule

    for key in ("certified", "correctness_failed", "nan_response"):
        nxt, r = step(pol, "confirm", {key: None})
        assert nxt == baseline and "default" in r, (
            f"a None {key!r} matched a guard: {r}"
        )
    # Absent behaves like None.
    assert step(pol, "confirm", {"round": None})[0] == baseline


@pytest.mark.mutation_sentinel
def test_a_measurement_outside_the_vocabulary_cannot_invent_a_branch():
    """An unknown observation key is INERT, and the epoch ends by the declared
    semantic exception rather than by a branch improvised for it.

    This is spec §3.2's core promise: no state of the machine responds to a
    measurement the policy did not register, so there is never a reason to ask a
    model what an unfamiliar number means.
    """
    pol = compile_policy(_campaign())
    default_next, default_rule = step(pol, "screen", {})

    junk = {"gpu_temperature_c": 91.0, "operator_hunch": "looks off",
            "vibes_good": True}
    assert not (set(junk) & OBSERVATION_KEYS)
    nxt, rule = step(pol, "screen", junk)
    assert (nxt, rule) == (default_next, default_rule), (
        "an out-of-vocabulary measurement changed the transition"
    )

    # The declared way to end the epoch on an uninterpretable measurement is the
    # registered semantic-exception guard, whose accounting rule says exactly
    # that no inference is drawn.
    exc_next, exc_rule = step(pol, "screen", {"nan_response": True})
    assert exc_next == "exception"
    assert "no inference is drawn" in exc_rule["accounting"]


@pytest.mark.mutation_sentinel
def test_first_matching_rule_wins_and_the_registered_order_is_load_bearing():
    """`step` takes the FIRST matching rule in registration order.

    Two orderings are asserted because `compile_policy`'s comments call both
    load-bearing:
      * foldover BEFORE refine — a screen with both a consequential alias and
        refinable survivors resolves the alias first, rather than fitting
        curvature on still-confounded linear terms;
      * `confirm_affordable: False` BEFORE the `budget_remaining < 1` guard — a
        budget with two runs left and nine needed is "affordable" to the coarse
        guard and unaffordable in fact.
    """
    pol = compile_policy(_campaign())
    both = {"alias_consequential": True, "foldover_affordable": True,
            "refinable_survivors": 2}
    assert step(pol, "screen", both)[0] == "foldover"

    order = [i for i, t in enumerate(pol["transitions"])
             if t.get("from") == "confirm" and "when" in t]
    keys = [tuple(pol["transitions"][i]["when"]) for i in order]
    assert keys.index(("confirm_affordable",)) < keys.index(("budget_remaining",))

    starved = {"confirm_affordable": False, "budget_remaining": 2, "round": 1}
    nxt, rule = step(pol, "confirm", starved)
    assert nxt == "report"
    assert "registered decline" in rule["accounting"]


def test_the_semantic_exception_guards_are_registered_before_every_other_rule():
    """Correctness failure and a NaN response outrank every inferential branch.

    A run whose correctness tests failed produced a number, and that number is
    meaningless. Any rule allowed to fire ahead of the exception guard would
    draw an inference from it.
    """
    pol = compile_policy(_campaign())
    for state in ("screen", "foldover", "refine", "confirm"):
        if state not in pol["states"]:
            continue
        rules = [t for t in pol["transitions"]
                 if t.get("from") == state and "when" in t]
        first_two = [tuple(t["when"]) for t in rules[:2]]
        assert first_two == [("correctness_failed",), ("nan_response",)], (
            f"{state}: semantic-exception guards are not registered first: "
            f"{[tuple(t['when']) for t in rules]}"
        )
        # And they win against every other observation being simultaneously true.
        loud = {"correctness_failed": True, "certified": True,
                "refinable_survivors": 3, "alias_consequential": True,
                "foldover_affordable": True}
        assert step(pol, state, loud)[0] == "exception"


# ── Layer 2b: transition coverage over every registered branch ─────────────


def _witness_for(when: dict) -> dict:
    """An observation dict that satisfies `when` exactly.

    Built from the guard's own operators, so a guard added later gets a witness
    for free and the coverage table below cannot silently stop covering it.
    """
    obs: dict = {}
    for key, spec in when.items():
        if not isinstance(spec, dict):
            obs[key] = spec
            continue
        (op, want), = spec.items()
        obs[key] = {">": want + 1, ">=": want, "<": want - 1, "<=": want}[op]
    return obs


@pytest.mark.mutation_sentinel
def test_every_registered_branch_is_reachable_and_its_accounting_rule_fires(shape):
    """TRANSITION COVERAGE: each conditional branch has a witness that drives it.

    A registered branch nothing can reach pre-registers a decision the campaign
    can never take — worse than not registering it, because `enumerate_paths`
    reports a path the campaign cannot walk. Every guard is driven by an
    observation derived FROM THAT GUARD, so the assertion covers branches added
    after this test was written.
    """
    uncovered = []
    for t in shape["transitions"]:
        if "when" not in t:
            continue
        obs = _witness_for(t["when"])
        nxt, rule = step(shape, t["from"], obs)
        # An EARLIER rule from the same state may legitimately shadow this one
        # when their guards overlap (the semantic-exception guards do exactly
        # that by design). Reachability means: with the shadowing observations
        # cleared, the branch fires.
        if rule is not t:
            for earlier in shape["transitions"]:
                if earlier is t:
                    break
                if earlier.get("from") == t["from"] and "when" in earlier:
                    for k in earlier["when"]:
                        obs.pop(k, None) if k not in t["when"] else None
            nxt, rule = step(shape, t["from"], obs)
        if rule is not t:
            uncovered.append((t["from"], t.get("to"), tuple(t["when"])))
        else:
            assert nxt == t["to"]
            assert rule.get("accounting")
    assert not uncovered, f"unreachable registered branches: {uncovered}"


def test_transition_coverage_table_is_complete_for_the_default_shape(capsys):
    """Emits the coverage table the brief asks for, and asserts completeness.

    Printed rather than merely asserted so `pytest -s` produces the artifact; the
    assertion is what keeps it honest.
    """
    pol = compile_policy(_campaign(confirm_max_rounds=3))
    rows = []
    for t in pol["transitions"]:
        if "when" in t:
            obs = _witness_for(t["when"])
            kind = "conditional"
        else:
            obs, kind = {}, "default"
        nxt, rule = step(pol, t["from"], obs)
        rows.append((t["from"], t.get("to") or t.get("default"), kind,
                     tuple(t.get("when", {})), rule is t,
                     (t.get("accounting") or "default")[:48]))

    print("\nstate-transition coverage (default shape, confirm_max_rounds=3)")
    print(f"{'from':<10} {'to':<10} {'kind':<12} {'guard':<44} fired")
    for f, to, kind, guard, fired, acc in rows:
        print(f"{f:<10} {to or '-':<10} {kind:<12} {str(guard):<44} {fired}")

    # Every state in the policy appears as the `from` of at least one row, and
    # every non-terminal state has both a default and (except a pure passthrough)
    # at least one conditional.
    froms = {r[0] for r in rows}
    for name, st_ in pol["states"].items():
        if not st_.get("terminal"):
            assert name in froms, f"state {name!r} has no transitions at all"
    assert all(r[4] for r in rows if r[2] == "default"), (
        "a default transition did not fire under an empty observation"
    )


# ── Layer 3: the audit trail, walked statefully ────────────────────────────


class EpochWalk(RuleBasedStateMachine):
    """Walks real epochs through `step` + `append_transition`, then reads back.

    Why stateful rather than a table: the field failure was a PATH nobody had
    written down (every iteration aborting pre-fit, so the trail stayed empty and
    no terminal state was ever reached). A rule-based machine generates paths
    from the transition structure itself, so a path that violates an invariant is
    found without anyone having imagined it first.

    The invariants asserted after EVERY step are the ones the runtime depends on:
    `current_state` agrees with where the walk actually is; every row carries its
    `epoch` and `policy_hash`; the file is append-only; and `epoch_transitions`
    isolates this epoch from its predecessor's rows.
    """

    def __init__(self):
        super().__init__()
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.work_dir = Path(self._tmp.name)
        self.policy = compile_policy(_campaign(confirm_max_rounds=3), epoch=2)
        self.state = self.policy["initial"]
        self.iteration = 0
        self.written: list[dict] = []
        self.finished = False
        self.rolled_over: list[int] = []
        # A PRIOR epoch's rows, already on disk. Every read must ignore them:
        # transitions.jsonl is append-only ACROSS epochs, so an unfiltered read
        # would resume epoch 2 at epoch 1's terminal `exception`.
        self.stale = {"iteration": 99, "epoch": 1, "from": "confirm",
                      "to": "exception", "rule": {"default": "exception"},
                      "observations": {}, "policy_hash": "stale"}
        append_transition(self.work_dir, self.stale)

    def teardown(self):
        self._tmp.cleanup()

    def _advance(self, obs: dict):
        self.iteration += 1
        nxt, rule = step(self.policy, self.state, obs)
        row = {"iteration": self.iteration, "epoch": self.policy["epoch"],
               "from": self.state, "to": nxt, "rule": rule,
               "observations": obs,
               "policy_hash": policy_hash(self.policy)}
        append_transition(self.work_dir, row)
        self.written.append(row)
        self.state = nxt
        if is_terminal(self.policy, nxt):
            self.finished = True

    @precondition(lambda self: not self.finished)
    @rule()
    def nothing_was_observed(self):
        """The abort-before-fit path: an iteration that computed no observations."""
        self._advance({})

    @precondition(lambda self: not self.finished)
    @rule(n=st.integers(min_value=0, max_value=4))
    def survivors_found(self, n):
        self._advance({"refinable_survivors": n})

    @precondition(lambda self: not self.finished)
    @rule(consequential=st.booleans(), affordable=st.booleans())
    def alias_examined(self, consequential, affordable):
        self._advance({"alias_consequential": consequential,
                       "foldover_affordable": affordable})

    @precondition(lambda self: not self.finished)
    @rule(certified=st.booleans(), rnd=st.integers(min_value=1, max_value=4),
          budget=st.integers(min_value=0, max_value=40), afford=st.booleans())
    def confirm_round_completed(self, certified, rnd, budget, afford):
        self._advance({"certified": certified, "round": rnd,
                       "budget_remaining": budget, "confirm_affordable": afford})

    @precondition(lambda self: not self.finished)
    @rule(which=st.sampled_from(["correctness_failed", "nan_response"]))
    def measurement_was_uninterpretable(self, which):
        self._advance({which: True})

    @precondition(lambda self: not self.finished)
    @rule(in_hull=st.booleans())
    def stationary_point_located(self, in_hull):
        self._advance({"stationary_in_hull": in_hull})

    @precondition(lambda self: self.finished)
    @rule()
    def the_epoch_ended_so_a_new_one_is_compiled(self):
        """The one legitimate way to change a design: a NEW epoch.

        Recompiling across an epoch boundary is the opposite operation from
        editing inside one — a fresh pre-registration, freshly hashed, whose
        rows must not be confused with its predecessor's. Making this a RULE
        rather than a fixture means the walk exercises epoch rollover at every
        terminal it can reach, not just at one hand-picked one.
        """
        prior = self.policy["epoch"]
        self.rolled_over.append(prior)
        self.policy = compile_policy(_campaign(confirm_max_rounds=3),
                                     epoch=prior + 1)
        self.state = self.policy["initial"]
        self.written = []
        self.finished = False

    @invariant()
    def current_state_reads_back_where_the_walk_actually_is(self):
        assert current_state(self.policy, self.work_dir) == self.state

    @invariant()
    def the_trail_records_exactly_what_step_returned(self):
        rows = epoch_transitions(self.policy, self.work_dir)
        assert len(rows) == len(self.written)
        for got, want in zip(rows, self.written):
            assert got["from"] == want["from"] and got["to"] == want["to"]
            assert got["observations"] == want["observations"]

    @invariant()
    def every_row_carries_its_epoch_and_policy_hash(self):
        for r in epoch_transitions(self.policy, self.work_dir):
            assert r["epoch"] == self.policy["epoch"]
            assert r["policy_hash"] == policy_hash(self.policy)

    @invariant()
    def the_previous_epochs_rows_survive_and_are_never_read_as_ours(self):
        """Append-only ACROSS epochs, and epoch-filtered on every read.

        The seeded epoch-1 row must still be the FIRST line of the file no
        matter how many epochs the walk has rolled through: a semantic
        exception ends an epoch, it never truncates the audit trail. And every
        row a read returns must belong to the epoch that asked.
        """
        allrows = read_transitions(self.work_dir)
        assert allrows[0]["policy_hash"] == "stale"
        assert allrows[0]["epoch"] == 1
        mine = epoch_transitions(self.policy, self.work_dir)
        assert all(r["epoch"] == self.policy["epoch"] for r in mine), (
            "a read leaked rows belonging to another epoch"
        )
        # Nothing is ever removed: the file only grows.
        assert len(allrows) >= len(self.written) + 1 + len(self.rolled_over)

    @invariant()
    def the_walk_never_leaves_the_declared_state_space(self):
        assert self.state in self.policy["states"]

    @invariant()
    def a_finished_walk_sits_on_a_terminal_state(self):
        if self.finished:
            assert is_terminal(self.policy, self.state)

    @invariant()
    def the_walk_cannot_outlive_the_epochs_compile_time_bound(self):
        """`longest_path` is a real upper bound on the iterations an epoch takes.

        A generous slack (x3) because the walk's rules can revisit `confirm`
        with observations that keep it looping, which is precisely what
        `max_rounds` bounds in production; the point of the invariant is that the
        bound EXISTS and is finite, not that it is tight.
        """
        assert len(self.written) <= 3 * longest_path(self.policy) + 8, (
            f"epoch {self.policy['epoch']} took {len(self.written)} steps, past "
            f"any bound derivable from longest_path={longest_path(self.policy)}"
        )


TestEpochWalk = EpochWalk.TestCase
TestEpochWalk.settings = settings(
    derandomize=True, deadline=None, max_examples=150, stateful_step_count=14,
    suppress_health_check=[HealthCheck.too_slow],
)


# ── Layer 3b: the empty-trail field failure, as a regression assertion ─────


@pytest.mark.mutation_sentinel
def test_a_transition_written_for_an_iteration_that_observed_nothing_is_still_recorded(tmp_path):
    """THE FIELD FAILURE, at the seam that failed.

    Every iteration of a real 14-hour campaign aborted before the fit, so no
    `step()` ran and `transitions.jsonl` was EMPTY — 18 valid measured rows and
    a completely blank audit trail. The unit-level guarantee that makes the
    empty trail impossible is: `step` is total for the empty observation dict
    (asserted above), and every `step` is followed by an `append_transition`.

    This test pins the second half at the policy seam. Whether the RUNTIME
    reaches this seam on a partial design is Agent A's change; see
    `test_optimize_contract_chain.py` for the pending end-to-end version.
    """
    pol = compile_policy(_campaign())
    nxt, rule = step(pol, "screen", {})
    append_transition(tmp_path, {"iteration": 1, "epoch": pol["epoch"],
                                 "from": "screen", "to": nxt, "rule": rule,
                                 "observations": {},
                                 "policy_hash": policy_hash(pol)})
    rows = read_transitions(tmp_path)
    assert len(rows) == 1
    assert rows[0]["from"] == "screen" and rows[0]["to"] == nxt
    assert current_state(pol, tmp_path) == nxt
    assert rows[0]["observations"] == {}, (
        "an iteration that observed nothing must still record WHAT it observed "
        "(nothing) — an absent key is indistinguishable from an unwritten row"
    )


def test_current_state_of_a_fresh_epoch_is_initial_not_its_predecessors_terminal(tmp_path):
    """A recompiled epoch starts at `screen`, not at epoch 1's `exception`.

    Without the epoch filter the new epoch would resume at a terminal state it
    can never leave — permanently stuck at the failure it was recompiled to
    escape.

    Cross-reference: `docs/optimization-invariants.md` INV-TMP07 — the statement of
    record lives there; this test is the executable check.
    """
    e1 = compile_policy(_campaign(), epoch=1)
    append_transition(tmp_path, {"iteration": 1, "epoch": 1, "from": "screen",
                                 "to": "exception", "rule": {"default": "exception"},
                                 "observations": {"nan_response": True},
                                 "policy_hash": policy_hash(e1)})
    assert current_state(e1, tmp_path) == "exception"

    e2 = compile_policy(_campaign(), epoch=2)
    assert current_state(e2, tmp_path) == e2["initial"] == "screen"
    assert len(read_transitions(tmp_path)) == 1, "the predecessor's row was destroyed"


# ── Two more mutation survivors, closed ───────────────────────────────────


@pytest.mark.mutation_sentinel
def test_each_declared_delta_lands_in_its_own_field_and_they_are_not_swapped():
    """CLOSES A MUTATION SURVIVOR (M08): `delta_screen` <-> `delta_terminal` swapped.

    A range assertion (`0 < delta < 1`) is blind to a swap by construction — both
    values stay in range. The swap is only observable when the two DIFFER and the
    mapping from declaration to field is checked, so this test declares them
    distinct and asserts which is which.

    Why the swap matters rather than merely being untidy: the two deltas buy
    different guarantees. `delta_screen` is spent on the MODEL bound, which
    carries the registered response-class assumption; `delta_terminal` is spent on
    the assumption-light terminal bound. A campaign that deliberately spends more
    of its error budget on the assumption-light comparison (the defensible choice)
    would silently get the opposite allocation, and `Pr(wrong decision) <=
    delta_s + delta_t` would still appear to hold because the SUM is unchanged.
    That is what makes it a swap rather than an error: the aggregate is right and
    every individual claim is wrong.

    Cross-reference: `docs/optimization-invariants.md` INV-SEM03 — the statement of
    record lives there; this test is the executable check.
    """
    pol = compile_policy(_campaign(delta_screen=0.02, delta_terminal=0.08))
    assert pol["objective"]["delta_screen"] == 0.02
    assert pol["objective"]["delta_terminal"] == 0.08

    # And a campaign declaring only one gets the default for the other, in the
    # right slot.
    only_screen = compile_policy(_campaign(delta_screen=0.01))
    assert only_screen["objective"]["delta_screen"] == 0.01
    assert only_screen["objective"]["delta_terminal"] == 0.05

    only_terminal = compile_policy(_campaign(delta_terminal=0.2))
    assert only_terminal["objective"]["delta_screen"] == 0.05
    assert only_terminal["objective"]["delta_terminal"] == 0.2


@pytest.mark.mutation_sentinel
def test_the_policy_hash_covers_the_transitions_so_an_edited_branch_changes_it():
    """CLOSES A MUTATION SURVIVOR (M22), and it is the most serious of the three.

    `policy_hash` is what makes `policy.json` a PRE-REGISTRATION: the hash written
    before the first benchmark run is the evidence that every branch was fixed
    before any result was seen, and `_load_or_compile_policy` hard-aborts when the
    document stops matching it. A hash computed over everything EXCEPT
    `transitions` would leave the adaptive branches — the only part an author
    could profitably edit mid-epoch — entirely unprotected: retarget a branch from
    `report` to `confirm` after seeing a disappointing screen, and the hash still
    matches, the abort never fires, and the artifact still claims to have been
    pre-registered.

    Nothing else in the suite noticed, because every other hash test compares a
    policy against ITSELF (round-trip) or against a stored digest of the same
    unmutated document. The property that has teeth is DIFFERENTIAL: two policies
    differing only in their transitions must hash differently.

    Cross-reference: `docs/optimization-invariants.md` INV-PROV01, INV-TMP01 — the statement of
    record lives there; this test is the executable check.
    """
    base = compile_policy(_campaign())
    assert base["transitions"], "no transitions to protect"

    # 1. Retargeting one branch changes the hash.
    retargeted = _mutate(base)
    for t in retargeted["transitions"]:
        if t.get("from") == "screen" and t.get("to") == "exception":
            t["to"] = "report"
            break
    else:
        pytest.fail("no screen->exception branch to retarget")
    assert policy_hash(retargeted) != policy_hash(base), (
        "retargeting a registered branch left the policy hash unchanged — the "
        "pre-registration does not cover the branches it exists to pre-register"
    )

    # 2. Removing a branch changes the hash.
    fewer = _mutate(base)
    fewer["transitions"] = fewer["transitions"][:-1]
    assert policy_hash(fewer) != policy_hash(base)

    # 3. Loosening a guard's threshold changes the hash.
    loosened = _mutate(base)
    for t in loosened["transitions"]:
        if isinstance(t.get("when", {}).get("refinable_survivors"), dict):
            t["when"]["refinable_survivors"] = {">": 99}
            break
    assert policy_hash(loosened) != policy_hash(base)

    # 4. Rewriting an accounting rule changes the hash: the rule is the
    #    inferential justification, so a branch relabelled to cite a different
    #    rule is a different pre-registration.
    relabelled = _mutate(base)
    for t in relabelled["transitions"]:
        if t.get("accounting"):
            t["accounting"] = "vibes"
            break
    assert policy_hash(relabelled) != policy_hash(base)

    # 5. Re-serialising the SAME document does not change it (the hash is over
    #    content, not over dict ordering), or the abort would fire spuriously.
    assert policy_hash(_mutate(base)) == policy_hash(base)
