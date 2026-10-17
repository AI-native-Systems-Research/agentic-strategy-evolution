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
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "bench"], cwd=repo, check=True)
    for rel, text in (pre_dirty or {}).items():
        (repo / rel).write_text(text)
    (repo / "__pycache__").mkdir(exist_ok=True)
    (repo / ".pytest_cache").mkdir(exist_ok=True)
    s, c = _build_campaign(tmp_path, repo)
    if build_checks:
        c["optimization"]["build_checks"] = {**c["optimization"]["build_checks"], **build_checks}
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


def test_editing_the_benchmark_harness_aborts(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="benchmark harness"):
        _build(tmp_path, monkeypatch, {"mech.py": "X = 2\n", "bench.py": "print(99)\n"},
               run_command="python bench.py --a={A}",
               build_checks={"mechanism_paths": ["mech.py"]})
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


# ─── the human gate after a build (audit Q10: HumanGate was never consulted) ─


def _verify(tmp_path, monkeypatch, gate):
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import SURFACES, make_synthetic_runner

    wd = _build(tmp_path, monkeypatch, {"mech.py": "X = 2\n"}, name="review")
    s = SURFACES["additive"]()
    _, c = _build_campaign(tmp_path, Path(tmp_path) / "target")
    run_stage(c, wd, iteration=2, stage="verify",
              config_runner=make_synthetic_runner(s, seed=1),
              test_results={t: True for t in _declared_ids(c)}, gate=gate)
    return wd


def test_a_rejected_build_review_spends_nothing(tmp_path, monkeypatch):
    from orchestrator.gates import HumanGate
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="not approved"):
        _verify(tmp_path, monkeypatch, HumanGate(auto_response="reject"))
    wd = tmp_path / "review"
    assert not (wd / "policy.json").exists()
    rec = json.loads((wd / "build_review.json").read_text())
    assert rec["decision"] == "reject"
    assert any(f.endswith("mechanism.patch") for f in rec["files"])


def test_an_auto_approved_build_review_is_recorded_as_unreviewed(tmp_path, monkeypatch):
    from orchestrator.gates import HumanGate
    from orchestrator.optimize.provenance import waivers

    wd = _verify(tmp_path, monkeypatch, HumanGate(auto_response="approve"))
    assert (wd / "policy.json").exists()
    rec = json.loads((wd / "build_review.json").read_text())
    assert rec["decision"] == "approve" and rec["auto"] is True
    assert {"gate": "build_review", "reason": "auto-approved",
            "note": "no human reviewed the built mechanism"} in waivers(wd, {})


def test_an_interactive_reviewer_is_asked_and_the_answer_recorded(tmp_path, monkeypatch):
    from orchestrator.gates import HumanGate

    monkeypatch.setattr("builtins.input", lambda *_a: "approve")
    wd = _verify(tmp_path, monkeypatch, HumanGate())
    rec = json.loads((wd / "build_review.json").read_text())
    assert rec == {**rec, "decision": "approve", "auto": False}


# ─── fail closed against a careless or adversarial build agent (review G1-G5) ─


def _agent(action):
    """A fake build agent that runs ``action(repo, work_dir_root)`` with full
    access to the target -- the reach a bypassPermissions agent has."""
    from orchestrator.sdk_dispatch import SDKResult

    def runner(**kw):
        action(Path(kw["cwd"]))
        return SDKResult(text="built", cost_usd=0.0, num_turns=1)
    return runner


def _adversarial(tmp_path, monkeypatch, action, *, build_checks=None,
                 run_command=None, extra_tracked=None, name="adv"):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    for rel, text in (extra_tracked or {}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "x",
                    "--allow-empty"], cwd=repo, check=True)
    s, c = _build_campaign(tmp_path, repo)
    c["optimization"]["build_checks"] = {"mechanism_paths": ["mech.py"], **(build_checks or {})}
    if run_command:
        c["optimization"]["run_command"] = run_command
    wd = setup_work_dir(name, repo_path=str(repo), campaign=c)
    runner = make_synthetic_runner(s, seed=1)

    def build():
        run_stage(c, wd, iteration=1, stage="build", config_runner=runner,
                  test_results={t: False for t in _declared_ids(c)},
                  sdk_runner=_agent(lambda r: action(r, wd)))

    def verify():
        run_stage(c, wd, iteration=2, stage="verify", config_runner=runner,
                  test_results={t: True for t in _declared_ids(c)})
    return wd, build, verify


def _git_in(repo, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, check=True,
                   capture_output=True)


def test_deleting_the_pre_build_record_during_the_build_aborts(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / "mech.py").write_text("X = 2\n")
        (Path(wd) / "pre_build_tests.json").unlink()

    _, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="gate record"):
        build()


def test_forging_the_pre_build_control_measurement_aborts(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / "mech.py").write_text("X = 2\n")
        p = Path(wd) / "baseline_equivalence.json"
        rec = json.loads(p.read_text())
        rec["pre"] = [999.0] * len(rec["pre"])
        p.write_text(json.dumps(rec))

    _, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="baseline_equivalence.json"):
        build()


def test_a_record_removed_between_build_and_verify_fails_verify(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    wd, build, verify = _adversarial(
        tmp_path, monkeypatch, lambda repo, wd: (repo / "mech.py").write_text("X = 2\n"))
    build()
    (Path(wd) / "pre_build_tests.json").unlink()
    with pytest.raises(OptimizationAborted, match="missing"):
        verify()
    assert not (Path(wd) / "policy.json").exists()


def test_a_record_edited_between_build_and_verify_fails_verify(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    wd, build, verify = _adversarial(
        tmp_path, monkeypatch, lambda repo, wd: (repo / "mech.py").write_text("X = 2\n"))
    build()
    p = Path(wd) / "pre_build_tests.json"
    rec = json.loads(p.read_text())
    rec["failure_kinds"] = {t: "behavioral" for t in rec["ran"]}
    p.write_text(json.dumps(rec))
    with pytest.raises(OptimizationAborted, match="is broken"):
        verify()


def test_verify_of_a_build_campaign_with_no_build_records_fails_closed(tmp_path, monkeypatch):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s, c = _build_campaign(tmp_path, repo)
    wd = setup_work_dir("nobuild", repo_path=str(repo), campaign=c)
    with pytest.raises(OptimizationAborted, match="unsealed"):
        run_stage(c, wd, iteration=2, stage="verify",
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: True for t in _declared_ids(c)})


def test_committing_the_edits_does_not_hide_them(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / "other.py").write_text("Y = 1\n")
        _git_in(repo, "add", "other.py")
        _git_in(repo, "commit", "-qm", "sneak")

    wd, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="HEAD moved"):
        build()


def test_stashing_moves_refs_stash_and_aborts(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / "mech.py").write_text("X = 7\n")
        _git_in(repo, "stash")

    _, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="refs/stash moved"):
        build()


def test_a_git_failure_after_the_build_is_a_violation_not_a_pass(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / "mech.py").write_text("X = 2\n")
        (repo / ".git" / "index").write_bytes(b"not an index")

    wd, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="readable before the build and is not"):
        build()
    rec = json.loads((Path(wd) / "build_scope.json").read_text())
    assert rec["ok"] is False and rec["integrity_violations"]


def test_skip_worktree_does_not_hide_an_edit(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        _git_in(repo, "update-index", "--skip-worktree", "other.py")
        (repo / "other.py").write_text("Y = 999\n")

    _, build, _ = _adversarial(tmp_path, monkeypatch, act,
                               extra_tracked={"other.py": "Y = 1\n"})
    with pytest.raises(OptimizationAborted, match="flags changed"):
        build()


def test_a_file_hidden_through_info_exclude_is_still_a_write(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / ".git" / "info").mkdir(exist_ok=True)
        with open(repo / ".git" / "info" / "exclude", "a") as fh:
            fh.write("conftest.py\n")
        (repo / "conftest.py").write_text("import pytest\n")

    wd, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="info/exclude"):
        build()
    assert "conftest.py" in json.loads((Path(wd) / "build_scope.json").read_text())["written"]


def test_an_already_ignored_source_file_written_by_the_build_is_seen(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / "hidden").mkdir(exist_ok=True)
        (repo / "hidden" / "plugin.py").write_text("HACK = 1\n")

    _, build, _ = _adversarial(tmp_path, monkeypatch, act,
                               extra_tracked={".gitignore": "hidden/\n"})
    with pytest.raises(OptimizationAborted, match=r"hidden/plugin.py"):
        build()


@pytest.mark.parametrize("cmd,harness", [
    ("python -m bench.run --a={A}", "bench/run.py"),
    ("go run ./cmd/bench --a={A}", "cmd/bench/main.go"),
    ("make bench", "Makefile"),
])
def test_the_harness_is_protected_however_the_run_command_reaches_it(
        tmp_path, monkeypatch, cmd, harness):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / harness).write_text("tampered\n")

    _, build, _ = _adversarial(
        tmp_path, monkeypatch, act, run_command=cmd,
        # The harness's directory is in scope, the harness file itself is not
        # listed exactly: protection alone must refuse the edit.
        build_checks={"mechanism_paths": ["mech.py", harness.rsplit("/", 1)[0]
                                          if "/" in harness else "mech.py"]},
        extra_tracked={harness: "original\n"})
    with pytest.raises(OptimizationAborted, match="benchmark harness|outside build_checks"):
        build()


def test_a_build_stage_without_mechanism_paths_fails_validation():
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES
    from orchestrator.validate import validate_optimization_campaign

    c = synthetic_campaign(SURFACES["additive"](), stages=["build", "verify", "screen", "confirm"],
                           known_valid_baseline={"A": 2, "B": 2, "C": "off"})
    errs = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN:")]
    assert any("mechanism_paths is not declared" in e for e in errs), errs
    c["optimization"]["build_checks"] = {"mechanism_paths": ["src"]}
    errs = [e for e in validate_optimization_campaign(c) if not e.startswith("WARN:")]
    assert not any("mechanism_paths is not declared" in e for e in errs), errs


def test_a_gate_that_does_not_say_whether_a_human_answered_is_recorded_as_automatic(
        tmp_path, monkeypatch):
    """A custom gate object (no is_automatic) must not be recorded as a human review."""
    class _Gate:
        def prompt(self, *a, **k):
            return "approve", None

    wd = _verify(tmp_path, monkeypatch, _Gate())
    assert json.loads((wd / "build_review.json").read_text())["auto"] is True


def test_humangate_reports_whether_it_is_automatic():
    from orchestrator.gates import HumanGate

    assert HumanGate(auto_response="approve").is_automatic is True
    assert HumanGate().is_automatic is False



# ─── round 2: records out of reach and sealed (A2) ───────────────────────────


def test_forging_a_record_and_its_digest_together_fails_the_seal(tmp_path, monkeypatch):
    """The round-1 forgery: edit pre_build_tests.json AND update the digest
    build_scope.json keeps for it. Without the HMAC key the seal breaks."""
    from orchestrator.optimize.build_scope import record_digest
    from orchestrator.optimize.stage_runner import OptimizationAborted

    wd, build, verify = _adversarial(
        tmp_path, monkeypatch, lambda repo, wd: (repo / "mech.py").write_text("X = 2\n"))
    build()
    p = Path(wd) / "pre_build_tests.json"
    rec = json.loads(p.read_text())
    rec["failure_kinds"] = {t: "behavioral" for t in rec["ran"]}
    p.write_text(json.dumps(rec))
    sp = Path(wd) / "build_scope.json"
    scope = json.loads(sp.read_text())
    scope["gate_records"]["pre_build_tests.json"] = record_digest(Path(wd), "pre_build_tests.json")
    sp.write_text(json.dumps(scope))
    with pytest.raises(OptimizationAborted, match="is broken"):
        verify()


def test_a_build_with_its_work_dir_inside_the_repo_is_refused(tmp_path, monkeypatch):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    repo = _git_repo(tmp_path)
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(repo / ".nous"))
    s, c = _build_campaign(tmp_path, repo)
    c["optimization"]["build_checks"] = {"mechanism_paths": ["mech.py"]}
    wd = setup_work_dir("inside", repo_path=str(repo), campaign=c)
    with pytest.raises(OptimizationAborted, match="INSIDE the target repo"):
        run_stage(c, wd, iteration=1, stage="build",
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: False for t in _declared_ids(c)},
                  sdk_runner=_fake_build({"mech.py": "X = 2\n"}))


# ─── round 2, A3: nothing the build starts may outlive it ────────────────────


def test_a_process_the_build_leaves_running_is_killed_and_fails_the_build(tmp_path, monkeypatch):
    import os
    import sys

    from orchestrator.optimize.stage_runner import OptimizationAborted

    pids = []

    def act(repo, wd):
        (repo / "mech.py").write_text("X = 2\n")
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             start_new_session=True)
        pids.append(p.pid)

    _, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="process"):
        build()
    import time
    time.sleep(0.3)
    try:
        os.waitpid(pids[0], os.WNOHANG)
    except ChildProcessError:
        pass
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)
    rec = json.loads((tmp_path / "adv" / "build_isolation.json").read_text())
    assert pids[0] in rec["survivors"] and pids[0] in rec["killed"]


def test_a_build_whose_processes_all_finish_passes_isolation(tmp_path, monkeypatch):
    import sys

    def act(repo, wd):
        (repo / "mech.py").write_text("X = 2\n")
        subprocess.run([sys.executable, "-c", "pass"], check=True)

    wd, build, _ = _adversarial(tmp_path, monkeypatch, act)
    build()
    assert json.loads((Path(wd) / "build_isolation.json").read_text())["survivors"] == []


def test_a_size_and_mtime_preserving_rewrite_of_an_ignored_config_is_seen(tmp_path, monkeypatch):
    import os

    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        p = repo / "hidden" / "settings.py"
        st = p.stat()
        p.write_text("HACK = 2\n")                       # same length as before
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))

    def seed(repo):
        (repo / "hidden").mkdir()
        (repo / "hidden" / "settings.py").write_text("SAFE = 1\n")

    from orchestrator.optimize import build_scope as bs
    _, build, _ = _adversarial(
        tmp_path, monkeypatch, lambda repo, wd: ((repo / "mech.py").write_text("X = 2\n"), act(repo, wd)),
        extra_tracked={".gitignore": "hidden/\n"})
    seed(tmp_path / "target")
    with pytest.raises(OptimizationAborted, match="hidden/settings.py"):
        build()
    rec = json.loads((tmp_path / "adv" / "build_scope.json").read_text())
    assert rec["not_checked"] and "clean checkout" in rec["role"]


def test_the_build_prompt_states_the_scope_the_protected_set_and_the_git_rules(tmp_path):
    from orchestrator.optimize.build import build_prompt

    repo = _git_repo(tmp_path)
    _, c = _build_campaign(tmp_path, repo)
    c["optimization"]["build_checks"] = {"mechanism_paths": ["src/mech.py", "tests/test_mech.py"]}
    c["optimization"]["run_command"] = "python bench/run.py --a={A}"
    text = build_prompt(c, ["tests/test_mech.py::test_x"])
    assert "  - src/mech.py" in text and "  - tests/test_mech.py" in text
    assert "python bench/run.py" in text and "pre-existing test file" in text
    for rule in ("Never commit, stash, check out", ".git/info/exclude", "skip-worktree",
                 "never\nleave a process running"):
        assert rule in text, rule



# ─── round 2, C1 / C3 ────────────────────────────────────────────────────────


def test_an_unreadable_git_tree_before_the_build_is_not_recorded_as_non_git(tmp_path):
    from orchestrator.optimize import build_scope as bs

    repo = _git_repo(tmp_path)
    wd = tmp_path / "wd"
    wd.mkdir()
    (repo / ".git" / "index").write_bytes(b"corrupt")
    before = bs.snapshot(repo, wd)
    assert before["is_git"] is True and before["git"] is False
    with pytest.raises(bs.BuildScopeViolation, match="could not be read BEFORE"):
        bs.check({"optimization": {"build_checks": {"mechanism_paths": ["mech.py"]}}},
                 repo, wd, before)


def test_an_unparseable_run_command_cannot_leave_the_harness_unprotected(tmp_path):
    from orchestrator.optimize import build_scope as bs

    repo = _git_repo(tmp_path)
    camp = {"optimization": {"run_command": "python 'unclosed"}}
    with pytest.raises(bs.BuildScopeViolation, match="cannot be parsed"):
        bs.protected_paths(repo, camp, [])


@pytest.mark.parametrize("bc", [{}, {"mechanism_paths": ["."]}, {"mechanism_paths": ["**"]}])
def test_a_build_with_no_or_whole_repo_scope_is_refused_at_run_time(tmp_path, monkeypatch, bc):
    """The runtime guard (review C4): validation only sees explicit stages."""
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _git_repo(tmp_path)
    s, c = _build_campaign(tmp_path, repo)
    c["optimization"]["build_checks"] = bc
    wd = setup_work_dir("scope", repo_path=str(repo), campaign=c)
    with pytest.raises(OptimizationAborted, match="mechanism_paths"):
        run_stage(c, wd, iteration=1, stage="build",
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: False for t in _declared_ids(c)},
                  sdk_runner=_fake_build({"mech.py": "X = 2\n"}))


# ─── round 3, A3: the agent repo's git control files ─────────────────────────


@pytest.mark.parametrize("what", ["hook", "fsmonitor", "attributes"])
def test_writing_the_agent_repos_git_control_files_aborts_the_build(tmp_path, monkeypatch, what):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    def act(repo, wd):
        (repo / "mech.py").write_text("X = 2\n")
        g = repo / ".git"
        if what == "hook":
            (g / "hooks" / "post-checkout").write_text("#!/bin/sh\necho pwn > bench.py\n")
        elif what == "fsmonitor":
            _git_in(repo, "config", "core.fsmonitor", "/tmp/x")
        else:
            (g / "info").mkdir(exist_ok=True)
            (g / "info" / "attributes").write_text("* filter=x\n")

    _, build, _ = _adversarial(tmp_path, monkeypatch, act)
    with pytest.raises(OptimizationAborted, match="git control files"):
        build()


# ─── round 3, C1/C2: isolation fails closed and covers target commands ───────


def test_isolation_fails_closed_when_processes_cannot_be_observed(tmp_path, monkeypatch):
    from orchestrator.optimize import isolation

    def broken(*a, **k):
        raise isolation.ObservationError("could not observe processes: ps exited 1")
    monkeypatch.setattr(isolation, "_table", broken)
    with pytest.raises(isolation.BuildSurvivors, match="could not observe"):
        with isolation.track(tmp_path):
            pass


def test_a_poller_failure_mid_build_fails_the_build(tmp_path, monkeypatch):
    import time

    from orchestrator.optimize import isolation

    real, calls = isolation._table, {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 3:
            raise isolation.ObservationError("could not observe processes: ps timed out")
        return real()
    monkeypatch.setattr(isolation, "_table", flaky)
    with pytest.raises(isolation.BuildSurvivors, match="could not be observed throughout"):
        with isolation.track(tmp_path, interval=0.05):
            time.sleep(0.5)
    assert json.loads((tmp_path / "build_isolation.json").read_text())["poll_errors"]


def test_a_target_command_that_leaves_a_process_running_is_reaped_and_recorded(tmp_path):
    import os
    import sys
    import time

    from orchestrator.optimize import reaper, runner

    reaper.take_survivors()
    pidf = tmp_path / "pid"
    cmd = (f"{sys.executable} -c \"import subprocess,sys; "
           f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
           f"stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
           f"open({str(pidf)!r},'w').write(str(p.pid))\"")
    runner.run_test_command(cmd, cwd=tmp_path)
    left = reaper.take_survivors()
    assert left and left[0]["cmd"].startswith(sys.executable)
    time.sleep(0.2)
    pid = int(pidf.read_text())
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_build_with_no_repo_is_refused_with_a_clear_message(tmp_path, monkeypatch):
    """E3: not a misleading 'record absent' seal error at verify."""
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    s, c = _build_campaign(tmp_path, tmp_path / "unused")
    c["target_system"]["repo_path"] = None
    wd = setup_work_dir("norepo", repo_path=None, campaign=c)
    with pytest.raises(OptimizationAborted, match="needs target_system.repo_path"):
        run_stage(c, wd, iteration=1, stage="build",
                  config_runner=make_synthetic_runner(s, seed=1),
                  test_results={t: False for t in _declared_ids(c)},
                  sdk_runner=_fake_build({}))


def test_a_target_child_that_calls_setsid_is_still_reaped_and_recorded(tmp_path):
    """Round 4, item 4: leaving the command's process group does not escape."""
    import os
    import sys
    import time

    from orchestrator.optimize import reaper, runner

    reaper.take_survivors()
    pidf = tmp_path / "pid"
    cmd = (f"{sys.executable} -c \"import subprocess,sys,time; "
           f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
           f"start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
           f"open({str(pidf)!r},'w').write(str(p.pid)); time.sleep(0.5)\"")
    runner.run_test_command(cmd, cwd=tmp_path)
    left = reaper.take_survivors()
    pid = int(pidf.read_text())
    assert left and pid in left[0]["escaped_session"], left
    time.sleep(0.2)
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_child_that_calls_setsid_after_the_first_poll_is_reaped(tmp_path):
    """Round 5, item 2 (repro a_setsid.py 'late'): seen in the command's group,
    then setsid() -- the pgid must be re-read at reap time."""
    import os
    import sys
    import time

    from orchestrator.optimize import reaper

    pidf = tmp_path / "pid"
    child = (
        "import os, sys, time\n"
        "if os.fork() == 0:\n"
        "    fd = os.open(os.devnull, os.O_RDWR); [os.dup2(fd, i) for i in (0, 1, 2)]\n"
        "    time.sleep(0.5)\n"
        "    os.setsid()\n"
        f"    open({str(pidf)!r}, 'w').write(str(os.getpid()))\n"
        "    time.sleep(30); os._exit(0)\n"
        "time.sleep(1.0)\n")
    reaper.take_survivors()
    reaper.run_in_process_group([sys.executable, "-c", child], capture_output=True,
                                text=True, timeout=30)
    left = reaper.take_survivors()
    pid = int(pidf.read_text())
    assert left and pid in left[0]["escaped_session"], left
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
