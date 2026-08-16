"""The ``build`` stage: author the mechanism before measuring it.

Why this module exists
----------------------
Every other stage in this package is pure Python. That is the whole point of
``kind: optimization`` — ``screen``/``refine``/``confirm`` drive a
pre-registered design matrix with zero model calls, so a campaign costs ~3
substantive calls against 60-90 tokenless benchmark runs.

But that left a real hole. ``verify`` runs the target's native tests and
aborts if a declared ``native_test`` did not execute (the fail-closed path in
``relations.reconcile``). When the mechanism under study *does not exist yet*
— a new flag, a new policy, a new curve — there was nothing in the
optimization path that could write it, because nothing in this package ever
called an agent. The campaign aborted at ``verify`` forever, correctly and
uselessly: it demanded tests for code that no stage was able to author.

The reflective kind has never had this problem; its SDK agent edits the
target repo as a matter of course. So the gap was specific to this kind, and
it mattered, because "extend the target, then optimize the extension" is the
common shape of a real optimization request.

What this does about it
-----------------------
``build`` is a stage that spends exactly ONE agent call to author the
mechanism and its native tests, then hands control straight back to the
tokenless machinery. It deliberately does NOT:

- iterate with the model until tests pass (that is a token sink, and it also
  lets the model negotiate with its own gate),
- read or fit any measurement (the design matrix is not written yet),
- decide anything about the experiment.

``verify`` remains the gate, unchanged and unaware of how the code arrived.
That separation is the safety property: the thing that writes the mechanism
is not the thing that certifies it, and certification is still pure Python
reading a real test runner's real output.

Token cost: one call. A build+verify+screen+confirm campaign therefore runs
~4 substantive calls instead of ~3 — the marginal cost of being able to
author mechanisms at all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

#: Ceiling on agent turns for the build call. Generous enough to write a
#: mechanism plus a test file and iterate on compile errors, bounded so a
#: confused agent cannot spend a campaign's budget in one stage.
DEFAULT_MAX_TURNS = 120


def check_build_touched_repo(repo: Path) -> str | None:
    """Return a warning if a git-tracked ``repo`` shows no local modifications.

    The build stage's whole job is to change files under ``repo``. When it
    reports success and the tree is still pristine, the likely explanation is
    that it edited a DIFFERENT checkout of the same project — which is silent,
    and which corrupts a parallel arm rather than failing. Observed for real
    against a worktree.

    Returns None when the check does not apply (not a git repo, git absent) so
    a non-git target is never penalised. Advisory rather than fatal: ``verify``
    is the authority on whether the mechanism is actually present, and a build
    that legitimately needed no change should not abort a campaign.
    """
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo), capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None  # not a git work tree
    if proc.stdout.strip():
        return None  # something changed, as expected
    return (
        f"build reported success but {repo} has no local modifications. If this "
        f"path is a git worktree or one of several checkouts of the same "
        f"project, the build may have edited a different checkout instead — "
        f"check the other one before trusting any measurement, because two "
        f"campaigns sharing a tree invalidate both."
    )


class BuildFailed(RuntimeError):
    """The build stage could not author the mechanism.

    Raised only for failures of the *call itself* (SDK error, empty result).
    A build that runs but produces wrong code is NOT this exception's job —
    that is ``verify``'s job, and conflating the two would let a build-stage
    self-assessment substitute for a real test run.
    """


def build_prompt(campaign: dict, declared_tests: list[str]) -> str:
    """Compose the build-stage prompt.

    Pure function of the campaign so it is testable without an SDK: the
    prompt is derived from the same ``target_system.description`` and
    ``native_test`` declarations that ``verify`` will later enforce, which
    is what keeps the instruction and the gate in agreement.

    States ``repo_path`` as an explicit, absolute working root. Passing it as
    ``cwd`` alone is NOT sufficient: when the campaign runs against a git
    worktree (the standard way to run two arms of a comparison without them
    colliding) and the description mentions file paths, an agent will happily
    resolve those paths against whichever checkout of the project it already
    knows about. Observed for real: a build stage with ``cwd`` set to its
    worktree read and then EDITED the canonical repo instead, which would
    have let two supposedly independent campaigns overwrite each other's
    mechanism.
    """
    target = campaign.get("target_system") or {}
    opt = campaign.get("optimization") or {}
    rq = (campaign.get("research_question") or "").strip()
    description = (target.get("description") or "").strip()
    test_command = (opt.get("test_command") or "").strip()
    run_command = (opt.get("run_command") or "").strip()
    repo = str(target.get("repo_path") or "").strip()

    tests_block = "\n".join(f"  - {t}" for t in declared_tests) or "  (none declared)"

    locked = campaign.get("locked_parameters") or {}
    locked_block = "\n".join(f"  - {k}: {v}" for k, v in locked.items()) or "  (none)"

    return f"""You are implementing a mechanism in a target repository so that a
factorial optimization experiment can then measure it. Write code and tests only.
Do NOT run the experiment, do not benchmark, do not tune parameters, and do not
edit the campaign.

WORKING ROOT — READ THIS FIRST
  {repo}

Every file you read, edit, or create must be under that exact directory. It may
be a git worktree or a copy of a project you have seen elsewhere; if so, other
checkouts of the same project exist on this machine and editing one of those
instead would corrupt a parallel experiment and silently invalidate both. So:

  - resolve every relative path in the specification below against that root;
  - never substitute a path from a different checkout, even when it looks like
    the same project and the file names match;
  - if a path you are about to touch does not start with that root, stop and
    re-derive it.

RESEARCH QUESTION
{rq}

WHAT TO BUILD (authored by the campaign author; treat as the specification)
{description}

NATIVE TESTS THAT MUST EXIST AND PASS
These exact identifiers are declared as correctness relations. A later stage
runs the test command below and treats any declared test that did not execute
as a FAILURE, which aborts the campaign. So every identifier here must exist,
be discoverable by that command, and pass:
{tests_block}

TEST COMMAND (the gate will run exactly this)
  {test_command}

Verify your work with that exact command before you finish. If an identifier in
the list does not appear in its output as a run test, the campaign will abort
even though your code may be correct.

LOCKED PARAMETERS (the experiment's fixed regime — do not change these, and do
not add code that overrides them)
{locked_block}

THE EXPERIMENT'S RUN COMMAND (for context only — do not run it)
  {run_command}

REQUIREMENTS
1. Tests must be native to the target's language and live in the target repo,
   using the target's own test tooling. Do not add a new test framework or a
   new dependency for this.
2. Where the specification asks for property-based or metamorphic tests, write
   them as such — assert the invariant across a swept or randomized input
   space, not at two or three hand-picked points. These tests are the only
   thing standing between a mis-wired mechanism and a confidently wrong result.
3. Preserve existing behaviour exactly where the specification says a default
   must be unchanged. Existing tests must keep passing.
4. Make invalid input fail loudly. A mechanism that silently falls back to its
   default turns a typo into a fabricated null result.
5. Follow the plumbing path the specification names rather than inventing a
   parallel one.

When you are done, reply with a short plain-text summary: the files you changed,
the flag or API you added, and the output of the test command. No JSON.
"""


def run_build(
    campaign: dict,
    work_dir: Path,
    *,
    iteration: int,
    declared_tests: list[str],
    model: str | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    sdk_runner: Callable | None = None,
    **_ignored,
) -> dict:
    """Spend one agent call authoring the mechanism. Return a metrics dict.

    ``sdk_runner`` is the injection seam, matching ``SDKDispatcher``: tests
    pass a callable returning an ``SDKResult`` and never touch the network.
    """
    from orchestrator.metrics import log_metrics
    from orchestrator.sdk_dispatch import (
        _default_sdk_runner_factory,
        _load_methodology_preamble,
    )

    target = campaign.get("target_system") or {}
    repo = target.get("repo_path")
    if not repo:
        raise BuildFailed(
            "build stage requires target_system.repo_path — there is no "
            "repository to author the mechanism in.",
        )

    # Resolve the build model through the same precedence the rest of Nous
    # uses (campaign.models > defaults.yaml > --model flag) rather than
    # hardcoding a fallback here. defaults.yaml pins `build` to the strongest
    # available model: it is the single agent call of the whole campaign, and
    # every later stage measures whatever it writes, so a weaker model here
    # degrades every downstream number.
    from orchestrator.campaign import _resolve_model

    resolved_model = model or _resolve_model(campaign, "build", None)

    prompt = build_prompt(campaign, declared_tests)
    runner = sdk_runner or _default_sdk_runner_factory()

    prompts_dir = ((campaign.get("prompts") or {}).get("methodology_layer"))
    system_prompt = None
    if prompts_dir:
        try:
            system_prompt = _load_methodology_preamble(Path(prompts_dir))
        except OSError as exc:  # a missing preamble must not be fatal
            logger.warning("build: could not load methodology preamble: %s", exc)

    iter_dir = Path(work_dir) / "runs" / f"iter-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    sandbox = campaign.get("sandbox", "bypass")
    permission_mode = "bypassPermissions" if sandbox == "bypass" else None

    logger.info(
        "build: authoring mechanism in %s (%d declared native test(s), "
        "max_turns=%d, model=%s)", repo, len(declared_tests), max_turns,
        resolved_model,
    )

    result = runner(
        prompt=prompt,
        model=resolved_model,
        cwd=Path(repo),
        max_turns=max_turns,
        system_prompt=system_prompt,
        event_log_path=iter_dir / "build_events.jsonl",
        permission_mode=permission_mode,
    )

    if getattr(result, "is_error", False):
        raise BuildFailed(
            f"build stage agent call failed: "
            f"{getattr(result, 'error_message', '') or 'unknown error'}",
        )

    text = (getattr(result, "text", "") or "").strip()
    (iter_dir / "build_summary.md").write_text(text or "(no summary returned)")

    row = {
        "dispatcher": "sdk",
        "role": "builder",
        "phase": "build",
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
    log_metrics(Path(work_dir) / "llm_metrics.jsonl", row)

    if not text:
        # Not fatal: verify is the real gate. But an empty summary usually
        # means the agent did nothing, and saying so now beats a confusing
        # abort one stage later.
        logger.warning(
            "build: agent returned no summary text — verify will decide "
            "whether anything was actually authored",
        )

    stray = check_build_touched_repo(Path(repo))
    if stray:
        logger.warning("build: %s", stray)
        (iter_dir / "build_warning.txt").write_text(stray + "\n")
    return row


def declared_native_tests(factors) -> list[str]:
    """Every distinct ``native_test`` declared across all factors' relations.

    Order-stable (first declaration wins) so the prompt is deterministic for
    a given campaign, which keeps the build call cache-friendly.
    """
    seen: dict[str, None] = {}
    for f in factors:
        for rel in getattr(f, "relations", ()) or ():
            name = rel.get("native_test") if isinstance(rel, dict) else None
            if name:
                seen.setdefault(name, None)
    return list(seen)
