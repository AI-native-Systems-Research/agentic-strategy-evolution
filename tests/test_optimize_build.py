"""Behavioral tests for the ``build`` stage (mechanism authoring).

No live LLM calls: every test injects ``sdk_runner=`` at the seam
:mod:`orchestrator.optimize.build` exposes for exactly that purpose, mirroring
``SDKDispatcher(sdk_runner=...)``. Assertions are about what lands on disk and
in ``llm_metrics.jsonl``, never about which method a mock saw.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.optimize import build as build_mod
from orchestrator.optimize.build import build_prompt
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.stage import Stage, stage_for_iteration
from orchestrator.sdk_dispatch import SDKResult


def _campaign(repo: Path, *, stages=None) -> dict:
    return {
        "kind": "optimization",
        "run_id": "build-test",
        "research_question": "Does the new curve beat linear?",
        "target_system": {
            "name": "T",
            "repo_path": str(repo),
            "description": "Add --ceiling-curve with linear|exponential.",
        },
        "locked_parameters": {"seed": 42},
        "sandbox": "bypass",
        "optimization": {
            "response": {"primary": {"metric": "goodput", "direction": "maximize"}},
            "factors": [
                {
                    "id": "CURVE",
                    "name": "ceiling_curve",
                    "type": "choice",
                    "levels": ["linear", "exponential"],
                    "apply": "--ceiling-curve={level}",
                    "manipulation": {
                        "observable": "applied.CURVE", "op": "==", "value": "{level}",
                    },
                    "relations": [
                        {
                            "id": "R1", "kind": "correctness",
                            "statement": "linear matches the legacy formula",
                            "native_test": "sim/curve_test.go::TestLinearLegacy",
                        },
                        {
                            "id": "R2", "kind": "correctness",
                            "statement": "invariants hold across the input space",
                            "native_test": "sim/curve_test.go::TestInvariants",
                        },
                    ],
                },
            ],
            "stages": stages or ["build", "verify", "screen", "confirm"],
            "design": {"screen": {"resolution": 3}, "confirm": {"replicates": 2}},
            "test_command": "go test ./sim/... -v",
            "run_command": "./bin run",
        },
    }


def _runner(result: SDKResult, seen: list[dict] | None = None):
    def _call(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        return result

    return _call


def test_build_writes_summary_and_metrics_row(tmp_path: Path):
    """One build call produces a readable summary and exactly one metrics row."""
    repo = tmp_path / "repo"
    repo.mkdir()
    work = tmp_path / "work"
    campaign = _campaign(repo)

    build_mod.run_build(
        campaign, work,
        iteration=1,
        declared_tests=["sim/curve_test.go::TestLinearLegacy"],
        sdk_runner=_runner(SDKResult(
            text="Added --ceiling-curve; go test passes.",
            input_tokens=1200, output_tokens=340, cost_usd=0.02, num_turns=7,
        )),
    )

    summary = (work / "runs" / "iter-1" / "build_summary.md").read_text()
    assert "ceiling-curve" in summary

    rows = [
        json.loads(line)
        for line in (work / "llm_metrics.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["phase"] == "build"
    assert rows[0]["role"] == "builder"
    assert rows[0]["output_tokens"] == 340


def test_build_counts_tokens_so_the_cost_claim_stays_honest(tmp_path: Path):
    """Build-stage tokens must reach llm_metrics.jsonl.

    The whole selling point of this campaign kind is a measured token budget.
    A stage that spent tokens without recording them would make every cost
    comparison understate the real bill.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    work = tmp_path / "work"

    build_mod.run_build(
        _campaign(repo), work,
        iteration=1,
        declared_tests=[],
        sdk_runner=_runner(SDKResult(
            text="done",
            input_tokens=5000, output_tokens=2500,
            cache_read_input_tokens=90_000, cache_creation_input_tokens=1_000,
        )),
    )
    row = json.loads((work / "llm_metrics.jsonl").read_text().splitlines()[0])
    assert row["input_tokens"] == 5000
    assert row["output_tokens"] == 2500
    assert row["cache_read_input_tokens"] == 90_000
    assert row["cache_creation_input_tokens"] == 1_000


def test_build_raises_on_sdk_error(tmp_path: Path):
    """A failed call must abort loudly, not silently proceed to verify."""
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(build_mod.BuildFailed, match="quota"):
        build_mod.run_build(
            _campaign(repo), tmp_path / "work",
            iteration=1,
            declared_tests=[],
            sdk_runner=_runner(SDKResult(
                text="", is_error=True, error_message="quota exhausted",
            )),
        )


def test_build_requires_repo_path(tmp_path: Path):
    campaign = _campaign(tmp_path)
    campaign["target_system"]["repo_path"] = ""
    with pytest.raises(build_mod.BuildFailed, match="repo_path"):
        build_mod.run_build(
            campaign, tmp_path / "work", iteration=1, declared_tests=[],
            sdk_runner=_runner(SDKResult(text="x")),
        )


def test_build_runs_in_the_target_repo(tmp_path: Path):
    """The agent must be pointed at the target, not at the Nous checkout.

    With per-arm worktrees this is what keeps two campaigns from editing each
    other's copy of the target.
    """
    repo = tmp_path / "wt" / "armA"
    repo.mkdir(parents=True)
    seen: list[dict] = []
    build_mod.run_build(
        _campaign(repo), tmp_path / "work",
        iteration=1, declared_tests=[],
        sdk_runner=_runner(SDKResult(text="ok"), seen),
    )
    assert Path(seen[0]["cwd"]) == repo


def test_prompt_names_every_declared_test_and_the_test_command(tmp_path: Path):
    """The build prompt and the verify gate must agree on the test identifiers.

    If the prompt omitted one, the agent could finish happily and verify would
    still abort — the failure mode this stage exists to prevent.
    """
    campaign = _campaign(tmp_path)
    factors = parse_factors(campaign["optimization"]["factors"])
    declared = build_mod.declared_native_tests(factors)
    prompt = build_mod.build_prompt(campaign, declared)

    assert "sim/curve_test.go::TestLinearLegacy" in prompt
    assert "sim/curve_test.go::TestInvariants" in prompt
    assert "go test ./sim/... -v" in prompt
    # It must not invite the agent to run the experiment itself.
    assert "do not run" in prompt.lower() or "do NOT" in prompt


def test_declared_native_tests_dedups_and_keeps_order(tmp_path: Path):
    """Two relations citing one test yield one prompt entry, order stable."""
    campaign = _campaign(tmp_path)
    campaign["optimization"]["factors"][0]["relations"].append({
        "id": "R3", "kind": "correctness", "statement": "same test again",
        "native_test": "sim/curve_test.go::TestLinearLegacy",
    })
    factors = parse_factors(campaign["optimization"]["factors"])
    assert build_mod.declared_native_tests(factors) == [
        "sim/curve_test.go::TestLinearLegacy",
        "sim/curve_test.go::TestInvariants",
    ]


def test_build_is_not_in_the_default_stage_order(tmp_path: Path):
    """Campaigns written before `build` existed must be unaffected."""
    campaign = _campaign(tmp_path)
    campaign["optimization"].pop("stages")
    assert stage_for_iteration(campaign, 1) is Stage.VERIFY


def test_build_is_stage_one_when_declared(tmp_path: Path):
    campaign = _campaign(tmp_path)
    assert stage_for_iteration(campaign, 1) is Stage.BUILD
    assert stage_for_iteration(campaign, 2) is Stage.VERIFY


def test_build_then_verify_end_to_end(tmp_path: Path, monkeypatch):
    """BUILD authors code and CONTINUEs; VERIFY independently gates it.

    The separation is the safety property: the stage that writes the mechanism
    must not be the stage that certifies it. Here the build call "succeeds"
    (it writes a file and returns cleanly) but the test command reports no
    per-test results, so verify must still abort fail-closed.
    """
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "campaigns"))

    campaign = _campaign(repo, stages=["build", "verify", "screen", "confirm"])
    campaign["run_id"] = "e2e"
    # `true` exits 0 while reporting nothing — the "package-level ok is not
    # evidence a specific test ran" case.
    campaign["optimization"]["test_command"] = "true"

    authored: list[Path] = []

    def fake_sdk(**kwargs):
        path = Path(kwargs["cwd"]) / "sim" / "curve_test.go"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// authored by the build stage\n")
        authored.append(path)
        return SDKResult(text="wrote curve_test.go", input_tokens=100, output_tokens=50)

    work = setup_work_dir("e2e", repo_path=str(repo), campaign=campaign)

    outcome = run_stage(
        campaign, work, iteration=1, sdk_runner=fake_sdk, auto_approve=True,
    )
    assert outcome is IterationOutcome.CONTINUE
    assert len(authored) == 1, "build must spend exactly one agent call"
    assert (repo / "sim" / "curve_test.go").exists()

    rows = [
        json.loads(line)
        for line in (work / "llm_metrics.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert [r["phase"] for r in rows] == ["build"]

    with pytest.raises(OptimizationAborted, match="verify"):
        run_stage(campaign, work, iteration=2, auto_approve=True)


def test_build_stage_does_not_run_the_test_command(tmp_path: Path, monkeypatch):
    """On a build iteration the target's tests must not run.

    The mechanism does not exist yet, so the run could only report the already
    known fact that the declared identifiers are missing. Worse, `go test -run`
    with a non-matching pattern exits 0 with "no tests to run", so a pre-build
    run looks like a pass at the shell level.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "campaigns"))
    campaign = _campaign(repo)
    campaign["run_id"] = "nobuildtest"
    sentinel = tmp_path / "ran.txt"
    campaign["optimization"]["test_command"] = f"touch {sentinel}"

    work = setup_work_dir("nobuildtest", repo_path=str(repo), campaign=campaign)
    run_stage(
        campaign, work, iteration=1, auto_approve=True,
        sdk_runner=lambda **kw: SDKResult(text="ok"),
    )
    assert not sentinel.exists(), "test_command must not run during build"


def test_prompt_states_the_absolute_working_root(tmp_path: Path):
    """cwd alone is not enough to keep the build inside a worktree.

    Observed for real: a build stage whose cwd was its own worktree read and
    then EDITED the canonical checkout of the same project, because the
    specification mentioned file paths and the agent resolved them against the
    repo it already knew. Two supposedly independent arms would then overwrite
    each other's mechanism. The prompt must name the root explicitly.
    """
    repo = tmp_path / "inference-sim" / ".nous-experiments" / "exp2" / "armA"
    repo.mkdir(parents=True)
    prompt = build_prompt(_campaign(repo), [])
    assert str(repo) in prompt
    lead = prompt[: prompt.index(str(repo))]
    assert "WORKING ROOT" in lead, "the root must be stated up front, not buried"
    assert "worktree" in prompt


def test_pristine_git_tree_after_build_is_reported(tmp_path: Path):
    """A build that changed nothing in a git target is suspicious, not silent."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        cwd=repo, check=True,
    )

    assert build_mod.check_build_touched_repo(repo) is not None

    (repo / "f.txt").write_text("changed\n")
    assert build_mod.check_build_touched_repo(repo) is None


def test_non_git_target_is_not_penalised(tmp_path: Path):
    """A target that is not a git work tree must not trip the check."""
    repo = tmp_path / "plain"
    repo.mkdir()
    assert build_mod.check_build_touched_repo(repo) is None


def test_build_writes_a_warning_file_when_the_tree_is_untouched(tmp_path: Path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        cwd=repo, check=True,
    )
    work = tmp_path / "work"
    build_mod.run_build(
        _campaign(repo), work, iteration=1, declared_tests=[],
        sdk_runner=_runner(SDKResult(text="claimed success, changed nothing")),
    )
    warning = (work / "runs" / "iter-1" / "build_warning.txt").read_text()
    assert "no local modifications" in warning


def test_verify_abort_separates_missing_tests_from_failing_ones():
    """The two failure modes need OPPOSITE fixes, so the message must split them.

    After a build stage the agent call is already spent, so a message that
    conflates "the test never ran" with "the assertion failed" costs a whole
    second build to rediscover which one it was.
    """
    from orchestrator.optimize.relations import RelationVerdict
    from orchestrator.optimize.stage_runner import _verify_abort_message

    msg = _verify_abort_message([
        RelationVerdict(
            relation_id="R_MISSING", factor_id="A", kind="correctness",
            native_test="t.go::TestGone", passed=False,
            detail="declared native_test 't.go::TestGone' but it was not executed",
        ),
        RelationVerdict(
            relation_id="R_BROKEN", factor_id="B", kind="correctness",
            native_test="t.go::TestReal", passed=False,
            detail="native_test 't.go::TestReal' failed",
        ),
    ])
    assert "NEVER EXECUTED" in msg and "RAN AND FAILED" in msg
    # each id must appear under the right heading
    never = msg.index("NEVER EXECUTED")
    ran = msg.index("RAN AND FAILED")
    assert msg.index("R_MISSING") > never
    assert ran < msg.index("R_BROKEN") < never
    # the go-test-exits-0 trap is the reason "not executed" is silent
    assert "matches nothing" in msg


def test_verify_abort_message_omits_empty_sections():
    from orchestrator.optimize.relations import RelationVerdict
    from orchestrator.optimize.stage_runner import _verify_abort_message

    msg = _verify_abort_message([
        RelationVerdict(
            relation_id="R1", factor_id="A", kind="correctness",
            native_test="t.go::T1", passed=False, detail="native_test failed",
        ),
    ])
    assert "RAN AND FAILED" in msg
    assert "NEVER EXECUTED" not in msg


def test_test_command_output_is_preserved_verbatim(tmp_path: Path):
    """The gate needs booleans; a human fixing it needs the text.

    A verify abort ends the campaign, so this output is the only record of why
    — and re-running by hand may not reproduce a timeout or an
    ordering-dependent failure.
    """
    from orchestrator.optimize.runner import run_test_command

    log = tmp_path / "runs" / "iter-1" / "test_output.log"
    run_test_command(
        "sh -c 'echo --- FAIL: TestX; echo want=3 got=7; echo boom >&2; exit 1'",
        cwd=tmp_path, log_path=log,
    )
    text = log.read_text()
    assert "want=3 got=7" in text, "the assertion detail must survive"
    assert "boom" in text, "stderr must survive"
    assert "exit=1" in text


def test_failed_config_run_keeps_full_output_not_a_200_char_tail(tmp_path: Path):
    """A failed benchmark run is the most diagnostic-hungry event in a campaign."""
    import re

    import pytest as _pytest

    from orchestrator.optimize.runner import make_config_runner

    class _Row:
        row_index = 4
        levels = {"A": 1}
        apply = {"cli_args": [], "env": {}}

    logs = tmp_path / "failed_runs"
    # 600 chars of stderr: more than the old 200-char tail, and the cause is
    # at the START, which a tail would have dropped.
    run = make_config_runner(
        "sh -c 'echo CAUSE: unknown flag --nope >&2; "
        "python3 -c \"print(\\\"x\\\"*600)\" >&2; exit 2'",
        cwd=tmp_path, metric_path="m", log_dir=logs,
    )
    with _pytest.raises(RuntimeError, match="exited 2"):
        run(_Row())

    saved = (logs / "failed_run_4.log").read_text()
    assert "CAUSE: unknown flag --nope" in saved, (
        "the cause is at the head of stderr and a tail would have lost it"
    )
    assert "row_index: 4" in saved
    assert "levels" in saved


def test_unparseable_output_is_kept_because_it_nan_poisons_a_fit(tmp_path: Path):
    import pytest as _pytest

    from orchestrator.optimize.runner import make_config_runner

    class _Row:
        row_index = 0
        levels = {"A": 1}
        apply = {"cli_args": [], "env": {}}

    logs = tmp_path / "failed_runs"
    run = make_config_runner(
        "sh -c 'echo not json at all'", cwd=tmp_path, metric_path="m", log_dir=logs,
    )
    with _pytest.raises(RuntimeError, match="no parseable JSON"):
        run(_Row())
    assert "not json at all" in (logs / "failed_run_0.log").read_text()


def test_logging_is_optional_and_never_breaks_the_run(tmp_path: Path):
    """log_path/log_dir default to None: existing callers are unaffected."""
    from orchestrator.optimize.runner import run_test_command

    assert run_test_command("sh -c 'echo --- PASS: TestA'", cwd=tmp_path) == {
        "TestA": True,
    }


def test_optimization_kind_resolves_every_phase_to_opus_5():
    """`kind: optimization` uses the strongest model for all of its few calls.

    This kind makes only a handful of model calls — one build (which authors the
    mechanism every later stage measures), one interpretation, and a small gate
    summary per iteration — while tokenless stages carry the bulk of the work.
    So the marginal cost of the strongest model is small and the downside of a
    weaker one on the build call is that every downstream number describes worse
    code.
    """
    from orchestrator.campaign import OPTIMIZATION_MODEL, _resolve_model

    opt = {"kind": "optimization"}
    for phase in ("build", "design", "execute_analyze", "report"):
        assert _resolve_model(opt, phase, None) == OPTIMIZATION_MODEL


def test_reflective_model_defaults_are_untouched():
    """The reflective per-phase defaults must not shift under this change."""
    from orchestrator.campaign import _resolve_model

    assert _resolve_model({}, "design", None) == "claude-opus-4-6"
    assert _resolve_model({"kind": "reflective"}, "design", None) == "claude-opus-4-6"
    # and a reflective campaign never picks up the optimization default
    from orchestrator.campaign import OPTIMIZATION_MODEL
    assert _resolve_model({}, "report", None) != OPTIMIZATION_MODEL


def test_explicit_campaign_model_beats_the_kind_default():
    """An author can still pin a cheaper model per phase."""
    from orchestrator.campaign import _resolve_model

    camp = {"kind": "optimization", "models": {"report": "aws/claude-haiku-4-5"}}
    assert _resolve_model(camp, "report", None) == "aws/claude-haiku-4-5"
    assert _resolve_model(camp, "build", None) == "claude-opus-5"


def test_build_records_the_resolved_model_in_metrics(tmp_path: Path):
    """The metrics row must name the model actually used, for cost accounting."""
    repo = tmp_path / "repo"
    repo.mkdir()
    work = tmp_path / "work"
    build_mod.run_build(
        _campaign(repo), work, iteration=1, declared_tests=[],
        sdk_runner=_runner(SDKResult(text="ok", input_tokens=10, output_tokens=5)),
    )
    row = json.loads((work / "llm_metrics.jsonl").read_text().splitlines()[0])
    assert row["model"] == "claude-opus-5"


def test_build_prompt_forbids_fitting_reference_numbers(tmp_path: Path):
    """The build call must not be spent grid-searching to match a spec figure.

    Observed for real across three aborted builds: a spec labelled a baseline leg
    with a behaviour the target's evaluator did not actually model, alongside an
    otherwise-correct figure. The agent could not tell a mislabelled spec from a
    wrong implementation, so it spent twenty-plus shell probes chasing an
    unclosable gap instead of writing the mechanism. The prompt must tell it to
    record a divergence and continue.
    """
    prompt = build_prompt(_campaign(tmp_path), [])
    low = prompt.lower()
    assert "budget discipline" in low
    assert "not\n    a target to fit" in low or "a target to fit" in low
    assert "divergence" in low
    # and it must ask for the divergence back in the summary
    assert "did not reproduce" in low
