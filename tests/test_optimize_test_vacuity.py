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
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
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
    c["optimization"]["test_command"] = (
        f"{sys.executable} -m pytest -v -p no:cacheprovider tests")
    if build_checks:
        c["optimization"]["build_checks"] = build_checks
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
    assert len(wt.strip().splitlines()) == 1, wt


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
    ("E   ZeroDivisionError: division by zero", "behavioral"),
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
