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
