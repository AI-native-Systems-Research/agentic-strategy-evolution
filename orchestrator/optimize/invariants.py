"""The compiled epoch's invariant REGISTRY: IDs, statements, and checkers.

Companion document: ``docs/optimization-invariants.md``, which carries the
prose, the evidence trail, and the behavior enumeration (§8). This module is
the machine-readable half. ``tests/test_optimize_invariants.py`` fails when the
two disagree in either direction, which is what keeps the inventory alive
rather than archaeological.

WHY THIS EXISTS. There are ~128 invariant-flavored statements in this package's
docstrings and comments -- "MUST NEVER", "load-bearing", "always", "by
construction", "the whole point is". Before this module none of them was
machine-checkable, and a real field test burned ~14 hours during which several
stated invariants were silently violated and nothing noticed. Prose that cannot
fail is a record of an intention, not a guard.

HOW THIS DIFFERS FROM THE TWO NEIGHBOURING "INVARIANT" CONCEPTS, which it is
easy and costly to confuse it with:

  * ``design_space.invariants`` (campaign YAML -> ``matrix.check_invariants``,
    ``runner._check_invariants``, ``validate.py``) are AUTHOR-DECLARED
    predicates over one measured response: "did this row stay inside the
    declared design space?". They are data, they differ per campaign, they are
    checked per ROW, and a violation makes that row ``rejected``. They say
    nothing about whether Nous itself is behaving.
  * ``relations`` / ``_check_correctness_relations`` are author-declared
    NATIVE TESTS in the target's own language, reconciled per stage. A
    correctness failure aborts the campaign; a behavioral one is a finding.
    Again: claims about the TARGET.
  * THIS module's invariants are claims about NOUS -- properties of the
    orchestrator's own artifacts, vocabularies, and arithmetic that hold for
    every campaign regardless of what any author declared. They are code, not
    data. Nothing here reads a campaign's ``design_space`` block.

Mnemonic: ``design_space.invariants`` ask "is the TARGET behaving?"; this module
asks "is NOUS behaving?".

WHAT A CHECKER MAY DO. Every checker is a PURE function returning
``list[str]`` -- one string per violation, empty when the invariant holds.
Never raises for a violation (the caller decides whether a violation is fatal),
never writes, never reads a file it was not handed, and never makes a model
call. Checkers are called from seams inside a compiled epoch, so an impure one
would break ``INV-ECO01``, the invariant this package cares about most.

WHAT A CHECKER MAY NOT COST. A check that walks every row on every stage is
fine. One that refits a model is not: the enforcement must not become a second,
slower copy of the thing it checks. ``INV-STAT01`` is therefore checked by
inspecting a ``Fit``'s labels rather than by re-solving, and ``INV-STAT04``'s
monotonicity is a ``test``-class property rather than an ``always`` one.

ENFORCEMENT CLASSES, and why an invariant lands in each:

  * ``ALWAYS``   -- every production run, at a named seam. O(rows) at worst.
  * ``PARANOID`` -- only under ``NOUS_OPTIMIZE_PARANOID=1``. For checks that
                    duplicate a guard one layer down, or whose failure mode has
                    never been observed and whose check is not free.
  * ``TEST``     -- only in the suite. Either it needs constructed inputs (a
                    mutated policy, a hand-built degenerate design) or it is a
                    property over a generated space, so there is no production
                    seam where it could fire.
  * ``AUDIT``    -- a post-hoc walk over a finished work-dir
                    (``audit_work_dir``). For epoch/campaign-level invariants
                    where inline checking would mean holding the whole campaign
                    in memory -- and, in ``INV-TMP08``'s case, because the
                    violation is precisely that the inline seam is never
                    reached.

Stdlib only, deliberately: this package has a no-numpy discipline and the
registry must be importable from anywhere in it without a dependency cycle. No
module-level import of any other ``orchestrator.optimize`` module, for the same
reason -- the few checkers that need one import it inside the function.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ── the two classification axes ───────────────────────────────────────────

#: TYPE. The prefix of every ID is its type, so an ID alone tells a reader what
#: KIND of thing broke. ``PROV`` and ``VOC`` were not in the starting taxonomy
#: and the evidence demanded them -- see the document's §1 for the argument.
TYPES: frozenset[str] = frozenset({
    "ST",    # structural: shape, schema, reference integrity
    "VOC",   # closed vocabulary: the set stays closed AND fully consumed
    "SEM",   # semantic/accounting: meaning-preserving; None is not zero
    "STAT",  # statistical: properties of estimates
    "TMP",   # temporal/ordering: sequencing
    "PROV",  # provenance/identity: two records of one commitment agreeing
    "RES",   # resource/isolation
    "ECO",   # economic: token and budget cost
})

#: LEVEL. Where the invariant must hold, and therefore where it is checkable.
#: The ordering is meaningful: a ``function``-level invariant can be a property
#: test, while an ``epoch``-level one can usually only be checked post hoc --
#: which is exactly why the epoch-level ones went unnoticed for 14 hours.
LEVELS: tuple[str, ...] = (
    "function", "module", "artifact", "iteration", "epoch", "campaign",
)

ALWAYS, PARANOID, TEST, AUDIT = "always", "paranoid", "test", "audit"
ENFORCEMENT: frozenset[str] = frozenset({ALWAYS, PARANOID, TEST, AUDIT})

PARANOID_ENV = "NOUS_OPTIMIZE_PARANOID"


def paranoid_enabled() -> bool:
    """Whether ``PARANOID``-class checks run. Off unless explicitly enabled."""
    return os.environ.get(PARANOID_ENV, "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Invariant:
    """One registered invariant.

    ``checker`` is ``None`` for an invariant that is real, traced, and NOT
    mechanically checkable from inside the process -- and that absence is
    information rather than an omission, so the registry records it instead of
    silently dropping the entry. ``violated_by`` names a historical defect, or
    is empty.

    ``open_violation`` is the honest field, and it is currently ``False``
    everywhere -- the five entries that carried ``True`` (INV-SEM02, INV-STAT05,
    INV-STAT12, INV-TMP08, INV-PROV01) were all closed and each verified
    empirically before the flag was cleared, not cleared because the fix was
    believed. Do not clear a flag without reproducing the violation's absence.
    ``True`` means the CURRENT code
    violates this stated invariant, verified empirically, and the checker (if
    any) is expected to fail against production artifacts until the underlying
    seam is fixed. An inventory that quietly omitted these would be worse than
    no inventory, because a reader would take silence for compliance.
    """

    id: str
    statement: str
    type: str
    level: str
    evidence: str
    enforcement: str
    checker: Callable[..., list[str]] | None = None
    violated_by: str = ""
    open_violation: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        prefix = self.id[len("INV-"):].rstrip("0123456789")
        if not self.id.startswith("INV-") or prefix not in TYPES:
            raise ValueError(
                f"invariant id {self.id!r} must be INV-<TYPE><nn> with TYPE in "
                f"{sorted(TYPES)}",
            )
        if prefix != self.type:
            raise ValueError(
                f"{self.id}: id prefix {prefix!r} disagrees with type {self.type!r}. "
                f"The prefix is how a reader classifies a violation from the ID "
                f"alone, so the two cannot be allowed to drift.",
            )
        if self.level not in LEVELS:
            raise ValueError(f"{self.id}: level {self.level!r} not in {LEVELS}")
        if self.enforcement not in ENFORCEMENT:
            raise ValueError(f"{self.id}: enforcement {self.enforcement!r} unknown")


class InvariantViolation(AssertionError):
    """A registered invariant was violated at a seam that treats it as fatal.

    ``AssertionError`` rather than a bespoke base because these are internal
    consistency claims about Nous, not campaign-authoring errors: an author
    cannot cause one by writing a bad YAML file, and a caller should not be
    catching them to recover. Callers that want a verdict rather than an
    exception call the checker directly and read the returned list.
    """

    def __init__(self, invariant_id: str, violations: list[str]) -> None:
        inv = REGISTRY.get(invariant_id)
        statement = inv.statement if inv else "<unregistered>"
        super().__init__(
            f"{invariant_id} violated: {statement}\n  "
            + "\n  ".join(violations)
            + f"\n(see docs/optimization-invariants.md#{invariant_id.lower()})",
        )
        self.invariant_id = invariant_id
        self.violations = list(violations)


# ══════════════════════════════════════════════════════════════════════════
#  CHECKERS
#
#  Each returns list[str]: one message per violation, empty when it holds.
#  Named `check_<what>` rather than `check_INV_xx` so a reader at the call site
#  sees what is being checked, not an opaque id.
# ══════════════════════════════════════════════════════════════════════════

# ── structural / vocabulary ───────────────────────────────────────────────

def check_policy_structure(policy: dict) -> list[str]:
    """INV-ST01..06, INV-VOC01/02, INV-SEM05: delegate to ``check_policy``.

    Deliberately a delegation and not a reimplementation. ``policy.check_policy``
    is the shipped structural gate; a second copy here would drift from it and
    the registry would then certify a policy the real gate refuses (or the
    reverse). The registry's value for these is the ID, the classification, and
    the anti-drift binding to the document -- not a competing implementation.
    """
    from orchestrator.optimize.policy import check_policy

    return list(check_policy(policy))


def check_comparison_ops_subset() -> list[str]:
    """INV-VOC03: ``COMPARISON_OPS`` is a subset of ``predicates.OPS``.

    A policy ``check_policy`` refuses must not be one ``step`` can still drive,
    and the reverse -- an op in ``COMPARISON_OPS`` with no callable behind it --
    would make ``_match_one`` silently treat the predicate as unsatisfiable and
    strand the registered branch it guards.
    """
    from orchestrator.optimize.policy import COMPARISON_OPS
    from orchestrator.optimize.predicates import OPS

    missing = sorted(set(COMPARISON_OPS) - set(OPS))
    return [
        f"COMPARISON_OPS contains {op!r} with no callable in predicates.OPS: "
        f"check_policy would accept a predicate step() cannot interpret"
        for op in missing
    ]


def check_observation_keys_consumed(policy, *, documented_non_branching=()) -> list[str]:
    """INV-VOC04: no dead vocabulary that reads like a live guard.

    Every ``OBSERVATION_KEYS`` member must have a named consumer: a registered
    transition, an artifact field, or a documented non-branching note.
    ``runs_needed_confirm`` was dead vocabulary for six tasks -- its producing
    comment claimed "so a compiled guard can compare it against the remaining
    budget", no such guard existed, and the gap it was computed to close stayed
    open the whole time.

    Only the FIRST of the three consumers is checkable from the policy alone, so
    this takes the documented exemptions as an argument rather than hardcoding
    them: the caller (the test) supplies the set the document justifies, which
    is what makes an addition to that set a visible edit to the inventory
    instead of an invisible edit to a Python literal.

    ``policy`` may be ONE compiled policy or a list of them: a key some
    campaign SHAPE compiles a guard for is consumed, even when a single-objective
    policy never registers it (``front_gap_large`` branches only in a
    multi-objective policy). The caller passes every shape it means to cover.
    """
    from orchestrator.optimize.policy import OBSERVATION_KEYS

    branched: set[str] = set()
    for pol in (policy if isinstance(policy, (list, tuple)) else [policy]):
        for t in pol.get("transitions") or []:
            branched |= set(t.get("when") or {})
    dead = sorted(set(OBSERVATION_KEYS) - branched - set(documented_non_branching))
    return [
        f"observation key {k!r} is in OBSERVATION_KEYS, is read by no `when` "
        f"clause, and is not in the documented non-branching set: it is dead "
        f"vocabulary that reads like a live guard"
        for k in dead
    ]


def check_vocabulary_produced_equals_consumed(
    *, name: str, produced, consumed,
) -> list[str]:
    """INV-VOC08: a closed vocabulary's producers and consumers agree.

    THE DEFECT CLASS THIS EXISTS FOR, which cost a certified-but-wrong answer on
    a synthetic oracle and would have cost a real campaign the same. The
    finalist-status vocabulary in ``_finish_confirm`` was split from a single
    ``"excluded"`` into ``"infeasible"`` / ``"unmeasured"`` -- a correct change,
    because a timed-out finalist was being reported as though it had violated a
    constraint. But the consumer three hundred lines later still read the
    RETIRED literal::

        n_excluded = sum(1 for v in status.values() if v == "excluded")

    Nothing raised. Nothing was type-checked. ``n_excluded`` silently became 0
    for every campaign, so nothing withheld certification, the registered
    ``confirm -> confirm`` top-up never fired, and the ``sla`` surface CERTIFIED
    an answer 6.12% off the true constrained optimum. Only the synthetic oracle
    caught it, end to end, after the fact.

    A literal string compared in one place and produced in another is a
    reference with no referential integrity. The general form is checkable and
    cheap: collect what the producer can emit, collect what the consumers
    compare against, and require the second to be a subset of the first. A
    consumer comparing against a value no producer can emit is a branch that
    can never fire -- which is exactly the failure, and it is invisible to
    every schema, every type checker, and every unit test that exercises the
    producer and the consumer separately.

    Both directions are reported, and they mean different things:
      * consumed-but-never-produced = a DEAD branch (the defect above);
      * produced-but-never-consumed = an UNHANDLED case, which is how a new
        status silently falls through a dispatch that had no arm for it.
    """
    produced, consumed = set(produced), set(consumed)
    out = [
        f"{name}: value {v!r} is compared by a consumer but no producer can "
        f"emit it -- that branch can never fire (the `n_excluded == \"excluded\"` "
        f"defect class)"
        for v in sorted(consumed - produced)
    ]
    out += [
        f"{name}: value {v!r} is produced but no consumer compares against it -- "
        f"an unhandled case falls through whatever dispatch reads this vocabulary"
        for v in sorted(produced - consumed)
    ]
    return out


def check_schema_declares_written_fields(
    schema: dict, row: dict, *, where: str = "row",
) -> list[str]:
    """INV-ST10: every field the producer writes is declared by the schema.

    Verified against a row from the REAL code path, never a hand-written dict --
    that distinction IS the invariant. ``runs_row.schema.json`` was
    ``additionalProperties: false`` while ``_run_row`` always wrote
    ``held_out`` / ``manipulation`` / ``invariants``, so EVERY real row on disk
    was schema-invalid, and the existing test passed the whole time because it
    validated dicts it had built itself. A schema tested only against its own
    test fixtures certifies the fixtures.
    """
    props = set((schema.get("properties") or {}).keys())
    out: list[str] = []
    if schema.get("additionalProperties") is False:
        undeclared = sorted(set(row) - props)
        out += [
            f"{where}: field {k!r} is written by the producer but not declared in "
            f"a schema with additionalProperties:false -- every real row on disk "
            f"is schema-invalid"
            for k in undeclared
        ]
    missing = sorted(set(schema.get("required") or []) - set(row))
    out += [
        f"{where}: field {k!r} is required by the schema but the producer did "
        f"not write it"
        for k in missing
    ]
    return out


def check_held_out_split(response: dict, held_out: dict) -> list[str]:
    """INV-ST07: ``response`` is fitting-safe by construction.

    The split is STRUCTURAL, not a filtered view: a held-out metric is removed
    from ``response`` entirely. So passing ``response`` wholesale to a fitter is
    safe by DEFAULT, rather than safe only if the caller remembered to reach for
    a particular sub-key.
    """
    leaked = sorted(set(response or {}) & set(held_out or {}))
    return [
        f"held-out metric {k!r} appears in `response` as well as `held_out`; "
        f"`response` is no longer fitting-safe by construction"
        for k in leaked
    ]


def check_failure_kind_agrees_with_status(status: str, failure_kind: str) -> list[str]:
    """INV-ST08/INV-VOC05: a non-complete row names WHY, a complete one does not."""
    from orchestrator.optimize.runner import FAILURE_KINDS

    out: list[str] = []
    if status == "complete" and failure_kind:
        out.append(
            f"a complete row carries failure_kind={failure_kind!r}; the empty "
            f"string is what marks a clean row",
        )
    if status != "complete" and not failure_kind:
        out.append(
            f"a {status!r} row carries no failure_kind, so telling a timeout (a "
            f"BUDGET question about the design) from an adapter crash (a DEFECT "
            f"that recurs) means substring-matching prose",
        )
    if failure_kind and failure_kind not in FAILURE_KINDS:
        out.append(
            f"failure_kind {failure_kind!r} is outside the closed FAILURE_KINDS "
            f"vocabulary {sorted(FAILURE_KINDS)}",
        )
    return out


# ── semantic / accounting ─────────────────────────────────────────────────

_BASES = ("certified", "terminal_best", "model", "measured", "baseline", "none")


def check_report_bounds_separate(report: dict) -> list[str]:
    """INV-SEM01/02/03: the two bounds stay apart, and null is not zero.

    ``Pr(wrong global decision) <= delta_s + delta_t`` is only meaningful while
    the two numbers stay apart. One merged "regret" number would advertise the
    assumption-light guarantee while delivering the model-dependent one -- so a
    report carrying a collapsed field, or missing one of the two, is a violation
    even if every number in it is individually right.
    """
    out: list[str] = []
    for k in ("residual_regret_model", "residual_regret_terminal"):
        if k not in report:
            out.append(
                f"report.json is missing {k!r}: the two bounds rest on different "
                f"assumptions and both must be reported",
            )
    for k in ("residual_regret", "regret", "residual_regret_combined"):
        if k in report:
            out.append(
                f"report.json carries a collapsed bound field {k!r}; the model "
                f"and terminal bounds must never be merged into one number",
            )
    for k in ("delta_screen", "delta_terminal"):
        if k not in report:
            out.append(f"report.json is missing {k!r}: each bound reports its own delta")
    basis = (report.get("recommendation") or {}).get("basis")
    if basis not in _BASES:
        out.append(
            f"recommendation.basis is {basis!r}, not one of the six declared "
            f"values {list(_BASES)}; the report must always name a rung",
        )
    return out


def check_exception_removes_only_model_rung(report: dict) -> list[str]:
    """INV-SEM04: a semantic exception removes ONLY the ``model`` rung.

    Rungs 1/2 are measurements of a shortlist against itself and do not consult
    the fitted surface, so an exception at a later state does not retract a
    terminal comparison that actually happened. And the report must still name
    an action -- the pre-ladder behaviour (raise, no ``report.json`` at all) is
    the defect the ladder exists to fix.
    """
    out: list[str] = []
    ended = report.get("epoch_ended")
    basis = (report.get("recommendation") or {}).get("basis")
    if ended and basis == "model":
        out.append(
            "report.json carries epoch_ended AND basis 'model'; the fitted "
            "surface is what the semantic exception impeached, so the model rung "
            "is unavailable once an exception ended the epoch",
        )
    if basis is None:
        out.append("report.json names no basis at all; the report must ALWAYS act")
    return out


def check_recommendation_admissible_per_configuration(
    report: dict, rows: list[dict],
) -> list[str]:
    """INV-SEM14: the report never returns a configuration any row measured inadmissible.

    Feasibility is a property of the CONFIGURATION: one ``infeasible`` /
    ``rejected`` row at the recommended levels makes it inadmissible however
    many other rows there completed -- the sticky rule confirm applies to its
    finalists. ``baseline`` is exempt (the author's declared last resort,
    returned and labelled as such) and ``none`` names nothing.
    """
    rec = report.get("recommendation") or {}
    if rec.get("basis") in ("baseline", "none") or not rec.get("levels"):
        return []
    want = rec["levels"]
    bad = sorted({
        r.get("status") for r in rows
        if r.get("levels") == want and r.get("status") in ("infeasible", "rejected")
    })
    if bad:
        return [
            f"report.json recommends {want} on basis {rec.get('basis')!r} although "
            f"rows at those levels were measured {bad}: a configuration admissible "
            f"only sometimes is not admissible",
        ]
    return []


def check_epsilon_has_a_reference(confirmation: dict) -> list[str]:
    """INV-SEM15: confirm's epsilon names its reference and is never a 0 from none.

    ``{"pct": p}`` is a percentage OF something. With no admissible finalist
    there is no winner to take it of, and resolving it against a missing value
    gave epsilon = 0 -- a width that can never certify and that the author never
    declared. Either a recorded reference stands behind a positive epsilon, or
    epsilon is null (unknown).
    """
    eps = confirmation.get("epsilon")
    ref = confirmation.get("epsilon_reference")
    out: list[str] = []
    if not isinstance(ref, dict) or "source" not in ref:
        out.append("confirmation.json carries no epsilon_reference")
        return out
    if ref["source"] == "none":
        if eps is not None:
            out.append(f"epsilon={eps!r} with no reference; it must be null (unknown)")
    elif ref["source"] != "declared_abs" and not (
        isinstance(eps, (int, float)) and eps > 0
    ):
        out.append(
            f"epsilon={eps!r} resolved from reference {ref['source']!r}; a "
            f"percentage of a recorded reference is never 0",
        )
    return out


def check_curvature_routes_to_refine(policy: dict) -> list[str]:
    """INV-SEM16: centre-point curvature never routes to confirm while refine exists.

    A response with an interior optimum has ~zero main effects at a 2-level
    screen's corners, so ``refinable_survivors > 0`` cannot fire and the ONLY
    evidence of the optimum is the centre-point curvature contrast (the
    lack-of-fit F on pure error). Whenever the policy registers ``refine``, each
    first-order state (``screen``, ``foldover``) must carry a
    ``{"lack_of_fit": True} -> refine`` rule that names its accounting, so such a
    screen augments to the second-order design instead of certifying an
    uninformed shortlist (``SURFACES["geometric_knob"]``: 26% below the optimum,
    certified, on every seed).
    """
    states = policy.get("states") or {}
    if "refine" not in states:
        return []
    out: list[str] = []
    for src in ("screen", "foldover"):
        if src not in states:
            continue
        hit = [t for t in policy.get("transitions") or []
               if t.get("from") == src and t.get("to") == "refine"
               and (t.get("when") or {}).get("lack_of_fit") is True
               and t.get("accounting")]
        if not hit:
            out.append(
                f"policy registers refine but {src!r} has no `lack_of_fit` -> refine "
                f"rule: a screen whose centre points detect curvature with no "
                f"refinable survivor would go to confirm and certify an "
                f"uninformed shortlist",
            )
    return out


def check_certificate_rests_on_adequate_model(certifying: dict,
                                              recommendation: dict) -> list[str]:
    """INV-SEM17: no global certificate rests on a model the data rejected.

    ``certifying`` is a ``confirmation.json`` or ``report.json``;
    ``recommendation`` is the latest fitting stage's ``recommendation.json``.
    When that fit's lack-of-fit test rejected (``model_adequate: false``) the
    shortlist was not informed by an adequate model, so the delta_screen premise
    is unsupported: ``certified`` must be false and, whenever terminal
    discrimination ran, ``certification_withheld`` must name
    ``model_inadequate``. An absent ``model_adequate`` reads as adequate (records
    predating the field). An UNKNOWN adequacy (``model_adequate: null``,
    stage-1b N1) likewise forbids a certificate, and the withheld reasons must
    name its ``model_adequate_basis``.
    """
    if "model_adequate" in recommendation and recommendation["model_adequate"] is None:
        basis = str(recommendation.get("model_adequate_basis") or "model_adequacy_unknown")
        out_u: list[str] = []
        if certifying.get("certified"):
            out_u.append(
                f"certified is true although the latest fitting stage's model "
                f"adequacy is UNKNOWN ({basis}) -- an untested model cannot "
                f"support the delta_screen premise")
        withheld = list(certifying.get("certification_withheld") or [])
        if withheld and "no_terminal_discrimination" not in withheld \
                and basis not in withheld:
            out_u.append(f"certification_withheld {withheld} omits {basis} although "
                         f"the model's adequacy is unknown")
        return out_u
    if recommendation.get("model_adequate") is not False:
        return []
    out: list[str] = []
    if certifying.get("certified"):
        out.append(
            "certified is true although the latest fitting stage reported "
            "model_adequate: false -- the shortlist was not informed by an "
            "adequate model, so the delta_screen premise is unearned",
        )
    withheld = list(certifying.get("certification_withheld") or [])
    if withheld and "no_terminal_discrimination" not in withheld \
            and "model_inadequate" not in withheld:
        out.append(
            f"certification_withheld {withheld} omits model_inadequate although "
            f"the model behind the shortlist failed its lack-of-fit test",
        )
    return out


def check_bound_unknown_is_not_zero(bound: Any) -> list[str]:
    """INV-SEM02 / INV-STAT05: a bound with no variance estimate is None.

    Spec §3.5, measured: four centre points on a real campaign returned
    bit-identical values, so ``pure_error = 0`` and every interval came back
    ``None``. A zero-variance sample supplies NO variance estimate, so a bound
    derived from it is unknown -- and an unknown is not a zero.

    ``model_regret_bound`` gets this right (``pure_error_df <= 0`` ->
    ``method="none"``, ``value=None``). ``terminal_regret_bound`` does NOT: on
    bit-identical replicates every ``variance()`` is 0, so ``se`` is 0, and the
    bound returns ``value=0.0`` wearing ``method="bonferroni_one_sided_t_paired"``
    -- a claim of exact epsilon-optimality derived from zero information, in the
    label of a real t-based certificate. This checker is what makes that
    detectable at the seam rather than only in the field.
    """
    value = getattr(bound, "value", None)
    method = getattr(bound, "method", "")
    if value == 0.0 and method not in {"none", "trivial"}:
        return [
            f"bound reports value=0.0 under method={method!r}. A floored-at-zero "
            f"bound is legitimate when the winner is clear, but a bound computed "
            f"from a ZERO-VARIANCE sample is not estimable at all and must be "
            f"None -- an unknown is not a zero (spec 3.5)",
        ]
    return []


def check_alias_sign_preserved(effect: Any) -> list[str]:
    """INV-SEM08: an alias's re-attributed coefficient carries its sign.

    Re-labelling ``AB``'s estimate as ``C`` while KEEPING its sign claims ``C``
    pushes the response DOWN when it pushes it up -- reversing the physical
    direction of the effect. Verified arithmetic: with ``col_C = -col_AB``, a
    response generated purely by ``C`` at ``+2.0`` fits ``beta_C = +2.0`` and
    ``beta_AB = -2.0``.
    """
    out: list[str] = []
    for terms, sign in getattr(effect, "aliased_with", ()) or ():
        if sign not in (1.0, -1.0):
            out.append(
                f"effect {getattr(effect, 'label', '?')!r} aliases {terms} with "
                f"sign {sign!r}; only +1.0 (identical column) and -1.0 (exact "
                f"negation) are meaningful, and the sign is load-bearing",
            )
    return out


def check_behavioral_not_folded_into_correctness(verdicts) -> list[str]:
    """INV-SEM09: correctness and behavioral failures stay in their own buckets.

    A correctness verdict smuggled into the behavioral bucket UNDER-reacts:
    behavioral triggers advance the stage, while correctness failures must abort.
    Also catches the upstream-dependency gap a verification pass found:
    ``classify_failures`` silently drops a failure whose ``kind`` is
    off-vocabulary (``kind="perf"`` lands in NEITHER bucket), so the "every
    failure is classified" property is enforced by ``factors._check_relations``
    at parse time, not inside the classifier that a caller can reach directly.
    """
    out: list[str] = []
    for v in verdicts or ():
        kind = getattr(v, "kind", None)
        if kind not in ("correctness", "behavioral"):
            out.append(
                f"relation {getattr(v, 'relation_id', '?')!r} has kind={kind!r}, "
                f"which classify_failures puts in NEITHER bucket -- a failure "
                f"with this kind would vanish silently",
            )
    return out


def check_declared_relation_absent_is_failure(factors, results) -> list[str]:
    """INV-SEM10: every declared relation appears in the verdicts, and an
    unexecuted one is ``passed=False``.

    A typo'd ``native_test`` identifier must not silently disable a correctness
    gate: if nothing ever ran it, the mechanism was never actually verified.

    Takes ``(factors, results)`` -- the inputs -- rather than the verdicts,
    because "was it executed?" is NOT a field on ``RelationVerdict``: the
    condition is encoded as ``passed=False`` plus a detail string. Checking the
    verdicts alone would therefore have to parse prose, which is exactly the
    substring-matching that ``failure_kind`` exists to end. Comparing the
    declared set against the results set is the same question asked where the
    answer is structural.
    """
    from orchestrator.optimize.relations import reconcile, required_relations

    declared = {r["id"]: r["native_test"] for _fid, r in required_relations(factors)}
    verdicts = {v.relation_id: v for v in reconcile(factors, results or {})}
    out: list[str] = []
    for rid, native_test in declared.items():
        v = verdicts.get(rid)
        if v is None:
            out.append(
                f"relation {rid!r} was declared but produced no verdict at all; "
                f"a relation nobody adjudicated cannot have gated anything",
            )
        elif native_test not in (results or {}) and v.passed:
            out.append(
                f"relation {rid!r} declared native_test {native_test!r}, nothing "
                f"ran it, and it is recorded as PASSED; a relation nobody ran "
                f"must never look satisfied",
            )
    return out


# ── statistical ───────────────────────────────────────────────────────────

def check_fit_has_no_nan(fit: Any) -> list[str]:
    """INV-STAT02: no fitted coefficient is NaN (spec 4 D2).

    One NaN response turns EVERY coefficient into NaN while still returning a
    schema-valid ``Fit`` -- verified: ``[0.1875, -0.5625, -0.0625, 0.1875]``
    became ``[nan, nan, nan, nan]`` with nothing raised and nothing logged.

    D2 is fixed at the ``stage_runner`` call site (NaN rows are dropped and
    named in ``fit_exclusions.json``), but ``effects.fit_effects`` itself is
    unchanged: handed a NaN directly it still poisons everything silently. That
    is a defensible division of labour -- the caller owns admissibility -- but
    it means the invariant is enforced at exactly one of the module's callers,
    and the NEXT caller inherits the defect. This checker is the module-boundary
    version, so any site that fits can assert it for free.
    """
    out: list[str] = []
    intercept = getattr(fit, "intercept", 0.0)
    if intercept != intercept:
        out.append("fit intercept is NaN")
    for e in list(getattr(fit, "effects", ()) or ()) + list(getattr(fit, "quadratic", ()) or ()):
        if e.estimate != e.estimate:
            out.append(
                f"fitted coefficient {e.label!r} is NaN; a single NaN response "
                f"poisons every coefficient while returning a schema-valid Fit",
            )
    return out


def check_one_coefficient_per_alias_class(fit: Any) -> list[str]:
    """INV-STAT01: one coefficient per ALIAS CLASS, not per interaction (spec 4 D1).

    ``fit_effects`` used to request one column per two-factor interaction; at
    resolution IV aliased columns COINCIDE, so ``XᵀX`` was singular and every
    tabulated resolution-IV screen crashed at fit (k=5..8, all 16-run designs).
    The fix estimates one coefficient per alias class and records the class.

    Checked by inspecting labels rather than by re-solving the normal equations:
    a duplicate label is exactly the singular-column condition, and the check
    must not become a second, slower copy of the fit.
    """
    labels = [e.label for e in getattr(fit, "effects", ()) or ()]
    dupes = sorted({l for l in labels if labels.count(l) > 1})
    return [
        f"fit carries {labels.count(l)} coefficients labelled {l!r}; aliased "
        f"columns coincide, so one column per interaction makes XtX singular -- "
        f"fit one coefficient per ALIAS CLASS (spec 4 D1)"
        for l in dupes
    ]


def check_bound_nonnegative(bound: Any) -> list[str]:
    """INV-STAT03: a residual-regret bound is never negative.

    ``x_hat`` is the argmax, so every challenger's point estimate is ``<= 0``
    and the true gap to the optimum cannot be below zero. ``None`` is fine --
    that is "not estimable", a different claim.
    """
    v = getattr(bound, "value", None)
    if v is not None and v < 0:
        return [
            f"residual-regret bound is {v!r}; the gap to the true optimum cannot "
            f"be negative, so the bound floors at 0.0",
        ]
    return []


def check_exclusions_recorded(planned: int, fitted: int, exclusions: dict | None) -> list[str]:
    """INV-STAT09: every excluded row is recorded with its index and reason.

    Spec 2.5, minimum information loss: no silent NaN, no infeasible row dropped
    without record. The failure this guards is not the exclusion -- a constrained
    design routinely has inadmissible corners -- it is the exclusion that leaves
    no trace, so a reader cannot tell a 12-row fit from a 12-of-18-row fit.
    """
    if planned == fitted:
        return []
    if not exclusions:
        return [
            f"{planned - fitted} of {planned} rows were excluded from the fit and "
            f"no fit_exclusions.json records which ones or why; the reduced "
            f"resolution is implied rather than visible",
        ]
    out: list[str] = []
    idx = exclusions.get("excluded_row_indices")
    if not idx:
        out.append("fit_exclusions.json names no excluded_row_indices")
    elif len(idx) != planned - fitted:
        out.append(
            f"fit_exclusions.json names {len(idx)} excluded row(s) but the fit "
            f"dropped {planned - fitted}",
        )
    if not exclusions.get("reason"):
        out.append("fit_exclusions.json gives no reason for the exclusions")
    return out


def check_exclusions_independent_of_levels(rows, factor_ids) -> list[str]:
    """INV-STAT08: exclusions are independent of factor levels.

    Historical defect 6: two wall-clock timeouts landed on the SAME corner of
    the factor space (one factor's level) while the other level at that
    identical corner completed -- a perfect 2x2 separation that nothing
    detected. A level-correlated exclusion set is a CONFOUNDED design, not
    merely a reduced one: the fit then attributes the missing rows' absence to
    the factor.

    ``rows`` are ``(levels, excluded[, bias_relevant])`` triples, the shape
    ``exclusions.analyse`` takes. Delegates to
    ``orchestrator.optimize.exclusions``, which owns the hypergeometric tail and
    the identifiability floors: the registry's job is to name the invariant and
    bind it to the document, not to keep a second copy of the statistics that
    could disagree with the shipped one.

    Reports both shapes the module distinguishes, because they are different
    findings: a FLAGGED FACTOR means every exclusion landed on one level of it,
    and a CELL HOLE means a whole design cell was lost while a sibling differing
    in exactly one factor completed -- which is defect 6's own 2x2 signature.
    """
    from orchestrator.optimize import exclusions as ex

    balance = ex.analyse(rows, factor_ids)
    out: list[str] = []
    for imb in getattr(balance, "factors", ()) or ():
        if getattr(imb, "flagged", False):
            out.append(
                f"exclusions are correlated with factor {imb.factor_id!r} "
                f"(every bias-relevant exclusion at level "
                f"{imb.concentrated_at!r}, p={imb.concentration_p}): a "
                f"level-correlated exclusion set confounds the design rather "
                f"than reducing it (historical defect 6)",
            )
    for hole in getattr(balance, "cells", ()) or ():
        out.append(
            f"design cell {hole.levels} was entirely excluded while sibling "
            f"{hole.sibling_levels} completed, differing only in "
            f"{hole.differs_from_sibling_in!r}: the 2x2 separation of defect 6",
        )
    return out


def check_fit_coordinates_are_actual(fit_coordinates: dict, levels_rows,
                                     factors) -> list[str]:
    """INV-STAT14: the fit's design matrix is the coded ACTUAL levels.

    ``fit_coordinates`` is ``effects.json["fit_coordinates"]``; ``levels_rows``
    the levels that ran for each fitted row, in the same order; ``factors``
    the parsed factors. Every fitted coordinate must equal
    ``factors.code_actual`` of the level that ran -- the clamped axial point at
    the range edge it ran at, a choice factor's centre row at the level it ran.
    """
    from orchestrator.optimize.factors import code_actual

    out: list[str] = []
    if (fit_coordinates or {}).get("basis") != "coded_actual_levels":
        return [f"fit_coordinates.basis is {(fit_coordinates or {}).get('basis')!r}, "
                f"not 'coded_actual_levels'"]
    by_id = {f.id: f for f in factors}
    ids = list(fit_coordinates.get("factor_ids") or [])
    rows = list(fit_coordinates.get("rows") or [])
    owner = list(fit_coordinates.get("factor_of_column") or [])
    if owner:
        # Mixed-level fit: column j is contrast number (j - first column of its
        # factor) of factor owner[j], coded by factors.code_vector.
        from orchestrator.optimize.factors import code_vector

        first = {}
        for j, g in enumerate(owner):
            first.setdefault(g, j)
        if len(rows) != len(levels_rows):
            return [f"{len(rows)} fitted row(s) recorded but {len(levels_rows)} level row(s) given"]
        for i, (row, lv) in enumerate(zip(rows, levels_rows)):
            for j, (cid, g) in enumerate(zip(ids, owner)):
                want = code_vector(by_id[g], lv[g])[j - first[g]]
                got = row["fitted"][j]
                if abs(float(got) - want) > 1e-9:
                    out.append(
                        f"fitted row {i} column {cid!r} of factor {g!r}: coded {got} "
                        f"but the level that ran ({lv[g]!r}) codes {want}")
        return out
    if len(rows) != len(levels_rows):
        return [f"{len(rows)} fitted row(s) recorded but {len(levels_rows)} level row(s) given"]
    for i, (row, lv) in enumerate(zip(rows, levels_rows)):
        for j, fid in enumerate(ids):
            want = code_actual(by_id[fid], lv[fid])
            got = row["fitted"][j]
            if abs(float(got) - want) > 1e-9:
                out.append(
                    f"fitted row {i} factor {fid!r}: coded {got} but the level that "
                    f"ran ({lv[fid]!r}) codes {want} -- the fit regressed on a "
                    f"coordinate that was never run",
                )
    return out


#: Statuses whose primary may enter the primary fit (INV-STAT15).
_FITTABLE_STATUSES = frozenset({"complete", "infeasible"})


def check_fitted_statuses(fit_coordinates: dict) -> list[str]:
    """INV-STAT15: only ``complete`` and ``infeasible`` rows inform the primary fit.

    An ``infeasible`` row is a valid measurement of an inadmissible
    configuration and IS fitted; ``rejected`` (invariant / ceiling / integrity)
    and ``failed`` (incl. a self_check violation) are not trustworthy
    measurements and never are.
    """
    out: list[str] = []
    for i, row in enumerate((fit_coordinates or {}).get("rows") or []):
        st = row.get("status")
        if st is not None and st not in _FITTABLE_STATUSES:
            out.append(f"fitted row {i} has status {st!r}, which must never be fitted")
    return out


def check_supported_feasible_candidate(recommendation: dict) -> list[str]:
    """INV-STAT16: the recorded supported-feasible candidate satisfies its rule.

    Read from ``recommendation.json`` alone: every modelled constraint's verdict
    is ``feasible`` with its satisfying-side bound inside the threshold, every
    unmodelled one is ``inside_admissible_region`` and the levels (and every
    pool member's) lie inside the recorded ``admissible_region``, the candidate
    heads its pool, and it was never measured inadmissible. Vacuous when the
    record is absent (no constraints declared) or names no candidate.
    """
    from orchestrator.optimize.constraint_models import in_admissible_region

    sf = (recommendation or {}).get("supported_feasible_candidate")
    if not sf or sf.get("levels") is None:
        return []
    out: list[str] = []
    levels = sf["levels"]
    region = sf.get("admissible_region")
    unmodelled = False
    for v in sf.get("constraint_verdicts") or []:
        if not v.get("modelled"):
            unmodelled = True
            if v.get("verdict") != "inside_admissible_region":
                out.append(f"unmodelled {v.get('metric')!r} verdict {v.get('verdict')!r}")
            continue
        if v.get("verdict") != "feasible":
            out.append(f"modelled {v.get('metric')!r} verdict {v.get('verdict')!r}, "
                       f"not confidently feasible")
            continue
        op, val = v.get("op"), float(v.get("value"))
        ok = {"<=": v["upper"] <= val, "<": v["upper"] < val,
              ">=": v["lower"] >= val, ">": v["lower"] > val}.get(op, False)
        if not ok:
            out.append(f"modelled {v.get('metric')!r}: the satisfying-side bound "
                       f"is not inside {op} {val}")
    if unmodelled:
        for lv in [levels] + [p.get("levels") for p in sf.get("pool") or []]:
            if not in_admissible_region(lv or {}, region or {}):
                out.append(f"{lv} lies outside the measured-admissible region")
    pool = sf.get("pool") or []
    if not pool or pool[0].get("levels") != levels:
        out.append("the supported-feasible candidate does not head its pool")
    if any(lv == levels for lv in recommendation.get("excluded_measured_infeasible") or []):
        out.append(f"{levels} was already measured inadmissible")
    return out


def check_recommendation_avoids_lost_levels(recommendation: dict, report: dict | None = None,
                                            confirmation: dict | None = None) -> list[str]:
    """INV-SEM19: the recommendation never names a categorical level the fit
    could not speak for -- LOST (no retained row) or INADMISSIBLE wherever it
    was measured (stage-1b N7). Matches the LEVEL, not a whole configuration,
    so an interior configuration at a lost level is caught too. Checked on the
    recommended levels and on every top candidate."""
    bad = {}
    # Fully-barred factors (lost ∪ inadmissible = every level): only their
    # LOST levels are barred (stage-1d Q2).
    every = set((recommendation or {}).get("all_levels_inadmissible") or ())
    for key in ("lost_levels", "inadmissible_levels"):
        for fid, lvs in ((recommendation or {}).get(key) or {}).items():
            if key == "inadmissible_levels" and fid in every:
                continue        # recorded, deliberately not excluded (N8)
            bad.setdefault(fid, []).extend(lvs)
    if not bad:
        return []
    out: list[str] = []
    rows = [recommendation.get("levels") or {}] + [
        c.get("levels") or {} for c in recommendation.get("top_candidates") or []]
    # The SAME rule wherever a configuration is recommended (stage-1c P1): the
    # report's recommendation and every confirm finalist.
    rows += [((report or {}).get("recommendation") or {}).get("levels") or {}]
    rows += [f.get("levels") or {} for f in (confirmation or {}).get("finalists") or []]
    # The author-declared known_valid_baseline is exempt (stage-1d Q4).
    base = (report or {}).get("known_valid_baseline")
    if base:
        rows = [r for r in rows if r != base]
    for lv in rows:
        for fid, lvs in bad.items():
            if fid in lv and lv[fid] in lvs:
                out.append(f"{fid}={lv[fid]!r} is lost or inadmissible but is "
                           f"recommended/ranked in {lv}")
    return out


# ── temporal / provenance ─────────────────────────────────────────────────

def check_pareto_front(pareto_block: dict) -> list[str]:
    """INV-STAT17: the reported measured front is internally consistent.

    From the ``pareto`` block of ``confirmation.json`` / ``report.json`` alone:
    no front point is eps-dominated IN POINT ESTIMATE by another front point
    (membership rule, per-objective epsilon honoured), a
    ``confidently_nondominated`` point names no possible dominator and a
    ``possibly_dominated`` one names at least one, the front is sorted
    best-first by the first objective, and the normalised hypervolume lies in
    [0, 1]. Vacuous for an absent block (single-objective).
    """
    par = pareto_block or {}
    if not par:
        return []
    out: list[str] = []
    objs = par.get("objectives") or []
    eps = par.get("epsilon") or {}
    front = par.get("front") or []

    def vec(f):
        return [(-1.0 if o["direction"] == "minimize" else 1.0) * f["mean"][o["metric"]]
                for o in objs]
    e = [eps.get(o["metric"]) for o in objs]  # None = unknown, resolves nothing
    for i, a in enumerate(front):
        for j, b in enumerate(front):
            if i != j and all(x >= y for x, y in zip(vec(b), vec(a))) and any(
                    ek is not None and x - y > ek for x, y, ek in zip(vec(b), vec(a), e)):
                out.append(f"front point {i} {a['levels']} is eps-dominated in point "
                           f"estimate by front point {j} {b['levels']}")
        if a.get("status") == "confidently_nondominated" and a.get("dominated_by"):
            out.append(f"front point {i} is confidently_nondominated but names "
                       f"possible dominators")
        if a.get("status") == "possibly_dominated" and not a.get("dominated_by"):
            out.append(f"front point {i} is possibly_dominated but names no rival")
    if objs and front:
        first = [vec(f)[0] for f in front]
        if first != sorted(first, reverse=True):
            out.append("the front is not sorted best-first by the first objective")
    hv = (par.get("hypervolume") or {}).get("value")
    n_conf = sum(1 for f in front if f.get("status") == "confidently_nondominated")
    if hv is None and n_conf:
        out.append(f"hypervolume is null although {n_conf} point(s) are confident")
    if hv is None and not (par.get("hypervolume") or {}).get("reason"):
        out.append("a null hypervolume carries no reason")
    if hv is not None and (par.get("hypervolume") or {}).get("normalized") and not (
            -1e-12 <= hv <= 1.0 + 1e-9):
        out.append(f"normalised hypervolume {hv} is outside [0, 1]")
    return out


def check_candidate_space(rec: dict, report: dict | None = None) -> list[str]:
    """INV-STAT18: a searched candidate space is recorded honestly.

    From ``recommendation.json``, and -- given ``report``, the ``report.json``
    whose ``residual_regret_model`` was copied from ``rec`` -- that the report
    carries the same ``candidate_space`` exactly when ``rec`` does. Vacuous when ``candidate_space`` is
    absent (the space was enumerated). When present: ``exhaustive`` is false,
    ``method`` is the search, the full ``size`` exceeds ``decide.CANDIDATE_CAP``
    (a space under the cap must be enumerated), ``evaluated`` is at most
    ``size`` and at least the number of ``top_candidates``, the model
    regret bound's ``detail`` says it was not taken over all of X_valid,
    ``alias_consequential_basis`` is ``"searched"``, a predicted front carries
    ``predicted_front_basis: "evaluated_points"``, every modelled
    constraint's ``applied`` agrees with ``constraint_models_applied``, no
    constraint ``reason`` claims "every candidate" (only enumeration can), and
    an ``alias_assessment`` accounts for every alias reading (assessed or
    listed unassessed).
    """
    from orchestrator.optimize.decide import CANDIDATE_CAP

    out: list[str] = []
    cs = (rec or {}).get("candidate_space")
    if report is not None and (report or {}).get("candidate_space") != cs:
        out.append("report.json's candidate_space does not match the recommendation's "
                   f"({(report or {}).get('candidate_space')!r} vs {cs!r}): the searched "
                   "caveat must travel with the model bound")
    if cs is None:
        return out
    if cs.get("exhaustive") is not False:
        out.append("candidate_space is present but does not say exhaustive: false")
    if cs.get("method") != "sampled_coordinate_ascent":
        out.append(f"candidate_space.method is {cs.get('method')!r}, not the search")
    size, ev = cs.get("size"), cs.get("evaluated")
    if not isinstance(size, int) or size <= CANDIDATE_CAP:
        out.append(f"a space of size {size!r} (cap {CANDIDATE_CAP}) must be enumerated, "
                   f"not searched")
    if not isinstance(ev, int) or (isinstance(size, int) and ev > size):
        out.append(f"evaluated={ev!r} exceeds the space size {size!r}")
    elif ev < len(rec.get("top_candidates") or []):
        out.append(f"evaluated={ev} is fewer than the {len(rec['top_candidates'])} "
                   f"top_candidates")
    detail = str((rec.get("residual_regret_model") or {}).get("detail") or "")
    if "NOT over all of X_valid" not in detail:
        out.append("residual_regret_model.detail does not say the bound was taken over "
                   "the evaluated set only")
    aa = rec.get("alias_assessment")
    if aa is not None and aa.get("readings") != (aa.get("assessed") or 0) + len(
            aa.get("unassessed") or []):
        out.append(f"alias_assessment does not account for every reading: {aa!r}")
    if rec.get("alias_consequential_basis") != "searched":
        out.append("alias_consequential is not marked alias_consequential_basis: "
                   "'searched'")
    if "predicted_front" in rec and rec.get("predicted_front_basis") != "evaluated_points":
        out.append("predicted_front statuses are not marked predicted_front_basis: "
                   "'evaluated_points'")
    applied = cs.get("constraint_models_applied")
    for e in rec.get("constraint_models") or []:
        if e.get("modelled") and applied is not None and bool(e.get("applied")) != applied:
            out.append(f"constraint {e.get('metric')!r} says applied={e.get('applied')} "
                       f"but candidate_space.constraint_models_applied={applied}")
        if "every candidate" in str(e.get("reason") or ""):
            out.append(f"constraint {e.get('metric')!r}'s reason claims EVERY candidate "
                       f"of a searched space; only the evaluated set is known")
    return out


def check_pareto_certificate(certifying: dict) -> list[str]:
    """INV-SEM18: a multi-objective certificate rests on the front.

    ``certifying`` is a ``confirmation.json`` or ``report.json``. When it
    carries a ``pareto`` block and ``certified`` is true, the preferred point is
    a front member, is ``confidently_nondominated`` at the CERTIFICATION level
    (delta_terminal / max_rounds), and the preference scalarisation's regret
    bound is known and within its epsilon; a report's recommendation names that
    point. Vacuous otherwise.
    """
    doc = certifying or {}
    par = doc.get("pareto")
    if not par or not doc.get("certified"):
        return []
    out: list[str] = []
    pref = par.get("preference") or {}
    chosen = pref.get("chosen") or {}
    if not any(dict(f.get("levels") or {}) == dict(chosen) for f in par.get("front") or []):
        out.append(f"certified preferred point {chosen} is not on the measured front")
    if pref.get("chosen_status_at_certification") != "confidently_nondominated":
        out.append("certified although the preferred point is not confidently "
                   "nondominated at the certification level")
    reg, eps = pref.get("scalar_regret"), pref.get("scalar_epsilon")
    if reg is None or eps is None or reg > eps:
        out.append(f"certified with scalar regret {reg!r} vs epsilon {eps!r}")
    rec = (doc.get("recommendation") or {}).get("levels")
    if rec is not None and dict(rec) != dict(chosen):
        out.append(f"report recommends {rec}, not the certified preferred point {chosen}")
    return out


def check_gap_fill_branch(policy: dict) -> list[str]:
    """INV-VOC09: ``front_gap_large`` is read only by the registered gap-fill
    branch -- ``confirm -> confirm``, accounting ``FRONT_GAP_ACCOUNTING``,
    guarded by the round cap and affordability -- and only in a policy that
    registers objectives."""
    from orchestrator.optimize.policy import FRONT_GAP_ACCOUNTING

    pol = policy or {}
    out: list[str] = []
    mo = bool((pol.get("objective") or {}).get("objectives"))
    cap = (((pol.get("states") or {}).get("confirm") or {}).get("design") or {}).get(
        "max_rounds")
    for t in pol.get("transitions") or []:
        when = t.get("when") or {}
        if "front_gap_large" not in when:
            continue
        where = f"{t.get('from')}->{t.get('to')}"
        if not mo:
            out.append(f"{where} reads front_gap_large in a single-objective policy")
        if (t.get("from"), t.get("to")) != ("confirm", "confirm"):
            out.append(f"{where}: the gap-fill branch must be confirm -> confirm")
        if t.get("accounting") != FRONT_GAP_ACCOUNTING:
            out.append(f"{where}: accounting {t.get('accounting')!r}, not "
                       f"{FRONT_GAP_ACCOUNTING!r}")
        if when.get("round") != {"<": cap} or when.get("confirm_affordable") is not True:
            out.append(f"{where}: not guarded by the round cap and affordability")
    return out


def check_refill_branch(policy: dict) -> list[str]:
    """INV-VOC10: ``finalists_vacated`` / ``feasible_finalists`` /
    ``refill_available`` are read only by the registered refill branch --
    ``confirm -> confirm``, accounting ``REFILL_ACCOUNTING``, guarded by the
    round cap, affordability and ``refill_available`` -- registered only when
    constraints exist (``response.constraints``), and ordered BEFORE
    certification and every decline guard out of ``confirm``."""
    from orchestrator.optimize.policy import REFILL_ACCOUNTING

    pol = policy or {}
    keys = {"finalists_vacated", "feasible_finalists", "refill_available"}
    out: list[str] = []
    cap = (((pol.get("states") or {}).get("confirm") or {}).get("design") or {}).get(
        "max_rounds")
    confirm_rules = [t for t in pol.get("transitions") or []
                     if t.get("from") == "confirm" and "when" in t]
    for i, t in enumerate(confirm_rules):
        when = t.get("when") or {}
        if not keys & set(when):
            continue
        where = f"{t.get('from')}->{t.get('to')}"
        if t.get("to") != "confirm" or t.get("accounting") != REFILL_ACCOUNTING:
            out.append(f"{where}: refill observations read outside the refill branch")
        if when.get("refill_available") is not True or when.get(
                "confirm_affordable") is not True or when.get("round") != {">=": cap}:
            out.append(f"{where}: refill not guarded by availability, affordability "
                       f"and the round cap")
        later_decl = [r for r in confirm_rules[:i]
                      if r.get("to") == "report" or "certified" in (r.get("when") or {})]
        if later_decl:
            out.append(f"{where}: registered after a certification/decline rule")
    return out


def check_single_objective_untouched(policy: dict, report: dict | None = None) -> list[str]:
    """INV-ST11: a single-objective campaign carries no multi-objective
    vocabulary -- no ``objective.objectives``, no ``front_gap_large`` guard, no
    ``pareto`` block in its report. The structural half of the metamorphic
    byte-identity property."""
    pol = policy or {}
    if (pol.get("objective") or {}).get("objectives"):
        return []
    out: list[str] = []
    if any("front_gap_large" in (t.get("when") or {}) for t in pol.get("transitions") or []):
        out.append("single-objective policy registers a front_gap_large guard")
    if report and "pareto" in report:
        out.append("single-objective report.json carries a pareto block")
    return out


def check_preregistration_precedes_measurement(work_dir: Path) -> list[str]:
    """INV-TMP01: policy.json + policy.sha256 exist before the first row.

    That ordering IS the pre-registration: a policy hash written before the
    first benchmark run means every subsequent branch was fixed before any
    result was seen. Checked at the OBSERVATION boundary (``execute_design``
    entry) rather than by comparing mtimes, because an mtime comparison is a
    post-hoc reading of a property that must be true PROSPECTIVELY -- and
    because a resumed work-dir legitimately has older rows than a recompiled
    policy.
    """
    work_dir = Path(work_dir)
    out: list[str] = []
    for name in ("policy.json", "policy.sha256"):
        if not (work_dir / name).exists():
            out.append(
                f"{name} is absent at the observation boundary; a benchmark row "
                f"measured before the pre-registration exists is not covered by "
                f"one",
            )
    return out


def check_provenance_pair(work_dir: Path, *, doc: str, sidecar: str,
                          hasher: Callable[[dict], str]) -> list[str]:
    """INV-PROV01/03: a document and its hash sidecar must BOTH exist and agree.

    ABSENCE IS AS FATAL AS DISAGREEMENT, and that is not how the shipped guard
    reads. ``_load_or_compile_policy`` guards with ``if recorded.exists() and
    ...``, so DELETING ``policy.sha256`` disables the check entirely rather than
    failing closed. Verified end to end: with the sidecar deleted and screen's
    ``default: confirm`` rewritten to ``default: report``, the epoch ran to a
    ``report.json`` claiming ``basis: model`` with terminal discrimination
    silently skipped, no ``confirmation.json``, and no sidecar regenerated
    (``_compile_and_write_policy`` is reached only when ``pol is None``). The
    tampered hash was then recorded in ``transitions.jsonl`` as though it were
    the registration.

    A pre-registration whose only proof of integrity can be removed by deleting
    a file is not a pre-registration. So this checker requires the pair, which
    is the form the invariant should always have had.
    """
    work_dir = Path(work_dir)
    dpath, spath = work_dir / doc, work_dir / sidecar
    if not dpath.exists():
        return []          # nothing registered yet is a different state, not a violation
    if not spath.exists():
        return [
            f"{doc} exists with no {sidecar}: the sidecar's ABSENCE must be as "
            f"fatal as its disagreement, or the integrity proof can be removed "
            f"by deleting a file",
        ]
    try:
        recorded, actual = spath.read_text().strip(), hasher(json.loads(dpath.read_text()))
    except (OSError, ValueError) as exc:
        return [f"{doc}/{sidecar} could not be compared: {exc}"]
    if recorded != actual:
        return [
            f"{doc} does not match {sidecar} (recorded {recorded[:16]}..., actual "
            f"{actual[:16]}...): a pre-registered artifact cannot change inside "
            f"an epoch",
        ]
    return []


def check_policy_provenance(work_dir: Path) -> list[str]:
    """INV-PROV01: delegates to ``policy.verify_policy_registration``.

    One implementation, two callers, deliberately: the registry must not carry a
    second copy of the check that could certify a work-dir the production seam
    refuses (or the reverse). ``policy.py`` owns the arithmetic because that is
    where ``policy_hash`` lives; this entry owns the ID, the classification, and
    the binding to the inventory document.
    """
    from orchestrator.optimize.policy import verify_policy_registration

    return verify_policy_registration(work_dir)


def check_transitions_epoch_scoped(rows: list[dict]) -> list[str]:
    """INV-TMP02/INV-PROV04: every transition row carries ``epoch`` and ``policy_hash``.

    ``transitions.jsonl`` is append-only ACROSS epochs -- that is the point, it
    is the audit trail. Without the per-row ``epoch`` a recompiled epoch reads
    its predecessor's rows as its own and resumes at the terminal ``exception``
    it was recompiled to escape. Without ``policy_hash``, "which policy
    scheduled this design?" stops being answerable for any epoch but the
    current one.
    """
    out: list[str] = []
    for i, r in enumerate(rows or ()):
        if "policy_hash" not in r:
            out.append(
                f"transitions.jsonl row {i} carries no policy_hash; the epoch's "
                f"registration is unrecoverable once the policy is recompiled",
            )
        if "epoch" not in r:
            out.append(
                f"transitions.jsonl row {i} carries no epoch; a recompiled epoch "
                f"would read this row as its own",
            )
    return out


def check_audit_trail_records_spending(work_dir: Path) -> list[str]:
    """INV-TMP08: an epoch that spent benchmark runs left a record of why it ended.

    HISTORICAL DEFECT 7, and this checker exists because the violation is that
    the inline seam is never reached. ``transitions.jsonl`` was completely EMPTY
    after 14 hours, because every iteration aborted before the fit and the
    transition write lives in the iteration closer (``_close_iteration``). Every
    ``OptimizationAborted`` raised upstream of that closer unwinds past the only
    site that appends to the audit trail.

    The trigger is LOWER than the design document's prose implies. Empirically
    reproduced: the gate is ``_fitting_responses``' "N of M runs produced no
    usable measurement", which fires on ONE failed row out of twelve -- not on
    the ``len(keep) < 2`` abort. Measured: five iterations, 60 benchmark runs
    spent, ``transitions.jsonl`` never created, no ``epoch_end-*.json``, no
    ``report.json``. A single transient benchmark crash per iteration is enough
    to produce the 14-hour silence.

    ``AUDIT``-class: it can only be checked from a finished work-dir, because
    inline it would need a seam the abort path skips by construction.
    """
    work_dir = Path(work_dir)
    rows_spent = sum(
        1
        for p in work_dir.glob("runs/iter-*/runs.jsonl")
        for line in p.read_text().splitlines()
        if line.strip()
    )
    if not rows_spent:
        return []
    trans = work_dir / "transitions.jsonl"
    if not trans.exists() or not trans.read_text().strip():
        return [
            f"{rows_spent} benchmark row(s) were measured and transitions.jsonl "
            f"is empty or absent. The audit trail records nothing about why the "
            f"epoch ended -- every abort upstream of _close_iteration unwinds "
            f"past the only writer (historical defect 7)",
        ]
    return []


# ── resource / economic ───────────────────────────────────────────────────

def check_duration_reserved_zero(outcome: Any) -> list[str]:
    """INV-RES06: ``duration_ms`` is positive on a row that ran; 0 means "did not run".

    Declared, schema-valid, and structurally ALWAYS 0 -- never assigned at any
    of nine ``RunOutcome`` construction sites (historical defect 3). Now floored
    at 1ms precisely so ``0`` stays reserved for "did not run", which is what
    keeps the absent-field case detectable forever rather than indistinguishable
    from a fast row. A row that TIMED OUT must record the time it consumed:
    that is exactly the number a timeout budget has to cover, and a field
    reading 0 there advertised "measured, instantaneous" about the one outcome
    whose duration mattered most.
    """
    d = getattr(outcome, "duration_ms", None)
    out: list[str] = []
    if d is None:
        return ["RunOutcome carries no duration_ms"]
    if d < 0:
        out.append(
            f"duration_ms is {d!r}; it is monotonic-clock derived, so it can "
            f"never be negative and never moves under a wall-clock adjustment",
        )
    if d == 0:
        out.append(
            "duration_ms is 0 on a constructed outcome; 0 is RESERVED for 'did "
            "not run', and a row that ran (including a timed-out one) floors at 1ms",
        )
    last = getattr(outcome, "last_attempt_ms", 0) or 0
    if last > d:
        out.append(
            f"last_attempt_ms ({last}) exceeds duration_ms ({d}), which is the "
            f"total across every attempt",
        )
    return out


def check_no_model_call_reachable_from_epoch() -> list[str]:
    """INV-ECO01: zero model calls inside a compiled epoch state.

    CLAUDE.md calls this "the single most important invariant in the kind" --
    it is what makes the token table (0 calls without ``build``, 1 with it) true
    rather than aspirational. A semantic exception ends the epoch instead of
    improvising, precisely so no state ever needs a model "just to interpret a
    result".

    Checked STATICALLY, by import graph: the only dispatcher imports anywhere in
    the package must be function-local inside ``plan.run_plan`` and
    ``build.run_build`` — the two PRE-EPOCH stages, both opt-in, both of which run
    before the first measurement and neither of which is a state the compiled
    policy can route to. The epoch itself stays at zero calls, which is what the
    invariant protects; adding a pre-epoch stage moves the substantive-call count
    (0 without them, 1 with ``build``, 2 with ``plan`` as well) and does not touch
    this invariant. A dynamic tripwire complements this in the
    test suite (verified live, with a negative control that fires when ``build``
    is declared), but the static form is what can run always and cheaply.
    """
    pkg = Path(__file__).resolve().parent
    needles = (
        "sdk_dispatch", "cli_dispatch", "llm_dispatch", "claude_agent_sdk",
        "orchestrator.dispatch",
    )
    out: list[str] = []
    for path in sorted(pkg.glob("*.py")):
        if path.name in ("invariants.py", "plan.py", "build.py"):
            # `plan` and `build` ARE the substantive calls, and both are pre-epoch:
            # `step()` can never route to either, so neither is reachable FROM an
            # epoch state. This file names them, which is why it is skipped too.
            continue
        text = path.read_text()
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if not s.startswith(("import ", "from ")):
                continue
            if any(n in s for n in needles):
                out.append(
                    f"{path.name}:{i} imports a model dispatcher ({s!r}). No "
                    f"model call may be reachable from a compiled epoch state, "
                    f"for any reason including 'just to interpret a result'",
                )
    return out


def check_compile_policy_is_pure(campaign: dict) -> list[str]:
    """INV-ECO02: ``compile_policy`` is a pure function of the campaign.

    Zero tokens, no measurement read, same input -> same hash. This is what
    makes ``T_compile = 0`` true and what makes the hash a pre-registration
    rather than a description of a run.
    """
    from orchestrator.optimize.policy import compile_policy, policy_hash

    a, b = compile_policy(campaign), compile_policy(campaign)
    if policy_hash(a) != policy_hash(b):
        return [
            "compile_policy returned two different hashes for one campaign; a "
            "policy that is not a pure function of the campaign cannot be a "
            "pre-registration",
        ]
    return []


# ══════════════════════════════════════════════════════════════════════════
#  THE REGISTRY
#
#  Every ID here appears in docs/optimization-invariants.md and vice versa;
#  tests/test_optimize_invariants.py fails on either direction of drift.
# ══════════════════════════════════════════════════════════════════════════

_ENTRIES: tuple[Invariant, ...] = (
    # ── structural ────────────────────────────────────────────────────────
    Invariant("INV-ST01", "Every non-terminal policy state has a default transition.",
              "ST", "artifact", "policy.check_policy; spec 3.1", ALWAYS,
              check_policy_structure),
    Invariant("INV-ST02", "Every transition's from and to/default names a declared state.",
              "ST", "artifact", "policy.check_policy", ALWAYS, check_policy_structure),
    Invariant("INV-ST03", "The initial state is declared AND is a spending state.",
              "ST", "artifact", "policy.check_policy", ALWAYS, check_policy_structure),
    Invariant("INV-ST04", "Every spending state can reach exception when exception exists.",
              "ST", "artifact", "policy.check_policy", ALWAYS, check_policy_structure),
    Invariant("INV-ST05", "No `when` clause is empty; an empty guard fires unconditionally "
                          "and shadows every later rule for the same from-state.",
              "ST", "artifact", "policy.py empty-guard check", ALWAYS,
              check_policy_structure),
    Invariant("INV-ST06", "A `when` predicate dict carries exactly one operator per key.",
              "ST", "artifact", "policy.check_policy", ALWAYS, check_policy_structure),
    Invariant("INV-ST07", "response and held_out are a structural split: no held-out metric "
                          "appears in response, so response is fitting-safe by construction.",
              "ST", "function", "runner.RunOutcome docstring", ALWAYS, check_held_out_split),
    Invariant("INV-ST08", "A non-complete RunOutcome carries a non-empty failure_kind; a "
                          "complete row carries the empty string.",
              "ST", "function", "runner.RunOutcome.failure_kind", ALWAYS,
              check_failure_kind_agrees_with_status,
              note="An earlier framing of this claimed failed rows carried no cause at "
                   "all. That was WRONG -- `error` was always populated and written. The "
                   "real gap was narrower: a timeout and a crash both surfaced as "
                   "`RuntimeError: config run ...`, so telling them apart meant "
                   "substring-matching prose the raise site is free to reword."),
    Invariant("INV-ST09", "report.json always carries a recommendation.basis, one of the "
                          "six declared values.",
              "ST", "artifact", "stage_runner._run_report ladder; CLAUDE.md", ALWAYS,
              check_report_bounds_separate),
    Invariant("INV-ST10", "Every field the producer writes is declared by the consumer's "
                          "schema, verified against a row from the REAL code path.",
              "ST", "artifact", "runs_row.schema.json additionalProperties:false vs _run_row",
              ALWAYS, check_schema_declares_written_fields,
              violated_by="runs_row.schema.json was additionalProperties:false while "
                          "_run_row always wrote held_out/manipulation/invariants, so every "
                          "real row on disk was schema-invalid; the existing test validated "
                          "only hand-written dicts"),

    Invariant("INV-ST11", "A single-objective campaign carries no multi-objective "
                          "vocabulary: no objective.objectives in its policy, no "
                          "front_gap_large guard, no pareto block in report.json.",
              "ST", "artifact", "pareto_stage gating on pareto.policy_objectives; spec "
              "2026-10-15 'single-objective campaigns are byte-identical'", TEST,
              check_single_objective_untouched,
              note="The structural half of the metamorphic byte-identity oracle; the "
                   "full half diffs every artifact of every SURFACES campaign against "
                   "the pre-Pareto commit (see the spec's Decisions)."),

    # ── closed vocabulary ─────────────────────────────────────────────────
    Invariant("INV-VOC01", "Every `when` clause's observation key is in OBSERVATION_KEYS.",
              "VOC", "artifact", "policy.check_policy; spec 3.2", ALWAYS,
              check_policy_structure),
    Invariant("INV-VOC02", "Every `when` operator is in COMPARISON_OPS (>, >=, <, <=) -- "
                           "deliberately narrower than predicates.OPS, which also has ==/!=.",
              "VOC", "artifact", "policy.COMPARISON_OPS docstring; spec 3.2", ALWAYS,
              check_policy_structure),
    Invariant("INV-VOC03", "COMPARISON_OPS is a subset of predicates.OPS: a policy "
                           "check_policy refuses must not be one step() can still drive.",
              "VOC", "module", "policy.py comment above the _OP_FUNCS import", ALWAYS,
              check_comparison_ops_subset),
    Invariant("INV-VOC04", "Every OBSERVATION_KEYS member has a named consumer: a registered "
                           "transition, an artifact field, or a documented non-branching note.",
              "VOC", "module", "policy.OBSERVATION_KEYS docstring", TEST,
              check_observation_keys_consumed,
              violated_by="runs_needed_confirm was dead vocabulary for six tasks: its "
                          "producing comment claimed a compiled guard that did not exist"),
    Invariant("INV-VOC05", "FAILURE_KINDS and the runs_row.schema.json enum are the same set.",
              "VOC", "module", "runner.FAILURE_KINDS docstring", ALWAYS,
              check_failure_kind_agrees_with_status),
    Invariant("INV-VOC06", "Every RunOutcome.status is complete/failed/infeasible/rejected.",
              "VOC", "function", "runner.RunOutcome.status; spec 6.4", ALWAYS,
              check_failure_kind_agrees_with_status),
    Invariant("INV-VOC07", "behavioral_violation is in OBSERVATION_KEYS and is read by NO "
                           "`when` clause -- a reporting key, deliberately non-branching.",
              "VOC", "artifact", "policy.py behavioral_violation note; stage.decide_after_screen",
              ALWAYS, check_observation_keys_consumed),
    Invariant("INV-VOC08", "A closed vocabulary's producers and consumers agree: no consumer "
                           "compares against a value no producer can emit, and no produced "
                           "value falls through every consumer.",
              "VOC", "module",
              "the n_excluded == \"excluded\" regression in _finish_confirm", ALWAYS,
              check_vocabulary_produced_equals_consumed,
              violated_by="the finalist-status vocabulary was split from \"excluded\" into "
                          "\"infeasible\"/\"unmeasured\" while the consumer still compared "
                          "the retired literal; n_excluded silently became 0, nothing "
                          "withheld certification, the registered confirm->confirm top-up "
                          "never fired, and the sla surface CERTIFIED an answer 6.12% off "
                          "the true constrained optimum. Only the synthetic oracle caught it."),

    Invariant("INV-VOC09", "front_gap_large is read only by the registered gap-fill "
                           "branch (confirm -> confirm, accounting 'front gap fill, "
                           "Bonferroni over rounds', guarded by the round cap and "
                           "confirm_affordable), and only in a multi-objective policy.",
              "VOC", "artifact", "policy.FRONT_GAP_ACCOUNTING; compile_policy", TEST,
              check_gap_fill_branch),

    Invariant("INV-VOC10", "finalists_vacated, feasible_finalists and refill_available "
                           "are read only by the registered refill branch (confirm -> "
                           "confirm, accounting 'refill vacated seats', guarded by "
                           "refill_available, confirm_affordable and the round cap), "
                           "registered before certification and every decline guard.",
              "VOC", "artifact", "policy.REFILL_ACCOUNTING; compile_policy", TEST,
              check_refill_branch,
              violated_by="a real Go campaign: 2 of 3 finalists measured infeasible at "
                          "the round cap, R_terminal = 0 over no feasible rival, two "
                          "thirds of confirm's budget spent and never refilled"),

    # ── semantic / accounting ─────────────────────────────────────────────
    Invariant("INV-SEM01", "residual_regret_model and residual_regret_terminal are separate "
                           "fields and are never collapsed: Pr(wrong global decision) <= "
                           "delta_s + delta_t is only meaningful while they stay apart.",
              "SEM", "artifact", "certificate.py docstring; spec 3.5; CLAUDE.md", ALWAYS,
              check_report_bounds_separate),
    Invariant("INV-SEM02", "A null bound means 'not estimable'. An unknown is never reported "
                           "as a zero.",
              "SEM", "artifact", "certificate.py 'an unknown is not a zero'; spec 3.5",
              ALWAYS, check_bound_unknown_is_not_zero, open_violation=False,
              violated_by="terminal_regret_bound returns value=0.0 with "
                          "method='bonferroni_one_sided_t_paired' on bit-identical "
                          "replicates -- a claim of exact epsilon-optimality from zero "
                          "information. Its sibling model_regret_bound correctly returns "
                          "None when pure_error_df <= 0."),
    Invariant("INV-SEM03", "delta_s and delta_t are reported with their own bounds and are "
                           "never summed into a single reported delta.",
              "SEM", "artifact", "spec 3.5", ALWAYS, check_report_bounds_separate),
    Invariant("INV-SEM04", "A semantic exception removes ONLY the model rung; rungs 1/2 and "
                           "4/5 are unaffected and the report always names an action.",
              "SEM", "artifact", "stage_runner._run_report epoch_ended comment; CLAUDE.md",
              ALWAYS, check_exception_removes_only_model_rung),
    Invariant("INV-SEM05", "Every conditional transition names an accounting rule: an "
                           "adaptive branch with no named inferential accounting does not ship.",
              "SEM", "artifact", "policy.check_policy; spec 5 non-goals", ALWAYS,
              check_policy_structure),
    Invariant("INV-SEM06", "A missing or None observation NEVER matches a guard -- unknown is "
                           "not a fact, and an omitted key is not a zero or a False.",
              "SEM", "function", "policy.step / _match_one docstrings", ALWAYS, None,
              note="Enforced by construction in `_matches` (`k in obs` plus a `value is not "
                   "None` conjunct). No checker: there is no artifact carrying the "
                   "counterfactual, and the property is a TEST-class one over generated "
                   "observations, which tests/test_optimize_invariants.py covers."),
    Invariant("INV-SEM07", "significant is None (unknown) is never treated as significant is "
                           "False (measured null): an unknown effect is never dropped as if "
                           "known-absent.",
              "SEM", "module", "stage.py module docstring", TEST, None,
              note="No production seam: the discipline is in how `decide_after_*` reads "
                   "`significant`, and a checker would inspect the reader rather than a "
                   "value. Covered as a property test over Fits with None significance."),
    Invariant("INV-SEM08", "An alias's re-attributed coefficient carries its sign: keeping "
                           "the sign while re-labelling reverses the effect's direction.",
              "SEM", "function", "effects.Effect.aliased_with", ALWAYS,
              check_alias_sign_preserved),
    Invariant("INV-SEM09", "A failed behavioral relation is never folded into the correctness "
                           "bucket: behavioral failures advance the stage, correctness "
                           "failures abort.",
              "SEM", "function", "relations.classify_failures; stage_runner._assert_all_behavioral",
              ALWAYS, check_behavioral_not_folded_into_correctness,
              note="classify_failures itself silently DROPS a verdict whose kind is "
                   "off-vocabulary (kind='perf' lands in neither bucket). Unreachable "
                   "through the real path -- factors._check_relations rejects any kind but "
                   "correctness/behavioral at parse time -- so 'every failure is classified' "
                   "is enforced UPSTREAM of the public classifier, which this checker states "
                   "as a dependency rather than assuming."),
    Invariant("INV-SEM10", "A declared relation absent from the results is a FAILURE, never a "
                           "pass: a typo'd native_test must not silently disable a gate.",
              "SEM", "function", "relations.py 'The load-bearing rule'", ALWAYS,
              check_declared_relation_absent_is_failure),
    Invariant("INV-SEM11", "Contract drift is a campaign ABORT, not a row failure: re-running "
                           "against a changed instrument yields a number still not comparable "
                           "to rows measured before the change.",
              "SEM", "epoch", "adapter_contract.AdapterContractDrift docstring", ALWAYS, None,
              note="Enforced by the exception TYPE, which stage_runner converts to "
                   "OptimizationAborted rather than routing to the exception branch. A "
                   "checker would assert a control-flow shape, not a value; covered by a "
                   "behavior test (BEH-GUARD-01)."),
    Invariant("INV-SEM12", "null is its own fingerprint type: {\"slope\": 0.4} and "
                           "{\"slope\": null} must not fingerprint alike.",
              "SEM", "function", "adapter_contract._type_name 'that is the whole point'",
              ALWAYS, None,
              violated_by="defect 4: an adapter's output schema was edited three times "
                          "mid-epoch; rows measured before each edit carried null, and a "
                          "coerce put None against a float, killing an iteration at fit "
                          "after ~2 hours",
              note="VERIFIED to hold at the TOP level (float -> null raises "
                   "AdapterContractDrift). The guarantee is one level deep only: nested "
                   "value types are NOT fingerprinted, so "
                   "{\"telemetry\":{\"rate\":2.0}} -> {\"telemetry\":{\"rate\":null}} gives "
                   "diff_contract == ([],[],[]). Nested KEY SETS are covered. Documented in "
                   "_type_name, but the prose 'must not fingerprint alike' reads wider than "
                   "what holds."),

    Invariant("INV-SEM13", "A measured row whose observation contradicts a locked_parameters "
                           "value at its declared optimization.locked_observables path (or "
                           "omits that path) ABORTS the campaign regardless of auto-approve: "
                           "every row would otherwise measure an unregistered experiment.",
              "SEM", "campaign", "locked.check_row / LockedParameterDeviation docstrings; "
              "stage_runner hard-fail #4; #246 (F1)", ALWAYS, None,
              note="Enforced by the exception TYPE (LockedParameterDeviation -> "
                   "OptimizationAborted), raised from the sweep's on_row. Covered "
                   "end to end by a metamorphic pair in "
                   "tests/test_optimize_locked_parameters.py "
                   "(test_a_target_that_ignores_the_locked_value_aborts_the_campaign / "
                   "test_a_target_that_honours_the_locked_value_is_unaffected). A lock "
                   "with NO declared observable is not enforceable and is only WARNed "
                   "by validate_optimization_campaign."),
    Invariant("INV-SEM14", "Feasibility is per CONFIGURATION: the report never returns (and "
                           "no shortlist seed or best-observed selector picks) a "
                           "configuration any row measured infeasible/rejected, however "
                           "many of its other rows completed.",
              "SEM", "artifact", "stage_runner._config_admissible / _top_measured / "
              "_run_report; _finish_confirm sticky rule", ALWAYS,
              check_recommendation_admissible_per_configuration,
              violated_by="field campaign (constraint noise straddling its bound): the "
                          "measured rung returned a finalist confirm had struck off, on "
                          "the strength of its one complete replicate"),
    Invariant("INV-SEM15", "Confirm's epsilon records the reference its percentage was taken "
                           "of, and is never 0 for want of one: with no admissible finalist "
                           "it is resolved from the best measured admissible configuration "
                           "(else recommendation.json's epsilon), else it is null.",
              "SEM", "artifact", "stage_runner._confirm_epsilon", ALWAYS,
              check_epsilon_has_a_reference,
              violated_by="field campaign: every finalist inadmissible, epsilon resolved "
                          "as pct of 0.0 = 0.0"),
    Invariant("INV-SEM16", "Whenever the policy registers refine, screen and foldover each "
                           "carry a registered `lack_of_fit` -> refine rule naming its "
                           "accounting: centre-point curvature with no refinable survivor "
                           "augments to the second-order design, never to confirm.",
              "SEM", "artifact", "policy.CURVATURE_ACCOUNTING; compile_policy raises on it",
              ALWAYS, check_curvature_routes_to_refine,
              violated_by="SURFACES['geometric_knob'] (linear coding): zero main effects "
                          "at the corners, lack-of-fit p~3.5e-7, routed screen -> confirm "
                          "and certified a point 26% below the optimum on every seed"),
    Invariant("INV-SEM17", "No global certificate rests on a model the data rejected: when "
                           "the latest fitting stage reported model_adequate: false, "
                           "certified is false and certification_withheld names "
                           "model_inadequate.",
              "SEM", "artifact", "stage_runner._finish_confirm (model_inadequate); spec 3.6 "
              "rung 3, 3.3", ALWAYS, check_certificate_rests_on_adequate_model,
              violated_by="SURFACES['geometric_knob']: screen and refine both rejected "
                          "for lack of fit, and confirm certified the best of a "
                          "measured-only shortlist 26% below the optimum"),
    Invariant("INV-SEM18", "A multi-objective certificate rests on the front: when "
                           "certified, the preferred point is on the measured front, "
                           "confidently nondominated at delta_terminal / max_rounds, and "
                           "the preference scalarisation's regret bound is known and "
                           "within epsilon_scalar; the report recommends that point.",
              "SEM", "artifact", "stage_runner._finish_confirm_pareto; spec 2026-10-15 "
              "step 7", TEST, check_pareto_certificate),
    Invariant("INV-SEM19", "The recommendation and the ranked candidates never name a "
                           "categorical level that is lost (no retained row) or "
                           "inadmissible wherever it was measured.",
              "SEM", "artifact", "stage_runner.run_stage (lost/inadmissible level "
              "exclusions); spec 2026-10-16 stage-1b N7", ALWAYS,
              check_recommendation_avoids_lost_levels),
    # ── statistical ───────────────────────────────────────────────────────
    Invariant("INV-STAT01", "One fitted coefficient per ALIAS CLASS, not per two-factor "
                            "interaction: a resolution-IV design must not make XtX singular.",
              "STAT", "function", "spec 4 D1", ALWAYS, check_one_coefficient_per_alias_class,
              violated_by="D1: every tabulated resolution-IV screen (k=5..8) crashed at fit "
                          "with 'design matrix is singular'"),
    Invariant("INV-STAT02", "No fitted coefficient is NaN: a single NaN response must not "
                            "poison every coefficient while returning a schema-valid Fit.",
              "STAT", "function", "spec 4 D2", ALWAYS, check_fit_has_no_nan,
              violated_by="D2: one infeasible row NaN-poisoned every coefficient while "
                          "returning a schema-valid Fit -- the abort guard excluded "
                          "infeasible rows from its CHECK but nothing excluded them from the "
                          "FIT. [0.1875, -0.5625, -0.0625, 0.1875] became all-NaN with "
                          "nothing raised and nothing logged.",
              note="Now closed at BOTH levels, which it was not when this inventory was "
                   "first drafted: `stage_runner` drops non-complete rows and records them "
                   "in fit_exclusions.json, AND `fit_effects` itself now raises on a NaN "
                   "response rather than returning an all-NaN Fit. The checker is retained "
                   "because an all-NaN Fit is still constructible, so any future fitting "
                   "path inherits the guard rather than the defect."),
    Invariant("INV-STAT03", "A residual-regret bound is never negative: the gap to the true "
                            "optimum cannot be below zero.",
              "STAT", "function", "certificate.py 'floors at 0.0'", ALWAYS,
              check_bound_nonnegative),
    Invariant("INV-STAT04", "A bound is non-decreasing as delta shrinks: a stronger "
                            "confidence requirement cannot produce a narrower certificate.",
              "STAT", "function", "the t-quantile; spec 3.5", TEST, None,
              note="A property over a generated space, not a per-call check: asserting it "
                   "inline would mean computing the bound at a second delta on every call."),
    Invariant("INV-STAT05", "A bound computed from a zero-variance sample is None, not 0.0 -- "
                            "the deterministic-target case of spec 3.5.",
              "STAT", "function", "spec 3.5 'pure_error = 0 and every interval came back None'",
              ALWAYS, check_bound_unknown_is_not_zero, open_violation=False,
              violated_by="terminal_regret_bound; see INV-SEM02"),
    Invariant("INV-STAT06", "More replicates never widen a bound; fewer rows never narrow it. "
                            "Dropping information can only widen uncertainty.",
              "STAT", "function", "spec 2.5 minimum information loss", TEST, None,
              note="A property over a generated space. Verified: 4 reps -> 0.08798, 16 reps "
                   "-> 0.02097 on the same means."),
    Invariant("INV-STAT08", "Row exclusions from the fit are independent of factor levels: a "
                            "level-correlated exclusion set is a confounded design, not a "
                            "reduced one.",
              "STAT", "iteration", "historical defect 6", ALWAYS,
              check_exclusions_independent_of_levels,
              violated_by="defect 6: two timeouts landed on the SAME corner of the factor "
                          "space while the other level at that identical corner completed -- "
                          "a perfect 2x2 separation that nothing detected"),
    Invariant("INV-STAT09", "Every excluded row is recorded in fit_exclusions.json with its "
                            "index and reason: no infeasible row dropped without record.",
              "STAT", "iteration", "spec 2.5; stage_runner fit-exclusion block", ALWAYS,
              check_exclusions_recorded, violated_by="D2"),
    Invariant("INV-STAT10", "A fit is refused rather than attempted when fewer than 2 rows "
                            "survive exclusion.",
              "STAT", "function", "stage_runner's len(keep) < 2 abort", ALWAYS, None,
              note="Enforced by the abort itself. No checker: the guard IS the check, and a "
                   "registry copy would test the language rather than the system. Rank and "
                   "identifiability floors beyond this live in "
                   "orchestrator.optimize.exclusions."),
    Invariant("INV-STAT11", "Sign symmetry: negating every response and flipping direction "
                            "yields the identical bound.",
              "STAT", "function", "metamorphic property over certificate", TEST, None,
              note="Verified exactly at 9 decimal places."),

    Invariant("INV-STAT12", "The terminal bound never RAISES on an admissible sample: "
                            "a variance it cannot estimate is None, not an exception.",
              "STAT", "function", "certificate.terminal_regret_bound Welch df denominator",
              TEST, None, open_violation=False,
              violated_by="the Welch degrees-of-freedom denominator "
                          "(vk**2)/(nk-1) + (vb**2)/(nb-1) is guarded only by "
                          "`if (vk + vb) > 0`. For subnormal-magnitude variances that "
                          "guard passes while vk**2 UNDERFLOWS to exactly 0.0, so the "
                          "bound raises ZeroDivisionError on the certification path. "
                          "Minimal input: two finalists with replicates "
                          "[-3.117993501313441e-82, 0.0] (vk == vb == 2.43e-164). Found by "
                          "the hypothesis property, not by construction. The paired branch "
                          "divides by n and survives, which localises it.",
              note="No checker: the failure is an EXCEPTION rather than a value, so there "
                   "is nothing for a pure predicate over a returned object to inspect. "
                   "Asserted directly in test_welch_df_underflows_on_subnormal_variance. "
                   "The guard should test the DENOMINATOR, not the sum of the variances."),

    Invariant("INV-STAT13", "A fitted constraint model excludes a candidate only when the "
                            "constraint's one-sided bound at delta_screen lies ENTIRELY on "
                            "the violating side: a candidate whose bound admits feasibility "
                            "is never removed from the argmax or top_candidates.",
              "STAT", "function", "constraint_models module docstring; decide._scored",
              TEST, None,
              violated_by="field campaign (throughput under p99 <= 90): every screen row at "
                          "one corner measured infeasible, the primary-only fit ranked that "
                          "corner's INTERIOR points first, and a confirm round was spent "
                          "measuring them infeasible, withholding certification. Excluding on "
                          "the point prediction instead would delete the true optimum "
                          "whenever model error puts it past the boundary.",
              note="A property over generated fits, thresholds, ops and deltas: "
                   "tests/test_optimize_constraint_models.py::"
                   "test_exclusion_never_removes_a_candidate_whose_bound_admits_feasibility, "
                   "which restates the bound from the definition rather than reading the "
                   "verdict back from the code under test (mutation-verified: excluding on "
                   "the point prediction fails it)."),

    Invariant("INV-STAT14", "The fit's design matrix is the coded ACTUAL levels: every "
                            "fitted row is coded from the levels that ran "
                            "(factors.code_actual), never from the design's nominal "
                            "coordinates -- a clamped axial point at the range edge it ran "
                            "at, a choice factor's centre row at the level it ran (-1). "
                            "design_matrix.json still records the plan.",
              "STAT", "artifact",
              "matrix.coded_as_run; stage_runner fit block; constraint_models; "
              "effects.json fit_coordinates",
              TEST, check_fit_coordinates_are_actual,
              violated_by="the nominal coding regressed on axial coordinates +-1.41/1.68 "
                          "that decode_coded clamps to +-1, and coded a choice factor's "
                          "centre row 0 where it ran at its first level. Measured: a truly "
                          "linear surface on a clamped CCD failed lack of fit ~100% of "
                          "seeds (~alpha once recoded); `additive` failed it at screen on "
                          "every seed; a real campaign's exactly-linear p99 constraint "
                          "model was rejected at p=2.7e-05 and its BS x CMP interaction "
                          "was 'estimated' (127.5) only through a mis-coded centre row.",
              note="tests/test_optimize_coded_as_run.py: oracle properties (LOF ~uniform "
                   "under a correct model, CI coverage, unbiased mixed interaction) and "
                   "the checker against a recorded fit_coordinates."),

    Invariant("INV-STAT15", "infeasible rows (a response.constraints violation) inform the "
                            "PRIMARY fit; rejected and failed rows never do. Admissibility is "
                            "enforced where a configuration can be RETURNED (measured-"
                            "infeasible exclusion, best-observed reads complete only, "
                            "confirm strikes an infeasible finalist), not by truncating the "
                            "fit at the constraint boundary.",
              "STAT", "artifact",
              "stage_runner._PRIMARY_FIT_STATUSES; effects.json fit_coordinates.rows_by_status",
              TEST, check_fitted_statuses,
              violated_by="excluding infeasible rows truncated the design exactly at the "
                          "constraint boundary: a real sqlite-utils campaign fitted refine "
                          "on 3 of 12 rows (9 infeasible), a re-run aborted with 2 retained "
                          "rows; on the constrained-bowl oracle 4/16 campaigns aborted.",
              note="tests/test_optimize_coded_as_run.py::"
                   "test_fitting_infeasible_rows_is_never_worse_on_the_constrained_oracle "
                   "(metamorphic, both rules per seed) and the checker over fit_coordinates."),

    Invariant("INV-STAT16", "When response.constraints are declared and the confirm "
                            "shortlist has >= 2 seats, a seat is reserved for the best-"
                            "predicted SUPPORTED-FEASIBLE candidate when one exists: every "
                            "modelled constraint confidently feasible at delta_screen "
                            "(Bonferroni, as exclusion) and, for each unmodelled one, inside "
                            "the per-factor span of measured-admissible configurations. "
                            "The seat never duplicates a finalist and never displaces a "
                            "measured one; with no constraints the shortlist is unchanged.",
              "STAT", "artifact",
              "constraint_models.supported_feasible; stage_runner._confirm_rows "
              "(_seat_supported); recommendation.json supported_feasible_candidate",
              TEST, check_supported_feasible_candidate,
              violated_by="two field campaigns: a deterministic max_unflushed_writes <= 200 "
                          "(unmodelled) saw both model-ranked finalists pair a bigger cache "
                          "with an infeasible write cache while a bigger cache with a "
                          "measured-feasible write cache was never tested; a noisy hit-rate "
                          "constraint's shortlist tested only the boundary level.",
              note="tests/test_optimize_supported_feasible_seat.py: oracle on "
                   "SURFACES['deterministic_constraint_axis'] (feasible answer beating "
                   "everything measured before confirm), metamorphic byte-identity with no "
                   "constraints, a property restating (a)/(b) from the definition, and the "
                   "checker over every recommendation.json. The admissible-region rule is a "
                   "conservative interpolation heuristic, not a feasibility guarantee."),

    Invariant("INV-STAT17", "The measured front is consistent: no front point is "
                            "eps-dominated in point estimate by another, a confidently "
                            "nondominated point names no possible dominator and a possibly "
                            "dominated one names one, the front is sorted by the first "
                            "objective, and the normalised hypervolume is in [0, 1] -- or null "
                            "with a reason, exactly when no point is confident.",
              "STAT", "artifact", "pareto.measured_front; pareto_stage.front_record",
              TEST, check_pareto_front,
              note="tests/test_optimize_pareto.py runs the checker over every oracle "
                   "campaign's report.json; the oracle properties (every confident point "
                   "within epsilon of the TRUE front, hypervolume floors) are what make "
                   "the statuses mean something."),
    Invariant("INV-STAT18", "recommendation.json carries candidate_space exactly when the "
                            "candidate space (the product of the fitted factors' axis sizes) "
                            "exceeds decide.CANDIDATE_CAP and was SEARCHED; it then says "
                            "exhaustive: false, the search method and seed, the full size and "
                            "the evaluated count and whether the constraint models applied; the "
                            "model regret bound's detail says the max ran over the evaluated set "
                            "only, alias_consequential_basis is 'searched', alias_assessment "
                            "accounts for every alias reading, no constraint reason claims "
                            "'every candidate', and a predicted "
                            "front is marked predicted_front_basis: 'evaluated_points'; "
                            "report.json carries the same candidate_space. At or "
                            "below the cap the space is enumerated and none of these keys exist.",
              "STAT", "artifact", "decide._scored; stage_runner recommendation write",
              TEST, check_candidate_space,
              note="tests/test_optimize_candidate_search.py forces the search on oracle "
                   "campaigns and runs the checker over every recommendation.json; "
                   "tests/test_optimize_invariants.py gives it teeth."),

    # ── temporal ──────────────────────────────────────────────────────────
    Invariant("INV-TMP01", "policy.json + policy.sha256 are written BEFORE the first "
                           "benchmark run of the epoch. That ordering IS the pre-registration.",
              "TMP", "epoch", "spec 3.1; CLAUDE.md", ALWAYS,
              check_preregistration_precedes_measurement,
              note="VERIFIED empirically on both write paths: verify-first and "
                   "_load_or_compile_policy's lazy branch. Every one of 21 rows saw "
                   "policy.sha256 present, and its mtime precedes the first runs.jsonl."),
    Invariant("INV-TMP02", "transitions.jsonl is append-only across epochs; an exception must "
                           "not truncate it.",
              "TMP", "campaign", "policy.epoch_transitions docstring", AUDIT,
              check_transitions_epoch_scoped,
              note="VERIFIED: after epoch 2, the file is a byte-PREFIX-preserving extension "
                   "of its epoch-1 content (1211 -> 2408 bytes, earlier rows identical)."),
    Invariant("INV-TMP03", "Every consumer asking 'what has happened so far?' means 'so far IN "
                           "THIS EPOCH' -- epoch_transitions, never read_transitions.",
              "TMP", "module", "policy.epoch_transitions 'one filter, one place'", TEST, None,
              note="A call-site discipline, checkable only by inspecting readers."),
    Invariant("INV-TMP04", "The adapter contract is captured from the first SUCCESSFUL row of "
                           "the epoch, never from a failed/infeasible/rejected one.",
              "TMP", "epoch", "runner.py guards-run-LAST comment; adapter_contract guard 1",
              ALWAYS, None,
              note="Enforced by guard placement (the guards run after every other check, so "
                   "a row reaches them only if it would otherwise be complete). A checker "
                   "would assert an ordering of code, not a value."),
    Invariant("INV-TMP05", "Freshness compares against the IMMEDIATELY PRECEDING row that "
                           "produced a usable measurement, never the whole history.",
              "TMP", "epoch", "adapter_contract.check_freshness", ALWAYS, None,
              note="VERIFIED, including the documented LIMIT: it cannot fire for an adapter "
                   "that echoes its own configuration back, because the echoed block makes "
                   "every canonical encoding differ. Declaring that block in "
                   "response.constant_fields restores detection."),
    Invariant("INV-TMP06", "confirm's round observation is 1-based and counts rounds SPENT "
                           "INCLUDING the current one; screen/refine report 0 because they "
                           "cannot self-loop.",
              "TMP", "iteration", "stage_runner OBSERVATION CONVENTIONS", TEST, None,
              note="VERIFIED: with confirm_max_rounds=4, the confirm round observations were "
                   "[1, 2, 3, 4] and the cap fired at exactly 4."),
    Invariant("INV-TMP07", "An epoch that ended on a semantic exception recompiles on the next "
                           "resume and starts at initial -- never at the terminal exception.",
              "TMP", "campaign", "_load_or_compile_policy; policy.current_state", ALWAYS, None,
              note="VERIFIED: at the moment epoch 2 began, epoch_transitions(pol2) was empty "
                   "and current_state(pol2) was 'screen' == initial."),
    Invariant("INV-TMP08", "A transition row is appended for every state the epoch actually "
                           "entered, INCLUDING one that aborted before its fit: an epoch that "
                           "died must leave a record of why.",
              "TMP", "epoch", "historical defect 7", AUDIT,
              check_audit_trail_records_spending, open_violation=False,
              violated_by="defect 7: transitions.jsonl completely empty after 14 hours. "
                          "REPRODUCED, and the trigger is LOWER than the design doc implies "
                          "-- the gate is _fitting_responses' 'N of M runs produced no usable "
                          "measurement', which fires on ONE failed row of twelve, not the "
                          "len(keep) < 2 abort. Measured: 5 iterations, 60 benchmark runs "
                          "spent, transitions.jsonl never created, no epoch_end-*.json, no "
                          "report.json."),

    # ── provenance ────────────────────────────────────────────────────────
    Invariant("INV-PROV01", "policy.json must HAVE a sidecar and AGREE with it: absence is as "
                            "fatal as disagreement.",
              "PROV", "artifact", "_load_or_compile_policy; CLAUDE.md", ALWAYS,
              check_policy_provenance, open_violation=False,
              violated_by="the shipped guard is `if recorded.exists() and ...`, so DELETING "
                          "policy.sha256 disables it rather than failing closed. Verified: "
                          "with the sidecar deleted and screen's default rewritten "
                          "confirm->report, the epoch produced a report.json claiming "
                          "basis 'model' with terminal discrimination silently skipped, no "
                          "confirmation.json, and no sidecar regenerated. The tampered hash "
                          "was recorded in transitions.jsonl as though it were the "
                          "registration."),
    Invariant("INV-PROV02", "mechanism.sha256 and policy.json's "
                            "compiled_from.mechanism_patch_hash agree: two records of one "
                            "commitment must not be individually well-formed and jointly "
                            "meaningless.",
              "PROV", "artifact", "stage_runner 'Two records of ONE commitment' comment",
              ALWAYS, None,
              note="Checked inline by stage_runner where both values are in hand. No "
                   "registry checker: reproducing it would need the mechanism tree, which a "
                   "pure function cannot be handed."),
    Invariant("INV-PROV03", "adapter_contract.json must have a sidecar and agree with it.",
              "PROV", "artifact", "adapter_contract.read_contract", ALWAYS,
              check_provenance_pair,
              note="read_contract has the SAME `sidecar.exists() and` conditional as "
                   "INV-PROV01's guard, so it inherits the same hole: deleting "
                   "adapter_contract.sha256 disables the check. Passing it through "
                   "check_provenance_pair is what makes the pair REQUIRED."),
    Invariant("INV-PROV04", "Every transitions.jsonl row carries the policy_hash it ran under, "
                            "so 'which policy scheduled this design?' stays answerable for "
                            "every epoch.",
              "PROV", "artifact", "_close_iteration; _load_or_compile_policy", ALWAYS,
              check_transitions_epoch_scoped),
    Invariant("INV-PROV05", "A fingerprint's hash equality does not depend on dict insertion "
                            "order.",
              "PROV", "function", "adapter_contract.contract_hash comment", TEST, None,
              note="VERIFIED: reordered contracts hash identically and diff_contract returns "
                   "([], [], [])."),
    Invariant("INV-PROV06", "The mechanism hash never covers Nous's own outputs: .nous/, "
                            ".nous-experiments/ and the campaign work_dir (when inside the "
                            "target) are excluded from BOTH halves of the drift text, so "
                            "Nous's writes during an epoch cannot read as mechanism drift.",
              "PROV", "function", "build._mechanism_text; build.NOUS_OWNED_PATHS", TEST, None,
              violated_by="default layout (NOUS_CAMPAIGN_PARENT unset): the work_dir at "
                          "<target>/.nous/<run_id>/ was hashed, including the "
                          "mechanism.patch the snapshot itself wrote, so iter-2 of every "
                          "such campaign aborted 'mechanism drifted since compile'. "
                          "REPRODUCED with a real git repo, then fixed.",
              note="VERIFIED by tests/test_optimize_build_oracles.py's default-layout tests: "
                   "runs.jsonl appends, a .nous/repo cache and a .nous-experiments worktree "
                   "leave the hash unchanged; a mech.py edit still aborts. A hash recorded "
                   "before the exclusion is still accepted (mechanism_hash_matches)."),

    # ── resource / isolation ──────────────────────────────────────────────
    Invariant("INV-RES01", "A per-run config patch is a COPY: the input document is never "
                           "mutated, so a caller holding the parsed doc is safe.",
              "RES", "function", "config_patch 'Pure: the input document is never mutated'",
              ALWAYS, None,
              note="VERIFIED including deep reference-freedom: a nested value mutated after "
                   "the call leaves the stored value unchanged, and three rows rendered from "
                   "one baseline give [1,2,3] while the baseline stays 1024."),
    Invariant("INV-RES02", "A level is serialized in its native type, never through str(): an "
                           "int level stays an int.",
              "RES", "function", "config_patch 'never stringified'", ALWAYS, None,
              violated_by="a bool/int level mismatch failed 67 of 67 runs on a real campaign",
              note="VERIFIED on disk in both JSON and YAML: block_size: 3, enabled: true, "
                   "not \"3\"/\"true\"."),
    Invariant("INV-RES03", "config_patch never CREATES structure: a pointer that does not "
                           "exist is a ConfigPatchError, never a silent no-op.",
              "RES", "function", "config_patch pointer check", ALWAYS, None,
              note="VERIFIED across six malformed-pointer shapes."),
    Invariant("INV-RES04", "No two concurrent rows share a filesystem path or a build output; "
                           "two rows patching the same file must never collide.",
              "RES", "iteration", "config_patch per-row materialisation; stage_runner", ALWAYS,
              None,
              note="Owned by orchestrator.optimize.concurrency, which also sets NOUS_RUN_DIR "
                   "/ NOUS_ROW_INDEX / NOUS_RUN_SLOT unconditionally so per-run isolation "
                   "does not depend on the width being above 1."),
    Invariant("INV-RES05", "Run-order randomization uses a local random.Random, never global "
                           "module state: the same seed always yields the same order and "
                           "global state is unperturbed.",
              "RES", "function", "matrix.randomize", TEST, None,
              note="VERIFIED both directions: identical order across 1000 intervening global "
                   "random() calls plus a reseed, and random.getstate() byte-identical "
                   "across a randomized_run_order call."),
    Invariant("INV-RES06", "duration_ms is monotonic-clock derived, positive on any row that "
                           "ran, and 0 is RESERVED for 'did not run'.",
              "RES", "function", "runner.RunOutcome.duration_ms", ALWAYS,
              check_duration_reserved_zero,
              violated_by="defect 3: declared, schema-valid, and structurally ALWAYS 0 -- "
                          "never assigned at any of nine construction sites. Now floored at "
                          "1ms so 0 keeps its meaning."),

    # ── economic ──────────────────────────────────────────────────────────
    Invariant("INV-ECO01", "ZERO model calls inside any compiled epoch state, for any reason "
                           "including 'just to interpret a result'.",
              "ECO", "epoch", "spec 2.2, 5; CLAUDE.md 'the single most important invariant'",
              ALWAYS, check_no_model_call_reachable_from_epoch,
              note="VERIFIED statically (the only dispatcher import in the package is "
                   "function-local inside build.run_build) and dynamically (tripwires on "
                   "every dispatcher plus urlopen, across all six epoch states including a "
                   "forced foldover; no llm_metrics.jsonl written) with a live negative "
                   "control that fires when build IS declared."),
    Invariant("INV-ECO02", "compile_policy is a pure function of the campaign: zero tokens, no "
                           "measurement read, same input -> same hash.",
              "ECO", "function", "spec 3.1; policy.compile_policy", ALWAYS,
              check_compile_policy_is_pure),
    Invariant("INV-ECO03", "budget_remaining absent a declared max_runs means 'unbounded', "
                           "never 'exhausted': a missing cap must never route a campaign to "
                           "report.",
              "ECO", "iteration", "stage_runner OBSERVATION CONVENTIONS", TEST, None,
              note="Enforced by the 10**9 sentinel. A checker would assert the sentinel's "
                   "value, which is the implementation rather than the property."),
)

REGISTRY: dict[str, Invariant] = {i.id: i for i in _ENTRIES}


def by_type(type_: str) -> list[Invariant]:
    return [i for i in _ENTRIES if i.type == type_]


def by_level(level: str) -> list[Invariant]:
    return [i for i in _ENTRIES if i.level == level]


def by_enforcement(enforcement: str) -> list[Invariant]:
    return [i for i in _ENTRIES if i.enforcement == enforcement]


def open_violations() -> list[Invariant]:
    """Registered invariants the CURRENT code violates, verified empirically.

    Kept as a first-class query rather than a comment because a reader must be
    able to ask "what does this package know it is getting wrong?" and get an
    answer. A disclosed violation is more useful than a hidden one: it tells a
    reviewer which guarantees not to rely on, and it tells the next owner where
    the work is.
    """
    return [i for i in _ENTRIES if i.open_violation]


def checkable() -> list[Invariant]:
    return [i for i in _ENTRIES if i.checker is not None]


def assert_invariant(invariant_id: str, *args, **kwargs) -> None:
    """Run one registered checker and raise ``InvariantViolation`` on failure.

    The seam helper. Skips ``PARANOID``-class invariants unless
    ``NOUS_OPTIMIZE_PARANOID`` is set, and raises ``KeyError`` for an
    unregistered id -- an assertion against an id with no registry entry is a
    typo, and failing loudly on it is what keeps call sites honest.
    """
    inv = REGISTRY[invariant_id]
    if inv.enforcement == PARANOID and not paranoid_enabled():
        return
    if inv.checker is None:
        return
    violations = inv.checker(*args, **kwargs)
    if violations:
        raise InvariantViolation(invariant_id, violations)


def audit_work_dir(work_dir: Path) -> dict[str, list[str]]:
    """Run every ``AUDIT``-class checker over a finished work-dir.

    Post hoc rather than inline, because these are the ``epoch``/``campaign``-level
    invariants -- and in ``INV-TMP08``'s case because the violation IS that the
    inline seam is never reached. Returns ``{id: violations}`` for the ones that
    failed, so a caller can report every finding rather than only the first.
    """
    from orchestrator.optimize.policy import read_transitions

    work_dir = Path(work_dir)
    out: dict[str, list[str]] = {}
    for inv in by_enforcement(AUDIT):
        if inv.checker is None:
            continue
        if inv.id == "INV-TMP02":
            v = inv.checker(read_transitions(work_dir))
        else:
            v = inv.checker(work_dir)
        if v:
            out[inv.id] = v
    return out
