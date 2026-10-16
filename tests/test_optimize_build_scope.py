"""The build agent's write scope is enforced by diffing what it changed
(audit Q10). Real git repos in tmp_path; the build agent is a fake
sdk_runner that edits files. No LLM."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.test_optimize_build_oracles import (
    _build_campaign,
    _declared_ids,
    _fake_build,
    _git_repo,
)


def _build(tmp_path, monkeypatch, writes, *, build_checks=None, run_command=None,
           pre_dirty=None, name="scope"):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    (repo / "bench.py").write_text("print('bench')\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bench"], cwd=repo, check=True)
    for rel, text in (pre_dirty or {}).items():
        (repo / rel).write_text(text)
    (repo / "__pycache__").mkdir(exist_ok=True)
    (repo / ".pytest_cache").mkdir(exist_ok=True)
    s, c = _build_campaign(tmp_path, repo)
    if build_checks:
        c["optimization"]["build_checks"] = build_checks
    if run_command:
        c["optimization"]["run_command"] = run_command
    wd = setup_work_dir(name, repo_path=str(repo), campaign=c)
    run_stage(c, wd, iteration=1, stage="build",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: False for t in _declared_ids(c)},
              sdk_runner=_fake_build(writes))
    return wd


def _record(wd):
    return json.loads((Path(wd) / "build_scope.json").read_text())


def test_a_write_outside_mechanism_paths_aborts(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="outside build_checks.mechanism_paths"):
        _build(tmp_path, monkeypatch, {"mech.py": "X = 2\n", "other.py": "Y = 1\n"},
               build_checks={"mechanism_paths": ["mech.py"]})
    rec = _record(tmp_path / "scope")
    assert rec["outside_scope"] == ["other.py"] and rec["ok"] is False


def test_writes_inside_the_scope_pass_and_are_recorded(tmp_path, monkeypatch):
    wd = _build(tmp_path, monkeypatch, {"mech.py": "X = 2\n"},
                build_checks={"mechanism_paths": ["mech.py"]})
    rec = _record(wd)
    assert rec["ok"] is True and rec["written"] == ["mech.py"]


def test_editing_the_benchmark_harness_aborts_even_without_mechanism_paths(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="benchmark harness"):
        _build(tmp_path, monkeypatch, {"mech.py": "X = 2\n", "bench.py": "print(99)\n"},
               run_command="python bench.py --a={A}")
    assert _record(tmp_path / "scope")["protected_touched"] == ["bench.py"]


def test_a_harness_edit_listed_by_exact_path_is_part_of_the_mechanism(tmp_path, monkeypatch):
    wd = _build(tmp_path, monkeypatch, {"mech.py": "X = 2\n", "bench.py": "print(99)\n"},
                run_command="python bench.py --a={A}",
                build_checks={"mechanism_paths": ["mech.py", "bench.py"]})
    assert _record(wd)["ok"] is True


def test_a_recorded_waiver_lets_the_build_proceed(tmp_path, monkeypatch):
    wd = _build(tmp_path, monkeypatch, {"mech.py": "X = 2\n", "other.py": "Y = 1\n"},
                build_checks={"mechanism_paths": ["mech.py"],
                              "allow_out_of_scope_writes": "vendored helper"})
    rec = _record(wd)
    assert rec["ok"] is True and rec["waived"] == "vendored helper"
    assert rec["outside_scope"] == ["other.py"]


def test_files_dirty_before_the_build_and_tool_caches_do_not_count(tmp_path, monkeypatch):
    wd = _build(tmp_path, monkeypatch,
                {"mech.py": "X = 2\n", "__pycache__/mech.cpython-313.pyc": "zz",
                 ".pytest_cache/v": "zz"},
                build_checks={"mechanism_paths": ["mech.py"]},
                pre_dirty={"notes.txt": "the author's scratch file\n"})
    rec = _record(wd)
    assert rec["ok"] is True and rec["written"] == ["mech.py"], rec
