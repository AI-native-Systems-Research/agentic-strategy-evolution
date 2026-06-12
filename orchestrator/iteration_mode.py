"""Per-iteration mode resolution.

A campaign's ``iterations: [...]`` list, when present, lets operators tag
each iteration as ``rehearsal`` or ``real``. The DESIGN methodology reads
the resolved mode from its prompt context and scope-shrinks accordingly:
rehearsal iterations focus on the *apparatus check* (does the workload
spec parse, do BLIS args bind, does analysis validate?) and the
*feasibility check* (does the parameter regime engage the mechanism?),
emitting ``brief_amendments.md`` for any campaign-spec friction. Real
iterations run the full bundle at full scope.

This module is **pure Python — no LLM, no I/O**. The orchestrator and
LLMDispatcher import the resolver to populate prompt context;
test_iteration_mode covers the cases.
"""
from __future__ import annotations

from typing import Literal


# Type alias used by callers that want the type-checker to enforce the
# enum at the API surface (instead of duck-typed strings flowing through).
Mode = Literal["rehearsal", "real"]

# Default when the campaign omits ``iterations``, or when an iteration
# index is out of range. ``real`` is the conservative default — a
# rehearsal-mode iteration scope-shrinks; defaulting to it could mean
# "skip the full experiment by accident."
DEFAULT_MODE: Mode = "real"

VALID_MODES: tuple[Mode, ...] = ("rehearsal", "real")


def iteration_mode_for(campaign: dict, iteration: int) -> Mode:
    """Return the mode for iteration N, defaulting to ``real``.

    Out-of-range index, missing block, or malformed entry: ``real``.
    """
    if iteration < 1:
        return DEFAULT_MODE
    iters = campaign.get("iterations")
    if not isinstance(iters, list) or not iters:
        return DEFAULT_MODE
    idx = iteration - 1
    if idx >= len(iters):
        return DEFAULT_MODE
    entry = iters[idx]
    if not isinstance(entry, dict):
        return DEFAULT_MODE
    mode = entry.get("mode")
    if mode in VALID_MODES:
        return mode  # type: ignore[return-value] — narrowed by membership
    return DEFAULT_MODE


REHEARSAL_GUIDANCE = """\
This iteration is a **REHEARSAL** (#212). Optimize for fast feedback over
scientific completeness. Two distinct goals — score them separately:

1. **Apparatus check.** Does the experimental machinery work end-to-end?
   - Does the workload spec parse?
   - Do BLIS / target-system args bind correctly?
   - Does the analysis script schema-validate at least one result?
   - Are the canonical seeds usable, or do they trip a known bug?

2. **Feasibility check.** Is the parameter regime worth running?
   - Does the workload actually engage the mechanism under test? (e.g.
     does the burst create KV pressure, vs all adversary requests being
     dropped_unservable?)
   - Does the policy contrast actually differentiate on this workload,
     or do both arms produce identical metrics?

**Scope discipline for rehearsals:**
- Use ONE seed (the first canonical seed for this campaign).
- Use the contrast-pair arms only (h-main vs the most direct control).
   Do NOT fan out across all arms in a multi-arm bundle.
- Keep wall-time small. If a rehearsal is going to take more than ~5–10
   minutes, you're doing too much.

**What to emit alongside findings:**
If you find any campaign-spec or brief inconsistencies (paths the
validator rejects, broken argv quoting, wall-time claims that don't
match reality, single-tenant probes when the target requires multi-
tenant, etc.), write them to
``runs/iter-N/inputs/brief_amendments.jsonl`` as one structured JSON
object per line. Required fields: ``id`` (pattern ``BA-N``),
``brief_section``, ``problem``, ``fix``, ``priority`` (one of
``BLOCKING``, ``HIGH``, ``MEDIUM``, ``LOW``, ``INFO``). Optional
``evidence``, ``impact``. Schema:
``orchestrator/schemas/brief_amendments.schema.json``. The promote
gate, the REPORT extractor, and the future ``apply-amendments`` CLI
all read this structured form.

**Do NOT:**
- Author full multi-arm bundles. Keep arms minimal.
- Run all canonical seeds. One seed is enough to verify apparatus
   + feasibility.
- Conclude on the research question. Rehearsals don't confirm or
   refute hypotheses; they validate the apparatus.
"""

REAL_GUIDANCE = """\
This iteration is a **REAL** run (#212). Run the bundle at full scope:
all arms, full seed list, full workload. Do not scope-shrink.

If a prior ``rehearsal`` iteration emitted ``brief_amendments.md``,
read it before authoring the bundle — apply the amendments and don't
re-discover the same friction.
"""


def mode_guidance_for(mode: Mode) -> str:
    """Return the DESIGN-phase prompt block that guides the agent for ``mode``.

    Raises ``ValueError`` on an unknown mode value. Silently defaulting
    to REAL_GUIDANCE was the prior behavior; that's the more dangerous
    default (rehearsal is the conservative one), so we fail loudly
    instead of running a full experiment when a typo says otherwise.
    """
    if mode == "rehearsal":
        return REHEARSAL_GUIDANCE
    if mode == "real":
        return REAL_GUIDANCE
    raise ValueError(
        f"unknown iteration mode {mode!r}; expected one of {VALID_MODES}"
    )


# ─── Execute-phase mode guidance (#221) ──────────────────────────────────
#
# The DESIGN agent's mode_guidance shaped how it scope-shrunk probes /
# bundle authoring. EXECUTE_ANALYZE needs its OWN mode-aware guidance
# so it doesn't fan out the bundle at full scope when iter is rehearsal.
# Without this, post-#212 paper-burst reruns observed the DESIGN agent
# honoring rehearsal scope while EXECUTE_ANALYZE dutifully ran the full
# 50-arm experiment anyway — defeating the cost asymmetry that was the
# entire economic argument for #212.

EXECUTE_REHEARSAL_GUIDANCE = """\
This iteration is in **REHEARSAL** mode. The DESIGN agent's bundle
declares the full experimental design (so iter-2 / future runs can
run it untouched). YOUR JOB this iter:

1. **Honor the rehearsal scope.** If the bundle's
   ``experiment_spec.rehearsal_subset`` is populated, execute ONLY
   that subset (typically: 1 seed × the contrast-pair arms).
   Do NOT fan out the full ``experiment_spec`` — that's iter-2's job.
   If ``rehearsal_subset`` is missing, default to: first canonical
   seed + ``h-main`` and ``h-control-negative`` arms only.

2. **Validate the analysis pipeline.** Schema-pass at least one
   result through the analysis_summary.json computation. If the
   analysis script fails or returns null where data is present,
   fix the script (or surface the issue) before iter-2 runs.

3. **Append per-policy timing observations.** During the
   feasibility / contrast-pair runs, measure wall-clock per policy.
   Record into ``experiment_spec.timing_observations``:
   ``expected_wall_time_seconds_per_policy: { ea-wfq: 25, wfq: 23, ... }``
   and a derived ``recommended_turn_silence_threshold_seconds``
   (~3× the slowest observed policy + buffer). iter-2's watchdog
   reads these to calibrate.

4. **Emit ``brief_amendments.jsonl``** at
   ``runs/iter-N/inputs/brief_amendments.jsonl`` if you find any
   campaign-spec friction (workload params, timing claims, missing
   flags, etc.). One JSON object per line; required fields: ``id``
   (pattern ``BA-N``), ``brief_section``, ``problem``, ``fix``,
   ``priority`` (BLOCKING / HIGH / MEDIUM / LOW / INFO). Optional
   ``evidence``, ``impact``.

5. **Append to ``bundle_amendments.jsonl``** when you override
   any parameter from ``experiment_spec.verified_parameters``.

6. **Write findings.json with ``mode: rehearsal``** in the outcome,
   noting that scientific claims are deferred to iter-2. The
   ``experiment_valid: true`` flag means "the apparatus works" —
   not "the hypothesis is confirmed/refuted."

**Do NOT:**
- Fan out the full bundle's seeds × policies grid.
- Mark h-main as CONFIRMED / REFUTED based on rehearsal data.
- Skip writing ``brief_amendments.jsonl`` if you discovered
  campaign-spec friction.
"""

EXECUTE_REAL_GUIDANCE = """\
This iteration is in **REAL** mode. Run the full experiment_spec at
the bundle's prescribed scope: all arms, full seed list.

If a prior ``rehearsal`` iter emitted ``brief_amendments.jsonl``, read
it BEFORE launching the experiment. Any ``priority: BLOCKING``
amendments encode constraints iter-2 must respect (e.g., a workload
parameter the rehearsal verified is required for the experiment to
engage the mechanism). Apply each BLOCKING amendment to your run
configuration and proceed; if you cannot apply one, write a
``failure_note.md`` describing why and STOP — the campaign should
revise the brief before continuing.

Write ``findings.json`` with ``mode: real`` and a CONFIRMED / REFUTED
/ NULL status per arm. Append ``bundle_amendments.jsonl`` for any
parameter overrides observed during execution (silent drift breaks
reproducibility).
"""


def execute_mode_guidance_for(mode: Mode) -> str:
    """Return the EXECUTE_ANALYZE-phase prompt block for ``mode`` (#221).

    Distinct from ``mode_guidance_for`` (which targets the DESIGN agent).
    Raises ``ValueError`` on unknown modes for the same fail-loud reason.
    """
    if mode == "rehearsal":
        return EXECUTE_REHEARSAL_GUIDANCE
    if mode == "real":
        return EXECUTE_REAL_GUIDANCE
    raise ValueError(
        f"unknown iteration mode {mode!r}; expected one of {VALID_MODES}"
    )
