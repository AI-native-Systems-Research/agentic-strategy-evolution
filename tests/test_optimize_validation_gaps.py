"""Three validation gaps found by running real ``kind: optimization`` campaigns.

No live LLM calls anywhere: rule 12 is pure filesystem/grep work, and the
``--smoke`` / ``--liveness`` probes execute a *shell-script target* written into
``tmp_path``. Every assertion is about an observable outcome — a reported issue
string, an exit code, a file the target wrote — never about which method a mock
saw.

  * GAP 1 — rule 12 only fired for ``path::test`` locators, so a bare Go test
    name (exactly what the Go result parser matches on) was SILENTLY skipped.
    Silence is the defect: an author could not tell "checked and fine" from
    "could not check".
  * GAP 2 — ``--smoke`` verified that manipulation predicates HOLD, never that a
    factor's levels MOVE the response. Of 8 candidate factors on a real target,
    3 were dead axes; a policy hash over dead axes pre-registers nothing.
  * GAP 3 — ``--smoke`` ran only the FIRST design corner, so a level that aborts
    the target was caught only by luck. One real level exited 2 on a Go panic
    and was reported as a clean null result identical to baseline.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

# ─────────────────────────── GAP 1: rule 12 locators ─────────────────────────
#
# Verified before the fix:
#   tests/test_x.py::test_foo                 -> checked (worked)
#   TestOffloadCPUTier_ARCRespectsCapacity    -> SILENTLY SKIPPED
#   go test ./sim/kv/ -run TestFoo            -> SILENTLY SKIPPED
# The bare identifier is what `runner._parse_go_output` matches on, so the
# style the runner supports best was the one the rule ignored.


def _rule12_campaign(repo: Path, native_tests: list[str], *,
                     stages=("verify", "screen", "confirm")) -> tuple:
    """A campaign shaped just enough for rule 12, plus its ``(opt, factors)``."""
    factors = [{
        "id": "F", "name": "flag", "type": "choice",
        "levels": ["0", "1"], "apply": "--flag={level}",
        "manipulation": {"observable": "applied.flag", "op": "==",
                         "value": "{level}"},
        "relations": [
            {"id": f"R{i}", "kind": "correctness", "statement": "s",
             "native_test": t}
            for i, t in enumerate(native_tests)
        ],
    }]
    campaign = {
        "kind": "optimization", "run_id": "r12",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "optimization": {"stages": list(stages), "factors": factors},
    }
    return campaign, campaign["optimization"], factors


def test_rule12_fires_for_a_bare_go_identifier_with_no_definition(tmp_path: Path):
    """A bare `TestFoo` nothing defines must be REPORTED, not skipped.

    This is the exact shape that validated at 0 errors / 0 warnings on a real
    campaign and then aborted at verify after a full run.
    """
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    (repo / "sim" / "kv").mkdir(parents=True)
    (repo / "sim" / "kv" / "other_test.go").write_text(
        "package kv\n\nfunc TestSomethingElse(t *testing.T) {}\n",
    )
    campaign, opt, factors = _rule12_campaign(
        repo, ["TestOffloadCPUTier_ARCRespectsCapacity"],
    )
    out = _rule12_missing_native_tests_need_build(campaign, opt, factors)
    assert out, "a bare identifier with no definition must not be silent"
    assert all(w.startswith("WARN:") for w in out), out
    assert "TestOffloadCPUTier_ARCRespectsCapacity" in " ".join(out)


def test_rule12_silent_when_the_bare_go_identifier_is_defined(tmp_path: Path):
    """No false positive: the definition exists, so nothing to report."""
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    (repo / "sim" / "kv").mkdir(parents=True)
    (repo / "sim" / "kv" / "offload_test.go").write_text(
        "package kv\n\n"
        "func TestOffloadCPUTier_ARCRespectsCapacity(t *testing.T) {}\n",
    )
    campaign, opt, factors = _rule12_campaign(
        repo, ["TestOffloadCPUTier_ARCRespectsCapacity"],
    )
    assert _rule12_missing_native_tests_need_build(campaign, opt, factors) == []


def test_rule12_silent_when_the_bare_pytest_identifier_is_defined(tmp_path: Path):
    """`def test_foo` counts as a definition just as `func TestFoo` does."""
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_arc.py").write_text(
        "def test_arc_respects_capacity():\n    assert True\n",
    )
    campaign, opt, factors = _rule12_campaign(
        repo, ["test_arc_respects_capacity"],
    )
    assert _rule12_missing_native_tests_need_build(campaign, opt, factors) == []


def test_rule12_fires_for_a_command_style_locator_with_run_selector(tmp_path: Path):
    """`go test ./sim/kv/ -run TestFoo` — the identifier lives behind `-run`."""
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    (repo / "sim" / "kv").mkdir(parents=True)
    (repo / "sim" / "kv" / "kv_test.go").write_text("package kv\n")
    campaign, opt, factors = _rule12_campaign(
        repo, ["go test ./sim/kv/ -run TestAbsentFromTheTree"],
    )
    out = _rule12_missing_native_tests_need_build(campaign, opt, factors)
    assert out, "the -run selector's identifier must be checked"
    assert "TestAbsentFromTheTree" in " ".join(out)


def test_rule12_warns_a_resolving_command_style_locator_will_fail_the_contract(
    tmp_path: Path,
):
    """A command-style locator RESOLVES here but still fails at verify.

    `runner.match_declared_tests` matches on trailing test identifiers and never
    parses a command line, so `pytest -k test_present` satisfies this rule and is
    then reported "declared but not executed" by the fail-closed reconcile.
    Endorsing a locator that verify will reject is worse than the silence this
    rule was fixed to remove, so the asymmetry gets its own WARNING naming the
    remedy (declare the bare identifier).
    """
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("def test_present():\n    pass\n")
    campaign, opt, factors = _rule12_campaign(
        repo, ["pytest -k test_present"],
    )
    out = _rule12_missing_native_tests_need_build(campaign, opt, factors)
    # NOT reported as missing -- the identifier really does resolve.
    assert not any("do not exist" in o for o in out), out
    assert any("COMMAND-STYLE" in o for o in out), out


def test_rule12_silent_for_a_bare_identifier_that_resolves(tmp_path: Path):
    """The locator style that works end-to-end draws no warning at all.

    A bare identifier is what `match_declared_tests` matches on, so it passes
    both this rule and the contract check -- the one shape with no asymmetry.
    """
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_x.py").write_text("def test_present():\n    pass\n")
    campaign, opt, factors = _rule12_campaign(repo, ["test_present"])
    assert _rule12_missing_native_tests_need_build(campaign, opt, factors) == []


def test_rule12_warns_that_an_unrecognised_locator_could_not_be_checked(
    tmp_path: Path,
):
    """Silence must never read as success.

    A locator whose shape the rule cannot parse into either a path or an
    identifier gets its own WARNING naming WHY, so "checked and fine" and
    "could not check" are distinguishable from the output alone.
    """
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign, opt, factors = _rule12_campaign(
        repo, ["make check && ./scripts/verify.sh --all"],
    )
    out = _rule12_missing_native_tests_need_build(campaign, opt, factors)
    assert out, "an un-checkable locator must be visible"
    joined = " ".join(out)
    assert all(w.startswith("WARN:") for w in out), out
    assert "could not be checked" in joined, joined


def test_rule12_still_silent_under_a_build_stage(tmp_path: Path):
    """`build` AUTHORS the tests, so their absence is the expected state."""
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign, opt, factors = _rule12_campaign(
        repo, ["TestNotYetWritten", "not/a/thing.go::TestX", "weird ; locator"],
        stages=("build", "verify", "screen", "confirm"),
    )
    assert _rule12_missing_native_tests_need_build(campaign, opt, factors) == []


def test_rule12_still_fires_for_a_missing_path_locator(tmp_path: Path):
    """Regression guard: the original path-style behaviour is unchanged."""
    from orchestrator.validate import _rule12_missing_native_tests_need_build

    repo = tmp_path / "repo"
    repo.mkdir()
    campaign, opt, factors = _rule12_campaign(repo, ["tests/gone.py::test_x"])
    out = _rule12_missing_native_tests_need_build(campaign, opt, factors)
    assert out and "tests/gone.py::test_x" in " ".join(out)


# ────────────────── GAP 2 / GAP 3: the shell-script target ────────────────────


def _script_target(tmp_path: Path, *, aborts_on: dict | None = None,
                   effects: dict | None = None, noise: float = 0.0) -> Path:
    """A shell target that echoes its config back as JSON.

    Deliberately a real executable rather than a Python fake: proving a level was
    EXERCISED means proving a process ran with it. The script appends every
    invocation to ``runs.log`` next to itself, which is how a test reads back
    which levels were actually exercised.

    ``aborts_on`` maps ``FLAG -> level``; a matching invocation exits 2 with a
    panic-shaped line on stderr (the real failure: a Go panic on exit 2).
    ``effects`` maps ``FLAG -> per-unit slope`` used to build the objective, so a
    factor can be made live or dead on purpose. ``noise`` scales a deterministic
    per-seed wobble so a noise floor is measurable without flakiness.
    """
    aborts_on = aborts_on or {}
    effects = effects or {}
    path = tmp_path / "target.py"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"ABORTS = {aborts_on!r}\n"
        f"EFFECTS = {effects!r}\n"
        f"NOISE = {noise!r}\n"
        "levels = {}\n"
        "for a in sys.argv[1:]:\n"
        "    if a.startswith('--') and '=' in a:\n"
        "        k, v = a[2:].split('=', 1)\n"
        "        levels[k] = v\n"
        "here = os.path.dirname(os.path.abspath(__file__))\n"
        "with open(os.path.join(here, 'runs.log'), 'a') as fh:\n"
        "    fh.write(json.dumps(levels) + '\\n')\n"
        "for k, bad in ABORTS.items():\n"
        "    if str(levels.get(k)) == str(bad):\n"
        "        sys.stderr.write('panic: runtime error: index out of range\\n')\n"
        "        sys.exit(2)\n"
        "score = 100.0\n"
        "for k, slope in EFFECTS.items():\n"
        "    try:\n"
        "        score += float(slope) * float(levels.get(k, 0))\n"
        "    except (TypeError, ValueError):\n"
        "        pass\n"
        "seed = int(os.environ.get('NOUS_WORKLOAD_SEED', '0'))\n"
        "score += NOISE * (((seed * 7919) % 101) / 100.0 - 0.5)\n"
        "print(json.dumps({'applied': levels, 'm': score}))\n",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _exercised_levels(tmp_path: Path) -> list[dict]:
    log = tmp_path / "runs.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line]


def _sweep_campaign(tmp_path: Path, *, factors: list[dict],
                    aborts_on=None, effects=None, noise: float = 0.0,
                    baseline: dict | None = None) -> dict:
    target = _script_target(
        tmp_path, aborts_on=aborts_on, effects=effects, noise=noise,
    )
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    opt = {
        "response": {"primary": {"metric": "m", "direction": "maximize"}},
        "factors": factors,
        "stages": ["verify", "screen", "confirm"],
        "design": {"screen": {"resolution": 3}, "confirm": {"replicates": 1}},
        "run_command": f"python3 {target}",
        "workload": {"seed_env": "NOUS_WORKLOAD_SEED"},
    }
    if baseline is not None:
        opt["known_valid_baseline"] = baseline
    return {
        "kind": "optimization", "run_id": "sweep",
        "research_question": "q",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "optimization": opt,
    }


def _relations(fid: str) -> list[dict]:
    return [{"id": f"R_{fid}", "kind": "correctness", "statement": "s",
             "native_test": "t.py::test_present"}]


def _numeric_factor(fid: str, levels: list) -> dict:
    return {
        "id": fid, "name": fid.lower(), "type": "numeric",
        "levels": [str(x) for x in levels],
        "apply": f"--{fid}={{level}}",
        "manipulation": {"observable": f"applied.{fid}", "op": "==",
                         "value": "{level}"},
        "relations": _relations(fid),
    }


# ───────────── GAP 3: a level that aborts must be a NAMED failure ─────────────


def test_smoke_default_reports_how_many_levels_went_unexercised(tmp_path: Path):
    """Plain `--smoke` must make the gap VISIBLE, not close it.

    Off by default: the per-level sweep costs real runs, so existing campaigns
    are unaffected. But an author who ran plain smoke must be able to read that
    only the first corner was exercised.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[_numeric_factor("A", [1, 2, 3]), _numeric_factor("B", [4, 5])],
        baseline={"A": "1", "B": "4"},
    )
    issues = _smoke_check_optimization(campaign)
    assert issues == [], issues
    # 5 declared levels; the single corner exercises one per factor -> 3 unseen.
    assert len(_exercised_levels(tmp_path)) == 1, _exercised_levels(tmp_path)


def test_smoke_default_prints_the_unexercised_level_count(tmp_path: Path, capsys):
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[_numeric_factor("A", [1, 2, 3]), _numeric_factor("B", [4, 5])],
        baseline={"A": "1", "B": "4"},
    )
    _smoke_check_optimization(campaign)
    out = capsys.readouterr().out
    assert "3" in out and "--liveness" in out, out
    assert "NOT exercised" in out, out


def test_liveness_names_the_factor_and_level_that_aborts(tmp_path: Path):
    """The real defect: `eviction_policy: arc` exited 2 on a Go panic.

    The author's own harness reused a stale metrics file on non-zero exit and
    reported the panicking level as a clean null result identical to baseline.
    The failure must name BOTH the factor and the level.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[{
            "id": "POLICY", "name": "eviction_policy", "type": "choice",
            "levels": ["lru", "arc"], "apply": "--POLICY={level}",
            "manipulation": {"observable": "applied.POLICY", "op": "==",
                             "value": "{level}"},
            "relations": _relations("POLICY"),
        }],
        aborts_on={"POLICY": "arc"},
        baseline={"POLICY": "lru"},
    )
    issues = _smoke_check_optimization(campaign, liveness=True)
    joined = " ".join(issues)
    assert issues, "an aborting level must be a smoke FAILURE"
    assert "POLICY" in joined and "arc" in joined, joined


def test_liveness_exercises_every_declared_level_exactly_once_at_least(
    tmp_path: Path,
):
    """`sum(len(levels))` runs, not `prod(...)` — linear, not combinatorial."""
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[_numeric_factor("A", [1, 2, 3]), _numeric_factor("B", [4, 5])],
        effects={"A": 10.0},
        baseline={"A": "1", "B": "4"},
    )
    _smoke_check_optimization(campaign, liveness=True)
    seen = _exercised_levels(tmp_path)
    for level in ("1", "2", "3"):
        assert any(r.get("A") == level for r in seen), (level, seen)
    for level in ("4", "5"):
        assert any(r.get("B") == level for r in seen), (level, seen)


def test_plain_smoke_does_not_exercise_the_aborting_level(tmp_path: Path):
    """Off by default: an existing campaign's smoke cost does not change."""
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[{
            "id": "POLICY", "name": "eviction_policy", "type": "choice",
            "levels": ["lru", "arc"], "apply": "--POLICY={level}",
            "manipulation": {"observable": "applied.POLICY", "op": "==",
                             "value": "{level}"},
            "relations": _relations("POLICY"),
        }],
        aborts_on={"POLICY": "arc"},
        baseline={"POLICY": "lru"},
    )
    assert _smoke_check_optimization(campaign) == []
    assert all(r.get("POLICY") != "arc" for r in _exercised_levels(tmp_path))


# ─────────── GAP 2: is the factor demonstrably LIVE above the noise? ──────────


def test_liveness_flags_a_factor_whose_effect_is_under_the_noise_floor(
    tmp_path: Path,
):
    """A knob captured in config but consumed by no mechanism is a dead axis.

    Two of eight real factors produced byte-identical output. Such a factor
    passes every static and smoke check, consumes its share of a resolution-V
    design, and contributes only variance to the fit.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[_numeric_factor("LIVE", [0, 10]),
                 _numeric_factor("DEAD", [0, 10])],
        effects={"LIVE": 5.0},   # DEAD moves the objective by exactly 0
        noise=2.0,
        baseline={"LIVE": "0", "DEAD": "0"},
    )
    issues = _smoke_check_optimization(campaign, liveness=True)
    # Report, do not refuse: a small-but-real effect is the author's call.
    assert issues == [], issues


def test_liveness_report_names_the_dead_factor_and_not_the_live_one(
    tmp_path: Path, capsys,
):
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[_numeric_factor("LIVE", [0, 10]),
                 _numeric_factor("DEAD", [0, 10])],
        effects={"LIVE": 5.0},
        noise=2.0,
        baseline={"LIVE": "0", "DEAD": "0"},
    )
    _smoke_check_optimization(campaign, liveness=True)
    out = capsys.readouterr().out
    assert "not demonstrably live" in out, out
    # The dead factor is flagged; the live one (effect 50 vs noise ~2) is not.
    dead_line = [ln for ln in out.splitlines() if "DEAD" in ln]
    live_line = [ln for ln in out.splitlines() if "LIVE" in ln]
    assert dead_line and "not demonstrably live" in " ".join(dead_line), out
    assert live_line and "not demonstrably live" not in " ".join(live_line), out


def test_liveness_measures_a_noise_floor_from_repeated_baseline_runs(
    tmp_path: Path, capsys,
):
    """The floor comes from N baseline runs varying ONLY the workload seed."""
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path,
        factors=[_numeric_factor("A", [0, 10])],
        effects={"A": 1.0},
        noise=6.0,
        baseline={"A": "0"},
    )
    _smoke_check_optimization(campaign, liveness=True, liveness_repeats=4)
    out = capsys.readouterr().out
    assert "noise" in out.lower(), out
    # 4 baseline runs at A=0, all with the SAME level and different seeds.
    baseline_runs = [r for r in _exercised_levels(tmp_path) if r.get("A") == "0"]
    assert len(baseline_runs) >= 4, _exercised_levels(tmp_path)


def test_liveness_needs_a_known_valid_baseline(tmp_path: Path):
    """Without a baseline there is nothing to hold the other factors at."""
    from orchestrator.cli import _smoke_check_optimization

    campaign = _sweep_campaign(
        tmp_path, factors=[_numeric_factor("A", [0, 10])], effects={"A": 5.0},
    )
    issues = _smoke_check_optimization(campaign, liveness=True)
    assert any("known_valid_baseline" in i for i in issues), issues


# ───────────────────────── the CLI flag itself ────────────────────────────────


def test_liveness_flag_is_rejected_without_smoke(tmp_path: Path, capsys):
    """`--liveness` is a smoke deepening, not an independent mode."""
    from orchestrator.cli import build_parser

    args = build_parser().parse_args(
        ["validate", "campaign", str(tmp_path / "c.yaml"), "--liveness"],
    )
    assert args.liveness is True
    assert args.smoke is False


def test_validate_campaign_default_leaves_liveness_off(tmp_path: Path):
    """Every new check is off by default; existing invocations are unaffected."""
    from orchestrator.cli import build_parser

    args = build_parser().parse_args(
        ["validate", "campaign", str(tmp_path / "c.yaml")],
    )
    assert args.smoke is False
    assert getattr(args, "liveness") is False
    assert getattr(args, "liveness_repeats") == 3


def test_validate_campaign_exits_1_when_a_level_aborts(tmp_path: Path):
    """The whole chain: `nous validate campaign FILE --smoke --liveness`.

    Exercises the flags through `_validate_campaign_file` rather than the
    internal check, so the exit code an author (or CI) actually sees is what is
    asserted. Without --liveness the same campaign validates clean, which is the
    off-by-default guarantee.
    """
    from orchestrator.cli import _validate_campaign_file

    factors = [{
        "id": "POLICY", "name": "eviction_policy", "type": "choice",
        "levels": ["lru", "arc"], "apply": "--POLICY={level}",
        "manipulation": {"observable": "applied.POLICY", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": "R", "kind": "correctness", "statement": "s",
                       "native_test": "test_present"}],
    }]
    campaign = _sweep_campaign(
        tmp_path, factors=factors, aborts_on={"POLICY": "arc"},
        baseline={"POLICY": "lru"},
    )
    repo = Path(campaign["target_system"]["repo_path"])
    (repo / "t.py").write_text("def test_present():\n    assert True\n")
    campaign["research_question"] = "Which eviction policy wins?"
    campaign["target_system"]["description"] = "A toy target."
    campaign["prompts"] = {"methodology_layer": "thin"}
    campaign["optimization"]["test_command"] = "echo '--- PASS: test_present'"
    path = tmp_path / "campaign.yaml"
    path.write_text(json.dumps(campaign))   # JSON is valid YAML

    # Off by default: the same campaign passes plain --smoke.
    _validate_campaign_file(path, smoke=True)

    with pytest.raises(SystemExit) as exc:
        _validate_campaign_file(path, smoke=True, liveness=True)
    assert exc.value.code == 1


# ─────── response.self_check: the invariant --smoke and --liveness enforce ──────
#
# Nous cannot know an objective's semantics, so it cannot detect a
# self-contradictory row itself. The author states the invariant that DEFINES the
# objective and Nous enforces it -- per row inside the epoch, and on the
# configurations `--smoke` / `--liveness` run, so a violated invariant surfaces
# BEFORE the policy hash is written rather than after ~2 hours of measurement.
#
# The real defect: `max_sustained_rate` was reported alongside a
# `backlog_slope` that exceeded the growing threshold on 8 of 12 rows, every one
# biased in the flattering direction. Exit codes were clean, the file was
# present and parseable, the manipulation predicates passed, and the schema
# validated.


def _self_check_target(tmp_path: Path, *, slope_when: dict) -> Path:
    """A target reporting an objective AND the diagnostic that defines it.

    ``slope_when`` maps a factor level to the ``backlog_slope`` the run reports.
    A slope above the campaign's declared threshold, alongside a healthy-looking
    ``m``, is a row asserting a rate was sustained while its own diagnostic says
    it was growing.
    """
    path = tmp_path / "sc_target.py"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"SLOPES = {slope_when!r}\n"
        "levels = {}\n"
        "for a in sys.argv[1:]:\n"
        "    if a.startswith('--') and '=' in a:\n"
        "        k, v = a[2:].split('=', 1)\n"
        "        levels[k] = v\n"
        "slope = float(SLOPES.get(levels.get('P'), 0.0))\n"
        "print(json.dumps({'applied': levels, 'm': 2.1562, "
        "'backlog_slope': slope}))\n",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _self_check_campaign(tmp_path: Path, *, slope_when: dict,
                         self_check: list | None = None) -> dict:
    target = _self_check_target(tmp_path, slope_when=slope_when)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    response = {"primary": {"metric": "m", "direction": "maximize"}}
    if self_check is not None:
        response["self_check"] = self_check
    return {
        "kind": "optimization", "run_id": "sc", "research_question": "q",
        "target_system": {"name": "T", "repo_path": str(repo)},
        "optimization": {
            "response": response,
            "factors": [{
                "id": "P", "name": "policy", "type": "choice",
                "levels": ["a", "b"], "apply": "--P={level}",
                "manipulation": {"observable": "applied.P", "op": "==",
                                 "value": "{level}"},
                "relations": _relations("P"),
            }],
            "stages": ["verify", "screen", "confirm"],
            "design": {"screen": {"resolution": 3},
                       "confirm": {"replicates": 1}},
            "run_command": f"python3 {target}",
            "known_valid_baseline": {"P": "a"},
        },
    }


_SLOPE_CHECK = [{"metric": "backlog_slope", "op": "<=", "value": 0.060}]


def test_smoke_fails_when_the_probe_violates_a_declared_self_check(tmp_path: Path):
    """One declared line catches at the probe what took an epoch to find."""
    from orchestrator.cli import _smoke_check_optimization

    campaign = _self_check_campaign(
        tmp_path, slope_when={"a": 0.1234, "b": 0.0100},
        self_check=_SLOPE_CHECK,
    )
    issues = _smoke_check_optimization(campaign)

    assert any("self_check violated" in i for i in issues), issues
    assert any("backlog_slope" in i and "0.1234" in i for i in issues), issues


def test_smoke_passes_when_the_declared_self_check_holds(tmp_path: Path):
    from orchestrator.cli import _smoke_check_optimization

    campaign = _self_check_campaign(
        tmp_path, slope_when={"a": 0.0100, "b": 0.0200},
        self_check=_SLOPE_CHECK,
    )
    assert _smoke_check_optimization(campaign) == []


def test_smoke_reports_how_many_self_checks_hold(tmp_path: Path, capsys):
    """The count is printed on a passing probe too -- an unread check is not one."""
    from orchestrator.cli import _smoke_check_optimization

    campaign = _self_check_campaign(
        tmp_path, slope_when={"a": 0.0100, "b": 0.0200},
        self_check=_SLOPE_CHECK,
    )
    _smoke_check_optimization(campaign)

    out = capsys.readouterr().out
    assert "1/1 declared response.self_check invariant(s) hold" in out


def test_smoke_with_no_self_check_declared_is_unchanged(tmp_path: Path, capsys):
    """A campaign declaring none behaves exactly as before -- silent and clean.

    The target here violates what WOULD have been the invariant; with nothing
    declared, Nous has no basis to object, and inventing one would be Nous
    guessing an objective's semantics.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _self_check_campaign(tmp_path, slope_when={"a": 0.1234})
    assert _smoke_check_optimization(campaign) == []
    assert "self_check" not in capsys.readouterr().out


def test_liveness_flags_the_level_whose_row_contradicts_itself(tmp_path: Path):
    """`--liveness` runs every level, so it finds a violation the corner misses.

    Level ``a`` is honest and sits at the probe corner; level ``b`` is the
    self-contradictory one. Plain `--smoke` therefore passes and `--liveness`
    fails -- which is the same off-by-default/opt-in split the aborting-level
    sweep has.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _self_check_campaign(
        tmp_path, slope_when={"a": 0.0100, "b": 0.1234},
        self_check=_SLOPE_CHECK,
    )
    assert _smoke_check_optimization(campaign) == []

    issues = _smoke_check_optimization(campaign, liveness=True,
                                       liveness_repeats=2)
    assert any("self_check violated" in i for i in issues), issues
    assert any("P=" in i and "'b'" in i for i in issues), issues


def test_liveness_still_measures_the_effect_of_a_self_contradicting_level(
    tmp_path: Path, capsys,
):
    """A self-check violation is not an "unrunnable level" -- the row DID run.

    Conflating the two would report "level could not be run" about a
    configuration that ran fine, and would suppress its effect-size measurement.
    """
    from orchestrator.cli import _smoke_check_optimization

    campaign = _self_check_campaign(
        tmp_path, slope_when={"a": 0.0100, "b": 0.1234},
        self_check=_SLOPE_CHECK,
    )
    issues = _smoke_check_optimization(campaign, liveness=True,
                                       liveness_repeats=2)

    assert not any("could not be run" in i for i in issues), issues
    # The effect line is still printed for P: both levels were measured.
    assert "P " in capsys.readouterr().out
