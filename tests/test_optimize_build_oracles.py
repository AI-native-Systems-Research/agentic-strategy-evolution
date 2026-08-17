"""Build oracles (spec §3.5, oracle 2). Real git repos in tmp_path; no LLM —
the build agent is a fake sdk_runner that edits files."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from orchestrator.optimize.build import current_mechanism_hash, snapshot_mechanism


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"; repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "mech.py").write_text("X = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def test_snapshot_records_the_diff_and_untracked_files_and_hash_changes_on_edit(tmp_path):
    repo = _git_repo(tmp_path); wd = tmp_path / "wd"; wd.mkdir()
    (repo / "mech.py").write_text("X = 2\n"); (repo / "new.py").write_text("Y = 1\n")
    h1 = snapshot_mechanism(repo, wd)
    patch = (wd / "mechanism.patch").read_text()
    assert "X = 2" in patch and "untracked: new.py" in patch
    assert (wd / "mechanism.sha256").read_text().strip() == h1 == current_mechanism_hash(repo)
    (repo / "mech.py").write_text("X = 3\n")
    assert current_mechanism_hash(repo) != h1


def test_non_git_target_yields_empty_hash_and_no_files(tmp_path):
    d = tmp_path / "plain"; d.mkdir(); wd = tmp_path / "wd"; wd.mkdir()
    assert snapshot_mechanism(d, wd) == "" and not (wd / "mechanism.patch").exists()


def test_epoch_iteration_hard_fails_when_the_mechanism_drifted(tmp_path, monkeypatch):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s = SURFACES["additive"]()
    c = synthetic_campaign(s); c["target_system"]["repo_path"] = str(repo)
    wd = setup_work_dir("drift", repo_path=str(repo), campaign=c)
    (repo / "mech.py").write_text("X = 2\n")
    snapshot_mechanism(repo, wd)
    tests_ok = {r["native_test"]: True for f in c["optimization"]["factors"] for r in f["relations"]}
    run_stage(c, wd, iteration=1, stage="verify", config_runner=make_synthetic_runner(s, seed=1), test_results=tests_ok)
    (repo / "mech.py").write_text("X = 99\n")            # drift after compile
    with pytest.raises(OptimizationAborted, match="drifted since compile"):
        run_stage(c, wd, iteration=2, config_runner=make_synthetic_runner(s, seed=1), test_results=tests_ok)


def test_epoch_iteration_proceeds_when_the_mechanism_is_unchanged(tmp_path, monkeypatch):
    """The discriminating half of the drift oracle.

    Without this, a check that aborted unconditionally (or one that compared
    the recorded hash against a constant) would still satisfy the drift test
    above. Same setup, same snapshot, no edit — the epoch iteration must run.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s = SURFACES["additive"]()
    c = synthetic_campaign(s); c["target_system"]["repo_path"] = str(repo)
    wd = setup_work_dir("nodrift", repo_path=str(repo), campaign=c)
    (repo / "mech.py").write_text("X = 2\n")
    recorded = snapshot_mechanism(repo, wd)
    assert recorded
    tests_ok = {r["native_test"]: True for f in c["optimization"]["factors"] for r in f["relations"]}
    run_stage(c, wd, iteration=1, stage="verify",
              config_runner=make_synthetic_runner(s, seed=1), test_results=tests_ok)
    run_stage(c, wd, iteration=2,
              config_runner=make_synthetic_runner(s, seed=1), test_results=tests_ok)
    assert (Path(wd) / "runs" / "iter-2").exists()


def test_recorded_hash_reaches_the_compiled_policy(tmp_path, monkeypatch):
    """`snapshot_mechanism` is what makes `mechanism_patch_hash` non-empty.

    Task 6 gave `compile_policy` the parameter; this is the wiring that fills
    it in a live campaign, so assert the recorded hash actually lands in
    policy.json rather than trusting the plumbing.
    """
    import json

    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s = SURFACES["additive"]()
    c = synthetic_campaign(s); c["target_system"]["repo_path"] = str(repo)
    wd = setup_work_dir("hashflow", repo_path=str(repo), campaign=c)
    (repo / "mech.py").write_text("X = 2\n")
    recorded = snapshot_mechanism(repo, wd)
    tests_ok = {r["native_test"]: True for f in c["optimization"]["factors"] for r in f["relations"]}
    run_stage(c, wd, iteration=1, stage="verify",
              config_runner=make_synthetic_runner(s, seed=1), test_results=tests_ok)
    pol = json.loads((Path(wd) / "policy.json").read_text())
    assert pol["compiled_from"]["mechanism_patch_hash"] == recorded


def test_build_stage_snapshots_the_mechanism_it_authored(tmp_path, monkeypatch):
    """The build stage must record the patch, not leave it to a later stage.

    The fake sdk_runner edits a file under the repo the way a real build agent
    would; after the build iteration, `mechanism.patch`/`mechanism.sha256` must
    describe that edit. No LLM: the runner is injected.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s = SURFACES["additive"]()
    c = synthetic_campaign(s)
    c["target_system"]["repo_path"] = str(repo)
    c["optimization"]["stages"] = ["build", "verify", "screen", "confirm"]
    wd = setup_work_dir("buildsnap", repo_path=str(repo), campaign=c)

    class _Result:
        is_error = False
        text = "authored the mechanism"
        input_tokens = output_tokens = 0
        cache_creation_input_tokens = cache_read_input_tokens = 0
        cost_usd = 0.0
        duration_ms = 0
        num_turns = 1

    def _fake_runner(**kwargs):
        (Path(repo) / "mech.py").write_text("X = 42\n")
        (Path(repo) / "test_mech.py").write_text("def test_mech(): assert True\n")
        return _Result()

    run_stage(c, wd, iteration=1, sdk_runner=_fake_runner,
              config_runner=make_synthetic_runner(s, seed=1))
    patch = (Path(wd) / "mechanism.patch").read_text()
    assert "X = 42" in patch and "untracked: test_mech.py" in patch
    assert (Path(wd) / "mechanism.sha256").read_text().strip() == current_mechanism_hash(repo)


# ─── oracle 2(b)/(c): the build's own claims, checked against measurement ───
#
# Both oracles below are ONE-SIDED by construction: they assert an abort. A
# check that aborted unconditionally would satisfy them, so each is paired
# with a passing-direction test on the same machinery — see
# `test_a_test_that_failed_before_build_and_passes_after_is_accepted` and
# `test_an_unchanged_baseline_passes_verify`.


def _build_campaign(tmp_path, repo):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    s = SURFACES["additive"]()
    c = synthetic_campaign(s, stages=["build", "verify", "screen", "confirm"],
                           known_valid_baseline={"A": 2, "B": 2, "C": "off"})
    c["target_system"]["repo_path"] = str(repo)
    return s, c


def _fake_build(writes: dict):
    """An sdk_runner that edits the target the way a real build agent would.

    `SDKResult` has no `session_id` field, so the fake constructs only the
    fields the dataclass declares; `text` is what `run_build` persists as the
    build summary.
    """
    from orchestrator.sdk_dispatch import SDKResult

    def runner(**kw):
        cwd = kw.get("cwd")
        if cwd is not None:
            for rel, text in writes.items():
                Path(cwd).joinpath(rel).write_text(text)
        return SDKResult(text="built", cost_usd=0.0, num_turns=1)
    return runner


def _declared_ids(campaign):
    return [r["native_test"]
            for f in campaign["optimization"]["factors"]
            for r in f["relations"]]


def test_a_test_that_passed_before_build_fails_verify(tmp_path, monkeypatch):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("prebuilt", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    all_pass = {t: True for t in ids}
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results=all_pass, sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    assert set(json.loads((wd / "pre_build_tests.json").read_text())["passed"]) == set(ids)
    with pytest.raises(OptimizationAborted, match="passed before the mechanism existed"):
        run_stage(c, wd, iteration=2, stage="verify",
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results=all_pass)


def test_a_test_that_failed_before_build_and_passes_after_is_accepted(tmp_path, monkeypatch):
    """The discriminating half of oracle 2(b).

    This is the SHAPE A BUILD IS SUPPOSED TO HAVE: the declared tests fail
    before the mechanism exists and pass after it does. Without this test, a
    check that rejected every build iteration (or that read `pre["ran"]`
    instead of `pre["passed"]`) would still satisfy the abort test above.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("honest", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: False for t in ids},
              sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    pre = json.loads((wd / "pre_build_tests.json").read_text())
    assert pre["passed"] == [] and set(pre["ran"]) == set(ids)
    run_stage(c, wd, iteration=2, stage="verify",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: True for t in ids})
    assert (Path(wd) / "policy.json").exists()


def test_allow_preexisting_tests_opts_out_of_oracle_2b(tmp_path, monkeypatch):
    """The escape hatch has to actually work, or authors will delete the check.

    A campaign whose correctness relation genuinely covers PRE-EXISTING
    behaviour (a backward-compatibility test) legitimately passes before the
    build. The opt-out is the documented way to say so, so exercise it.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    c["optimization"]["build_checks"] = {"allow_preexisting_tests": True}
    wd = setup_work_dir("optout", repo_path=str(repo), campaign=c)
    all_pass = {t: True for t in _declared_ids(c)}
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results=all_pass, sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    run_stage(c, wd, iteration=2, stage="verify",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results=all_pass)
    assert (Path(wd) / "policy.json").exists()


def test_baseline_equivalence_hard_fails_when_build_changed_the_control(tmp_path, monkeypatch):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("shifted", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    pre = {t: False for t in ids}; post = {t: True for t in ids}
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results=pre, sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    shifted = make_synthetic_runner(s, seed=1)

    def post_runner(row):
        obs = shifted(row); obs["m"] += 5.0; return obs   # build broke the control

    with pytest.raises(OptimizationAborted, match="baseline"):
        run_stage(c, wd, iteration=2, stage="verify",
                  config_runner=post_runner, test_results=post)
    be = json.loads((wd / "baseline_equivalence.json").read_text())
    assert be["ok"] is False and len(be["pre"]) == len(be["post"]) == 3


def test_an_unchanged_baseline_passes_verify(tmp_path, monkeypatch):
    """The discriminating half of oracle 2(c).

    Same wiring, same replicate count, no shift. A tolerance comparison with
    the wrong sign (`< tol` instead of `> tol`) or an absolute-vs-relative
    mix-up would abort here, and the abort test above cannot see that.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("inert", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: False for t in ids},
              sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    run_stage(c, wd, iteration=2, stage="verify",
              config_runner=make_synthetic_runner(s, seed=2),
              test_results={t: True for t in ids})
    be = json.loads((wd / "baseline_equivalence.json").read_text())
    assert be["ok"] is True
    assert len(be["pre"]) == len(be["post"]) == 3
    assert be["levels"] == {"A": 2, "B": 2, "C": "off"}
    assert (Path(wd) / "policy.json").exists()


def test_baseline_equivalence_records_the_measurement_even_when_it_passes(tmp_path, monkeypatch):
    """A tolerance the reader cannot see is a tolerance nobody can audit.

    `baseline_equivalence.json` is the certificate that the mechanism is inert
    at its control level, so the resolved tolerance and both means must be on
    disk whether or not the check tripped.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    c["optimization"]["build_checks"] = {"baseline_replicates": 2,
                                         "baseline_tolerance_pct": 25.0}
    wd = setup_work_dir("recorded", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: False for t in ids},
              sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    run_stage(c, wd, iteration=2, stage="verify",
              config_runner=make_synthetic_runner(s, seed=2),
              test_results={t: True for t in ids})
    be = json.loads((wd / "baseline_equivalence.json").read_text())
    assert be["tolerance_pct"] == 25.0
    assert len(be["pre"]) == len(be["post"]) == 2
    assert be["pre_mean"] == pytest.approx(sum(be["pre"]) / 2)
    assert be["post_mean"] == pytest.approx(sum(be["post"]) / 2)


def test_build_without_known_valid_baseline_is_rejected_by_the_validator():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    from orchestrator.validate import validate_optimization_campaign
    c = synthetic_campaign(SURFACES["additive"](),
                           stages=["build", "verify", "screen", "confirm"])
    assert any("known_valid_baseline" in e for e in validate_optimization_campaign(c))


def test_a_campaign_without_build_still_needs_no_baseline():
    """Rule 15 must not become a blanket requirement.

    `known_valid_baseline` stays optional for the ~3-call campaigns that add no
    mechanism; only the build stage's inertness check makes it load-bearing.
    """
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    from orchestrator.validate import validate_optimization_campaign
    c = synthetic_campaign(SURFACES["additive"](),
                           stages=["verify", "screen", "confirm"])
    assert not any("known_valid_baseline" in e
                   for e in validate_optimization_campaign(c))


def test_the_tolerance_is_relative_to_the_metric_not_an_absolute_delta(tmp_path, monkeypatch):
    """`|post-pre|/|pre| > tol/100`, NOT `|post-pre| > tol/100`.

    A mutation test caught this: on the additive surface the control sits near
    10.0 and the default tolerance is 5%, so a 5.0 shift trips BOTH forms and a
    noise-level shift trips neither — the abort/pass pair above cannot tell the
    relative form from the absolute one. Here the metric is scaled up 1000x and
    shifted by 0.4% of it. That is far inside 5% relative (must PASS) and far
    outside 0.05 absolute (the absolute form would abort).

    The distinction is not cosmetic: on a target measuring nanoseconds or bytes
    the absolute form aborts every campaign, and on one measuring a ratio in
    [0,1] it never aborts at all.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("scaled", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)

    def _scaled(seed, bump=0.0):
        inner = make_synthetic_runner(s, seed=seed)

        def run(row):
            obs = inner(row); obs["m"] = obs["m"] * 1000.0 + bump; return obs
        return run

    run_stage(c, wd, iteration=1, stage="build", config_runner=_scaled(1),
              test_results={t: False for t in ids},
              sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    pre_mean = json.loads((wd / "baseline_equivalence.json").read_text())["pre_mean"]
    # 0.4% of the control: inside the 5% relative band, outside 0.05 absolute.
    run_stage(c, wd, iteration=2, stage="verify",
              config_runner=_scaled(1, bump=0.004 * pre_mean),
              test_results={t: True for t in ids})
    be = json.loads((wd / "baseline_equivalence.json").read_text())
    assert be["ok"] is True
    assert abs(be["post_mean"] - be["pre_mean"]) > be["tolerance_pct"] / 100.0, (
        "the shift must exceed the ABSOLUTE reading of the tolerance, or this "
        "test cannot distinguish the two forms"
    )


def test_a_control_that_cannot_be_measured_is_not_equivalence(tmp_path, monkeypatch):
    """NaN on either side must ABORT, not pass.

    A control that failed to measure was not shown to be inert. Reading NaN as
    equivalence would make the oracle strongest exactly where the apparatus is
    weakest — the target emitting no metric for the baseline configuration is a
    bigger problem than a shifted mean, not a smaller one.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("nanctl", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: False for t in ids},
              sdk_runner=_fake_build({"mech.py": "X = 2\n"}))

    def _no_metric(row):
        return {"other": 1.0}          # the primary metric is simply absent

    with pytest.raises(OptimizationAborted, match="baseline"):
        run_stage(c, wd, iteration=2, stage="verify", config_runner=_no_metric,
                  test_results={t: True for t in ids})
    be = json.loads((wd / "baseline_equivalence.json").read_text())
    assert be["ok"] is False


# ─── the oracle's own setup must never be able to kill the campaign ──────────


def _strict_runner(row):
    """A harness that rejects flags it has never heard of.

    The pre-build reality for a `build` campaign: the mechanism's flag does not
    exist yet, and often neither does the benchmark harness, because `build` is
    what authors it. `render_apply` renders the flag anyway (at its control
    level), so a strict CLI parser exits non-zero on it.
    """
    raise RuntimeError(
        "config run exited 2: unknown flag %r" % sorted(row.levels),
    )


def test_a_prebuild_harness_that_cannot_run_does_not_kill_the_build(tmp_path, monkeypatch):
    """The oracle's SETUP must not destroy the campaign's one model call.

    Regression guard. The pre-build control measurement runs the target's
    run_command against a tree where the mechanism — and often the harness
    itself — does not exist yet. Both a non-zero exit and unparseable output are
    NORMAL there, not campaign errors. When the raise propagated, `run_build`
    was never reached: the campaign died before spending the single substantive
    model call the whole kind is built around, and authored nothing.

    So: the build completes, the mechanism IS authored, and the oracle degrades.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("strictpre", repo_path=str(repo), campaign=c)

    authored: list[int] = []

    def _sdk(**kw):
        authored.append(1)
        Path(kw["cwd"]).joinpath("mech.py").write_text("X = 2\n")
        return _fake_build({})(**kw)

    run_stage(c, wd, iteration=1, stage="build", config_runner=_strict_runner,
              test_results={t: False for t in _declared_ids(c)}, sdk_runner=_sdk)
    assert authored == [1], "the build's one model call must still happen"
    assert "X = 2" in (repo / "mech.py").read_text()
    assert (Path(wd) / "mechanism.sha256").exists(), "the build still snapshots"


def test_an_unarmed_oracle_is_recorded_not_silent(tmp_path, monkeypatch, caplog):
    """NOT ARMED must be distinguishable from PASSED, in the artifact and the log.

    A silently absent oracle on the one stage that authors code reads exactly
    like an oracle that passed. So the build records WHY it could not arm, and
    verify says so at WARNING rather than no-op'ing — otherwise a campaign
    author reading the artifacts afterwards cannot tell that nothing checked
    whether the mechanism was inert.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("unarmed", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    run_stage(c, wd, iteration=1, stage="build", config_runner=_strict_runner,
              test_results={t: False for t in ids},
              sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    be = json.loads((wd / "baseline_equivalence.json").read_text())
    assert "pre" not in be, "no pre-build measurement was taken, so claim none"
    assert "unknown flag" in be["pre_unavailable"], be
    assert be["levels"] == {"A": 2, "B": 2, "C": "off"}

    # verify must proceed (nothing to compare against) and must SAY it did not
    # check, rather than passing silently.
    import logging
    with caplog.at_level(logging.WARNING, logger="orchestrator.optimize.stage_runner"):
        run_stage(c, wd, iteration=2, stage="verify",
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: True for t in ids})
    assert any("NOT ARMED" in r.getMessage() for r in caplog.records), caplog.text
    assert (Path(wd) / "policy.json").exists(), "the epoch still compiles"
    # And the record must NOT have been rewritten into something that looks OK.
    be2 = json.loads((wd / "baseline_equivalence.json").read_text())
    assert be2.get("ok") is None and "pre_unavailable" in be2


def test_a_post_build_measurement_failure_still_aborts(tmp_path, monkeypatch):
    """The GUARD IS ASYMMETRIC on purpose, and that asymmetry is the contract.

    Pre-build, a harness that cannot run is expected and must degrade. At
    verify, the mechanism and its harness DO exist, so the same failure means
    the apparatus is broken — and the campaign must not proceed to spend an
    epoch's runs on it. If someone later wraps the verify-side call in the same
    try/except as the build-side one, this fails.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path); s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("postfail", repo_path=str(repo), campaign=c)
    ids = _declared_ids(c)
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: False for t in ids},
              sdk_runner=_fake_build({"mech.py": "X = 2\n"}))
    assert "pre" in json.loads((wd / "baseline_equivalence.json").read_text())
    with pytest.raises(RuntimeError):
        run_stage(c, wd, iteration=2, stage="verify", config_runner=_strict_runner,
                  test_results={t: True for t in ids})


# ── Task 13.5: the drift oracle's precision ──────────────────────────────────
#
# Task 12 hashed the target's WHOLE working tree. Nous itself runs the target's
# `test_command`/`run_command` with the target repo as cwd, so any artifact
# those commands leave behind that git does not ignore (a `.pytest_cache/`, a
# `run.log`, a coverage file) changed the hash — and the NEXT epoch iteration
# aborted with "mechanism drifted since compile". A false positive dressed as
# the worst available true positive. The fix is an opt-in allowlist; these four
# tests pin all four corners of it.


def _leave_artifact(repo: Path, rel: str = "run.log") -> None:
    """Stand in for what a test/run command leaves behind in the target's cwd.

    Deliberately a plain untracked file rather than a real subprocess: the
    defect is about *any* non-gitignored artifact, and a real `pytest` run
    inside a tmp repo would make the test slow and platform-dependent while
    testing the same one byte of hash input.
    """
    (repo / rel).write_text("run 1: ok\n")


def _drift_setup(tmp_path, monkeypatch, name: str, campaign_edit=None):
    """A verified campaign whose mechanism is snapshotted, ready for iter-2.

    Returns (campaign, work_dir, repo, recorded_hash). `campaign_edit` is
    applied to the campaign dict BEFORE verify compiles the policy, which is
    where `mechanism_paths` has to be in place for the epoch to see it.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s = SURFACES["additive"]()
    c = synthetic_campaign(s); c["target_system"]["repo_path"] = str(repo)
    if campaign_edit is not None:
        campaign_edit(c)
    wd = setup_work_dir(name, repo_path=str(repo), campaign=c)
    (repo / "mech.py").write_text("X = 2\n")          # the mechanism itself
    recorded = snapshot_mechanism(
        repo, wd, allowlist=_mechanism_paths_of(c),
    )
    assert recorded
    tests_ok = _declared_ids(c)
    run_stage(c, wd, iteration=1, stage="verify",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: True for t in tests_ok})
    return c, wd, repo, recorded, s


def _mechanism_paths_of(campaign) -> list[str] | None:
    return ((campaign.get("optimization") or {}).get("build_checks")
            or {}).get("mechanism_paths")


def _declare_paths(paths):
    def edit(c):
        c["optimization"].setdefault("build_checks", {})["mechanism_paths"] = paths
    return edit


def test_without_mechanism_paths_a_test_artifact_still_aborts_the_epoch(tmp_path, monkeypatch):
    """PINS TASK 12'S DEFAULT — this is the hazard, kept on purpose.

    A campaign that declares no `mechanism_paths` must behave EXACTLY as it did
    before this task: the whole tree is hashed, so a stray `run.log` from the
    target's own test command aborts the next iteration. Narrowing every
    existing campaign's oracle silently would be a worse bug than the one being
    fixed, so the fix is opt-in and this test is what keeps it opt-in.
    """
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    c, wd, repo, _rec, s = _drift_setup(tmp_path, monkeypatch, "wholetree")
    _leave_artifact(repo)                              # NOT a mechanism edit
    with pytest.raises(OptimizationAborted, match="drifted since compile"):
        run_stage(c, wd, iteration=2,
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: True for t in _declared_ids(c)})


def test_declared_mechanism_paths_exclude_a_test_command_artifact(tmp_path, monkeypatch):
    """THE FIX. The same artifact, with the allowlist declared, is not drift.

    `mechanism_paths: ["mech.py"]` says the experiment is about `mech.py`. A
    `run.log` the test command dropped is outside it, so the epoch proceeds —
    which is the whole point: Nous's own machinery must not be able to abort a
    campaign for a reason that has nothing to do with the mechanism.
    """
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    c, wd, repo, _rec, s = _drift_setup(
        tmp_path, monkeypatch, "scoped", _declare_paths(["mech.py"]),
    )
    _leave_artifact(repo)
    (repo / ".pytest_cache").mkdir(exist_ok=True)
    _leave_artifact(repo, ".pytest_cache/CACHEDIR.TAG")
    run_stage(c, wd, iteration=2,
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: True for t in _declared_ids(c)})
    assert (Path(wd) / "runs" / "iter-2").exists()


def test_declared_mechanism_paths_still_catch_a_real_mechanism_edit(tmp_path, monkeypatch):
    """THE ALLOWLIST MUST NOT WEAKEN THE ORACLE.

    An allowlist implementation that filtered too aggressively — dropping the
    tracked diff, or matching nothing — would pass the test above while
    silently disabling the oracle entirely. That is the failure mode worth
    fearing here, because it is invisible: every campaign would just proceed.
    So: an edit INSIDE the allowlist must still abort, in the presence of the
    same out-of-scope artifact that must not.
    """
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    c, wd, repo, _rec, s = _drift_setup(
        tmp_path, monkeypatch, "realedit", _declare_paths(["mech.py"]),
    )
    _leave_artifact(repo)                       # out of scope, must not count
    (repo / "mech.py").write_text("X = 99\n")    # in scope, MUST count
    with pytest.raises(OptimizationAborted, match="drifted since compile"):
        run_stage(c, wd, iteration=2,
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: True for t in _declared_ids(c)})


def test_an_untracked_mechanism_file_inside_the_allowlist_is_still_watched(tmp_path, monkeypatch):
    """A NEW FILE is the common shape of a mechanism, and it must stay watched.

    `git diff HEAD` cannot see untracked files, so the allowlist has to filter
    the untracked listing rather than drop it. If it dropped it, a mechanism
    authored as a new module would have no drift oracle at all.

    The new module is written BEFORE the snapshot (as a real build would), so
    the registered hash covers it; only then is it edited. Re-snapshotting after
    verify would instead trip the policy/sidecar cross-check, which is a
    different oracle.
    """
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    def _author_new_module(c):
        _declare_paths(["mech.py", "extra/"])(c)
        (Path(c["target_system"]["repo_path"]) / "extra").mkdir(exist_ok=True)
        (Path(c["target_system"]["repo_path"]) / "extra" / "knob.py").write_text("K = 1\n")

    c, wd, repo, _rec, s = _drift_setup(
        tmp_path, monkeypatch, "untracked", _author_new_module,
    )
    assert "untracked: extra/knob.py" in (Path(wd) / "mechanism.patch").read_text()
    (repo / "extra" / "knob.py").write_text("K = 2\n")
    with pytest.raises(OptimizationAborted, match="drifted since compile"):
        run_stage(c, wd, iteration=2,
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: True for t in _declared_ids(c)})


def test_policy_and_sidecar_hash_disagreement_is_its_own_failure(tmp_path, monkeypatch):
    """The second half of the Task 12 finding: two records of one commitment.

    `policy.json`'s `compiled_from.mechanism_patch_hash` and `mechanism.sha256`
    are both records of WHICH CODE the epoch measures. Nothing compared them,
    so a re-snapshot that did not recompile left the pair disagreeing while
    both files looked fine — and the drift check, which reads the sidecar,
    would happily certify a tree against a hash the policy never registered.
    The message must distinguish this from ordinary tree drift, because the
    fixes differ (recompile vs. restore the tree).
    """
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    c, wd, repo, recorded, s = _drift_setup(tmp_path, monkeypatch, "sidecar")
    pol = json.loads((Path(wd) / "policy.json").read_text())
    assert pol["compiled_from"]["mechanism_patch_hash"] == recorded
    # Re-stamp the sidecar alone — the mid-epoch re-snapshot the review found.
    (Path(wd) / "mechanism.sha256").write_text("f" * 64 + "\n")
    with pytest.raises(OptimizationAborted, match="registered hash"):
        run_stage(c, wd, iteration=2,
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: True for t in _declared_ids(c)})


def test_allowlist_matching_agrees_with_gits_own_pathspec(tmp_path):
    """The two halves of the filter must mean the same thing by an entry.

    The tracked half is scoped by handing the entries to git as a
    ``git diff HEAD -- <paths>`` pathspec; the untracked half is scoped by
    `_in_allowlist`. If those disagreed, one channel would drop a file the
    other kept and the effective scope would be neither. Asserted against real
    git rather than against a remembered rule, because git's pathspec semantics
    are the half we do not control.
    """
    from orchestrator.optimize.build import _in_allowlist
    repo = _git_repo(tmp_path)
    for d in ("src", "srcx"):
        (repo / d).mkdir()
        (repo / d / "a.py").write_text("V = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "dirs"], cwd=repo, check=True)
    for d in ("src", "srcx"):
        (repo / d / "a.py").write_text("V = 2\n")
    for entry in ("src", "src/", "src/a", "srcx", "nope"):
        git_says = set(subprocess.run(
            ["git", "diff", "HEAD", "--name-only", "--", entry],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.split())
        ours = {p for p in ("src/a.py", "srcx/a.py") if _in_allowlist(p, [entry])}
        assert ours == git_says, f"{entry!r}: we say {ours}, git says {git_says}"


# ── Task 14.5: a glob-shaped entry must be refused, not half-honoured ────────
#
# `_in_allowlist` is a literal path-component prefix match. Git's own pathspec,
# which scopes the TRACKED half of the same hash, DOES expand `*`. So a
# natural-looking `mechanism_paths: ["src/*"]` is honoured by one half of the
# oracle and matches nothing in the other — the untracked half, which is where
# a new mechanism module lives. That is a silently half-disabled oracle: the
# same failure family the allowlist exists to fix. Reject at validate time,
# where the author can still read the message.


def _campaign_with_paths(paths):
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    c = synthetic_campaign(SURFACES["additive"](),
                           stages=["verify", "screen", "confirm"])
    c["optimization"].setdefault("build_checks", {})["mechanism_paths"] = paths
    return c


def _mechanism_path_errors(paths):
    from orchestrator.validate import validate_optimization_campaign
    return [e for e in validate_optimization_campaign(_campaign_with_paths(paths))
            if "mechanism_paths" in e and not e.startswith("WARN:")]


@pytest.mark.parametrize("entry", ["src/*", "*.py", "mech?.py", "src/[ab].py"])
def test_glob_shaped_mechanism_paths_are_rejected(entry):
    """Every shape git would expand but `_in_allowlist` would not."""
    hits = _mechanism_path_errors([entry])
    assert hits, f"{entry!r} was accepted"
    assert any("glob" in h for h in hits), f"message must name globs: {hits}"
    assert any(entry in h for h in hits), f"message must quote the entry: {hits}"


@pytest.mark.parametrize("entry", [".", "./", "/"])
def test_a_whole_tree_shorthand_entry_is_rejected(entry):
    """`.` is not a glob metacharacter but it is the same trap.

    Git reads `.` as "the whole tree"; `_in_allowlist` normalises it to a
    literal component named `.` that matches nothing. Rejected with its own
    message rather than the glob one, because the repair differs — name the
    files, or omit the field to keep the whole-tree default deliberately.
    """
    hits = _mechanism_path_errors([entry])
    assert hits, f"{entry!r} was accepted"
    assert any("matches nothing" in h for h in hits), hits


@pytest.mark.parametrize("entry", [
    "src/", "src", "src/mech.py", "orchestrator/optimize/build.py", "a/b/c/",
])
def test_literal_mechanism_paths_are_accepted(entry):
    """The forms `_in_allowlist` and git's pathspec agree on must pass.

    This is the half that makes the check an oracle rather than a blanket
    refusal: a validator rejecting every entry would satisfy the test above
    while making the field unusable.
    """
    assert _mechanism_path_errors([entry]) == []


def test_an_empty_mechanism_paths_entry_is_rejected():
    """`""` (or whitespace) is dropped by `_mechanism_text`'s own filter.

    An allowlist of only-empty entries falls back to the whole-tree hash while
    the campaign file reads as if it were scoped — the quiet version of the
    same defect.
    """
    assert _mechanism_path_errors(["   "]), "a blank entry was accepted"


def test_mechanism_paths_absent_reports_nothing():
    """No false positive on the (backward-compatible) common case."""
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    from orchestrator.validate import validate_optimization_campaign
    c = synthetic_campaign(SURFACES["additive"](),
                           stages=["verify", "screen", "confirm"])
    assert not any("mechanism_paths" in e
                   for e in validate_optimization_campaign(c))


def test_a_rejected_glob_is_exactly_what_the_runtime_cannot_match(tmp_path):
    """The rejection set and `_in_allowlist`'s blind spot must coincide.

    Two independent rules ("what the validator refuses" and "what the runtime
    silently drops") drifting apart is how a check like this rots. Asserted
    against the real matcher over a real repo layout rather than against a
    remembered rule: for each rejected entry, `_in_allowlist` matches nothing
    while git's pathspec matches something — the asymmetry itself.
    """
    from orchestrator.optimize.build import _in_allowlist
    repo = _git_repo(tmp_path)
    (repo / "src").mkdir()
    for rel in ("src/mech.py", "src/other.py"):
        (repo / rel).write_text("V = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "src"], cwd=repo, check=True)
    for rel in ("src/mech.py", "src/other.py"):
        (repo / rel).write_text("V = 2\n")

    for entry in ("src/*", "*.py", "."):
        git_says = set(subprocess.run(
            ["git", "diff", "HEAD", "--name-only", "--", entry],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.split())
        ours = {p for p in ("src/mech.py", "src/other.py")
                if _in_allowlist(p, [entry])}
        assert git_says and not ours, (
            f"{entry!r}: premise of the rejection no longer holds "
            f"(git {git_says}, us {ours})"
        )
        assert _mechanism_path_errors([entry]), f"{entry!r} was accepted"
