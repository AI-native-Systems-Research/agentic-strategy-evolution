"""Synthetic targets with KNOWN response surfaces — the oracle for this kind.

Why this module exists
----------------------
Every "observed on a real campaign" comment in this package records a bug the
test suite did not catch, because the tests checked artifacts and mocks and
nothing checked the ANSWER. A surface whose optimum is known lets a test
assert that the recommendation lands on it, that the certificate covers it,
and that the policy took the branch it should — with zero LLM calls and zero
subprocesses (in-process runner) or, through ``python -m``, as a real
``run_command`` for ``nous validate --smoke``.

Each surface is named for the historical failure it catches:

  * ``additive`` — baseline sanity: main effects only, no interaction.
  * ``interaction_only`` — mains are null over the screen pair, so a
    resolution-IV design's aliasing is consequential and a foldover is the
    only way to recover the truth.
  * ``bowl`` — an interior stationary point that ``refine`` must find and
    ``confirm`` must reproduce.
  * ``bowl_out_of_hull`` — the stationary point lies outside the declared
    level hull, so extrapolating to it is the failure and clamping to the
    boundary is the honest answer.
  * ``bowl_centred`` — a symmetric bowl centred on the design centre, so the
    corners carry no main effect at all and only the screen's centre-point
    curvature test says where the optimum is; routing that screen to confirm
    certifies an uninformed shortlist.
  * ``saddle`` — a stationary point that is NOT the argmax; solving
    ``grad = 0`` and reporting it is the bug.
  * ``choice_x_numeric`` — the numeric optimum flips sign with the choice
    level, so holding the choice fixed loses the optimum entirely.
  * ``drift`` — a monotone per-run trend that randomized run order absorbs
    and a time-ordered sweep would attribute to a factor.
  * ``sla`` — the unconstrained argmax violates a constraint observable, so
    the answer must be the argmax restricted to the valid region.
  * ``infeasible_corner_interior`` — a whole CORNER region violates a
    smooth, noisy constraint metric while the primary is maximised there, so
    the primary-only fit ranks the corner's INTERIOR points (levels the screen
    never ran) highest; without a model of the constraint, confirm seats them
    as finalists and spends a round measuring them infeasible.
  * ``nan_at_corner`` — one configuration makes the target emit NaN, which
    is a semantic exception that ends the epoch rather than a datum to fit.
  * ``fails_at_one_level`` — a whole CORNER of the space never produces a
    measurement at all (wall-clock timeout / adapter crash), and the failures
    sit on ONE level of ONE factor while the same corner at that factor's other
    level measures fine. Aborting the iteration is the bug (18 rows measured,
    15 valid, all 15 discarded four times over), and so is refitting silently:
    the loss deletes the region where the mechanism under study does the most
    work, which biases that factor's coefficient in a named direction.
  * ``stochastic_constraint_boundary`` — the constraint metric's MEAN sits on
    its bound across the whole high-primary region, with run-to-run noise
    that straddles it, so feasibility is STOCHASTIC per replicate there and
    every confirm finalist drawn from that region gets at least one
    infeasible replicate. No finalist is admissible; reading that as a NaN
    (an instrumentation defect), resolving epsilon against a non-existent
    best as 0, or returning a configuration whose OTHER rows were measured
    infeasible are the three bugs it catches.

No numpy: the surfaces are closed-form arithmetic and the noise comes from
``random.Random``, so the oracle has no dependency the harness does not
already have and every number in it is auditable by reading it.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from orchestrator.optimize.factors import snap_to_grid


@dataclass(frozen=True)
class Surface:
    """One synthetic response surface plus everything needed to judge it.

    ``fn`` is the NOISELESS response, so a test can compare an observation
    against ground truth. ``invalid`` marks the points outside ``X_valid``
    (the constraint region), and ``exception_at`` names the one level
    combination at which the target emits NaN rather than a number — the
    two failure modes a fitter must treat differently.
    """

    name: str
    factors: tuple[dict, ...]
    fn: Callable[[dict], float]
    noise_sd: float = 0.0
    drift_per_run: float = 0.0
    invalid: Callable[[dict], bool] | None = None
    exception_at: dict | None = None
    #: Level combinations at which the target produces NO MEASUREMENT: the
    #: runner RAISES, which ``runner._run_once`` converts into a ``failed``
    #: RunOutcome. Categorically different from ``exception_at``, and the
    #: distinction is the whole point of the surface that uses it:
    #:
    #:   * ``exception_at`` — the row reaches ``complete`` and reports a
    #:     non-numeric primary metric. SEMANTIC: the objective and the
    #:     instrumentation disagree about what is measurable there, no re-run
    #:     repairs it, and the paper's rule is that it ends the EPOCH.
    #:   * ``fails_at`` — the row never completes. A MEASUREMENT failure a
    #:     re-run repairs; nothing semantic has been discovered, so it must not
    #:     end the epoch and must not end the campaign either. It is a hole in
    #:     the design, and whether that hole is level-correlated is what decides
    #:     whether the fit's coefficients are merely widened or actually biased.
    fails_at: Callable[[dict], bool] | None = None
    direction: str = "maximize"
    extra_observables: Callable[[dict], dict] = field(default=lambda lv: {})
    #: Observables that carry their OWN measurement noise, drawn from the same
    #: per-row stream as the primary. ``extra_observables`` is deterministic, so
    #: a constraint built from it has zero pure error and can never be fitted
    #: with an interval -- which is right for ``sla`` and wrong for a surface
    #: whose point is a constraint model with real uncertainty.
    noisy_observables: Callable[[dict, Any], dict] | None = None
    #: MULTI-OBJECTIVE surfaces only (``PARETO_SURFACES``): one entry per
    #: objective, ``{"metric", "direction", "fn", "noise_sd"}``. The target
    #: emits every objective with its own noise; ``fn`` above is the FIRST
    #: objective so the single-objective helpers stay meaningful. Empty on every
    #: single-objective surface, whose observations are therefore unchanged.
    objectives: tuple = ()
    #: ``response.constraints`` the harness declares for this surface (so the
    #: oracle runs the campaign the surface was built for). Empty on every
    #: pre-existing surface, whose tests pass constraints explicitly.
    constraints: tuple = ()
    #: The factor ids ``fn``, ``invalid`` and every objective actually read.
    #: Empty means all of them. A many-knob surface names its few active
    #: factors so the oracle enumerates only THEIR grid with the inert ones
    #: pinned -- still exact, because nothing it judges depends on the inert
    #: ones -- instead of 9^k points (a 16-knob truth would never finish).
    active: tuple = ()


def _numeric(fid: str, levels=(2, 4, 8, 16), grid=1) -> dict:
    """A numeric factor dict in exactly the shape campaign YAML declares.

    The ``relations`` entry is not decoration: ``parse_factors`` refuses a
    factor with no ``correctness`` relation, because a lever with no native
    test has nothing to catch it when it breaks.
    """
    return {
        "id": fid, "name": fid.lower(), "type": "numeric",
        "levels": list(levels), "grid": grid,
        "apply": f"--{fid.lower()}={{level}}",
        "manipulation": {"observable": f"cfg.{fid.lower()}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": f"R{fid}", "kind": "correctness",
                       "statement": f"{fid} at baseline reproduces baseline",
                       "native_test": f"tests/prop_{fid.lower()}.py::test_noop"}],
    }


def _choice(fid: str, levels=("off", "on")) -> dict:
    """A choice factor dict — nothing runnable lives between the levels."""
    return {
        "id": fid, "name": fid.lower(), "type": "choice", "levels": list(levels),
        "apply": f"--{fid.lower()}={{level}}",
        "manipulation": {"observable": f"cfg.{fid.lower()}", "op": "==",
                         "value": "{level}"},
        "relations": [{"id": f"R{fid}", "kind": "correctness",
                       "statement": f"{fid} off is byte-identical to baseline",
                       "native_test": f"tests/prop_{fid.lower()}.py::test_noop"}],
    }


def _additive() -> Surface:
    return Surface(
        name="additive", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"), _choice("C")),
        fn=lambda lv: 10 - 0.05 * lv["A"] + 0.20 * lv["B"] + (2.0 if lv["C"] == "on" else 0.0),
    )


def _interaction_only() -> Surface:
    return Surface(
        name="interaction_only", noise_sd=0.05,
        factors=tuple(_numeric(f, levels=(2, 16)) for f in "ABCD"),
        fn=lambda lv: 10 + 0.02 * (lv["A"] - 9) * (lv["B"] - 9),
    )


def _bowl(a0=9.0, b0=11.0, name="bowl") -> Surface:
    return Surface(
        name=name, noise_sd=0.05, factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 20 - 0.05 * (lv["A"] - a0) ** 2 - 0.05 * (lv["B"] - b0) ** 2,
    )


def _bowl_centred() -> Surface:
    """A symmetric bowl centred EXACTLY on the screen's design centre.

    Pure curvature: every 2-level corner sits at the same distance from the
    optimum, so every numeric main effect (and the A x B interaction) is zero
    at the corners and no numeric factor survives the screen. The ONLY
    evidence of where the optimum lives is the centre-point curvature contrast
    -- the lack-of-fit F on pure error. A policy whose only screen -> refine
    route is ``refinable_survivors > 0`` goes straight to confirm, seats a
    shortlist from the measured corners and centre, and certifies a point that
    was never informed by an adequate model. The choice factor C carries a
    real additive effect, so the held-fixed level refine uses for it is part
    of what the oracle judges: the optimum is (A=9, B=9, C=on).
    """
    return Surface(
        name="bowl_centred", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"), _choice("C")),
        fn=lambda lv: (20 - 0.05 * (lv["A"] - 9) ** 2 - 0.05 * (lv["B"] - 9) ** 2
                       + (1.0 if lv["C"] == "on" else 0.0)),
    )


def _saddle() -> Surface:
    return Surface(
        name="saddle", noise_sd=0.05, factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 10 + 0.05 * (lv["A"] - 9) ** 2 - 0.05 * (lv["B"] - 11) ** 2,
    )


def _choice_x_numeric() -> Surface:
    return Surface(
        name="choice_x_numeric", noise_sd=0.05,
        factors=(_numeric("A"), _choice("C")),
        fn=lambda lv: 10 + (0.5 * lv["A"] if lv["C"] == "on" else -0.5 * lv["A"]),
    )


def _drift() -> Surface:
    return Surface(
        name="drift", noise_sd=0.05, drift_per_run=0.05,
        factors=(_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16))),
        fn=lambda lv: 10 - 0.05 * lv["A"] + 0.20 * lv["B"],
    )


def _sla() -> Surface:
    return Surface(
        name="sla", noise_sd=0.05, factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 10 + 0.5 * lv["A"] + 0.2 * lv["B"],
        invalid=lambda lv: (2 * lv["A"] + lv["B"]) > 40,
        extra_observables=lambda lv: {"p99_ms": 2 * lv["A"] + lv["B"]},
    )


def _infeasible_corner_interior() -> Surface:
    """The confirm-shortlist defect, in closed form.

    Observed on a real campaign (primary throughput maximised, ``p99 <= 90``):
    every screen row at ``BS=32, CMP=on`` measured infeasible, yet the top two
    candidates were ``BS=32, CMP=on, PF=6`` and ``PF=2`` -- interior points of
    that corner, which the screen never ran, so the exact-match
    measured-infeasible skip could not see them. A confirm round was spent
    measuring them infeasible and their infeasibility withheld certification.

    Here ``p99_ms`` is a SMOOTH function of the factors (mains plus the
    ``BS x CMP`` interaction -- inside the screen's model class) with real
    measurement noise, so it can be fitted with pure error. It exceeds 90 over
    the whole ``BS=32, CMP=2`` region for every ``PF`` (true value 104..107)
    and clears it by >= 12 everywhere else, while the primary is additive and
    maximised in exactly that region, so the primary-only fit ranks the
    region's interior ``PF`` points first. The true constrained optimum is
    ``{BS: 32, CMP: 0, PF: 8}`` (14.4).

    ``BS`` and ``CMP`` are two-level NUMERICS with no grid (so the candidate
    space and ``true_optimum`` both see only their declared pair) rather than
    a ``choice`` (``CMP`` is a 0/2 compression level, so its centre point is
    the runnable integer 1): a choice factor's centre points run at its FIRST level while
    the fit codes them 0, which biases every coefficient they touch and would
    confound the failure this surface isolates with an unrelated one.
    """
    def p99(lv: dict) -> float:
        cmp_ = float(lv["CMP"]) / 2.0
        bs = float(lv["BS"]) - 8.0
        return 50.0 + 1.0 * bs + 5.0 * cmp_ + 1.0 * bs * cmp_ + 0.5 * float(lv["PF"])

    return Surface(
        name="infeasible_corner_interior", noise_sd=0.05,
        factors=(_numeric("BS", levels=(8, 32), grid=None),
                 _numeric("CMP", levels=(0, 2), grid=None),
                 _numeric("PF", levels=(2, 4, 6, 8))),
        fn=lambda lv: (
            10.0 + 0.1 * float(lv["BS"]) + 0.75 * float(lv["CMP"])
            + 0.15 * float(lv["PF"])
        ),
        invalid=lambda lv: p99(lv) > 90.0,
        noisy_observables=lambda lv, rng: {"p99_ms": p99(lv) + rng.gauss(0.0, 1.5)},
    )


def _nan_at_corner() -> Surface:
    return Surface(
        name="nan_at_corner", noise_sd=0.05,
        factors=(_numeric("A", levels=(2, 16)), _numeric("B", levels=(2, 16))),
        fn=lambda lv: 10 - 0.05 * lv["A"] + 0.20 * lv["B"],
        exception_at={"A": 16, "B": 16},
    )


def _fails_at_one_level() -> Surface:
    """The BLIS defect, in closed form.

    Three factors, and one CORNER of the space never produces a measurement:
    ``EV=arc`` together with ``DEV=sata_ssd`` and ``CPU=40``. The same corner at
    ``EV=lru`` measures fine — a perfect 2x2 separation, which is exactly what
    the field campaign showed (rows 9 and 13 timed out at ``EV=arc, DEV=sata_ssd,
    CPU=40GiB`` while both ``EV=lru`` rows at that identical corner completed).

    The surface is built so the DELETED REGION IS THE ONE THAT MATTERS: ``EV=arc``
    is worth ``+3.0`` at ``DEV=sata_ssd`` (the slow device, where a smarter
    eviction policy earns its keep) and only ``+0.2`` elsewhere. So the rows lost
    are precisely the rows carrying ``arc``'s advantage, and a fit over the
    survivors underestimates the ``EV`` main effect. A campaign that refits
    silently reports a small ``EV`` effect with a tight interval and recommends
    ``lru``; the truth is that ``arc`` wins. Reporting the exclusion as
    level-correlated is what stops that number being read as certified.

    Two levels per factor so the screen design is a full ``2^3`` and every cell
    has a one-factor sibling — the pattern ``exclusions.cell_holes`` reports.
    """
    return Surface(
        name="fails_at_one_level", noise_sd=0.05,
        factors=(
            _choice("EV", levels=("lru", "arc")),
            _choice("DEV", levels=("nvme", "sata_ssd")),
            _numeric("CPU", levels=(8, 40), grid=1),
        ),
        fn=lambda lv: (
            10.0
            + (1.0 if lv["DEV"] == "nvme" else 0.0)
            + 0.02 * float(lv["CPU"])
            + ((3.0 if lv["DEV"] == "sata_ssd" else 0.2)
               if lv["EV"] == "arc" else 0.0)
        ),
        fails_at=lambda lv: (
            lv["EV"] == "arc" and lv["DEV"] == "sata_ssd"
            and float(lv["CPU"]) >= 40
        ),
    )


def _stochastic_constraint_boundary() -> Surface:
    """The confirm-with-no-admissible-finalist defect, in closed form.

    Observed on a real campaign (bulk-insert throughput maximised,
    ``max_stall_ms <= 10``): under one journal mode the stall metric's
    run-to-run noise straddled 10 ms right where throughput peaked, so EVERY
    confirm finalist had at least one infeasible replicate. That state then
    produced three wrong artifacts — an epsilon of 0 (resolved as a percentage
    of a best that did not exist), a ``nan_response`` exception blaming the
    metric's definition although every value was numeric, and a ``measured``
    recommendation of a finalist whose other replicates were infeasible.

    Here ``stall_ms`` has mean ``bound + 0.3`` (with sd 1.0) wherever
    ``A + B > 18`` — the high-primary corner, where the primary is maximised —
    and mean 4 (seven sd clear) everywhere else. Each replicate in the corner
    therefore violates with probability ~0.62 and a 5-replicate finalist is
    admissible on all five with probability < 1%. Declare the constraint as
    ``{"metric": "stall_ms", "op": "<=", "value": 10}``.

    ``invalid`` marks the corner: a configuration admissible only sometimes is
    not admissible (``_finish_confirm``'s sticky rule), so the true
    constrained optimum lies outside it — ``{A: 16, B: 2}`` (18.4).
    """
    def mean_stall(lv: dict) -> float:
        return 10.3 if float(lv["A"]) + float(lv["B"]) > 18 else 4.0

    return Surface(
        name="stochastic_constraint_boundary", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B")),
        fn=lambda lv: 10 + 0.5 * lv["A"] + 0.2 * lv["B"],
        invalid=lambda lv: mean_stall(lv) > 10.0,
        noisy_observables=lambda lv, rng: {
            "stall_ms": mean_stall(lv) + rng.gauss(0.0, 1.0),
        },
    )


def _geometric_knob(*, scale: str | None = None) -> Surface:
    """Two geometric knobs whose optimum sits at the geometric interior.

    Named for a real campaign: an access-update interval declared [1, 8, 64]
    was coded linearly, so its centre point ran at 32 and refine explored
    32..64 while the answer lived near 8. The response is a smooth bowl in
    log(level) -- how a size / interval knob usually acts -- peaking at
    INT=8 and BUF=2048. ``scale`` is written onto both factors so the same
    surface can be run with and without ``scale: log``.
    """
    import math

    def fac(fid, levels):
        f = _numeric(fid, levels=levels, grid=1)
        if scale:
            f["scale"] = scale
        return f

    def fn(lv):
        a = math.log2(float(lv["INT"]) / 8.0)
        b = math.log2(float(lv["BUF"]) / 2048.0)
        return 100.0 - 4.0 * a * a - 3.0 * b * b + 0.5 * a * b

    return Surface(
        name="geometric_knob" if scale is None else f"geometric_knob_{scale}",
        factors=(fac("INT", (1, 8, 64)), fac("BUF", (256, 2048, 16384))),
        fn=fn, noise_sd=0.3,
    )


def _deterministic_constraint_axis() -> Surface:
    """The confirm-shortlist-never-tests-a-supported-feasible-point defect.

    Observed on a real campaign (ops per CPU-second maximised, a write cache
    whose un-persisted writes must stay ``<= 200``): the constraint metric is
    DETERMINISTIC (it is the write-cache size minus one), so its model has no
    pure error and stays unmodelled; the fitted ranking preferred a large write
    cache, so every model-ranked finalist was infeasible by construction, and
    the campaign returned the measured leader -- although a bigger front cache
    with a small, already-measured-feasible write cache was faster and was
    never tested.

    Here the primary rises freely with ``A`` and ``B`` and with ``C`` (coded on
    a log scale, like a cache size); the constraint ``backlog = C - 1 <= 7``
    is violated iff ``C > 8``. ``C``'s centre level 8 is exactly feasible, so
    the screen measures it admissible, but no design point pairs it with
    ``A = B = 16``: a factorial corner has ``C`` at 1 or 64, and an axial point
    moves one factor at a time from the centre. The true constrained optimum
    ``{A: 16, B: 16, C: 8}`` (19.0) is therefore inside the region the
    measured-admissible configurations span, never measured, and below every
    model-ranked candidate at ``C > 8``. Declare the constraint as
    ``{"metric": "backlog", "op": "<=", "value": 7}``.
    """
    import math

    c = _numeric("C", levels=(1, 8, 64), grid=1)
    c["scale"] = "log"
    return Surface(
        name="deterministic_constraint_axis", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"), c),
        fn=lambda lv: (10.0 + 0.25 * float(lv["A"]) + 0.2 * float(lv["B"])
                       + 0.6 * math.log2(float(lv["C"]))),
        invalid=lambda lv: float(lv["C"]) - 1.0 > 7.0,
        extra_observables=lambda lv: {"backlog": float(lv["C"]) - 1.0},
    )



def sparse_knobs(k: int, *, noise_sd: float = 0.05) -> Surface:
    """``k`` numeric knobs of which only three move the response -- effect
    sparsity, the usual shape of a real many-knob system. X00 has an interior
    optimum, X01 is monotone (its best is the upper edge), and an X00 x X02
    interaction moves the joint optimum to X00=12, X01=16, X02=16. Not in
    ``SURFACES``: the every-surface loops would pay for a many-knob campaign
    each; the many-knob tests use it directly."""
    ids = tuple(f"X{i:02d}" for i in range(k))
    a, b, c = ids[0], ids[1], ids[2]
    return Surface(
        name=f"sparse_knobs_{k}", noise_sd=noise_sd,
        factors=tuple(_numeric(i) for i in ids),
        fn=lambda lv: 20 - 0.05 * (lv[a] - 11) ** 2 + 0.2 * lv[b] + 0.01 * lv[a] * lv[c],
        active=(a, b, c),
    )

def curvature_under_second_level() -> Surface:
    """Curvature that exists only under a NON-FIRST choice level (spec
    2026-10-16-mixed-level-factors-design.md, feature 3).

    ``C=off`` is flat at 15; ``C=on`` is a bowl peaking at 16 at the design
    centre (A = B = 9) and reading 11.1 at every corner. With every centre row
    at ``C=off`` (the old layout) the screen sees no curvature, nothing
    refines, and the campaign certifies ``off`` 1.0 below the optimum; with the
    centres cycled the ``on`` centres show the bowl. Not in ``SURFACES``: the
    every-surface loops and the byte-identity baseline stay as they were.
    """
    return Surface(
        name="curvature_under_second_level", noise_sd=0.05,
        factors=(_numeric("A"), _numeric("B"), _choice("C")),
        fn=lambda lv: (15.0 if lv["C"] == "off" else
                       16.0 - 0.05 * ((lv["A"] - 9) ** 2 + (lv["B"] - 9) ** 2)),
    )


SURFACES: dict[str, Callable[[], Surface]] = {
    "additive": _additive,
    "interaction_only": _interaction_only,
    "bowl": _bowl,
    "bowl_out_of_hull": lambda: _bowl(a0=30.0, name="bowl_out_of_hull"),
    "bowl_centred": _bowl_centred,
    "saddle": _saddle,
    "choice_x_numeric": _choice_x_numeric,
    "drift": _drift,
    "sla": _sla,
    "infeasible_corner_interior": _infeasible_corner_interior,
    "nan_at_corner": _nan_at_corner,
    "fails_at_one_level": _fails_at_one_level,
    "stochastic_constraint_boundary": _stochastic_constraint_boundary,
    "geometric_knob": _geometric_knob,
    "geometric_knob_log": lambda: _geometric_knob(scale="log"),
    "deterministic_constraint_axis": _deterministic_constraint_axis,
}


# ── MULTI-OBJECTIVE oracles (spec 2026-10-15-pareto-front-design.md) ────────
#
# Ground truth for every one of these is EXHAUSTIVE ENUMERATION over
# ``candidate_grid`` (``true_front``), the same grid ``true_optimum`` uses, so
# the truth is "the best the declared space offers", not an analytic curve the
# grid cannot reach. Each is named for what it catches:
#
#   * ``pareto_convex`` -- the front BULGES toward the ideal point (f2 is a
#     concave function of f1): a knee exists and every front point is some
#     weighted sum's optimum. The baseline: a correct implementation finds the
#     whole curve.
#   * ``pareto_concave`` -- the front SAGS toward the anti-ideal (f2 convex in
#     f1): no weighted sum reaches an interior front point, so a weights
#     preference returns an extreme while knee / lexicographic must still return
#     a FRONT point. Catches scalarising up front.
#   * ``pareto_with_constraint`` -- the convex front with its high-f1 end cut
#     off by a NOISY coupled constraint (``load = A + B/2 <= 18``): catches a
#     front that reports inadmissible points, or loses the constrained edge.
#   * ``pareto_three`` -- three objectives; the front is a 2-D surface, the
#     hypervolume is exact by slicing, and "adjacent" gaps are MST edges.
#   * ``pareto_choice_split`` -- a CHOICE factor splits the front into two
#     branches (C=off owns the high-f2 half, C=on the high-f1 half). Refine holds
#     C at one level, so a campaign that forgets the other branch reports half a
#     front; catches exactly that.
#   * ``pareto_convex_min`` -- the convex front with a MINIMISED cost
#     objective: catches a sign or a normalisation frame that assumes
#     maximisation.
#   * ``pareto_three_noisy`` -- three objectives at noise ~ epsilon: the K > 2
#     certificate (min-improvement regret) under real uncertainty.
#   * ``pareto_noisy`` -- the convex front at noise 0.25, i.e. about one
#     epsilon: neighbouring front points are NOT separable by a few replicates,
#     so a point-estimate front would misreport dominance. Catches confidence
#     claims the measurements cannot support (statuses must degrade to
#     ``possibly_dominated`` rather than lie).
#
# Noise is 0.05 on objectives whose range is ~3-4 units (the single-objective
# surfaces' level), so the default epsilon (2% of ~13 = ~0.27) is ~7% of range.


def _unit(lv: dict, fid: str, lo: float = 2.0, hi: float = 16.0) -> float:
    return (float(lv[fid]) - lo) / (hi - lo)


def _obj(metric, fn, direction="maximize", noise_sd=0.05) -> dict:
    return {"metric": metric, "direction": direction, "fn": fn, "noise_sd": noise_sd}


def _pareto_convex(name="pareto_convex", noise_sd: float = 0.05) -> Surface:
    f1 = lambda lv: 10.0 + 4.0 * _unit(lv, "A") + 1.0 * _unit(lv, "B")  # noqa: E731
    f2 = lambda lv: 14.0 - 4.0 * _unit(lv, "A") ** 2 + 1.0 * _unit(lv, "B")  # noqa: E731
    return Surface(name=name, noise_sd=noise_sd,
                   factors=(_numeric("A"), _numeric("B")), fn=f1,
                   objectives=(_obj("f1", f1, noise_sd=noise_sd),
                               _obj("f2", f2, noise_sd=noise_sd)))


def _pareto_concave() -> Surface:
    f1 = lambda lv: 10.0 + 4.0 * _unit(lv, "A") + 1.0 * _unit(lv, "B")  # noqa: E731
    f2 = lambda lv: 10.0 + 4.0 * (1.0 - _unit(lv, "A")) ** 2 + 1.0 * _unit(lv, "B")  # noqa: E731
    return Surface(name="pareto_concave", noise_sd=0.05,
                   factors=(_numeric("A"), _numeric("B")), fn=f1,
                   objectives=(_obj("f1", f1), _obj("f2", f2)))


def _pareto_with_constraint() -> Surface:
    base = _pareto_convex(name="pareto_with_constraint")

    def load(lv):
        return float(lv["A"]) + 0.5 * float(lv["B"])

    return Surface(name="pareto_with_constraint", noise_sd=0.05,
                   factors=base.factors, fn=base.fn, objectives=base.objectives,
                   invalid=lambda lv: load(lv) > 18.0,
                   constraints=({"metric": "load", "op": "<=", "value": 18.0},),
                   noisy_observables=lambda lv, rng: {"load": load(lv) + rng.gauss(0.0, 0.3)})


def _pareto_three(name: str = "pareto_three", noise_sd: float = 0.05) -> Surface:
    f1 = lambda lv: 10.0 + 3.0 * _unit(lv, "A") + 0.5 * _unit(lv, "C")  # noqa: E731
    f2 = lambda lv: 10.0 + 3.0 * _unit(lv, "B") + 0.5 * _unit(lv, "C")  # noqa: E731
    f3 = lambda lv: (14.0 - 2.0 * _unit(lv, "A") ** 2 - 2.0 * _unit(lv, "B") ** 2  # noqa: E731
                     + 0.5 * _unit(lv, "C"))
    return Surface(name=name, noise_sd=noise_sd,
                   factors=(_numeric("A"), _numeric("B"), _numeric("C")), fn=f1,
                   objectives=(_obj("f1", f1, noise_sd=noise_sd),
                               _obj("f2", f2, noise_sd=noise_sd),
                               _obj("f3", f3, noise_sd=noise_sd)))


def _pareto_convex_min() -> Surface:
    """``pareto_convex`` with its second objective turned into a COST to
    minimise (``cost = 30 - f2``): the same front, mirrored. Every oracle runs
    over it, so a sign or frame error on a minimised objective fails them."""
    base = _pareto_convex(name="pareto_convex_min")
    f1, f2 = base.objectives
    fn2 = f2["fn"]
    cost = {**f2, "metric": "cost", "direction": "minimize",
            "fn": lambda lv: 30.0 - fn2(lv)}
    return Surface(name="pareto_convex_min", noise_sd=base.noise_sd,
                   factors=base.factors, fn=base.fn, objectives=(f1, cost))


def _pareto_choice_split() -> Surface:
    def f1(lv):
        return (13.0 if lv["C"] == "on" else 10.0) + 3.0 * _unit(lv, "A")

    def f2(lv):
        return (12.0 if lv["C"] == "on" else 16.0) - 3.0 * _unit(lv, "A") ** 2

    return Surface(name="pareto_choice_split", noise_sd=0.05,
                   factors=(_numeric("A"), _choice("C")), fn=f1,
                   objectives=(_obj("f1", f1), _obj("f2", f2)))


PARETO_SURFACES: dict[str, Callable[[], Surface]] = {
    "pareto_convex": _pareto_convex,
    "pareto_concave": _pareto_concave,
    "pareto_with_constraint": _pareto_with_constraint,
    "pareto_three": _pareto_three,
    "pareto_choice_split": _pareto_choice_split,
    "pareto_noisy": lambda: _pareto_convex(name="pareto_noisy", noise_sd=0.25),
    "pareto_convex_min": lambda: _pareto_convex_min(),
    "pareto_three_noisy": lambda: _pareto_three(name="pareto_three_noisy", noise_sd=0.25),
}


def candidate_grid(factors_raw: list[dict], *, max_numeric_points: int = 9) -> list[dict]:
    """Every level combination worth predicting: declared levels, plus for
    numeric factors with a grid up to ``max_numeric_points`` snapped points
    spanning [min, max]. Deterministic order."""
    axes: list[list[Any]] = []
    ids: list[str] = []
    for f in factors_raw:
        ids.append(f["id"])
        levels = list(f["levels"])
        if f.get("levels_only"):
            # Only the declared levels are runnable: the truth is over them.
            axes.append(levels)
        elif f["type"] == "numeric" and f.get("grid") is not None:
            lo, hi = float(min(levels)), float(max(levels))
            n = max(2, int(max_numeric_points))
            # HAZARD for whoever adds a FRACTIONAL-grid surface: this set mixes
            # ``snap_to_grid`` output with the raw ``levels``, and the two can
            # disagree on int-vs-float representation. ``snap_to_grid`` returns
            # an int only when the grid is integral, so with ``grid: 1`` (all
            # nine current surfaces) every member is an int and the axis is
            # uniform. With ``grid: 0.5`` the snapped points are floats while
            # the declared levels are ints, and since ``pts.update(levels)``
            # runs SECOND, set insertion keeps the first-seen representative --
            # so a declared level of 2 that coincides with a snapped 2.0 stays
            # ``2.0``, while a declared level off the snap sequence enters as
            # ``2``. The axis is then mostly float with stray ints. This is
            # deterministic and ``==``-safe (2 == 2.0), so lookups and the
            # candidate enumeration are correct either way, but a consumer that
            # compares REPRESENTATIONS (a JSON round-trip diff, a CLI argument
            # rendered as "2" vs "2.0" -- see snap_to_grid's own note about
            # BLIS rejecting --max-num-running-reqs=160.0) would see the
            # inconsistency. Normalise the axis there, not here.
            pts = {snap_to_grid(lo + (hi - lo) * i / (n - 1), float(f["grid"])) for i in range(n)}
            pts.update(levels)
            axes.append(sorted(pts))
        else:
            axes.append(levels)
    return [dict(zip(ids, combo)) for combo in itertools.product(*axes)]


def _truth_grid(surface: Surface):
    """The grid the oracle judges over: every factor's candidate points, or,
    when the surface declares ``active`` factors, only theirs with each inert
    factor pinned at its first level (exact: nothing judged depends on it)."""
    if not surface.active:
        yield from candidate_grid(list(surface.factors))
        return
    act = [f for f in surface.factors if f["id"] in surface.active]
    pinned = {f["id"]: f["levels"][0] for f in surface.factors
              if f["id"] not in surface.active}
    for lv in candidate_grid(act):
        yield {**pinned, **lv}


def true_optimum(surface: Surface) -> tuple[dict, float]:
    """Best VALID level combination on the candidate grid, by ``direction``."""
    best_lv, best_v = None, None
    sign = 1.0 if surface.direction == "maximize" else -1.0
    for lv in _truth_grid(surface):
        if surface.invalid is not None and surface.invalid(lv):
            continue
        # `fails_at` points are deliberately NOT skipped. `invalid` is a fact
        # about X_valid -- the configuration is inadmissible, so it cannot be the
        # answer. `fails_at` is a fact about the INSTRUMENT -- the configuration
        # is perfectly admissible and may well be optimal; the harness just
        # cannot measure it. Skipping it here would redefine the truth to match
        # the instrument's blind spot, which is the exact error the surface
        # exists to detect in the campaign.
        v = surface.fn(lv)
        if best_v is None or sign * v > sign * best_v:
            best_lv, best_v = lv, v
    if best_lv is None:
        raise ValueError(f"surface {surface.name!r} has no valid point")
    return best_lv, best_v


def objective_values(surface: Surface, levels: dict) -> dict:
    """The NOISELESS objective vector at ``levels`` (multi-objective surfaces)."""
    return {o["metric"]: float(o["fn"](levels)) for o in surface.objectives}


def true_front(surface: Surface) -> list[tuple[dict, dict]]:
    """Every VALID grid point no other valid grid point dominates.

    Exhaustive over ``candidate_grid`` (exactly as ``true_optimum``), plain
    Pareto dominance on the noiseless objectives. ``fails_at`` points are NOT
    skipped, for the reason ``true_optimum`` gives.
    """
    pts = []
    for lv in _truth_grid(surface):
        if surface.invalid is not None and surface.invalid(lv):
            continue
        pts.append((lv, objective_values(surface, lv)))
    from orchestrator.optimize.pareto import nondominated_indices

    signs = [(-1.0 if o["direction"] == "minimize" else 1.0) for o in surface.objectives]
    vec = [[s * v[o["metric"]] for s, o in zip(signs, surface.objectives)] for _, v in pts]
    return [pts[i] for i in nondominated_indices(vec)]


def within_eps_of_front(surface: Surface, levels: dict, eps: dict, *,
                        front: list | None = None) -> bool:
    """Additive epsilon-approximate Pareto optimality of ``levels`` in TRUTH:
    no valid grid point beats it by at least ``eps[m]`` on every objective.
    ``front`` is ``true_front(surface)`` when the caller already has it."""
    me = objective_values(surface, levels)
    for lv, v in (true_front(surface) if front is None else front):
        if all(((-1.0 if o["direction"] == "minimize" else 1.0)
                * (v[o["metric"]] - me[o["metric"]])) >= eps[o["metric"]]
               for o in surface.objectives):
            return False
    return True


def _observe(surface: Surface, levels: dict, *, rng: random.Random,
             run_counter: int) -> dict:
    """One observation dict: the metric plus every declared observable.

    ``cfg.<lower>`` echoes the requested levels because that is the path
    each factor's ``manipulation`` predicate reads — the synthetic target
    behaves like a target that honestly reports what it was configured
    with. Constraint observables (``sla``'s ``p99_ms``) come from
    ``extra_observables`` so the surface, not the runner, decides what the
    target is instrumented to emit.
    """
    lv = dict(levels)
    if surface.fails_at is not None and surface.fails_at(lv):
        # RAISE, don't return a sentinel. `runner._run_once` converts a raising
        # runner into a `failed` RunOutcome, which is the real shape of a
        # wall-clock timeout or an adapter crash; a sentinel value would model
        # the failure as a measurement and defeat the surface's whole purpose.
        raise RuntimeError(
            f"synthetic target failed to measure at {lv} (surface "
            f"{surface.name!r}: fails_at). Models a wall-clock timeout or an "
            f"adapter crash -- the row produces NO measurement.",
        )
    if surface.exception_at and all(lv.get(k) == v for k, v in surface.exception_at.items()):
        m = float("nan")
    else:
        m = (surface.fn(lv) + rng.gauss(0.0, surface.noise_sd)
             + surface.drift_per_run * run_counter)
    obs = {"cfg": {k.lower(): v for k, v in lv.items()}, "m": m}
    for o in surface.objectives:
        obs[o["metric"]] = float(o["fn"](lv)) + rng.gauss(0.0, float(o.get("noise_sd", 0.0)))
    obs.update(surface.extra_observables(lv))
    if surface.noisy_observables is not None:
        obs.update(surface.noisy_observables(lv, rng))
    return obs


def make_synthetic_runner(surface: Surface, *, seed: int,
                          seed_env: str | None = None, **_extra) -> Callable:
    """An in-process ``ConfigRunner``: seeded noise, monotone run counter.

    The counter is the surface's notion of wall-clock: ``drift`` adds
    ``drift_per_run * counter`` so a sweep executed in design order picks up
    a trend that randomized run order spreads across the levels. Keyword-only
    extras are accepted and ignored so later callers can pass options this
    version does not interpret.

    ``seed_env`` makes this a model of a SEEDED target (spec §3.7 oracle 3).
    When it names an environment key the row carries in ``apply["env"]``, the
    noise for that row is drawn from ``Random(row_seed)`` instead of from the
    shared stream — so two rows at the same levels with the same seed return the
    same number, and the common-random-numbers property the ``confirm`` stage
    relies on is real rather than asserted.

    That matters for the oracle, not just for tidiness. Without it the harness
    would report a paired bound over replicates whose "shared" seed changed
    nothing, i.e. it would confirm the pairing machinery against a target for
    which pairing was decoration — the one thing an oracle must not do. The
    shared-stream behaviour is untouched when ``seed_env`` is None, so every
    existing synthetic campaign's numbers are byte-identical.

    The row seed is combined with ``seed`` rather than used alone, so two
    campaigns over the same surface with different ``seed=`` still see different
    workloads: the seed set is the WORKLOAD's identity, and the campaign seed is
    the instrument's.
    """
    rng = random.Random(seed)
    counter = {"n": 0}

    def run(row) -> dict:
        row_seed = ((getattr(row, "apply", None) or {}).get("env") or {}).get(
            seed_env,
        ) if seed_env else None
        draw = (random.Random(f"{seed}:{int(row_seed)}")
                if row_seed is not None else rng)
        obs = _observe(surface, row.levels, rng=draw, run_counter=counter["n"])
        counter["n"] += 1
        return obs
    return run


def main(argv: list[str] | None = None) -> int:
    """``python -m orchestrator.optimize.synthetic --surface K --seed S --a=4 ...``

    Emits ONE JSON object on stdout, the contract every real target's
    run_command must meet. ``run_counter`` is passed explicitly (``--run``)
    because a subprocess has no memory across calls."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--surface", required=True, choices=sorted(SURFACES))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run", type=int, default=0)
    known, rest = ap.parse_known_args(argv)
    surface = SURFACES[known.surface]()
    levels: dict = {}
    by_lower = {f["id"].lower(): f for f in surface.factors}
    for tok in rest:
        if not tok.startswith("--") or "=" not in tok:
            print(f"unrecognised argument {tok!r}", file=sys.stderr)
            return 2
        k, v = tok[2:].split("=", 1)
        f = by_lower.get(k)
        if f is None:
            print(f"unknown factor flag --{k}", file=sys.stderr)
            return 2
        levels[f["id"]] = int(v) if f["type"] == "numeric" else v

    # Symmetric with the unknown-flag check above. Without this, omitting a
    # flag reaches ``surface.fn`` with an incomplete ``levels`` dict and dies
    # on a bare ``KeyError: 'B'`` with a raw traceback and exit 1. This
    # module's docstring advertises the CLI as the contract every real
    # target's run_command must meet, so a smoke test that mis-renders one
    # ``apply`` template deserves a diagnosis naming the flag it forgot, not
    # a stack trace through a lambda.
    missing = [f["id"].lower() for f in surface.factors if f["id"] not in levels]
    if missing:
        print(
            "missing factor flag(s) "
            + ", ".join(f"--{name}" for name in missing)
            + f"; surface {known.surface!r} declares "
            + ", ".join(f"--{f['id'].lower()}" for f in surface.factors),
            file=sys.stderr,
        )
        return 2

    rng = random.Random(known.seed)
    print(json.dumps(_observe(surface, levels, rng=rng, run_counter=known.run)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
