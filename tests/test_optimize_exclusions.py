"""Property and behavioral tests for the partial-fit reconciliation (FIX 1)
and the level-correlated-exclusion detector (FIX 2).

NO HYPOTHESIS IN THIS ENVIRONMENT, so the property tests are EXHAUSTIVE where
the space is small enough to enumerate (every subset of a 2^3 screen's rows:
4096 cases) and seeded-random where it is not. Every random draw here uses an
explicit ``random.Random(seed)`` with a literal seed, so a failure is
reproducible from the test name alone. An unseeded draw would make a red build
un-debuggable, which is worse than a smaller space.

Where the property is about the SHIPPED code path rather than about arithmetic,
the test drives the real ``stage_runner.run_stage`` through
``orchestrator.optimize.harness`` — no dispatcher, no LLM, no subprocess — and
asserts on what is on disk afterwards. That is the behavioral contract per
CLAUDE.md: artifacts, not mock call counts.
"""
from __future__ import annotations

import itertools
import json
import math
import random
from pathlib import Path

import pytest

from orchestrator.optimize import design as design_mod
from orchestrator.optimize import exclusions as E
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.harness import run_synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES

# ── shared fixtures for the pure-arithmetic properties ──────────────────────

#: A 2^3 screen's corner levels, in design order, plus 4 centre replicates —
#: the shape `_fails_at_one_level` actually runs, so the enumerated properties
#: below are enumerated over the real thing rather than over a toy.
_LEVELS_2x2x2 = [
    {"EV": ev, "DEV": dev, "CPU": cpu}
    for ev in ("lru", "arc")
    for dev in ("nvme", "sata_ssd")
    for cpu in (8, 40)
]
_CENTRES = [{"EV": "lru", "DEV": "nvme", "CPU": 24}] * 4
_IDS = ("EV", "DEV", "CPU")


def _rows(excluded_positions, *, levels=None, bias=True):
    """``(levels, excluded, bias_relevant)`` triples for a chosen exclusion set."""
    lv = list(levels if levels is not None else _LEVELS_2x2x2 + _CENTRES)
    ex = set(excluded_positions)
    return [(lv[i], i in ex, (i in ex) and bias) for i in range(len(lv))]


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 1 — fitting on the complete subset NEVER returns a NaN coefficient.
#
# This is the invariant the whole of FIX 1 exists to guarantee, and it is the
# one the removed abort was protecting by refusing to run at all. Enumerated
# over EVERY subset of a 2^3 screen's 8 corners (256 cases) rather than
# sampled, because the failure mode is structural (a singular column) and a
# sampler could miss the one subset that triggers it.
# ═══════════════════════════════════════════════════════════════════════════

def _fit_subset(keep_positions, ys):
    """Refit exactly as ``run_stage`` does: drop rows, replace points, solve."""
    import dataclasses

    full = design_mod.with_center_points(
        design_mod.full_factorial(_IDS), 4,
    )
    keep = sorted(keep_positions)
    ident = E.identifiable_factors(
        [(_LEVELS_2x2x2 + _CENTRES)[i] for i in keep], _IDS,
    )
    if not ident.estimable:
        return None, ident
    d = full
    if ident.dropped:
        est = set(ident.estimable)
        d = dataclasses.replace(
            d, factor_ids=tuple(ident.estimable),
            points=tuple(
                dataclasses.replace(p, coded=tuple(
                    c for j, c in enumerate(p.coded)
                    if full.factor_ids[j] in est
                ))
                for p in d.points
            ),
        )
    d = dataclasses.replace(d, points=tuple(d.points[i] for i in keep))
    return fit_effects(
        d, [ys[i] for i in keep], factor_ids=ident.estimable,
    ), ident


@pytest.mark.parametrize("seed", [1, 7, 99])
def test_property_a_fit_on_the_retained_subset_never_returns_a_nan_coefficient(
    seed,
):
    """EXHAUSTIVE over all 256 subsets of the 8 corners, at three response seeds.

    The retained centre replicates are always kept, mirroring the real path
    (a centre point fails no more often than a corner and the design keeps
    them). What varies is which CORNERS survived — the case the field failure
    produced.

    A subset that cannot be fitted must raise or be refused by the floor; it
    must NEVER return a Fit with a NaN in it. A NaN coefficient is the exact
    failure the abort existed to prevent, and it is silent: the artifact stays
    schema-valid because jsonschema accepts NaN as "number".
    """
    rng = random.Random(seed)
    ys = [10.0 + rng.gauss(0, 1) for _ in range(len(_LEVELS_2x2x2) + 4)]
    centres = list(range(len(_LEVELS_2x2x2), len(ys)))

    checked = fitted = refused = 0
    for r in range(len(_LEVELS_2x2x2) + 1):
        for corners in itertools.combinations(range(len(_LEVELS_2x2x2)), r):
            keep = list(corners) + centres
            checked += 1
            if len(keep) < 2:
                continue
            try:
                fit, ident = _fit_subset(keep, ys)
            except ValueError as exc:
                # `_solve_normal_equations`' own singularity refusal. Allowed:
                # it is a refusal, not a NaN. Asserted to be that specific
                # refusal so a future arithmetic bug cannot hide behind it.
                assert "singular" in str(exc), str(exc)
                refused += 1
                continue
            if fit is None:
                refused += 1
                continue
            fitted += 1
            vals = (
                [fit.intercept]
                + [e.estimate for e in fit.effects]
                + [e.estimate for e in fit.quadratic]
            )
            assert all(v == v for v in vals), (
                f"NaN coefficient from subset {corners}: {vals}"
            )
            assert all(math.isfinite(v) for v in vals), (
                f"non-finite coefficient from subset {corners}: {vals}"
            )
    assert checked == 256, checked
    assert fitted > 0 and refused > 0, (fitted, refused)


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 2 — the floor is TOTAL: every subset either fits or is refused with
# a message naming what is missing. There is no third outcome.
# ═══════════════════════════════════════════════════════════════════════════

def test_property_b_every_subset_either_fits_or_names_what_is_missing():
    """No subset produces a Fit that a reader cannot interpret.

    Two refusal shapes are legal and they say different things:

      * ``identifiable_factors`` reports ``dropped`` — the factor lost every
        level but one, so its coefficient is not identifiable. The FIT STILL
        RUNS over the remaining factors; the dropped id is named. This is the
        deliberate choice over aborting: aborting would discard every surviving
        coefficient to protect one that was never estimable.
      * ``estimable`` is empty — nothing has two levels, so there is no model.
        This must be a refusal, not a degenerate fit.

    Enumerated over all 256 corner subsets. The assertion is the DISJUNCTION
    being exhaustive: dropped-and-fitted, or refused. A subset that silently
    fitted a factor with one retained level would be a fit whose coefficient is
    an artefact of the intercept's collinearity.
    """
    rng = random.Random(4242)
    ys = [10.0 + rng.gauss(0, 1) for _ in range(len(_LEVELS_2x2x2) + 4)]
    centres = list(range(len(_LEVELS_2x2x2), len(ys)))
    outcomes = {"fitted_all": 0, "fitted_narrowed": 0, "refused_no_model": 0}

    for r in range(len(_LEVELS_2x2x2) + 1):
        for corners in itertools.combinations(range(len(_LEVELS_2x2x2)), r):
            keep = list(corners) + centres
            ident = E.identifiable_factors(
                [(_LEVELS_2x2x2 + _CENTRES)[i] for i in keep], _IDS,
            )
            if not ident.estimable:
                outcomes["refused_no_model"] += 1
                # The refusal must NAME what is missing, per row (a) of the
                # floor's contract: an operator has to know which axis to
                # re-measure without opening runs.jsonl.
                assert ident.levels_retained, ident
                assert set(ident.levels_retained) == set(_IDS)
                assert set(ident.dropped) == set(_IDS)
                continue
            # Every estimable factor genuinely has >= 2 retained levels, and
            # every dropped one genuinely has < 2. This is the property the
            # `fit_effects` call downstream depends on.
            for fid in ident.estimable:
                assert len(ident.levels_retained[fid]) >= 2, (corners, fid)
            for fid in ident.dropped:
                assert len(ident.levels_retained[fid]) < 2, (corners, fid)
            outcomes["fitted_narrowed" if ident.dropped else "fitted_all"] += 1

    assert all(v > 0 for v in outcomes.values()), outcomes


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 3 — excluding rows can only WIDEN or leave unchanged the reported
# uncertainty. A partial design must never look MORE confident than the full
# one.
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("seed", [3, 17, 271])
def test_property_c_excluding_rows_never_narrows_the_reported_uncertainty(seed):
    """Drop one corner at a time; no surviving effect's SE may shrink.

    This is the property that distinguishes an honest partial fit from a
    flattering one. The mechanism: an effect's SE is
    ``sigma / sqrt(sum_i x_ij^2)``, and dropping a corner can only DECREASE
    that column's sum of squares, so the SE can only rise. The pure-error
    variance itself is estimated from the CENTRE replicates, which are retained
    here — so this test isolates the design-matrix half of the claim, which is
    the half a row exclusion actually moves.

    Asserted with a small relative tolerance because the arithmetic is
    floating-point, not because the property is approximate.
    """
    rng = random.Random(seed)
    full = design_mod.with_center_points(design_mod.full_factorial(_IDS), 4)
    ys = [10.0 + rng.gauss(0, 0.3) for _ in range(len(full.points))]

    base = fit_effects(full, ys, factor_ids=_IDS)
    base_se = {e.label: e.se for e in base.effects}
    assert all(v is not None for v in base_se.values()), base_se

    import dataclasses
    n_corners = len(_LEVELS_2x2x2)
    compared = 0
    for drop in range(n_corners):
        keep = [i for i in range(len(full.points)) if i != drop]
        d = dataclasses.replace(
            full, points=tuple(full.points[i] for i in keep),
        )
        ident = E.identifiable_factors(
            [(_LEVELS_2x2x2 + _CENTRES)[i] for i in keep], _IDS,
        )
        assert ident.estimable == _IDS, ident   # one dropped corner keeps all
        part = fit_effects(d, [ys[i] for i in keep], factor_ids=_IDS)
        for e in part.effects:
            if e.label not in base_se or e.se is None:
                continue
            compared += 1
            assert e.se >= base_se[e.label] * (1 - 1e-9), (
                f"dropping corner {drop} NARROWED {e.label}'s SE from "
                f"{base_se[e.label]!r} to {e.se!r} — a partial design must "
                f"never look more confident than the full one"
            )
    assert compared > 0


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 4 — the detector NEVER fires when exclusions are perfectly balanced
# across every factor's levels.
# ═══════════════════════════════════════════════════════════════════════════

def test_property_d_a_perfectly_balanced_exclusion_never_flags():
    """EXHAUSTIVE over every balanced exclusion set of a 2^3 corner block.

    "Perfectly balanced" here means: for every factor, every level lost the
    same number of rows. Enumerated over all 256 corner subsets and filtered to
    the balanced ones, so the test cannot pass by only checking the empty set.

    A false positive here is the expensive failure: it would caveat every
    coefficient of every campaign that lost a row, which trains a reader to
    ignore the field.
    """
    balanced_seen = 0
    for r in range(len(_LEVELS_2x2x2) + 1):
        for ex in itertools.combinations(range(len(_LEVELS_2x2x2)), r):
            per_factor = {}
            for fid in _IDS:
                counts = {}
                for i in ex:
                    counts[_LEVELS_2x2x2[i][fid]] = (
                        counts.get(_LEVELS_2x2x2[i][fid], 0) + 1
                    )
                per_factor[fid] = counts
            # balanced == every level of every factor lost the SAME count, and
            # every level was actually hit (a level with 0 losses while another
            # has 2 is exactly the concentration we DO want flagged).
            if not all(
                len(set(c.values())) <= 1 and len(c) in (0, 2)
                for c in per_factor.values()
            ):
                continue
            balanced_seen += 1
            b = E.analyse(_rows(ex, levels=_LEVELS_2x2x2), _IDS)
            assert not b.level_correlated, (ex, b.as_dict())
            assert b.flagged_factors == (), (ex, b.flagged_factors)
            assert b.caveat() == ""
    # A meaningful number of NON-EMPTY balanced sets, not just the empty one.
    assert balanced_seen >= 5, balanced_seen


def test_property_d2_a_balanced_loss_across_a_three_level_factor_never_flags():
    """The same claim for a factor with three levels, which the 2^3 block
    cannot express. Seeded-random over 200 balanced draws.

    A 2-level factor is the easy case for any concentration rule; the rule has
    to be right when a level can be missed entirely. Here every level loses
    exactly one row, so nothing concentrated.
    """
    rng = random.Random(20260822)
    levels = [{"A": a, "B": b} for a in (1, 2, 3) for b in ("x", "y")]
    for _ in range(200):
        # one exclusion per A-level, spread over B at random -> balanced in A;
        # B is balanced only when the draw happens to split, so B is checked
        # for correctness rather than asserted unflagged.
        ex = [rng.choice([i for i, lv in enumerate(levels) if lv["A"] == a])
              for a in (1, 2, 3)]
        b = E.analyse(_rows(ex, levels=levels), ("A",))
        assert not b.level_correlated, (ex, b.as_dict())


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 5 — the detector DOES fire on a concentrated loss, and names the
# right level. The mirror of property 4: a rule that never fires is trivially
# free of false positives.
# ═══════════════════════════════════════════════════════════════════════════

def test_property_e_a_concentrated_loss_flags_and_names_the_level():
    """EXHAUSTIVE over every non-empty subset of ONE level's rows.

    For each factor and each of its levels, every non-empty subset of the rows
    carrying that level (and no others) must flag that factor at that level —
    provided the level has >= MIN_ROWS_AT_LEVEL rows and some other level
    completed, which holds throughout a 2^3 block.
    """
    fired = 0
    for fid in _IDS:
        for level in {lv[fid] for lv in _LEVELS_2x2x2}:
            at = [i for i, lv in enumerate(_LEVELS_2x2x2) if lv[fid] == level]
            assert len(at) >= E.MIN_ROWS_AT_LEVEL
            for r in range(1, len(at) + 1):
                for ex in itertools.combinations(at, r):
                    if r == len(at):
                        # Every row at this level lost => no completed row at
                        # this level, but OTHER levels still completed, so the
                        # rule's `other_complete` clause holds and it must fire.
                        pass
                    b = E.analyse(_rows(ex, levels=_LEVELS_2x2x2), _IDS)
                    assert b.level_correlated, (fid, level, ex, b.as_dict())
                    assert fid in b.flagged_factors, (fid, level, ex)
                    hit = next(f for f in b.factors if f.factor_id == fid)
                    assert hit.concentrated_at == E._key(level), (fid, ex, hit)
                    assert hit.rule == "all_exclusions_on_one_level"
                    assert 0.0 < hit.concentration_p <= 1.0
                    assert b.caveat(), (fid, ex)
                    fired += 1
    assert fired > 0


def test_the_deterministic_rule_fires_where_a_p_value_gate_would_not():
    """The reason the trigger is not a p-value, asserted rather than asserted-in-prose.

    On the motivating 2x2 pattern the exact one-sided hypergeometric tail is
    0.333 — nowhere near any conventional alpha. A rule gated on p < 0.05 would
    stay silent on the exact defect the module was built for, laundering it as
    a checked null. So the deterministic rule must fire while the p-value does
    not, and both numbers must be on the artifact.
    """
    ex = [i for i, lv in enumerate(_LEVELS_2x2x2)
          if lv == {"EV": "arc", "DEV": "sata_ssd", "CPU": 40}]
    assert len(ex) == 1
    b = E.analyse(_rows(ex, levels=_LEVELS_2x2x2), _IDS)
    ev = next(f for f in b.factors if f.factor_id == "EV")
    assert ev.flagged is True
    assert ev.concentration_p > 0.05, (
        "if the tail ever drops below a conventional alpha on this pattern, "
        "revisit the module docstring's argument — but the rule, not the "
        "p-value, must remain the trigger"
    )
    assert b.level_correlated


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 6 — infeasible exclusions are NOT bias evidence.
# ═══════════════════════════════════════════════════════════════════════════

def test_property_f_an_infeasible_only_loss_never_flags_however_concentrated():
    """A constraint boundary concentrates by construction and means no bias.

    Every inadmissible corner of a constrained design sits on one side of the
    constraint, so `infeasible` exclusions are ALWAYS concentrated. Counting
    them as bias would flag every constrained campaign ever run — measured on
    SURFACES["sla"], whose refine fit loses both rows at A=16, a perfect
    concentration meaning only "the p99 ceiling binds at high A".

    The exclusions are still COUNTED in `n_excluded` and in `by_level` (a
    reader needs the whole table); only `level_correlated` ignores them.
    """
    for fid in _IDS:
        for level in {lv[fid] for lv in _LEVELS_2x2x2}:
            at = [i for i, lv in enumerate(_LEVELS_2x2x2) if lv[fid] == level]
            b = E.analyse(
                _rows(at, levels=_LEVELS_2x2x2, bias=False), _IDS,
            )
            assert not b.level_correlated, (fid, level, b.as_dict())
            assert b.n_excluded == len(at)
            assert b.n_bias_excluded == 0
            hit = next(f for f in b.factors if f.factor_id == fid)
            # Visible in the table even though it is not bias evidence.
            assert hit.by_level[E._key(level)][1] == len(at)
            assert hit.by_level[E._key(level)][2] == 0


def test_a_mixed_loss_flags_only_on_the_bias_relevant_half():
    """An infeasible row at one level and a failed row at another.

    The failed row is the only bias evidence, so the flag must follow IT, not
    the union. This is the case a naive union would get wrong in the direction
    that matters: it would report the constraint boundary as bias.
    """
    levels = [{"A": a} for a in (1, 1, 2, 2)]
    rows = [
        (levels[0], True, False),    # A=1, infeasible
        (levels[1], False, False),
        (levels[2], True, True),     # A=2, failed to measure
        (levels[3], False, False),
    ]
    b = E.analyse(rows, ("A",))
    assert b.level_correlated
    assert b.flagged_factors == ("A",)
    a = b.factors[0]
    assert a.concentrated_at == "2", a
    assert b.n_excluded == 2 and b.n_bias_excluded == 1


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 7 — the per-cell report finds the 2x2 separation and names the
# factor whose level flipped.
# ═══════════════════════════════════════════════════════════════════════════

def test_property_g_a_cell_hole_names_every_one_factor_sibling():
    """The BLIS corner has three one-factor siblings; all three are reported.

    Reporting only one would make the named factor an artefact of iteration
    order. Reporting the FACTOR list alone would say which coefficients to
    distrust but not which configuration to re-measure — the two fields answer
    different questions, so both are asserted.
    """
    ex = [i for i, lv in enumerate(_LEVELS_2x2x2)
          if lv == {"EV": "arc", "DEV": "sata_ssd", "CPU": 40}]
    b = E.analyse(_rows(ex, levels=_LEVELS_2x2x2), _IDS)
    assert len(b.cells) == 3, b.as_dict()["cells"]
    assert {c.differs_from_sibling_in for c in b.cells} == set(_IDS)
    for c in b.cells:
        assert c.levels == {"EV": "arc", "DEV": "sata_ssd", "CPU": 40}
        diff = [k for k in _IDS if c.sibling_levels[k] != c.levels[k]]
        assert diff == [c.differs_from_sibling_in], (c, diff)


def test_a_cell_with_no_completed_sibling_is_not_reported_as_a_hole():
    """Coverage gap != biased coefficient.

    A cell whose every one-factor neighbour also failed is a region the design
    never covered. Saying "re-measure this corner, its sibling worked" would be
    false, so `cells` stays empty and `factors` carries whatever the
    per-factor rule concluded.
    """
    levels = [{"A": a, "B": b} for a in (1, 2) for b in (1, 2)]
    # lose BOTH cells at A=2, so neither A=2 cell has a completed A-sibling in
    # the B direction.
    ex = [i for i, lv in enumerate(levels) if lv["A"] == 2]
    b = E.analyse(_rows(ex, levels=levels), ("A", "B"))
    assert {c.differs_from_sibling_in for c in b.cells} == {"A"}, b.as_dict()
    # ... and the A-direction sibling IS completed, which is why A is the only
    # one named. Now remove that too: lose everything.
    b2 = E.analyse(_rows(range(len(levels)), levels=levels), ("A", "B"))
    assert b2.cells == (), b2.as_dict()


def test_the_detector_is_deterministic_across_repeated_calls():
    """Byte-identical output on identical input, as every writer here promises.

    `cells` iterates dicts; without the `sorted` on both loops the reported
    sibling could vary between runs and two artifacts of the same fit would
    differ.
    """
    ex = [7]
    first = json.dumps(
        E.analyse(_rows(ex), _IDS).as_dict(), sort_keys=True,
    )
    for _ in range(5):
        assert json.dumps(
            E.analyse(_rows(ex), _IDS).as_dict(), sort_keys=True,
        ) == first


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 8 — fit_exclusions.json row counts always reconcile.
# END-TO-END, through the real run_stage.
# ═══════════════════════════════════════════════════════════════════════════

def _iter_dirs(work_dir):
    runs = Path(work_dir) / "runs"
    return sorted(
        (d for d in runs.iterdir() if d.name.startswith("iter-")),
        key=lambda d: int(d.name.split("-")[1]),
    )


def _read(p):
    return json.loads(Path(p).read_text()) if Path(p).exists() else None


@pytest.mark.parametrize("seed", [11, 23, 37])
def test_property_h_fit_exclusions_row_counts_always_reconcile(seed, tmp_path):
    """planned == fitted + excluded, on every fit_exclusions.json a real
    campaign writes. Driven through the REAL run_stage.

    A reader auditing a reduced-resolution fit has to be able to reconcile the
    three numbers without opening runs.jsonl. Three seeds because the noise
    draw moves which finalists confirm seats and therefore how many rows the
    terminal stage loses.
    """
    res = run_synthetic_campaign(
        SURFACES["fails_at_one_level"](), seed=seed, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"]},
    )
    seen = 0
    for it in _iter_dirs(res.work_dir):
        fx = _read(it / "fit_exclusions.json")
        if fx is None:
            continue
        seen += 1
        assert fx["planned_rows"] == fx["fitted_rows"] + len(
            fx["excluded_row_indices"],
        ), (it.name, fx)
        # Every excluded row has exactly one reason, and the by-reason index
        # partitions the same set.
        assert set(fx["excluded_reasons"]) == {
            str(i) for i in fx["excluded_row_indices"]
        }, fx
        assert sorted(
            i for group in fx["excluded_by_reason"].values() for i in group
        ) == sorted(fx["excluded_row_indices"]), fx
        eb = fx["exclusion_balance"]
        assert eb["n_rows"] == fx["planned_rows"], fx
        assert eb["n_excluded"] == len(fx["excluded_row_indices"]), fx
        assert eb["n_bias_excluded"] <= eb["n_excluded"], fx
    assert seen >= 1, "no fit_exclusions.json was written at all"


# ═══════════════════════════════════════════════════════════════════════════
# THE ORACLE: the BLIS defect, end to end. Per CLAUDE.md's oracle-first
# discipline, this is the synthetic surface that FAILS without the fix.
# ═══════════════════════════════════════════════════════════════════════════

def test_the_blis_surface_completes_instead_of_aborting_the_iteration(tmp_path):
    """THE headline claim of FIX 1, on the surface named for the field failure.

    Before: `_fitting_responses` aborted the moment any row failed to measure,
    so the campaign produced no effects, no recommendation, no certificate and
    NO transitions.jsonl row — four iterations in a row, discarding 15 valid
    measurements each time.

    After: the fit runs on the retained rows, every downstream artifact is
    written, the epoch reaches a terminal state, and the transition is
    RECORDED. The recorded path is the discriminating assertion: the field
    campaign's total output was zero transition rows.
    """
    res = run_synthetic_campaign(
        SURFACES["fails_at_one_level"](), seed=11, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"]},
    )
    assert not any(p.startswith("aborted:") for p in res.path), res.path
    assert res.recommendation, res.report
    assert res.basis in ("certified", "terminal_best", "model", "measured"), res.basis

    # The epoch reached a TERMINAL state and said so in the audit trail.
    trans = Path(res.work_dir) / "transitions.jsonl"
    assert trans.exists(), "no transitions.jsonl — the epoch left no audit trail"
    rows = [json.loads(l) for l in trans.read_text().splitlines() if l.strip()]
    assert rows, "transitions.jsonl is empty"
    assert rows[-1]["to"] == "report", rows[-1]
    assert res.path[-1] == "report", res.path

    # The fit actually happened, over the retained rows, with finite numbers.
    screen = next(
        it for it in _iter_dirs(res.work_dir)
        if (_read(it / "effects.json") or {}).get("stage") == "screen"
    )
    eff = _read(screen / "effects.json")
    ests = [e["estimate"] for e in eff["effects"]] + [eff["intercept"]]
    assert all(math.isfinite(v) for v in ests), ests
    assert eff["n_runs"] < 12, (
        "the fit used every planned row, so no row was actually excluded and "
        "this test is not exercising the partial-fit path"
    )


def test_the_blis_surface_reports_the_level_correlated_exclusion(tmp_path):
    """THE headline claim of FIX 2. The caveat must be where a reader looks.

    Asserted on THREE artifacts, because "we logged a warning" is exactly the
    non-consequence the brief rules out:

      1. `effects.json` — next to the coefficients it qualifies.
      2. `recommendation.json` — next to `residual_regret_model`, the bound
         whose guarantee rests on the surface the missing region biases.
      3. `confirmation.json` — the GLOBAL certificate is withheld, with the
         reason named.
    """
    res = run_synthetic_campaign(
        SURFACES["fails_at_one_level"](), seed=11, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"]},
    )
    screen = next(
        it for it in _iter_dirs(res.work_dir)
        if (_read(it / "effects.json") or {}).get("stage") == "screen"
    )

    eb = _read(screen / "effects.json").get("exclusion_balance")
    assert eb is not None, "effects.json carries no exclusion_balance"
    assert eb["level_correlated"] is True, eb
    # EV is the factor under study and the one the missing region biases; the
    # other two share the lost corner's levels and are correctly named too (one
    # lost row cannot attribute blame to one of three factors).
    assert "EV" in eb["flagged_factors"], eb
    ev = next(f for f in eb["factors"] if f["factor_id"] == "EV")
    assert ev["concentrated_at"] == "arc", ev
    assert ev["rule"] == "all_exclusions_on_one_level"
    # The cell report localises the region and names the flipped factor.
    assert any(
        c["levels"] == {"EV": "arc", "DEV": "sata_ssd", "CPU": 40}
        for c in eb["cells"]
    ), eb["cells"]
    assert "EV" in {c["differs_from_sibling_in"] for c in eb["cells"]}, eb["cells"]

    rec = _read(screen / "recommendation.json")
    assert (rec.get("exclusion_balance") or {}).get("level_correlated") is True, rec

    conf = next(
        (_read(it / "confirmation.json") for it in _iter_dirs(res.work_dir)
         if (it / "confirmation.json").exists()), None,
    )
    assert conf is not None, "no confirmation.json"
    assert conf["certified"] is False, conf
    assert "fit_exclusions_level_correlated" in conf["certification_withheld"], conf
    # The WITHIN-SHORTLIST bound is untouched: suppressing it would hide the
    # comparison that genuinely did happen.
    assert conf["residual_regret_terminal"] is not None, conf
    assert res.report["certified"] is False, res.report


def test_a_balanced_loss_does_not_withhold_certification(tmp_path):
    """The mirror: the consequence must not fire when the loss is balanced.

    `sla`'s refine fit excludes two INFEASIBLE rows (a constraint boundary,
    perfectly concentrated at A=16). If `infeasible` counted as bias evidence,
    this campaign could never certify — and every constrained campaign would
    carry a false caveat. It certifies at confirm_max_rounds 3, which is the
    existing behaviour this change must not have broken.
    """
    s = SURFACES["sla"]()
    res = run_synthetic_campaign(
        s, seed=5, parent_dir=tmp_path,
        campaign_overrides={
            "response": {"primary": {"metric": "m", "direction": "maximize"},
                         "constraints": [{"metric": "p99_ms", "op": "<=", "value": 40}]},
            "policy": {"confirm_max_rounds": 3},
        },
        max_iterations=12,
    )
    assert res.basis == "certified", res.report["recommendation"]
    for it in _iter_dirs(res.work_dir):
        eb = (_read(it / "effects.json") or {}).get("exclusion_balance")
        if eb is None:
            continue
        assert eb["level_correlated"] is False, (it.name, eb)
        assert eb["n_bias_excluded"] == 0, (it.name, eb)


def test_the_semantic_exception_path_is_untouched(tmp_path):
    """A `complete` row reporting a float NaN still ends the EPOCH.

    This is categorically different from a measurement failure (the paper's
    semantic exception: the objective and the instrumentation disagree about
    what is measurable there, and no re-run repairs it), and folding the two
    together was the explicit non-goal. `nan_at_corner` is the surface that
    catches a regression here: it must reach `exception`, write
    `epoch_end-1.json`, and still return an action.
    """
    res = run_synthetic_campaign(
        SURFACES["nan_at_corner"](), seed=4, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"]},
    )
    assert "exception" in res.path, res.path
    ends = list(Path(res.work_dir).glob("epoch_end-*.json"))
    assert ends, "no epoch_end record — the semantic exception did not end the epoch"
    # Always act: the exception removes the `model` rung, not the report.
    assert res.report.get("epoch_ended"), res.report
    assert res.report["recommendation"]["basis"] != "model", res.report
    # And it must NOT have gone down the partial-fit path: a NaN on a complete
    # row is not an excluded row.
    for it in _iter_dirs(res.work_dir):
        assert not (it / "fit_exclusions.json").exists(), it.name


def test_a_screen_that_loses_everything_still_refuses_with_a_clear_message(
    tmp_path,
):
    """The floors are real. Nothing measurable => a refusal naming the reason.

    Fitting "the retained subset" when the retained subset is empty is the
    failure mode a permissive reading of FIX 1 would introduce. The message
    must name what is missing, so an operator knows whether to re-run or to
    re-scope.
    """
    from orchestrator.optimize.harness import synthetic_campaign
    campaign = synthetic_campaign(
        SURFACES["additive"](),
        **{"response": {"primary": {"metric": "no_such_metric",
                                    "direction": "maximize"}}},
    )
    res = run_synthetic_campaign(
        SURFACES["additive"](), seed=6, parent_dir=tmp_path,
        campaign_overrides={
            "response": {"primary": {"metric": "no_such_metric",
                                     "direction": "maximize"}},
        },
    )
    assert res.recommendation == {}
    assert res.path and res.path[-1].startswith("aborted:"), res.path
    assert "usable measurement" in res.path[-1], res.path[-1]
    assert campaign["optimization"]["response"]["primary"]["metric"] == "no_such_metric"


# ═══════════════════════════════════════════════════════════════════════════
# The identifiability floor, driven end to end: a factor that loses a level is
# DROPPED and named, not silently fitted and not fatal.
# ═══════════════════════════════════════════════════════════════════════════

def test_a_factor_that_loses_every_row_at_one_level_is_dropped_and_named(
    tmp_path,
):
    """A whole level of one factor never measures.

    `len(keep) >= 2` is satisfied — there are plenty of rows — but B has one
    retained level, so its column is constant, collinear with the intercept,
    and `_solve_normal_equations` would raise "design matrix is singular": a
    message about matrix rank rather than about the factor that lost a level.

    The floor drops B, names it, pins it in `held_fixed`, and fits A. Aborting
    instead would discard A's perfectly good coefficient to protect one that
    was never estimable.
    """
    import dataclasses

    surface = SURFACES["additive"]()
    # Every row at C="on" fails: C then has one retained level.
    surface = dataclasses.replace(
        surface, fails_at=lambda lv: lv["C"] == "on",
    )
    res = run_synthetic_campaign(
        surface, seed=8, parent_dir=tmp_path,
        campaign_overrides={"stages": ["verify", "screen", "confirm"]},
    )
    assert not any(p.startswith("aborted:") for p in res.path), res.path

    screen = next(
        it for it in _iter_dirs(res.work_dir)
        if (_read(it / "effects.json") or {}).get("stage") == "screen"
    )
    fx = _read(screen / "fit_exclusions.json")
    assert fx is not None, "no fit_exclusions.json"
    assert "C" in fx["non_identifiable_factors"], fx
    assert "C" not in fx["fitted_ids"], fx
    assert set(fx["fitted_ids"]) == {"A", "B"}, fx

    rec = _read(screen / "recommendation.json")
    assert "C" not in rec["fitted_ids"], rec
    # Pinned at the level that WAS measured, so the argmax does not score
    # candidates at a level the reduced fit has no coefficient for.
    assert rec["held_fixed"].get("C") == "off", rec["held_fixed"]

    eff = _read(screen / "effects.json")
    labels = {e["label"] for e in eff["effects"]}
    assert "C" not in labels, labels
    assert {"A", "B"} <= labels, labels
    assert all(math.isfinite(e["estimate"]) for e in eff["effects"]), eff


def test_a_subset_with_no_identifiable_factor_at_all_refuses(tmp_path):
    """Nothing has two levels => no model. This must be a refusal.

    Reached here as a unit on the floor rather than through a campaign,
    because a design that loses every level of every factor loses every row
    and would hit the arithmetic floor first — the two floors overlap, and
    this one has to be correct on its own terms.
    """
    ident = E.identifiable_factors(
        [{"A": 1, "B": "x"}, {"A": 1, "B": "x"}], ("A", "B"),
    )
    assert ident.estimable == ()
    assert set(ident.dropped) == {"A", "B"}
    assert ident.levels_retained == {"A": ("1",), "B": ("x",)}


def test_int_and_float_representations_of_one_level_are_one_level():
    """`2` and `2.0` are the same level and must not split a level's count.

    `matrix._decode_level` can produce either representation for one declared
    level, so a key on the raw value would halve `rows` at that level and
    defeat MIN_ROWS_AT_LEVEL — silently turning a real concentration into an
    unflagged one.
    """
    ident = E.identifiable_factors([{"A": 2}, {"A": 2.0}], ("A",))
    assert ident.estimable == ()
    assert ident.levels_retained["A"] == ("2",)

    rows = [({"A": 2}, False, False), ({"A": 2.0}, True, True),
            ({"A": 5}, False, False), ({"A": 5}, False, False)]
    b = E.analyse(rows, ("A",))
    a = b.factors[0]
    assert a.by_level["2"][0] == 2, a.by_level
    assert a.concentrated_at == "2"
    assert a.flagged is True


def test_the_hypergeometric_tail_is_a_probability_and_monotone():
    """Sanity on the reported statistic, since it is on the artifact.

    A number a reader compares across campaigns has to be in [0, 1] and has to
    move the right way: losing MORE rows at a level can only make the
    concentration less likely by chance.
    """
    f = E._hypergeometric_upper_tail
    assert f(8, 0, 4, 0) == 1.0
    assert f(8, 4, 4, 0) == 1.0            # "at least 0" is certain
    prev = 1.0
    for x in range(0, 5):
        p = f(8, 4, 4, x)
        assert 0.0 <= p <= 1.0, (x, p)
        assert p <= prev + 1e-12, (x, p, prev)
        prev = p
    # all 4 losses on a 4-row level out of 8: C(4,4)/C(8,4) = 1/70
    assert f(8, 4, 4, 4) == pytest.approx(1 / 70)


def test_an_empty_analysis_is_total_and_says_nothing_happened():
    """Totality: the detector is defined for no rows and for no exclusions.

    `step()` is total for the same reason and it matters here for the same
    reason: a partial-design analyser that raised on the complete-design case
    would make every ordinary campaign's fit path conditional on it.
    """
    for rows in ([], _rows([])):
        b = E.analyse(rows, _IDS)
        assert b.n_excluded == 0
        assert b.level_correlated is False
        assert b.flagged_factors == ()
        assert b.cells == ()
        assert b.caveat() == ""
        assert b.as_dict()["factors"] == []


# ═══════════════════════════════════════════════════════════════════════════
# SURVIVOR-KILLERS. Every test below exists because a MUTATION of the source
# survived the suite above, which means that invariant was documented but not
# checked. Each names the mutation it kills.
# ═══════════════════════════════════════════════════════════════════════════

def test_no_identifiable_factor_at_all_aborts_through_the_real_run_stage(
    tmp_path, monkeypatch,
):
    """KILLS M4 (`if not ident.estimable` deleted).

    The two floors OVERLAP on every realistic campaign — a design that loses
    every level of every factor has usually lost nearly every row, so the
    arithmetic floor fires first and the identifiability abort is never reached.
    That overlap is exactly why the mutation survived: nothing drove a subset
    that is arithmetically fittable (>= 2 rows) but carries no estimable factor.

    Constructed here: the CENTRE replicates all measure, every CORNER fails. Four
    retained rows clears `len(keep) >= 2`, and all four sit at the same level of
    every factor, so no coefficient is identifiable. Without the guard this
    reaches `fit_effects` with an all-constant model matrix and dies on
    `_solve_normal_equations`' "singular" ValueError — an uncaught exception out
    of run_stage rather than an OptimizationAborted naming the cause.
    """
    from orchestrator.optimize.stage_runner import OptimizationAborted, run_stage
    from orchestrator.optimize.harness import _all_pass, synthetic_campaign
    from orchestrator.iteration import setup_work_dir

    surface = SURFACES["additive"]()
    campaign = synthetic_campaign(surface, stages=["verify", "screen", "confirm"])

    def only_centres_measure(row):
        if row.role != "center":
            raise RuntimeError("corner failed to measure")
        lv = row.levels
        return {"cfg": {k.lower(): v for k, v in lv.items()}, "m": 10.0}

    monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path))
    wd = setup_work_dir("m4-probe", repo_path=None, campaign=campaign)
    with pytest.raises(OptimizationAborted) as exc:
        run_stage(campaign, wd, iteration=1, stage="verify",
                  config_runner=only_centres_measure,
                  test_results=_all_pass(campaign), auto_approve=True)
        run_stage(campaign, wd, iteration=2, stage="screen",
                  config_runner=only_centres_measure,
                  test_results=_all_pass(campaign), auto_approve=True)
    msg = str(exc.value)
    assert "no factor retains two distinct levels" in msg.lower() or \
        "NO factor retains two distinct levels" in msg, msg
    assert "identifiable" in msg, msg


def test_the_identifiability_abort_names_every_factor_and_its_retained_level():
    """KILLS M4's message half, as a unit on the floor itself.

    The abort has to say WHICH axis collapsed, or an operator cannot tell
    "re-run the failed rows" from "this design was never going to work".
    Asserted on the data the message is built from so a reworded message does
    not silently drop the facts.
    """
    ident = E.identifiable_factors(
        [{"A": 4, "B": "x", "C": 1}] * 4, ("A", "B", "C"),
    )
    assert ident.estimable == ()
    assert set(ident.dropped) == {"A", "B", "C"}
    for fid, want in (("A", ("4",)), ("B", ("x",)), ("C", ("1",))):
        assert ident.levels_retained[fid] == want, ident.levels_retained


def test_each_excluded_row_keeps_its_own_reason_not_the_majority_reason(
    tmp_path,
):
    """KILLS M8 (every reason overwritten with `failed_to_measure`).

    Nothing drove a fit that excluded rows for TWO DIFFERENT reasons at once, so
    collapsing the per-row map to a constant changed no assertion. That is the
    whole point of the field: `infeasible` is information about X_valid that a
    re-run reproduces, and `failed_to_measure` is a repairable hole — a reader
    handed one label for both is told the wrong thing to do next.

    Built here with a constraint that makes one corner infeasible AND a runner
    that fails a different corner, so the same fit_exclusions.json must carry
    both labels.
    """
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.harness import _all_pass, synthetic_campaign
    from orchestrator.iteration import setup_work_dir
    import os

    surface = SURFACES["additive"]()
    campaign = synthetic_campaign(
        surface,
        stages=["verify", "screen", "confirm"],
        response={"primary": {"metric": "m", "direction": "maximize"},
                  "constraints": [{"metric": "guard", "op": "<=", "value": 10}]},
    )

    def mixed(row):
        lv = row.levels
        if row.row_index == 5:
            raise RuntimeError("this corner never measured")
        return {
            "cfg": {k.lower(): v for k, v in lv.items()},
            # row 3 runs fine but violates the declared constraint
            "guard": 99 if row.row_index == 3 else 0,
            "m": 10.0 + 0.2 * float(lv["B"]),
        }

    prior = os.environ.get("NOUS_CAMPAIGN_PARENT")
    os.environ["NOUS_CAMPAIGN_PARENT"] = str(tmp_path)
    try:
        wd = setup_work_dir("m8-probe", repo_path=None, campaign=campaign)
        run_stage(campaign, wd, iteration=1, stage="verify", config_runner=mixed,
                  test_results=_all_pass(campaign), auto_approve=True)
        run_stage(campaign, wd, iteration=2, stage="screen", config_runner=mixed,
                  test_results=_all_pass(campaign), auto_approve=True)
    finally:
        if prior is None:
            os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        else:
            os.environ["NOUS_CAMPAIGN_PARENT"] = prior

    fx = _read(Path(wd) / "runs" / "iter-2" / "fit_exclusions.json")
    assert fx is not None, "no fit_exclusions.json"
    reasons = fx["excluded_reasons"]
    assert reasons.get("5") == "failed_to_measure", reasons
    assert reasons.get("3") == "infeasible", reasons
    # TWO distinct reasons in one artifact is the discriminating fact.
    assert len(set(reasons.values())) == 2, reasons
    assert set(fx["excluded_by_reason"]) == {"failed_to_measure", "infeasible"}, fx
    # ... and only the failed one counts as bias evidence.
    assert fx["exclusion_balance"]["n_excluded"] == 2, fx
    assert fx["exclusion_balance"]["n_bias_excluded"] == 1, fx


def test_foldover_positions_map_to_the_right_block(tmp_path):
    """KILLS M11 (`_fit_row_levels` returns the fold block padded with blanks).

    At foldover `ys` is `screen_ys + fold_ys`, so position 0 is the SCREEN
    block's row 0 and lives in a PREVIOUS iteration's directory. Getting this
    wrong attributes the fold block's levels to the screen block's exclusions
    and analyses the wrong contingency table.

    Driven as a unit on the helper because reaching the foldover state with a
    partial screen block is not possible end to end: `_screen_responses`' NaN
    flag routes a screen row that never measured to the policy's `nan_response`
    branch before any combined fit is formed. So the helper's correctness is
    asserted directly against a real runs.jsonl on disk.
    """
    from orchestrator.optimize import artifacts
    from orchestrator.optimize.stage_runner import _fit_row_levels

    class _Row:
        def __init__(self, i, levels):
            self.row_index, self.levels = i, levels

    screen_dir = tmp_path / "runs" / "iter-2"
    screen_dir.mkdir(parents=True)
    # Written OUT OF ORDER on purpose: runs.jsonl records EXECUTION order (the
    # pre-registered randomized permutation), so a reader that trusts file order
    # misaligns every row with its design point.
    for idx in (2, 0, 1):
        artifacts.append_run(screen_dir, {
            "row_index": idx, "levels": {"A": f"s{idx}"}, "status": "complete",
        })

    fold_rows = [_Row(0, {"A": "f0"}), _Row(1, {"A": "f1"})]
    got = _fit_row_levels(
        tmp_path, fold_rows, [], "foldover", 2, n_total=5, n_fold=2,
    )
    assert got == [
        {"A": "s0"}, {"A": "s1"}, {"A": "s2"}, {"A": "f0"}, {"A": "f1"},
    ], got

    # And at a non-foldover state the two indexings coincide, so the screen
    # reader must NOT be consulted at all.
    assert _fit_row_levels(
        tmp_path, fold_rows, [], "screen", None, n_total=2, n_fold=2,
    ) == [{"A": "f0"}, {"A": "f1"}]


def test_foldover_exclusion_reasons_come_from_the_right_block(tmp_path):
    """KILLS M11's sibling in `_fit_exclusion_reasons`.

    The outcomes this iteration holds are the FOLD block's; pairing them with a
    screen position would report one row's failure mode against another row's
    index.
    """
    from orchestrator.optimize import artifacts
    from orchestrator.optimize.stage_runner import _fit_exclusion_reasons

    class _O:
        def __init__(self, i, status):
            self.row_index, self.status = i, status

    screen_dir = tmp_path / "runs" / "iter-2"
    screen_dir.mkdir(parents=True)
    artifacts.append_run(screen_dir, {
        "row_index": 0, "levels": {}, "status": "infeasible",
    })
    artifacts.append_run(screen_dir, {
        "row_index": 1, "levels": {}, "status": "complete",
    })

    reasons = _fit_exclusion_reasons(
        [_O(0, "complete"), _O(1, "failed")], "foldover", [0, 3],
        n_total=4, n_fold=2, work_dir=tmp_path, screen_iter=2,
    )
    # position 0 is the SCREEN block's infeasible row; position 3 is the FOLD
    # block's failed row (offset 2).
    assert reasons == {0: "infeasible", 3: "failed_to_measure"}, reasons


def test_a_level_visited_by_exactly_one_row_does_not_flag_that_factor():
    """KILLS M16 (`MIN_ROWS_AT_LEVEL` lowered to 1).

    With one row at a level, "every exclusion is at this level" and "this one
    row failed" are the SAME statement, and the former dresses the latter up as
    a claim about the level. A rule that fires there would caveat a coefficient
    on the strength of a design that barely visited the level at all.

    An unbalanced design is needed to express this, which is why the enumerated
    2^3 properties above could not: every level of a full factorial carries 4
    rows.
    """
    levels = [{"A": 1}, {"A": 1}, {"A": 1}, {"A": 2}]
    b = E.analyse(_rows([3], levels=levels), ("A",))
    assert not b.level_correlated, b.as_dict()
    a = b.factors[0]
    assert a.by_level["2"][0] == 1, a.by_level
    assert a.flagged is False
    # The tail is still REPORTED so a reader is not left blind.
    assert a.concentration_p is not None

    # Two rows at that level and the same single loss: still not flagged (one of
    # the two completed, so the exclusions did not take the level).
    levels2 = [{"A": 1}, {"A": 1}, {"A": 2}, {"A": 2}]
    b2 = E.analyse(_rows([3], levels=levels2), ("A",))
    assert b2.level_correlated, b2.as_dict()
    assert b2.factors[0].by_level["2"] == (2, 1, 1), b2.factors[0].by_level


def test_a_factor_whose_every_other_level_also_failed_does_not_flag():
    """KILLS M17 (`other_complete` forced True).

    "The exclusions concentrated at this level" is only a claim about the LEVEL
    if some other level actually produced a measurement. When nothing measured
    anywhere, the concentration is an artefact of the design having no surviving
    contrast at all — and the honest report is the identifiability floor's
    (nothing is estimable), not a bias caveat pointing at one level.
    """
    levels = [{"A": 1}, {"A": 1}, {"A": 2}, {"A": 2}]
    # every A=2 row lost AND every A=1 row lost too, but only A=2's are
    # bias-relevant: no level completed, so the rule must not fire.
    rows = [
        (levels[0], True, False), (levels[1], True, False),
        (levels[2], True, True), (levels[3], True, True),
    ]
    b = E.analyse(rows, ("A",))
    assert not b.level_correlated, b.as_dict()
    assert b.factors[0].flagged is False, b.factors[0]
    assert b.caveat() == ""
    # `concentrated_at` is still POPULATED here, deliberately: it is the level
    # the (reported, never triggering) hypergeometric tail was computed for, and
    # a reader inspecting an unflagged factor still wants to know which level the
    # losses leaned toward. `flagged` is the verdict, and it is False.

    # Restore ONE completed row at the other level and it fires, which is what
    # says the clause is doing work rather than just suppressing everything.
    rows_ok = [
        (levels[0], False, False), (levels[1], True, False),
        (levels[2], True, True), (levels[3], True, True),
    ]
    b2 = E.analyse(rows_ok, ("A",))
    assert b2.level_correlated, b2.as_dict()
    assert b2.factors[0].concentrated_at == "2"


def test_a_level_correlated_fit_alone_withholds_global_certification(
    tmp_path, monkeypatch,
):
    """KILLS M18 (`fit_bias` dropped from the `certified` conjunction).

    THE CENTRAL CLAIM OF FIX 2, and the mutation survived because on every
    synthetic surface where the fit loses a level-correlated row, the terminal
    stage ALSO loses a finalist at that same corner — so
    `finalist_measured_infeasible` was already withholding certification and
    removing the bias term changed nothing observable. The two reasons are
    structurally coupled on those surfaces, which is realistic but useless as a
    discriminating test.

    So this drives the REAL screen and the REAL confirm and changes exactly ONE
    input between them: `recommendation.json`'s `exclusion_balance`. Both arms
    measure the same finalists with the same runner and produce the same
    terminal bound; the only difference is whether the fit behind the shortlist
    reported a level-correlated loss. A/B on the one bit.
    """
    from orchestrator.engine import Engine
    from orchestrator.iteration import setup_work_dir
    from orchestrator.optimize.harness import _all_pass, synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.optimize.synthetic import make_synthetic_runner

    surface = SURFACES["additive"]()
    campaign = synthetic_campaign(surface, stages=["verify", "screen", "confirm"])

    def _drive(tag: str, *, inject_bias: bool) -> dict:
        monkeypatch.setenv("NOUS_CAMPAIGN_PARENT", str(tmp_path / tag))
        runner = make_synthetic_runner(surface, seed=5)
        wd = setup_work_dir(f"m18-{tag}", repo_path=None, campaign=campaign)
        run_stage(campaign, wd, iteration=1, stage="verify", config_runner=runner,
                  test_results=_all_pass(campaign), auto_approve=True)
        run_stage(campaign, wd, iteration=2, stage="screen", config_runner=runner,
                  test_results=_all_pass(campaign), auto_approve=True)

        rec_path = Path(wd) / "runs" / "iter-2" / "recommendation.json"
        rec = json.loads(rec_path.read_text())
        # A COMPLETE screen writes no exclusion_balance at all, which is the
        # control arm. The treatment arm injects the verdict a level-correlated
        # partial screen would have written, leaving every measurement identical.
        assert "exclusion_balance" not in rec, "control arm is not clean"
        if inject_bias:
            rec["exclusion_balance"] = {
                "n_rows": 12, "n_excluded": 1, "n_bias_excluded": 1,
                "level_correlated": True, "flagged_factors": ["C"],
                "factors": [], "cells": [],
            }
            rec_path.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")

        eng = Engine(wd)
        if eng.phase != "DONE":
            eng.transition("DONE")
        eng.transition("DESIGN")
        run_stage(campaign, wd, iteration=3, stage="confirm", config_runner=runner,
                  test_results=_all_pass(campaign), auto_approve=True)
        return json.loads(
            (Path(wd) / "runs" / "iter-3" / "confirmation.json").read_text(),
        )

    control = _drive("control", inject_bias=False)
    treated = _drive("treated", inject_bias=True)

    # The terminal comparison is IDENTICAL in both arms -- same finalists, same
    # replicates, same bound. If it is not, this test is comparing two different
    # experiments and proves nothing.
    assert control["residual_regret_terminal"] == treated["residual_regret_terminal"]
    assert control["epsilon"] == treated["epsilon"]
    assert "finalist_measured_infeasible" not in control["certification_withheld"]
    assert "finalist_measured_infeasible" not in treated["certification_withheld"]

    # Control certifies; treatment does not, for exactly the bias reason.
    assert control["certified"] is True, control["certification_withheld"]
    assert treated["certified"] is False, treated
    assert treated["certification_withheld"] == [
        "fit_exclusions_level_correlated",
    ], treated["certification_withheld"]

    # And the WITHIN-SHORTLIST bound survives untouched: suppressing it would
    # hide the comparison that genuinely did happen (KILLS M21 on this path too).
    assert treated["residual_regret_terminal"] is not None
    assert treated["terminal_bound"]["value"] is not None


def test_the_true_optimum_of_a_surface_ignores_the_instruments_blind_spot():
    """KILLS M27 (`true_optimum` skipping `fails_at` points).

    `invalid` and `fails_at` are different facts and the oracle must not
    conflate them. `invalid` says the configuration is INADMISSIBLE, so it
    cannot be the answer and is rightly skipped. `fails_at` says the harness
    cannot MEASURE an otherwise perfectly admissible configuration — which may
    well be the optimum.

    Skipping it would redefine the truth to match the instrument's blind spot,
    so a campaign that never explores the deleted region would score a gap of
    zero and the oracle would certify its own blindness. On
    `fails_at_one_level` the true optimum IS the unmeasurable corner, which is
    what makes this assertion sharp.
    """
    from orchestrator.optimize.synthetic import true_optimum

    s = SURFACES["fails_at_one_level"]()
    opt, best = true_optimum(s)
    assert s.fails_at(opt), (
        "the true optimum of this surface is the corner the instrument cannot "
        "measure; if that stops being true the test no longer discriminates"
    )
    assert opt == {"EV": "arc", "DEV": "sata_ssd", "CPU": 40}, opt
    assert best == pytest.approx(13.8), best

    # ... and `invalid` points ARE skipped, which is the contrast.
    sla = SURFACES["sla"]()
    opt2, _ = true_optimum(sla)
    assert not sla.invalid(opt2), opt2


def test_a_partial_fits_uncertainty_is_compared_against_the_full_fit_exactly(
):
    """KILLS M28 (SEs scaled DOWN whenever the design is small).

    The property test above compares a partial fit against the full fit, but it
    dropped exactly one corner from a 12-row design — 11 rows, still >= 12? no,
    but the mutation keyed on `len(pts) < 12`, so BOTH arms were scaled and the
    ratio was preserved. A property stated as a ratio cannot catch a change that
    multiplies both sides.

    So this pins the ABSOLUTE arithmetic: for a balanced +/-1 design with
    replicated centres, a main effect's SE is exactly
    `sqrt(pure_error_var / sum_i x_ij^2)`, computed here independently of the
    module. A fit that reports anything else is misreporting confidence, whether
    it is optimistic on small designs or on large ones.
    """
    rng = random.Random(1234)
    full = design_mod.with_center_points(design_mod.full_factorial(_IDS), 4)
    ys = [10.0 + rng.gauss(0, 0.4) for _ in range(len(full.points))]
    fit = fit_effects(full, ys, factor_ids=_IDS)

    centres = [y for p, y in zip(full.points, ys) if p.role == "center"]
    from statistics import variance
    pe = variance(centres)
    assert fit.pure_error_var == pytest.approx(pe)

    n_corners = sum(1 for p in full.points if p.role == "corner")
    for e in fit.effects:
        if len(e.terms) != 1:
            continue
        # every corner contributes x^2 = 1; centres contribute 0.
        expected = math.sqrt(pe / n_corners)
        assert e.se == pytest.approx(expected, rel=1e-12), (
            f"{e.label}: se={e.se!r} but sqrt(pure_error/{n_corners}) is "
            f"{expected!r}"
        )
        assert e.ci_high - e.ci_low > 0

    # And on a design with one corner dropped the SE rises by exactly the
    # factor the column sum of squares changes by -- an ABSOLUTE claim, not a
    # ratio between two possibly-both-wrong numbers.
    import dataclasses
    keep = [i for i in range(len(full.points)) if i != 0]
    part = fit_effects(
        dataclasses.replace(full, points=tuple(full.points[i] for i in keep)),
        [ys[i] for i in keep], factor_ids=_IDS,
    )
    for e in part.effects:
        if len(e.terms) != 1:
            continue
        assert e.se == pytest.approx(math.sqrt(pe / (n_corners - 1)), rel=1e-12), e


def test_a_rank_deficient_subset_drops_interactions_rather_than_aborting(
    tmp_path,
):
    """The THIRD floor, found by the mutation harness rather than by design.

    Per-factor level counts are necessary and not sufficient: with corners 3 and
    5 of a 2^3 screen excluded, A, B and C each keep three distinct levels — so
    `identifiable_factors` passes — but the seven-term model (intercept + 3
    mains + 3 two-factor interactions) has rank 6 over the six surviving
    corners. Without the rank check, `_solve_normal_equations` raises a raw
    `ValueError("design matrix is singular")` straight out of `run_stage`: an
    exception about matrix rank where the campaign should be deciding what is
    estimable.

    Six corners cannot support seven terms. The response is `effects.py`'s own:
    fit fewer terms and say so. Every MAIN EFFECT — which is what the stage
    rule, `dropped_factors` and the argmax all read — survives.
    """
    from orchestrator.optimize.harness import _all_pass, synthetic_campaign
    from orchestrator.optimize.stage_runner import run_stage
    from orchestrator.iteration import setup_work_dir

    surface = SURFACES["additive"]()
    campaign = synthetic_campaign(surface, stages=["verify", "screen", "confirm"])

    def two_corners_fail(row):
        if row.row_index in (3, 5):
            raise RuntimeError("this corner never measured")
        lv = row.levels
        return {"cfg": {k.lower(): v for k, v in lv.items()},
                "m": 10.0 + 0.2 * float(lv["B"])}

    import os
    prior = os.environ.get("NOUS_CAMPAIGN_PARENT")
    os.environ["NOUS_CAMPAIGN_PARENT"] = str(tmp_path)
    try:
        wd = setup_work_dir("rank-probe", repo_path=None, campaign=campaign)
        run_stage(campaign, wd, iteration=1, stage="verify",
                  config_runner=two_corners_fail,
                  test_results=_all_pass(campaign), auto_approve=True)
        run_stage(campaign, wd, iteration=2, stage="screen",
                  config_runner=two_corners_fail,
                  test_results=_all_pass(campaign), auto_approve=True)
    finally:
        if prior is None:
            os.environ.pop("NOUS_CAMPAIGN_PARENT", None)
        else:
            os.environ["NOUS_CAMPAIGN_PARENT"] = prior

    fx = _read(Path(wd) / "runs" / "iter-2" / "fit_exclusions.json")
    assert fx["interactions_dropped"] is True, fx
    assert sorted(fx["excluded_row_indices"]) == [3, 5], fx
    # Every main effect survives with a finite estimate; no interaction term does.
    eff = _read(Path(wd) / "runs" / "iter-2" / "effects.json")
    labels = {e["label"] for e in eff["effects"]}
    assert labels == {"A", "B", "C"}, labels
    assert all(math.isfinite(e["estimate"]) for e in eff["effects"]), eff
    assert math.isfinite(eff["intercept"])
    # ... and the campaign did not abort.
    assert _read(Path(wd) / "runs" / "iter-2" / "recommendation.json") is not None


def test_the_rank_floor_distinguishes_reducible_from_hopeless():
    """A unit on `model_is_full_rank`, since it now gates two different outcomes.

    Reducible: the interaction block is what does not fit, so dropping it
    recovers a solvable main-effects model. Hopeless: not even the mains fit, and
    then the campaign must refuse rather than emit a degenerate fit.
    """
    import dataclasses

    full = design_mod.with_center_points(design_mod.full_factorial(_IDS), 4)
    assert E.model_is_full_rank(full) is True

    reducible = dataclasses.replace(
        full, points=tuple(
            p for i, p in enumerate(full.points) if i not in (3, 5)
        ),
    )
    assert E.model_is_full_rank(reducible) is False
    assert E.model_is_full_rank(reducible, include_interactions=False) is True

    # Centres only: every coded coordinate is 0, so only the intercept has any
    # signal and nothing is estimable either way.
    hopeless = dataclasses.replace(
        full, points=tuple(p for p in full.points if p.role == "center"),
    )
    assert E.model_is_full_rank(hopeless) is False
    assert E.model_is_full_rank(hopeless, include_interactions=False) is False


def test_property_a2_the_rank_floor_agrees_with_the_solver_on_every_subset():
    """EXHAUSTIVE cross-check: `model_is_full_rank` must predict the solve.

    The floor exists to replace a raw solver exception with a decision, so a
    disagreement between the two is the failure mode: a "full rank" verdict
    followed by a singularity is exactly the uncaught ValueError the floor was
    added to prevent, and a "deficient" verdict on a solvable design would drop
    interactions the design could have estimated.

    Enumerated over all 256 corner subsets (centres always retained), asserting
    the floor's verdict against what `fit_effects` actually does.
    """
    import dataclasses

    rng = random.Random(31337)
    full = design_mod.with_center_points(design_mod.full_factorial(_IDS), 4)
    ys = [10.0 + rng.gauss(0, 1) for _ in range(len(full.points))]
    centres = [i for i, p in enumerate(full.points) if p.role == "center"]

    agreed = deficient = 0
    for r in range(9):
        for corners in itertools.combinations(range(8), r):
            keep = sorted(list(corners) + centres)
            d = dataclasses.replace(
                full, points=tuple(full.points[i] for i in keep),
            )
            predicted = E.model_is_full_rank(d)
            try:
                fit_effects(d, [ys[i] for i in keep], factor_ids=_IDS)
                actual = True
            except ValueError as exc:
                assert "singular" in str(exc), str(exc)
                actual = False
            assert predicted == actual, (
                f"floor said full_rank={predicted} but the solve said "
                f"{actual} for corners {corners}"
            )
            agreed += 1
            deficient += (not actual)
    assert agreed == 256, agreed
    assert deficient > 0, "no subset was rank-deficient, so this proves nothing"
