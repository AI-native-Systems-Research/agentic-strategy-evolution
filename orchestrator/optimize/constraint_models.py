"""Fitted models of the CONSTRAINT metrics, used to rank candidates honestly.

Why this module exists
----------------------
The fitting stages model only the primary metric. ``decide.ranked`` therefore
ranks the candidate space with no idea where ``response.constraints`` binds,
and the only thing standing between an infeasible region and the terminal
shortlist was the exact-match ``_measured_infeasible`` skip: a candidate was
dropped only if its EXACT levels had been measured inadmissible.

Observed on a real campaign (primary ``throughput_rps`` maximised, constraint
``p99_ms <= 90``): the screen measured every row at ``BS=32, CMP=on``
infeasible, the fitted surface still ranked ``BS=32, CMP=on, PF=6`` and
``BS=32, CMP=on, PF=2`` highest -- interior points of the very corner every
measurement had refused -- and a whole confirm round was spent measuring them
infeasible, which then withheld certification of an otherwise-correct answer.
``SURFACES["infeasible_corner_interior"]`` reproduces that shape in closed
form.

The standard constrained response-surface remedy is to fit each constraint
metric with the same design and model family as the primary and use those
models when ranking. Infeasible rows are VALID measurements of the constraint
metric -- they are exactly the rows that say where the boundary is -- so they
enter this fit even though they are excluded from the primary's. Failed and
rejected rows are not measurements and stay out.

The decision rule, and why it is one-sided
------------------------------------------
A candidate is EXCLUDED only when it is CONFIDENTLY predicted infeasible: the
constraint's one-sided ``1 - delta`` confidence bound lies entirely on the
violating side. For ``metric <= v`` that is ``lower = yhat - t * se > v``.
Never on the point prediction alone: model error would then delete the true
optimum whenever it sits near the boundary, and recovering from that costs a
whole epoch while seating an uncertain candidate costs one confirm row. An
uncertain candidate therefore stays, and only a measurement settles it.

``t`` is the one-sided Student quantile at ``1 - delta / C`` on the constraint
fit's pure-error df, where ``C`` is the number of constraints actually
modelled (Bonferroni over constraints): the probability that the TRUE
constrained optimum is wrongly excluded by ANY constraint is then at most
``delta``. Only the true optimum's own exclusion matters for that claim, so no
division by the number of candidates is needed -- excluding a point that is in
fact infeasible costs nothing. That risk is the same kind ``delta_s`` already
names ("screening did not exclude the winner", spec §3.3), and the docs record
it as such.

Prediction uncertainty is the per-coefficient arithmetic ``certificate``
already uses: ``Var(yhat(x)) = Var(b0) + sum_e se_e^2 * col_e(x)^2``, with the
intercept's SE from the same per-column formula ``effects.fit_effects`` uses
for every other term (``sigma / sqrt(N)``). Exact for the orthogonal main /
two-factor columns; optimistic for the intercept and pure-quadratic columns on
a central composite, by the factor ``effects.py`` documents. That is the
registered response-class assumption the model bound already carries.

When a constraint cannot be modelled
------------------------------------
``==`` / ``!=`` (no side to be confidently on), a guarded constraint
(``when`` / ``when_not``), a non-numeric threshold, a metric missing or
non-numeric on a measured row, a singular or rank-deficient model, no pure
error (a deterministic constraint metric gives ``pure_error = 0``, and an
unknown variance is not a zero one), or a lack-of-fit test that rejects the
model: each falls back to TODAY'S behaviour for that constraint -- no
model-based exclusion -- and the reason is recorded in
``recommendation.json["constraint_models"]`` so the fallback is auditable.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from scipy.stats import t as student_t

from orchestrator.optimize.effects import Fit, fit_effects

#: Comparators whose violating side is well defined. ``==``/``!=`` are not
#: modellable: a confidence band can never sit "entirely on the violating side"
#: of an equality, so those constraints are left to measurement.
MODELLABLE_OPS = frozenset({"<", "<=", ">", ">="})

#: Lack-of-fit p-value below which a constraint model is not trusted to
#: exclude anything. The primary's ``model_adequate`` uses the same test.
LACK_OF_FIT_ALPHA = 0.05

#: The rows that carry a trustworthy measurement of a constraint metric.
_MEASURED = frozenset({"complete", "infeasible"})

_MISSING = object()


@dataclass(frozen=True)
class ConstraintModel:
    """One ``response.constraints`` entry and, when it could be fitted, its model.

    ``fit is None`` means the constraint is UNMODELLED and ``reason`` says why;
    an unmodelled constraint never excludes a candidate.
    """

    metric: str
    op: str
    value: object
    fit: Fit | None
    reason: str
    n_rows: int = 0

    @property
    def modelled(self) -> bool:
        return self.fit is not None


def _resolve(path: str, observed: dict):
    cur = observed
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _why_not_modellable(constraint: dict) -> str:
    """Empty when the constraint has a well-defined violating side, else why not."""
    op = constraint.get("op")
    if op not in MODELLABLE_OPS:
        return f"op {op!r} has no violating side a confidence bound can sit on"
    if "when" in constraint or "when_not" in constraint:
        return "guarded by when/when_not; the guard is a level filter, not a model term"
    v = constraint.get("value")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return f"threshold {v!r} is not a number"
    if not (constraint.get("metric") or constraint.get("observable")):
        return "names no metric"
    return ""


def fit_constraint_models(constraints, design, records, *, fitted_ids,
                          held_levels: dict | None = None,
                          levels_by_pos=None) -> list[ConstraintModel]:
    """Fit every numeric constraint metric over the same design as the primary.

    ``design`` is the design CODED FROM THE LEVELS THAT RAN
    (``matrix.coded_as_run``, INV-STAT14) -- the same matrix the primary is
    fitted on -- not the nominal plan: a clamped axial point or a choice
    factor's centre row coded nominally biases the constraint model exactly as
    it biases the primary, and a lack-of-fit rejection then disables the model.

    ``records`` is one ``(status, response)`` pair per POSITION of ``design``
    (the same positional convention as the primary's response vector). Rows
    whose status is ``complete`` or ``infeasible`` and whose metric is a finite
    number are fitted; everything else is left out. ``fitted_ids`` is the
    primary fit's factor set, so the constraint model predicts at exactly the
    candidates' coded coordinates. When the primary dropped a non-identifiable
    factor (``held_levels``), only rows measured at the held level enter, so a
    constraint row from the other level is not read as a replicate.
    """
    out: list[ConstraintModel] = []
    keep_ids = [f for f in design.factor_ids if f in set(fitted_ids)]
    cols = [j for j, f in enumerate(design.factor_ids) if f in set(fitted_ids)]
    for c in constraints or ():
        metric = str(c.get("metric") or c.get("observable") or "")
        op, value = c.get("op"), c.get("value")
        why = _why_not_modellable(c)
        if why:
            out.append(ConstraintModel(metric, op, value, None, why))
            continue
        pos, ys = [], []
        bad = None
        for i, (status, response) in enumerate(records):
            if status not in _MEASURED:
                continue
            if held_levels and levels_by_pos is not None:
                lv = levels_by_pos[i] or {}
                if any(lv.get(k) != v for k, v in held_levels.items()):
                    continue
            raw = _resolve(metric, response or {})
            try:
                y = float(raw) if raw is not _MISSING and raw is not None \
                    and not isinstance(raw, bool) else None
            except (TypeError, ValueError):
                y = None
            if y is None or not math.isfinite(y):
                bad = i
                break
            pos.append(i)
            ys.append(y)
        if bad is not None:
            out.append(ConstraintModel(
                metric, op, value, None,
                f"metric missing or non-numeric on measured row at position {bad}"))
            continue
        sub = dataclasses.replace(
            design, factor_ids=tuple(keep_ids),
            points=tuple(
                dataclasses.replace(
                    design.points[i],
                    coded=tuple(design.points[i].coded[j] for j in cols),
                )
                for i in pos
            ),
        )
        # Same reduction the primary fit uses (stage_runner floor (c)): omit
        # each higher-order term that is a function of the intercept and main
        # effects on these rows, then fall back to main effects only.
        from orchestrator.optimize.exclusions import non_estimable_terms

        omit = non_estimable_terms(sub)
        fit = None
        for interactions in (True, False):
            try:
                fit = fit_effects(sub, ys, factor_ids=keep_ids,
                                  include_interactions=interactions,
                                  omit_terms=omit)
                break
            except ValueError:
                continue
        if fit is None:
            out.append(ConstraintModel(
                metric, op, value, None,
                f"model not estimable from the {len(ys)} measured row(s) (singular)",
                n_rows=len(ys)))
            continue
        terms = list(fit.effects) + list(fit.quadratic)
        if fit.pure_error_df <= 0 or not fit.pure_error_var or any(
                e.se is None for e in terms):
            out.append(ConstraintModel(
                metric, op, value, None,
                "no pure-error estimate (no replicated centre points, or a "
                "deterministic constraint metric): an unknown variance is not zero",
                n_rows=len(ys)))
            continue
        if fit.lack_of_fit_p is not None and fit.lack_of_fit_p < LACK_OF_FIT_ALPHA:
            out.append(ConstraintModel(
                metric, op, value, None,
                f"lack of fit rejects the model (p={fit.lack_of_fit_p:.3g})",
                n_rows=len(ys)))
            continue
        out.append(ConstraintModel(metric, op, value, fit, "modelled", n_rows=len(ys)))
    return out


def predicted_with_se(fit: Fit, coded: dict) -> tuple[float, float]:
    """``(yhat, se(yhat))`` at ``coded`` under the per-coefficient arithmetic."""
    from orchestrator.optimize.decide import predict

    y = predict(fit, coded)
    var = float(fit.pure_error_var or 0.0) / max(int(fit.n_runs), 1)
    for e in list(fit.effects) + list(fit.quadratic):
        x = math.prod(float(coded[t]) for t in e.terms)
        var += (e.se or 0.0) ** 2 * x * x
    return y, math.sqrt(var)


def per_constraint_delta(models, delta: float) -> float:
    """Bonferroni over the constraints actually modelled."""
    n = sum(1 for m in models if m.modelled)
    return float(delta) / max(n, 1)


def bound(model: ConstraintModel, coded: dict, *, delta: float) -> dict:
    """The two one-sided ``1 - delta`` bounds at ``coded``, and their verdict.

    ``verdict`` is ``infeasible`` when the bound on the violating side lies
    entirely past the threshold (for ``<=``: ``lower > value``), ``feasible``
    when the opposite bound lies entirely inside it, and ``uncertain``
    otherwise -- the only verdict that excludes is ``infeasible``.
    ``delta`` is the per-constraint level (see ``per_constraint_delta``).
    """
    y, se = predicted_with_se(model.fit, coded)
    tcrit = float(student_t.ppf(1.0 - float(delta), max(model.fit.pure_error_df, 1)))
    lo, hi = y - tcrit * se, y + tcrit * se
    v = float(model.value)
    if model.op in ("<", "<="):
        # feasible iff metric (<|<=) v; the violating side is ABOVE v, so the
        # LOWER bound decides exclusion and the UPPER bound decides "feasible".
        infeasible = lo > v if model.op == "<=" else lo >= v
        feasible = hi <= v if model.op == "<=" else hi < v
    else:
        infeasible = hi < v if model.op == ">=" else hi <= v
        feasible = lo >= v if model.op == ">=" else lo > v
    verdict = "infeasible" if infeasible else ("feasible" if feasible else "uncertain")
    return {"predicted": y, "se": se, "lower": lo, "upper": hi, "verdict": verdict}


def confidently_infeasible(models, coded: dict, *, delta: float) -> list[str]:
    """Metrics of every modelled constraint that confidently excludes ``coded``."""
    d = per_constraint_delta(models, delta)
    return [m.metric for m in models
            if m.modelled and bound(m, coded, delta=d)["verdict"] == "infeasible"]


# ── the SUPPORTED-FEASIBLE candidate: a confirm seat the evidence backs ──────
#
# Exclusion above is deliberately one-sided: only a CONFIDENTLY infeasible
# candidate leaves the ranking. That is right for not deleting the optimum, but
# it means nothing guarantees the terminal comparison tests even ONE candidate
# whose feasibility the evidence actually supports. On a constraint-bound
# frontier the ranking prefers higher-predicted candidates of uncertain
# feasibility; observed on two real campaigns, every model-ranked finalist was
# then measured infeasible and a feasible improvement was never tested (a
# deterministic `max_unflushed_writes <= 200`, unmodelled for want of pure
# error: both model-ranked finalists paired a bigger cache with a write cache
# infeasible by construction, while a bigger cache with an already-measured-
# feasible write cache was faster and never seated; and a noisy hit-rate
# constraint whose shortlist tested only the boundary level). The rule below
# names the best-predicted candidate the evidence supports, and confirm
# reserves a seat for it -- one registered row block, no new model call.


def admissible_region(configurations, factors) -> dict:
    """The per-factor span of the measured-ADMISSIBLE configurations.

    ``configurations`` are level dicts the campaign has measured admissible
    (``stage_runner._config_admissible``: a complete row and no infeasible /
    rejected row anywhere). Returns ``{factor_id: span}`` with

      * numeric: ``{"kind": "range", "min": lo, "max": hi}`` over the admissible
        levels. Taken on the LEVELS themselves, which is the same box in the
        factor's own scale whatever that scale is: ``scale: log`` (or any coding)
        is a monotone map, so the min and max of the coded levels are the coded
        min and max. The box is not widened to a grid neighbour or a declared
        range end -- only levels the campaign watched pass count;
      * choice (or any non-numeric level): ``{"kind": "levels", "levels": [...]}``,
        the levels SEEN admissible. A categorical has no "between", so a level
        never measured admissible is outside however its neighbours behaved.

    A factor with no admissible observation is absent, which puts every
    candidate outside the region (no evidence is not support). An empty input
    gives ``{}``.
    """
    numeric = {f.id for f in factors if getattr(f, "type", None) == "numeric"}
    spans: dict = {}
    for f in factors:
        vals = [c[f.id] for c in configurations or () if f.id in c]
        if not vals:
            continue
        if f.id in numeric:
            nums = [v for v in vals
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(float(v))]
            if nums:
                spans[f.id] = {"kind": "range", "min": min(nums), "max": max(nums)}
            continue
        seen: list = []
        for v in vals:
            if v not in seen:
                seen.append(v)
        spans[f.id] = {"kind": "levels", "levels": sorted(seen, key=str)}
    return spans


def in_admissible_region(levels: dict, region: dict) -> bool:
    """Is every level of ``levels`` inside ``region`` (``admissible_region``)?

    Numerics compare with a relative tolerance (levels round-trip through
    JSON, so ``8`` and ``8.0`` are one level). A factor the region does not
    span is outside.
    """
    if not region or not levels:
        return False
    for fid, v in levels.items():
        span = region.get(fid)
        if span is None:
            return False
        if span["kind"] == "range":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return False
            lo, hi = float(span["min"]), float(span["max"])
            tol = 1e-9 * max(1.0, abs(lo), abs(hi))
            if not (lo - tol <= float(v) <= hi + tol):
                return False
        elif v not in span["levels"]:
            return False
    return True


def supported_feasible(candidates, models, *, delta: float, region: dict) -> list:
    """The candidates whose feasibility the EVIDENCE supports, in input order.

    ``models`` holds ONE ``ConstraintModel`` per declared constraint (an
    unmodelled one has ``fit is None``). A candidate qualifies when

      (a) every MODELLED constraint's verdict is confidently ``feasible``: the
          one-sided bound on the SATISFYING side lies inside the threshold (for
          ``<=``: ``upper <= value``), at the same per-constraint delta the
          exclusion uses (``per_constraint_delta``, Bonferroni over the
          modelled constraints) -- the mirror image of exclusion, so
          "excluded", "uncertain" and "supported" partition the modelled space;
      (b) when ANY constraint is unmodelled, the candidate lies inside
          ``region`` (``admissible_region``): every level within the span of
          configurations the campaign has measured admissible.

    (b) IS A CONSERVATIVE INTERPOLATION HEURISTIC, NOT A GUARANTEE. With no
    model there is no bound to be on the right side of, and the only evidence
    is which configurations passed. Staying inside their per-factor box never
    EXTRAPOLATES any single factor past a level the campaign watched pass --
    which is exactly the failure observed (a write cache larger than any
    admissible one) -- and costs nothing to compute. It does not prove
    feasibility: a constraint that couples factors (``A + B <= c``) can fail at
    a box corner no admissible configuration occupies. That risk is bounded by
    what the seat costs -- one candidate measured freshly, struck off by
    ``_finish_confirm`` if a replicate is infeasible, never returned unmeasured.

    Returns ``[(candidate, verdicts)]``; ``verdicts`` has one entry per model:
    the ``bound`` dict (plus metric/op/value/modelled) for a modelled
    constraint, ``{"verdict": "inside_admissible_region"}`` for an unmodelled
    one. An empty list when nothing qualifies.
    """
    models = list(models or ())
    need_region = any(not m.modelled for m in models)
    if need_region and not region:
        return []
    d = per_constraint_delta(models, delta)
    out = []
    for c in candidates:
        if need_region and not in_admissible_region(c.levels, region):
            continue
        verdicts = []
        ok = True
        for m in models:
            head = {"metric": m.metric, "op": m.op, "value": m.value,
                    "modelled": m.modelled}
            if not m.modelled:
                verdicts.append({**head, "verdict": "inside_admissible_region"})
                continue
            b = bound(m, c.coded, delta=d)
            if b["verdict"] != "feasible":
                ok = False
                break
            verdicts.append({**head, **b})
        if ok:
            out.append((c, verdicts))
    return out
