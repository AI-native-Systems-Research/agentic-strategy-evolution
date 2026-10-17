"""Aliasing is a resource decision: fold over only when it can change the answer.

Spec §3.4 / paper §Illustrative: "If every plausible resolution of an alias gives
the same winner, resolving it cannot change the decision; if one can change the
winner, the policy may spend a registered foldover." The two end-to-end tests
below are that sentence, one clause each:

  * ``interaction_only`` has a strong ``AB`` effect and null mains. At resolution
    IV (8 runs) ``AB`` is aliased with ``CD``; attributing the shared estimate to
    ``CD`` instead names a materially worse configuration, so the alias IS
    consequential and the policy MUST spend the foldover — and the combined fit
    must then land on the true optimum.
  * an additive four-factor surface has no interaction anywhere in its truth, so
    every resolution of every alias names the same epsilon-optimal winner and the
    policy MUST NOT spend the block.

Both must discriminate. A ``alias_consequential`` stubbed to always return ``[]``
fails the first; stubbed to always return a pair, it fails the second. Zero model
calls anywhere: the whole campaign is arithmetic over a synthetic surface.
"""
from __future__ import annotations

import dataclasses
import itertools
import json
from pathlib import Path

from orchestrator.optimize.design import (
    Design,
    DesignPoint,
    alias_pairs,
    combine,
    foldover,
    fractional_factorial,
    with_center_points,
)
from orchestrator.optimize.effects import fit_effects
from orchestrator.optimize.harness import run_synthetic_campaign, synthetic_campaign
from orchestrator.optimize.synthetic import SURFACES, _numeric

_RES4_OVERRIDES = {
    "design": {
        "screen": {"resolution": 4, "center_points": 4},
        "confirm": {"replicates": 3, "shortlist_size": 3},
    },
}


def _additive_four_factor():
    """``additive`` re-cast over four 2-level numerics, truth strictly additive.

    The stock surface has three factors (one of them a ``choice``), which at
    resolution IV falls back to a full factorial and aliases nothing — so it
    could not discriminate. Four 2-level numerics is the smallest shape that
    actually gets a resolution-IV design with real aliasing AND has no
    interaction in its truth, which is what makes "does not fold over" a claim
    about the decision rule rather than about the absence of an alias.
    """
    s = SURFACES["additive"]()
    return dataclasses.replace(
        s,
        factors=tuple(_numeric(f, levels=(2, 16)) for f in "ABCD"),
        fn=lambda lv: 10 + 0.1 * lv["A"] + 0.2 * lv["B"] - 0.05 * lv["C"],
    )


# ─── the alias-aware fit (D1's other half: surfacing what it detected) ──────


def test_resolution_iv_screen_records_which_terms_were_aliased_together():
    """`alias_classes` was computed and thrown away; now it reaches the Effect.

    Collapsing the aliased column is what makes a resolution-IV screen fittable
    at all (without it `X^T X` is singular). But collapsing WITHOUT recording
    which term went where leaves the confounding knowable only as a design-level
    label pair — with no link to the coefficient that carries the shared
    estimate, which is the link `alias_consequential` needs.
    """
    d = with_center_points(fractional_factorial(list("ABCD"), resolution=4), 4)
    fit = fit_effects(
        d, [float(i) for i in range(len(d.points))], factor_ids=list("ABCD"),
    )
    labels = {e.label: e for e in fit.effects}
    assert "AB" in labels and "CD" not in labels
    assert labels["AB"].aliased_with == ((("C", "D"), 1.0),)
    # The design-level record is unchanged: both views of the same fact.
    assert ("AB", "CD") in fit.aliases


def test_a_negated_alias_records_sign_minus_one_and_the_flipped_estimate():
    """The sign is the difference between +2 and -2, so it cannot be dropped.

    For an orthogonal +/-1 design `beta = sum_i x_ij y_i / N`, so regressing on
    `-x` instead of `x` returns exactly `-beta`. Here `C = -A*B` by construction
    and the response is driven purely by `C` at `+2.0`: the fit attributes
    `+2.0` to `C`, and the alternative reading of that same column (`AB`) is
    therefore `-2.0`. An implementation that recorded the alias without its sign
    would let a consumer relabel `+2.0` as `AB` and claim the interaction pushes
    the response UP when it pushes it down.
    """
    pts = [
        DesignPoint(coded=(float(a), float(b), float(-a * b)))
        for a, b in itertools.product((-1, 1), repeat=2)
    ]
    pts += [
        DesignPoint(coded=(0.0, 0.0, 0.0), role="center", replicate=i)
        for i in range(4)
    ]
    d = Design(points=tuple(pts), factor_ids=("A", "B", "C"),
               kind="fractional", resolution=3)
    ys = [10.0 + 2.0 * p.coded[2] for p in d.points]
    fit = fit_effects(d, ys, factor_ids=("A", "B", "C"))
    c = next(e for e in fit.effects if e.label == "C")
    assert c.estimate == 2.0
    assert c.aliased_with == ((("A", "B"), -1.0),)
    # No separate AB column was added — that is the collapse.
    assert "AB" not in {e.label for e in fit.effects}


def test_resolution_v_records_no_aliasing_on_any_effect():
    """No regression: at resolution V nothing coincides, so nothing is recorded."""
    d = with_center_points(fractional_factorial(list("ABCDE"), resolution=5), 4)
    fit = fit_effects(
        d, [float((i * 3) % 7) + 1 for i in range(len(d.points))],
        factor_ids=list("ABCDE"),
    )
    assert all(e.aliased_with == () for e in fit.effects)
    assert not fit.aliases


# ─── the fold blocks themselves ────────────────────────────────────────────


def test_single_factor_foldover_separates_ab_from_cd():
    base = fractional_factorial(list("ABCD"), resolution=4)
    assert alias_pairs(base) == [("AB", "CD"), ("AC", "BD"), ("AD", "BC")]
    both = combine(base, foldover(base, on="A"))
    assert ("AB", "CD") not in alias_pairs(both)
    assert ("AC", "BD") not in alias_pairs(both)
    # And the combined design can actually estimate all six interactions, which
    # is what the spent runs bought.
    fit = fit_effects(
        both, [float((i * 5) % 13) for i in range(len(both.points))],
        factor_ids=list("ABCD"),
    )
    assert {"AB", "AC", "AD", "BC", "BD", "CD"} <= {e.label for e in fit.effects}
    assert both.folded_on == "A"


def test_full_foldover_of_resolution_iii_clears_mains():
    base = fractional_factorial(list("ABCDEFG"), resolution=3)
    assert any(len(b) == 1 for _, b in alias_pairs(base))
    both = combine(base, foldover(base))
    assert not any(len(b) == 1 for _, b in alias_pairs(both))
    assert both.folded_on is None


def test_foldover_replicates_the_centre_points_rather_than_dropping_them():
    """The fold block is a fresh set of runs, so it needs its own pure error."""
    base = with_center_points(fractional_factorial(list("ABCD"), resolution=4), 4)
    fold = foldover(base, on="B")
    assert len(fold.corners) == len(base.corners)
    assert sum(1 for p in fold.points if p.role == "center") == 4
    assert fold.kind == "foldover" and fold.resolution is None


def test_foldover_rejects_a_factor_the_design_does_not_have():
    import pytest

    base = fractional_factorial(list("ABCD"), resolution=4)
    with pytest.raises(ValueError, match="cannot fold over on 'Z'"):
        foldover(base, on="Z")


def test_combine_rejects_designs_over_different_factors():
    import pytest

    a = fractional_factorial(list("ABCD"), resolution=4)
    b = fractional_factorial(list("ABCDE"), resolution=5)
    with pytest.raises(ValueError, match="different factors"):
        combine(a, b)


# ─── the decision rule ─────────────────────────────────────────────────────


def _screen_fit_for(surface, *, seed):
    from orchestrator.optimize import matrix
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.synthetic import make_synthetic_runner

    factors = parse_factors([dict(f) for f in surface.factors])
    d = with_center_points(fractional_factorial(list("ABCD"), resolution=4), 4)
    run = make_synthetic_runner(surface, seed=seed)
    ys = [run(r)["m"] for r in matrix.expand(d, factors)]
    return fit_effects(d, ys, factor_ids=tuple("ABCD")), factors


def test_alias_consequential_fires_on_every_seed_of_an_interaction_surface():
    """Not "on the seed the end-to-end test happens to use".

    A bare `alt.levels != base.levels` comparison fired on only 16 of these 30
    seeds, because removing the kept term leaves the factors it spanned
    unconstrained and `recommend`'s tie-break sometimes lands on the same corner
    anyway. Quantifying over the alternative resolution's own epsilon-optimal set
    — the paper's "every plausible resolution" — makes the answer a property of
    the surface rather than of the tie-break.
    """
    from orchestrator.optimize.decide import alias_consequential

    s = SURFACES["interaction_only"]()
    for seed in range(30):
        fit, factors = _screen_fit_for(s, seed=seed)
        pairs = alias_consequential(
            fit, factors, direction="maximize", fitted_ids=tuple("ABCD"),
            held_fixed={},
        )
        assert ("AB", "CD") in pairs, (seed, pairs)


def test_alias_consequential_is_silent_on_every_seed_of_an_additive_surface():
    """The other half of the same claim; a bare level comparison fired on 12/30."""
    from orchestrator.optimize.decide import alias_consequential

    s = _additive_four_factor()
    for seed in range(30):
        fit, factors = _screen_fit_for(s, seed=seed)
        pairs = alias_consequential(
            fit, factors, direction="maximize", fitted_ids=tuple("ABCD"),
            held_fixed={},
        )
        assert pairs == [], (seed, pairs)


def test_fold_on_picks_a_full_fold_at_resolution_iii_and_a_column_above_it():
    """Which flavour of foldover, and which column — both from the design.

    Resolution III aliases 2fi onto MAINS, and only a full foldover clears that;
    resolution IV aliases 2fi with each other, which one negated column
    resolves. Getting this backwards spends the block and leaves the alias
    exactly where it was.
    """
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _fold_on

    f7 = parse_factors([_numeric(x, levels=(2, 16)) for x in "ABCDEFG"])
    assert _fold_on(f7, {"screen": {"resolution": 3}}, [("A", "BD")]) is None
    f4 = parse_factors([_numeric(x, levels=(2, 16)) for x in "ABCD"])
    assert _fold_on(f4, {"screen": {"resolution": 4}}, [("AB", "CD")]) == "A"
    # The label is parsed by matching declared ids, not by splitting characters:
    # a campaign may declare multi-character factor ids.
    fkv = parse_factors([_numeric(x, levels=(2, 16)) for x in ("KV", "BS", "TP", "QQ")])
    assert _fold_on(
        fkv, {"screen": {"resolution": 4}}, [("KVBS", "TPQQ")],
    ) == "KV"


def test_a_full_foldover_of_a_resolution_iii_screen_clears_its_mains():
    """The res-III path through `_build_design`, end to end on the designs."""
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.stage_runner import _build_design

    factors = parse_factors([_numeric(x, levels=(2, 16)) for x in "ABCDEFG"])
    cfg = {"screen": {"resolution": 3, "center_points": 4}}
    screen = _build_design(factors, cfg, "screen")
    fold = _build_design(factors, cfg, "foldover", fold_on=None)
    assert fold.kind == "foldover" and fold.folded_on is None
    assert any(len(b) == 1 for _, b in alias_pairs(screen))
    assert not any(len(b) == 1 for _, b in alias_pairs(combine(screen, fold)))


def test_alias_consequential_is_empty_when_nothing_is_aliased():
    from orchestrator.optimize.decide import alias_consequential
    from orchestrator.optimize.factors import parse_factors

    s = SURFACES["interaction_only"]()
    factors = parse_factors([dict(f) for f in s.factors])
    d = with_center_points(fractional_factorial(list("ABCD"), resolution=4), 4)
    both = combine(d, foldover(d, on="A"))
    fit = fit_effects(
        both, [float((i * 5) % 13) for i in range(len(both.points))],
        factor_ids=tuple("ABCD"),
    )
    assert not fit.aliases
    assert alias_consequential(
        fit, factors, direction="maximize", fitted_ids=tuple("ABCD"),
        held_fixed={},
    ) == []


def _signed_fit(sign: float):
    """A fit whose one significant coefficient is aliased at ``sign``.

    ``C = +5.0`` carries the whole signal and is aliased onto ``(A, B)``. The
    alternative reading of that same column is ``+5.0 * sign``, so the two signs
    are two physically OPPOSITE claims about A and B: one says the response is
    maximised when they agree, the other when they disagree.
    """
    from orchestrator.optimize.effects import Effect, Fit

    return Fit(
        intercept=10.0,
        effects=(
            Effect(label="A", terms=("A",), estimate=0.0, se=0.01,
                   ci_low=-0.02, ci_high=0.02, significant=False),
            Effect(label="B", terms=("B",), estimate=0.0, se=0.01,
                   ci_low=-0.02, ci_high=0.02, significant=False),
            Effect(label="C", terms=("C",), estimate=5.0, se=0.01,
                   ci_low=4.98, ci_high=5.02, significant=True,
                   aliased_with=((("A", "B"), sign),)),
            Effect(label="D", terms=("D",), estimate=0.0, se=0.01,
                   ci_low=-0.02, ci_high=0.02, significant=False),
        ),
        n_runs=8, pure_error_var=1e-4, pure_error_df=3,
    )


def test_alias_resolutions_re_signs_a_negated_alias():
    """The one place the sign is observable, and the defect it prevents.

    A negated alias's re-attributed coefficient is `-beta`, not `beta`. Pinned
    on the ESTIMATE (the arithmetic) and on the resulting RECOMMENDATION (the
    consequence): at `sign = +1` the alternative reading says the response is
    maximised when A and B AGREE, at `sign = -1` when they DISAGREE. An
    implementation that relabelled without re-signing gives the +1 answer for
    both, so it would hand a consumer advice pointing the wrong way for exactly
    the designs where the alias is negated.
    """
    from orchestrator.optimize.decide import alias_resolutions, recommend
    from orchestrator.optimize.factors import parse_factors

    factors = parse_factors([_numeric(f, levels=(2, 16)) for f in "ABCD"])
    ids = tuple("ABCD")
    seen = {}
    for sign in (1.0, -1.0):
        (idx, kept, alt, alt_fit), = alias_resolutions(_signed_fit(sign))
        assert (idx, kept, alt) == (2, "C", "AB")
        swapped = alt_fit.effects[idx]
        assert swapped.terms == ("A", "B") and swapped.aliased_with == ()
        assert swapped.estimate == 5.0 * sign
        rec = recommend(alt_fit, factors, direction="maximize",
                        fitted_ids=ids, held_fixed={})
        seen[sign] = rec.coded["A"] * rec.coded["B"]
    # Opposite advice about the same two factors -- which is the whole point.
    assert seen[1.0] == 1.0 and seen[-1.0] == -1.0


def test_alias_consequential_reports_the_pair_under_either_sign():
    """Companion to the test above: the VERDICT is sign-invariant here, by design.

    Recorded so a reader does not mistake the absence of a sign-flipping boolean
    test for an untested sign. Dropping the kept term frees every factor it
    spanned, so when that coefficient is large SOME member of the alternative's
    optimal set is materially worse under the fitted reading whichever way the
    sign points. What the sign changes is WHICH configuration the alternative
    recommends, which is why it is pinned on `alias_resolutions` rather than
    here.
    """
    from orchestrator.optimize.decide import alias_consequential
    from orchestrator.optimize.factors import parse_factors

    factors = parse_factors([_numeric(f, levels=(2, 16)) for f in "ABCD"])
    kw = dict(direction="maximize", fitted_ids=tuple("ABCD"), held_fixed={})
    assert alias_consequential(_signed_fit(1.0), factors, **kw) == [("C", "AB")]
    assert alias_consequential(_signed_fit(-1.0), factors, **kw) == [("C", "AB")]


# ─── the policy: a registered branch that spends, conditionally ─────────────


def test_policy_registers_foldover_before_refine_and_it_spends():
    from orchestrator.optimize.policy import check_policy, compile_policy

    pol = compile_policy(synthetic_campaign(SURFACES["bowl"]()))
    assert pol["states"]["foldover"]["spends"] is True
    assert check_policy(pol) == []
    screen_rules = [t for t in pol["transitions"] if t["from"] == "screen"]
    targets = [t.get("to") or t.get("default") for t in screen_rules]
    assert targets.index("foldover") < targets.index("refine"), targets
    fold = next(t for t in screen_rules if t.get("to") == "foldover")
    assert fold["when"] == {"alias_consequential": True, "foldover_affordable": True}
    # foldover carries screen's rules MINUS a second foldover.
    fold_out = [t for t in pol["transitions"] if t["from"] == "foldover"]
    assert not any((t.get("to") or t.get("default")) == "foldover" for t in fold_out)
    assert any(t.get("to") == "exception" for t in fold_out)
    assert any("default" in t for t in fold_out)


def test_the_foldover_branch_needs_both_facts_not_either():
    """Consequential-but-unaffordable must NOT fire, and neither must affordable
    -but-inconsequential. That conjunction is the whole rule."""
    from orchestrator.optimize.policy import compile_policy, step

    pol = compile_policy(synthetic_campaign(SURFACES["bowl"]()))
    base = {"correctness_failed": False, "nan_response": False,
            "refinable_survivors": 2, "budget_remaining": 100}
    assert step(pol, "screen", {**base, "alias_consequential": True,
                                "foldover_affordable": True})[0] == "foldover"
    assert step(pol, "screen", {**base, "alias_consequential": True,
                                "foldover_affordable": False})[0] == "refine"
    assert step(pol, "screen", {**base, "alias_consequential": False,
                                "foldover_affordable": True})[0] == "refine"


def test_policy_foldover_false_removes_the_state():
    from orchestrator.optimize.policy import check_policy, compile_policy

    pol = compile_policy(
        synthetic_campaign(SURFACES["additive"](), policy={"foldover": False}),
    )
    assert "foldover" not in pol["states"]
    assert not any(
        (t.get("to") or t.get("default")) == "foldover" for t in pol["transitions"]
    )
    assert check_policy(pol) == []


def test_the_foldover_opt_out_is_reachable_from_a_schema_valid_campaign():
    """An escape hatch the campaign SCHEMA rejects is not an escape hatch.

    MUTATION-DRIVEN, and the mutation is deletion of the schema property rather
    than of any code: ``compile_policy`` reads ``optimization.policy.foldover``,
    but the ``policy`` block is ``additionalProperties: false``, so for the life
    of this branch the opt-out was unreachable from any real campaign file — the
    test above only reached it by handing ``compile_policy`` a dict directly,
    which is exactly the seam that hid it. Validate a real campaign against the
    real schema, then compile THAT.
    """
    import jsonschema
    import yaml

    from orchestrator.optimize.policy import compile_policy

    root = Path(__file__).resolve().parents[1]
    schema = yaml.safe_load(
        (root / "orchestrator" / "schemas" / "campaign.schema.yaml").read_text(),
    )
    c = yaml.safe_load(
        (root / "examples" / "optimization" / "vllm-batching.yaml").read_text(),
    )
    c["optimization"].setdefault("policy", {})["foldover"] = False
    jsonschema.validate(c, schema)          # the hatch is DECLARED, not just read
    assert "foldover" not in compile_policy(c)["states"]
    # ...and the default still registers it, so the opt-out is opt-IN only.
    c["optimization"]["policy"].pop("foldover")
    jsonschema.validate(c, schema)
    assert "foldover" in compile_policy(c)["states"]


def test_every_foldover_path_terminates_with_room_to_spare():
    """`enumerate_paths`'s max_len must not silently truncate the new paths.

    Adding the state raises the theoretical ceiling (`1 + len(transitions)`) but
    the REALIZED longest simple path is what matters, and it must stay clear of
    the default `max_len` — a truncated path is reported as if it ended at a
    non-terminal state, which would silently misclassify the policy as
    non-terminating.
    """
    from orchestrator.optimize.policy import compile_policy, enumerate_paths, is_terminal

    pol = compile_policy(synthetic_campaign(SURFACES["bowl"]()))
    paths = enumerate_paths(pol)
    assert all(is_terminal(pol, p[-1]) for p in paths)
    longest = max(len(p) for p in paths)
    assert longest < 12, longest          # the default max_len
    assert any("foldover" in p and p[-1] == "report" for p in paths)
    assert any("foldover" in p and p[-1] == "exception" for p in paths)
    assert any(p[:3] == ["screen", "foldover", "refine"] for p in paths)


# ─── end to end: the two clauses of the paper's sentence ───────────────────


def test_interaction_only_surface_triggers_foldover_and_lands_on_truth(tmp_path):
    res = run_synthetic_campaign(
        SURFACES["interaction_only"](), seed=21, parent_dir=tmp_path,
        campaign_overrides=dict(_RES4_OVERRIDES),
    )
    assert "foldover" in res.path, res.path
    assert abs(res.true_gap) / abs(res.true_best) <= 0.02, (
        res.recommendation, res.true_optimum,
    )
    trans = [
        json.loads(line)
        for line in (res.work_dir / "transitions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    screen_row = next(t for t in trans if t["from"] == "screen")
    # The branch fired on FACTS, and both of them.
    assert screen_row["to"] == "foldover"
    assert screen_row["observations"]["alias_consequential"] is True
    assert screen_row["observations"]["foldover_affordable"] is True
    assert screen_row["observations"]["runs_needed_foldover"] == 12

    fold_row = next(t for t in trans if t["from"] == "foldover")
    fold_iter = fold_row["iteration"]
    fold_dir = res.work_dir / "runs" / f"iter-{fold_iter}"
    dm = json.loads((fold_dir / "design_matrix.json").read_text())
    assert dm["kind"] == "foldover"
    assert dm["folded_on"] in list("ABCD")
    assert dm["screen_iteration"] == screen_row["iteration"]

    # IT SPENT BUDGET AND PRODUCED NEW MEASUREMENTS. A foldover that only
    # diagnosed the aliasing would leave this file absent or empty, which is the
    # "diagnosis without action" defect the spec's gap table names.
    fold_runs = [
        json.loads(line)
        for line in (fold_dir / "runs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(fold_runs) == len(dm["rows"]) == 12
    assert all(r["status"] == "complete" for r in fold_runs)

    # AND THE ALIAS IS ACTUALLY RESOLVED: the combined fit estimates all six
    # two-factor interactions, where the screen alone could only reach three.
    fold_fit = json.loads((fold_dir / "effects.json").read_text())
    assert fold_fit["stage"] == "foldover"
    by_label = {e["label"]: e for e in fold_fit["effects"]}
    assert {"AB", "AC", "AD", "BC", "BD", "CD"} <= set(by_label), sorted(by_label)
    assert fold_fit["n_runs"] == 24          # 12 screen + 12 foldover

    # THE COMBINED FIT MUST BE ALIGNED, not merely large. `combine` concatenates
    # screen-then-fold and `fit_effects` pairs response i with points[i], so the
    # response vector has to be assembled the same way round. Assembling it
    # backwards still yields 24 rows and all six interactions — it just SIGN
    # FLIPS every coefficient involving the folded column, which on this surface
    # turns the true optimum into the worst corner (verified: 9.02 instead of
    # 10.98). `interaction_only` is `10 + 0.02*(A-9)*(B-9)`, so AB must come back
    # strongly POSITIVE and every main effect null.
    assert by_label["AB"]["estimate"] > 0.5, by_label["AB"]
    assert by_label["AB"]["significant"] is True
    for fid in "ABCD":
        assert abs(by_label[fid]["estimate"]) < 0.2, (fid, by_label[fid])
    screen_fit = json.loads(
        (res.work_dir / "runs" / f"iter-{screen_row['iteration']}"
         / "effects.json").read_text(),
    )
    assert {"CD", "BD", "BC"} & {e["label"] for e in screen_fit["effects"]} == set()
    # The block did its job: nothing is consequential any more.
    fold_rec = json.loads((fold_dir / "recommendation.json").read_text())
    assert fold_rec["alias_consequential"] == []
    assert fold_rec["aliases"] == []

    # AND THE STATE'S OWN ANSWER IS THE TRUTH. `res.true_gap` above is the
    # CAMPAIGN's answer, which confirm's terminal discrimination can rescue from
    # a corrupted fit (its shortlist includes the best MEASURED corner), so it
    # is not by itself evidence about this state. Score the foldover's argmax
    # against the surface directly.
    surface = SURFACES["interaction_only"]()
    from orchestrator.optimize.synthetic import true_optimum
    _opt, best = true_optimum(surface)
    fold_true = surface.fn(fold_rec["levels"])
    assert abs(best - fold_true) / abs(best) <= 0.02, (fold_rec["levels"], best)


def test_additive_surface_at_resolution_iv_does_not_fold_over(tmp_path):
    res = run_synthetic_campaign(
        _additive_four_factor(), seed=22, parent_dir=tmp_path,
        campaign_overrides=dict(_RES4_OVERRIDES),
    )
    assert "foldover" not in res.path, res.path
    trans = [
        json.loads(line)
        for line in (res.work_dir / "transitions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    screen_row = next(t for t in trans if t["from"] == "screen")
    # NOT because the branch was unregistered or unaffordable — because the
    # aliasing genuinely could not change the winner. That distinction is what
    # makes this test discriminate rather than pass vacuously.
    assert screen_row["observations"]["alias_consequential"] is False
    assert screen_row["observations"]["foldover_affordable"] is True
    screen_dir = res.work_dir / "runs" / f"iter-{screen_row['iteration']}"
    rec = json.loads((screen_dir / "recommendation.json").read_text())
    assert rec["alias_consequential"] == []
    # The aliasing IS there and IS recorded — it is only the CONSEQUENCE that is
    # absent. A campaign that simply had no alias would prove nothing.
    assert rec["aliases"], rec["aliases"]


def test_a_consequential_alias_is_left_unresolved_when_the_budget_cannot_pay(tmp_path):
    """Conditional means conditional on BOTH facts, end to end.

    Same surface and seed as the firing test, so the only thing that changed is
    the declared budget: 20 runs, of which the screen spends 12, leaving 8 for a
    block that costs 12. The alias is still consequential and still recorded —
    the campaign simply cannot afford to resolve it, and says so rather than
    spending runs it does not have or pretending the aliasing away.
    """
    res = run_synthetic_campaign(
        SURFACES["interaction_only"](), seed=21, parent_dir=tmp_path,
        campaign_overrides={
            "design": {"max_runs": 20,
                       "screen": {"resolution": 4, "center_points": 4},
                       "confirm": {"replicates": 3, "shortlist_size": 3}},
        },
    )
    assert "foldover" not in res.path, res.path
    trans = [
        json.loads(line)
        for line in (res.work_dir / "transitions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    screen_row = next(t for t in trans if t["from"] == "screen")
    obs = screen_row["observations"]
    assert obs["alias_consequential"] is True        # it WOULD have mattered
    assert obs["foldover_affordable"] is False       # but it could not be paid for
    assert obs["runs_needed_foldover"] == 12
    assert obs["budget_remaining"] < obs["runs_needed_foldover"]
    # The unresolved confounding survives into the artifact, so a reader of the
    # recommendation knows it rests on an assumption the campaign could not test.
    rec = json.loads(
        (res.work_dir / "runs" / f"iter-{screen_row['iteration']}"
         / "recommendation.json").read_text(),
    )
    assert ["AB", "CD"] in rec["alias_consequential"]


def test_a_resolution_v_campaign_never_reaches_the_foldover_state(tmp_path):
    """Nothing aliased, so nothing to resolve — the state stays unvisited."""
    res = run_synthetic_campaign(
        SURFACES["bowl"](), seed=5, parent_dir=tmp_path,
        campaign_overrides={
            "design": {"screen": {"resolution": 5, "center_points": 4},
                       "refine": {"kind": "central_composite", "center_points": 4},
                       "confirm": {"replicates": 3, "shortlist_size": 3}},
        },
    )
    assert "foldover" not in res.path, res.path
