"""Oracle 2(d): a build's authored correctness tests must discriminate the
mechanism, not merely its existence (audit Q10, test_vacuity.py).

Real git repos with a real pytest ``test_command`` in tmp_path; the build
agent is a fake sdk_runner that writes files. No LLM. Each case runs the
build iteration and then verify, and asserts the verdict and what
``authored_tests.json`` records.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.optimize.test_vacuity import failure_kind, failure_texts
from tests.test_optimize_build_oracles import _build_campaign, _fake_build

TEST_ID = "tests/test_mech.py::test_mech"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "calc.py").write_text("def scale(x):\n    return x\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _run(tmp_path, monkeypatch, writes, *, build_checks=None, name="vac"):
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    repo = _repo(tmp_path)
    s, c = _build_campaign(tmp_path, repo)
    for f in c["optimization"]["factors"]:
        f["relations"] = [{"id": f"{f['id']}-R", "kind": "correctness",
                           "statement": "the mechanism does what it claims",
                           "native_test": TEST_ID}]
    c["optimization"]["build_checks"] = {"mechanism_paths": ["mech.py", "calc.py", "tests"]}
    c["optimization"]["test_command"] = (
        f"{sys.executable} -m pytest -v -p no:cacheprovider tests")
    if build_checks:
        c["optimization"]["build_checks"].update(build_checks)
    wd = setup_work_dir(name, repo_path=str(repo), campaign=c)

    def sdk(**kw):
        Path(kw["cwd"], "tests").mkdir(exist_ok=True)
        return _fake_build(writes)(**kw)

    runner = make_synthetic_runner(s, seed=1)
    run_stage(c, wd, iteration=1, stage="build", config_runner=runner, sdk_runner=sdk)
    run_stage(c, wd, iteration=2, stage="verify", config_runner=runner)
    return wd


def _record(tmp_path, name="vac"):
    return json.loads((tmp_path / name / "authored_tests.json").read_text())


def test_an_import_only_test_of_a_new_module_is_rejected_as_vacuous(tmp_path, monkeypatch):
    """The audit's case: fails before only because the module is absent,
    passes after whatever the mechanism does."""
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="does not observe the mechanism"):
        _run(tmp_path, monkeypatch, {
            "mech.py": "def boost(x):\n    return 2 * x\n",
            "calc.py": "import mech\n\ndef scale(x):\n    return mech.boost(x)\n",
            "tests/test_mech.py": "import mech\n\ndef test_mech():\n    assert mech.boost\n",
        })
    rec = _record(tmp_path)
    assert rec["tests"][TEST_ID]["evidence"] is None
    assert rec["mutant"]["reverted"] == ["calc.py"]
    assert rec["mutant"]["verdicts"][TEST_ID] is True


def test_a_test_that_only_fails_on_a_missing_symbol_is_rejected(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="missing symbol"):
        _run(tmp_path, monkeypatch, {
            "calc.py": "def scale(x):\n    return x\n\ndef fast(x):\n    return x\n",
            "tests/test_mech.py": "from calc import fast\n\ndef test_mech():\n    assert fast\n",
        })
    rec = _record(tmp_path)
    assert rec["mutant"]["kinds"][TEST_ID] == "absence"


def test_a_test_that_observes_the_mechanisms_behaviour_passes(tmp_path, monkeypatch):
    wd = _run(tmp_path, monkeypatch, {
        "mech.py": "def boost(x):\n    return 2 * x\n",
        "calc.py": "import mech\n\ndef scale(x):\n    return mech.boost(x)\n",
        "tests/test_mech.py": ("import calc\n\ndef test_mech():\n"
                               "    assert calc.scale(3) == 6\n"),
    })
    rec = _record(tmp_path)
    assert rec["ok"] is True
    assert rec["tests"][TEST_ID] == {"evidence": "mutant_behavioral_failure"}
    assert (wd / "policy.json").exists()
    # The mutant worktree is cleaned up; the target's tree is untouched.
    assert "boost" in (Path(tmp_path) / "target" / "calc.py").read_text()
    wt = subprocess.run(["git", "worktree", "list"], cwd=tmp_path / "target",
                        capture_output=True, text=True).stdout
    # The clean tree and the mutants are PRIVATE repositories: the agent's repo
    # has no worktrees registered at all, and no mutant is left behind.
    assert len(wt.strip().splitlines()) == 1, wt
    from orchestrator.optimize.clean_tree import tree_root
    assert not list(tree_root(wd).glob("mutants/*")) and not list(tree_root(wd).glob("stubs/*"))


def test_a_waiver_lets_a_nondiscriminating_test_through_and_is_recorded(tmp_path, monkeypatch):
    wd = _run(tmp_path, monkeypatch, {
        "mech.py": "def boost(x):\n    return 2 * x\n",
        "tests/test_mech.py": "import mech\n\ndef test_mech():\n    assert mech.boost\n",
    }, build_checks={"allow_nondiscriminating_tests": "smoke test only; covered by 2(c)"})
    rec = _record(tmp_path)
    assert rec["ok"] is True and rec["waived"] == "smoke test only; covered by 2(c)"
    assert (wd / "policy.json").exists()


@pytest.mark.parametrize("text,kind", [
    ("E   ModuleNotFoundError: No module named 'mech'", "absence"),
    ("    assert mech.f(2) == 4\nE   AttributeError: module 'mech' has no attribute 'f'", "absence"),
    ("E   TypeError: scale() got an unexpected keyword argument 'factor'", "absence"),
    ("./x_test.go:9:2: undefined: Boost", "absence"),
    ("E   assert 3 == 6", "behavioral"),
    ("E   AssertionError: expected 6", "behavioral"),
    ("E   ZeroDivisionError: division by zero", "unknown"),   # neither list: not evidence
    ("error[E0599]: no method named `boost` found for struct `Calc`", "absence"),
    ("error TS2339: Property 'boost' does not exist on type 'Calc'.", "absence"),
    ("E   TypeError: scale() takes 1 positional argument but 2 were given", "absence"),
    ("E       fixture 'boosted' not found", "absence"),
    ("Timeout: test exceeded 30s", "unknown"),
    ("   12 |     assert_eq!(calc.scale(3), 6);", "unknown"),         # a source echo
    ("E   assert False\nE    +  where False = hasattr(<module 'calc'>, 'fast')", "absence"),
    ("", "unknown"),
])
def test_failure_kinds(text, kind):
    assert failure_kind(text) == kind


def test_failure_text_is_isolated_per_test_from_pytest_output():
    out = ("tests/t.py::test_a FAILED\ntests/t.py::test_b FAILED\n"
           "_____ test_a _____\n\n    def test_a():\n>       assert f() == 2\n"
           "E   assert 1 == 2\n_____ test_b _____\nE   ModuleNotFoundError: x\n"
           "=== short test summary info ===\n")
    texts = failure_texts(out, ["tests/t.py::test_a", "tests/t.py::test_b"])
    assert failure_kind(texts["tests/t.py::test_a"]) == "behavioral"
    assert failure_kind(texts["tests/t.py::test_b"]) == "absence"


def test_test_names_are_matched_exactly_and_ambiguous_sections_are_not_used():
    out = ("FAILED tests/t.py::test_ab - AssertionError: x\n"
           "_____ test_dup _____\nE   assert 1 == 2\n"
           "_____ test_dup _____\nE   ModuleNotFoundError: m\n")
    texts = failure_texts(out, ["tests/t.py::test_a", "tests/a.py::test_dup"])
    assert "tests/t.py::test_a" not in texts           # test_ab is not test_a
    assert "tests/a.py::test_dup" not in texts         # two sections share the name


def test_unisolatable_output_gives_no_text_and_no_evidence():
    out = "Tests: 1 failed, 3 passed\nAssertionError somewhere in the suite\n"
    assert failure_texts(out, ["suite::case"]) == {}


def _check_direct(tmp_path, pre, *, repo=None, run_tests=None, scope_written=None,
                  build_checks=None):
    from orchestrator.optimize import test_vacuity
    from orchestrator.optimize.factors import parse_factors

    (tmp_path / "pre_build_tests.json").write_text(json.dumps(pre))
    if scope_written is not None:
        (tmp_path / "build_scope.json").write_text(json.dumps({"written": scope_written}))
    f = {"id": "A", "name": "a", "type": "choice", "levels": ["x", "y"], "apply": "--a={level}",
         "manipulation": {"observable": "cfg.a", "op": "==", "value": "{level}"},
         "relations": [{"id": "R", "kind": "correctness", "statement": "s",
                        "native_test": TEST_ID}]}
    camp = {"optimization": {"build_checks": build_checks or {}}}
    return test_vacuity.check(camp, tmp_path, parse_factors([f]), repo=repo,
                              run_tests=run_tests, built_ids={"A"})


def test_an_unclassified_pre_build_failure_is_not_evidence_when_output_existed(tmp_path):
    pre = {"ran": [TEST_ID], "passed": [], "failure_kinds": {TEST_ID: "unknown"},
           "output_recorded": True}
    with pytest.raises(ValueError, match="no mutant could be run"):
        _check_direct(tmp_path, pre)
    pre["output_recorded"] = False          # injected verdicts: the test seam
    pre["verdicts_injected"] = True
    rec = _check_direct(tmp_path, pre)
    assert rec["tests"][TEST_ID]["evidence"] == "pre_build_failure_unclassified"


def test_a_git_failure_building_the_mutant_is_recorded_not_blamed_on_the_test(tmp_path):
    pre = {"ran": [], "passed": [], "failure_kinds": {}, "output_recorded": True}
    not_git = tmp_path / "plain"
    not_git.mkdir()
    with pytest.raises(ValueError, match="no mutant could be run"):
        _check_direct(tmp_path, pre, repo=not_git, run_tests=lambda cwd: ({}, ""),
                      scope_written=["calc.py"])
    rec = json.loads((tmp_path / "authored_tests.json").read_text())
    assert "could not build the mutant" in rec["mutant"]["unavailable"]
    assert "git" in rec["mutant"]["unavailable"]


def test_a_hasattr_assertion_test_is_rejected(tmp_path, monkeypatch):
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="missing symbol"):
        _run(tmp_path, monkeypatch, {
            "calc.py": "def scale(x):\n    return x\n\ndef fast(x):\n    return 2 * x\n",
            "tests/test_mech.py": ("import calc\n\ndef test_mech():\n"
                                   "    assert hasattr(calc, 'fast')\n"),
        })


def test_a_corrupt_record_with_allow_preexisting_tests_fails_closed(tmp_path):
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import (
        OptimizationAborted,
        _check_authored_tests_discriminate,
    )

    (tmp_path / "pre_build_tests.json").write_text("{not json")
    camp = {"optimization": {"build_checks": {"allow_preexisting_tests": True}}}
    with pytest.raises(OptimizationAborted, match="unreadable"):
        _check_authored_tests_discriminate(camp, tmp_path, [], 2)


def test_agent_code_rewriting_a_record_during_verify_changes_no_verdict(tmp_path, monkeypatch):
    """Records are read ONCE before any target code runs (A2). This test file
    is agent-authored code: when verify runs it, it rewrites the pre-build
    record to claim a behavioural pre-build failure. The verdict must still be
    the one the sealed record supports."""
    from orchestrator.optimize.stage_runner import OptimizationAborted

    wd = tmp_path / "vac"
    forged = json.dumps({"ran": [TEST_ID], "passed": [], "output_recorded": True,
                         "failure_kinds": {TEST_ID: "behavioral"}})
    test_src = (
        "import json, pathlib, mech\n"
        f"P = pathlib.Path({str(wd / 'pre_build_tests.json')!r})\n"
        "def test_mech():\n"
        f"    if P.exists(): P.write_text({forged!r})\n"
        "    assert mech.boost\n")
    with pytest.raises(OptimizationAborted, match="does not observe the mechanism"):
        _run(tmp_path, monkeypatch, {
            "mech.py": "def boost(x):\n    return 2 * x\n",
            "calc.py": "import mech\n\ndef scale(x):\n    return mech.boost(x)\n",
            "tests/test_mech.py": test_src,
        })


# ─── round 2, B1: honest builds in other frameworks are classified correctly ─

GO_V = """=== RUN   TestScale
    calc_test.go:9: got 3 want 6
--- FAIL: TestScale (0.00s)
FAIL
"""
GO_JSON = ('{"Action":"run","Test":"TestScale"}\n'
           '{"Action":"output","Test":"TestScale","Output":"    calc_test.go:9: got 3 want 6\\n"}\n'
           '{"Action":"fail","Test":"TestScale"}\n')
TESTIFY = """=== RUN   TestScale
    calc_test.go:11:
        \tError Trace:\tcalc_test.go:11
        \tError:      \tNot equal:
        \t            \texpected: 6
        \t            \tactual  : 3
--- FAIL: TestScale (0.00s)
"""
JEST = """  ● calc › scale doubles

    expect(received).toBe(expected) // Object.is equality

    Expected: 6
    Received: 3

  ● calc › other
"""
RUST = """---- tests::scale stdout ----
thread 'tests::scale' panicked at src/lib.rs:9:9:
assertion `left == right` failed
  left: 3
 right: 6
"""
PYTEST = """tests/t.py::test_scale FAILED
_____ test_scale _____
>       assert calc.scale(3) == 6
E       assert 3 == 6
E        +  where 3 = <function scale at 0x1>(3)
E        +    where <function scale at 0x1> = calc.scale
"""


@pytest.mark.parametrize("out,tid", [
    (GO_V, "calc_test.go::TestScale"),
    (GO_JSON, "calc_test.go::TestScale"),
    (TESTIFY, "calc_test.go::TestScale"),
    (JEST, "src/calc.test.js::scale doubles"),
    (PYTEST, "tests/t.py::test_scale"),
])
def test_honest_assertion_failures_are_behavioral_in_every_framework(out, tid):
    texts = failure_texts(out, [tid])
    assert failure_kind(texts.get(tid)) == "behavioral", texts


def test_rust_assertion_text_is_behavioral():
    assert failure_kind(RUST) == "behavioral"


def test_go_missing_symbol_is_still_absence():
    out = "# calc [calc.test]\n./calc_test.go:9:9: undefined: Boost\nFAIL calc [build failed]\n"
    assert failure_kind(out) == "absence"


# ─── round 2, B3: the stub-body mutant catches existence-only evasions ───────


@pytest.mark.parametrize("probe", [
    "assert 'fast' in dir(calc)",
    "assert 'fast' in vars(calc)",
    "assert 'fast' in calc.__dict__",
    "import inspect; assert any(n == 'fast' for n, _ in inspect.getmembers(calc))",
])
def test_an_existence_only_test_that_dodges_the_revert_mutant_is_caught(
        tmp_path, monkeypatch, probe):
    """Against the revert mutant these fail BY ASSERTION (calc has no `fast`),
    which reads as behavioural; with the body stubbed they still pass."""
    from orchestrator.optimize.stage_runner import OptimizationAborted

    with pytest.raises(OptimizationAborted, match="stubbed"):
        _run(tmp_path, monkeypatch, {
            "calc.py": "def scale(x):\n    return x\n\ndef fast(x):\n    return 2 * x\n",
            "tests/test_mech.py": f"import calc\n\ndef test_mech():\n    {probe}\n",
        })
    rec = json.loads((tmp_path / "vac" / "authored_tests.json").read_text())
    assert "calc.py:fast" in rec["mutant"]["stubbed"]



# ─── round 2, C2: a real run with no readable output fails closed ────────────


@pytest.mark.parametrize("extra", [{"verdicts_injected": False}, {}])
def test_a_real_pre_build_run_with_no_readable_output_fails_closed(tmp_path, extra):
    pre = {"ran": [TEST_ID], "passed": [], "failure_kinds": {TEST_ID: "unknown"},
           "output_recorded": False, **extra}
    with pytest.raises(ValueError, match="output was not recorded"):
        _check_direct(tmp_path, pre)


def test_a_failed_mutant_cleanup_is_logged_not_swallowed(tmp_path, monkeypatch, caplog):
    import logging

    from orchestrator.optimize import build_scope, test_vacuity

    monkeypatch.setattr(build_scope, "_git", lambda *a, **k: None)
    legacy = tmp_path / "gone"
    legacy.mkdir()
    (legacy / ".git").write_text("gitdir: /nowhere\n")    # a worktree-style mutant
    with caplog.at_level(logging.WARNING, logger="orchestrator.optimize.test_vacuity"):
        test_vacuity.remove_mutant(tmp_path, legacy)
    assert "could not remove mutant worktree" in caplog.text


def test_a_control_measurement_rewritten_during_verify_is_never_resealed(tmp_path, monkeypatch):
    """B3: agent code run at verify rewrites the build-written part of
    baseline_equivalence.json. What verify finally seals is the sealed
    in-memory copy, never the rewrite."""
    wd = tmp_path / "vac"
    test_src = (
        "import calc, json, pathlib\n"
        f"P = pathlib.Path({str(wd / 'baseline_equivalence.json')!r})\n"
        "def test_mech():\n"
        "    if P.exists():\n"
        "        d = json.loads(P.read_text()); d['tolerance_pct'] = 99.0\n"
        "        P.write_text(json.dumps(d))\n"
        "    assert calc.scale(3) == 6\n")
    _run(tmp_path, monkeypatch, {
        "mech.py": "def boost(x):\n    return 2 * x\n",
        "calc.py": "import mech\n\ndef scale(x):\n    return mech.boost(x)\n",
        "tests/test_mech.py": test_src,
    })
    from orchestrator.optimize import gate_records as gr
    assert json.loads((wd / "baseline_equivalence.json").read_text())["tolerance_pct"] != 99.0
    assert gr.check(wd, "baseline_equivalence.json") == "ok"


def test_confirm_build_part_refuses_a_rewritten_record(tmp_path):
    from orchestrator.optimize import gate_records as gr

    mem = {"levels": {"A": 1}, "pre": [1.0], "pre_mean": 1.0, "tolerance_pct": 5.0}
    (tmp_path / "baseline_equivalence.json").write_text(json.dumps({**mem, "tolerance_pct": 99}))
    with pytest.raises(gr.GateRecordError, match="changed during verify"):
        gr.confirm_build_part(tmp_path, {"baseline_equivalence.json": mem})
    (tmp_path / "baseline_equivalence.json").write_text(json.dumps({**mem, "post": [1.0]}))
    gr.confirm_build_part(tmp_path, {"baseline_equivalence.json": mem})
