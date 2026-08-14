"""Behavioral tests for matrix expansion and fidelity checking.

``expand`` turns a coded design row into a runnable config via each
factor's ``apply`` spec -- the seam that removes the LLM from the inner
loop. ``matrix_payload`` records the pre-registered matrix (including a
randomized-but-reproducible run order) so ``check_fidelity`` can later
verify that what actually ran matches what was declared. Float
comparisons use ``math.isclose`` -- decoded/grid-snapped levels carry
representation error and ``==`` would be flaky.
"""
from __future__ import annotations

import math

from orchestrator.optimize.design import (
    DesignPoint,
    Design,
    alias_pairs,
    fractional_factorial,
    full_factorial,
    with_center_points,
)
from orchestrator.optimize.factors import parse_factors
from orchestrator.optimize.matrix import (
    check_fidelity,
    check_invariants,
    expand,
    matrix_payload,
    randomized_run_order,
)


def _numeric_raw(**over):
    raw = {
        "id": "L1", "name": "queue_count", "type": "numeric",
        "levels": [2, 4, 8, 16], "grid": 1,
        "apply": "--queues={level}",
        "manipulation": {"observable": "telemetry.queue_count",
                         "op": "==", "value": "{level}"},
        "relations": [{"id": "R1", "kind": "correctness",
                       "statement": "baseline reproduces baseline",
                       "native_test": "tests/prop_q.py::test_noop"}],
    }
    raw.update(over)
    return raw


def _choice_raw(**over):
    raw = {
        "id": "L5", "name": "batching", "type": "choice",
        "levels": ["off", "on"],
        "apply": {"kind": "env_var", "name": "CERTUS_BATCHING", "value": "{level}"},
        "manipulation": {"observable": "telemetry.mean_batch_size",
                         "op": ">", "value": 1, "when": "on"},
        "relations": [{"id": "R3", "kind": "correctness",
                       "statement": "off is byte-identical to baseline",
                       "native_test": "tests/prop_b.py::test_off_noop"}],
    }
    raw.update(over)
    return raw


def _patch_raw(**over):
    raw = {
        "id": "L9", "name": "min_peak", "type": "numeric",
        "levels": [0.01, 0.05], "grid": 0.01,
        "apply": {"kind": "config_patch", "path": "strategy.json",
                  "pointer": "/filters/min_peak", "value": "{level}"},
        "manipulation": {"observable": "config.min_peak", "op": "==", "value": "{level}"},
        "relations": [{"id": "R9", "kind": "correctness",
                       "statement": "patch round-trips",
                       "native_test": "tests/prop_p.py::test_patch"}],
    }
    raw.update(over)
    return raw


# --- 1. one ConfigRow per design point, in design order ---------------

def test_expand_produces_one_row_per_design_point_in_order():
    fs = parse_factors([_numeric_raw(), _choice_raw()])
    design = full_factorial(("L1", "L5"))
    rows = expand(design, fs)
    assert len(rows) == len(design.points)
    assert [r.row_index for r in rows] == list(range(len(design.points)))


# --- 2. numeric factor coded -1 / +1 yields low / high screen level ----

def test_numeric_factor_coded_extremes_map_to_screen_levels():
    fs = parse_factors([_numeric_raw()])
    design = Design(points=(DesignPoint(coded=(-1.0,)), DesignPoint(coded=(1.0,))),
                     factor_ids=("L1",))
    rows = expand(design, fs)
    assert rows[0].levels["L1"] == 2
    assert rows[1].levels["L1"] == 16


# --- 3. cli_flag apply renders {level} into apply["cli_args"] ----------

def test_cli_flag_apply_renders_into_cli_args():
    fs = parse_factors([_numeric_raw()])
    design = Design(points=(DesignPoint(coded=(-1.0,)),), factor_ids=("L1",))
    row = expand(design, fs)[0]
    assert row.apply["cli_args"] == ["--queues=2"]


# --- 4. env_var apply renders into apply["env"] -------------------------

def test_env_var_apply_renders_into_env_dict():
    fs = parse_factors([_choice_raw()])
    design = Design(points=(DesignPoint(coded=(1.0,)),), factor_ids=("L5",))
    row = expand(design, fs)[0]
    assert row.apply["env"] == {"CERTUS_BATCHING": "on"}


# --- 5. config_patch apply renders path/pointer/value -------------------

def test_config_patch_apply_renders_path_pointer_value():
    fs = parse_factors([_patch_raw()])
    design = Design(points=(DesignPoint(coded=(-1.0,)),), factor_ids=("L9",))
    row = expand(design, fs)[0]
    assert row.apply["patches"] == [
        {"path": "strategy.json", "pointer": "/filters/min_peak", "value": 0.01},
    ]


# --- 6. center-point rows: role == "center", midpoint / pinned levels --

def test_center_point_rows_carry_grid_snapped_numeric_midpoint():
    fs = parse_factors([_numeric_raw()])
    design = with_center_points(full_factorial(("L1",)), 1)
    rows = expand(design, fs)
    center = [r for r in rows if r.role == "center"][0]
    assert math.isclose(center.levels["L1"], 9.0, rel_tol=1e-9, abs_tol=1e-12)


def test_center_point_rows_pin_choice_factor_to_low_and_flag_it():
    fs = parse_factors([_choice_raw()])
    design = with_center_points(full_factorial(("L5",)), 1)
    rows = expand(design, fs)
    center = [r for r in rows if r.role == "center"][0]
    assert center.levels["L5"] == "off"
    assert center.apply.get("center_choice_pinned") == {"L5": True}


# --- 7. randomized_run_order: permutation, reproducible, seed-sensitive -

def test_randomized_run_order_is_a_reproducible_permutation():
    a = randomized_run_order(16, seed=42)
    b = randomized_run_order(16, seed=42)
    c = randomized_run_order(16, seed=43)
    assert sorted(a) == list(range(16))
    assert a == b
    assert a != c


# --- 8. matrix_payload includes required top-level keys and one row ----

def test_matrix_payload_has_required_keys_and_one_entry_per_row():
    fs = parse_factors([_numeric_raw(), _choice_raw()])
    design = full_factorial(("L1", "L5"))
    payload = matrix_payload(design, fs, run_order_seed=7)
    for key in ("factor_ids", "resolution", "generators", "aliases",
                "run_order", "run_order_seed", "rows"):
        assert key in payload
    assert len(payload["rows"]) == len(design.points)
    assert sorted(payload["run_order"]) == list(range(len(design.points)))
    assert payload["run_order_seed"] == 7


# --- fix round 1: aliases populated from design.alias_pairs -------------

def test_matrix_payload_reports_alias_pairs_for_a_confounded_design():
    ids = ("A", "B", "C", "D", "E", "F", "G")
    fs = parse_factors([_numeric_raw(id=i, name=i) for i in ids])
    design = fractional_factorial(ids, resolution=3)
    payload = matrix_payload(design, fs, run_order_seed=1)
    assert len(payload["aliases"]) == len(alias_pairs(design))
    assert payload["aliases"], "resolution-III design must report aliasing"


def test_matrix_payload_reports_no_aliases_for_a_resolution_v_design():
    ids = ("A", "B", "C", "D", "E")
    fs = parse_factors([_numeric_raw(id=i, name=i) for i in ids])
    design = fractional_factorial(ids, resolution=5)
    payload = matrix_payload(design, fs, run_order_seed=1)
    assert payload["aliases"] == []


# --- 9. check_fidelity([]) when runs match the payload exactly ---------

def test_check_fidelity_empty_when_runs_match_payload():
    fs = parse_factors([_numeric_raw()])
    design = full_factorial(("L1",))
    payload = matrix_payload(design, fs, run_order_seed=1)
    runs = [{"row_index": r["row_index"], "levels": r["levels"]} for r in payload["rows"]]
    assert check_fidelity(payload, runs) == []


# --- 10. check_fidelity reports level drift with factor/expected/observed

def test_check_fidelity_reports_level_drift():
    fs = parse_factors([_numeric_raw()])
    design = full_factorial(("L1",))
    payload = matrix_payload(design, fs, run_order_seed=1)
    runs = [{"row_index": r["row_index"], "levels": dict(r["levels"])} for r in payload["rows"]]
    runs[0]["levels"]["L1"] = 999
    violations = check_fidelity(payload, runs)
    assert len(violations) == 1
    assert "L1" in violations[0]
    assert "999" in violations[0]
    expected = payload["rows"][0]["levels"]["L1"]
    assert str(expected) in violations[0]


# --- 11. check_fidelity reports a missing planned row (skipped cell) ---

def test_check_fidelity_reports_missing_planned_row():
    fs = parse_factors([_numeric_raw()])
    design = full_factorial(("L1",))
    payload = matrix_payload(design, fs, run_order_seed=1)
    runs = [{"row_index": r["row_index"], "levels": r["levels"]} for r in payload["rows"][1:]]
    violations = check_fidelity(payload, runs)
    assert any("0" in v and ("missing" in v.lower() or "skip" in v.lower()) for v in violations)


# --- 12. check_fidelity reports an unplanned extra run ------------------

def test_check_fidelity_reports_unplanned_extra_run():
    fs = parse_factors([_numeric_raw()])
    design = full_factorial(("L1",))
    payload = matrix_payload(design, fs, run_order_seed=1)
    runs = [{"row_index": r["row_index"], "levels": r["levels"]} for r in payload["rows"]]
    runs.append({"row_index": 99, "levels": {"L1": 2}})
    violations = check_fidelity(payload, runs)
    assert any("99" in v for v in violations)


# --- 13. check_invariants: [] when all hold; one string per violation --

def test_check_invariants_empty_when_all_hold():
    invariants = [{"id": "I1", "statement": "connector is P2P",
                   "observable": "telemetry.transfer_path", "op": "==", "value": "p2p"}]
    assert check_invariants(invariants, {"telemetry": {"transfer_path": "p2p"}}) == []


def test_check_invariants_one_string_per_violation_naming_id_and_statement():
    invariants = [
        {"id": "I1", "statement": "connector is P2P",
         "observable": "telemetry.transfer_path", "op": "==", "value": "p2p"},
        {"id": "I2", "statement": "queue depth positive",
         "observable": "telemetry.queue_depth", "op": ">", "value": 0},
    ]
    observed = {"telemetry": {"transfer_path": "relay", "queue_depth": 5}}
    violations = check_invariants(invariants, observed)
    assert len(violations) == 1
    assert "I1" in violations[0]
    assert "connector is P2P" in violations[0]


# --- 14. check_invariants treats a missing observable as a violation ---

def test_check_invariants_missing_observable_is_a_violation():
    invariants = [{"id": "I3", "statement": "batch size recorded",
                   "observable": "telemetry.mean_batch_size", "op": ">", "value": 0}]
    violations = check_invariants(invariants, {"telemetry": {}})
    assert len(violations) == 1
    assert "I3" in violations[0]
