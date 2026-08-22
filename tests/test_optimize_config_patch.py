"""Behavioral tests for the ``config_patch`` apply kind (the apply/measure seam).

``config_patch`` was schema-valid, documented, and rendered onto every
``ConfigRow`` by ``matrix.expand`` -- and then never read by anything that
launched a run. Every row of a design matrix whose factors used it silently
executed the BASELINE configuration while the design matrix, ``runs.jsonl``,
and the fitted response surface all looked real. That is the silent-wrong-
result class: found the hard way on a live campaign, at row 1 of 18, after a
full ``build`` stage, by the run-time manipulation predicate.

These tests are the oracle for the fix. They assert on FILES ON DISK (the
per-run patched copy's content, the author's original left untouched) and on
what the row records about itself -- never on which helper was called or what
argv looked like. No subprocess reaches an LLM; the "target" is a two-line
shell script that echoes the config file it was handed back as JSON, which is
the only way to prove the patch reached the thing that actually ran.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from orchestrator.optimize.config_patch import (
    ConfigPatchError,
    apply_pointer,
    materialize_patches,
    read_pointer,
)
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import render_apply
from orchestrator.optimize.runner import make_config_runner


# --- fixtures: a target whose whole job is to report the config it was given --

_ECHO_TARGET = """#!/bin/sh
# A stand-in for a real target: it reads the config file it was pointed at and
# echoes it back as the run's JSON observation. A campaign against this target
# can therefore PROVE whether the patch landed, which is exactly the question
# the config_patch defect answered wrongly. Uses the TEST interpreter rather
# than a bare `python3` (which on this machine has no yaml) so the YAML cases
# exercise the same path as the JSON ones.
"{interpreter}" - "$@" <<'EOFPY'
import json, sys, pathlib
# Find the config argument by scanning, not by position: the assembled command
# is the campaign's own run_command plus appended cli_args, so the config file's
# position is not fixed.
cand = [a for a in sys.argv[1:] if a.split("=")[-1].endswith((".json", ".yaml", ".yml"))]
raw = pathlib.Path(cand[-1].split("=")[-1]).read_text()
try:
    cfg = json.loads(raw)
except json.JSONDecodeError:
    import yaml
    cfg = yaml.safe_load(raw)
print(json.dumps({{"latency_ms": 1.0, "cfg": cfg}}))
EOFPY
"""


_FAILING_TARGET = """#!/bin/sh
# A target that reads the config it was handed and then FAILS. The failure
# path is where the patched copy is preserved, so it needs its own fixture:
# the copy must be attributable to a row precisely when the run went wrong.
cat "$2" >/dev/null
exit 3
"""


def _echo_target(tmp_path: Path) -> Path:
    script = tmp_path / "echo_target.sh"
    script.write_text(_ECHO_TARGET.format(interpreter=sys.executable))
    script.chmod(0o755)
    return script


def _patch_factor(*, path: str, pointer: str, levels, fid: str = "P1") -> dict:
    return {
        "id": fid, "name": "patched_knob", "type": "numeric" if isinstance(
            levels[0], (int, float),
        ) and not isinstance(levels[0], bool) else "choice",
        "levels": list(levels),
        "apply": {"kind": "config_patch", "path": path,
                  "pointer": pointer, "value": "{level}"},
        "manipulation": {"observable": f"applied.{fid}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": "R1", "kind": "correctness",
                       "statement": "the patched config round-trips",
                       "native_test": "tests/test_p.py::test_patch"}],
    }


class _Row:
    """The minimal duck-typed row ``make_config_runner``'s closure consumes."""

    def __init__(self, levels: dict, apply: dict, row_index: int = 0):
        self.row_index = row_index
        self.replicate = 0
        self.role = "corner"
        self.levels = dict(levels)
        self.apply = dict(apply)


# --- 1. the patch reaches the command; the author's original is untouched ----

def test_patch_reaches_the_running_command_and_never_mutates_the_original(
    tmp_path: Path,
):
    original = tmp_path / "engine.json"
    original.write_text(json.dumps(
        {"cache": {"cpu_bytes_to_use": 85899345920}}, indent=2,
    ))
    before = original.read_text()

    factors = parse_factors([_patch_factor(
        path="engine.json", pointer="/cache/cpu_bytes_to_use",
        levels=[42949672960, 85899345920],
    )])
    row = _Row({"P1": 42949672960},
               render_apply(factors, {"P1": 42949672960}))

    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.json",
        cwd=tmp_path, metric_path="latency_ms",
    )
    obs = run(row)

    assert obs["cfg"]["cache"]["cpu_bytes_to_use"] == 42949672960, (
        "the command must have read the PATCHED copy, not the baseline file -- "
        "reading the baseline is the silent-wrong-result defect itself"
    )
    assert original.read_text() == before, (
        "the campaign author's file must never be mutated: rows run "
        "concurrently in principle, so a shared mutated file is both a race "
        "and a cross-row contamination channel"
    )


# --- 2. the value's TYPE survives the round-trip -----------------------------

@pytest.mark.parametrize("level,expected_type", [
    (42949672960, int),
    (0.25, float),
    (True, bool),
    ("arc", str),
])
def test_patched_value_keeps_its_declared_type(tmp_path: Path, level, expected_type):
    """A level that arrives as the string "42949672960" where the target expects
    an int is the same silent-wrong-config failure in a new costume."""
    original = tmp_path / "engine.json"
    original.write_text(json.dumps({"knob": None}))

    raw = _patch_factor(path="engine.json", pointer="/knob", levels=[level, level])
    raw["type"] = "choice" if isinstance(level, (bool, str)) else "numeric"
    factors = parse_factors([raw])
    row = _Row({"P1": level}, render_apply(factors, {"P1": level}))

    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.json",
        cwd=tmp_path, metric_path="latency_ms",
    )
    got = run(row)["cfg"]["knob"]
    assert type(got) is expected_type, f"{got!r} came back as {type(got).__name__}"
    assert got == level


# --- 3. two rows get two files and cannot contaminate each other -------------

def test_two_rows_get_independent_patched_files(tmp_path: Path):
    original = tmp_path / "engine.yaml"
    original.write_text(yaml.safe_dump({"policy": "lru"}))

    raw = _patch_factor(path="engine.yaml", pointer="/policy",
                        levels=["lru", "arc"])
    raw["type"] = "choice"
    factors = parse_factors([raw])

    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.yaml",
        cwd=tmp_path, metric_path="latency_ms",
    )
    row_lru = _Row({"P1": "lru"}, render_apply(factors, {"P1": "lru"}), row_index=0)
    row_arc = _Row({"P1": "arc"}, render_apply(factors, {"P1": "arc"}), row_index=1)

    obs_arc = run(row_arc)
    obs_lru = run(row_lru)

    assert obs_arc["cfg"]["policy"] == "arc"
    assert obs_lru["cfg"]["policy"] == "lru", (
        "row 0 must not read row 1's patched file -- one shared temp path would "
        "make the second row's config leak into the first's measurement"
    )
    realized_arc = row_arc.apply["applied_patches"]["P1"]["materialized_path"]
    realized_lru = row_lru.apply["applied_patches"]["P1"]["materialized_path"]
    assert realized_arc != realized_lru


# --- 4. a path absent from run_command is LOUD, never a silent no-op ---------

def test_path_absent_from_run_command_is_a_loud_error(tmp_path: Path):
    """The whole defect class is 'the patch could not possibly take effect and
    nothing said so'. A path the command never mentions is exactly that."""
    (tmp_path / "engine.json").write_text(json.dumps({"knob": 1}))
    factors = parse_factors([_patch_factor(
        path="engine.json", pointer="/knob", levels=[1, 2],
    )])
    row = _Row({"P1": 2}, render_apply(factors, {"P1": 2}))

    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --no-config-here",
        cwd=tmp_path, metric_path="latency_ms",
    )
    with pytest.raises(RuntimeError, match="engine.json"):
        run(row)


# --- 5. JSON and YAML both work; an unsupported extension errors -------------

def test_yaml_config_is_patched_in_place_of_its_original(tmp_path: Path):
    original = tmp_path / "engine.yml"
    original.write_text(yaml.safe_dump({"cache": {"policy": "lru", "size": 10}}))

    raw = _patch_factor(path="engine.yml", pointer="/cache/policy",
                        levels=["lru", "arc"])
    raw["type"] = "choice"
    factors = parse_factors([raw])
    row = _Row({"P1": "arc"}, render_apply(factors, {"P1": "arc"}))

    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.yml",
        cwd=tmp_path, metric_path="latency_ms",
    )
    cfg = run(row)["cfg"]
    assert cfg["cache"]["policy"] == "arc"
    assert cfg["cache"]["size"] == 10, "unpatched keys must survive verbatim"


def test_unsupported_extension_is_a_loud_error(tmp_path: Path):
    (tmp_path / "engine.toml").write_text("knob = 1\n")
    with pytest.raises(ConfigPatchError, match="extension"):
        materialize_patches(
            [{"path": "engine.toml", "pointer": "/knob", "value": 2}],
            cwd=tmp_path, temp_dir=tmp_path / "t",
        )


def test_missing_config_file_is_a_loud_error(tmp_path: Path):
    with pytest.raises(ConfigPatchError, match="does not exist"):
        materialize_patches(
            [{"path": "absent.json", "pointer": "/knob", "value": 2}],
            cwd=tmp_path, temp_dir=tmp_path / "t",
        )


# --- 6. the realized patch is recorded next to applied_args / applied_env ----

def test_realized_patch_is_recorded_on_the_row(tmp_path: Path):
    original = tmp_path / "engine.json"
    original.write_text(json.dumps({"cache": {"policy": "lru"}}))

    raw = _patch_factor(path="engine.json", pointer="/cache/policy",
                        levels=["lru", "arc"])
    raw["type"] = "choice"
    factors = parse_factors([raw])
    row = _Row({"P1": "arc"}, render_apply(factors, {"P1": "arc"}))

    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.json",
        cwd=tmp_path, metric_path="latency_ms",
    )
    run(row)

    recorded = row.apply["applied_patches"]
    assert list(recorded) == ["P1"], "keyed by factor id, not a list"
    entry = recorded["P1"]
    assert entry["path"] == "engine.json"
    assert entry["pointer"] == "/cache/policy"
    assert entry["value"] == "arc"
    assert Path(entry["materialized_path"]).name.endswith(".json")


def test_applied_patches_is_addressable_by_a_real_manipulation_predicate(
    tmp_path: Path,
):
    """``applied_args`` and ``applied_env`` are already addressable by a
    manipulation predicate; the realized patch must be too, or a file-configured
    target that does not echo its config back has no truthful check available.

    ROUTED THROUGH ``predicates.evaluate``, not plain subscripting. Asserting
    ``scope["applied_patches"][0]["value"] == "arc"`` proves only that a key is
    present in a dict -- and a LIST-shaped record passes that while being
    addressable by nothing: ``predicates._resolve`` walks dotted paths through
    dicts only, there is no list-index token, and ``OPS`` has no ``contains``.
    So ``applied_patches.0.value`` resolves to missing and fails EVERY row,
    silently, because the design pre-flight treats an ``applied_patches`` root
    as "this will exist at check time"."""
    from orchestrator.optimize import predicates
    from orchestrator.optimize.runner import _applied_namespace

    original = tmp_path / "engine.json"
    original.write_text(json.dumps({"cache": {"policy": "lru"}}))
    raw = _patch_factor(path="engine.json", pointer="/cache/policy",
                        levels=["lru", "arc"])
    raw["type"] = "choice"
    raw["manipulation"] = {"observable": "applied_patches.P1.value",
                           "op": "==", "value": "{level}"}
    factors = parse_factors([raw])
    row = _Row({"P1": "arc"}, render_apply(factors, {"P1": "arc"}))

    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.json",
        cwd=tmp_path, metric_path="latency_ms",
    )
    run(row)

    verdict = predicates.evaluate(
        factors[0].manipulation, _applied_namespace(row), level="arc",
    )
    assert verdict.ok, verdict.detail
    assert not verdict.missing

    # And the negative: the level the row did NOT run must not satisfy it.
    verdict = predicates.evaluate(
        factors[0].manipulation, _applied_namespace(row), level="lru",
    )
    assert not verdict.ok


def test_a_config_patch_factor_can_pass_its_manipulation_check_end_to_end(
    tmp_path: Path,
):
    """The whole point of the namespace: a full ``execute_design`` row whose
    only evidence the lever engaged is ``applied_patches`` must come back
    ``complete``, not ``failed`` with "the target did not emit it"."""
    from orchestrator.optimize.matrix import ConfigRow
    from orchestrator.optimize.runner import execute_design

    (tmp_path / "engine.json").write_text(json.dumps({"cache": {"policy": "lru"}}))
    raw = _patch_factor(path="engine.json", pointer="/cache/policy",
                        levels=["lru", "arc"])
    raw["type"] = "choice"
    raw["manipulation"] = {"observable": "applied_patches.P1.value",
                           "op": "==", "value": "{level}"}
    factors = parse_factors([raw])
    run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.json",
        cwd=tmp_path, metric_path="latency_ms",
    )
    row = ConfigRow(row_index=0, levels={"P1": "arc"}, role="corner",
                    replicate=0, apply=render_apply(factors, {"P1": "arc"}))
    outcomes = execute_design(
        [row], runner=run, response_spec={}, invariants=[], factors=factors,
    )
    assert outcomes[0].status == "complete", outcomes[0].error
    assert all(v["ok"] for v in outcomes[0].manipulation)


# --- 7. RFC 6901 pointer mechanics ------------------------------------------

def test_pointer_supports_array_indices_and_escapes():
    doc = {"a~b": {"c/d": [{"x": 1}, {"x": 2}]}}
    # ~0 is a literal '~', ~1 is a literal '/'
    assert read_pointer(doc, "/a~0b/c~1d/1/x") == 2
    patched = apply_pointer(doc, "/a~0b/c~1d/1/x", 99)
    assert patched["a~b"]["c/d"][1]["x"] == 99
    assert doc["a~b"]["c/d"][1]["x"] == 2, "apply_pointer must not mutate its input"
    assert patched["a~b"]["c/d"][0]["x"] == 1, "siblings must survive verbatim"


def test_pointer_that_names_nothing_is_a_loud_error():
    with pytest.raises(ConfigPatchError, match="pointer"):
        apply_pointer({"a": {"b": 1}}, "/a/nope/deeper", 1)


def test_empty_pointer_replaces_the_whole_document():
    assert apply_pointer({"a": 1}, "", {"b": 2}) == {"b": 2}


def test_pointer_must_start_with_a_slash():
    with pytest.raises(ConfigPatchError, match="pointer"):
        apply_pointer({"a": 1}, "a", 2)


# --- 8. cleanup: the temp copies do not accumulate under the run's log dir ---

def test_materialized_copies_live_under_the_supplied_temp_dir(tmp_path: Path):
    (tmp_path / "engine.json").write_text(json.dumps({"knob": 1}))
    temp_dir = tmp_path / "patched"
    realized = materialize_patches(
        [{"path": "engine.json", "pointer": "/knob", "value": 7}],
        cwd=tmp_path, temp_dir=temp_dir,
    )
    materialized = Path(realized[0]["materialized_path"])
    assert temp_dir in materialized.parents
    assert json.loads(materialized.read_text())["knob"] == 7


# --- 9. --smoke must not pass a config_patch campaign whose patch is dropped --

def _smoke_campaign(tmp_path: Path, *, run_command: str) -> dict:
    """A minimal ``kind: optimization`` campaign whose only factor is a patch."""
    (tmp_path / "engine.json").write_text(json.dumps({"cache": {"policy": "lru"}}))
    target = _echo_target(tmp_path)
    return {
        "kind": "optimization",
        "research_question": "Does the cache policy matter?",
        "target_system": {"name": "echo", "description": "Echoes its config.",
                          "repo_path": str(tmp_path)},
        "prompts": {"methodology_layer": "prompts/methodology"},
        "optimization": {
            "run_command": run_command.format(target=target),
            "response": {"primary": {"metric": "latency_ms",
                                     "direction": "minimize"}},
            "factors": [{
                "id": "P1", "name": "policy", "type": "choice",
                "levels": ["arc", "lru"],
                "apply": {"kind": "config_patch", "path": "engine.json",
                          "pointer": "/cache/policy", "value": "{level}"},
                "manipulation": {"observable": "applied.P1", "op": "==",
                                 "value": "{level}"},
                "relations": [{"id": "R1", "kind": "correctness",
                               "statement": "the patched config round-trips",
                               "native_test": "tests/t.py::test_patch"}],
            }],
            "design": {"screen": {"resolution": 3, "center_points": 0},
                       "confirm": {"replicates": 2}, "max_runs": 8},
        },
    }


def test_smoke_reports_a_config_patch_that_never_reached_the_target(
    tmp_path: Path, monkeypatch,
):
    """The defect's signature under --smoke: the probe run SUCCEEDS (exit 0,
    parseable JSON, objective metric present) while measuring the baseline. So
    smoke must check the patched file's contents, not just that the run worked."""
    from orchestrator.cli import _smoke_check_optimization
    from orchestrator.optimize import config_patch as cp

    campaign = _smoke_campaign(
        tmp_path, run_command="sh {target} --config engine.json",
    )
    assert _smoke_check_optimization(campaign) == []

    # Neuter the materialization the way the original defect did: the command
    # keeps pointing at the author's unpatched file. Everything else -- exit
    # code, JSON shape, objective metric -- is unchanged, which is exactly why
    # the old smoke check passed.
    monkeypatch.setattr(cp, "rewrite_command", lambda cmd, realized: list(cmd))
    problems = _smoke_check_optimization(campaign)
    assert any("config_patch" in p and "/cache/policy" in p for p in problems), (
        f"smoke must catch a dropped config_patch; got {problems!r}"
    )


def test_smoke_reports_a_config_patch_whose_path_the_command_never_names(
    tmp_path: Path,
):
    from orchestrator.cli import _smoke_check_optimization

    campaign = _smoke_campaign(tmp_path, run_command="sh {target} --no-config")
    problems = _smoke_check_optimization(campaign)
    assert any("engine.json" in p for p in problems), problems


def test_smoke_leaves_no_patched_copies_behind(tmp_path: Path, monkeypatch):
    """The probe's materialized copies are diagnostics for one command, not
    campaign artifacts; validate must not accumulate them across invocations.

    Counts FILES anywhere under the temp root, not just the wrapper directory.
    Globbing only ``nous-smoke-*`` cannot fail for the copies it is named after:
    those land INSIDE that wrapper, so deleting the cleanup entirely still leaves
    the glob unchanged as long as ``mkdtemp`` is called once."""
    import tempfile as _tempfile
    from orchestrator.cli import _smoke_check_optimization

    campaign = _smoke_campaign(
        tmp_path, run_command="sh {target} --config engine.json",
    )
    # PRIVATE TEMP ROOT, not the shared one. The assertion below is a
    # before/after set difference over `nous-*` in the temp root, so it is only
    # sound if nothing ELSE writes there during the call. On the shared system
    # temp dir that does not hold: `runner._materialise` creates
    # `nous-config-patch-*` there for every patched row, so any other test
    # exercising a config-patch row -- in this file, in another file, or in a
    # parallel xdist worker -- made this test fail with leaks it did not cause.
    # Observed exactly that: three live `nous-config-patch-*` dirs from unrelated
    # runs, and a failure that vanished when run alone.
    #
    # Redirecting TMPDIR keeps the check's real content (nothing is left behind)
    # while making it independent of the rest of the suite. Narrowing the glob to
    # `nous-smoke-*` would NOT work, and the docstring above says why: those
    # copies land inside the wrapper, so the glob would stay unchanged even if the
    # cleanup were deleted outright.
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmproot"))
    (tmp_path / "tmproot").mkdir()
    _tempfile.tempdir = None          # force re-read of TMPDIR
    root = Path(_tempfile.gettempdir())
    assert root == tmp_path / "tmproot", root
    before = {
        str(f) for d in root.glob("nous-*") for f in d.rglob("*") if f.is_file()
    } | {str(d) for d in root.glob("nous-*")}
    assert _smoke_check_optimization(campaign) == []
    after = {
        str(f) for d in root.glob("nous-*") for f in d.rglob("*") if f.is_file()
    } | {str(d) for d in root.glob("nous-*")}
    assert after == before, f"leaked: {sorted(after - before)}"


# --- 13. the copies are kept for a FAILED row only, and named by row ---------

def test_a_failed_row_keeps_its_patched_config_named_by_row(tmp_path: Path):
    """A failed row's exact configuration is what a campaign author needs, and
    ``_dump_failed_run``'s precedent is a row-keyed filename. A successful row's
    configuration is reproducible from the pre-registered matrix, so keeping it
    would only leave ~90 unattributed copies in a screen's iteration dir."""
    from orchestrator.optimize.matrix import ConfigRow

    (tmp_path / "engine.json").write_text(json.dumps({"cache": {"policy": "lru"}}))
    raw = _patch_factor(path="engine.json", pointer="/cache/policy",
                        levels=["lru", "arc"])
    raw["type"] = "choice"
    factors = parse_factors([raw])
    logs = tmp_path / "logs" / "failed_runs"
    kept = tmp_path / "logs" / "patched_configs"

    ok_run = make_config_runner(
        f"sh {_echo_target(tmp_path)} --config engine.json",
        cwd=tmp_path, metric_path="latency_ms", log_dir=logs,
    )
    ok_run(_Row({"P1": "arc"}, render_apply(factors, {"P1": "arc"})))
    assert not kept.exists(), "a successful row must not leave a copy behind"

    failing = tmp_path / "failing_target.sh"
    # Names the config file as an argument (so the rewrite applies) and then
    # exits non-zero, which is the shape a real target failure takes.
    failing.write_text(_FAILING_TARGET)
    failing.chmod(0o755)
    bad_run = make_config_runner(
        f"sh {failing} --config engine.json",
        cwd=tmp_path, metric_path="latency_ms", log_dir=logs,
    )
    row = ConfigRow(row_index=7, levels={"P1": "arc"}, role="corner",
                    replicate=0, apply=render_apply(factors, {"P1": "arc"}))
    with pytest.raises(RuntimeError, match="exited 3"):
        bad_run(row)

    saved = sorted(kept.rglob("engine.json"))
    assert len(saved) == 1, f"expected one preserved copy, got {saved}"
    assert "row-7" in str(saved[0]), (
        f"the copy must be attributable to its row; got {saved[0]}"
    )
    assert json.loads(saved[0].read_text())["cache"]["policy"] == "arc"


# --- 10. path-boundary edge cases in the command rewrite ---------------------

def test_nested_paths_do_not_swallow_each_other(tmp_path: Path):
    """``engine.json`` is a substring of ``sub/engine.json``. With a bare
    substring test, whichever path is processed first consumes the other's token
    and the second then reports "does not appear anywhere in the assembled run
    command" for a command that plainly names it. Verified directly before the
    match was anchored to an argument boundary."""
    from orchestrator.optimize import config_patch as cp

    (tmp_path / "engine.json").write_text(json.dumps({"k": 1}))
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "engine.json").write_text(json.dumps({"k": 1}))

    realized = cp.materialize_patches(
        [{"path": "engine.json", "pointer": "/k", "value": 9},
         {"path": "sub/engine.json", "pointer": "/k", "value": 8}],
        cwd=tmp_path, temp_dir=tmp_path / "t",
    )
    for cmd in (["bench", "--a", "engine.json", "--b", "sub/engine.json"],
                ["bench", "--a=engine.json", "--b=sub/engine.json"]):
        got = cp.rewrite_command(cmd, realized)
        values = [
            json.loads(Path(tok.split("=")[-1]).read_text())["k"]
            for tok in got if tok.endswith(".json")
        ]
        assert values == [9, 8], f"{cmd} rewrote to {got}"


def test_a_path_that_is_only_the_tail_of_another_path_is_not_a_match(
    tmp_path: Path,
):
    """``other/engine.json`` must not satisfy a factor declaring
    ``engine.json``: the run would read a file the campaign never named."""
    from orchestrator.optimize import config_patch as cp

    (tmp_path / "engine.json").write_text(json.dumps({"k": 1}))
    realized = cp.materialize_patches(
        [{"path": "engine.json", "pointer": "/k", "value": 3}],
        cwd=tmp_path, temp_dir=tmp_path / "t",
    )
    with pytest.raises(ConfigPatchError, match="engine.json"):
        cp.rewrite_command(["bench", "--cfg", "other/engine.json"], realized)


def test_an_absolute_path_is_patched_and_substituted(tmp_path: Path):
    from orchestrator.optimize import config_patch as cp

    source = tmp_path / "engine.json"
    source.write_text(json.dumps({"k": 1}))
    realized = cp.materialize_patches(
        [{"path": str(source), "pointer": "/k", "value": 5}],
        cwd=tmp_path, temp_dir=tmp_path / "t",
    )
    got = cp.rewrite_command(["bench", "--config", str(source)], realized)
    assert json.loads(Path(got[-1]).read_text())["k"] == 5
    assert json.loads(source.read_text())["k"] == 1


def test_a_symlinked_config_is_read_through_and_the_target_is_untouched(
    tmp_path: Path,
):
    """A repo that symlinks its config into place is ordinary; the copy must
    come from what the link resolves to, and writing must not follow it back."""
    from orchestrator.optimize import config_patch as cp

    real = tmp_path / "engine.json"
    real.write_text(json.dumps({"k": 1}))
    (tmp_path / "link.json").symlink_to(real)
    realized = cp.materialize_patches(
        [{"path": "link.json", "pointer": "/k", "value": 7}],
        cwd=tmp_path, temp_dir=tmp_path / "t",
    )
    assert json.loads(Path(realized[0]["materialized_path"]).read_text())["k"] == 7
    assert json.loads(real.read_text())["k"] == 1


# --- 11. leaves that exist but hold nothing -----------------------------------

def test_a_null_or_empty_leaf_is_a_legitimate_patch_target(tmp_path: Path):
    """``policy:`` with no value is an ordinary way to write "the target's
    default here", and it is exactly the field a campaign wants to vary. It
    EXISTS, so the no-create-structure rule must not reject it."""
    (tmp_path / "a.json").write_text(json.dumps({"k": None}))
    realized = materialize_patches(
        [{"path": "a.json", "pointer": "/k", "value": 5}],
        cwd=tmp_path, temp_dir=tmp_path / "t",
    )
    assert json.loads(Path(realized[0]["materialized_path"]).read_text())["k"] == 5

    (tmp_path / "b.yaml").write_text("cache:\n  policy:\n")
    realized = materialize_patches(
        [{"path": "b.yaml", "pointer": "/cache/policy", "value": "arc"}],
        cwd=tmp_path, temp_dir=tmp_path / "t2",
    )
    doc = yaml.safe_load(Path(realized[0]["materialized_path"]).read_text())
    assert doc["cache"]["policy"] == "arc"


def test_an_empty_config_document_is_a_loud_error(tmp_path: Path):
    """``yaml.safe_load("")`` is ``None``; patching it would produce a file the
    target's own parser has never seen a valid shape of."""
    (tmp_path / "c.yaml").write_text("")
    with pytest.raises(ConfigPatchError, match="names nothing"):
        materialize_patches(
            [{"path": "c.yaml", "pointer": "/k", "value": 1}],
            cwd=tmp_path, temp_dir=tmp_path / "t",
        )
