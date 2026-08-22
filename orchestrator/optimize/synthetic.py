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
  * ``saddle`` — a stationary point that is NOT the argmax; solving
    ``grad = 0`` and reporting it is the bug.
  * ``choice_x_numeric`` — the numeric optimum flips sign with the choice
    level, so holding the choice fixed loses the optimum entirely.
  * ``drift`` — a monotone per-run trend that randomized run order absorbs
    and a time-ordered sweep would attribute to a factor.
  * ``sla`` — the unconstrained argmax violates a constraint observable, so
    the answer must be the argmax restricted to the valid region.
  * ``nan_at_corner`` — one configuration makes the target emit NaN, which
    is a semantic exception that ends the epoch rather than a datum to fit.
  * ``fails_at_one_level`` — a whole CORNER of the space never produces a
    measurement at all (wall-clock timeout / adapter crash), and the failures
    sit on ONE level of ONE factor while the same corner at that factor's other
    level measures fine. Aborting the iteration is the bug (18 rows measured,
    15 valid, all 15 discarded four times over), and so is refitting silently:
    the loss deletes the region where the mechanism under study does the most
    work, which biases that factor's coefficient in a named direction.

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


SURFACES: dict[str, Callable[[], Surface]] = {
    "additive": _additive,
    "interaction_only": _interaction_only,
    "bowl": _bowl,
    "bowl_out_of_hull": lambda: _bowl(a0=30.0, name="bowl_out_of_hull"),
    "saddle": _saddle,
    "choice_x_numeric": _choice_x_numeric,
    "drift": _drift,
    "sla": _sla,
    "nan_at_corner": _nan_at_corner,
    "fails_at_one_level": _fails_at_one_level,
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
        if f["type"] == "numeric" and f.get("grid") is not None:
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


def true_optimum(surface: Surface) -> tuple[dict, float]:
    """Best VALID level combination on the candidate grid, by ``direction``."""
    best_lv, best_v = None, None
    sign = 1.0 if surface.direction == "maximize" else -1.0
    for lv in candidate_grid(list(surface.factors)):
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
    obs.update(surface.extra_observables(lv))
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
