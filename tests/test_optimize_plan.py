"""Behavioral tests for the ``plan`` stage (mechanism design before authoring).

No live LLM calls: every test injects ``sdk_runner=`` at the seam
:mod:`orchestrator.optimize.plan` exposes, mirroring ``SDKDispatcher``.
Assertions are about what lands on disk, what reaches the next stage, and what
the stage refuses — never about which method a mock saw.

Why this stage exists, measured rather than assumed. On one target, three builds
of the same mechanism against the same objective:

    build with no cost facts   : removed 70% of the per-item work, ran 23.7% SLOWER
    build with the cost facts  : +3.65%, certified
    reflective (design first)  : -10.4%, and it named the winning architecture in
                                 its DESIGN artifact BEFORE writing any code

The reflective arm's bundle was 29.4K chars of which 87% was experiment design
(hypothesis arms, locked parameters, run plans) that ``kind: optimization``
already has pre-registered and content-hashed — a strictly stronger guarantee.
The part that actually produced the winning architecture was the mechanism
reasoning: where the cost sits, which approach was chosen, what was rejected and
why, and which invariants a naive version breaks. THAT is what this stage
captures, and nothing else, which is why it is one call and a small artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.optimize import plan as plan_mod
from orchestrator.optimize.plan import (
    PLAN_FILENAME,
    check_plan,
    plan_prompt,
    read_plan,
    run_plan,
)
from orchestrator.sdk_dispatch import SDKResult


def _campaign(repo: Path, *, stages=None, constraints=None) -> dict:
    opt = {
        "response": {
            "primary": {"metric": "render_seconds", "direction": "minimize"},
        },
        "factors": [
            {
                "id": "DT",
                "name": "dirty_tracking",
                "type": "choice",
                "levels": [False, True],
                "apply": "--dirty-tracking={level}",
                "manipulation": {
                    "observable": "config.dirty_tracking", "op": "==",
                    "value": "{level}",
                },
                "relations": [
                    {
                        "id": "R1", "kind": "correctness",
                        "statement": "tracking on renders the same pixels",
                        "native_test": "tests/t.py::test_invisible",
                    },
                ],
            },
        ],
        "design": {"screen": {"resolution": 5, "center_points": 0},
                   "confirm": {"replicates": 6}},
        "stages": stages or ["plan", "build", "verify", "screen", "confirm"],
        "run_command": "python -P adapter/run.py",
        "test_command": "python -m pytest tests/ -v",
        "known_valid_baseline": {"DT": False},
        "guidance": {
            "factor_nomination": "Preserve the claim protocol; a naive skip raises IndexError.",
            "interpretation": "Report a monotonicity break as the finding.",
        },
    }
    if constraints:
        opt["response"]["constraints"] = constraints
    return {
        "kind": "optimization",
        "run_id": "plan-test",
        "research_question": "Which dirty-tracking setting minimizes render time?",
        "target_system": {
            "name": "manim",
            "repo_path": str(repo),
            "description": "Renderer walks every mobject every frame.",
        },
        "locked_parameters": {"fps": 30},
        "sandbox": "bypass",
        "optimization": opt,
    }


def _valid_plan() -> dict:
    return {
        "cost_model": {
            "summary": "28,800 write_uniforms calls/render, 26.2% report a change; "
                       "57,600 SharedBuffer.claim calls. Cost is diffuse: renderer "
                       "26%, interpreter 22%, FFI 15% of self time.",
            "currency": "render_seconds",
            "measured": True,
        },
        "approach": {
            "summary": "Push invalidation to the source: an epoch counter bumped by "
                       "the few mutators, read O(1) per frame; replay buffer claims "
                       "in one step instead of per drawing.",
            "cost_of_deciding": "O(1) per frame (one counter read)",
            "cost_avoided": "O(N) per frame over N drawings, plus N claim calls",
            "files": ["manimlib/renderer/renderer.py", "manimlib/renderer/shared_buffer.py"],
        },
        "rejected": [
            {
                "approach": "Recompute a state tuple over every family member each frame "
                            "and compare it to last frame's.",
                "why": "The check is O(N) over the same N it would skip, so it cannot "
                       "pay for itself — measured 23.7% SLOWER on this target.",
            },
        ],
        "failure_modes": [
            {
                "symptom": "IndexError: list index out of range in compare_uniforms",
                "cause": "Skipping write_uniforms leaves the shared buffer's per-frame "
                         "claim unmade, so group() indexes claims that were never made.",
                "guard": "Replay the claim sequence in bulk; assert used/offsets are "
                         "bit-identical to a full frame.",
            },
        ],
    }


def _runner(result: SDKResult):
    def _r(**_kw):
        return result
    return _r


def _plan_result(payload: dict | str, **kw) -> SDKResult:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SDKResult(text=text, input_tokens=kw.pop("input_tokens", 100),
                     output_tokens=kw.pop("output_tokens", 200), **kw)


# --------------------------------------------------------------------------
# CONTRACT: what the stage promises the NEXT stage
# --------------------------------------------------------------------------

def test_plan_writes_the_artifact_build_reads(tmp_path: Path):
    """The stage's whole output contract: a plan on disk that `build` can read."""
    work = tmp_path / "wd"
    work.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_plan(_campaign(repo), work, iteration=1,
             sdk_runner=_runner(_plan_result(_valid_plan())))
    assert (work / PLAN_FILENAME).exists()
    got = read_plan(work)
    assert got["approach"]["cost_of_deciding"] == "O(1) per frame (one counter read)"
    assert got["rejected"][0]["why"].startswith("The check is O(N)")


def test_plan_reaches_the_build_prompt_as_a_specification(tmp_path: Path):
    """A plan on disk must appear in the build's prompt, or the stage bought nothing.

    This is the contract that makes `plan` worth a call: `build` is the consumer.
    """
    from orchestrator.optimize.build import build_prompt

    work = tmp_path / "wd"
    work.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _campaign(repo)
    run_plan(campaign, work, iteration=1,
             sdk_runner=_runner(_plan_result(_valid_plan())))
    prompt = build_prompt(campaign, [], work_dir=work)
    assert "MECHANISM PLAN" in prompt
    # the load-bearing content, not just the header
    assert "epoch counter" in prompt
    assert "cannot pay for itself" in prompt          # the rejected alternative
    assert "IndexError" in prompt                     # the failure mode


def test_build_prompt_is_unchanged_when_no_plan_exists(tmp_path: Path):
    """`plan` is opt-in: a campaign without it must render exactly as before."""
    from orchestrator.optimize.build import build_prompt

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign = _campaign(repo, stages=["build", "verify", "screen", "confirm"])
    with_dir = build_prompt(campaign, [], work_dir=tmp_path / "empty")
    without = build_prompt(campaign, [])
    assert "MECHANISM PLAN" not in with_dir
    assert with_dir == without


# --------------------------------------------------------------------------
# PROPERTY: holds across a swept input space, not at one hand-picked point
# --------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["cost_model", "approach", "rejected", "failure_modes"])
def test_every_required_section_is_required(missing: str):
    """Property: dropping ANY required section must be rejected, not just one.

    A checker that happens to test the first field is indistinguishable from one
    that tests all four until you sweep them.
    """
    p = _valid_plan()
    del p[missing]
    errors = check_plan(p)
    assert errors, f"check_plan accepted a plan with no {missing!r}"
    assert any(missing in e for e in errors), (
        f"errors do not name the missing section: {errors}"
    )


@pytest.mark.parametrize("empty", [[], {}, "", None])
def test_no_section_may_be_present_but_vacuous(empty):
    """Property: an empty section is as useless as an absent one, and is caught.

    The failure this prevents is a plan that satisfies a key-presence check while
    saying nothing — which reads as a completed plan in every artifact listing.
    """
    p = _valid_plan()
    p["rejected"] = empty
    assert check_plan(p), f"check_plan accepted rejected={empty!r}"


@pytest.mark.parametrize("n_rejected", [1, 2, 5])
def test_any_number_of_rejected_alternatives_at_least_one(n_rejected: int):
    """Property: one rejected alternative is the floor; more is always fine."""
    p = _valid_plan()
    p["rejected"] = [
        {"approach": f"alternative strategy number {i}",
         "why": f"its decision path is O(N) in the same N, costing more than "
                f"the work it avoids (variant {i})"}
        for i in range(n_rejected)
    ]
    assert check_plan(p) == []


# --------------------------------------------------------------------------
# METAMORPHIC: a transformation of the input must move the output a known way
# --------------------------------------------------------------------------

def test_more_detail_never_turns_a_valid_plan_invalid():
    """Metamorphic: adding fields is monotone — a valid plan stays valid.

    Direction checked by hand first: `check_plan` rejects what is MISSING or
    VACUOUS, so adding content can only remove reasons to reject. If extra keys
    ever caused rejection, a plan could be made invalid by explaining itself
    better, which is the opposite of the intent.
    """
    base = _valid_plan()
    assert check_plan(base) == []
    richer = json.loads(json.dumps(base))
    richer["approach"]["alternatives_benchmarked"] = 2
    richer["cost_model"]["profile"] = {"renderer": 0.26, "interpreter": 0.22}
    richer["notes"] = "extra prose"
    assert check_plan(richer) == [], "extra detail must not invalidate a plan"


def test_truncating_any_rationale_makes_the_plan_worse_not_better():
    """Metamorphic: shortening a `why` toward emptiness must not gain acceptance.

    Worked through concretely: 'The check is O(N)...' (valid) -> 'no' (too short
    to be a reason) -> '' (vacuous). Acceptance must be monotone non-increasing
    along that sequence, never the reverse.
    """
    verdicts = []
    for why in ("The check is O(N) over the same N it would skip.", "no", ""):
        p = _valid_plan()
        p["rejected"] = [{"approach": "state tuple per frame", "why": why}]
        verdicts.append(check_plan(p) == [])
    assert verdicts[0] is True, "the full rationale must be accepted"
    assert verdicts[2] is False, "an empty rationale must be rejected"
    # monotone: once rejected, a shorter string may not become accepted again
    assert not (verdicts[1] is False and verdicts[2] is True)


# --------------------------------------------------------------------------
# MUTATION-RESISTANT: each asserts a distinct behaviour, so deleting any one
# line of the checker fails a specific test rather than none.
# --------------------------------------------------------------------------

def test_a_plan_that_names_no_cost_currency_is_rejected():
    """Killing the currency check must fail THIS test and no other."""
    p = _valid_plan()
    del p["cost_model"]["currency"]
    errors = check_plan(p)
    assert any("currency" in e for e in errors), errors


def test_a_plan_whose_deciding_cost_is_not_stated_is_rejected():
    """O1/O2 exist to force this comparison; a plan may not skip it."""
    p = _valid_plan()
    del p["approach"]["cost_of_deciding"]
    errors = check_plan(p)
    assert any("cost_of_deciding" in e for e in errors), errors


def test_a_plan_whose_avoided_cost_is_not_stated_is_rejected():
    """The other half of the comparison — separately checked, separately killable."""
    p = _valid_plan()
    del p["approach"]["cost_avoided"]
    errors = check_plan(p)
    assert any("cost_avoided" in e for e in errors), errors


def test_a_failure_mode_without_a_guard_is_rejected():
    """Naming a crash mode and not guarding it is how the first build shipped it."""
    p = _valid_plan()
    del p["failure_modes"][0]["guard"]
    errors = check_plan(p)
    assert any("guard" in e for e in errors), errors


# --------------------------------------------------------------------------
# BEHAVIOUR under a hostile model response
# --------------------------------------------------------------------------

def test_non_json_response_fails_loudly_and_writes_no_plan(tmp_path: Path):
    """A build must never proceed on a plan that was never parsed.

    Fail-closed: no artifact, and the error names what was wrong.
    """
    work = tmp_path / "wd"
    work.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(plan_mod.PlanRejected) as exc:
        run_plan(_campaign(repo), work, iteration=1,
                 sdk_runner=_runner(_plan_result("I thought about it. Looks fine!")))
    assert not (work / PLAN_FILENAME).exists()
    assert "json" in str(exc.value).lower()


def test_json_wrapped_in_prose_or_fences_is_still_read(tmp_path: Path):
    """Models fence their JSON; that is a formatting habit, not a refusal."""
    work = tmp_path / "wd"
    work.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    body = json.dumps(_valid_plan())
    run_plan(_campaign(repo), work, iteration=1,
             sdk_runner=_runner(_plan_result(
                 f"Here is the plan.\n```json\n{body}\n```\nDone.")))
    assert read_plan(work)["cost_model"]["currency"] == "render_seconds"


def test_a_structurally_invalid_plan_is_rejected_not_written(tmp_path: Path):
    """The checker gates the artifact, so `build` cannot read a vacuous plan."""
    work = tmp_path / "wd"
    work.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    bad = _valid_plan()
    bad["rejected"] = []
    with pytest.raises(plan_mod.PlanRejected):
        run_plan(_campaign(repo), work, iteration=1,
                 sdk_runner=_runner(_plan_result(bad)))
    assert not (work / PLAN_FILENAME).exists()


def test_plan_logs_its_cost_to_llm_metrics(tmp_path: Path):
    """The stage is a substantive call; the cost axis must see it."""
    work = tmp_path / "wd"
    work.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_plan(_campaign(repo), work, iteration=1,
             sdk_runner=_runner(_plan_result(_valid_plan(),
                                             input_tokens=11, output_tokens=22)))
    rows = [json.loads(l) for l in (work / "llm_metrics.jsonl").read_text().splitlines()]
    assert [r["phase"] for r in rows] == ["plan"]
    assert rows[0]["output_tokens"] == 22


# --------------------------------------------------------------------------
# The PROMPT: what the planning call is told
# --------------------------------------------------------------------------

def test_plan_prompt_forbids_writing_code(tmp_path: Path):
    """`plan` reasons and reports; `build` writes. Conflating them wastes a call."""
    low = " ".join(plan_prompt(_campaign(tmp_path)).lower().split())
    assert "do not write" in low or "write no code" in low
    assert "json" in low


def test_plan_prompt_carries_the_objective_and_its_constraints(tmp_path: Path):
    """A plan cannot state cost "in the objective's currency" without the objective."""
    campaign = _campaign(tmp_path, constraints=[
        {"metric": "peak_rss_mb", "op": "<=", "value": 512},
    ])
    prompt = plan_prompt(campaign)
    assert "render_seconds" in prompt and "minimize" in prompt
    assert "peak_rss_mb" in prompt


def test_plan_prompt_carries_author_guidance_but_not_interpretation(tmp_path: Path):
    """Same split as `build`: mechanism steering in, result-reading steering out."""
    prompt = plan_prompt(_campaign(tmp_path))
    assert "claim protocol" in prompt
    assert "monotonicity break" not in prompt


def test_plan_prompt_requires_a_rejected_alternative(tmp_path: Path):
    """The `rejected` field is the point: it forces a cost comparison up front."""
    low = " ".join(plan_prompt(_campaign(tmp_path)).lower().split())
    assert "reject" in low
    assert "at least one" in low


# --------------------------------------------------------------------------
# STAGE WIRING: the vocabulary and the ordering rule
# --------------------------------------------------------------------------

def test_plan_is_a_stage_and_maps_to_iteration_one():
    """`plan` must be a first-class stage, resolvable by index like the others."""
    from orchestrator.optimize.stage import Stage, stage_for_iteration

    assert Stage.PLAN.value == "plan"
    campaign = {"optimization": {"stages": [
        "plan", "build", "verify", "screen", "confirm",
    ]}}
    assert stage_for_iteration(campaign, 1) is Stage.PLAN
    assert stage_for_iteration(campaign, 2) is Stage.BUILD


@pytest.mark.parametrize("stages,ok", [
    (["plan", "build", "verify", "screen", "confirm"], True),
    (["build", "verify", "screen", "confirm"], True),          # plan is opt-in
    (["verify", "screen", "confirm"], True),                   # neither declared
    (["plan", "verify", "screen", "confirm"], False),          # plan without build
    (["build", "plan", "verify", "screen", "confirm"], False), # wrong order
    (["verify", "plan", "build", "screen"], False),            # not first
    (["plan", "plan", "build", "verify"], False),              # twice
])
def test_plan_ordering_rule(stages, ok):
    """Property: `plan` is legal only as position 1 immediately before `build`.

    A plan AFTER the build specifies code that already exists — the artifact
    would describe a mechanism the campaign had already committed to, which reads
    as a pre-registration but is a post-hoc rationalisation. A plan with no build
    is a design nothing implements. Both are schema-valid, which is exactly the
    class worth rejecting up front.
    """
    from orchestrator.validate import validate_optimization_campaign

    campaign = {
        "kind": "optimization",
        "run_id": "r",
        "research_question": "q",
        "target_system": {"name": "t", "repo_path": "/tmp", "description": "d"},
        "prompts": {"methodology_layer": "prompts/methodology"},
        "optimization": {
            "run_command": "python run.py",
            "test_command": "pytest -v",
            "known_valid_baseline": {"DT": False},
            "response": {"primary": {"metric": "m", "direction": "minimize"}},
            "factors": [{
                "id": "DT", "name": "dt", "type": "choice", "levels": [False, True],
                "apply": "--dt={level}",
                "manipulation": {"observable": "config.dt", "op": "==",
                                 "value": "{level}"},
                "relations": [{"id": "R1", "kind": "correctness",
                               "statement": "off reproduces baseline",
                               "native_test": "tests/t.py::test_off"}],
            }],
            "design": {"screen": {"resolution": 5, "center_points": 0},
                       "confirm": {"replicates": 4}},
            "stages": stages,
        },
    }
    errors = [e for e in validate_optimization_campaign(campaign)
              if "stages" in e and "plan" in e]
    if ok:
        assert errors == [], f"legal stage list rejected: {errors}"
    else:
        assert errors, f"illegal stage list {stages} accepted"


def test_run_stage_dispatches_plan_and_writes_the_artifact(tmp_path: Path, monkeypatch):
    """END-TO-END through the real `run_stage`: a plan iteration writes the plan.

    Behavioural: asserts what lands on disk after the real dispatcher ran, not
    that a mock was called. The SDK is replaced at plan's own injection seam.
    """
    from orchestrator.optimize import stage_runner

    from orchestrator.iteration import setup_work_dir

    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    campaign = _campaign(repo)
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "artifacts"))
    work = setup_work_dir("plan-dispatch", repo_path=str(repo), campaign=campaign)

    captured: dict = {}

    real_run_plan = plan_mod.run_plan

    def fake_run_plan(camp, wd, **kw):
        captured["called"] = True
        return real_run_plan(
            camp, wd, sdk_runner=_runner(_plan_result(_valid_plan())),
            **{k: v for k, v in kw.items() if k != "sdk_runner"})

    monkeypatch.setattr(plan_mod, "run_plan", fake_run_plan)

    outcome = stage_runner.run_stage(
        campaign, work, iteration=1, stage="plan", test_results={},
    )
    assert captured.get("called"), "run_stage did not dispatch the plan stage"
    assert (work / PLAN_FILENAME).exists()
    assert outcome is not None      # a pre-epoch stage never terminates the run


def test_plan_iteration_is_never_terminal(tmp_path: Path, monkeypatch):
    """The epoch has not begun, so a plan iteration cannot end the campaign."""
    from orchestrator.optimize import stage_runner
    from orchestrator.iteration import IterationOutcome

    from orchestrator.iteration import setup_work_dir

    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "artifacts2"))
    work = setup_work_dir("plan-terminal", repo_path=str(repo),
                          campaign=_campaign(repo))

    real_run_plan = plan_mod.run_plan
    monkeypatch.setattr(
        plan_mod, "run_plan",
        lambda camp, wd, **kw: real_run_plan(
            camp, wd, sdk_runner=_runner(_plan_result(_valid_plan())),
            **{k: v for k, v in kw.items() if k != "sdk_runner"}),
    )
    outcome = stage_runner.run_stage(
        _campaign(repo), work, iteration=1, stage="plan", test_results={},
    )
    assert outcome is IterationOutcome.CONTINUE


# --------------------------------------------------------------------------
# ACCOUNTABILITY: the plan is a PREDICTION, so screen can falsify it
# --------------------------------------------------------------------------

def test_plan_prediction_is_checked_against_the_measured_effect():
    """A plan that predicted a win against a screen that measured a loss must be FLAGGED.

    Without this the plan is write-only: `build` reads it, nothing ever compares
    it to reality, and the exact defect the stage exists to prevent — a mechanism
    whose decision path costs more than it saves — passes silently one stage later.
    The plan asserts `cost_avoided > cost_of_deciding`; the screen's main effect on
    the mechanism's own factor is the measurement of that claim.
    """
    from orchestrator.optimize.plan import check_plan_against_effect

    plan = _valid_plan()
    # Screen says enabling the mechanism made the objective WORSE (minimize).
    flags = check_plan_against_effect(
        plan, factor_id="DT", effect=+0.056, direction="minimize",
        noise_pct=2.4, baseline=0.234,
    )
    assert flags, "a contradicted plan must be flagged"
    joined = " ".join(flags)
    assert "cost_of_deciding" in joined or "overhead" in joined
    assert "DT" in joined


def test_a_plan_borne_out_by_the_measurement_is_not_flagged():
    """The other direction: a correct prediction must stay silent."""
    from orchestrator.optimize.plan import check_plan_against_effect

    flags = check_plan_against_effect(
        _valid_plan(), factor_id="DT", effect=-0.024, direction="minimize",
        noise_pct=2.4, baseline=0.234,
    )
    assert flags == [], f"a borne-out plan must not be flagged: {flags}"


@pytest.mark.parametrize("effect,direction,flagged", [
    (+0.056, "minimize", True),    # slower when minimising -> contradicted
    (-0.056, "minimize", False),   # faster when minimising -> borne out
    (-0.056, "maximize", True),    # smaller when maximising -> contradicted
    (+0.056, "maximize", False),   # bigger when maximising -> borne out
])
def test_direction_is_honoured_in_both_senses(effect, direction, flagged):
    """Property: the sign test must follow the objective's direction, not assume time.

    Reasoned before asserting: "the mechanism helped" means the objective moved
    the way `direction` says is better. A checker that hardcoded "lower is better"
    would silently invert on every maximise campaign — and most of the corpus
    maximises.
    """
    from orchestrator.optimize.plan import check_plan_against_effect

    flags = check_plan_against_effect(
        _valid_plan(), factor_id="DT", effect=effect, direction=direction,
        noise_pct=2.4, baseline=0.234,
    )
    assert bool(flags) is flagged


@pytest.mark.parametrize("effect", [0.0, 0.001, -0.002])
def test_an_effect_inside_the_noise_floor_is_not_a_contradiction(effect):
    """Property: below the noise floor the measurement cannot contradict anything.

    Claiming a plan was refuted by an effect smaller than run-to-run variation
    would manufacture findings — the same error as reading a 1% difference as real
    when the floor is 2.4%.
    """
    from orchestrator.optimize.plan import check_plan_against_effect

    assert check_plan_against_effect(
        _valid_plan(), factor_id="DT", effect=effect, direction="minimize",
        noise_pct=2.4, baseline=0.234,
    ) == []


def test_no_plan_means_nothing_to_check():
    """Opt-in stays opt-in: with no plan there is no prediction to falsify."""
    from orchestrator.optimize.plan import check_plan_against_effect

    assert check_plan_against_effect(
        {}, factor_id="DT", effect=+0.9, direction="minimize",
        noise_pct=2.4, baseline=0.234,
    ) == []


def test_effects_json_carries_the_plan_contradiction(tmp_path: Path):
    """CONTRACT with the artifact a reader actually opens.

    The flag has to land on `effects.json` — the file carrying the coefficient it
    qualifies — for the same reason `exclusion_balance` does: a caveat in a sibling
    file is a caveat the reader may never open, and `project_findings` derives its
    prose from this artifact.
    """
    from orchestrator.optimize.artifacts import write_effects
    from orchestrator.optimize.effects import Effect, Fit
    from orchestrator.optimize.factors import parse_factors

    work = tmp_path / "wd"
    (work / "runs" / "iter-3").mkdir(parents=True)
    (work / PLAN_FILENAME).write_text(json.dumps(_valid_plan()))

    factors = parse_factors(_campaign(tmp_path)["optimization"]["factors"])
    fit = Fit(
        intercept=0.234, n_runs=8, pure_error_var=None, pure_error_df=0,
        lack_of_fit_f=None, lack_of_fit_p=None,
        effects=(Effect(label="DT", terms=("DT",), estimate=+0.056),),
    )
    path = write_effects(
        work / "runs" / "iter-3", fit, factors=factors, stage="screen",
        work_dir=work, direction="minimize", noise_pct=2.4,
    )
    payload = json.loads(path.read_text())
    assert payload.get("plan_contradictions"), (
        "effects.json must carry the plan contradiction beside the coefficient"
    )
    assert "DT" in " ".join(payload["plan_contradictions"])


def test_effects_json_has_no_flag_when_the_plan_is_borne_out(tmp_path: Path):
    """The negative half: a correct plan must add no noise to the artifact."""
    from orchestrator.optimize.artifacts import write_effects
    from orchestrator.optimize.effects import Effect, Fit
    from orchestrator.optimize.factors import parse_factors

    work = tmp_path / "wd"
    (work / "runs" / "iter-3").mkdir(parents=True)
    (work / PLAN_FILENAME).write_text(json.dumps(_valid_plan()))

    factors = parse_factors(_campaign(tmp_path)["optimization"]["factors"])
    fit = Fit(
        intercept=0.234, n_runs=8, pure_error_var=None, pure_error_df=0,
        lack_of_fit_f=None, lack_of_fit_p=None,
        effects=(Effect(label="DT", terms=("DT",), estimate=-0.030),),
    )
    path = write_effects(
        work / "runs" / "iter-3", fit, factors=factors, stage="screen",
        work_dir=work, direction="minimize", noise_pct=2.4,
    )
    assert "plan_contradictions" not in json.loads(path.read_text())


def test_write_effects_is_unchanged_without_the_new_arguments(tmp_path: Path):
    """Backward compatible: every existing caller keeps working untouched."""
    from orchestrator.optimize.artifacts import write_effects
    from orchestrator.optimize.effects import Effect, Fit
    from orchestrator.optimize.factors import parse_factors

    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir()
    factors = parse_factors(_campaign(tmp_path)["optimization"]["factors"])
    fit = Fit(
        intercept=0.2, n_runs=4, pure_error_var=None, pure_error_df=0,
        lack_of_fit_f=None, lack_of_fit_p=None,
        effects=(Effect(label="DT", terms=("DT",), estimate=+0.9),),
    )
    payload = json.loads(
        write_effects(iter_dir, fit, factors=factors, stage="screen").read_text())
    assert "plan_contradictions" not in payload
