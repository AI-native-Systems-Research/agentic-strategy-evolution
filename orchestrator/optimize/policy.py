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
  which ``recommendation.json`` carries and ``_confirm_rows`` reads to decide
  whether the fitted argmax may anchor the shortlist; ``all_within_noise`` /
  ``lack_of_fit``, which reach ``findings.json`` through
  ``StageDecision.triggers`` and ``effects.json`` through ``lack_of_fit_p``,
  and whose branching consequence the policy expresses through
  ``refinable_survivors`` and confirm's registered augmentation instead — see
  the "DELIBERATELY NOT a ``lack_of_fit`` rule" note on refine's transitions
  below);
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

_PRE = ("build", "verify")
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


def compile_policy(campaign: dict, *, mechanism_patch_hash: str = "", epoch: int = 1) -> dict:
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
                       "center_points": int((design.get("refine") or {}).get("center_points", 4))},
            "estimator": "ols_normal_equations",
            "accounting": "per_term_t_on_pure_error",
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
                       "shortlist_size": int(confirm_cfg.get("shortlist_size", 3)),
                       "replicates": max(1, int(confirm_cfg.get("replicates", 3))),
                       "max_rounds": int(pol_cfg.get("confirm_max_rounds", 1))},
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
            # DELIBERATELY NOT a `lack_of_fit` rule. Model inadequacy IS named
            # by the policy — refine's registered augmentation is confirm's
            # fresh measurements — so it routes to `confirm` on the default with
            # `recommendation.json["model_adequate"] = false`, which is what
            # makes `_confirm_rows` build finalists from MEASURED valid rows
            # instead of from the model's untrusted pick (paper: "remeasures the
            # leading measured valid candidates rather than choosing the largest
            # noisy observation"). An out-of-hull optimum is different in kind:
            # no amount of remeasurement inside the hull finds a point outside
            # it.
            {"from": "refine", "when": {"stationary_in_hull": False}, "to": "exception",
             "accounting": sem},
            {"from": "refine", "default": after_refine},
        ]
    if confirm_on:
        transitions += [
            {"from": "confirm", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "confirm", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
            {"from": "confirm", "when": {"certified": True}, "to": "report",
             "accounting": "bonferroni_one_sided_welch_t at delta_terminal over |S|-1 finalists"},
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
            "epsilon": dict(pol_cfg.get("epsilon") or {"pct": 2.0}),
            "delta_screen": float(pol_cfg.get("delta_screen", 0.05)),
            "delta_terminal": float(pol_cfg.get("delta_terminal", 0.05)),
        },
        "budget": {"max_runs": design.get("max_runs")},
        "known_valid_baseline": opt.get("known_valid_baseline"),
        "workload": opt.get("workload"),
        "initial": "screen",
        "states": states,
        "transitions": transitions,
    }
    _sanity = {t["from"] for t in transitions if "default" in t}
    assert {s for s, v in states.items() if not v.get("terminal")} <= _sanity
    return policy


def policy_hash(policy: dict) -> str:
    return hashlib.sha256(_canonical(policy).encode()).hexdigest()


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
