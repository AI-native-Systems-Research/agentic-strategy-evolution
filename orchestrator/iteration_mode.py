"""Per-iteration mode resolution (#212).

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


# Default when the campaign omits ``iterations``, or when an iteration
# index is out of range. Real iterations are the safe default — agents
# at sonnet level have always run real iterations until #212.
DEFAULT_MODE = "real"

VALID_MODES = ("rehearsal", "real")


def iteration_mode_for(campaign: dict, iteration: int) -> str:
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
        return mode
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
tenant, etc.), write them to ``runs/iter-N/brief_amendments.md`` —
one entry per finding, with file path + suggested change. The next
``real`` iteration will read this; future runs of the same campaign
will benefit indefinitely.

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


def mode_guidance_for(mode: str) -> str:
    """Return the prompt block that guides the agent for ``mode``."""
    if mode == "rehearsal":
        return REHEARSAL_GUIDANCE
    return REAL_GUIDANCE
