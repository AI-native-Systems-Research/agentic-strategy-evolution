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


def _mechanism_text(repo: Path) -> str | None:
    """Canonical text of everything the build stage changed under ``repo``.

    ``git diff HEAD`` covers tracked edits; new files are invisible to it, and
    a new file is the COMMON case for a mechanism (a new module, a new test
    file). So untracked-but-not-ignored files are appended by content under an
    ``+++ untracked: <path>`` marker, sorted so the text is a function of the
    tree rather than of git's listing order.

    Returns None — not "" — when ``repo`` is not a git work tree or git is
    absent. The distinction matters: "" is a legitimate hash input (a git repo
    with no changes at all), while None means "no oracle available here", which
    callers must not turn into a hash that could later be compared against.
    """
    import subprocess

    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--no-color"], cwd=str(repo),
            capture_output=True, text=True, timeout=120,
        )
        if diff.returncode != 0:
            return None
        others = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(repo), capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = [diff.stdout]
    for rel in sorted(p for p in others.stdout.splitlines() if p.strip()):
        try:
            parts.append(f"+++ untracked: {rel}\n" + (repo / rel).read_text())
        except (OSError, UnicodeDecodeError):
            parts.append(f"+++ untracked: {rel}\n<binary or unreadable>\n")
    return "".join(parts)


def current_mechanism_hash(repo: Path) -> str:
    """Hash the target's current working tree the same way ``snapshot_mechanism`` did.

    Recomputed from the tree on every call — never cached, never read back from
    ``mechanism.sha256``. That is the whole point: the drift check compares a
    FRESH reading against the recorded one, so a check that trusted the stored
    value would be no check at all.
    """
    import hashlib

    text = _mechanism_text(Path(repo))
    return "" if text is None else hashlib.sha256(text.encode()).hexdigest()


def snapshot_mechanism(repo: Path, work_dir: Path) -> str:
    """Record the target's post-build diff and its hash next to the campaign.

    Written once, right after ``build`` authors the mechanism, and thereafter
    read-only: it is the pre-registration of WHICH CODE the epoch's numbers
    describe. ``mechanism.patch`` is the human-readable record (a reviewer can
    read what was built without the target repo in hand); ``mechanism.sha256``
    is what the epoch's drift check and the compiled policy's
    ``mechanism_patch_hash`` key on.

    Returns "" and writes nothing for a non-git target, so a campaign against a
    directory that is not under version control is not penalised — it simply
    gets no drift oracle, and the absence of the file is what disables the
    check rather than a hash that would never match.
    """
    text = _mechanism_text(Path(repo))
    if text is None:
        return ""
    import hashlib

    h = hashlib.sha256(text.encode()).hexdigest()
    (Path(work_dir) / "mechanism.patch").write_text(text)
    (Path(work_dir) / "mechanism.sha256").write_text(h + "\n")
    return h


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

BUDGET DISCIPLINE — read this before you start probing
This is ONE call, and it is the only call in the campaign that spends tokens on
the target. Everything after it is tokenless. So:

  - Write the mechanism and its tests. That is the deliverable. Exploratory
    scripts, grid searches, and attribution probes are spend that buys no
    measurement.
  - Reference numbers in the specification are for a ONE-TIME sanity check, not
    a target to fit. Reproduce them once. If your first faithful implementation
    disagrees with one, say so in your summary and keep going — a documented
    divergence is a finding for a human to adjudicate, and it is far cheaper
    than a search for a variant that matches. The specification's author may
    simply have mislabelled a leg.
  - If the spec asks for behaviour you cannot find in the target, do not go
    hunting for it across the codebase. Note it as absent and implement what is
    specified minus that piece.
  - Delete any temporary probe scripts you create before you finish.

When you are done, reply with a short plain-text summary: the files you changed,
the flag or API you added, the output of the test command, and any place where a
reference number in the specification did not reproduce. No JSON.
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


def baseline_runs(
    config_runner: Callable, factors, baseline: dict, *, n: int, metric: str,
) -> list[float]:
    """Measure the ``known_valid_baseline`` configuration ``n`` times.

    Oracle 2(c) (spec §3.7): the campaign's declared control must behave the
    same before and after ``build``. If the mechanism the build authored moves
    the metric even at its OFF level, it is not inert, and every treatment
    effect the epoch measures is confounded with whatever else the build
    changed. Measured rather than argued: the same configuration, the same
    runner, before and after.

    ``row_index`` is NEGATIVE (``-1 - i``) on purpose. These runs are not part
    of the pre-registered design matrix, and a non-negative index would collide
    with a real design row in ``check_fidelity``'s bookkeeping and in
    ``failed_runs/failed_run_<idx>.log``. ``role="baseline"`` says the same
    thing to any reader of the observation.

    Returns raw floats — no aggregation, no rejection. NaN is passed through as
    NaN so the caller can distinguish "the control did not run" from "the
    control ran and moved", which are different failures with different fixes.
    """
    from orchestrator.optimize.matrix import ConfigRow, render_apply

    out: list[float] = []
    for i in range(n):
        row = ConfigRow(
            row_index=-1 - i, levels=dict(baseline), role="baseline",
            replicate=i, apply=render_apply(factors, baseline),
        )
        obs = config_runner(row)
        out.append(float((obs or {}).get(metric, float("nan"))))
    return out


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
