"""Durable artifacts for an optimization-campaign iteration (design spec 5.5).

Four new, schema-validated artifacts:

  * ``design_matrix.json`` -- the pre-registered plan, written before
    execution (``write_design_matrix``).
  * ``runs.jsonl``         -- one line per executed config, append-only
    (``append_run`` / ``read_runs``).
  * ``effects.json``       -- the fitted model: main effects, interactions,
    pure-error estimate, lack-of-fit test, aliasing caveats, dropped
    factors (``write_effects``).
  * ``relations.json``     -- per-relation verdicts from the native test
    run (``write_relations``).

Unchanged in schema and still written every iteration: ``findings.json``
and ``principle_updates.json``. In the reflective kind those are authored
by the model; here they are projected **deterministically** from a fitted
``Fit`` by ``project_findings`` and ``project_principle_updates`` --
making "screen and refine make zero LLM calls" true without dropping the
durable-artifact contract that ``/post-campaign``, ``index-wiki``,
``visualize-campaign`` and the cross-campaign registry all depend on.
This module is pure Python, following the ``orchestrator/meta_findings.py``
(#155) precedent: no I/O beyond reading/writing the artifacts themselves,
no randomness, no LLM.

**The findings-schema mapping (the load-bearing trick of this module).**
``findings.schema.json`` is unmodified and was designed for the
reflective kind's predict-then-compare epistemology: ``arm_type`` and
``status`` are closed enums with no "fitted effect" vocabulary. Rather
than widen those enums or add a parallel artifact, this module maps onto
the existing vocabulary:

  * One arm row per surviving (significant) effect: ``arm_type: "h-main"``.
    ``predicted`` is the factor's declared relation statement (the closest
    analogue to a directional hypothesis this schema has).  ``observed``
    is the fitted estimate with its CI and run count, rendered as a
    string. ``status`` is ``CONFIRMED`` when the CI excludes zero in the
    hypothesised direction, ``REFUTED`` when it excludes zero in the
    opposite direction, ``PARTIALLY_CONFIRMED`` otherwise (including the
    "significance unknown" case -- see below).
  * One arm row per factor dropped as within-noise: ``arm_type:
    "h-control-negative"``, ``status: "REFUTED"``, with the noise floor
    (the term's standard error) named in ``diagnostic_note``.
  * A factor whose ``significant`` is ``None`` (no pure-error estimate --
    unknown, not measured-null; see ``effects.py``) is neither "surviving"
    nor "dropped": it gets ``PARTIALLY_CONFIRMED`` with the unknown-ness
    stated in ``diagnostic_note``, and is excluded from
    ``h-control-negative``.
  * Everything optimization-specific -- label, estimate, ci_low, ci_high,
    se, stage, aliases -- goes in ``metadata``, an OPEN object with no
    ``additionalProperties: false``.
  * ``experiment_valid`` is ``False`` iff a passed-in correctness relation
    verdict failed.

``principles.schema.json`` needs no such trick: its enums map naturally
(``confidence`` from CI width relative to the estimate, ``derivation_type:
"empirical"``, ``category: "domain"``, ``status: "active"``), and
``evidence`` is ``array[string]`` so numeric citations go in as formatted
strings that pass ``meta_findings.validate_evidence``'s citation floor by
construction (every string names a number).

Determinism: every writer sorts effects by descending ``abs(estimate)``
before rendering, so repeated calls with identical input produce
byte-identical files. No timestamps appear inside any payload body.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from orchestrator.optimize.effects import Effect, Fit
from orchestrator.optimize.factors import Factor
from orchestrator.optimize.relations import RelationVerdict
from orchestrator.util import atomic_write

logger = logging.getLogger(__name__)


def _dump(payload: Any) -> str:
    """Canonical, deterministic JSON rendering -- sorted keys, trailing newline."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ─── design_matrix.json ─────────────────────────────────────────────────


def write_design_matrix(iter_dir: Path, payload: dict) -> Path:
    """Write the pre-registered design matrix. Written before execution."""
    iter_dir = Path(iter_dir)
    target = iter_dir / "design_matrix.json"
    atomic_write(target, _dump(payload))
    return target


# ─── runs.jsonl ─────────────────────────────────────────────────────────


def append_run(iter_dir: Path, row: dict) -> None:
    """Append one JSON line to runs.jsonl. Append-only: never rewritten,
    so a crash mid-campaign leaves every already-completed row intact.
    """
    iter_dir = Path(iter_dir)
    target = iter_dir / "runs.jsonl"
    line = json.dumps(row, sort_keys=True) + "\n"
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(line)


def read_runs(iter_dir: Path) -> list[dict]:
    """Read every row of runs.jsonl, in append order.

    Tolerates a torn **trailing** line: ``append_run`` writes one line at a
    time, so the only way a line can be malformed is a crash mid-write of
    the last line in the file -- every earlier line was already flushed by
    a prior, completed ``append_run`` call. That torn final line is skipped
    (and reported via ``logger.warning``, naming the file and line number)
    rather than raising, so completed rows survive a crashed run exactly as
    the append-only contract promises: the campaign can refit on whatever
    completed and report the reduced resolution honestly, instead of losing
    every already-written row.

    A malformed line anywhere *other* than the last is a different failure
    mode entirely -- a crash cannot tear an interior line, since every line
    before it was already terminated before the next ``append_run`` began.
    That case still raises ``json.JSONDecodeError``: silently skipping it
    would hide real corruption rather than a crash signature.
    """
    target = Path(iter_dir) / "runs.jsonl"
    if not target.exists():
        return []
    lines = target.read_text(encoding="utf-8").splitlines()
    last_nonblank = -1
    for idx, line in enumerate(lines):
        if line.strip():
            last_nonblank = idx

    out: list[dict] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            out.append(json.loads(stripped))
        except json.JSONDecodeError:
            if idx == last_nonblank:
                logger.warning(
                    "read_runs: skipping torn trailing line %d in %s "
                    "(crash mid-append) -- %d completed row(s) still returned",
                    idx + 1, target, len(out),
                )
                break
            raise
    return out


# ─── effects.json ───────────────────────────────────────────────────────


def _effect_to_dict(e: Effect) -> dict:
    return {
        "label": e.label,
        "terms": list(e.terms),
        "estimate": e.estimate,
        "se": e.se,
        "ci_low": e.ci_low,
        "ci_high": e.ci_high,
        "significant": e.significant,
    }


def _sorted_effects(effects: tuple[Effect, ...]) -> list[Effect]:
    """Descending |estimate| order, ties broken by label for stability."""
    return sorted(effects, key=lambda e: (-abs(e.estimate), e.label))


def write_effects(iter_dir: Path, fit: Fit, *, factors: list[Factor],
                   stage: str, exclusion_balance: dict | None = None,
                   work_dir: Path | str | None = None,
                   direction: str | None = None,
                   noise_pct: float | None = None,
                   fit_coordinates: dict | None = None,
                   omitted_terms=None,
                   interactions_dropped: bool = False,
                   planned_aliases_separated=None,
                   curvature_untested_levels=None,
                   lost_levels=None) -> Path:
    """Write the fitted model: effects, pure error, lack-of-fit, aliases,
    dropped factors. ``factors`` supplies the factor-id universe that
    ``dropped_factors`` checks against -- the factors this fit was run
    over, in their declared order.

    ``exclusion_balance`` (``orchestrator.optimize.exclusions.ExclusionBalance``
    rendered by ``as_dict``) is present ONLY when rows were excluded from the
    fit, and it carries whether that exclusion was independent of the factor
    levels. It lives HERE, on the artifact that carries the coefficients, and
    not only in ``fit_exclusions.json``, for the reason the exclusions module
    documents: a balanced loss widens every confidence interval, so the
    arithmetic already reports it, while a LEVEL-CORRELATED loss moves a point
    estimate and leaves its interval exactly as tight as before. A reader (or a
    downstream projection) consuming ``effects[i].estimate`` has to see the
    caveat next to the number it qualifies, not in a sibling file they may not
    open.

    ``caveat`` is a rendered sentence rather than a flag alone because
    ``project_findings`` and ``project_principle_updates`` derive prose from this
    artifact, and a caveat that only exists as a boolean would be dropped by
    every one of them.
    """
    iter_dir = Path(iter_dir)
    target = iter_dir / "effects.json"

    from orchestrator.optimize.effects import dropped_factors as _dropped
    factor_ids = [f.id for f in factors]
    dropped = _dropped(fit, factor_ids)

    payload = {
        "stage": stage,
        "intercept": fit.intercept,
        "n_runs": fit.n_runs,
        "pure_error_var": fit.pure_error_var,
        "pure_error_df": fit.pure_error_df,
        "lack_of_fit_f": fit.lack_of_fit_f,
        "lack_of_fit_p": fit.lack_of_fit_p,
        "aliases": [list(pair) for pair in fit.aliases],
        "effects": [_effect_to_dict(e) for e in _sorted_effects(fit.effects)],
        "quadratic": [_effect_to_dict(e) for e in _sorted_effects(fit.quadratic)],
        "dropped_factors": sorted(dropped),
    }
    if fit.factor_tests:
        payload["categoricals"] = categorical_record(fit, factors, lost_levels)
        payload["centre_isolated"] = bool(fit.centre_isolated)
        if fit.centre_isolation_reason:
            payload["centre_isolation_reason"] = fit.centre_isolation_reason
        payload["variance_inflation"] = {k: v for k, v in fit.variance_inflation}
    if exclusion_balance is not None:
        payload["exclusion_balance"] = exclusion_balance
    # INV-STAT14: the coordinates the regression was fitted on (the coded
    # ACTUAL levels) beside the planned ones, per fitted row, so a reader can
    # audit a clamped axial point or a choice factor's centre row without
    # refitting. Optional so every caller that predates it is byte-identical.
    if fit_coordinates is not None:
        payload["fit_coordinates"] = fit_coordinates
    # Higher-order terms left out because their column lies in the span of the
    # intercept and main effects on the fitted rows (exclusions.non_estimable_terms).
    # Present only when non-empty, so earlier payloads are byte-identical.
    if omitted_terms:
        payload["omitted_terms"] = [list(t) for t in omitted_terms]
    # The fitted rows could not support any two-factor interaction (the full
    # model was rank-deficient -- e.g. a resolution-III mixed-level screen
    # whose collapsed categorical leaves 2fi columns partially aliased), so the
    # fit is MAIN EFFECTS ONLY. Recorded on the artifact the reduced model is
    # read from; present only when it happened (earlier payloads unchanged).
    if interactions_dropped:
        payload["interactions_dropped"] = True
    if curvature_untested_levels:
        # Choice levels no fitted centre row ran: lack of fit (the curvature
        # check) says nothing about them (stage-1 M8).
        payload["curvature_untested_levels"] = dict(curvature_untested_levels)
    if planned_aliases_separated:
        payload["planned_aliases_separated"] = list(planned_aliases_separated)
    if fit.span_aliased:
        payload["aliased_in_span"] = [
            {"term": list(t), "spanned_by": list(sp)} for t, sp in fit.span_aliased]

    # Hold the `plan` stage to its own prediction, on the artifact that carries
    # the coefficient the prediction was about. Same reasoning as
    # `exclusion_balance` above: a caveat in a sibling file is one the reader may
    # never open, and `project_findings` derives its prose from here. All three
    # arguments are optional, so every caller written before `plan` existed keeps
    # working and produces a byte-identical payload.
    if work_dir is not None and direction and noise_pct is not None:
        from orchestrator.optimize.plan import check_plan_against_effect, read_plan

        plan = read_plan(work_dir)
        if plan:
            flags: list[str] = []
            for eff in fit.effects:
                if len(getattr(eff, "terms", ()) or ()) != 1:
                    continue      # main effects only: one term, one factor
                flags += check_plan_against_effect(
                    plan, factor_id=str(eff.label), effect=float(eff.estimate),
                    direction=direction, noise_pct=float(noise_pct),
                    baseline=float(fit.intercept),
                )
            if flags:
                payload["plan_contradictions"] = flags

    atomic_write(target, _dump(payload))
    return target


def categorical_record(fit: Fit, factors, lost_levels=None) -> list[dict]:
    """``effects.json["categoricals"]``: per multi-level categorical, its L-1 df
    F test and, per level, the coded vector, the main-effect contribution
    ``sum_j b_j c_j(level)`` (defined only up to a constant -- it depends on
    the contrast basis; DIFFERENCES between levels do not) and the
    LEAST-SQUARES MEAN (Searle, Speed &
    Milliken 1980, population marginal means): the predicted response at that
    level with every numeric and two-level factor at its coded centre and every
    other categorical averaged over its levels. With main effects and 2fi only
    (no 3fi), averaging a product equals the product of averages, so the
    prediction at the averaged coding IS the marginal mean.

    A LOST level (``lost_levels``: no retained row; stage-1b N2) has NO
    estimate -- its contrasts were dropped, so a prediction there would read
    the dropped coefficients as zero and fabricate a mean. It is reported with
    ``ls_mean``/``effect`` null and ``lost: true``, and other categoricals are
    averaged over their RETAINED levels only."""
    from orchestrator.optimize.decide import predict
    from orchestrator.optimize.factors import code_vector, is_categorical, model_columns

    by_id = {f.id: f for f in factors}
    owner = dict(fit.groups)
    gone = {k: {json.dumps(v) for v in vs} for k, vs in (lost_levels or {}).items()}

    def retained(f):
        return [lv for lv in f.levels if json.dumps(lv) not in gone.get(f.id, set())]

    base: dict[str, float] = {}
    for col, g in owner.items():
        f = by_id.get(g)
        if f is not None and is_categorical(f):
            k = model_columns(f).index(col)
            kept = retained(f)
            base[col] = sum(code_vector(f, lv)[k] for lv in kept) / len(kept)
        else:
            base[col] = 0.0
    est = {e.terms[0]: e.estimate for e in fit.effects if len(e.terms) == 1}
    out = []
    for t in fit.factor_tests:
        f = by_id.get(t.factor)
        levels = []
        for lv in (f.levels if f is not None else ()):
            vec = code_vector(f, lv)
            if json.dumps(lv) in gone.get(t.factor, set()):
                levels.append({"level": lv, "coded": list(vec), "effect": None,
                               "ls_mean": None, "lost": True})
                continue
            coded = {**base, **dict(zip(model_columns(f), vec))}
            levels.append({
                "level": lv, "coded": list(vec),
                "effect": sum(est.get(c, 0.0) * v for c, v in zip(model_columns(f), vec)),
                "ls_mean": predict(fit, coded),
            })
        n_fit = sum(1 for x in levels if not x.get("lost"))
        out.append({"factor": t.factor, "columns": list(t.columns), "df": t.df,
                    "f": t.f, "p": t.p, "significant": t.significant,
                    "test": "wald_f_on_pure_error", "levels": levels,
                    **({"levels_fitted": n_fit, "levels_declared": len(levels)}
                       if f is not None and n_fit < len(levels) else {})})
    return out


# ─── relations.json ─────────────────────────────────────────────────────


def _verdict_to_dict(v: RelationVerdict) -> dict:
    return {
        "relation_id": v.relation_id,
        "factor_id": v.factor_id,
        "kind": v.kind,
        "native_test": v.native_test,
        "passed": v.passed,
        "detail": v.detail,
    }


def write_relations(iter_dir: Path, verdicts: list[RelationVerdict]) -> Path:
    """Write per-relation verdicts plus the correctness/behavioral split."""
    iter_dir = Path(iter_dir)
    target = iter_dir / "relations.json"

    from orchestrator.optimize.relations import classify_failures
    correctness, behavioral = classify_failures(list(verdicts))

    payload = {
        "verdicts": [_verdict_to_dict(v) for v in verdicts],
        "correctness_failures": [v.relation_id for v in correctness],
        "behavioral_failures": [v.relation_id for v in behavioral],
    }
    atomic_write(target, _dump(payload))
    return target


# ─── findings.json projection ───────────────────────────────────────────


def _factor_statement(factor: Factor | None) -> str:
    """The factor's declared correctness/behavioral relation statement,
    used as the closest analogue to a directional hypothesis the
    (reflective-kind-shaped) findings schema has. Falls back to a
    generic sentence naming the factor id when no relation carries a
    statement, so ``predicted`` is never empty.
    """
    if factor is not None:
        for rel in factor.relations:
            stmt = rel.get("statement")
            if stmt:
                return str(stmt)
    fid = factor.id if factor is not None else "factor"
    return f"{fid} has a non-zero main effect on the response"


def _render_observed(e: Effect, n_runs: int) -> str:
    """Render the fitted estimate + CI + run count as a string. Every
    numeric ingredient the schema description promises (estimate, CI
    bounds, run count) must be recoverable from this string by
    construction -- it is assembled from numbers, never invented prose.
    """
    if e.ci_low is None or e.ci_high is None or e.se is None:
        return (
            f"estimate={e.estimate:.6g} (significance unknown -- no "
            f"pure-error estimate available; n_runs={n_runs})"
        )
    return (
        f"estimate={e.estimate:.6g}, 95% CI=[{e.ci_low:.6g}, {e.ci_high:.6g}], "
        f"se={e.se:.6g}, n_runs={n_runs}"
    )


def _main_effect_status(e: Effect, statement: str) -> tuple[str, str | None]:
    """(status, error_type) for a surviving/uncertain main effect.

    The hypothesised direction is read off the statement's own polarity
    words ("increas*"/"decreas*"/"positive"/"negative") when present;
    absent any such cue the direction is treated as "same sign as the
    estimate" so an ordinary CONFIRMED is still reachable without
    requiring authors to write direction-coded prose.
    """
    if e.significant is None:
        return "PARTIALLY_CONFIRMED", None

    lowered = statement.lower()
    if "decreas" in lowered or "negative" in lowered:
        hypothesised_sign = -1
    elif "increas" in lowered or "positive" in lowered:
        hypothesised_sign = 1
    else:
        hypothesised_sign = 1 if e.estimate >= 0 else -1

    if e.significant is False:
        return "PARTIALLY_CONFIRMED", None

    # significant is True: CI excludes zero: check direction
    actual_sign = 1 if e.estimate >= 0 else -1
    if actual_sign == hypothesised_sign:
        return "CONFIRMED", None
    return "REFUTED", "direction"


def project_findings(fit: Fit, *, factors: list[Factor], stage: str,
                      decision: str, iteration: int, bundle_ref: str,
                      relation_verdicts: list[RelationVerdict] | None = None,
                      direction: str = "maximize",
                      lost_levels=None,
                      ) -> dict:
    """Build a ``findings.schema.json``-conformant dict from a fitted model.

    Pure function -- callers write it via the standard atomic-write path
    (mirroring how ``iteration.py`` writes the reflective kind's
    model-authored ``findings.json``). ``decision`` is the stage-rule
    outcome (e.g. "refine", "confirm") and is recorded in ``metadata`` for
    traceability; it does not affect the mapping.
    """
    by_id = {f.id: f for f in factors}
    main_effects = _single_column_mains(fit)

    surviving: list[Effect] = []
    dropped: list[Effect] = []
    uncertain: list[Effect] = []
    for e in main_effects:
        if e.significant is True:
            surviving.append(e)
        elif e.significant is False:
            dropped.append(e)
        else:
            uncertain.append(e)

    arms: list[dict] = []

    for e in _sorted_effects(tuple(surviving) + tuple(uncertain)):
        fid = e.terms[0]
        factor = by_id.get(fid)
        statement = _factor_statement(factor)
        status, error_type = _main_effect_status(e, statement)
        diagnostic = (
            f"main effect {e.label} unknown-significance: no pure-error "
            f"estimate (no replicated center points) at stage={stage}."
            if e.significant is None else
            f"main effect {e.label} CI excludes zero at stage={stage}."
        )
        arms.append({
            "arm_type": "h-main",
            "predicted": statement,
            "observed": _render_observed(e, fit.n_runs),
            "status": status,
            "error_type": error_type,
            "diagnostic_note": diagnostic,
            "metadata": {
                "label": e.label,
                "terms": list(e.terms),
                "estimate": e.estimate,
                "se": e.se,
                "ci_low": e.ci_low,
                "ci_high": e.ci_high,
                "significant": e.significant,
                "stage": stage,
                "decision": decision,
                "aliases": [list(pair) for pair in fit.aliases],
            },
        })

    for e in _sorted_effects(tuple(dropped)):
        fid = e.terms[0]
        factor = by_id.get(fid)
        statement = _factor_statement(factor)
        noise_floor = e.se if e.se is not None else 0.0
        arms.append({
            "arm_type": "h-control-negative",
            "predicted": statement,
            "observed": _render_observed(e, fit.n_runs),
            "status": "REFUTED",
            "error_type": "magnitude",
            "diagnostic_note": (
                f"main effect {e.label} dropped as within-noise at "
                f"stage={stage}: |estimate|={abs(e.estimate):.6g} did not "
                f"exceed the noise floor se={noise_floor:.6g}."
            ),
            "metadata": {
                "label": e.label,
                "terms": list(e.terms),
                "estimate": e.estimate,
                "se": e.se,
                "ci_low": e.ci_low,
                "ci_high": e.ci_high,
                "significant": e.significant,
                "stage": stage,
                "decision": decision,
                "aliases": [list(pair) for pair in fit.aliases],
            },
        })

    for c in (categorical_record(fit, factors, lost_levels) if fit.factor_tests else ()):
        arms.append(_categorical_arm(c, by_id.get(c["factor"]), stage, decision, fit,
                                     direction=direction))

    if not arms:
        # findings.schema.json requires arms to be non-empty (minItems: 1).
        # A fit with no main effects at all (degenerate/edge case) still
        # needs a row; report the intercept itself rather than fabricate
        # a factor that was never fitted.
        arms.append({
            "arm_type": "h-control-negative",
            "predicted": "the fitted model has no main effects to report",
            "observed": (
                f"intercept={fit.intercept:.6g}, n_runs={fit.n_runs}"
            ),
            "status": "REFUTED",
            "error_type": None,
            "diagnostic_note": (
                f"no main effects were present in this fit at stage={stage}."
            ),
            "metadata": {"stage": stage, "decision": decision},
        })

    correctness_failed = False
    if relation_verdicts:
        from orchestrator.optimize.relations import classify_failures
        correctness, _behavioral = classify_failures(list(relation_verdicts))
        correctness_failed = bool(correctness)

    discrepancy = (
        f"stage={stage} decision={decision}: {len(surviving)} effect(s) "
        f"confirmed/refuted by CI, {len(dropped)} dropped as within-noise, "
        f"{len(uncertain)} of unknown significance, over n_runs={fit.n_runs}."
    )

    return {
        "iteration": iteration,
        "bundle_ref": bundle_ref,
        "arms": arms,
        "experiment_valid": not correctness_failed,
        "discrepancy_analysis": discrepancy,
    }


# ─── principle_updates.json projection ──────────────────────────────────


def _confidence_from_ci(e: Effect) -> str:
    """CI half-width relative to |estimate| -> low/medium/high confidence.

    A tight CI relative to the estimate's magnitude is high confidence;
    a wide one (or no CI at all) is low confidence.
    """
    if e.ci_low is None or e.ci_high is None or e.estimate == 0:
        return "low"
    half_width = (e.ci_high - e.ci_low) / 2.0
    denom = abs(e.estimate)
    if denom <= 0:
        return "low"
    ratio = half_width / denom
    if ratio <= 0.25:
        return "high"
    if ratio <= 0.75:
        return "medium"
    return "low"


def project_principle_updates(fit: Fit, *, factors: list[Factor],
                               stage: str, direction: str = "maximize",
                               lost_levels=None) -> dict:
    """Build a ``principles.schema.json``-conformant dict from a fitted
    model. One principle per main effect (surviving or dropped); each
    entry's ``evidence`` is a list of numeric-citation strings that pass
    ``meta_findings.validate_evidence``'s floor by construction.
    """
    by_id = {f.id: f for f in factors}
    main_effects = _single_column_mains(fit)
    objective_direction = direction  # the loop below reuses the name

    principles: list[dict] = []
    for e in _sorted_effects(tuple(main_effects)):
        fid = e.terms[0]
        factor = by_id.get(fid)
        name = factor.name if factor is not None else fid

        if e.significant is False:
            statement = f"{name} ({fid}) has no measurable effect on the response"
            mechanism = (
                f"fitted main effect estimate={e.estimate:.6g} did not "
                f"clear the pure-error noise floor se={e.se:.6g}"
                if e.se is not None else
                f"fitted main effect estimate={e.estimate:.6g}"
            )
        elif e.significant is True:
            direction = "increases" if e.estimate >= 0 else "decreases"
            statement = f"{name} ({fid}) {direction} the response"
            mechanism = (
                f"fitted main effect estimate={e.estimate:.6g} with 95% "
                f"CI=[{e.ci_low:.6g}, {e.ci_high:.6g}] excluding zero"
            )
        else:
            statement = (
                f"{name} ({fid})'s effect on the response is not yet "
                f"determined (significance unknown)"
            )
            mechanism = (
                f"fitted main effect estimate={e.estimate:.6g}; no "
                f"pure-error estimate available (no replicated center points)"
            )

        evidence = [
            f"effects.json (stage={stage}): {e.label} estimate={e.estimate:.6g}, "
            f"n_runs={fit.n_runs}"
        ]
        if e.se is not None:
            evidence.append(f"{e.label} se={e.se:.6g}")
        if e.ci_low is not None and e.ci_high is not None:
            evidence.append(
                f"{e.label} 95% CI=[{e.ci_low:.6g}, {e.ci_high:.6g}]"
            )

        principles.append({
            "id": f"opt-{stage}-{fid}",
            "statement": statement,
            "confidence": _confidence_from_ci(e),
            "regime": stage,
            "evidence": evidence,
            "contradicts": [],
            "extraction_iteration": 0,
            "mechanism": mechanism,
            "applicability_bounds": (
                f"screened/fitted range for factor {fid} at stage={stage}"
            ),
            "superseded_by": None,
            "category": "domain",
            "status": "active",
            "derivation_type": "empirical",
        })

    for c in (categorical_record(fit, factors, lost_levels) if fit.factor_tests else ()):
        principles.append(_categorical_principle(c, by_id.get(c["factor"]), stage, fit,
                                                 direction=objective_direction))

    return {"principles": principles}


def _single_column_mains(fit: Fit) -> list[Effect]:
    """Main effects of SINGLE-column factors. A multi-level categorical's
    contrasts are basis-dependent (which level a contrast singles out is a
    coding choice), so it is projected once, from its L-1 df F test and its
    per-level LS means, by ``_categorical_arm`` / ``_categorical_principle``."""
    owned = {c for t in fit.factor_tests for c in t.columns}
    return [e for e in fit.effects if len(e.terms) == 1 and e.terms[0] not in owned]


def _cat_observed(c: dict, fit: Fit) -> str:
    means = ", ".join(f"{lv['level']}={lv['ls_mean']:.6g}" if lv.get("ls_mean") is not None
                      else f"{lv['level']}=lost" for lv in c["levels"])
    if c["f"] is None:
        return (f"L-1={c['df']} df main effect; significance unknown -- no "
                f"pure-error estimate; LS means {means}; n_runs={fit.n_runs}")
    return (f"F={c['f']:.6g} on ({c['df']}, {fit.pure_error_df}) df, p={c['p']:.3g}; "
            f"LS means {means}; n_runs={fit.n_runs}")


def _best_ls(c: dict, direction: str):
    """The level with the BEST least-squares mean for the campaign's direction
    (lowest when minimizing; stage-1 M9), or ``None``."""
    est = [lv for lv in c["levels"] if lv.get("ls_mean") is not None]
    if not est:
        return None
    sign = -1.0 if direction == "minimize" else 1.0
    return max(est, key=lambda lv: sign * lv["ls_mean"])


def _categorical_arm(c: dict, factor, stage: str, decision: str, fit: Fit, *,
                     direction: str = "maximize") -> dict:
    statement = _factor_statement(factor)
    b = _best_ls(c, direction)
    best = b["level"] if b else None
    if c["significant"] is False:
        arm_type, status, err = "h-control-negative", "REFUTED", "magnitude"
        note = (f"categorical {c['factor']} dropped as within-noise at stage={stage}: "
                f"the {c['df']} df F test did not reject (p={c['p']:.3g}).")
    elif c["significant"] is None:
        arm_type, status, err = "h-main", "PARTIALLY_CONFIRMED", None
        note = (f"categorical {c['factor']} unknown-significance: no pure-error "
                f"estimate at stage={stage}.")
    else:
        arm_type, status, err = "h-main", "CONFIRMED", None
        note = (f"categorical {c['factor']}: the {c['df']} df F test rejects equal "
                f"levels at stage={stage}; best LS mean at {best!r}.")
    return {
        "arm_type": arm_type, "predicted": statement,
        "observed": _cat_observed(c, fit), "status": status, "error_type": err,
        "diagnostic_note": note,
        "metadata": {"label": c["factor"], "terms": list(c["columns"]),
                     "f": c["f"], "p": c["p"], "df": c["df"],
                     "significant": c["significant"], "best_level": best,
                     "direction": direction,
                     "levels": c["levels"], "stage": stage, "decision": decision,
                     "aliases": [list(pair) for pair in fit.aliases]},
    }


def _categorical_principle(c: dict, factor, stage: str, fit: Fit, *,
                           direction: str = "maximize") -> dict:
    fid = c["factor"]
    name = factor.name if factor is not None else fid
    best = _best_ls(c, direction)
    if c["significant"] is False:
        statement = f"{name} ({fid}) has no measurable effect on the response"
    elif c["significant"] is True and best is not None:
        statement = (f"{name} ({fid}) matters; {best['level']!r} has the best "
                     f"least-squares mean response ({'lowest' if direction == 'minimize' else 'highest'}, "
                     f"for direction {direction})")
    else:
        statement = (f"{name} ({fid})'s effect on the response is not yet "
                     f"determined (significance unknown)")
    p = c["p"]
    conf = "low" if p is None else "high" if p < 0.001 else "medium" if p < 0.05 else "low"
    return {
        "id": f"opt-{stage}-{fid}", "statement": statement, "confidence": conf,
        "regime": stage,
        "evidence": [f"effects.json (stage={stage}): {fid} " + _cat_observed(c, fit)],
        "contradicts": [], "extraction_iteration": 0,
        "mechanism": (f"Wald F test of the {c['df']} df main effect on pure error "
                      f"(method-of-replacement screen)"),
        "applicability_bounds": f"declared levels {[lv['level'] for lv in c['levels']]} at stage={stage}",
        "superseded_by": None, "category": "domain", "status": "active",
        "derivation_type": "empirical",
    }
