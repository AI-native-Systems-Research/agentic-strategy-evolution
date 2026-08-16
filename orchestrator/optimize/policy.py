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
    "runs_needed_foldover", "runs_needed_confirm", "residual_regret", "epsilon",
    "behavioral_violation",
})

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
            "design": {"kind": "shortlist_replicate",
                       "shortlist_size": int(confirm_cfg.get("shortlist_size", 1)),
                       "replicates": max(1, int(confirm_cfg.get("replicates", 3))),
                       "max_rounds": int(pol_cfg.get("confirm_max_rounds", 1))},
            "estimator": "sample_means",
            "accounting": "holm_one_sided_t",
        }

    after_refine = "confirm" if confirm_on else "report"
    sem = "none: semantic exception ends the epoch, no inference is drawn"
    transitions: list[dict] = [
        {"from": "screen", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
        {"from": "screen", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
    ]
    if refine_on:
        transitions.append({"from": "screen", "when": {"refinable_survivors": {">": 0}}, "to": "refine",
                            "accounting": "screen selection at alpha=0.05 per main effect (Task 8 adds regret)"})
    transitions.append({"from": "screen", "default": ("confirm" if confirm_on else "report")})
    if refine_on:
        transitions += [
            {"from": "refine", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "refine", "when": {"nan_response": True}, "to": "exception", "accounting": sem},
            {"from": "refine", "default": after_refine},
        ]
    if confirm_on:
        transitions += [
            {"from": "confirm", "when": {"correctness_failed": True}, "to": "exception", "accounting": sem},
            {"from": "confirm", "when": {"certified": True}, "to": "report",
             "accounting": "holm_one_sided_t at delta_terminal over |S|-1 finalists"},
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
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    p = work_dir / "policy.json"
    p.write_text(json.dumps(policy, indent=2, sort_keys=True))
    (work_dir / "policy.sha256").write_text(policy_hash(policy) + "\n")
    return p


def read_policy(work_dir: Path) -> dict | None:
    p = Path(work_dir) / "policy.json"
    return json.loads(p.read_text()) if p.exists() else None


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
