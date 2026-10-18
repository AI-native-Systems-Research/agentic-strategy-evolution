"""The compiled experimental policy: data, not code.

Spec §3.1. ``compile_policy`` is a PURE function of the campaign's
``optimization`` block plus the mechanism patch hash and epoch index; it makes
no model call and reads no measurement. Its output is written once at the end
of ``verify`` (stage_runner), hashed, and cited by every design_matrix.json
materialised inside the epoch. ``step`` (below, Task 5) interprets it over a
CLOSED observation vocabulary — no free-form expressions, no generated code.

Why data: a JSON document with a sha256 written before the first benchmark
run IS a pre-registration; path fidelity against it is checkable exactly like
``matrix.check_fidelity`` checks rows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orchestrator.optimize.factors import is_refinable, parse_factors

POLICY_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "policy.schema.json"

OBSERVATION_KEYS: frozenset[str] = frozenset({
    "correctness_failed", "nan_response", "all_within_noise", "lack_of_fit",
    "refinable_survivors", "alias_consequential", "stationary_in_hull",
    "model_adequate", "certified", "round", "budget_remaining",
    "runs_needed_foldover", "foldover_affordable",
    "runs_needed_confirm", "confirm_affordable",
    "residual_regret", "epsilon",
    # MULTI-OBJECTIVE ONLY (spec 2026-10-15-pareto-front-design.md step 6).
    # Consumer: the registered `confirm -> confirm` gap-fill branch
    # (`FRONT_GAP_ACCOUNTING`), compiled only when `response.objectives` is
    # declared. True when the largest normalised gap between adjacent
    # measured-front points exceeds `2 x max_k(eps_k / range_k)`; the gap list
    # itself is in `confirmation.json["pareto"]["gaps_remaining"]`.
    "front_gap_large",
    # CONSTRAINED CAMPAIGNS ONLY. Consumer: the registered `confirm -> confirm`
    # refill branch (`REFILL_ACCOUNTING`), compiled only when
    # `response.constraints` is declared. `finalists_vacated` = finalists
    # measured inadmissible this round; `feasible_finalists` = admissible
    # finalists that produced measurements; `refill_available` = no refill
    # round spent yet this epoch (the branch is capped at one) AND the refill
    # pool still holds an unmeasured candidate whose nearest measured neighbour
    # is admissible -- derived in the runtime, like `confirm_affordable`.
    # Produced only on a round that vacated a seat, so an unvacated round's
    # observations are unchanged.
    "finalists_vacated", "feasible_finalists", "refill_available",
    # OPT-IN ALLOCATE BRANCH ONLY (WP-D D1 / P6b). Consumer: the registered
    # `confirm -> confirm` allocate round (`ALLOCATE_ACCOUNTING`), compiled
    # only when `design.confirm.allocate` is declared. True when the round at
    # the cap did not certify, the branch is not yet spent this epoch, and the
    # allocator (models adequate) left at least one seatable candidate in
    # `confirmation.json["allocation"]["seats"]` -- derived in the runtime,
    # like `refill_available`. Produced only when the branch is registered.
    "allocate_available",
    # Its companion, NEVER branched on: the sha256 of the seats round r
    # registered, anchored in the transition row so round r+1 can verify the
    # seats before measuring them (P6b review H1). A REPORTING key.
    "allocate_seats_sha256",
    # `behavioral_violation` is INTENTIONALLY never read by a compiled `when`
    # clause, and the intent is the one `stage.decide_after_screen` states in
    # its own words: "Behavioral violations are reported but never block
    # advancement: a monotonicity break is a discovery, not a reason to stop."
    # Its evidence reaches the campaign through `findings.json` — the note
    # `stage._behavioral_trigger_note` builds is folded into
    # `StageDecision.rationale`, which `stage_runner.run_stage` hands to
    # `artifacts.project_findings` as `decision`, landing in that file's
    # `discrepancy_analysis` and in every arm's `metadata.decision` — plus the
    # per-relation verdict in `relations.json`. So it is a REPORTING key, not a
    # branching one, and its presence here is what lets it be observed and
    # logged to `transitions.jsonl` without a transition consuming it. Adding a
    # `when: {"behavioral_violation": True}` rule would reverse that design
    # decision, not complete it.
    "behavioral_violation",
})
"""The closed observation vocabulary a compiled ``when`` predicate may read.

``foldover_affordable`` and ``confirm_affordable`` are DERIVED booleans rather
than comparisons the policy performs itself, and the reason is that ``when``
predicates compare an observation against a CONSTANT — there is no form that
compares two observations. "Is the remaining budget at least what the fold
block / the next confirm round would cost?" is exactly such a two-observation
comparison (``budget_remaining >= runs_needed_foldover``, ``budget_remaining >=
runs_needed_confirm``), so the runtime evaluates it where both numbers are known
and reports the verdict. ``runs_needed_foldover`` / ``runs_needed_confirm`` are
still recorded next to their verdicts: the verdict is what the guard reads, the
count is what a reader of ``transitions.jsonl`` needs to see WHY it came out
that way, and a boolean with no accompanying magnitude would make a
budget-denied block indistinguishable from an irrelevant one in the audit trail.

NOT EVERY KEY HERE IS READ BY A ``when`` CLAUSE, and that is legitimate for
three distinct reasons, which a maintainer reading this set cold cannot
otherwise tell apart:

* it is the MAGNITUDE behind a derived verdict, kept for the audit trail
  (``runs_needed_foldover``, ``runs_needed_confirm``);
* it is a REPORTED number a downstream artifact consumes rather than a branch
  (``residual_regret`` / ``epsilon`` in ``report.json``; ``model_adequate``,
  which ``recommendation.json`` carries, ``_confirm_rows`` reads to decide
  whether the fitted argmax may anchor the shortlist, and ``_finish_confirm``
  reads to withhold certification (``model_inadequate``); ``all_within_noise``,
  which reaches ``findings.json`` through ``StageDecision.triggers``);
  ``lack_of_fit`` is BRANCHING at ``screen``/``foldover`` only -- the
  registered curvature branch to ``refine`` (``CURVATURE_ACCOUNTING``) -- and
  deliberately non-branching at ``refine``, where model inadequacy is answered
  by confirm's fresh measurements instead (see the "DELIBERATELY NOT a
  ``lack_of_fit`` rule" note on refine's transitions below);
* it is DELIBERATELY non-branching by design, as ``behavioral_violation``'s
  note above records.

What is NOT legitimate is a key whose comment claims a guard that was never
compiled. ``runs_needed_confirm`` did exactly that: its comment at the
producing site said "so a compiled guard can compare it against the remaining
budget", no such guard existed for six tasks, and the gap it was computed to
close — a round the budget cannot finish, while ``budget_remaining < 1`` still
reads as affordable — stayed open the whole time. So when you add a key here,
name its consumer: a registered transition, an artifact field, or a note like
``behavioral_violation``'s. A key with none of the three is dead vocabulary
that reads like a live guard.
"""

COMPARISON_OPS: frozenset[str] = frozenset({">", ">=", "<", "<="})
"""The closed operator vocabulary a ``when`` predicate may use.

A ``when`` value is either a bare literal (``True``/``False``/number — bare
equality against the observation) or a single-entry dict mapping one of these
operators to a constant. Nothing else is interpretable, which is what makes
"no free-form expressions" true rather than aspirational: ``check_policy``
rejects an unknown operator instead of letting ``step`` treat the predicate as
unsatisfiable and silently strand the branch it guards.
"""

# The stages that sit OUTSIDE the compiled epoch, in campaign order.
#
# ``plan`` and ``build`` are the kind's only model-facing stages; ``verify`` is
# what compiles the policy, so it cannot be a state inside it. Everything after
# these is an epoch state that ``step()`` may route to.
#
# ``plan`` MUST be listed here, and its omission broke both functions below in
# the same way: ``pre_epoch_stages`` walks the declared order and BREAKS at the
# first non-pre-epoch stage, so a ``[plan, build, verify, ...]`` campaign broke on
# element 0 and returned ``[]`` -- skipping BOTH model-facing stages and running
# ``verify`` first, which then aborted on the very relations ``build`` was there
# to author. And ``_enabled`` subtracts this tuple, so ``plan`` leaked into the
# epoch's state set, contradicting the kind's central invariant that no model
# call is ever made inside a compiled epoch state.
_PRE = ("plan", "build", "verify")
_DEFAULT_STAGES = ("verify", "screen", "refine", "confirm")


def pre_epoch_stages(campaign: dict) -> list[str]:
    stages = ((campaign.get("optimization") or {}).get("stages")) or list(_DEFAULT_STAGES)
    out: list[str] = []
    for s in stages:
        s = getattr(s, "value", None) or str(s)
        if s in _PRE:
            out.append(s)
        else:
            break
    return out


def _enabled(campaign: dict) -> set[str]:
    stages = ((campaign.get("optimization") or {}).get("stages")) or list(_DEFAULT_STAGES)
    return {getattr(s, "value", None) or str(s) for s in stages} - set(_PRE)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


CURVATURE_ACCOUNTING = (
    "lack-of-fit F on pure error (the centre-point curvature contrast) at "
    "alpha=0.05; registered second-order augmentation: refine's central "
    "composite spans EVERY refinable factor, because curvature detected by a "
    "2-level design's centre points is one contrast that no factor can be "
    "credited with"
)
"""The accounting rule of the registered CURVATURE branch (screen/foldover -> refine).

WHY THE BRANCH EXISTS. A response whose optimum is INTERIOR has ~zero main
effects at a 2-level screen's corners -- every corner sits about as far from
the optimum as every other -- so no numeric factor survives the screen and
``refinable_survivors > 0`` cannot fire. The screen's centre points are the one
part of the design that sees such a response: the centre-vs-corner contrast is
what the lack-of-fit F on pure error measures when the screen model is mains +
two-factor interactions. Routing that screen to ``confirm`` seated a shortlist
from corners and centre and CERTIFIED the best of it: 26% below the true
optimum on ``synthetic.SURFACES["geometric_knob"]`` on every seed, and 1.0 below
it (2.5x epsilon) on the pure-curvature ``bowl_centred``. The textbook response
to significant curvature in a centre-pointed 2-level design is to augment it to
a second-order (central composite) design, which is exactly what ``refine`` is.

WHY ALL REFINABLE FACTORS, NOT A SUBSET. With a 2-level design, every pure
quadratic column equals the intercept on the corners, so the curvature
contrast is the SUM of the pure quadratic effects and cannot be attributed to
any one factor. ``_build_design`` already builds refine's composite over every
refinable factor (not over the survivors), so no selection rule is needed and
none is invented here. Non-refinable factors are held at the screen's
recommendation (``stage_runner``'s held-fixed rule): pure quadratic terms are
aliased only with the intercept in a 2-level factorial plus centre points, so
the main-effect and interaction coefficients that recommendation is the argmax
of are unbiased by the curvature the test detected.

WHY NO NEW OBSERVATION KEY. "Is at least one factor refinable?" is a fact about
the campaign's DECLARATION, known at compile time, and the rule is registered
only when it holds (``refine_on``). A runtime ``refinable_factors`` count would
put the same fact in two places and let them drift -- the argument the foldover
registration makes about resolution.

WHY IT IS NOT ADAPTIVE SEARCH (spec §5). The branch is pre-registered, fires on
one named test at a stated alpha, and leads to a fixed design family; it reads
one closed-vocabulary boolean. Its error is accounted at the test's alpha, and
what follows it is the refine stage's own registered accounting.

ORDER. After the consequential-alias foldover (resolve confounded linear terms
first) and after the survivors rule (which also routes to refine and keeps its
own accounting label when both hold).
"""


def _curvature_rule(state: str) -> dict:
    return {"from": state, "when": {"lack_of_fit": True}, "to": "refine",
            "accounting": CURVATURE_ACCOUNTING}


FRONT_GAP_ACCOUNTING = "front gap fill, Bonferroni over rounds"
"""The accounting rule of the registered multi-objective gap-fill branch.

``confirm -> confirm`` when the measured front has a gap wider than twice the
largest normalised epsilon and a round remains: the next round seats
predicted-front candidates inside the largest gaps. Every round's front claims
are made at ``delta_terminal / max_rounds`` (Bonferroni over the registered
rounds), so looping cannot buy a claim the round cap did not pay for.
"""


REFILL_ACCOUNTING = (
    "refill vacated seats: one round, Bonferroni over the rounds actually "
    "spent, CRN-paired with the surviving finalists' replicates"
)
"""The accounting rule of the registered refill branch (constrained campaigns).

``confirm -> confirm`` once, when a round measured finalists inadmissible and
fewer than two admissible finalists remain: with no admissible rival the
terminal bound is vacuous, so the vacated seats are refilled from the
supported-feasible pool first, then the constraint-filtered ranking, never with
a configuration already measured inadmissible. Capped at ONE round regardless of
``confirm_max_rounds`` (so the default single-round campaign benefits); the
refill round's terminal bound is taken at ``delta_terminal / rounds spent``, and
its survivors share the round's replicate seeds with the new seats.
"""

ALLOCATE_ACCOUNTING = (
    "allocate round (WP-D D1): seats chosen on the fitted model's predictions "
    "(knowledge gradient / EHVI per run), claims on their fresh replicates only; "
    "one registered look, Bonferroni over rounds as for gap fill"
)
"""The accounting rule of the opt-in allocate branch (``design.confirm.allocate``).

``confirm -> confirm`` once per epoch, AT the round cap, when that round did
not certify and the allocator (``allocate.allocate``, through
``allocate_seat.plan``) found a seatable candidate with a free seat on an
ADEQUATE model. Multi-objective campaigns ALSO seat allocator picks in the
registered gap-fill rounds below the cap (``FRONT_GAP_ACCOUNTING``), each
already a charged look, so there the allocator may seat in several rounds
while the allocate RULE itself still fires at most once. Statistics owns inference, decision
theory owns allocation: the seats are SELECTED on predictions (recombination
of the values the measured finalists / front points disagree on, the predicted
front or ranked candidates, optional BO proposals), but every claim about a
seat rests on its fresh paired replicates, and its certificate is the ordinary
terminal or front certificate. No predicted value enters any bound. The branch
is ONE look, charged to ``confirm_looks`` and to the P3 replicate floor
whether or not it is taken (a per-look level must be fixed before the data
decide how many looks there are), exactly like the refill look.
"""


def _allocate_cfg(opt: dict) -> dict | None:
    """``design.confirm.allocate`` when declared (opt-in), else ``None``."""
    a = ((opt.get("design") or {}).get("confirm") or {}).get("allocate")
    return a if isinstance(a, dict) else None


#: Whether constrained campaigns register the refill branch. Not a campaign
#: knob: it exists so the metamorphic oracle can compile the same campaign with
#: and without the branch.
_REFILL_VACATED = True


def _multi_objective_block(opt: dict) -> dict | None:
    """``objective.objectives`` / ``objective.preference`` for a multi-objective
    campaign (``None`` for single-objective, which keeps its policy identical)."""
    from orchestrator.optimize.objectives import (
        DEFAULT_PREFERENCE,
        declared_objectives,
        epsilon_spec_for,
        is_multi_objective,
    )

    if not is_multi_objective(opt):
        return None
    objs = declared_objectives(opt)
    pref_raw = ((opt.get("response") or {}).get("preference") or {})
    pref = {"method": pref_raw.get("method") or DEFAULT_PREFERENCE}
    # Resolved to the DECLARED objective names here, once: the validator
    # compares names case/whitespace-insensitively, and the runtime looks them
    # up exactly, so an author's `F1:` weight would otherwise weigh nothing.
    from orchestrator.optimize.objectives import resolve_metric

    metrics = [o["metric"] for o in objs]
    if pref["method"] == "weights":
        pref["weights"] = {resolve_metric(k, metrics) or k: float(v)
                           for k, v in (pref_raw.get("weights") or {}).items()}
    if pref["method"] == "lexicographic":
        pref["order"] = [resolve_metric(m, metrics) or m
                         for m in (pref_raw.get("order") or metrics)]
    return {
        "objectives": [{"metric": o["metric"], "direction": o["direction"],
                        "epsilon": epsilon_spec_for(opt, o["metric"])} for o in objs],
        "preference": pref,
    }


VALIDATE_ACCOUNTING = (
    "post-selection validation block (#321): the winner is fixed by confirm "
    "before these replicates are drawn, so they are independent of the "
    "selection; reported value, gain point estimate and epsilon reference come "
    "from them only; no certificate is decided here"
)


INERTNESS_ACCOUNTING = (
    "held-factor inertness (#321): TOST (Schuirmann 1987) of each held-factor "
    "flip vs the winner at a declared margin; each flip's two one-sided tests "
    "at delta_terminal / F (F flips, Bonferroni, so the family of 'shown "
    "inert' verdicts is wrong with probability <= delta_terminal; each TOST is "
    "an intersection-union test, so its size is its one-sided level); widens "
    "the certificate's scope statement only, decides no certificate"
)


def _constraint_exclusion_registered(opt: dict) -> bool:
    """Can a constraint model exclude candidates in this epoch? True when a
    declared constraint has a violating side (``<``, ``<=``, ``>``, ``>=``)
    and no ``when`` guard -- the constraints ``constraint_models`` may model.
    A pure function of the declaration, so the term is fixed before data."""
    for c in (opt.get("response") or {}).get("constraints") or ():
        if isinstance(c, dict) and c.get("op") in ("<", "<=", ">", ">=") \
                and "when" not in c and "when_not" not in c:
            return True
    return False


def _feasibility_registered(opt: dict) -> bool:
    """Is a distributional constraint (``semantics: mean | chance:<a>``)
    declared? Then confirm decides feasibility statistically and the
    ``delta_feasibility`` union term is registered (#321 P3 item 3)."""
    return any(isinstance(c, dict) and c.get("semantics", "every_replicate")
               != "every_replicate"
               for c in (opt.get("response") or {}).get("constraints") or ())


def campaign_delta_share(spec: dict | None, epoch: int) -> float | None:
    """Epoch ``epoch``'s share of a declared campaign-wide budget (#321 item 7).

    ``spec`` is ``optimization.policy.campaign_delta``: ``{total: D,
    schedule: "geometric"}`` gives ``D / 2^e`` (so the sum over every epoch
    is at most ``D``), and ``{total: D, schedule: [d_1, d_2, ...]}`` gives
    ``d_e`` (the validator checks ``sum d_e <= D``) and ``0`` past the list
    -- an exhausted budget, which certifies nothing. A pure function of the
    declaration and the epoch index, so every share is fixed before any data:
    Pr(any epoch certifies wrongly) <= sum_e share_e <= D by the union bound,
    however the epochs were chosen (each later epoch is compiled after the
    earlier data were seen, which is why only a union bound is claimed).
    ``None`` when the mode is not declared."""
    if not spec:
        return None
    total = float(spec["total"])
    sched = spec.get("schedule", "geometric")
    if sched == "geometric":
        return total / (2 ** int(epoch))
    lst = [float(x) for x in sched]
    return lst[epoch - 1] if 1 <= epoch <= len(lst) else 0.0


#: The registered M3 check (#321 P3 item 1). See ``noise.brown_forsythe``.
_HETERO_RULE = {
    "alpha": 0.05,
    "method": "brown_forsythe_one_sided_contrast_finalists_vs_pure_error",
    "groups": "the fitting stage's pure-error cells against every admissible "
              "confirm finalist with >= 2 replicates",
    "role": "veto: a rejection (p < alpha) or an untestable spread withholds "
            "the model half (heteroscedastic_pure_error / "
            "heteroscedasticity_not_testable); it never certifies, so it "
            "spends no part of delta",
}


#: A5 skewness pretest level (a veto; spends no delta). Fixed a priori at the
#: level recommended for PRELIMINARY tests of an assumption, where a type II
#: error (missing the violation) is the costly one: 0.25 (Bancroft 1964,
#: Biometrics 20, 427-442; Kennedy & Bancroft 1971, Technometrics 13, 899-913).
#: Not tuned on the reported Monte-Carlo cells (spec §7 records the tuning-free
#: evaluation on a fresh seed set). Its cost: under normal noise it vetoes
#: ~25% of otherwise-certifiable confirm rounds.
TERMINAL_SKEW_ALPHA = 0.25


def _registered_looks(opt: dict) -> int:
    """``confirm_looks`` from the declaration, before the transitions exist:
    the round cap, plus the refill look when that branch will be compiled
    (``_REFILL_VACATED`` and any declared constraint), plus the allocate look
    when ``design.confirm.allocate`` is declared."""
    pol_cfg = opt.get("policy") or {}
    rounds = int(pol_cfg.get("confirm_max_rounds", 1) or 1)
    refill = bool(_REFILL_VACATED and (opt.get("response") or {}).get("constraints"))
    # The opt-in allocate look (WP-D D1), charged whether or not it is taken.
    allocate = _allocate_cfg(opt) is not None
    return max(1, rounds) + (1 if refill else 0) + (1 if allocate else 0)


def effective_delta_terminal(opt: dict, epoch: int = 1) -> float:
    """``delta_terminal`` as confirm will actually spend it: the declared value,
    scaled by the charged cross-epoch share when ``campaign_delta`` is declared
    (P3 review H2: a floor computed from the unscaled value was too small, so
    the charged mode could never certify). A function of the declaration and
    the epoch index only."""
    pol_cfg = opt.get("policy") or {}
    dt = float(pol_cfg.get("delta_terminal", 0.05))
    share = campaign_delta_share(pol_cfg.get("campaign_delta"), int(epoch))
    if share is None or not share > 0.0:
        return dt
    ds = float(pol_cfg.get("delta_screen", 0.05))
    dc = (float(pol_cfg.get("delta_constraint", ds))
          if _constraint_exclusion_registered(opt) else 0.0)
    df = (float(pol_cfg.get("delta_feasibility", dt))
          if _feasibility_registered(opt) else 0.0)   # same default as compile
    return dt * share / (ds + dt + dc + df)


def replicate_floor(opt: dict, epoch: int = 1) -> int:
    """The A5 replicate floor (#321 P3 item 2) for a single-objective campaign:
    the smallest n with ``2^-n <= delta_t / (L (S - 1))`` -- the exact
    sign-flip bound's existence condition at the per-look, per-challenger
    level, at the delta_terminal the epoch will spend. A function of the
    declaration and the epoch index only."""
    from orchestrator.optimize.noise import sign_flip_floor

    confirm_cfg = (opt.get("design") or {}).get("confirm") or {}
    dt = effective_delta_terminal(opt, epoch)
    seats = int(confirm_cfg.get("shortlist_size", 3)) + (
        1 if opt.get("known_valid_baseline") else 0)
    alpha = dt / _registered_looks(opt) / max(1, seats - 1)
    return sign_flip_floor(alpha)


def default_confirm_replicates(opt: dict, epoch: int = 1) -> int:
    """The single-objective default for ``design.confirm.replicates``: the A5
    floor (#321 P3). Was 3, at which no bound holds its level under skewed,
    heteroscedastic noise (spec §7)."""
    return replicate_floor(opt, epoch)


def terminal_robustness_rule(pol_cfg: dict, campaign: dict, *, looks: int,
                             epoch: int = 1) -> dict:
    """The registered A5 rule (#321 P3 item 2), a function of the declaration.

    ``floor`` is the smallest replicate count at which the robust bound exists
    at the per-look, per-challenger level ``delta_t / (L (S - 1))``: the exact
    sign-flip bound needs ``2^-n <= alpha``. It is computed here from the
    declared ``delta_terminal``, the registered looks and shortlist size --
    never from data. Unpaired campaigns use the same floor (the bootstrap-t is
    not exact, and measured below this n it is not within level either).
    """
    from orchestrator.optimize.noise import sign_flip_floor

    opt = campaign.get("optimization") or {}
    design = opt.get("design") or {}
    confirm_cfg = design.get("confirm") or {}
    dt = effective_delta_terminal(opt, epoch)
    assert looks == _registered_looks(opt), (looks, _registered_looks(opt))
    # The floor is computed at the delta_terminal confirm SPENDS: under the
    # charged cross-epoch mode that is the scaled share (P3 review H2).
    seats = int(confirm_cfg.get("shortlist_size", 3)) + (
        1 if opt.get("known_valid_baseline") else 0)
    alpha = dt / max(1, looks) / max(1, seats - 1)
    return {"floor": sign_flip_floor(alpha), "skew_alpha": TERMINAL_SKEW_ALPHA,
            "level_for_floor": alpha,
            "method": "per challenger max(paired t, exact sign-flip (Hartigan "
                      "1969)) under CRN, max(Welch, bootstrap-t (Hall 1988)) "
                      "otherwise, Bonferroni over challengers and looks; "
                      "withheld below the replicate floor or when the "
                      "studentized-third-moment pretest rejects at skew_alpha"}


def delta_stated(policy: dict) -> float:
    """The epoch's stated error budget: ``delta_screen + delta_terminal``,
    plus ``delta_constraint`` when constraint exclusion is registered, plus
    ``delta_feasibility`` when a distributional constraint is (#321 P3)."""
    o = policy["objective"]
    return (float(o["delta_screen"]) + float(o["delta_terminal"])
            + float(o.get("delta_constraint") or 0.0)
            + float(o.get("delta_feasibility") or 0.0))


#: Reanalysis of a policy compiled before #321 P3 (no ``terminal_robustness``
#: key) sets this, so the recompiled policy -- and every artifact read from it
#: -- is the one that epoch registered: no noise checks, confirm replicates
#: defaulting to 3. Never set on a live campaign.
LEGACY_PRE_P3 = __import__("contextvars").ContextVar("nous_legacy_pre_p3", default=False)


def compile_policy(campaign: dict, *, mechanism_patch_hash: str = "", epoch: int = 1,
                   run_order_salt: str | None = None) -> dict:
    opt = campaign.get("optimization") or {}
    factors = parse_factors(opt["factors"])
    design = opt.get("design") or {}
    pol_cfg = opt.get("policy") or {}
    enabled = _enabled(campaign)
    refine_on = "refine" in enabled and any(is_refinable(f) for f in factors)
    confirm_on = "confirm" in enabled
    # The registered foldover is ON BY DEFAULT and gated at RUNTIME, not at
    # compile time. Compilation cannot know whether any alias will turn out
    # consequential — that is a fact about measurements, and a policy that reads
    # a measurement is not a pre-registration. So the branch is always
    # registered when the state exists, and `alias_consequential` /
    # `foldover_affordable` decide whether it fires. A campaign that would
    # rather never spend the block says so explicitly with
    # `optimization.policy.foldover: false`, which removes the state and the
    # branch together — a registered branch that can never fire is worse than an
    # absent one, because `enumerate_paths` would report a path the campaign
    # cannot take.
    #
    # Deliberately NOT gated on the screen design's resolution either. A
    # resolution-V screen aliases nothing, so `alias_consequential` returns []
    # and the branch simply never fires; making the state's existence depend on
    # `design.screen.resolution` would put the same fact in two places and let
    # them drift.
    fold_on = bool(pol_cfg.get("foldover", True))
    primary = (opt.get("response") or {}).get("primary") or {}
    confirm_cfg = design.get("confirm") or {}
    mo = _multi_objective_block(opt)
    if mo is not None:
        # The FIRST objective plays the primary's role wherever the
        # single-objective machinery needs one metric (the stage rule's fit,
        # effects.json, the NaN guard); every objective is fitted and the front
        # is what the campaign reports.
        primary = {"metric": mo["objectives"][0]["metric"],
                   "direction": mo["objectives"][0]["direction"]}
    # Multi-objective defaults (spec decision): a front needs more seats than a
    # single argmax -- one extreme measured and one predicted per objective,
    # the knee, and a spread point -- and the registered gap-fill branch needs a
    # second round to exist at all. Explicit declarations always win.
    k_obj = len(mo["objectives"]) if mo else 0
    default_shortlist = 2 * k_obj + 2 if mo else 3
    default_rounds = 2 if mo else 1

    states: dict = {
        "screen": {
            "spends": True,
            "design": {"kind": "screen",
                       "resolution": int((design.get("screen") or {}).get("resolution", 5)),
                       "center_points": int((design.get("screen") or {}).get("center_points", 4))},
            "estimator": "ols_orthogonal_closed_form",
            "accounting": "per_term_t_on_pure_error",
        },
        "report": {"spends": False, "terminal": True},
        "exception": {"spends": False, "terminal": True, "ends_epoch": True},
    }
    if fold_on:
        states["foldover"] = {
            # SPENDS is the whole point. A state that only reported the
            # confounding would be the spec's own named defect — "diagnosis
            # without action", the `Trigger` enum documented as "reported, not
            # acted on". The paper is explicit: "if one flips the winner, the
            # policy SPENDS its registered foldover." This state executes a
            # second block of benchmark runs and produces new measurements.
            "spends": True,
            # Not a design family: the block is derived from whatever the screen
            # actually built, so the design is named by REFERENCE to that state
            # rather than by parameters that could disagree with it.
            "design": {"kind": "foldover_of", "state": "screen"},
            "estimator": "ols_orthogonal_closed_form",
            "accounting": (
                "combined OLS over screen ∪ foldover runs; per-term t on "
                "pooled pure error"
            ),
        }
    if refine_on:
        states["refine"] = {
            "spends": True,
            "design": {"kind": "central_composite",
                       "center_points": int((design.get("refine") or {}).get("center_points", 4)),
                       # WP-B (spec 2026-10-17): the held-out validation block
                       # and the sequential-assembly option are part of the
                       # pre-registration, so they are in the hashed policy.
                       "validation_points": max(0, int((design.get("refine") or {}).get(
                           "validation_points", 4))),
                       "validation_seed": int((design.get("refine") or {}).get(
                           "validation_seed", 0)),
                       "reuse_screen": bool((design.get("refine") or {}).get(
                           "reuse_screen", False))},
            "estimator": "ols_normal_equations",
            "accounting": ("per_term_t_on_pure_error; validation points held out, "
                           "joint predictive F at alpha 0.05 (a rejection makes "
                           "model_adequate false)"),
        }
    if confirm_on:
        states["confirm"] = {
            "spends": True,
            # `shortlist_size: 3` is the DEFAULT because the terminal state is
            # discrimination, not replication (spec §3.3): one configuration
            # replicated only measures how repeatable it is, and whether it is
            # the BEST configuration then remains a claim about the fitted
            # surface. Three finalists is the smallest shortlist that can
            # actually discriminate while keeping the Bonferroni divisor small.
            # `1` is still legal and reproduces the old single-point confirm
            # exactly, which is what the legacy tests declare explicitly.
            "design": {"kind": "shortlist_replicate",
                       "shortlist_size": int(confirm_cfg.get("shortlist_size",
                                                             default_shortlist)),
                       # #321 P3 (A5): single-objective defaults to the
                       # registered replicate floor (6 at the defaults), the
                       # smallest n at which the robust terminal bound exists.
                       "replicates": max(1, int(confirm_cfg.get(
                           "replicates",
                           3 if (mo or LEGACY_PRE_P3.get())
                           else default_confirm_replicates(opt, int(epoch))))),
                       "max_rounds": int(pol_cfg.get("confirm_max_rounds",
                                                     default_rounds)),
                       # WP-D D1 (opt-in): present only when declared, so
                       # every other policy is byte-identical.
                       **({"allocate": {"seats": int(_allocate_cfg(opt).get("seats", 1))}}
                          if _allocate_cfg(opt) is not None else {})},
            "estimator": "sample_means",
            # Bonferroni, not Holm. Holm is uniformly more powerful for
            # TESTING, but the terminal artifact is a BOUND (`R_delta`), and
            # Holm's step-down thresholds do not invert into a simultaneous
            # one-sided interval the way a fixed `delta/M` does — the
            # threshold a hypothesis is judged at depends on how many others
            # were already rejected, so there is no single level to attach to
            # the reported number. See certificate.terminal_regret_bound.
            "accounting": "bonferroni_one_sided_welch_t",
        }

    after_refine = "confirm" if confirm_on else "report"
    out_of_hull = str(pol_cfg.get("out_of_hull") or "confirm")
    sem = "none: semantic exception ends the epoch, no inference is drawn"
    transitions: list[dict] = [
        {"from": "screen", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
        {"from": "screen", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
    ]
    # BEFORE the refine rule, and the order is load-bearing. `step` takes the
    # FIRST matching rule, so registering the foldover after refine would mean a
    # screen with both refinable survivors and a consequential alias goes
    # straight to refine — fitting curvature on a surface whose linear terms are
    # still confounded, which is the more expensive stage resting on the weaker
    # model. Resolve the alias first, then refine on coefficients that mean what
    # they say.
    fold_rule = {
        "from": "screen",
        "when": {"alias_consequential": True, "foldover_affordable": True},
        "to": "foldover",
        "accounting": (
            "combined OLS over screen ∪ foldover runs; per-term t on pooled "
            "pure error"
        ),
    }
    if fold_on:
        transitions.append(dict(fold_rule))
    if refine_on:
        transitions.append({"from": "screen", "when": {"refinable_survivors": {">": 0}}, "to": "refine",
                            "accounting": "screen selection at alpha=0.05 per main effect (Task 8 adds regret)"})
        transitions.append(dict(_curvature_rule("screen")))
    transitions.append({"from": "screen", "default": ("confirm" if confirm_on else "report")})
    if fold_on:
        # Foldover carries SCREEN's rules MINUS the foldover rule — one fold per
        # screen, by registration. The alias the block was spent on is resolved,
        # so a second fold could only chase a different alias with runs the
        # budget already committed here; and the absent self-branch is what makes
        # `enumerate_paths` finite without needing a decreasing-budget argument.
        transitions += [
            {"from": "foldover", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "foldover", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
        ]
        if refine_on:
            transitions.append({
                "from": "foldover", "when": {"refinable_survivors": {">": 0}},
                "to": "refine",
                "accounting": "screen selection at alpha=0.05 per main effect on the combined fit",
            })
            transitions.append(dict(_curvature_rule("foldover")))
        transitions.append(
            {"from": "foldover", "default": ("confirm" if confirm_on else "report")},
        )
    if refine_on:
        transitions += [
            {"from": "refine", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "refine", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
            # THE DECLARED RANGES DO NOT CONTAIN THE OPTIMUM — a defect in the
            # factor's DEFINITION, which no additional measurement inside those
            # ranges repairs (paper, "the one way back": the threshold expressed
            # in tokens while the allocator works in pages). So this is a
            # semantic exception, not a branch: the epoch ends, an agent may
            # widen the ranges, and recompilation starts a new epoch.
            #
            # DELIBERATELY NOT a `lack_of_fit` rule HERE (screen and foldover
            # do carry one -- CURVATURE_ACCOUNTING -- because their first-order
            # design has a registered second-order augmentation; refine's design
            # IS that augmentation, and there is no higher registered family to
            # climb to). Model inadequacy IS named
            # by the policy — refine's registered augmentation is confirm's
            # fresh measurements — so it routes to `confirm` on the default with
            # `recommendation.json["model_adequate"] = false`, which is what
            # makes `_confirm_rows` build finalists from MEASURED valid rows
            # instead of from the model's untrusted pick (paper: "remeasures the
            # leading measured valid candidates rather than choosing the largest
            # noisy observation"). An out-of-hull optimum is different in kind:
            # no amount of remeasurement inside the hull finds a point outside
            # it.
            #
            # That reading holds when the declared ranges are an author's GUESS.
            # When they are the system's LIMITS -- concurrency >= 1, GOMAXPROCS
            # <= cores, a memory budget -- the optimum on the boundary IS the
            # answer, and ending the epoch handed back one unreplicated row
            # (found on a real multi-repo Go campaign, three axes at their
            # edges). So the default `out_of_hull: confirm` registers a BRANCH:
            # confirm the constrained argmax inside the hull, with a certificate
            # whose scope is the declared ranges (report.md names the axes to
            # widen). `end_epoch` keeps the exception.
            ({"from": "refine", "when": {"stationary_in_hull": False}, "to": "exception",
              "accounting": sem}
             if out_of_hull == "end_epoch" else
             {"from": "refine", "when": {"stationary_in_hull": False}, "to": after_refine,
              "accounting": (
                  "registered boundary branch: the fitted optimum lies past the "
                  "declared ranges; the best configuration INSIDE them is "
                  "confirmed, and any certificate is scoped to those ranges"
              )}),
            {"from": "refine", "default": after_refine},
        ]
    if confirm_on:
        transitions += [
            {"from": "confirm", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "confirm", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
        ]
        if _REFILL_VACATED and (opt.get("response") or {}).get("constraints"):
            # FIRST after the semantic guards -- before gap fill, certification and
            # every decline guard: a round
            # whose finalists were measured inadmissible has no admissible rival
            # to bound against, so neither a certificate nor a decline is the
            # right reading of it. Its own guard carries affordability, so it
            # cannot outlive the budget; `refill_available` caps it at one round
            # whatever `confirm_max_rounds` says. It fires only AT the round cap:
            # while registered rounds remain, the default `confirm -> confirm`
            # already re-fills the shortlist from deeper in the ranking, so the
            # refill is the one extra round a capped epoch would otherwise lack
            # (the default single-round campaign is exactly that case). Registered only when
            # constraints are declared -- the only way a finalist is vacated by
            # a measurement -- so an unconstrained policy is unchanged.
            transitions.append({
                "from": "confirm",
                "when": {"finalists_vacated": {">": 0}, "feasible_finalists": {"<": 2},
                         "refill_available": True, "confirm_affordable": True,
                         "round": {">=": states["confirm"]["design"]["max_rounds"]}},
                "to": "confirm", "accounting": REFILL_ACCOUNTING,
            })
        if mo is not None:
            # BEFORE `certified`: the multi-objective epoch's product is the
            # FRONT, and a certified preferred point with a wide unexplored
            # gap beside it has answered the smaller question. Guarded on the
            # round cap and affordability so it can never outlive them.
            transitions.append({
                "from": "confirm",
                "when": {"front_gap_large": True, "confirm_affordable": True,
                         "round": {"<": states["confirm"]["design"]["max_rounds"]}},
                "to": "confirm", "accounting": FRONT_GAP_ACCOUNTING,
            })
        transitions += [
            {"from": "confirm", "when": {"certified": True}, "to": "report",
             "accounting": ("bonferroni_one_sided_welch_t at delta_terminal / "
                            "confirm_looks over |S|-1 finalists, plus the model "
                            "bound at delta_screen (spec 2026-10-17-"
                            "certification-soundness)")},
        ]
        if "allocate" in states["confirm"]["design"]:
            # AFTER `certified` (a certified round has nothing for allocation to
            # buy) and BEFORE every decline guard, like the refill: it fires
            # only AT the round cap, so it is exactly the one extra look
            # `confirm_looks` charges, and `allocate_available` caps it at one
            # round. Its own guard carries affordability.
            transitions.append({
                "from": "confirm",
                "when": {"allocate_available": True, "confirm_affordable": True,
                         "round": {">=": states["confirm"]["design"]["max_rounds"]}},
                "to": "confirm", "accounting": ALLOCATE_ACCOUNTING,
            })
        transitions += [
            # BEFORE both budget guards below, and the order is load-bearing for
            # the same reason the foldover rule precedes refine: `step` takes the
            # FIRST matching rule, and `budget_remaining < 1` only fires once
            # literally nothing is left. "Two runs remain but the next round of
            # terminal discrimination needs nine" is affordable by that guard's
            # standard and unaffordable in fact, so without this rule the epoch
            # self-loops into a round it cannot complete and the shortfall
            # surfaces as failed runs instead of as a registered decline.
            #
            # `confirm_affordable` is derived in the runtime (stage_runner) for
            # the reason documented at OBSERVATION_KEYS: a `when` predicate
            # compares an observation against a constant, never against another
            # observation, so `budget_remaining >= runs_needed_confirm` is
            # evaluated where both numbers are known and the VERDICT is what this
            # guard reads.
            #
            # Routes to `report`, not `exception`: this is a REGISTERED BRANCH
            # declining to spend, not a semantic exception. Nothing about the
            # measurements became uninterpretable — the campaign has a winner
            # from the rounds it did run, just no certificate — which is exactly
            # how the round cap and the exhausted-budget guard below both end,
            # and how an unaffordable foldover is declined at `screen`.
            {"from": "confirm", "when": {"confirm_affordable": False}, "to": "report",
             "accounting": (
                 "registered decline: the next round of terminal discrimination "
                 "costs more runs than the budget has left, so no further "
                 "comparison is made and no inference is drawn from runs not "
                 "taken; report uncertified on the rounds already completed"
             )},
            {"from": "confirm", "when": {"round": {">=": states["confirm"]["design"]["max_rounds"]}},
             "to": "report", "accounting": "registered round cap; report uncertified"},
            {"from": "confirm", "when": {"budget_remaining": {"<": 1}}, "to": "report",
             "accounting": "budget exhausted; report uncertified"},
            {"from": "confirm", "default": "confirm"},
        ]

    # ── #321 item 2: the post-selection validation block ───────────────────
    # Registered only when `design.validate.replicates` is declared AND a
    # single-objective campaign has a known_valid_baseline to compare with
    # (the validator refuses the block otherwise). Every `confirm -> report`
    # exit is redirected through `validate`, so the block runs whichever rule
    # ended confirm; `validate` itself always ends at `report` (a semantic
    # NaN is the one exception). Compile-time facts only.
    val_cfg = design.get("validate") or {}
    validate_on = (confirm_on and val_cfg.get("replicates") is not None
                   and bool(opt.get("known_valid_baseline")) and mo is None)
    if validate_on:
        states["validate"] = {
            "spends": True,
            "design": {"kind": "validation_replicate",
                       "replicates": int(val_cfg["replicates"])},
            "estimator": ("paired differences winner - baseline on fresh "
                          "replicates sharing workload seeds (CRN); two-sided "
                          "Student t at delta_terminal"),
            "accounting": VALIDATE_ACCOUNTING,
        }
        for t in transitions:
            if t.get("from") == "confirm" and t.get("to") == "report":
                t["to"] = "validate"
        transitions += [
            {"from": "validate", "when": {"nan_response": True}, "to": "exception",
             "accounting": sem},
            {"from": "validate", "default": "report"},
        ]

    cd_spec = pol_cfg.get("campaign_delta")
    share = campaign_delta_share(cd_spec, int(epoch))
    _ds = float(pol_cfg.get("delta_screen", 0.05))
    _dt = float(pol_cfg.get("delta_terminal", 0.05))
    _dc = (float(pol_cfg.get("delta_constraint", _ds))
           if _constraint_exclusion_registered(opt) else 0.0)
    _df = (float(pol_cfg.get("delta_feasibility", _dt))
           if _feasibility_registered(opt) else 0.0)
    cd_block = None
    if share is not None:
        # The epoch certifies at its SHARE, split over its union terms in the
        # declared proportions (delta_screen : delta_terminal [: delta_constraint]).
        declared = _ds + _dt + _dc + _df
        exhausted = not share > 0.0
        scale = (share / declared) if not exhausted else 1.0
        cd_block = {"total": float(cd_spec["total"]),
                    "schedule": cd_spec.get("schedule", "geometric"),
                    "epoch_share": float(share), "exhausted": bool(exhausted),
                    "declared_split": {"delta_screen": _ds, "delta_terminal": _dt,
                                       **({"delta_constraint": _dc} if _dc else {}),
                                       **({"delta_feasibility": _df} if _df else {})},
                    "rule": "epoch e certifies at share_e of the campaign-wide "
                            "budget, split in the declared proportions; "
                            "sum_e share_e <= total (union bound over epochs)"}
        if not exhausted:
            _ds, _dt, _dc, _df = _ds * scale, _dt * scale, _dc * scale, _df * scale

    # ── #321 item 8: held-factor inertness checks (opt-in) ─────────────────
    inert_cfg = design.get("inertness") or {}
    inert_on = (confirm_on and inert_cfg.get("replicates") is not None
                and mo is None)
    if inert_on:
        states["inertness"] = {
            "spends": True,
            "design": {"kind": "inertness_replicate",
                       "replicates": int(inert_cfg["replicates"]),
                       "margin": dict(inert_cfg.get("margin") or {"pct": 2.0})},
            "estimator": ("paired differences flip - winner on fresh replicates "
                          "sharing workload seeds; TOST (Schuirmann 1987) at the "
                          "declared margin, each one-sided test at delta_terminal"),
            "accounting": INERTNESS_ACCOUNTING,
        }
        # Every exit to `report` from confirm or validate passes through it.
        for t in transitions:
            if t.get("from") in ("confirm", "validate") and (
                    t.get("to") == "report" or t.get("default") == "report"):
                if "to" in t:
                    t["to"] = "inertness"
                else:
                    t["default"] = "inertness"
        transitions += [
            {"from": "inertness", "when": {"nan_response": True}, "to": "exception",
             "accounting": sem},
            {"from": "inertness", "default": "report"},
        ]

    policy = {
        "policy_version": 1,
        "epoch": int(epoch),
        "compiled_from": {
            "campaign_hash": hashlib.sha256(_canonical(opt).encode()).hexdigest(),
            "mechanism_patch_hash": mechanism_patch_hash or "",
            "factor_ids": [f.id for f in factors],
            "pre_epoch": pre_epoch_stages(campaign),
        },
        "objective": {
            "metric": primary.get("metric", ""),
            "direction": primary.get("direction", "maximize"),
            "epsilon": (dict(mo["objectives"][0]["epsilon"]) if mo
                        else dict(pol_cfg.get("epsilon") or {"pct": 2.0})),
            **(mo or {}),
            "delta_screen": _ds,
            "delta_terminal": _dt,
            # The THIRD union term (#321 P2 item 3). Constraint-model exclusion
            # removes a candidate whose one-sided bound sits confidently on the
            # violating side; the true constrained optimum x* is wrongly
            # removed with probability <= delta_constraint (Bonferroni over the
            # modelled constraints; only x*'s own exclusion matters, and x* is
            # fixed, not data-chosen). That event is distinct from the model
            # family E_s, so it is its own term in the stated sum. Registered
            # exactly when a constraint with a violating side is DECLARED --
            # known at compile time, never after the data -- and charged even
            # if the constraint later turns out unmodellable (conservative).
            # Defaults to delta_screen, the level exclusion always used.
            **({"delta_constraint": _dc}
               if _constraint_exclusion_registered(opt) else {}),
            # #321 P3 item 3: the FOURTH union term. A distributional constraint
            # (semantics mean | chance:<a>) is decided at confirm: each finalist
            # must be SHOWN feasible, per constraint, at delta_feasibility /
            # (S C L) -- Bonferroni over finalists, constraints and looks, so
            # the data-chosen winner is covered. Registered from the
            # declaration only. Defaults to delta_terminal.
            **({"delta_feasibility": _df} if _feasibility_registered(opt) else {}),
            # #321 item 7: the charged cross-epoch mode, when declared.
            **({"campaign_delta": cd_block} if cd_block is not None else {}),
            # #321 P3 item 1: the Brown-Forsythe check of M3 (pure error is
            # the error variance at every configuration). Registered, so its
            # level is fixed before any data; a VETO on the model half, so it
            # spends no delta. A policy compiled before P3 lacks the key and
            # confirm then skips the check (old epochs reproduce).
            **({"heteroscedasticity": dict(_HETERO_RULE)}
               if confirm_on and mo is None and not LEGACY_PRE_P3.get() else {}),
            # #321 P3 item 2 (A5): the robust terminal family, its replicate
            # floor and the skewness pretest, all fixed at compile time.
            **({"terminal_robustness": terminal_robustness_rule(
                pol_cfg, campaign, epoch=int(epoch), looks=confirm_looks(
                    {"states": states, "transitions": transitions}))}
               if confirm_on and mo is None and not LEGACY_PRE_P3.get() else {}),
        },
        "budget": {"max_runs": design.get("max_runs")},
        "known_valid_baseline": opt.get("known_valid_baseline"),
        "workload": opt.get("workload"),
        "initial": "screen",
        "states": states,
        "transitions": transitions,
    }
    if run_order_salt:
        # Run-order concealment (#321): the salt is a random draw recorded at
        # compile (run_order.epoch-<e>.json) and compiled INTO the policy, so
        # it is covered by policy.sha256 and a reader can recompute every
        # run order from the record. Absent block = derivation 1 (the
        # iteration index), which every policy written before this existed
        # uses; run_order_seed() keeps reproducing those.
        policy["run_order"] = {"derivation": RUN_ORDER_DERIVATION,
                               "salt": str(run_order_salt)}
    # WP-D (#320): the planning tools' declarations (the optional BO
    # proposer's sampler/n_startup/seed, plan-next's stopping threshold and
    # campaign run budget) are compiled into the policy and hashed with it, so
    # they are fixed before any data of this epoch. Present only when declared,
    # so every other policy is byte-identical. Allocation only: nothing
    # certifies from them.
    _pl = opt.get("planner") or {}
    if _pl:
        _pc: dict = {}
        if _pl.get("bo") is not None:
            _bo = _pl["bo"]
            _pc["bo"] = {"sampler": str(_bo.get("sampler", "tpe")),
                         "n_startup": int(_bo.get("n_startup", 10)),
                         "seed": int(_bo.get("seed", 0))}
        if _pl.get("stop_value_per_run") is not None:
            _pc["stop_value_per_run"] = float(_pl["stop_value_per_run"])
        if _pl.get("campaign_max_runs") is not None:
            _pc["campaign_max_runs"] = int(_pl["campaign_max_runs"])
        policy["planner"] = _pc
    _sanity = {t["from"] for t in transitions if "default" in t}
    assert {s for s, v in states.items() if not v.get("terminal")} <= _sanity
    from orchestrator.optimize.invariants import (
        InvariantViolation,
        check_curvature_routes_to_refine,
    )
    curvature_errs = check_curvature_routes_to_refine(policy)
    if curvature_errs:  # INV-SEM16
        raise InvariantViolation("INV-SEM16", curvature_errs)
    return policy


def policy_hash(policy: dict) -> str:
    return hashlib.sha256(_canonical(policy).encode()).hexdigest()


#: The current run-order seed derivation. 1 = the iteration index (identical
#: across campaigns: reproducible, not concealed). 2 = sha256 over the policy
#: hash (which covers the recorded salt) and the iteration.
RUN_ORDER_DERIVATION = 2


def run_order_seed(policy: dict | None, iteration: int) -> int:
    """The seed every run-order permutation (and every derived workload seed)
    of ``iteration`` is drawn from, under the derivation ``policy`` registered.

    A policy with no ``run_order`` block was compiled before concealment
    existed (or by a campaign pinned to derivation 1): the seed is the
    iteration, exactly as before, so old campaigns reproduce byte for byte.
    """
    ro = (policy or {}).get("run_order") or {}
    if int(ro.get("derivation") or 1) < 2:
        return int(iteration)
    digest = hashlib.sha256(
        f"nous-run-order-v2|{policy_hash(policy)}|{int(iteration)}".encode()).hexdigest()
    return int(digest[:15], 16) % (2 ** 31)


def write_policy(work_dir: Path, policy: dict) -> Path:
    """Write the compiled policy and its content hash, or raise.

    ``POLICY_SCHEMA_PATH`` existed from Task 4 but nothing in production ever
    called ``jsonschema.validate`` against it — ``check_policy`` covers the
    closed observation/operator vocabulary and reachability, not the schema's
    own shape constraints (``policy_version`` pinned to 1,
    ``additionalProperties: false``, the ``epsilon`` ``abs``/``pct``
    ``oneOf``, the delta bounds). A schema file nothing validates against is
    the same phantom-check failure mode this branch closed for
    ``report.json``/``recommendation.json``/``confirmation.json``/
    ``shortlist.json`` — this is the fifth and last of the same class of gap,
    and the one every downstream artifact's own pre-registration hash
    ultimately rests on.
    """
    import jsonschema

    schema = json.loads(POLICY_SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(policy, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"compiled policy does not conform to {POLICY_SCHEMA_PATH.name}: "
            f"{exc.message} (at {'/'.join(str(p) for p in exc.absolute_path) or '<root>'})",
        ) from exc
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    p = work_dir / "policy.json"
    p.write_text(json.dumps(policy, indent=2, sort_keys=True))
    (work_dir / "policy.sha256").write_text(policy_hash(policy) + "\n")
    return p


def read_policy(work_dir: Path) -> dict | None:
    p = Path(work_dir) / "policy.json"
    return json.loads(p.read_text()) if p.exists() else None


def verify_policy_registration(work_dir: Path) -> list[str]:
    """Is the pre-registration on disk INTACT? Returns violations, or empty.

    ``INV-PROV01`` in ``docs/optimization-invariants.md``. The pair
    ``policy.json`` + ``policy.sha256`` is what makes a pre-registration
    checkable, and the invariant is that the document must both HAVE a sidecar
    and AGREE with it — **absence is as fatal as disagreement**.

    WHY THIS EXISTS AS ITS OWN FUNCTION. ``_load_or_compile_policy``'s guard is
    ``if recorded.exists() and recorded.read_text().strip() != policy_hash(pol)``,
    so deleting ``policy.sha256`` does not fail the check — it SKIPS it, and
    nothing downstream regenerates the sidecar or notices its absence
    (``_compile_and_write_policy`` is reached only when ``pol is None``).
    Verified end to end: with the sidecar deleted and ``screen``'s
    ``default: confirm`` rewritten to ``default: report`` — removing terminal
    discrimination from a pre-registered design — the epoch ran to completion and
    wrote a ``report.json`` claiming ``basis: model`` with no
    ``confirmation.json`` anywhere, and the tampered hash was recorded in
    ``transitions.jsonl`` as though it were the registration.

    A pre-registration whose only proof of integrity can be removed by deleting
    a file is not a pre-registration. This returns the finding rather than
    raising so the caller decides the blast radius (``stage_runner`` raises
    ``OptimizationAborted``; an audit tool reports). ``read_policy`` returning
    ``None`` — nothing registered yet — is a different state, not a violation.
    """
    work_dir = Path(work_dir)
    doc = work_dir / "policy.json"
    if not doc.exists():
        return []
    sidecar = work_dir / "policy.sha256"
    if not sidecar.exists():
        return [
            "policy.json exists with no policy.sha256. The sidecar's ABSENCE "
            "must be as fatal as its disagreement, or the one proof that the "
            "pre-registration is unchanged can be removed by deleting a file.",
        ]
    try:
        pol = json.loads(doc.read_text())
    except (OSError, ValueError) as exc:
        return [f"policy.json could not be read ({exc}); the epoch's registration is unreadable"]
    recorded = sidecar.read_text().strip()
    actual = policy_hash(pol)
    if recorded != actual:
        return [
            f"policy.json was edited after compilation (recorded {recorded[:16]}..., "
            f"actual {actual[:16]}...); a pre-registered policy cannot change "
            f"inside an epoch",
        ]
    return []


def check_policy(policy: dict) -> list[str]:
    """Structural rules a valid compiled policy must satisfy (spec §3.1, §3.5)."""
    errs: list[str] = []
    states = policy.get("states") or {}
    if policy.get("initial") not in states:
        errs.append(f"initial state {policy.get('initial')!r} is not a declared state")
    elif not states[policy["initial"]].get("spends"):
        errs.append("initial state must be a spending state")
    by_from: dict[str, list[dict]] = {}
    for t in policy.get("transitions") or []:
        by_from.setdefault(t.get("from"), []).append(t)
        if t.get("from") not in states:
            errs.append(f"transition from unknown state {t.get('from')!r}")
        target = t.get("to") or t.get("default")
        if target not in states:
            errs.append(f"transition to unknown state {target!r}")
        if "when" in t:
            where = f"transition {t.get('from')}->{t.get('to')}"
            unknown = set(t["when"]) - OBSERVATION_KEYS
            if unknown:
                errs.append(f"{where} uses unknown observation key(s) {sorted(unknown)}")
            if not t["when"]:
                # An empty guard matches vacuously, so it fires unconditionally
                # and shadows every later rule declared for the same `from`
                # state. A rule that can never NOT fire is a `default` written
                # in a way that hides the shadowing from a reader.
                errs.append(f"{where} has an empty `when` and would match unconditionally")
            for key, spec in t["when"].items():
                if not isinstance(spec, dict):
                    continue  # bare literal: equality against the observation
                if not spec:
                    errs.append(f"{where} has an empty predicate for {key!r}")
                    continue
                bad_ops = sorted(set(spec) - COMPARISON_OPS)
                if bad_ops:
                    # Unreachable-branch defect: `step` cannot interpret the
                    # operator, so the guarded (registered) branch is dead and
                    # nothing else reports it.
                    errs.append(f"{where} uses unknown operator(s) {bad_ops} on {key!r}")
                if len(spec) > 1:
                    errs.append(f"{where} has {len(spec)} operators on {key!r}; predicates take exactly one")
            if not t.get("accounting"):
                errs.append(f"conditional transition {t.get('from')}->{t.get('to')} names no accounting rule")
    for name, st in states.items():
        if st.get("terminal"):
            continue
        outs = by_from.get(name, [])
        if not any("default" in t for t in outs):
            errs.append(f"state {name!r} has no default transition")
        if st.get("spends") and "exception" in states and not any(t.get("to") == "exception" for t in outs):
            errs.append(f"spending state {name!r} cannot reach exception")
    return errs


# The comparison CALLABLES only. The interpretable vocabulary is this module's
# own COMPARISON_OPS, which is narrower: `predicates.OPS` also carries `==` and
# `!=`, and `check_policy` rejects those in a `when` predicate. Gating dispatch
# on COMPARISON_OPS rather than on this dict's keyset is what keeps checker and
# interpreter speaking the same language — a policy check_policy refuses must
# not be one step() can still drive.
from orchestrator.optimize.predicates import OPS as _OP_FUNCS  # noqa: E402


def _match_one(spec, value) -> bool:
    if isinstance(spec, dict):
        return all(op in COMPARISON_OPS and value is not None and _OP_FUNCS[op](value, want)
                   for op, want in spec.items())
    return value is not None and value == spec


def _matches(when: dict, obs: dict) -> bool:
    return all(k in obs and _match_one(spec, obs[k]) for k, spec in when.items())


def step(policy: dict, state: str, observations: dict) -> tuple[str, dict]:
    """Next state under ``policy`` from ``state`` given ``observations``.

    First conditional rule (in registration order) whose every key is present
    in ``observations`` and matches wins; otherwise the state's default. A
    missing or ``None`` observation never matches — unknown is not a fact.
    """
    default = None
    for t in policy.get("transitions") or []:
        if t.get("from") != state:
            continue
        if "when" in t:
            if _matches(t["when"], observations):
                return t["to"], t
        elif "default" in t and default is None:
            default = t
    if default is None:
        raise ValueError(f"policy has no default transition from {state!r}")
    return default["default"], default


def is_terminal(policy: dict, state: str) -> bool:
    return bool((policy.get("states") or {}).get(state, {}).get("terminal"))


def enumerate_paths(policy: dict, *, max_len: int = 12) -> list[list[str]]:
    """All simple paths (each transition used at most once) from initial to a terminal."""
    out: list[list[str]] = []
    trans = policy.get("transitions") or []

    def walk(state, path, used):
        if is_terminal(policy, state) or len(path) >= max_len:
            out.append(path)
            return
        for i, t in enumerate(trans):
            if t.get("from") != state or i in used:
                continue
            walk(t.get("to") or t.get("default"), path + [t.get("to") or t.get("default")], used | {i})
    walk(policy["initial"], [policy["initial"]], frozenset())
    return out


def confirm_looks(policy: dict) -> int:
    """How many times an epoch may LOOK at the terminal certificate.

    Every confirm round evaluates ``certified`` and stops on it, so each round
    is a look, and a certificate judged at the full ``delta_terminal`` on every
    look fails with probability up to ``looks x delta_terminal`` (measured: 4
    rounds at 0.05 gave 0.108). Bonferroni alpha-spending over the
    PRE-REGISTERED maximum number of looks fixes it: each look is taken at
    ``delta_terminal / confirm_looks``. The maximum is the registered round
    cap plus one when the refill branch (``REFILL_ACCOUNTING``) is registered,
    because that branch fires only AT the cap and buys exactly one extra round.
    Charged whether or not the refill is ever taken: a per-look level must be
    fixed before the data decide how many looks there are. The opt-in allocate
    branch (``ALLOCATE_ACCOUNTING``) is one more look, charged the same way. One for the default
    unconstrained single-round campaign, so its certificate is unchanged.
    Single- and multi-objective confirm share this divisor
    (spec 2026-10-17-certification-soundness.md).
    """
    rounds = int(((policy.get("states") or {}).get("confirm") or {}).get(
        "design", {}).get("max_rounds", 1) or 1)
    refill = any(t.get("from") == "confirm"
                 and t.get("accounting") == REFILL_ACCOUNTING
                 for t in policy.get("transitions") or [])
    allocate = any(t.get("from") == "confirm"
                   and t.get("accounting") == ALLOCATE_ACCOUNTING
                   for t in policy.get("transitions") or [])
    return max(1, rounds) + (1 if refill else 0) + (1 if allocate else 0)


def longest_path(policy: dict) -> int:
    """Iterations an epoch can take: longest simple path plus registered self-loop rounds."""
    base = max((len(p) for p in enumerate_paths(policy)), default=1)
    extra = sum(max(0, int((v.get("design") or {}).get("max_rounds", 1)) - 1)
                for v in (policy.get("states") or {}).values() if v.get("spends"))
    return base + extra


def append_transition(work_dir: Path, row: dict) -> None:
    with (Path(work_dir) / "transitions.jsonl").open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def read_transitions(work_dir: Path) -> list[dict]:
    p = Path(work_dir) / "transitions.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def epoch_transitions(policy: dict, work_dir: Path) -> list[dict]:
    """``read_transitions`` narrowed to the rows belonging to THIS epoch.

    ``transitions.jsonl`` is append-only ACROSS epochs — it is the campaign's
    audit trail, and truncating it on an exception would destroy the record of
    why the epoch ended. Every consumer that asks "what has happened so far?"
    therefore has to mean "so far IN THIS EPOCH", or a recompiled epoch inherits
    its predecessor's history: ``current_state`` would resume at the terminal
    ``exception``, and ``_confirm_round`` would count a spent round cap it never
    spent. One filter, one place, so the two cannot drift.

    ``r.get("epoch", 1)`` treats a row with no recorded epoch as epoch 1. Rows
    predating the field (and the hand-written ones in the unit tests) are all
    first-epoch rows, so the default is the truth rather than a guess.
    """
    want = int(policy.get("epoch", 1))
    return [r for r in read_transitions(work_dir) if int(r.get("epoch", 1)) == want]


def current_state(policy: dict, work_dir: Path) -> str:
    """Where THIS epoch is: the last transition recorded under ``policy["epoch"]``.

    Filtering by epoch is what makes a semantic exception genuinely END an
    epoch rather than merely label one. ``transitions.jsonl`` is append-only
    across epochs — that is the point, it is the audit trail — so an unfiltered
    read would hand the new epoch its predecessor's last state, which is
    ``exception``: terminal, so the recompiled policy would resume at a state it
    can never leave and the campaign would be permanently stuck at the failure
    it was just recompiled to escape. With the filter, epoch e+1 sees no rows of
    its own and starts at ``initial``, which is a CLEAN restart from screen.

    See ``epoch_transitions`` for why the filter is not optional.
    """
    rows = epoch_transitions(policy, work_dir)
    return rows[-1]["to"] if rows else policy["initial"]
