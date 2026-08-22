"""The synthetic target is the oracle for the whole optimization kind.

Every surface knows its own optimum, so a campaign's recommendation can be
judged against truth rather than against artifacts. Zero LLM, zero subprocess
in the in-process runner; the CLI exists so the same surface can be a real
run_command for smoke tests.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys

import pytest

from orchestrator.optimize.matrix import ConfigRow
from orchestrator.optimize.synthetic import (
    SURFACES, Surface, candidate_grid, make_synthetic_runner, true_optimum,
)


def _row(levels, idx=0):
    return ConfigRow(row_index=idx, levels=dict(levels), role="corner",
                     replicate=0, apply={})


@pytest.mark.parametrize("key", sorted(SURFACES))
def test_every_surface_declares_parseable_factors_and_a_reachable_optimum(key):
    from orchestrator.optimize.factors import parse_factors
    s = SURFACES[key]()
    parse_factors(list(s.factors))                      # valid campaign factors
    opt, best = true_optimum(s)
    assert set(opt) == {f["id"] for f in s.factors}
    assert math.isfinite(best)
    if s.invalid is not None:
        assert not s.invalid(opt)                       # optimum is inside X_valid


@pytest.mark.parametrize("key", sorted(SURFACES))
def test_every_surface_names_itself_by_its_registry_key(key):
    assert SURFACES[key]().name == key


def test_true_optimum_of_the_saddle_is_a_corner_not_the_stationary_point():
    s = SURFACES["saddle"]()
    opt, best = true_optimum(s)
    # f = 10 + 0.05(A-9)^2 - 0.05(B-11)^2 : A is CONVEX, so its argmax is a
    # hull edge (2 and 16 are equidistant from 9 and tie at 12.45); B is
    # concave, so its argmax IS its stationary value 11 -- which the grid
    # contains. The point of the surface is that solving grad = 0 gives
    # (9, 11), the minimum in A, and reporting it is the bug.
    assert opt["A"] in (2, 16)
    assert opt["B"] == 11
    assert opt != {"A": 9, "B": 11}
    assert best > s.fn({"A": 9, "B": 11})


def test_bowl_optimum_is_the_interior_stationary_point():
    opt, _ = true_optimum(SURFACES["bowl"]())
    assert opt == {"A": 9, "B": 11}


def test_bowl_out_of_hull_optimum_sits_on_the_hull_boundary():
    opt, _ = true_optimum(SURFACES["bowl_out_of_hull"]())
    # true stationary point is A=30, outside the declared [2, 16] hull
    assert opt["A"] == 16


def test_runner_emits_metric_manipulation_observables_and_seeded_noise():
    s = SURFACES["additive"]()
    r1 = make_synthetic_runner(s, seed=1)
    r2 = make_synthetic_runner(s, seed=1)
    o1 = r1(_row({"A": 4, "B": 8, "C": "on"}))
    o2 = r2(_row({"A": 4, "B": 8, "C": "on"}))
    assert o1["cfg"] == {"a": 4, "b": 8, "c": "on"}
    assert o1["m"] == o2["m"]                            # same seed, same noise
    assert abs(o1["m"] - s.fn({"A": 4, "B": 8, "C": "on"})) < 5 * s.noise_sd + 1e-9


def test_runner_observation_satisfies_every_manipulation_predicate():
    from orchestrator.optimize.predicates import evaluate
    s = SURFACES["additive"]()
    levels = {"A": 4, "B": 8, "C": "on"}
    obs = make_synthetic_runner(s, seed=0)(_row(levels))
    for f in s.factors:
        verdict = evaluate(f["manipulation"], obs, level=levels[f["id"]])
        assert verdict.ok, verdict.detail


def test_different_seeds_give_different_noise_draws():
    s = SURFACES["additive"]()
    a = make_synthetic_runner(s, seed=1)(_row({"A": 4, "B": 8, "C": "on"}))["m"]
    b = make_synthetic_runner(s, seed=2)(_row({"A": 4, "B": 8, "C": "on"}))["m"]
    assert a != b


def test_drift_surface_adds_run_counter_drift():
    s = SURFACES["drift"]()
    r = make_synthetic_runner(s, seed=0)
    first = r(_row({"A": 2, "B": 2}))["m"]
    for _ in range(9):
        r(_row({"A": 2, "B": 2}))
    tenth = r(_row({"A": 2, "B": 2}))["m"]
    assert tenth - first == pytest.approx(10 * s.drift_per_run, abs=6 * s.noise_sd)


def test_non_drift_surfaces_have_no_run_counter_trend():
    s = SURFACES["additive"]()
    assert s.drift_per_run == 0.0


def test_nan_surface_emits_nan_only_at_the_declared_corner():
    s = SURFACES["nan_at_corner"]()
    r = make_synthetic_runner(s, seed=0)
    assert math.isnan(r(_row({"A": 16, "B": 16}))["m"])
    assert math.isfinite(r(_row({"A": 2, "B": 16}))["m"])


def test_sla_surface_emits_the_constraint_observable():
    s = SURFACES["sla"]()
    obs = make_synthetic_runner(s, seed=0)(_row({"A": 16, "B": 16}))
    assert obs["p99_ms"] == 2 * 16 + 16
    assert s.invalid({"A": 16, "B": 16}) is True


def test_sla_optimum_is_the_best_point_that_still_meets_the_sla():
    s = SURFACES["sla"]()
    opt, _ = true_optimum(s)
    assert 2 * opt["A"] + opt["B"] <= 40
    # unconstrained argmax (A=16, B=16) would beat it
    assert s.fn({"A": 16, "B": 16}) > s.fn(opt)


def test_interaction_only_has_null_main_effects_over_the_screen_pair():
    s = SURFACES["interaction_only"]()
    lv = dict.fromkeys(("A", "B", "C", "D"), 2)
    at_low = s.fn(lv)
    at_high = s.fn({**lv, "A": 16})
    # A's main effect averaged over B is zero because B is centred at 9
    other = {**lv, "B": 16}
    assert (at_high - at_low) + (s.fn({**other, "A": 16}) - s.fn(other)) == \
        pytest.approx(0.0)


def test_choice_x_numeric_optimum_needs_the_choice_at_on():
    s = SURFACES["choice_x_numeric"]()
    opt, _ = true_optimum(s)
    assert opt["C"] == "on"
    # held at off, more A is strictly worse
    assert s.fn({"A": 16, "C": "off"}) < s.fn({"A": 2, "C": "off"})


def test_candidate_grid_enumerates_declared_levels_and_snapped_interior():
    s = SURFACES["bowl"]()
    grid = candidate_grid(list(s.factors))
    assert {"A": 2, "B": 2} in grid and {"A": 16, "B": 16} in grid
    assert {"A": 9, "B": 11} in grid                    # interior grid point


def test_candidate_grid_is_deterministic_and_duplicate_free():
    factors = list(SURFACES["bowl"]().factors)
    first = candidate_grid(factors)
    assert first == candidate_grid(factors)
    assert len(first) == len({tuple(sorted(d.items())) for d in first})


def test_candidate_grid_of_a_choice_factor_uses_declared_levels_only():
    grid = candidate_grid(list(SURFACES["choice_x_numeric"]().factors))
    assert {row["C"] for row in grid} == {"off", "on"}


def test_cli_emits_the_same_json_as_the_in_process_runner():
    s = SURFACES["additive"]()
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.optimize.synthetic",
         "--surface", "additive", "--seed", "3", "--a=4", "--b=8", "--c=on"],
        capture_output=True, text=True, check=True,
    )
    obs = json.loads(proc.stdout.strip().splitlines()[-1])
    assert obs["m"] == make_synthetic_runner(s, seed=3)(_row({"A": 4, "B": 8, "C": "on"}))["m"]


def test_cli_rejects_an_unknown_factor_flag():
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.optimize.synthetic",
         "--surface", "additive", "--zzz=1"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "zzz" in proc.stderr


def test_cli_rejects_a_missing_factor_flag_instead_of_raising_keyerror():
    # Omitting --b and --c used to reach surface.fn with an incomplete levels
    # dict and die on a bare KeyError traceback with exit 1.
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.optimize.synthetic",
         "--surface", "additive", "--a=4"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "--b" in proc.stderr and "--c" in proc.stderr
    assert proc.stdout.strip() == ""            # no half-formed observation


def test_cli_accepts_flags_in_any_order_once_all_are_present():
    s = SURFACES["additive"]()
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.optimize.synthetic",
         "--surface", "additive", "--seed", "3", "--c=on", "--b=8", "--a=4"],
        capture_output=True, text=True, check=True,
    )
    obs = json.loads(proc.stdout.strip().splitlines()[-1])
    assert obs["m"] == make_synthetic_runner(s, seed=3)(
        _row({"A": 4, "B": 8, "C": "on"}))["m"]


def test_surface_is_a_frozen_value_type():
    s = SURFACES["additive"]()
    assert isinstance(s, Surface)
    with pytest.raises(Exception):
        s.name = "mutated"  # type: ignore[misc]
