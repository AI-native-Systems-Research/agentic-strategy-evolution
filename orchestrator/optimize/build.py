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

#: Retries (beyond the first attempt) for the plan/build agent calls when
#: ``optimization.agent_retries`` is unset. Deliberately SMALL, unlike the
#: reflective dispatcher's 10: one real build attempt has cost ~$20 and ~30
#: minutes, so the budget only has to ride out an infra hiccup, not an outage.
DEFAULT_AGENT_RETRIES = 2

#: Live silence-watchdog default for plan/build — the DESIGN-phase value,
#: because both are heavy-reasoning turns with long gaps between tool calls.
DEFAULT_AGENT_SILENCE_SECONDS = 600.0

#: ``is_error`` results worth a fresh session. Kept small and explicit:
#: context exhaustion (a fresh session with the resume hint IS the recovery)
#: and provider-side overload / 5xx. Everything else — auth, invalid request,
#: quota, max-turns — fails fast, because retrying it only multiplies the bill.
_RETRYABLE_ERROR_PATTERNS = (
    "prompt is too long",
    "context length",
    "context window",
    "overloaded",
    "rate limit",
    "rate_limit",
    "internal server error",
    "api_error",
    # A status code only in a STATUS context. A bare `\b500\b` matched
    # `build_error_message`'s own diagnostics (`duration_ms=500`,
    # `num_turns=429`), turning a fail-fast authentication error into a paid
    # retry whenever a counter happened to land on one of these numbers.
    r"(status|http|error|code)\W{0,3}(code\W{0,3})?(429|500|502|503|504|529)\b",
)


def is_retryable_agent_error(result) -> bool:
    """True when an ``is_error`` plan/build result is worth a fresh attempt."""
    import re

    msg = (getattr(result, "error_message", "") or "").lower()
    return any(re.search(p, msg) for p in _RETRYABLE_ERROR_PATTERNS)


def resolve_agent_retries(campaign: dict) -> int:
    """``optimization.agent_retries``, else :data:`DEFAULT_AGENT_RETRIES`."""
    raw = (campaign.get("optimization") or {}).get("agent_retries")
    if raw is None:
        return DEFAULT_AGENT_RETRIES
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError(
            f"optimization.agent_retries must be a non-negative integer, "
            f"got {raw!r}"
        )
    return raw


#: Headroom above the declared test budget for the build's own verification run.
_BUILD_SILENCE_MARGIN_SECONDS = 120.0


def _default_silence(campaign: dict, phase: str) -> float:
    """The watchdog default when the campaign declares none.

    For ``build`` it is at least ``test_timeout_sec`` plus a margin, not a flat
    600s. The build prompt tells the agent to verify its work with the exact
    ``test_command`` before finishing, and a foreground tool call streams NO SDK
    events until it returns -- so on a campaign whose relation suite runs for
    1,100s (and declares ``test_timeout_sec`` to match), a 600s watchdog trips
    inside the agent's own verification, retries a fresh ~$20 session, and trips
    again. The suite budget the author declared is the honest lower bound on a
    silent stretch this call can legitimately have.
    """
    if phase != "build":
        return DEFAULT_AGENT_SILENCE_SECONDS
    from orchestrator.optimize.runner import DEFAULT_TEST_TIMEOUT_SEC

    opt = campaign.get("optimization") or {}
    test_budget = opt.get("test_timeout_sec")
    if not isinstance(test_budget, (int, float)) or isinstance(test_budget, bool):
        test_budget = DEFAULT_TEST_TIMEOUT_SEC
    return max(DEFAULT_AGENT_SILENCE_SECONDS,
               float(test_budget) + _BUILD_SILENCE_MARGIN_SECONDS)


def resolve_agent_silence_threshold(campaign: dict, phase: str) -> float:
    """Live watchdog threshold for the ``plan`` / ``build`` call.

    Reads ``sdk_timeouts.turn_silence_threshold_seconds`` with the same
    scalar-or-per-phase-map shape ``SDKDispatcher`` accepts: a scalar applies
    to every phase; a map is looked up by ``phase``. Unset (or a map without
    this phase) falls back to ``silence_threshold_seconds`` when the scalar
    form is absent, else the default from :func:`_default_silence`. ``0`` disables
    the watchdog, as for the reflective kind.
    """
    timeouts = campaign.get("sdk_timeouts") or {}
    raw = timeouts.get("turn_silence_threshold_seconds")
    label = "campaign.sdk_timeouts.turn_silence_threshold_seconds"
    default = _default_silence(campaign, phase)
    if isinstance(raw, dict):
        raw = raw.get(phase, default)
        label += f".{phase}"
    elif raw is None:
        raw = timeouts.get("silence_threshold_seconds", default)
        label = "campaign.sdk_timeouts.silence_threshold_seconds"
    if isinstance(raw, bool):
        raise ValueError(f"{label} must be a non-negative number, got {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be a non-negative number, got {raw!r}"
        ) from exc
    if value < 0:
        raise ValueError(f"{label} must be >= 0, got {value}")
    return value


def _agent_wall_clock(campaign: dict, phase: str) -> float | None:
    """Wall-clock ceiling for one plan/build attempt (#303).

    ``sdk_timeouts.phase_wall_clock_seconds`` when the campaign sets it for
    this phase. Otherwise the shared default -- raised for ``build`` to three
    of its silence windows, because the build reruns the author's own
    ``test_command`` (each run up to ``test_timeout_sec``) while verifying.
    """
    from orchestrator.sdk_dispatch import resolve_phase_wall_clock

    raw = (campaign.get("sdk_timeouts") or {}).get("phase_wall_clock_seconds")
    explicit = raw is not None and not (isinstance(raw, dict) and phase not in raw)
    value = resolve_phase_wall_clock(campaign, phase)
    if explicit or phase != "build" or value is None:
        return value
    return max(value, 3 * _default_silence(campaign, phase))


def run_agent_call(
    runner: Callable,
    *,
    campaign: dict,
    work_dir: Path,
    phase: str,
    role: str,
    iteration: int,
    model: str,
    prompt: str,
    runner_kwargs: dict,
    retry_sleep: Callable[[float], None] | None = None,
):
    """One plan/build agent call under the shared SDK retry loop.

    Wraps ``sdk_dispatch.call_sdk_with_retry`` — the same loop
    ``SDKDispatcher`` uses — with this kind's policy: a small retry budget
    (``optimization.agent_retries``), a live silence watchdog
    (:func:`resolve_agent_silence_threshold`), fail-fast on non-retryable
    ``is_error`` results, a ``retry_log.jsonl`` row per failure tagged with
    ``phase``, and an ``llm_metrics.jsonl`` row for EVERY completed attempt.

    Returns ``(result, metrics_row)`` for the successful attempt. Raises
    ``sdk_dispatch.SDKCallFailed`` (or ``ValueError`` for bad config); the
    caller translates that into its own ``BuildFailed`` / ``PlanRejected``.
    """
    from orchestrator.metrics import log_metrics
    from orchestrator.sdk_dispatch import call_sdk_with_retry

    metrics_path = Path(work_dir) / "llm_metrics.jsonl"
    max_retries = resolve_agent_retries(campaign)
    kwargs = dict(runner_kwargs)
    kwargs["turn_silence_threshold"] = resolve_agent_silence_threshold(
        campaign, phase,
    )
    kwargs["wall_clock_seconds"] = _agent_wall_clock(campaign, phase)
    rows: list[dict] = []

    def _log(result) -> None:
        row = {
            "dispatcher": "sdk",
            "role": role,
            "phase": phase,
            # `model` is what was REQUESTED (an alias, e.g. claude-opus-5);
            # `model_resolved` is what the SDK reported serving the turn, or
            # None when it reported nothing (audit Q10: the alias alone does
            # not say which snapshot authored the mechanism).
            "model": model,
            "model_resolved": getattr(result, "resolved_model", "") or None,
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
        rows.append(row)
        # Every attempt, BEFORE any error check: the tokens were spent whether
        # or not the attempt succeeded, and the cost axis must see them.
        log_metrics(metrics_path, row)

    result = call_sdk_with_retry(
        runner,
        prompt=prompt,
        runner_kwargs=kwargs,
        max_retries=max_retries,
        metrics_path=metrics_path,
        retry_context={"role": role, "phase": phase, "iteration": iteration},
        on_result=_log,
        is_retryable_error=is_retryable_agent_error,
        sleep=retry_sleep,
    )
    return result, rows[-1]


def agent_failure_message(stage: str, exc: BaseException) -> str:
    """Human message for an exhausted / fatal plan or build call."""
    attempts = getattr(exc, "attempts", None)
    last = getattr(exc, "last_error", None) or str(exc)
    if attempts is None:
        return f"{stage} stage agent call failed: {exc}"
    if getattr(exc, "retryable", True):
        return (
            f"{stage} stage agent call failed after {attempts} attempt(s) "
            f"(optimization.agent_retries exhausted); last error: {last}"
        )
    return (
        f"{stage} stage agent call failed with a non-retryable error on "
        f"attempt {attempts}: {last}"
    )


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


def _in_allowlist(rel: str, allowlist: list[str]) -> bool:
    """Does the repo-relative path ``rel`` fall under any allowlist entry?

    MATCHING RULE — plain prefix on path components, no globbing:

      - ``"src/mechanism.py"`` matches that file exactly;
      - ``"src/"`` (or ``"src"``) matches every path under that directory;
      - ``"src/mech"`` does NOT match ``"src/mechanism.py"`` — a partial
        component is not a match, because ``"log"`` silently covering
        ``"logs_from_the_test_runner/"`` is exactly the surprise this oracle
        cannot afford.

    Prefix rather than ``fnmatch``: an allowlist entry that is wrong widens the
    oracle's blind spot, and a glob is much easier to get subtly wrong than a
    directory name (``*`` matching across separators, ``[`` opening a character
    class, a bare ``mech*`` catching ``mech_backup.py.orig``). Directory-or-file
    prefix covers the documented use case — "the experiment is about these
    files and this directory" — with a rule a campaign author can verify by
    reading it once. Separators are normalised to ``/`` (git's own output
    format) so a Windows-style entry still matches.

    This rule is chosen to AGREE with the semantics git applies to the same
    entries as a ``git diff HEAD -- <paths>`` pathspec, which is how the
    tracked half of the mechanism text is scoped. Verified on all four
    interesting cases: ``src`` and ``src/`` both match ``src/a.py``, while the
    partial components ``src/a`` and ``mech`` match nothing. If the two halves
    disagreed about what an entry means, one channel would filter a file the
    other kept and the "scope" would be neither of the two.
    """
    r = rel.replace("\\", "/").strip("/")
    for entry in allowlist:
        e = str(entry).replace("\\", "/").strip("/")
        if not e:
            continue
        if r == e or r.startswith(e + "/"):
            return True
    return False


#: Repo-root directories Nous itself writes into a target tree. Never part of
#: a mechanism: ``.nous/`` holds the legacy campaign work_dirs
#: (``<target>/.nous/<run_id>/``, the default when ``NOUS_CAMPAIGN_PARENT`` is
#: unset) and the ``.nous/repo/`` cache ``campaign._write_repo_cache`` writes at
#: campaign end AND on the aborted path; ``.nous-experiments/`` holds the
#: per-arm worktrees (#133). See ``orchestrator/work_dir_resolver.py``.
NOUS_OWNED_PATHS: tuple[str, ...] = (".nous", ".nous-experiments")


def _nous_owned_prefixes(repo: Path, work_dir: Path | None) -> list[str]:
    """Repo-relative prefixes of Nous's own outputs under ``repo``.

    The fixed :data:`NOUS_OWNED_PATHS`, plus the campaign ``work_dir`` itself
    when it resolves inside ``repo`` (a ``NOUS_CAMPAIGN_PARENT`` pointed into
    the target, or a hand-chosen work_dir there). Both sides are resolved so a
    symlinked tmp dir (macOS ``/var`` -> ``/private/var``) still compares equal.
    """
    out = list(NOUS_OWNED_PATHS)
    if work_dir is not None:
        try:
            rel = Path(work_dir).resolve().relative_to(Path(repo).resolve())
        except (ValueError, OSError):
            rel = None
        if rel is not None:
            r = rel.as_posix().strip("/")
            # `relative_to` == "." means the work_dir IS the repo; excluding
            # that would exclude everything, which is never what it means.
            if r and r != "." and not _in_allowlist(r, out):
                out.append(r)
    return out


def _mechanism_text(
    repo: Path, *, allowlist: list[str] | None = None,
    work_dir: Path | None = None, exclude_nous_owned: bool = True,
) -> str | None:
    """Canonical text of everything the build stage changed under ``repo``.

    ``git diff HEAD`` covers tracked edits; new files are invisible to it, and
    a new file is the COMMON case for a mechanism (a new module, a new test
    file). So untracked-but-not-ignored files are appended by content under an
    ``+++ untracked: <path>`` marker, sorted so the text is a function of the
    tree rather than of git's listing order.

    ``allowlist`` narrows BOTH halves to the declared paths: the tracked diff
    via ``git diff HEAD -- <paths>``, the untracked listing via
    :func:`_in_allowlist`. Narrowing only one half would be worse than
    narrowing neither — the oracle would look scoped and still fire on a stray
    artifact through the other channel.

    ``allowlist=None`` (the default) is Task 12's original whole-tree
    behaviour: no target path is filtered from either half (only Nous's own
    outputs are — see below), so an existing campaign's recorded hash stays
    valid across this change. That default is deliberate. Whole-tree hashing
    has a real defect — Nous runs the target's own ``test_command`` with the
    repo as cwd, so a ``.pytest_cache/`` or ``run.log`` that git does not
    ignore reads as "the mechanism drifted" — but silently narrowing every
    existing campaign's oracle would trade a loud false positive for a quiet
    false negative, and only one of those two is discoverable by the person it
    misleads. So the narrowing is opt-in, via
    ``optimization.build_checks.mechanism_paths``.

    NOUS'S OWN OUTPUTS ARE ALWAYS EXCLUDED (``exclude_nous_owned``, default
    True), from BOTH halves, allowlist or not: ``.nous/`` and
    ``.nous-experiments/`` at the repo root, and ``work_dir`` when it resolves
    inside ``repo`` (:func:`_nous_owned_prefixes`). This is NOT the "silently
    narrowing an author's oracle" warned against above. That warning is about
    the target's files — which of them the experiment is about is the author's
    call, and only the author can make it. These paths are not the target's:
    Nous creates them, Nous appends to them during the epoch, and no mechanism
    can live in them. Including them was not a stricter oracle but a broken
    one: in the default layout (``NOUS_CAMPAIGN_PARENT`` unset, work_dir at
    ``<target>/.nous/<run_id>/``) the snapshot wrote ``mechanism.patch`` into
    the very tree it had just hashed, so the first epoch iteration of every
    such campaign aborted with "mechanism drifted", and every ``runs.jsonl``
    append would have done it again. ``exclude_nous_owned=False`` reproduces
    the pre-exclusion text exactly; it exists only so
    :func:`mechanism_hash_matches` can honour a hash recorded before this
    change.

    Returns None — not "" — when ``repo`` is not a git work tree or git is
    absent. The distinction matters: "" is a legitimate hash input (a git repo
    with no changes at all), while None means "no oracle available here", which
    callers must not turn into a hash that could later be compared against.
    """
    import subprocess

    paths = [p for p in (allowlist or []) if str(p).strip()]
    owned = _nous_owned_prefixes(repo, work_dir) if exclude_nous_owned else []
    diff_cmd = ["git", "diff", "HEAD", "--no-color"]
    if paths or owned:
        # An exclude-only pathspec means "everything except", so the
        # no-allowlist case still diffs the whole tree minus Nous's outputs.
        diff_cmd += ["--", *paths, *(f":(exclude){o}" for o in owned)]
    try:
        diff = subprocess.run(
            diff_cmd, cwd=str(repo),
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
        if paths and not _in_allowlist(rel, paths):
            continue
        if owned and _in_allowlist(rel, owned):
            continue
        try:
            parts.append(f"+++ untracked: {rel}\n" + (repo / rel).read_text())
        except (OSError, UnicodeDecodeError):
            parts.append(f"+++ untracked: {rel}\n<binary or unreadable>\n")
    return "".join(parts)


def current_mechanism_hash(
    repo: Path, *, allowlist: list[str] | None = None,
    work_dir: Path | None = None,
) -> str:
    """Hash the target's current working tree the same way ``snapshot_mechanism`` did.

    Recomputed from the tree on every call — never cached, never read back from
    ``mechanism.sha256``. That is the whole point: the drift check compares a
    FRESH reading against the recorded one, so a check that trusted the stored
    value would be no check at all.

    ``allowlist`` must be the SAME list ``snapshot_mechanism`` was given, or
    the comparison is between two different questions and every iteration
    "drifts". Both call sites resolve it from one place —
    ``stage_runner._mechanism_paths(campaign)`` — for that reason.

    ``work_dir`` likewise must be the campaign's work_dir, so the same
    Nous-owned paths are excluded on both sides (see :func:`_mechanism_text`).
    """
    import hashlib

    text = _mechanism_text(Path(repo), allowlist=allowlist, work_dir=work_dir)
    return "" if text is None else hashlib.sha256(text.encode()).hexdigest()


def mechanism_hash_matches(
    repo: Path, recorded: str, *, allowlist: list[str] | None = None,
    work_dir: Path | None = None,
) -> tuple[bool, str]:
    """Does the tree still hash to ``recorded``? Returns ``(ok, current)``.

    ``current`` is always the CURRENT-form hash (Nous-owned paths excluded),
    for the abort message. On a mismatch, the pre-exclusion form is computed
    too and accepted if it equals ``recorded``: a campaign snapshotted before
    the exclusion existed recorded that form, and must not false-abort on the
    resume that first runs this code. Accepting it is safe — the old form
    covers a strict superset of the new one, so equality there implies the
    mechanism is byte-identical. (An old hash recorded with the work_dir
    INSIDE the target never matched anything, since it covered the
    ``mechanism.patch`` written after it; that campaign could not resume
    before this change either, and after it a fresh campaign is the remedy.)
    """
    import hashlib

    current = current_mechanism_hash(repo, allowlist=allowlist, work_dir=work_dir)
    if current == recorded:
        return True, current
    legacy = _mechanism_text(
        Path(repo), allowlist=allowlist, exclude_nous_owned=False,
    )
    if legacy is not None and hashlib.sha256(legacy.encode()).hexdigest() == recorded:
        return True, current
    return False, current


def snapshot_mechanism(
    repo: Path, work_dir: Path, *, allowlist: list[str] | None = None,
) -> str:
    """Record the target's post-build diff and its hash next to the campaign.

    Written once, right after ``build`` authors the mechanism, and thereafter
    read-only: it is the pre-registration of WHICH CODE the epoch's numbers
    describe. ``mechanism.patch`` is the human-readable record (a reviewer can
    read what was built without the target repo in hand); ``mechanism.sha256``
    is what the epoch's drift check and the compiled policy's
    ``mechanism_patch_hash`` key on.

    ``allowlist`` scopes what counts as "the mechanism" — see
    :func:`_mechanism_text` for the matching rule and for why ``None`` (whole
    tree) is the backward-compatible default.

    Returns "" and writes nothing for a non-git target, so a campaign against a
    directory that is not under version control is not penalised — it simply
    gets no drift oracle, and the absence of the file is what disables the
    check rather than a hash that would never match.
    """
    text = _mechanism_text(Path(repo), allowlist=allowlist, work_dir=work_dir)
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


def build_prompt(
    campaign: dict,
    declared_tests: list[str],
    work_dir: Path | str | None = None,
) -> str:
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

    # `optimization.guidance.factor_nomination` is the author's steer about the
    # MECHANISM — which knob reaches what, which pathway to use, which failure
    # mode to avoid. It has to reach the stage that writes the mechanism, or a
    # field named "guidance" guides nobody. Observed for real: an author put a
    # target's known crash mode there, it reached no prompt, and the build shipped
    # exactly that defect.
    #
    # `guidance.interpretation` is deliberately NOT passed. It steers how RESULTS
    # are read, and `build` makes no correctness judgement — `verify` is the gate.
    # Handing the authoring agent the interpretation rules would invite it to
    # pre-judge the measurement it is not allowed to make.
    # The `plan` stage's artifact, when that opt-in stage ran. Absent is the
    # normal case and must render byte-identically to a campaign that never had a
    # plan stage — this is opt-in, and every campaign authored before it existed
    # has to behave the same.
    plan_block = ""
    if work_dir is not None:
        from orchestrator.optimize.plan import format_plan_for_build, read_plan
        plan_block = format_plan_for_build(read_plan(work_dir))

    guidance = (opt.get("guidance") or {}).get("factor_nomination") or ""
    guidance = guidance.strip()
    guidance_block = (
        f"""

AUTHOR'S GUIDANCE ON THE MECHANISM (optimization.guidance.factor_nomination)
{guidance}"""
        if guidance else ""
    )

    # The objective, so "make it fast" is a direction and a metric rather than a
    # sentiment. A build that does not know which way is better cannot weigh its
    # own bookkeeping against the work it removes.
    response = (opt.get("response") or {})
    primary = (response.get("primary") or {})
    metric = str(primary.get("metric") or "the primary metric").strip()
    direction = str(primary.get("direction") or "improve").strip()
    constraints = [
        f"{c.get('metric') or c.get('observable')} {c.get('op')} {c.get('value')}"
        for c in (response.get("constraints") or [])
        if isinstance(c, dict)
    ]
    constraints_clause = (
        " It is also subject to these declared constraints, which the mechanism "
        "must not spend to buy the primary metric: " + "; ".join(constraints) + "."
        if constraints else ""
    )

    # The write scope and the rules the build is CHECKED against (build_scope.py,
    # clean_tree.py): stated so the agent is told exactly what will be verified.
    scope_paths = [str(p) for p in ((opt.get("build_checks") or {}).get("mechanism_paths")
                                    or []) if str(p).strip()]
    scope_block = "\n".join(f"  - {p}" for p in scope_paths) or "  (none declared -- the build will be refused)"
    protected_note = (
        "  - the benchmark harness the run command uses"
        + (f" (`{run_command}`)" if run_command else "")
        + ", unless a file of it is listed above by its exact path;\n"
        "  - every pre-existing test file of the declared native tests.")
    scope_section = f"""

WRITE SCOPE — WHAT IS CHECKED
Only changes under these paths are part of the mechanism. After you finish, Nous
records exactly the diff of these paths against the pre-build commit, and every
later test and measurement runs in a clean checkout of that commit with that diff
applied -- anything you change elsewhere is not measured, and a write outside
these paths aborts the campaign:
{scope_block}
Never modify (the campaign aborts if you do):
{protected_note}
Never commit, stash, check out, reset or rebase; never change git config,
.git/info/exclude or per-file git flags (skip-worktree, assume-unchanged); never
leave a process running when you finish. Leave your edits uncommitted in the
working tree."""

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

{scope_section}

RESEARCH QUESTION
{rq}

WHAT TO BUILD (authored by the campaign author; treat as the specification)
{description}
{guidance_block}{plan_block}

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
6. THE MECHANISM HAS TO BE OPTIMAL IN THE OBJECTIVE'S OWN CURRENCY, not merely
   correct. This campaign is measured on `{metric}` ({direction}).{constraints_clause}
   A mechanism that is correct but costly in that currency is a FAILED mechanism:
   it will be measured as a regression and the campaign will recommend leaving it
   off, and the one call that could have authored it differently is already spent.

   So before you write it, state the cost of the mechanism ITSELF in the same
   currency as the objective, against the cost it removes. **The mechanism's own
   overhead must be strictly smaller than what it saves.** Say the two costs in
   asymptotic terms, in the size that actually varies at run time.
     - If the objective is TIME: the decision path is the overhead. A check that
       walks the same N items it is trying to skip cannot pay for itself no matter
       how much work it then avoids — hoist the decision to something readable in
       O(1), such as a counter or epoch bumped at the few places that genuinely
       invalidate it, rather than recomputing a summary over every item every
       time. Where the work avoided is a long run of small per-item calls, avoid
       the RUN in one step rather than each call in turn.
     - If the objective is MEMORY or space: the resident state you add is the
       overhead, and per-item bookkeeping that scales with N is the thing to
       avoid.
     - If a constraint above names a second budget, the mechanism must not buy the
       primary metric by spending that one — that is infeasible, not optimal.

SCOPE — what is and is not this stage's job
`kind: optimization` is frugal BY DESIGN: this is the campaign's one substantive
call and every state after it is tokenless. So do NOT economise here — the saving
is already banked, and this call determines the quality of every number the
campaign will report. Spend what the mechanism needs, including measuring your own
implementation to establish that it is worth enabling.

What is out of scope is a set of wrong ACTIVITIES, not a cost ceiling:

  - EXPLORE FREELY to find where the cost actually sits, to compare candidate
    implementations, and to confirm your own mechanism pays for itself. Profiling,
    counting calls, and timing two variants against each other are part of writing
    a mechanism worth enabling, not a distraction from it.
  - What you must NOT do is pre-empt the pre-registered experiment: do not search
    the declared factor LEVELS for a winner, and do not tune the campaign's knobs
    to a result. `screen` and `confirm` do that under a design fixed before any
    result was seen, which is what makes their answer admissible. Your job is to
    make the mechanism the best it can be at every level it will be measured at.
  - Reference numbers in the specification are a ONE-TIME sanity check, not a
    target to fit. Reproduce them once. If your faithful implementation disagrees
    with one, say so in your summary and keep going — a documented divergence is a
    finding for a human to adjudicate. The specification's author may simply have
    mislabelled a leg.
  - If the spec asks for behaviour you cannot find in the target, do not hunt for
    it across the codebase. Note it as absent and implement what is specified
    minus that piece.
  - Delete any temporary probe scripts you create before you finish.

BEFORE YOU FINISH — answer every item below in your summary
Each is a defect a real build shipped. "n/a, because ..." is an answer; silence is
not. The list is short because each line cost a campaign.

CORRECTNESS — the mechanism does what it claims
  C1. Every declared native_test exists, is discoverable by the test command, and
      passes. (An identifier the runner never reports counts as a FAILURE and
      aborts the campaign even when your code is right.)
  C2. The OFF/control level reproduces pre-existing behaviour exactly — bit-,
      byte- or pixel-identical wherever the target admits that comparison.
  C3. An unrecognised knob value fails LOUDLY. A silent fallback to the default
      turns a typo into a fabricated null result.
  C4. Every invariant the surrounding code relies on still holds on the fast
      path. Name the ones you had to preserve and how. A fast path that leaves a
      protocol half-finished crashes, or worse, computes the wrong answer.
  C5. Existing tests still pass, and any test you had to CHANGE was updated
      rather than deleted. Say which, and why the new assertion is the right one.
  C6. Your new tests FAIL against the unmodified tree. A test that is green
      without the mechanism is green for some other reason.

OPTIMALITY — the mechanism is worth enabling
  O1. The mechanism's own overhead, stated asymptotically in the objective's
      currency, is strictly smaller than the cost it removes. Give both figures.
  O2. Deciding to use the fast path is cheaper than the work that path skips.
  O3. Cost sits where it is paid ONCE — setup, or the rare invalidating event —
      not in the measured path.
  O4. You changed the algorithm, not just a constant, wherever a better
      complexity class was available. Say which you did.
  O5. No declared constraint is spent to buy the primary metric.
  O6. State the REGIME your choice assumes and roughly where it stops holding.
      An unstated assumption becomes an unexplained interaction at `screen`.

When you are done, reply with a plain-text summary: the files you changed, the
flag or API you added, the output of the test command, your answers to the
CORRECTNESS and OPTIMALITY items above, and any place where a reference number in
the specification did not reproduce. No JSON.
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
    retry_sleep: Callable[[float], None] | None = None,
    **_ignored,
) -> dict:
    """Spend one agent call authoring the mechanism. Return a metrics dict.

    ``sdk_runner`` is the injection seam, matching ``SDKDispatcher``: tests
    pass a callable returning an ``SDKResult`` and never touch the network.
    ``retry_sleep`` replaces the backoff sleep (tests pass a no-op).

    Transient failures and retryable ``is_error`` results are retried up to
    ``optimization.agent_retries`` times (see :func:`run_agent_call`); each
    retry is a fresh session told to CONTINUE from the repo's current state,
    never to restart. Exhaustion raises :class:`BuildFailed`.
    """
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

    # `work_dir` is REQUIRED here, not optional: it is how `build_prompt` finds
    # `mechanism_plan.json` and renders the MECHANISM PLAN block. Omitting it made
    # the `plan` stage write-only in production -- the stage ran, spent its agent
    # call, wrote a schema-checked plan, and `build` never saw a word of it, so the
    # build re-derived the mechanism from scratch (including alternatives the plan
    # had already priced and rejected). The block is ~27K chars on a real plan, so
    # the omission was a silent 26833-char difference in the prompt.
    prompt = build_prompt(campaign, declared_tests, work_dir)
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

    from orchestrator.sdk_dispatch import SDKCallFailed

    try:
        result, row = run_agent_call(
            runner,
            campaign=campaign, work_dir=work_dir, phase="build", role="builder",
            iteration=iteration, model=resolved_model, prompt=prompt,
            runner_kwargs=dict(
                model=resolved_model,
                cwd=Path(repo),
                max_turns=max_turns,
                system_prompt=system_prompt,
                event_log_path=iter_dir / "build_events.jsonl",
                permission_mode=permission_mode,
            ),
            retry_sleep=retry_sleep,
        )
    except ValueError as exc:
        raise BuildFailed(f"build stage misconfigured: {exc}") from exc
    except SDKCallFailed as exc:
        raise BuildFailed(agent_failure_message("build", exc)) from exc

    text = (getattr(result, "text", "") or "").strip()
    (iter_dir / "build_summary.md").write_text(text or "(no summary returned)")

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


#: Seed base for the baseline oracle's workload draws. A CONSTANT, and that is
#: the whole point: oracle 2(c) compares the same configuration measured at two
#: different moments in the campaign (once at ``build``, before the mechanism
#: exists; once at ``verify``, after it does), so the only thing that may vary
#: between the two measurements is the replicate index. Anything
#: iteration-derived — the base ``confirm`` uses, which is right there because
#: confirm's rounds are supposed to see FRESH draws — would hand pre and post
#: different workloads and reintroduce exactly the noise this seeding removes.
BASELINE_SEED_BASE = 0


def baseline_seeds(workload: dict | None, n: int) -> list[int] | None:
    """The workload common-random-numbers draws for ``n`` baseline replicates.

    Returns None when the campaign declares no ``optimization.workload.
    seed_env`` — the same opt-in convention every other CRN path in this kind
    uses (spec §3.8). None means "this comparison is unpaired", and callers must
    keep saying so in the artifact rather than claiming a pairing that did not
    happen.

    Seed *i* is a function of the replicate index alone, so replicate *i* of the
    PRE-build measurement and replicate *i* of the POST-build measurement run
    the same workload draw. That is what makes the oracle's tolerance mean
    something on a target whose workload variance dominates its configuration
    effect (a queue, a cache, an autoscaler — spec §2.6): the draw's
    contribution cancels out of the pre/post difference instead of being
    charged to the mechanism.

    The arithmetic is deliberately the same as
    ``stage_runner._assign_workload_seeds``' — ``workload.seeds`` taken verbatim
    modulo the index when declared, else ``(base * 7919 + i) % 2**31`` — so a
    reader comparing a baseline seed against a design-matrix seed is comparing
    two values produced the same way.
    """
    wl = workload or {}
    if not wl.get("seed_env"):
        return None
    declared = wl.get("seeds") or None
    if declared:
        return [int(declared[i % len(declared)]) for i in range(n)]
    return [(BASELINE_SEED_BASE * 7919 + i) % (2 ** 31) for i in range(n)]


def baseline_runs(
    config_runner: Callable, factors, baseline: dict, *, n: int, metric: str,
    workload: dict | None = None,
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

    ``workload`` is the campaign's ``optimization.workload`` block. When it
    declares ``seed_env``, every replicate carries the workload
    common-random-numbers draw for its index (:func:`baseline_seeds`) in
    ``apply["env"]``, exactly as the design-matrix rows and the ``confirm``
    replicates do. Seeded here rather than through
    ``stage_runner._assign_workload_seeds`` because these negative-indexed rows
    are deliberately OUTSIDE design-matrix bookkeeping (see above) and that
    function's payload cross-check does not apply to them — the seed arithmetic
    is shared, the bookkeeping is not.

    Returns raw floats — no aggregation, no rejection. NaN is passed through as
    NaN so the caller can distinguish "the control did not run" from "the
    control ran and moved", which are different failures with different fixes.
    """
    from orchestrator.optimize.matrix import ConfigRow, render_apply

    env_name = (workload or {}).get("seed_env")
    seeds = baseline_seeds(workload, n)
    out: list[float] = []
    for i in range(n):
        apply = render_apply(factors, baseline)
        if seeds is not None:
            apply = {**apply,
                     "env": {**(apply.get("env") or {}), env_name: seeds[i]}}
        row = ConfigRow(
            row_index=-1 - i, levels=dict(baseline), role="baseline",
            replicate=i, apply=apply,
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
