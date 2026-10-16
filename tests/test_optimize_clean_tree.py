"""Clean-checkout verification (round 2, A1): verify and every epoch stage run
the target in a fresh worktree of the PRE-BUILD commit plus the recorded
mechanism patch, never in the agent's tree.

Real git repo and a real pytest test_command in tmp_path; the build agent is a
fake sdk_runner that edits files. No LLM.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_optimize_build_oracles import _build_campaign

TEST_ID = "tests/test_mech.py::test_mech"
GOOD_TEST = ("import calc, os\n\ndef test_mech():\n"
             "    open(os.environ['CWD_LOG'], 'a').write(os.getcwd() + '\\n')\n"
             "    assert calc.scale(3) == 6\n")


def _repo(tmp_path):
    repo = tmp_path / "target"
    repo.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=repo, check=True)
    (repo / "calc.py").write_text("def scale(x):\n    return x\n")
    (repo / "bench.py").write_text("print('bench')\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
                   cwd=repo, check=True)
    return repo


def _setup(tmp_path, monkeypatch, act, *, build_checks=None, name="clean",
           before_build=None, run_command="python bench.py --a={A}"):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner
    from orchestrator.sdk_dispatch import SDKResult

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    monkeypatch.setenv("CWD_LOG", str(tmp_path / "cwd.log"))
    repo = _repo(tmp_path)
    if before_build:
        before_build(tmp_path)
    s, c = _build_campaign(tmp_path, repo)
    for f in c["optimization"]["factors"]:
        f["relations"] = [{"id": f"{f['id']}-R", "kind": "correctness",
                           "statement": "s", "native_test": TEST_ID}]
    c["optimization"]["test_command"] = f"{sys.executable} -m pytest -v -p no:cacheprovider tests"
    c["optimization"]["run_command"] = run_command
    c["optimization"]["build_checks"] = {"mechanism_paths": ["calc.py", "mech.py", "tests"],
                                         **(build_checks or {})}
    wd = setup_work_dir(name, repo_path=str(repo), campaign=c)
    runner = make_synthetic_runner(s, seed=1)

    def sdk(**kw):
        act(Path(kw["cwd"]))
        return SDKResult(text="built", cost_usd=0.0, num_turns=1)

    def stage(i, **kw):
        return run_stage(c, wd, iteration=i, config_runner=runner,
                         sdk_runner=sdk if i == 1 else None, **kw)
    return repo, Path(wd), stage


def _honest(repo):
    (repo / "mech.py").write_text("def boost(x):\n    return 2 * x\n")
    (repo / "calc.py").write_text("import mech\n\ndef scale(x):\n    return mech.boost(x)\n")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_mech.py").write_text(GOOD_TEST)


def test_verify_runs_the_tests_in_the_clean_checkout_not_the_agents_tree(tmp_path, monkeypatch):
    def act(repo):
        _honest(repo)
        (repo / "helper.py").write_text("SNEAK = 1\n")          # outside scope

    repo, wd, stage = _setup(tmp_path, monkeypatch, act,
                             build_checks={"allow_out_of_scope_writes": "a stray helper"})
    stage(1)
    stage(2)
    from orchestrator.optimize.clean_tree import TREE, tree_root
    clean = tree_root(wd) / TREE
    cwds = (tmp_path / "cwd.log").read_text().split()
    assert str(clean.resolve()) in cwds, cwds
    assert str(repo.resolve()) not in cwds, "a verify test ran in the agent's tree"
    assert "boost" in (clean / "calc.py").read_text()
    assert not (clean / "helper.py").exists(), "an out-of-scope write reached the measured tree"
    rec = json.loads((wd / "clean_tree.json").read_text())
    assert rec["touched"] == ["calc.py", "mech.py", "tests/test_mech.py"]
    assert (wd / "mechanism.sha256").read_text().strip() == rec["patch_sha256"]


def test_a_planted_cache_in_the_agents_tree_never_runs(tmp_path, monkeypatch):
    """The review's .pyc attack: a planted bytecode file for an unchanged module.
    The clean checkout is built from the commit, so it does not contain it."""
    def act(repo):
        _honest(repo)
        (repo / "__pycache__").mkdir(exist_ok=True)
        (repo / "__pycache__" / "bench.cpython-313.pyc").write_bytes(b"planted")

    repo, wd, stage = _setup(tmp_path, monkeypatch, act)
    stage(1)
    stage(2)
    # Nothing writes bytecode into the measured tree either: every target
    # command runs with PYTHONPYCACHEPREFIX pointed at a Nous-owned directory.
    from orchestrator.optimize.clean_tree import TREE, tree_root
    assert not list((tree_root(wd) / TREE).rglob("*.pyc")), "a cache reached the clean tree"


def test_target_code_that_modifies_the_measured_tree_aborts_the_next_stage(tmp_path, monkeypatch):
    """Protected files are not checked once: the clean tree's integrity is
    re-checked before every stage, so agent code (here: the authored test, run at
    verify) that rewrites the harness in the tree it runs in is caught."""
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo):
        _honest(repo)
        (repo / "tests" / "test_mech.py").write_text(
            GOOD_TEST + "\ndef test_tamper():\n    open('bench.py', 'w').write('print(1)')\n")

    repo, wd, stage = _setup(tmp_path, monkeypatch, act)
    stage(1)
    stage(2)
    from orchestrator.engine import Engine
    eng = Engine(wd)
    if eng.phase != "DONE":
        eng.transition("DONE")
    eng.transition("DESIGN")
    with pytest.raises(OptimizationAborted, match="clean checkout the epoch measures was modified"):
        stage(3)


def test_a_patch_touching_the_harness_is_refused_even_with_the_scope_waiver(tmp_path, monkeypatch):
    """tools/bench.py is the harness (the run_command names it). It lies inside
    a listed directory but is not listed by exact path, so it stays protected:
    the write-scope waiver lets the build finish its early check, and the
    mechanism capture still refuses the patch."""
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo):
        _honest(repo)
        (repo / "tools" / "bench.py").write_text("print('rigged')\n")

    def setup_harness(tmp_path):
        repo = tmp_path / "target"
        (repo / "tools").mkdir()
        (repo / "tools" / "bench.py").write_text("print('bench')\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "h"],
                       cwd=repo, check=True)

    repo, wd, stage = _setup(
        tmp_path, monkeypatch, act,
        build_checks={"mechanism_paths": ["calc.py", "mech.py", "tests", "tools"],
                      "allow_out_of_scope_writes": "trust me"},
        before_build=setup_harness, run_command="python tools/bench.py --a={A}")
    with pytest.raises(OptimizationAborted, match="touches protected path"):
        stage(1)


def test_a_dirty_pre_build_tree_is_refused(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    repo, wd, stage = _setup(tmp_path, monkeypatch, _honest)
    (repo / "calc.py").write_text("def scale(x):\n    return x  # uncommitted\n")
    with pytest.raises(OptimizationAborted, match="committed before it runs"):
        stage(1)


def test_a_missing_clean_tree_is_recreated_identically(tmp_path, monkeypatch):
    import shutil

    repo, wd, stage = _setup(tmp_path, monkeypatch, _honest)
    stage(1)
    stage(2)
    from orchestrator.optimize.clean_tree import TREE, tree_root
    before = (tree_root(wd) / TREE / "calc.py").read_text()
    shutil.rmtree(tree_root(wd) / TREE)
    from orchestrator.optimize.clean_tree import ensure
    dest = ensure(repo, wd)
    assert (dest / "calc.py").read_text() == before



def test_a_measurement_batch_that_modifies_the_clean_tree_fails_that_iteration(tmp_path, monkeypatch):
    """A4: checked right after the batch, not at the next iteration's start."""
    from orchestrator.engine import Engine
    from orchestrator.optimize.clean_tree import TREE, tree_root
    from orchestrator.optimize.stage_runner import OptimizationAborted

    repo, wd, stage = _setup(tmp_path, monkeypatch, _honest)
    stage(1)
    stage(2)
    from orchestrator.optimize import stage_runner as sr
    real = None

    def tampering_runner(row):
        (tree_root(wd) / TREE / "bench.py").write_text("print('rigged')\n")
        return real(row)

    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner
    real = make_synthetic_runner(SURFACES["additive"](), seed=1)
    eng = Engine(wd)
    if eng.phase != "DONE":
        eng.transition("DONE")
    eng.transition("DESIGN")
    import yaml
    c = yaml.safe_load((wd / "campaign.epoch-1.yaml").read_text())
    with pytest.raises(OptimizationAborted, match="after the screen measurement batch"):
        sr.run_stage(c, wd, iteration=3, config_runner=tampering_runner)
    assert not (wd / "runs" / "iter-3" / "effects.json").exists()
