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


def test_build_stage_runs_the_test_command_before_authoring(tmp_path: Path, monkeypatch):
    """The build iteration DOES run the target's tests — before it builds.

    This inverts an earlier rule, and the reason is oracle 2(b) (spec §3.7): a
    declared correctness test that ALREADY PASSES before the mechanism exists
    does not test the mechanism, and `verify` cannot ask that question later
    because by then the code is there. So the pre-build verdicts are recorded in
    `pre_build_tests.json` and read at verify.

    The old rationale's real point — `go test -run <pattern>` exits 0 with "no
    tests to run", so a shell-level pass means nothing — is handled rather than
    avoided: verdicts come from the PER-TEST parse, where an identifier that
    never ran is absent, not passing. Asserted here on exactly that command
    shape (a command that exits 0 having reported no per-test result).

    The build iteration still makes no correctness judgement: it CONTINUEs
    regardless of what the pre-build run said.
    """
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "campaigns"))
    campaign = _campaign(repo)
    campaign["run_id"] = "prebuildtest"
    sentinel = tmp_path / "ran.txt"
    campaign["optimization"]["test_command"] = f"touch {sentinel}"

    # BEFORE, not merely "at some point": the sentinel must already exist by the
    # time the build agent is called, or the recorded verdicts describe a tree
    # the mechanism was already in.
    seen_at_build_time: list[bool] = []

    def _sdk(**kw):
        seen_at_build_time.append(sentinel.exists())
        return SDKResult(text="ok")

    work = setup_work_dir("prebuildtest", repo_path=str(repo), campaign=campaign)
    outcome = run_stage(
        campaign, work, iteration=1, auto_approve=True, sdk_runner=_sdk,
    )
    assert outcome is IterationOutcome.CONTINUE
    assert sentinel.exists(), "test_command must run on a build iteration"
    assert seen_at_build_time == [True], "test_command must run BEFORE the build call"
    pre = json.loads((work / "pre_build_tests.json").read_text())
    # A command that exits 0 reporting nothing per-test yields NO passes, which
    # is the whole point: a shell-level green must not read as "already passing".
    assert pre["passed"] == [] and pre["ran"] == []


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


def test_build_prompt_carries_optimization_guidance(tmp_path: Path):
    """`optimization.guidance` must reach the stage that writes the mechanism.

    Observed for real, and it confounded a two-arm field test: a campaign author
    put the target's known failure mode ("naively skipping this call CRASHES with
    IndexError because the shared buffer's claim goes unmade") into
    `optimization.guidance.factor_nomination`, reasonably assuming a field named
    *guidance* reaches the agent being guided. It did not — `build_prompt` read
    only `research_question` and `target_system.description`, so the warning
    reached nobody and the build shipped the exact defect the author had already
    diagnosed. The reflective arm of the same comparison got the same facts via
    its `research_question` (which IS its prompt) and avoided the defect, making
    a 10x optimality gap partly an artifact of which field the author chose.
    """
    campaign = _campaign(tmp_path)
    campaign["optimization"]["guidance"] = {
        "factor_nomination": "Preserve the claim protocol; a naive skip raises IndexError.",
        "interpretation": "Report a monotonicity break as the finding, not a defect.",
    }
    prompt = build_prompt(campaign, [])
    assert "claim protocol" in prompt
    assert "IndexError" in prompt
    # `interpretation` steers how RESULTS are read, which is not this stage's job:
    # build writes code and makes no correctness judgement, so feeding it the
    # interpretation rules would invite it to pre-judge its own measurement.
    assert "monotonicity break" not in prompt


def test_build_prompt_demands_the_mechanism_be_cheap(tmp_path: Path):
    """A time-objective campaign must tell the build that time is the point.

    Observed for real: every REQUIREMENT in this prompt was about correctness, and
    BUDGET DISCIPLINE told the agent that probing "buys no measurement" — so a
    build authored a mechanism that removed 70% of the per-item work and ran 23.7%
    SLOWER, because its per-frame decision was O(n) over the same n it was trying
    to skip. Correct, well-tested, and a regression. The prompt has to say that the
    cost of deciding must be cheaper than the work avoided.
    """
    prompt = build_prompt(_campaign(tmp_path), [])
    low = prompt.lower()
    assert "cost of deciding" in low
    assert "asymptotic" in low
    # And the objective's own direction must be visible, so "fast" is not abstract.
    assert "goodput" in low and "maximize" in low


def _decl(*names):
    class _F:
        def __init__(self, rels):
            self.relations = rels
    return [_F([{"native_test": n} for n in names])]


def test_parametrized_tests_match_their_bare_declaration():
    """pytest reports `test_x[case]`; a declaration naming `test_x` must match.

    Observed for real and it aborted a completed build: a campaign's 68 tests
    all passed, but only 2 of 6 declared identifiers matched because the other
    four were parametrized. Those four reconciled as "declared but not executed"
    and the fail-closed path killed a build that had done everything asked.
    """
    from orchestrator.optimize.runner import match_declared_tests

    decl = _decl("py/tests/t.py::test_no_rebalancing")
    res = {
        "test_no_rebalancing[0.95-1.05]": True,
        "test_no_rebalancing[0.8-2.0]": True,
    }
    assert match_declared_tests(decl, res) == {
        "py/tests/t.py::test_no_rebalancing": True,
    }


def test_one_failing_parametrization_fails_the_relation():
    """Aggregation must be all(), not last-seen — fail-closed is the point."""
    from orchestrator.optimize.runner import match_declared_tests

    decl = _decl("py/tests/t.py::test_inv")
    res = {"test_inv[a]": True, "test_inv[b]": False, "test_inv[c]": True}
    assert match_declared_tests(decl, res)["py/tests/t.py::test_inv"] is False


def test_go_subtests_aggregate_the_same_way():
    """Go reports subtests as TestX/case; the same rule applies."""
    from orchestrator.optimize.runner import match_declared_tests

    decl = _decl("sim/x_test.go::TestCeiling")
    assert match_declared_tests(
        decl, {"TestCeiling/linear": True, "TestCeiling/step": True},
    )["sim/x_test.go::TestCeiling"] is True
    assert match_declared_tests(
        decl, {"TestCeiling/linear": True, "TestCeiling/step": False},
    )["sim/x_test.go::TestCeiling"] is False


def test_plain_test_names_still_match_exactly():
    """No regression for the non-parametrized case."""
    from orchestrator.optimize.runner import match_declared_tests

    decl = _decl("py/tests/t.py::test_plain")
    assert match_declared_tests(decl, {"test_plain": True}) == {
        "py/tests/t.py::test_plain": True,
    }


def test_absent_test_still_fails_closed():
    """A declaration with no matching result must stay absent, not default True."""
    from orchestrator.optimize.runner import match_declared_tests

    decl = _decl("py/tests/t.py::test_never_written")
    assert match_declared_tests(decl, {"test_something_else": True}) == {}


# ─── refine must not drop non-designed factors ────────────────────────────

def test_refine_holds_non_designed_factors_fixed(tmp_path, monkeypatch):
    """A `choice` factor must still reach the target during `refine`.

    refine builds a central composite over REFINABLE (numeric, >2 level)
    factors only. A factor outside that design contributed no level and so no
    `apply` fragment, and its CLI flag vanished from the command line. A target
    that (correctly) requires all of its flags then fails every run on a usage
    error. Observed for real: 48 of 48 refine and confirm runs died with
    "the following arguments are required: --enable-a, --enable-b".
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "c"))

    def _num(fid, name, levels):
        return {
            "id": fid, "name": name, "type": "numeric", "levels": levels,
            "grid": 0.1, "apply": f"--{name}={{level}}",
            "manipulation": {
                "observable": f"applied.{name}", "op": "==", "value": "{level}",
            },
            "relations": [{
                "id": f"R_{fid}", "kind": "correctness", "statement": "s",
                "native_test": "t.py::test_ok",
            }],
        }

    campaign = {
        "kind": "optimization", "run_id": "refdrop",
        "research_question": "q",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "optimization": {
            "response": {"primary": {"metric": "m", "direction": "maximize"}},
            "factors": [
                {
                    "id": "FLAG", "name": "flag", "type": "choice",
                    "levels": ["off", "on"], "apply": "--flag={level}",
                    "manipulation": {
                        "observable": "applied.flag", "op": "==",
                        "value": "{level}",
                    },
                    "relations": [{
                        "id": "R_FLAG", "kind": "correctness", "statement": "s",
                        "native_test": "t.py::test_ok",
                    }],
                },
                _num("A", "aaa", [1.0, 2.0, 3.0]),
                _num("B", "bbb", [1.0, 2.0, 3.0]),
            ],
            "stages": ["verify", "screen", "refine", "confirm"],
            "design": {
                "screen": {"resolution": 3},
                "refine": {"kind": "central_composite", "center_points": 1},
                "confirm": {"replicates": 1},
            },
        },
    }
    wd = setup_work_dir("refdrop", repo_path=str(repo), campaign=campaign)

    seen: list[dict] = []

    names = {"FLAG": "flag", "A": "aaa", "B": "bbb"}

    def runner(row):
        seen.append(dict(row.levels))
        return {
            "applied": {names[k]: v for k, v in row.levels.items()},
            "m": 1.0 + float(row.levels.get("A", 0)),
        }

    run_stage(
        campaign, wd, iteration=3, stage="refine", config_runner=runner,
        test_results={"t.py::test_ok": True}, auto_approve=True,
    )
    assert seen, "refine executed no rows"
    for lv in seen:
        assert "FLAG" in lv, (
            f"the non-designed choice factor was dropped from the row: {lv}. "
            "Its CLI flag would be missing from every command line."
        )
        assert lv["FLAG"] == "off", "held-fixed value must be the first level"


def test_held_fixed_is_recorded_in_the_design_matrix(tmp_path, monkeypatch):
    """The held-fixed value must be auditable, not implicit."""
    import json as _json

    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "c"))
    campaign = {
        "kind": "optimization", "run_id": "heldfix",
        "research_question": "q",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "optimization": {
            "response": {"primary": {"metric": "m", "direction": "maximize"}},
            "factors": [
                {
                    "id": "FLAG", "name": "flag", "type": "choice",
                    "levels": ["off", "on"], "apply": "--flag={level}",
                    "manipulation": {
                        "observable": "applied.flag", "op": "==",
                        "value": "{level}",
                    },
                    "relations": [{
                        "id": "R1", "kind": "correctness", "statement": "s",
                        "native_test": "t.py::test_ok",
                    }],
                },
                {
                    "id": "A", "name": "aaa", "type": "numeric",
                    "levels": [1.0, 2.0, 3.0], "grid": 0.1,
                    "apply": "--aaa={level}",
                    "manipulation": {
                        "observable": "applied.aaa", "op": "==",
                        "value": "{level}",
                    },
                    "relations": [{
                        "id": "R2", "kind": "correctness", "statement": "s",
                        "native_test": "t.py::test_ok",
                    }],
                },
                {
                    "id": "B", "name": "bbb", "type": "numeric",
                    "levels": [1.0, 2.0, 3.0], "grid": 0.1,
                    "apply": "--bbb={level}",
                    "manipulation": {
                        "observable": "applied.bbb", "op": "==",
                        "value": "{level}",
                    },
                    "relations": [{
                        "id": "R3", "kind": "correctness", "statement": "s",
                        "native_test": "t.py::test_ok",
                    }],
                },
            ],
            "stages": ["verify", "screen", "refine", "confirm"],
            "design": {
                "screen": {"resolution": 3},
                "refine": {"kind": "central_composite", "center_points": 1},
                "confirm": {"replicates": 1},
            },
        },
    }
    wd = setup_work_dir("heldfix", repo_path=str(repo), campaign=campaign)
    run_stage(
        campaign, wd, iteration=3, stage="refine",
        config_runner=lambda row: {
            "applied": {
                {"FLAG": "flag", "A": "aaa", "B": "bbb"}[k]: v
                for k, v in row.levels.items()
            },
            "m": 1.0,
        },
        test_results={"t.py::test_ok": True}, auto_approve=True,
    )
    dm = _json.loads(
        (Path(wd) / "runs" / "iter-3" / "design_matrix.json").read_text(),
    )
    assert dm.get("held_fixed") == {"FLAG": "off"}


# ─── validate --smoke: execute the contract, not just its shape ────────────

def _smoke_campaign(repo: Path, *, predicate: dict, run_cmd: str,
                    test_cmd: str = "echo --- PASS: test_present") -> dict:
    return {
        "kind": "optimization", "run_id": "smk",
        "research_question": "q",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "optimization": {
            "response": {"primary": {"metric": "m", "direction": "maximize"}},
            "factors": [{
                "id": "F", "name": "flag", "type": "choice",
                "levels": ["0", "1"], "apply": "--flag={level}",
                "manipulation": predicate,
                "relations": [{
                    "id": "R1", "kind": "correctness", "statement": "s",
                    "native_test": "t.py::test_present",
                }],
            }],
            "stages": ["verify", "screen", "confirm"],
            "design": {"screen": {"resolution": 3}, "confirm": {"replicates": 1}},
            "run_command": run_cmd,
            "test_command": test_cmd,
        },
    }


def test_smoke_catches_a_predicate_type_mismatch(tmp_path: Path):
    """The failure that rejected 67 of 67 runs while the target was correct.

    A level is a string; a target echoing a bool for the same knob can never
    compare equal. Static validation cannot see this — the predicate is
    well-formed and the target is right. Only running one configuration and
    reading the target's OWN echo exposes it.
    """
    from orchestrator.cli import _smoke_check_optimization

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _smoke_campaign(
        repo,
        predicate={"observable": "applied.flag", "op": "==", "value": "{level}"},
        # target echoes a BOOLEAN for `flag`, not the string level
        run_cmd="""python3 -c 'print({"applied":{"flag":False},"m":1.0})'""",
    )
    # the CLI prints python-repr above; use JSON so the runner can parse it
    campaign["optimization"]["run_command"] = (
        """python3 -c 'import json;print(json.dumps({"applied":{"flag":False},"m":1.0}))'"""
    )
    issues = _smoke_check_optimization(campaign)
    assert any("manipulation predicate fails" in i for i in issues), issues
    assert any("TYPE" in i for i in issues), "must name the type mismatch"


def test_smoke_catches_a_missing_objective_metric(tmp_path: Path):
    """A metric the target never emits makes every run score NaN."""
    from orchestrator.cli import _smoke_check_optimization

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _smoke_campaign(
        repo,
        predicate={"observable": "applied.flag", "op": "==", "value": "{level}"},
        run_cmd=(
            """python3 -c 'import json;print(json.dumps("""
            """{"applied":{"flag":"0"},"other":1.0}))'"""
        ),
    )
    issues = _smoke_check_optimization(campaign)
    assert any("absent from the run" in i for i in issues), issues


def test_smoke_catches_a_run_command_that_cannot_exec(tmp_path: Path):
    """An inline VAR=value prefix is parsed by shlex as the binary name."""
    from orchestrator.cli import _smoke_check_optimization

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _smoke_campaign(
        repo,
        predicate={"observable": "applied.flag", "op": "==", "value": "{level}"},
        run_cmd="PYTHONPATH=x python3 -c 'pass'",
    )
    issues = _smoke_check_optimization(campaign)
    assert any("run_command failed" in i for i in issues), issues


def test_smoke_passes_a_sound_contract(tmp_path: Path):
    """No false positives when the campaign and target actually agree."""
    from orchestrator.cli import _smoke_check_optimization

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _smoke_campaign(
        repo,
        predicate={"observable": "applied.flag", "op": "==", "value": "{level}"},
        run_cmd=(
            """python3 -c 'import json;print(json.dumps("""
            """{"applied":{"flag":"0"},"m":1.0}))'"""
        ),
    )
    assert _smoke_check_optimization(campaign) == []


def test_smoke_reports_an_unmatched_native_test(tmp_path: Path):
    """A declared test the runner never reports fails closed at verify."""
    from orchestrator.cli import _smoke_check_optimization

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _smoke_campaign(
        repo,
        predicate={"observable": "applied.flag", "op": "==", "value": "{level}"},
        run_cmd=(
            """python3 -c 'import json;print(json.dumps("""
            """{"applied":{"flag":"0"},"m":1.0}))'"""
        ),
        test_cmd="python3 -c \"print('--- PASS: test_something_else')\"",
    )
    issues = _smoke_check_optimization(campaign)
    assert any("did not appear in the test command" in i for i in issues), issues


# ── Task 14.5: a mechanism_paths entry that resolves to nothing ───────────────
#
# The drift oracle is only as narrow as the allowlist is accurate. A typo'd
# entry is not a loud failure — it silently contributes nothing, so the oracle
# watches less than the campaign says it does, and (with every entry typo'd)
# `_mechanism_text` filters the tree down to nothing and no edit ever reads as
# drift. Static validation cannot see this: the string is well-formed, and only
# the target tree knows whether it exists.


def _smoke_repo_with_git(tmp_path: Path) -> Path:
    """A real git work tree — the smoke check resolves paths against the target.

    Real git rather than a bare directory: the runtime allowlist is applied both
    to `git diff HEAD -- <paths>` and to git's untracked listing, so a check
    validated only against a plain filesystem could disagree with the thing it
    is meant to pre-flight.
    """
    import subprocess
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "mech.py").write_text("X = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _sound_run_cmd() -> str:
    return (
        """python3 -c 'import json;print(json.dumps("""
        """{"applied":{"flag":"0"},"m":1.0}))'"""
    )


def _smoke_with_mechanism_paths(repo: Path, paths: list[str]) -> dict:
    campaign = _smoke_campaign(
        repo,
        predicate={"observable": "applied.flag", "op": "==", "value": "{level}"},
        run_cmd=_sound_run_cmd(),
    )
    campaign["optimization"]["build_checks"] = {"mechanism_paths": paths}
    return campaign


def test_smoke_reports_a_mechanism_path_that_does_not_exist(tmp_path: Path):
    """A typo'd entry silently narrows the drift oracle to nothing."""
    from orchestrator.cli import _smoke_check_optimization

    repo = _smoke_repo_with_git(tmp_path)
    # `src/mech.py` exists; the second entry is the typo. Note the assertion
    # below deliberately checks the count and the entry LIST, not merely
    # "src/mech.py is absent from the text" — the message's own remedy sentence
    # quotes 'src/mech.py' as an example of a well-formed entry, so a naive
    # substring check would fail for the wrong reason.
    campaign = _smoke_with_mechanism_paths(repo, ["src/mech.py", "src/typo.py"])
    issues = _smoke_check_optimization(campaign)
    hits = [i for i in issues if "mechanism_paths" in i]
    assert len(hits) == 1, issues
    assert "1 build_checks.mechanism_paths" in hits[0], (
        "exactly one entry is broken", hits,
    )
    assert "src/typo.py" in hits[0], ("must name the offending entry", hits)


def test_smoke_accepts_mechanism_paths_that_resolve(tmp_path: Path):
    """No false positives: a file and a directory prefix both resolve.

    A check that flagged everything would pass the test above while making the
    field unreportable — the one-sided oracle worth guarding against here.
    """
    from orchestrator.cli import _smoke_check_optimization

    repo = _smoke_repo_with_git(tmp_path)
    campaign = _smoke_with_mechanism_paths(repo, ["src/mech.py", "src/", "src"])
    assert _smoke_check_optimization(campaign) == []


def test_smoke_accepts_a_mechanism_path_that_is_not_yet_authored_under_build(
    tmp_path: Path,
):
    """With a `build` stage the mechanism's file legitimately does not exist yet.

    `build` is the stage that AUTHORS it, so pre-flighting its existence would
    make the smoke check reject exactly the campaigns it should help most.
    """
    from orchestrator.cli import _smoke_check_optimization

    repo = _smoke_repo_with_git(tmp_path)
    campaign = _smoke_with_mechanism_paths(repo, ["src/not_yet.py"])
    campaign["optimization"]["stages"] = [
        "build", "verify", "screen", "confirm",
    ]
    assert not any("mechanism_paths" in i
                   for i in _smoke_check_optimization(campaign))
