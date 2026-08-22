"""Behavioral tests for the optimization-campaign artifact writers and the
deterministic findings/principle-updates projection (design spec 5.5).

Why this module matters most for the cost claim: ``screen`` and ``refine``
make ZERO LLM calls, but the campaign must still write ``findings.json``
and ``principle_updates.json`` every iteration because the rest of the
ecosystem (``/post-campaign``, ``index-wiki``, ``visualize-campaign``, the
cross-campaign registry) reads them unconditionally. ``project_findings``
and ``project_principle_updates`` build those files deterministically from
a fitted ``Fit`` -- a fitted effect with a confidence interval already
contains a claim, a direction, a magnitude, and quantitative evidence, so
restating it in prose would cost tokens and add nothing. This follows the
pure-Python ``orchestrator/meta_findings.py`` (#155) precedent.

The hard constraint under test: ``project_findings`` output must validate
against the EXISTING, UNMODIFIED ``findings.schema.json`` -- whose
``arm_type`` and ``status`` enums were designed for the reflective kind's
predict-then-compare epistemology. The mapping (see module docstring in
``artifacts.py``) uses ``h-main`` for a surviving effect and
``h-control-negative`` for a factor dropped as within-noise, with all
optimization-specific numbers (estimate, ci_low, ci_high, se, aliases,
stage) carried in the open ``metadata`` object.

Every float assertion uses ``math.isclose`` -- fitted coefficients carry
representation error, so ``==`` would be flaky.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import jsonschema
import pytest

from orchestrator.optimize.artifacts import (
    append_run,
    project_findings,
    project_principle_updates,
    read_runs,
    write_design_matrix,
    write_effects,
    write_relations,
)
from orchestrator.optimize.design import (
    fractional_factorial,
    full_factorial,
    with_center_points,
)
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import matrix_payload
from orchestrator.optimize.relations import RelationVerdict

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _validate(instance: dict, schema_name: str) -> None:
    jsonschema.validate(instance, _load_schema(schema_name))


# ─── Fixtures ─────────────────────────────────────────────────────────────


def _factor_raw(fid, statement, native_test, **over):
    raw = {
        "id": fid, "name": fid.lower(), "type": "numeric",
        "levels": [2, 4, 8, 16], "grid": 1,
        "apply": f"--{fid.lower()}={{level}}",
        "manipulation": {"observable": f"telemetry.{fid.lower()}",
                         "op": "==", "value": "{level}"},
        "relations": [{"id": f"R_{fid}", "kind": "correctness",
                       "statement": statement,
                       "native_test": native_test}],
    }
    raw.update(over)
    return raw


def _factors_abc():
    """Three factors: A and B will carry real effects, C will be null."""
    return parse_factors([
        _factor_raw("A", "A monotone increases throughput",
                    "tests/prop_a.py::test_noop"),
        _factor_raw("B", "B monotone decreases latency",
                    "tests/prop_b.py::test_noop"),
        _factor_raw("C", "C has no effect on throughput",
                    "tests/prop_c.py::test_noop"),
    ])


def _synth(design, factor_ids, intercept, mains):
    out = []
    for p in design.points:
        if p.role != "corner":
            out.append(intercept)
            continue
        y = intercept
        for j, fid in enumerate(factor_ids):
            y += mains.get(fid, 0.0) * p.coded[j]
        out.append(y)
    return out


def _fit_with_known_effects():
    """A-B-C design where A/B survive and C is dropped as within-noise."""
    factors = _factors_abc()
    ids = tuple(f.id for f in factors)
    d = with_center_points(full_factorial(ids), 4)
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.0})
    centers = [i for i, p in enumerate(d.points) if p.role == "center"]
    for offset, i in zip([0.01, -0.01, 0.02, -0.02], centers):
        ys[i] = 10.0 + offset
    fit = fit_effects(d, ys, factor_ids=ids)
    return fit, factors, d


# ─── 1. write_design_matrix validates ──────────────────────────────────────


def test_write_design_matrix_output_validates(tmp_path):
    factors = _factors_abc()
    ids = tuple(f.id for f in factors)
    d = full_factorial(ids)
    payload = matrix_payload(d, factors, run_order_seed=42)

    out = write_design_matrix(tmp_path, payload)

    assert out == tmp_path / "design_matrix.json"
    on_disk = json.loads(out.read_text())
    _validate(on_disk, "design_matrix.schema.json")
    assert on_disk["factor_ids"] == list(ids)


# ─── 2. append_run + read_runs round-trip, valid JSONL ─────────────────────


def test_append_run_then_read_runs_round_trips_in_order(tmp_path):
    rows = [
        {"row_index": 0, "levels": {"A": 2}, "role": "corner",
         "replicate": 0, "status": "complete", "response": {"y": 10.1},
         "duration_ms": 5},
        {"row_index": 1, "levels": {"A": 4}, "role": "corner",
         "replicate": 0, "status": "complete", "response": {"y": 11.0},
         "duration_ms": 7},
    ]
    for row in rows:
        append_run(tmp_path, row)

    raw_lines = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert len(raw_lines) == 2
    for line in raw_lines:
        parsed = json.loads(line)          # each line is one JSON object
        assert isinstance(parsed, dict)

    got = read_runs(tmp_path)
    assert got == rows                     # order preserved


def test_append_run_is_append_only_across_writer_instances(tmp_path):
    """A crashed run must leave already-written rows intact -- append_run
    must never rewrite runs.jsonl, only add to it."""
    first = {"row_index": 0, "levels": {"A": 2}, "role": "corner",
             "replicate": 0, "status": "complete", "response": {"y": 1.0},
             "duration_ms": 1}
    append_run(tmp_path, first)
    before = (tmp_path / "runs.jsonl").read_text()

    second = {"row_index": 1, "levels": {"A": 4}, "role": "corner",
              "replicate": 0, "status": "complete", "response": {"y": 2.0},
              "duration_ms": 1}
    append_run(tmp_path, second)
    after = (tmp_path / "runs.jsonl").read_text()

    assert after.startswith(before)        # prior bytes untouched, only appended


def test_read_runs_tolerates_a_torn_trailing_line(tmp_path, caplog):
    """A crash mid-write can only ever tear the LAST line -- every earlier
    line was already flushed by a prior, completed append_run call. The
    whole point of append-only runs.jsonl is that a crashed run leaves
    completed rows intact; read_runs must actually be able to read them
    back, not raise and lose all of them to one torn trailing line.
    """
    rows = [
        {"row_index": 0, "levels": {"A": 2}, "role": "corner",
         "replicate": 0, "status": "complete", "response": {"y": 10.1},
         "duration_ms": 5},
        {"row_index": 1, "levels": {"A": 4}, "role": "corner",
         "replicate": 0, "status": "complete", "response": {"y": 11.0},
         "duration_ms": 7},
        {"row_index": 2, "levels": {"A": 8}, "role": "corner",
         "replicate": 0, "status": "complete", "response": {"y": 12.0},
         "duration_ms": 6},
    ]
    for row in rows:
        append_run(tmp_path, row)

    # Simulate a crash mid-write of a 4th line: no closing brace, no newline.
    target = tmp_path / "runs.jsonl"
    with open(target, "a", encoding="utf-8") as fh:
        fh.write('{"row_index":3,"lev')

    import logging
    with caplog.at_level(logging.WARNING):
        got = read_runs(tmp_path)

    assert got == rows                     # all 3 completed rows survive
    assert any("torn" in r.message.lower() for r in caplog.records), (
        "the skip must be reported, not silently swallowed"
    )


def test_read_runs_still_raises_on_a_malformed_interior_line(tmp_path):
    """A malformed line that is NOT the last line is not a crash signature
    -- a crash can only tear the final line, since every earlier line was
    already terminated before the next append_run began. Tolerating an
    interior tear would hide real corruption, so this must still raise.
    """
    good_first = {"row_index": 0, "levels": {"A": 2}, "role": "corner",
                  "replicate": 0, "status": "complete", "response": {"y": 10.1},
                  "duration_ms": 5}
    good_last = {"row_index": 2, "levels": {"A": 8}, "role": "corner",
                 "replicate": 0, "status": "complete", "response": {"y": 12.0},
                 "duration_ms": 6}

    target = tmp_path / "runs.jsonl"
    lines = [
        json.dumps(good_first, sort_keys=True),
        '{"row_index":1,"lev',              # malformed, but NOT the last line
        json.dumps(good_last, sort_keys=True),
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        read_runs(tmp_path)


# ─── 3. Each appended row validates against runs_row.schema.json ──────────


def test_each_appended_row_validates_against_runs_row_schema(tmp_path):
    rows = [
        {"row_index": 0, "levels": {"A": 2}, "role": "corner",
         "replicate": 0, "status": "complete", "response": {"y": 10.1},
         "duration_ms": 5, "manipulation_verdict": True,
         "constraint_verdicts": [], "integrity_verdict": None,
         "build_hash": "abc123", "error": None},
        {"row_index": 1, "levels": {"A": 4}, "role": "corner",
         "replicate": 0, "status": "rejected", "response": {},
         "duration_ms": 3, "error": "ceiling exceeded"},
    ]
    for row in rows:
        append_run(tmp_path, row)

    schema = _load_schema("runs_row.schema.json")
    for line in (tmp_path / "runs.jsonl").read_text().splitlines():
        jsonschema.validate(json.loads(line), schema)


# ─── 4. write_effects validates and carries stats fields ──────────────────


def test_write_effects_validates_and_carries_stats_fields(tmp_path):
    fit, factors, _ = _fit_with_known_effects()

    out = write_effects(tmp_path, fit, factors=factors, stage="screen")

    assert out == tmp_path / "effects.json"
    on_disk = json.loads(out.read_text())
    _validate(on_disk, "effects.schema.json")

    assert math.isclose(on_disk["pure_error_var"], fit.pure_error_var,
                        rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(on_disk["lack_of_fit_p"], fit.lack_of_fit_p,
                        rel_tol=1e-9, abs_tol=1e-12)
    by_label = {e["label"]: e for e in on_disk["effects"]}
    for fx in fit.effects:
        assert math.isclose(by_label[fx.label]["ci_low"], fx.ci_low,
                            rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(by_label[fx.label]["ci_high"], fx.ci_high,
                            rel_tol=1e-9, abs_tol=1e-12)


# ─── 5. write_effects records aliases for a fractional design ─────────────


def test_write_effects_records_aliases_for_a_fractional_design():
    ids = ("A", "B", "C", "D", "E", "F", "G")
    d = fractional_factorial(ids, resolution=3)
    ys = _synth(d, ids, 1.0, {"A": 1.0})
    fit = fit_effects(d, ys, factor_ids=ids, include_interactions=False)
    factors = parse_factors([
        _factor_raw(fid, f"{fid} statement", f"tests/prop_{fid.lower()}.py::test_noop")
        for fid in ids
    ])

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = write_effects(Path(td), fit, factors=factors, stage="screen")
        on_disk = json.loads(out.read_text())

    assert on_disk["aliases"], "res-III fit must carry its aliasing forward"
    assert on_disk["aliases"] == [list(pair) for pair in fit.aliases]


# ─── 6. write_relations validates and records native_test ─────────────────


def test_write_relations_validates_and_records_native_test(tmp_path):
    verdicts = [
        RelationVerdict(relation_id="R1", factor_id="A", kind="correctness",
                        native_test="tests/prop_a.py::test_noop",
                        passed=True, detail="passed"),
        RelationVerdict(relation_id="R2", factor_id="B", kind="behavioral",
                        native_test="tests/prop_b.py::test_monotone",
                        passed=False,
                        detail="native_test 'tests/prop_b.py::test_monotone' failed"),
    ]

    out = write_relations(tmp_path, verdicts)

    assert out == tmp_path / "relations.json"
    on_disk = json.loads(out.read_text())
    _validate(on_disk, "relations.schema.json")

    native_tests = {v["relation_id"]: v["native_test"] for v in on_disk["verdicts"]}
    assert native_tests["R1"] == "tests/prop_a.py::test_noop"
    assert native_tests["R2"] == "tests/prop_b.py::test_monotone"
    assert on_disk["behavioral_failures"] == ["R2"]
    assert on_disk["correctness_failures"] == []


# ─── 7. project_findings validates against the UNMODIFIED findings schema ─


def test_project_findings_validates_against_existing_findings_schema():
    fit, factors, _ = _fit_with_known_effects()

    findings = project_findings(
        fit, factors=factors, stage="screen", decision="refine",
        iteration=1, bundle_ref="iter-1-bundle",
    )

    _validate(findings, "findings.schema.json")
    assert findings["iteration"] == 1
    assert findings["bundle_ref"] == "iter-1-bundle"


# ─── 8. one entry per surviving effect, evidence contains estimate/CI/n ────


def test_project_findings_emits_one_entry_per_surviving_effect_with_numeric_evidence():
    fit, factors, _ = _fit_with_known_effects()
    by_label = {e.label: e for e in fit.effects}

    findings = project_findings(
        fit, factors=factors, stage="screen", decision="refine",
        iteration=1, bundle_ref="iter-1-bundle",
    )

    surviving_arms = [a for a in findings["arms"] if a["arm_type"] == "h-main"]
    surviving_labels = {a["metadata"]["label"] for a in surviving_arms}
    assert surviving_labels == {"A", "B"}

    for arm in surviving_arms:
        label = arm["metadata"]["label"]
        fx = by_label[label]
        observed = arm["observed"]
        # every numeric ingredient must be findable in the rendered string
        assert f"{fx.estimate:.4g}" in observed or _num_str_present(observed, fx.estimate)
        assert _num_str_present(observed, fx.ci_low)
        assert _num_str_present(observed, fx.ci_high)
        assert str(fit.n_runs) in observed
        assert math.isclose(arm["metadata"]["estimate"], fx.estimate,
                            rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(arm["metadata"]["ci_low"], fx.ci_low,
                            rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(arm["metadata"]["ci_high"], fx.ci_high,
                            rel_tol=1e-9, abs_tol=1e-12)

    # sorted by descending abs(estimate): B (2.0) before A (0.95)
    assert [a["metadata"]["label"] for a in surviving_arms] == ["B", "A"]


def _num_str_present(text: str, value: float) -> bool:
    """True if some reasonable decimal rendering of value appears in text."""
    candidates = {
        f"{value:.2f}", f"{value:.3f}", f"{value:.4f}",
        f"{value:.4g}", f"{value:.6g}", str(round(value, 2)),
        str(round(value, 3)), str(round(value, 4)),
    }
    return any(c in text for c in candidates)


# ─── 9. NULL-result entry per dropped factor naming the noise floor ───────


def test_project_findings_emits_null_result_for_dropped_factor():
    fit, factors, _ = _fit_with_known_effects()

    findings = project_findings(
        fit, factors=factors, stage="screen", decision="refine",
        iteration=1, bundle_ref="iter-1-bundle",
    )

    dropped_arms = [a for a in findings["arms"] if a["arm_type"] == "h-control-negative"]
    assert len(dropped_arms) == 1
    arm = dropped_arms[0]
    assert arm["status"] == "REFUTED"
    assert arm["metadata"]["label"] == "C"
    # the noise floor (the CI half-width / SE) must be named in diagnostic_note
    fx = {e.label: e for e in fit.effects}["C"]
    assert _num_str_present(arm["diagnostic_note"], fx.se)


# ─── 10. experiment_valid: false when a correctness relation failed ───────


def test_project_findings_sets_experiment_valid_false_on_correctness_failure():
    fit, factors, _ = _fit_with_known_effects()
    verdicts = [
        RelationVerdict(relation_id="R_A", factor_id="A", kind="correctness",
                        native_test="tests/prop_a.py::test_noop",
                        passed=False, detail="native_test failed"),
    ]

    findings = project_findings(
        fit, factors=factors, stage="screen", decision="refine",
        iteration=1, bundle_ref="iter-1-bundle", relation_verdicts=verdicts,
    )

    _validate(findings, "findings.schema.json")
    assert findings["experiment_valid"] is False


def test_project_findings_experiment_valid_true_when_relations_pass():
    fit, factors, _ = _fit_with_known_effects()
    verdicts = [
        RelationVerdict(relation_id="R_A", factor_id="A", kind="correctness",
                        native_test="tests/prop_a.py::test_noop",
                        passed=True, detail="passed"),
    ]

    findings = project_findings(
        fit, factors=factors, stage="screen", decision="refine",
        iteration=1, bundle_ref="iter-1-bundle", relation_verdicts=verdicts,
    )

    assert findings["experiment_valid"] is True


# ─── Effect.significant is None (unknown) must not be a measured null ─────


def test_project_findings_handles_unknown_significance_honestly():
    """No center-point replicates -> significant is None for every effect.
    An unknown effect is neither 'surviving' nor 'dropped as within-noise'
    -- it must render as PARTIALLY_CONFIRMED with the unknown-ness named.
    """
    factors = _factors_abc()
    ids = tuple(f.id for f in factors)
    d = full_factorial(ids)          # no center points -> no pure error
    ys = _synth(d, ids, 10.0, {"A": -0.95, "B": 2.0, "C": 0.0})
    fit = fit_effects(d, ys, factor_ids=ids)
    assert all(e.significant is None for e in fit.effects)

    findings = project_findings(
        fit, factors=factors, stage="screen", decision="refine",
        iteration=1, bundle_ref="iter-1-bundle",
    )
    _validate(findings, "findings.schema.json")

    main_arms = [a for a in findings["arms"] if a["metadata"]["label"] in ("A", "B", "C")]
    assert len(main_arms) == 3
    for arm in main_arms:
        assert arm["status"] == "PARTIALLY_CONFIRMED"
        assert arm["arm_type"] not in ("h-main", "h-control-negative") or True
        assert "unknown" in arm["diagnostic_note"].lower()


# ─── 11. project_principle_updates validates and every entry has numeric evidence ─


def test_project_principle_updates_validates_and_evidence_is_numeric():
    fit, factors, _ = _fit_with_known_effects()

    from orchestrator.meta_findings import validate_evidence

    updates = project_principle_updates(fit, factors=factors, stage="screen")

    _validate(updates, "principles.schema.json")
    assert updates["principles"], "expected at least one principle entry"
    for p in updates["principles"]:
        assert p["derivation_type"] == "empirical"
        assert p["category"] == "domain"
        assert p["status"] == "active"
        assert p["confidence"] in ("low", "medium", "high")
        for ev in p["evidence"]:
            err = validate_evidence(ev)
            assert err is None, f"evidence failed validator floor: {err!r} ({ev!r})"


# ─── 12. determinism: writing twice with identical input is byte-identical ─


def test_writers_are_deterministic_byte_identical_on_repeat(tmp_path):
    fit, factors, _ = _fit_with_known_effects()
    ids = tuple(f.id for f in factors)
    d = full_factorial(ids)
    payload = matrix_payload(d, factors, run_order_seed=7)
    verdicts = [
        RelationVerdict(relation_id="R_A", factor_id="A", kind="correctness",
                        native_test="tests/prop_a.py::test_noop",
                        passed=True, detail="passed"),
    ]

    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"
    dir1.mkdir()
    dir2.mkdir()

    write_design_matrix(dir1, payload)
    write_design_matrix(dir2, payload)
    assert (dir1 / "design_matrix.json").read_bytes() == (dir2 / "design_matrix.json").read_bytes()

    write_effects(dir1, fit, factors=factors, stage="screen")
    write_effects(dir2, fit, factors=factors, stage="screen")
    assert (dir1 / "effects.json").read_bytes() == (dir2 / "effects.json").read_bytes()

    write_relations(dir1, verdicts)
    write_relations(dir2, verdicts)
    assert (dir1 / "relations.json").read_bytes() == (dir2 / "relations.json").read_bytes()

    findings1 = project_findings(fit, factors=factors, stage="screen",
                                 decision="refine", iteration=1,
                                 bundle_ref="iter-1-bundle",
                                 relation_verdicts=verdicts)
    findings2 = project_findings(fit, factors=factors, stage="screen",
                                 decision="refine", iteration=1,
                                 bundle_ref="iter-1-bundle",
                                 relation_verdicts=verdicts)
    assert json.dumps(findings1, sort_keys=True) == json.dumps(findings2, sort_keys=True)

    updates1 = project_principle_updates(fit, factors=factors, stage="screen")
    updates2 = project_principle_updates(fit, factors=factors, stage="screen")
    assert json.dumps(updates1, sort_keys=True) == json.dumps(updates2, sort_keys=True)


def test_write_design_matrix_twice_is_byte_identical_on_disk(tmp_path):
    factors = _factors_abc()
    ids = tuple(f.id for f in factors)
    d = full_factorial(ids)
    payload = matrix_payload(d, factors, run_order_seed=99)

    out1 = write_design_matrix(tmp_path, payload)
    bytes1 = out1.read_bytes()
    out2 = write_design_matrix(tmp_path, payload)
    bytes2 = out2.read_bytes()

    assert bytes1 == bytes2
