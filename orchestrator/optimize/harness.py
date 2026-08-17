"""Drive a whole optimization campaign against a synthetic surface.

Why this module exists
----------------------
Every test in this package so far checks an artifact, a mock, or a pure
function. None of them check the ANSWER: whether the campaign, driven end to
end through the real ``run_stage``, recommends the configuration that is
actually optimal. That is the only claim a reader of a campaign report cares
about, and it is the one claim nothing measured.

This harness closes that gap. Given a ``synthetic.Surface`` — a response
surface whose optimum is known in closed form — it runs the campaign's real
stage schedule with an in-process config runner and returns the
recommendation next to the truth, so a test can assert on the answer
(spec §3.5, oracle 1).

Zero LLM: ``build`` is never declared, so no stage in the schedule makes an
agent call; ``verify`` is handed ``test_results`` with every declared relation
passing, so nothing shells out to a test command; and the config runner is
``synthetic.make_synthetic_runner``, so nothing shells out to a benchmark
either. The whole campaign is arithmetic.

Reading the recommendation
--------------------------
The campaign's answer is ``report.json``'s ``recommendation.levels``, written
by the policy's terminal state. The reader below falls back to the last
iteration's ``runs/iter-N/confirmation.json`` (``confirmed_at_levels``) for a
campaign that aborted before reaching the terminal, so the same harness
measures the branch before and after that change and the tests written
against it do not move.

Not to be confused with ``runs/iter-N/recommendation.json``, which each
FITTING stage writes (``decide.recommend``'s argmax over the candidate
space). That is the per-stage answer confirm replicates and refine holds its
non-designed factors at; ``report.json`` is the campaign's. A test asserting
on the mechanism rather than the answer wants the per-stage artifact — see
``test_optimize_harness._read_recommendation``.

Likewise the ``path`` (which stages the campaign actually visited) is
reconstructed from which artifact each iteration wrote, until Task 6 records
``transitions.jsonl`` — at which point the recorded path wins, because a
recorded transition is evidence and an inferred one is a guess.

Driving multiple stages through one work_dir
--------------------------------------------
This is the first thing in the repo to do that, so it has to advance the
phase machine between iterations the way ``run_campaign`` does
(``HUMAN_FINDINGS_GATE -> DONE -> DESIGN``). That is not bookkeeping:
``iteration._enter_phase`` returns False once the engine is PAST the phase
being requested, and the DESIGN block it guards is what writes
``design_matrix.json`` and runs ``_preflight_design``. Skipping the advance
silently disabled both from iteration 2 onward — so the instrument diverged
from production in exactly the direction that hides pre-registration and
design-validation defects. Mirror production; do not invent a variant.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestrator.optimize.synthetic import Surface, make_synthetic_runner, true_optimum


@dataclass(frozen=True)
class SyntheticResult:
    """One campaign's answer, next to the truth it should have found.

    ``true_gap`` is signed so that a POSITIVE value always means "the
    recommendation is worse than the truth", whichever direction the
    campaign optimizes. It is ``inf`` when the campaign produced no
    recommendation at all, so a test that forgets to check
    ``recommendation`` still fails rather than dividing by a plausible
    number.
    """

    recommendation: dict
    basis: str
    residual_regret: float | None
    residual_regret_terminal: float | None
    true_optimum: dict
    true_best: float
    true_gap: float
    path: list[str]
    work_dir: Path
    report: dict


def synthetic_campaign(surface: Surface, **overrides) -> dict:
    """A valid ``kind: optimization`` campaign dict for ``surface``.

    ``overrides`` replace whole top-level keys of the ``optimization``
    block, which is what a test needs when it wants (say) a different
    ``response`` with constraints attached.

    HAZARD for later tasks — the default declares a ``refine`` stage, and
    ``_build_design`` aborts refine when no factor is refinable
    (``is_refinable`` requires a numeric factor with MORE THAN two levels).
    Two surfaces are built entirely from 2-level numerics — ``drift`` and
    ``interaction_only`` — so the default schedule aborts them at refine with
    "refine has nothing to refine" and the campaign returns an empty
    recommendation. That abort is CORRECT behaviour (the alternative,
    silently fitting quadratics over categorical/2-level factors, is the bug
    ``_build_design``'s comment records), so a test that needs either surface
    must skip the stage explicitly::

        run_synthetic_campaign(
            SURFACES["drift"](), seed=1, parent_dir=tmp_path,
            campaign_overrides={"stages": ["verify", "screen", "confirm"]},
        )
    """
    opt = {
        "response": {"primary": {"metric": "m", "direction": surface.direction}},
        "factors": [dict(f) for f in surface.factors],
        "design": {"screen": {"resolution": 5, "center_points": 4},
                   "refine": {"kind": "central_composite", "center_points": 4},
                   "confirm": {"replicates": 3}},
    }
    opt.update(overrides)
    return {
        "kind": "optimization",
        "run_id": f"synthetic-{surface.name}",
        "research_question": f"where is the optimum of {surface.name}?",
        "prompts": {"methodology_layer": "prompts/methodology", "domain_adapter_layer": None},
        "target_system": {"name": "synthetic", "description": f"synthetic surface {surface.name}"},
        "optimization": opt,
    }


def _all_pass(campaign: dict) -> dict[str, bool]:
    """Every declared ``native_test`` reported as passing.

    ``relations.reconcile`` treats a declared relation ABSENT from the
    results as a failure, so an incomplete dict here would abort every
    campaign at ``verify`` for a reason that has nothing to do with the
    surface under test.
    """
    return {r["native_test"]: True
            for f in campaign["optimization"]["factors"] for r in f["relations"]}


def _read_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def _latest_iter_dirs(work_dir: Path) -> list[Path]:
    """Iteration directories in NUMERIC order.

    Lexicographic order puts ``iter-10`` before ``iter-2``, which would make
    the recommendation reader pick a stale confirmation on any campaign that
    reaches double digits.
    """
    runs = work_dir / "runs"
    if not runs.exists():
        return []
    dirs = [d for d in runs.iterdir() if d.name.startswith("iter-")]
    return sorted(dirs, key=lambda d: int(d.name.split("-")[1]))


def run_synthetic_campaign(surface: Surface, *, seed: int, parent_dir: Path,
                           campaign_overrides: dict | None = None,
                           max_iterations: int = 8) -> SyntheticResult:
    """Run every stage of a synthetic campaign and report the answer.

    ``parent_dir`` becomes ``NOUS_CAMPAIGN_PARENT`` for the duration of the
    call, so the work_dir lands under the caller's tmp_path rather than in
    the target repo. The variable is restored afterwards: leaking it would
    silently relocate every later campaign in the same process.
    """
    import os

    from orchestrator.engine import Engine
    from orchestrator.iteration import IterationOutcome, setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage

    campaign = synthetic_campaign(surface, **(campaign_overrides or {}))
    # The synthetic target honours the campaign's own `workload.seed_env` when
    # one is declared. Reading it from the CAMPAIGN rather than taking it as a
    # separate harness argument is what keeps the instrument honest: a mismatch
    # between the name the campaign exports and the name the target reads is a
    # real and easy campaign-authoring bug (spec §3.8), and a harness that took
    # the name twice could never reproduce it.
    runner = make_synthetic_runner(
        surface, seed=seed,
        seed_env=(campaign["optimization"].get("workload") or {}).get("seed_env"),
    )
    path: list[str] = []

    prior_parent = os.environ.get("NOUS_CAMPAIGN_PARENT")
    os.environ["NOUS_CAMPAIGN_PARENT"] = str(parent_dir)
    try:
        work_dir = setup_work_dir(
            campaign["run_id"] + f"-{seed}", repo_path=None, campaign=campaign,
        )
        for i in range(1, max_iterations + 1):
            try:
                outcome = run_stage(campaign, work_dir, iteration=i, config_runner=runner,
                                    test_results=_all_pass(campaign), auto_approve=True)
            except OptimizationAborted as exc:
                path.append(f"aborted:{exc}")
                break
            # Task 6 records transitions.jsonl; before that, reconstruct the
            # path from which artifact each iteration wrote.
            it = work_dir / "runs" / f"iter-{i}"
            if (it / "confirmation.json").exists():
                path.append("confirm")
            elif (it / "effects.json").exists():
                path.append(json.loads((it / "effects.json").read_text()).get("stage", "screen"))
            else:
                path.append("verify")
            if outcome == IterationOutcome.COMPLETED:
                break

            # Advance the engine exactly as run_campaign does between
            # iterations (campaign.py: HUMAN_FINDINGS_GATE -> DONE -> DESIGN).
            #
            # NOT optional bookkeeping. `_enter_phase` returns False whenever
            # the engine's current phase is PAST the requested one, and the
            # block it guards at DESIGN contains BOTH
            # `artifacts.write_design_matrix` AND `_preflight_design`. Leave
            # the engine parked at HUMAN_FINDINGS_GATE after iteration 1 and
            # every later iteration silently skips both: measured on `bowl`
            # seed 3, `design_matrix.json` was absent from all four iteration
            # directories and the pre-flight — whose docstring records three
            # live-campaign failures it exists to catch — never ran once.
            #
            # This harness is the first thing in the repo to drive multiple
            # stages through ONE work_dir, so it was exercising a code path
            # production never takes. An instrument that diverges from
            # production is not an instrument. Mirror run_campaign rather
            # than inventing a variant.
            #
            # Guarded on the phase because `DONE -> DONE` is an invalid
            # transition and run_campaign only ever reaches this point from
            # HUMAN_FINDINGS_GATE. A campaign re-driven over a work_dir that
            # already finished starts at DONE, where the single legal move is
            # straight to DESIGN — so mirror the state machine's own rule
            # rather than assuming a phase.
            engine = Engine(work_dir)
            if engine.phase != "DONE":
                engine.transition("DONE")
            engine.transition("DESIGN")
    finally:
        if prior_parent is None:
            os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        else:
            os.environ["NOUS_CAMPAIGN_PARENT"] = prior_parent

    trans = work_dir / "transitions.jsonl"
    if trans.exists():
        lines = [ln for ln in trans.read_text().splitlines() if ln.strip()]
        if lines:
            path = [json.loads(ln)["from"] for ln in lines]
            path.append(json.loads(lines[-1])["to"])

    report = _read_json(work_dir / "report.json") or {}
    rec = (report.get("recommendation") or {}).get("levels")
    basis = (report.get("recommendation") or {}).get("basis", "")
    if rec is None:
        for it in reversed(_latest_iter_dirs(work_dir)):
            conf = _read_json(it / "confirmation.json")
            if conf and conf.get("confirmed_at_levels"):
                rec, basis = conf["confirmed_at_levels"], "confirmation.json"
                break
    rec = rec or {}
    opt, best = true_optimum(surface)
    gap = (best - surface.fn(rec)) if rec else float("inf")
    if surface.direction == "minimize":
        gap = -gap
    return SyntheticResult(
        recommendation=rec, basis=basis,
        residual_regret=report.get("residual_regret_model"),
        residual_regret_terminal=report.get("residual_regret_terminal"),
        true_optimum=opt, true_best=best, true_gap=gap, path=path,
        work_dir=work_dir, report=report,
    )
