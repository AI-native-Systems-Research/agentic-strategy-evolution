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
