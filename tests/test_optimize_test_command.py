"""``test_command``: its ceiling, its diagnostics, and the fact it is not a shell.

Two friction reports from one 13-factor campaign, fixed together because they
share a symptom. Both surfaced as::

    smoke: test command reported 0 test(s); 0/13 declared identifier(s) matched
    x 13 declared native_test(s) did not appear ... Check the identifier
      spelling, that the command selects them, and ...

  * #319 -- the command was KILLED by a hard-coded 900s ceiling the campaign
    could not raise. The empty-results path was shared between "ran and printed
    nothing parseable" and "never finished", and the message only described the
    former, so the author chased spelling, selection and output format in turn
    -- one full gate cycle each -- before reading the source. The partial output
    that would have said which test was running was ALSO discarded on POSIX:
    ``TimeoutExpired.stdout`` is bytes there even under ``text=True``.
  * #317 -- ``test_command`` is ``shlex.split``, not shell-run, while the guide
    called it a "shell command". So ``cd repo && pytest ...`` handed ``cd`` and
    ``&&`` to pytest as literal arguments, and the second smoke run reported the
    same 13 unmatched identifiers with no hint why.

Every assertion is on something a user sees (a smoke problem string, a verify
abort message, a validator error) or on an artifact (the persisted log, a
schema verdict). The "targets" are ``sh`` one-liners; no LLM is reachable.
"""
from __future__ import annotations

import shlex
from pathlib import Path

import jsonschema
import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from orchestrator.optimize import runner
from orchestrator.validate import validate_optimization_campaign

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "orchestrator" / "schemas" / "campaign.schema.yaml"


# --- fixtures ---------------------------------------------------------------

def _campaign(repo: Path, *, test_cmd: str, native_tests: list[str],
              **opt_over) -> dict:
    """A campaign with a test_command and no run_command.

    No ``run_command`` means ``--smoke`` stops after the test-command check,
    which is the only part under test here.
    """
    opt = {
        "response": {"primary": {"metric": "m", "direction": "maximize"}},
        "factors": [{
            "id": "F", "name": "flag", "type": "choice", "levels": ["0", "1"],
            "apply": "--flag={level}",
            "manipulation": {"observable": "applied.flag", "op": "==",
                             "value": "{level}"},
            "relations": [
                {"id": f"R{i}", "kind": "correctness", "statement": "s",
                 "native_test": t}
                for i, t in enumerate(native_tests)
            ],
        }],
        "stages": ["verify", "screen", "confirm"],
        "design": {"screen": {"resolution": 3}, "confirm": {"replicates": 1}},
        "test_command": test_cmd,
    }
    opt.update(opt_over)
    return {
        "kind": "optimization", "run_id": "tc",
        "research_question": "does the gate say why it failed?",
        "prompts": {"methodology_layer": "prompts/methodology",
                    "domain_adapter_layer": None},
        "target_system": {"name": "T", "description": "a test target",
                          "repo_path": str(repo)},
        "optimization": opt,
    }


def _slow_suite(tmp_path: Path, *, passes: list[str], sleep_sec: float) -> str:
    """A test command that reports some passes, then outlives its ceiling.

    The shape of the real failure: each relation drives a simulation, so the
    suite reports its first few tests and is still running the rest when the
    ceiling arrives.
    """
    script = tmp_path / "slow_suite.sh"
    lines = ["#!/bin/sh"] + [f"echo '{p} PASSED'" for p in passes]
    lines.append(f"sleep {sleep_sec}")
    lines += ["echo 'tests/test_late.py::test_never_reached PASSED'"]
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    return str(script)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _smoke(campaign: dict) -> list[str]:
    from orchestrator.cli import _smoke_check_optimization

    return _smoke_check_optimization(campaign)


# --- #319: a killed command is a budget problem and must say so -------------

def test_smoke_names_the_timeout_not_the_identifiers(tmp_path: Path):
    """The fix the friction report asked for, verbatim in substance.

    The old message offered spelling, selection and output format -- three
    wrong answers that each cost a gate cycle. A killed suite must be reported
    as killed, with the ceiling, the count it got through, and where to raise it.
    """
    repo = _repo(tmp_path)
    cmd = _slow_suite(
        tmp_path,
        passes=["tests/test_a.py::test_one", "tests/test_a.py::test_two"],
        sleep_sec=30,
    )
    campaign = _campaign(
        repo, test_cmd=cmd, test_timeout_sec=1,
        native_tests=["tests/test_a.py::test_one",
                      "tests/test_late.py::test_never_reached"],
    )
    problems = _smoke(campaign)
    joined = "\n".join(problems)
    assert "KILLED at the 1s timeout" in joined, problems
    assert "after reporting 2 test(s)" in joined, problems
    assert "budget problem, not an identifier problem" in joined, problems
    assert "optimization.test_timeout_sec" in joined, problems
    # And the wrong advice is gone: nothing here is a spelling problem.
    assert "identifier spelling" not in joined, problems
    # The message points at the saved partial output, which names the test
    # that was running when the ceiling arrived.
    saved = Path(joined.split("is saved in ", 1)[1].split(" ", 1)[0].rstrip("."))
    assert "tests/test_a.py::test_two PASSED" in saved.read_text()


def test_the_declared_ceiling_is_the_one_the_command_actually_gets(tmp_path: Path):
    """Enforced at the DECLARED value, in both directions.

    Only the failing half proves a ceiling exists; only the passing half proves
    it is the declared one rather than something smaller. A 2s suite killed at
    1s and completing under 10s pins it between the two.
    """
    repo = _repo(tmp_path)
    cmd = _slow_suite(tmp_path, passes=["tests/test_a.py::test_one"],
                      sleep_sec=2)
    declared = ["tests/test_a.py::test_one",
                "tests/test_late.py::test_never_reached"]

    killed = _smoke(_campaign(repo, test_cmd=cmd, native_tests=declared,
                              test_timeout_sec=1))
    assert any("KILLED at the 1s timeout" in p for p in killed), killed

    finished = _smoke(_campaign(repo, test_cmd=cmd, native_tests=declared,
                                test_timeout_sec=10))
    assert finished == [], finished


def test_an_undeclared_ceiling_defaults_to_900_seconds():
    """Absence keeps the pre-field behaviour: 900s, the old hard-coded value."""
    from orchestrator.optimize.stage_runner import resolve_test_timeout

    assert resolve_test_timeout({}) == 900
    assert resolve_test_timeout(None) == 900
    assert resolve_test_timeout({"test_timeout_sec": 2400}) == 2400
    # A hand-edited non-integer cannot reach here from a schema-valid campaign;
    # treated as absent rather than becoming a 0-second ceiling.
    assert resolve_test_timeout({"test_timeout_sec": "2400"}) == 900
    assert resolve_test_timeout({"test_timeout_sec": True}) == 900


def test_a_timeout_preserves_the_partial_output_in_the_log(tmp_path: Path):
    """The partial output is the most informative artifact of a killed run.

    It was silently discarded on POSIX: ``TimeoutExpired.stdout`` is bytes there
    even under ``text=True``, and the old code kept it only if it was a str.
    """
    log = tmp_path / "test_output.log"
    cmd = _slow_suite(tmp_path, passes=["tests/test_a.py::test_one"],
                      sleep_sec=30)
    result = runner.run_test_command(cmd, cwd=tmp_path, timeout=1, log_path=log)
    text = log.read_text()
    assert "TIMED OUT after 1s" in text
    assert "tests/test_a.py::test_one PASSED" in text, text
    # Fail-closed is unchanged: a killed suite certifies nothing, even for the
    # test that finished before the kill.
    assert dict(result) == {}


def test_verify_abort_on_a_killed_suite_names_the_timeout(tmp_path: Path, monkeypatch):
    """The production gate, not only --smoke, must say "killed".

    A verify abort ends the campaign, so its message is what an author reads
    first; repeating #319's misdiagnosis there would cost the same cycles.
    """
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "campaigns"))
    repo = _repo(tmp_path)
    cmd = _slow_suite(tmp_path, passes=["tests/test_a.py::test_one"],
                      sleep_sec=30)
    # 4s, not 1s: the partial-output assertion below needs the suite to have
    # printed its first line before the kill, which a loaded machine (the full
    # suite under -n 4) can delay past a 1s ceiling.
    campaign = _campaign(
        repo, test_cmd=cmd, test_timeout_sec=4,
        native_tests=["tests/test_a.py::test_one",
                      "tests/test_late.py::test_never_reached"],
    )
    work = setup_work_dir("tc", repo_path=str(repo), campaign=campaign)
    with pytest.raises(OptimizationAborted) as exc:
        run_stage(campaign, work, iteration=1, auto_approve=True)
    msg = str(exc.value)
    assert "KILLED at the 4s timeout" in msg, msg
    assert "optimization.test_timeout_sec" in msg, msg
    log = work / "runs" / "iter-1" / "test_output.log"
    assert "tests/test_a.py::test_one PASSED" in log.read_text()


@pytest.mark.parametrize("value,ok", [
    (1, True), (2400, True), (0, False), (-5, False), (1.5, False),
    ("900", False),
])
def test_schema_accepts_test_timeout_sec_symmetrically_with_run_timeout_sec(
    tmp_path: Path, value, ok,
):
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    campaign = _campaign(tmp_path, test_cmd="pytest -v",
                         native_tests=["t.py::test_x"], test_timeout_sec=value)
    if ok:
        jsonschema.validate(campaign, schema)
    else:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, schema)


# --- #317: when identifiers do not match, show what WAS observed ------------

def test_unmatched_identifiers_list_what_the_command_did_report(tmp_path: Path):
    """Declared-vs-observed turns a three-way guess into a one-line fix.

    Here a genuine typo: the declared name is close to one the command printed,
    and the message must show both so the difference is visible.
    """
    repo = _repo(tmp_path)
    campaign = _campaign(
        repo,
        test_cmd="sh -c 'echo tests/test_a.py::test_batching_width PASSED'",
        native_tests=["tests/test_a.py::test_batching_widht"],
    )
    problems = _smoke(campaign)
    joined = "\n".join(problems)
    assert "declared: tests/test_a.py::test_batching_widht" in joined, problems
    assert "observed: tests/test_a.py::test_batching_width" in joined, problems


def test_no_per_test_output_after_a_failing_exit_points_at_the_command(
    tmp_path: Path,
):
    """``cd repo && pytest`` is the #317 trap: pytest receives ``cd`` as a path.

    It exits non-zero having run nothing. That is a command problem, not an
    identifier problem, and the message must say the command reported no tests
    at all, its exit status, and that it is not run in a shell.
    """
    repo = _repo(tmp_path)
    campaign = _campaign(
        repo,
        # `sh -c 'exit 4'` stands in for pytest rejecting `cd` as a file arg.
        test_cmd="sh -c 'echo ERROR: file or directory not found: cd >&2; exit 4'",
        native_tests=["tests/test_a.py::test_one"],
    )
    problems = _smoke(campaign)
    joined = "\n".join(problems)
    assert "reported NO per-test results" in joined, problems
    assert "exited 4" in joined, problems
    assert "not run in a shell" in joined, problems
    assert "identifier spelling" not in joined, problems


def test_a_path_prefix_only_difference_is_named_with_the_fix():
    """Pytest prints node ids relative to its invocation.

    Reached only through ``explain_unmatched`` directly: the matcher already
    bridges a locator to the runner's name via the trailing ``::`` identifier,
    so a pure path-prefix difference does not produce a miss today. The hint is
    there so that the explanation stays right if a matcher ever compares more
    than the tail -- and it costs nothing when it does not fire.

    When a declared id and an observed id differ ONLY by a leading path, the
    explanation is never "spelling", and the message says what to change.
    General suffix matching was considered and rejected in #317 (two
    same-named tests in different directories would collide); this is
    diagnosis only.
    """
    text = runner.explain_unmatched(
        ["tests/test_config_levers.py::test_batching_width"],
        ["r2/tests/test_config_levers.py::test_batching_width_other",
         "test_config_levers.py::test_batching_width"],
    )
    assert "differ only by a path prefix" in text, text
    assert "relative to target_system.repo_path" in text, text
    assert "declare the identifier as the command prints it" in text, text


@settings(max_examples=60, deadline=None)
@given(
    prefix=st.lists(st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True),
                    min_size=1, max_size=3),
    path=st.from_regex(r"test_[a-z]{1,8}\.py::test_[a-z_]{1,10}", fullmatch=True),
)
def test_prefix_hint_is_symmetric_in_which_side_carries_the_prefix(prefix, path):
    """Metamorphic: swapping which side has the longer path keeps the verdict.

    An absolute-path invocation SHORTENS what pytest prints; running from a
    parent directory LENGTHENS it. Both are the same defect and both must be
    named as such.
    """
    longer = "/".join(prefix) + "/" + path
    a = runner.explain_unmatched([longer], [path])
    b = runner.explain_unmatched([path], [longer])
    assert "differ only by a path prefix" in a
    assert "differ only by a path prefix" in b


def test_no_prefix_hint_for_unrelated_identifiers():
    """The hint must not fire on a mere shared filename: that is a real miss."""
    text = runner.explain_unmatched(
        ["tests/test_a.py::test_one"], ["tests/test_a.py::test_two"],
    )
    assert "path prefix" not in text, text


# --- #317: test_command / run_command are argv, not shell -------------------

def _validated(tmp_path: Path, **opt_over) -> list[str]:
    campaign = _campaign(tmp_path, test_cmd="pytest -v",
                         native_tests=["t.py::test_x"], **opt_over)
    return validate_optimization_campaign(campaign)


def _shell_errors(errors: list[str]) -> list[str]:
    return [e for e in errors if "not run in a shell" in e]


@pytest.mark.parametrize("field", ["test_command", "run_command"])
@pytest.mark.parametrize("cmd,named", [
    ("cd /abs/r2 && python -m pytest tests/ -v", "&&"),
    ("pytest -v || true", "||"),
    ("pytest -v | tee out.log", "|"),
    ("make build; ./bench --json", ";"),
    ("pytest -v > out.log", ">"),
    ("./bench --json 2>/dev/null", ">"),
    ("./bench < input.json", "<"),
    ("./bench --seed `date +%s`", "`"),
    ("./bench --seed $(date +%s)", "$("),
    ('./bench --seed "$(date +%s)"', "$("),
    ("cd sim", "cd"),
    ("PYTHONPATH=src python bench.py", "PYTHONPATH=src"),
])
def test_shell_syntax_in_an_argv_command_is_an_error(tmp_path, field, cmd, named):
    errors = _shell_errors(_validated(tmp_path, **{field: cmd}))
    assert len(errors) == 1, errors
    err = errors[0]
    assert not err.startswith("WARN:"), err
    assert f"optimization.{field}" in err, err
    assert named in err, err
    assert "shlex.split" in err and "target_system.repo_path" in err, err
    assert "sh -c" in err, err


@pytest.mark.parametrize("cmd", [
    "sh -c 'cd sim && go test ./... -v'",            # a real shell, on purpose
    "bash -c \"pytest -v | tee out.log\"",
    "go test ./sim/kv/ -count=1 -json -run 'TestA|TestB'",  # quoted regex pipe
    "python -m pytest -k 'fast and not slow' -v",
    "./bench --filter 'a>b' --json",
    "find . -name x -exec echo {} \\;",            # escaped, not a separator
    "env PYTHONPATH=src python bench.py",
    "uv run --no-project --with pytest python -m pytest tests/test_x.py -v",
    "python3 -c 'import json;print(json.dumps({\"m\": 1}))'",
])
def test_argv_commands_that_merely_contain_metacharacters_are_accepted(tmp_path, cmd):
    """No false positives: quoted or escaped metacharacters reach argv intact."""
    for field in ("test_command", "run_command"):
        assert _shell_errors(_validated(tmp_path, **{field: cmd})) == []


def test_an_unparseable_command_is_reported_rather_than_crashing(tmp_path):
    errors = _validated(tmp_path, test_command="pytest -k 'unbalanced -v")
    assert any("optimization.test_command" in e and "shlex" in e
               for e in errors), errors


_ARG = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1,
    max_size=12,
)


@settings(max_examples=150, deadline=None)
@given(args=st.lists(_ARG, min_size=0, max_size=6))
def test_any_shlex_joined_argv_is_accepted(args):
    """Property: whatever the arguments contain, QUOTING them makes them safe.

    ``shlex.join`` is exactly the transformation that makes a string mean the
    argv it was built from, so the check must accept every such string. This is
    what pins "flag what is not shell-run" against over-eager substring rules.
    """
    cmd = shlex.join(["python", *args])
    campaign = _campaign(Path("/nonexistent"), test_cmd=cmd,
                         native_tests=["t.py::test_x"])
    assert _shell_errors(validate_optimization_campaign(campaign)) == []


@settings(max_examples=60, deadline=None)
@given(
    left=st.lists(_ARG, min_size=0, max_size=3),
    right=st.lists(_ARG, min_size=0, max_size=3),
    sep=st.sampled_from(["&&", "||", "|", ";"]),
)
def test_chaining_two_argvs_with_an_operator_is_always_flagged(left, right, sep):
    """Metamorphic partner of the property above: the same safe argvs, joined
    by an UNQUOTED operator, are always flagged -- the operator is the only
    thing that changed."""
    cmd = f"{shlex.join(['python', *left])} {sep} {shlex.join(['python', *right])}"
    campaign = _campaign(Path("/nonexistent"), test_cmd=cmd,
                         native_tests=["t.py::test_x"])
    errors = _shell_errors(validate_optimization_campaign(campaign))
    assert len(errors) == 1 and sep in errors[0], (cmd, errors)
