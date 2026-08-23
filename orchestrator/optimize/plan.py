"""The ``plan`` stage: design the mechanism before authoring it.

Why this stage exists, measured rather than argued. Three builds of the same
mechanism, same target, same objective, same adapter:

===========================================  ==============================
build whose prompt never received the cost    removed 70% of the per-item
facts (they sat unread in a field the         work and ran **23.7% SLOWER**
prompt did not read)
build that received them                      +3.65%, certified
the reflective kind, which designs first      **-10.4%**, and it named the
                                              winning architecture in its
                                              design artifact BEFORE writing
                                              a line of code
===========================================  ==============================

The reflective arm's advantage was not more tokens in the authoring call — it was
a *separate* call that reasoned about the mechanism's cost model first. Its bundle
was 29.4K characters, of which **87% was experiment design** (hypothesis arms,
locked parameters, run plans) that ``kind: optimization`` already carries
pre-registered and content-hashed, which is a strictly stronger guarantee. Only
the remaining fraction — where the cost sits, which approach was chosen, what was
rejected and why, which invariants a naive version breaks — is what produced the
better mechanism.

So this stage captures **exactly that fraction and nothing else**. One call, no
code, a small schema-checked JSON artifact. That is the frugality argument: the
kind stays at two substantive calls (``plan`` + ``build``) against the reflective
kind's nineteen, while buying the one thing that separated them.

The stage is **opt-in** and, like ``build``, sits OUTSIDE the compiled epoch: the
epoch itself remains tokenless, which is the kind's load-bearing invariant.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Written at the work-dir root, beside ``policy.json`` — it describes the
#: mechanism the whole epoch measures, not any one iteration of it.
PLAN_FILENAME = "mechanism_plan.json"

DEFAULT_MAX_TURNS = 60

#: Every section the plan must carry, and why each one is not optional. Each
#: entry maps a section to the keys it must itself contain; a section present but
#: empty is rejected exactly like an absent one, because a vacuous plan reads as
#: a completed plan in every artifact listing.
REQUIRED: dict[str, tuple[str, ...]] = {
    # Where the cost actually is, in the objective's own currency. NOT derivable
    # from the campaign YAML — it has to be read off the target.
    "cost_model": ("summary", "currency"),
    # The chosen strategy, with both halves of the comparison the build's O1/O2
    # checklist items demand. Stating them here, before the code exists, is the
    # whole point: it is cheap to reject an O(N) decision path on paper.
    "approach": ("summary", "cost_of_deciding", "cost_avoided"),
    # At least one alternative considered and priced. This is the field that
    # catches "my check walks the same N I am skipping" while it is still free.
    "rejected": ("approach", "why"),
    # Invariants a naive implementation breaks, with the symptom and the guard.
    # A named crash mode with no guard is how the first build shipped one.
    "failure_modes": ("symptom", "cause", "guard"),
}

#: Sections that are lists of records rather than a single record.
_LIST_SECTIONS = ("rejected", "failure_modes")

#: Shortest string that can carry a reason. Not a style rule: "no" and "" are
#: both non-answers, and a checker that accepts them cannot tell a priced
#: alternative from a box ticked.
_MIN_RATIONALE = 12


class PlanRejected(RuntimeError):
    """The planning call produced nothing a build could act on.

    Raised instead of writing a partial artifact: ``build`` reads this file as a
    specification, so a plan that failed its own structural check must not be on
    disk at all. Fail closed.
    """


def check_plan(plan: Any) -> list[str]:
    """Structurally validate a mechanism plan. Pure; returns human-readable errors.

    Deliberately narrow. It cannot know whether a cost model is *true* — only
    ``screen`` can, by measuring — but it can insist the plan says the things
    that make a build accountable: the currency, both sides of the cost
    comparison, a priced alternative, and a guarded failure mode.
    """
    errors: list[str] = []
    if not isinstance(plan, dict):
        return [f"plan must be a JSON object, got {type(plan).__name__}"]

    for section, keys in REQUIRED.items():
        if section not in plan:
            errors.append(
                f"{section}: missing. The plan must say "
                f"{'; '.join(keys)} — a build cannot be held to a plan that "
                f"does not state them.",
            )
            continue
        value = plan[section]
        if not value:
            errors.append(
                f"{section}: present but empty. An empty section is as useless "
                f"as an absent one and reads as a completed plan.",
            )
            continue
        records = value if section in _LIST_SECTIONS else [value]
        if not isinstance(records, list):
            errors.append(f"{section}: expected a list of records, got "
                          f"{type(records).__name__}")
            continue
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                errors.append(f"{section}[{i}]: expected an object, got "
                              f"{type(rec).__name__}")
                continue
            for key in keys:
                got = rec.get(key)
                if got is None or (isinstance(got, str) and not got.strip()):
                    errors.append(
                        f"{section}[{i}].{key}: missing or empty.",
                    )
                elif isinstance(got, str) and len(got.strip()) < _MIN_RATIONALE:
                    errors.append(
                        f"{section}[{i}].{key}: too short to be an answer "
                        f"({got.strip()!r}). State the reason, not a token.",
                    )
    return errors


def read_plan(work_dir: Path | str) -> dict:
    """Read the plan a previous ``plan`` stage wrote, or ``{}`` if there is none.

    Absent is the normal case: ``plan`` is opt-in, and every campaign written
    before it existed must behave identically.
    """
    path = Path(work_dir) / PLAN_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("plan: could not read %s: %s", path, exc)
        return {}


def _extract_json(text: str) -> Any:
    """Pull the JSON object out of a model reply that may fence or frame it.

    Fencing is a formatting habit, not a refusal, so a plan wrapped in prose or
    in ```json is still a plan. Anything with no object in it at all is not.
    """
    text = (text or "").strip()
    if not text:
        raise PlanRejected(
            "plan stage returned no text, so there is no JSON plan to check.",
        )
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    # Last resort: the outermost brace-balanced span.
    first, last = text.find("{"), text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    for cand in candidates:
        try:
            return json.loads(cand.strip())
        except json.JSONDecodeError:
            continue
    raise PlanRejected(
        "plan stage did not return a JSON object. The plan is read by the build "
        "stage as its specification, so an unparseable reply cannot be used; "
        f"got {text[:200]!r}",
    )


def plan_prompt(campaign: dict) -> str:
    """Compose the planning prompt. Pure function of the campaign, so it is testable.

    Carries the same two author channels ``build`` does — ``target_system.description``
    and ``optimization.guidance.factor_nomination`` — plus the objective and its
    constraints, because a plan cannot state cost "in the objective's currency"
    without being told the currency. ``guidance.interpretation`` is withheld for the
    same reason as in ``build``: it steers how *results* are read, and neither the
    planning nor the authoring stage may pre-judge a measurement it does not make.
    """
    target = campaign.get("target_system") or {}
    opt = campaign.get("optimization") or {}
    rq = (campaign.get("research_question") or "").strip()
    description = (target.get("description") or "").strip()
    repo = str(target.get("repo_path") or "").strip()

    response = opt.get("response") or {}
    primary = response.get("primary") or {}
    metric = str(primary.get("metric") or "the primary metric").strip()
    direction = str(primary.get("direction") or "improve").strip()
    constraints = [
        f"{c.get('metric') or c.get('observable')} {c.get('op')} {c.get('value')}"
        for c in (response.get("constraints") or []) if isinstance(c, dict)
    ]
    constraints_clause = (
        "\nDECLARED CONSTRAINTS (a second budget the mechanism must not spend to "
        "buy the primary metric):\n  " + "\n  ".join(constraints)
        if constraints else ""
    )

    guidance = ((opt.get("guidance") or {}).get("factor_nomination") or "").strip()
    guidance_block = (
        f"""

AUTHOR'S GUIDANCE ON THE MECHANISM (optimization.guidance.factor_nomination)
{guidance}"""
        if guidance else ""
    )

    knobs = ", ".join(
        str(f.get("name") or f.get("id"))
        for f in (opt.get("factors") or []) if isinstance(f, dict)
    ) or "(none declared)"

    return f"""You are DESIGNING a mechanism that a later stage will author and a
factorial experiment will then measure. Produce a plan. **Write no code, no tests,
and no configuration** — the next stage does that, from what you write here.

WORKING ROOT — read the target, do not modify it
  {repo}

You may read anything under that root, profile it, count calls, and run its own
tooling to find out where the cost is. Do not edit it.

RESEARCH QUESTION
{rq}

THE TARGET (authored by the campaign author)
{description}
{guidance_block}

THE OBJECTIVE THE MECHANISM WILL BE JUDGED ON
  `{metric}` ({direction}){constraints_clause}

THE KNOBS THE EXPERIMENT WILL VARY
  {knobs}

WHY THIS STAGE EXISTS
A mechanism can be correct, well-tested, and still a REGRESSION — measured on a
real campaign: an implementation removed 70% of the per-item work it targeted and
ran 23.7% SLOWER, because its per-frame decision walked the same N items it was
trying to skip. Nothing in the correctness gate catches that; it surfaces only
after the authoring call is spent. Deciding on paper which approach pays is
cheap. Discovering it after the build is not.

SCOPE
`kind: optimization` is frugal by design, and this stage is deliberately small:
one call, no code. Explore the target as much as the plan needs — profiling and
call counting are the substance of the plan, not a distraction. What you must NOT
do is pre-empt the pre-registered experiment: do not search the declared knob
LEVELS for a winner. `screen` and `confirm` do that under a design fixed before
any result was seen.

REPLY WITH A SINGLE JSON OBJECT, and nothing that is not part of it:

{{
  "cost_model": {{
    "summary": "Where the cost actually is, with numbers you measured or read
                off the target — call counts, profile shares, what fraction of
                the work is redundant. Say whether it is one hotspot or many
                small operations, because that changes which mechanism can win.",
    "currency": "{metric}",
    "measured": true
  }},
  "approach": {{
    "summary": "The strategy you recommend, concretely enough to implement.",
    "cost_of_deciding": "The overhead the mechanism itself adds, asymptotically,
                         in the size that varies at run time.",
    "cost_avoided": "The cost it removes, in the same terms. This must be
                     strictly larger than cost_of_deciding.",
    "files": ["paths you expect the build to change"]
  }},
  "rejected": [
    {{
      "approach": "An alternative you considered.",
      "why": "Why it loses, in cost terms. AT LEAST ONE entry is required: the
              act of pricing a loser is what catches a decision path that
              cannot pay for itself, while it is still free to catch."
    }}
  ],
  "failure_modes": [
    {{
      "symptom": "What breaks if the mechanism is implemented naively — the exact
                  error or wrong behaviour.",
      "cause": "The invariant that gets violated.",
      "guard": "What the implementation must do, and what test must assert it."
    }}
  ]
}}

Every field is required and every string must be a real answer; a plan that omits
one is rejected and the campaign stops before spending the authoring call.
"""


def run_plan(
    campaign: dict,
    work_dir: Path,
    *,
    iteration: int,
    model: str | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    sdk_runner: Callable | None = None,
    **_ignored,
) -> dict:
    """Spend one agent call designing the mechanism. Write the plan; return metrics.

    ``sdk_runner`` is the injection seam, matching ``SDKDispatcher`` and
    ``run_build``: tests pass a callable returning an ``SDKResult`` and never
    touch the network.

    Fails closed. A reply that does not parse, or a plan that fails
    :func:`check_plan`, raises :class:`PlanRejected` and writes NO artifact —
    ``build`` reads this file as its specification, so a half-formed plan on disk
    is worse than none.
    """
    from orchestrator.metrics import log_metrics
    from orchestrator.sdk_dispatch import (
        _default_sdk_runner_factory,
        _load_methodology_preamble,
    )

    target = campaign.get("target_system") or {}
    repo = target.get("repo_path")
    if not repo:
        raise PlanRejected(
            "plan stage requires target_system.repo_path — there is no "
            "repository to read while designing the mechanism.",
        )

    from orchestrator.campaign import _resolve_model

    resolved_model = model or _resolve_model(campaign, "plan", None)
    prompt = plan_prompt(campaign)
    runner = sdk_runner or _default_sdk_runner_factory()

    prompts_dir = ((campaign.get("prompts") or {}).get("methodology_layer"))
    system_prompt = None
    if prompts_dir:
        try:
            system_prompt = _load_methodology_preamble(Path(prompts_dir))
        except OSError as exc:
            logger.warning("plan: could not load methodology preamble: %s", exc)

    iter_dir = Path(work_dir) / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    sandbox = campaign.get("sandbox", "bypass")
    permission_mode = "bypassPermissions" if sandbox == "bypass" else None

    logger.info(
        "plan: designing mechanism against %s (max_turns=%d, model=%s)",
        repo, max_turns, resolved_model,
    )

    result = runner(
        prompt=prompt,
        model=resolved_model,
        cwd=Path(repo),
        max_turns=max_turns,
        system_prompt=system_prompt,
        event_log_path=iter_dir / "plan_events.jsonl",
        permission_mode=permission_mode,
    )

    row = {
        "dispatcher": "sdk",
        "role": "planner",
        "phase": "plan",
        "model": resolved_model,
        "input_tokens": getattr(result, "input_tokens", 0),
        "output_tokens": getattr(result, "output_tokens", 0),
        "cache_creation_input_tokens": getattr(
            result, "cache_creation_input_tokens", 0,
        ),
        "cache_read_input_tokens": getattr(result, "cache_read_input_tokens", 0),
        "cost_usd": getattr(result, "cost_usd", 0.0),
        "duration_ms": getattr(result, "duration_ms", 0),
        "num_turns": getattr(result, "num_turns", 1),
    }
    # Logged BEFORE the structural check: the call was made and the tokens were
    # spent whether or not the plan survives, and the cost axis must see it.
    log_metrics(Path(work_dir) / "llm_metrics.jsonl", row)

    if getattr(result, "is_error", False):
        raise PlanRejected(
            f"plan stage agent call failed: "
            f"{getattr(result, 'error_message', '') or 'unknown error'}",
        )

    plan = _extract_json(getattr(result, "text", "") or "")
    errors = check_plan(plan)
    if errors:
        raise PlanRejected(
            "the mechanism plan is not usable as a build specification:\n  - "
            + "\n  - ".join(errors)
            + "\nNo plan was written. Revise the campaign's "
              "target_system.description or optimization.guidance."
              "factor_nomination so the planning call has what it needs.",
        )

    path = Path(work_dir) / PLAN_FILENAME
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    logger.info(
        "plan: wrote %s — approach %r, %d rejected alternative(s), "
        "%d failure mode(s)",
        PLAN_FILENAME,
        str((plan.get("approach") or {}).get("summary", ""))[:60],
        len(plan.get("rejected") or []),
        len(plan.get("failure_modes") or []),
    )
    return row


def format_plan_for_build(plan: dict) -> str:
    """Render a plan as the build prompt's specification block.

    Deterministic and total: a plan that passed ``check_plan`` renders fully, and
    an empty plan renders as the empty string so an opt-in stage stays opt-in.
    """
    if not plan:
        return ""
    cm = plan.get("cost_model") or {}
    ap = plan.get("approach") or {}
    lines = [
        "",
        "MECHANISM PLAN (from the `plan` stage — this is your specification)",
        f"  Cost model ({cm.get('currency', '?')}): {cm.get('summary', '')}",
        f"  Approach: {ap.get('summary', '')}",
        f"    cost of deciding : {ap.get('cost_of_deciding', '')}",
        f"    cost avoided     : {ap.get('cost_avoided', '')}",
    ]
    files = ap.get("files") or []
    if files:
        lines.append(f"    expected files   : {', '.join(str(f) for f in files)}")
    rejected = plan.get("rejected") or []
    if rejected:
        lines.append("  Alternatives already priced and REJECTED — do not "
                     "re-derive these:")
        for r in rejected:
            lines.append(f"    - {r.get('approach', '')}: {r.get('why', '')}")
    modes = plan.get("failure_modes") or []
    if modes:
        lines.append("  Failure modes the implementation must guard:")
        for m in modes:
            lines.append(
                f"    - {m.get('symptom', '')} (cause: {m.get('cause', '')}) "
                f"-> {m.get('guard', '')}",
            )
    lines.append(
        "  The plan is the specification. If implementing it reveals the plan is "
        "wrong, implement what is correct and say so in your summary — a "
        "documented divergence is a finding, not a failure.",
    )
    return "\n".join(lines)


def check_plan_against_effect(
    plan: dict,
    *,
    factor_id: str,
    effect: float,
    direction: str,
    noise_pct: float,
    baseline: float,
) -> list[str]:
    """Hold the plan to its own prediction, using the screen's measured effect.

    The plan asserts ``cost_avoided > cost_of_deciding`` — i.e. that enabling the
    mechanism moves the objective the way ``direction`` calls better. ``screen``
    measures exactly that as the main effect of the mechanism's factor. Comparing
    the two is what stops the plan being write-only, and it catches, one stage
    later but still before the recommendation is believed, the defect the stage
    exists to prevent: a decision path that costs more than the work it removes.

    Reported, never fatal. A refuted plan is a *finding* — the campaign's own
    ``screen`` did its job, and the honest outcome is a recommendation that leaves
    the mechanism off plus a flag saying the plan's cost model was wrong. Aborting
    would throw away a correct measurement.

    ``effect`` is the objective's change when the mechanism goes from its control
    level to its enabled level, in the objective's units. An effect inside the
    workload's own noise floor is not a contradiction: below the floor the
    measurement cannot refute anything, and claiming otherwise manufactures
    findings.
    """
    if not plan:
        return []          # opt-in: no plan, no prediction to falsify
    approach = plan.get("approach") or {}
    if not approach:
        return []

    floor = abs(float(baseline)) * float(noise_pct) / 100.0
    if abs(float(effect)) <= floor:
        return []

    better_is_lower = str(direction).strip().lower() == "minimize"
    helped = (effect < 0) if better_is_lower else (effect > 0)
    if helped:
        return []

    return [
        f"the mechanism plan predicted its overhead would be smaller than the "
        f"work it removes (cost_of_deciding {approach.get('cost_of_deciding')!r} "
        f"vs cost_avoided {approach.get('cost_avoided')!r}), but screen measured "
        f"factor {factor_id} moving the objective by {effect:+.6g} — the wrong way "
        f"for direction={direction}, and larger than the {noise_pct:g}% noise floor "
        f"({floor:.6g}). The plan's cost model is contradicted by the measurement: "
        f"treat the mechanism as not worth enabling, and read the plan's "
        f"`rejected` alternatives as the candidates that were priced but not built."
    ]
