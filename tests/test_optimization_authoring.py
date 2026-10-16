"""Behavioral tests for the kind: optimization authoring path.

scaffold -> validate (names placeholders) -> fill -> validate / --smoke /
--liveness (design preview) -> run refuses placeholders. Every check runs the
real CLI entry point (``orchestrator.cli.main``) against a tiny tmp target; no
LLM anywhere.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest
import yaml

from orchestrator import cli

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "fixtures" / "create_campaign_reflective_golden"


def _nous(argv: list[str], capsys) -> tuple[int, str, str]:
    old = sys.argv
    sys.argv = ["nous", *argv]
    code = 0
    try:
        cli.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    finally:
        sys.argv = old
    out, err = capsys.readouterr()
    return code, out, err


# ── a tiny target: adapter + its own relation tests ──────────────────────────

ADAPTER = r'''
import argparse, json, os, random
ap = argparse.ArgumentParser()
ap.add_argument("--knob", type=int, required=True)
ap.add_argument("--mode", choices=["off", "on"], required=True)
a = ap.parse_args()
seed = int(os.environ.get("NOUS_WORKLOAD_SEED", "0"))
noise = random.Random(seed).gauss(0, float(os.environ.get("NOISE_SD", "1.0")))
score = 100.0 + 5.0 * a.knob + (10.0 if a.mode == "on" else 0.0) + noise
print(json.dumps({"score": score, "latency_ms": 10.0, "completed": True,
                  "holdout_score": score, "cfg": {"knob": a.knob,
                  "mode": a.mode, "size": 4}}))
'''

RELATIONS = '''
def test_numeric_knob():
    assert True

def test_choice_knob():
    assert True
'''


def _target(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    (repo / "tests").mkdir(parents=True)
    (repo / "adapter.py").write_text(ADAPTER)
    (repo / "tests" / "test_relations.py").write_text(RELATIONS)
    return repo


def _fill(text: str, *, epsilon: str | None = None) -> str:
    """What an author does: replace every TODO- token with a real value."""
    for a, b in fill_subs():
        assert a in text, a
        text = text.replace(a, b)
    if epsilon is not None:
        text = text.replace("epsilon: {pct: 2.0}", f"epsilon: {epsilon}")
    return text


def fill_subs() -> list[tuple[str, str]]:
    """The (placeholder, value) pairs that fill the single-objective scaffold."""
    py = sys.executable
    return [
        ("TODO-run-id", "tiny-opt"),
        ("TODO-which configuration of the declared knobs maximizes the "
         "primary metric, subject to the constraints?",
         "Which knob and mode maximize score?"),
        ("TODO-target-name", "tiny-target"),
        ("TODO-describe the target and what one run of the adapter measures.",
         "A synthetic adapter."),
        ("TODO-locked-knob: TODO-locked-value", "size: 4"),
        ("TODO-locked-knob: TODO-cfg.locked_knob", "size: cfg.size"),
        ("TODO-python TODO-path/to/adapter.py", f"{py} adapter.py"),
        ("TODO-python -m pytest -v TODO-tests/test_relations.py",
         f"{py} -m pytest -v -p no:cacheprovider tests/test_relations.py"),
        ("TODO-primary-metric", "score"),
        ("TODO-constraint-metric", "latency_ms"),
        ('op: "<=", value: 0}', 'op: "<=", value: 100}'),
        ("TODO-completed-flag", "completed"),
        ("TODO-held-out-metric", "holdout_score"),
        ("TODO-numeric-knob-name", "knob"),
        ("--TODO-numeric-flag", "--knob"),
        ("TODO-cfg.numeric_knob", "cfg.knob"),
        ("TODO: what must stay correct at every level of this knob", "ok"),
        ("TODO-tests/test_relations.py::test_numeric_knob",
         "tests/test_relations.py::test_numeric_knob"),
        ("TODO-choice-knob-name", "mode"),
        ("--TODO-choice-flag", "--mode"),
        ("TODO-cfg.choice_knob", "cfg.mode"),
        ("TODO: what must stay correct with this choice on and off", "ok"),
        ("TODO-tests/test_relations.py::test_choice_knob",
         "tests/test_relations.py::test_choice_knob"),
    ]


def _scaffold(tmp_path: Path, capsys, *extra: str) -> tuple[Path, Path]:
    repo = _target(tmp_path)
    camp = tmp_path / "campaign.yaml"
    code, out, err = _nous(
        ["create-campaign", "--kind", "optimization", "--to", str(camp),
         "--target-repo-path", str(repo), *extra], capsys,
    )
    assert code == 0, err
    assert "nous docs quickstart" in out
    return camp, repo


# ── 2: the scaffold ──────────────────────────────────────────────────────────


def test_unedited_scaffold_fails_validate_naming_every_placeholder(tmp_path, capsys):
    camp, _ = _scaffold(tmp_path, capsys)
    code, out, err = _nous(["validate", "campaign", str(camp)], capsys)
    assert code == 1
    for path in ("optimization.run_command", "optimization.test_command",
                 "optimization.response.primary.metric",
                 "optimization.factors[0].apply",
                 "optimization.factors[1].manipulation.observable",
                 "optimization.factors[0].relations[0].native_test",
                 "optimization.locked_observables.TODO-locked-knob",
                 "target_system.name"):
        assert f"[placeholder] {path} =" in err, path
    assert "nous docs quickstart" in err
    assert re.search(r"next: fix the \d+ error\(s\) above", err)


def test_nous_run_refuses_an_unfilled_scaffold(tmp_path, capsys):
    camp, _ = _scaffold(tmp_path, capsys)
    code, _out, err = _nous(["run", str(camp)], capsys)
    assert code == 1
    assert "Refusing to run" in err and "optimization.run_command" in err


def test_scaffold_is_structurally_complete(tmp_path, capsys):
    camp, _ = _scaffold(tmp_path, capsys)
    doc = yaml.safe_load(camp.read_text())
    opt = doc["optimization"]
    assert doc["kind"] == "optimization"
    for key in ("run_command", "test_command", "test_timeout_sec",
                "run_timeout_sec", "locked_observables", "known_valid_baseline",
                "workload", "policy", "response", "factors", "design", "stages"):
        assert key in opt, key
    # 4 centres: the two-level choice factor B gets two centre configurations
    # of two replicates each (spec 2026-10-16 feature 3), df = 2.
    assert opt["design"]["screen"] == {"resolution": 5, "center_points": 4}
    numeric = [f for f in opt["factors"] if f["type"] == "numeric"]
    assert numeric and numeric[0]["grid"] == 1
    assert {f["type"] for f in opt["factors"]} == {"numeric", "choice"}
    for k in ("primary", "constraints", "self_check", "held_out",
              "noise_estimate_pct"):
        assert k in opt["response"], k
    # plan/build are offered but OFF
    assert "build" not in opt["stages"] and "# stages: [plan, build" in camp.read_text()


def test_adapter_stub_is_written_and_executable(tmp_path, capsys):
    stub = tmp_path / "bench" / "adapter.py"
    _scaffold(tmp_path, capsys, "--adapter-stub", str(stub))
    text = stub.read_text()
    assert stub.stat().st_mode & 0o100
    for needle in ("NOUS_WORKLOAD_SEED", "NOUS_RUN_DIR", "json.dumps", '"cfg"'):
        assert needle in text, needle
    compile(text, str(stub), "exec")


def test_reflective_scaffold_is_byte_identical_to_pre_change(tmp_path, capsys):
    camp = tmp_path / "reflective.yaml"
    code, out, _ = _nous(["create-campaign", "--to", str(camp),
                          "--target-repo-path", "/GOLDEN_REPO"], capsys)
    assert code == 0
    assert camp.read_text() == (GOLDEN / "campaign.yaml").read_text()
    assert out.replace(str(camp), "FILE") == (GOLDEN / "stdout.txt").read_text()


def test_adapter_stub_rejected_for_reflective(tmp_path, capsys):
    code, _o, err = _nous(["create-campaign", "--to", str(tmp_path / "c.yaml"),
                           "--adapter-stub", str(tmp_path / "a.py")], capsys)
    assert code == 2 and "--kind optimization" in err


# ── 5 + 6: filled scaffold through the loop ──────────────────────────────────


def _filled(tmp_path, capsys, **kw) -> Path:
    camp, _ = _scaffold(tmp_path, capsys)
    camp.write_text(_fill(camp.read_text(), **kw))
    return camp


def test_filled_scaffold_passes_static_and_points_at_smoke(tmp_path, capsys):
    camp = _filled(tmp_path, capsys)
    code, out, err = _nous(["validate", "campaign", str(camp)], capsys)
    assert code == 0, err
    assert f"next: `nous validate campaign {camp} --smoke`" in out


def test_smoke_passes_and_points_at_liveness(tmp_path, capsys):
    camp = _filled(tmp_path, capsys)
    code, out, err = _nous(["validate", "campaign", str(camp), "--smoke"], capsys)
    assert code == 0, err + out
    assert "smoke: OK" in out
    assert f"next: `nous validate campaign {camp} --liveness`" in out
    assert "DESIGN PREVIEW" not in out


def test_liveness_prints_preview_with_the_screen_run_count(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / "parent"))
    camp = _filled(tmp_path, capsys)
    # --liveness alone implies --smoke.
    code, out, err = _nous(["validate", "campaign", str(camp), "--liveness"], capsys)
    assert code == 0, err + out
    assert "DESIGN PREVIEW" in out
    # 2 factors at resolution 5 -> full 2^2 = 4 corners + 4 centres = 8, and
    # the preview says why it is the full factorial; the centres cover both
    # levels of the choice factor B in 2 configurations (df 4 - 2 = 2).
    assert re.search(r"screen\s+8\s+— 4 corners \(the full factorial, already the "
                     r"smallest design of this resolution\) \+ 4 centre point\(s\) "
                     r"in 2 configuration", out), out
    # confirm: 3 finalists x 3 replicates, 1 round.
    assert re.search(r"confirm\s+9\s+— 3 finalist", out), out
    assert "refine" not in out.split("DESIGN PREVIEW", 1)[1].split("total")[0]
    assert "wall clock:" in out
    assert "screen MDE: t(0.975, df=2)=4.303" in out
    assert "levels of A: brackets base 4" in out
    assert f"next: `NOUS_CAMPAIGN_PARENT={tmp_path / 'parent'} nous run {camp}`" in out


def _liveness_out(tmp_path, capsys, monkeypatch, *, noise: float, eps: str) -> str:
    monkeypatch.setenv("NOISE_SD", str(noise))
    camp = _filled(tmp_path, capsys, epsilon=eps)
    code, out, err = _nous(["validate", "campaign", str(camp), "--liveness"], capsys)
    assert code == 0, err + out
    return out


def _mde(out: str) -> float:
    return float(re.search(r"/ sqrt\(\d+ corners\) = ([0-9.e+-]+)", out).group(1))


def test_mde_warning_fires_only_when_epsilon_is_below_it(tmp_path, capsys, monkeypatch):
    noisy = _liveness_out(tmp_path / "a", capsys, monkeypatch, noise=5.0,
                          eps="{abs: 0.01}")
    assert "epsilon is unreachable from the screen" in noisy
    roomy = _liveness_out(tmp_path / "b", capsys, monkeypatch, noise=5.0,
                          eps="{abs: 1000.0}")
    assert "epsilon is unreachable" not in roomy


def test_mde_is_monotone_in_measured_noise(tmp_path, capsys, monkeypatch):
    mdes = [_mde(_liveness_out(tmp_path / f"n{i}", capsys, monkeypatch,
                               noise=sd, eps="{abs: 1000.0}"))
            for i, sd in enumerate((0.5, 2.0, 8.0))]
    assert mdes[0] < mdes[1] < mdes[2], mdes


def test_static_pass_reports_all_problems_in_one_pass(tmp_path, capsys):
    """A schema error does not hide placeholder or cross-field findings."""
    camp, _ = _scaffold(tmp_path, capsys)
    doc = yaml.safe_load(camp.read_text())
    doc["optimization"]["run_timeout_sec"] = "slow"          # schema error
    doc["optimization"]["design"]["refine"] = {"center_points": 4}  # rule 4
    camp.write_text(yaml.safe_dump(doc))
    code, _o, err = _nous(["validate", "campaign", str(camp)], capsys)
    assert code == 1
    assert "[schema] optimization.run_timeout_sec" in err
    assert "[placeholder] optimization.run_command" in err
    assert "[rules, provisional]" in err and "refine" in err


# ── preview arithmetic, cross-checked against a real zero-token epoch ────────


def test_preview_screen_count_matches_what_a_synthetic_campaign_runs(tmp_path):
    from orchestrator.optimize.harness import run_synthetic_campaign
    from orchestrator.optimize.preview import build_preview
    from orchestrator.optimize.harness import synthetic_campaign
    from orchestrator.optimize.synthetic import SURFACES

    surface = SURFACES["additive"]()
    campaign = synthetic_campaign(surface)
    pv = build_preview(campaign, noise_sd=1.0, mean=100.0, run_secs=[1.0])
    predicted = {s.stage: s.runs for s in pv.stages}

    res = run_synthetic_campaign(surface, seed=1, parent_dir=tmp_path)
    work = Path(res.work_dir)
    measured = {}
    for it in sorted((work / "runs").glob("iter-*")):
        dm = it / "design_matrix.json"
        eff = it / "effects.json"
        if dm.exists() and eff.exists():
            stage = json.loads(eff.read_text()).get("stage", "screen")
            measured.setdefault(stage, len(json.loads(dm.read_text())["rows"]))
    assert measured.get("screen") == predicted["screen"], (measured, predicted)
    if "refine" in measured:
        assert measured["refine"] == predicted["refine"]


def test_screen_mde_formula_matches_the_guide_example():
    from orchestrator.optimize.preview import screen_mde

    # Guide §7.9 check 14: 2^4 screen + 3 centres -> df=2, t=4.303.
    mde, t = screen_mde(16, 2, 1.0)
    assert t == pytest.approx(4.303, abs=1e-3)
    assert mde == pytest.approx(4.303 * 2 / 4, abs=1e-3)
    assert math.isinf(screen_mde(16, 0, 1.0)[0])


# ── --smoke / --liveness with a `build` stage (tests not authored yet) ───────


def _build_campaign(tmp_path, capsys, *, new_file_exists: bool) -> Path:
    camp = _filled(tmp_path, capsys)
    repo = tmp_path / "target"
    if new_file_exists:  # authored, but the mechanism is not there yet
        (repo / "tests" / "test_new.py").write_text(
            "def test_choice_mechanism():\n    assert False\n")
    doc = yaml.safe_load(camp.read_text())
    opt = doc["optimization"]
    opt["stages"] = ["build", "verify", "screen", "confirm"]
    opt["test_command"] += " tests/test_new.py"
    opt["factors"][1]["relations"][0]["native_test"] = (
        "tests/test_new.py::test_choice_mechanism")
    camp.write_text(yaml.safe_dump(doc, sort_keys=False))
    return camp


def test_smoke_with_build_does_not_fail_on_tests_build_will_author(tmp_path, capsys):
    camp = _build_campaign(tmp_path, capsys, new_file_exists=False)
    code, out, err = _nous(["validate", "campaign", str(camp), "--smoke"], capsys)
    assert code == 0, err + out
    assert ("1 declared test(s) are expected to be authored by build: "
            "tests/test_new.py::test_choice_mechanism; verify will require them"
            in out)
    assert "dropped 1 test path argument(s)" in out and "tests/test_new.py" in out
    # The existing relation still had to resolve and match.
    assert "1/1 declared identifier(s) matched" in out
    # ...and it already passes pre-build -- but it belongs to a knob the target
    # already has (all its tests ran), so oracle 2(b) does not bind it and smoke
    # must not push the author toward allow_preexisting_tests.
    assert "already PASS pre-build" not in out


def test_smoke_warns_when_a_built_factors_test_already_passes(tmp_path, capsys):
    """The case oracle 2(b) exists for: a factor the build AUTHORS also declares
    a test that is green before the mechanism exists. Smoke must say so, with
    exactly the verdict verify will reach."""
    camp = _build_campaign(tmp_path, capsys, new_file_exists=False)
    doc = yaml.safe_load(camp.read_text())
    factors = doc["optimization"]["factors"]
    existing = factors[0]["relations"][0]["native_test"]
    factors[1]["relations"].append({"id": "B-R2", "kind": "correctness",
                                    "statement": "s", "native_test": existing})
    camp.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, out, err = _nous(["validate", "campaign", str(camp), "--smoke"], capsys)
    assert "already PASS pre-build" in out and existing in out, err + out


def test_smoke_with_build_still_fails_an_unmatched_existing_test(tmp_path, capsys):
    """Only tests build will AUTHOR are excused. A path-style id in a file that
    exists now must still be reported by the runner, or smoke fails."""
    camp = _build_campaign(tmp_path, capsys, new_file_exists=False)
    doc = yaml.safe_load(camp.read_text())
    doc["optimization"]["factors"][0]["relations"][0]["native_test"] = (
        "tests/test_relations.py::test_misspelled")
    camp.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, out, err = _nous(["validate", "campaign", str(camp), "--smoke"], capsys)
    assert code == 1
    assert "test_misspelled" in err and "did not appear" in err
    line = next(l for l in out.splitlines() if "expected to be authored by build" in l)
    assert "test_misspelled" not in line


def test_liveness_with_build_reports_authored_factor_as_not_applicable(
    tmp_path, capsys,
):
    camp = _build_campaign(tmp_path, capsys, new_file_exists=True)
    code, out, err = _nous(["validate", "campaign", str(camp), "--liveness"], capsys)
    assert code == 0, err + out
    assert "FAIL pre-build — expected" in out
    assert re.search(r"\n\s+B\s+authored by build; liveness not applicable "
                     r"pre-build", out), out
    assert "not demonstrably live (B" not in out
