"""Build oracles (spec §3.5, oracle 2). Real git repos in tmp_path; no LLM —
the build agent is a fake sdk_runner that edits files."""
from __future__ import annotations

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
