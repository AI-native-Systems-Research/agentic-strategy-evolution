"""WP-D D1: the recombination pool and its acquisition scores (pure functions).

STATISTICS OWNS INFERENCE; DECISION THEORY OWNS ALLOCATION. This module only
answers "where would the next runs buy the most?". It reads a fitted model's
PREDICTIONS and returns a ranked list, with a rationale per candidate. It
certifies nothing, writes nothing and reads no file. Whatever seats a candidate
it ranks (the confirm / gap-fill rounds, P6b) has to measure that candidate on
FRESH replicates, and the claim rests only on those replicates. Selecting on
predictions and claiming on fresh measurements is the same accounting rule
gap-fill registers: Bonferroni over rounds (``policy.FRONT_GAP_ACCOUNTING``).

THE POOL (``recombination_pool``)
---------------------------------
Measured front points (or, single-objective, the measured finalists) often
agree on most knobs and disagree on a few. The pool is the Cartesian product of
the values those points take on the knobs where they DISAGREE. Every other knob
stays at the PREFERRED point's value. Configurations already measured are left
out by default. The pool can hold a combination that no measured point had,
for example A from one point and B from another. That is the point of
recombination: when the front needs both, no single measured point is on it.
The pool's size is the product of the distinct-value counts, and it is computed
BEFORE anything is enumerated (resource rule 4). Above ``POOL_CAP`` the
function declines with ``pool_too_large``; it never truncates silently. The
predicted front and (optional) BO proposals (``bo_proposer``) join the pool
with their ``source`` recorded.

THE PREDICTIVE DISTRIBUTION (stated, not approximated silently)
---------------------------------------------------------------
For each objective the fitted linear model gives ``yhat(x)`` and
``se(x) = s * sqrt(phi(x)' (X'X)^-1 phi(x))``, with ``s^2`` the pure-error
variance on ``nu = pure_error_df`` degrees of freedom
(``constraint_models.predicted_with_se``). That is exact for second-order and
mixed fits; for orthogonal two-level fits it is exact for their columns. The
belief about the TRUE mean response ``f(x)`` is taken as a location-scale
Student t: ``f(x) ~ yhat + se * T_nu``. This is the flat-prior Bayesian
posterior of a linear model's mean response when ``sigma^2`` is estimated
from pure error on ``nu`` df. It assumes the model class holds, which is why
everything here DECLINES unless ``model_adequate is True``. Objectives are
taken as INDEPENDENT (multi-objective). This is an assumption: objectives
measured on the same run usually have correlated noise, and correlated
predictions change EHVI. It is recorded in every result.

THE SCORES
----------
* Single objective, **expected improvement** (Jones, Schonlau & Welch 1998)
  under the t marginal, in closed form:
  ``EI = (m - tau) F_nu(z) + se (nu + z^2)/(nu - 1) f_nu(z)``, with
  ``z = (m - tau)/se`` (finite mean needs ``nu >= 2``). The incumbent ``tau``
  is the largest POSTERIOR MEAN over the measured configurations. This is the
  plug-in incumbent for noisy observations (Picheny et al. 2013), not the
  largest noisy observation.
* Single objective, **knowledge gradient** (Frazier, Powell & Dayanik 2009,
  correlated normal beliefs; Frazier et al. 2008): the expected rise in
  ``max_{x' in D} mu(x')`` from measuring ``x`` with ``r`` replicates. The
  decision set ``D`` is the MEASURED configurations plus ``x`` itself, because
  a Nous claim may rest only on measured configurations (an unmeasured pool
  point is never the answer). KG is computed EXACTLY for that finite ``D``:
  the upper envelope of the lines ``mu(x') + sigma~(x', x) Z`` is integrated
  against the normal density, with ``sigma~(x', x) = Sigma(x', x) /
  sqrt(Sigma(x, x) + s^2 / r)`` and ``Sigma = s^2 phi' (X'X)^-1 phi``. The
  baseline is ``max`` over the measured configurations, so KG includes the
  candidate's own mean gain, and correlation with the incumbents enters
  through ``Sigma(x', x)``.
  Approximations, stated: Gaussian (``s^2`` treated as known) rather than t;
  myopic one-step; and a batch is ranked GREEDILY, so redundancy between two
  seated candidates is ignored. The ranking key is KG per run (``r`` runs per
  seat).
* Multi-objective, **expected hypervolume improvement** (Emmerich, Giannakoglou
  & Naujoks 2006; Emmerich, Deutz & Klinkenberg 2011; Daulton, Balandat &
  Bakshy 2020), in the normalised frame of ``pareto.make_frame`` with the
  reference at the frame's worst point, as ``report.json``'s hypervolume uses.
  With K = 2 it is EXACT: in 2-D the region a new point ``y`` adds is a union
  of strips ``[l_i, u_i] x [h_i, y_2]``, so under independent marginals
  ``EHVI = sum_i E[(min(u_i, Y_1) - l_i)^+] * E[(Y_2 - h_i)^+]``, and each
  factor is a closed-form t partial expectation. With K >= 3 it is a seeded
  Monte Carlo (``MC_SAMPLES`` draws, ``MC_SEED``; common random numbers
  across candidates). The method string records both numbers.
  Per-run cost: EHVI / r. EHVI is a property of the TRUE value, so more
  replicates do not raise it. Dividing by ``r`` only states the cost.

DECLINES ARE NAMED (``DECLINE_REASONS``). Each one is a string that P6b and
``plan-next`` copy verbatim into their artifacts.
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field

from scipy.stats import norm
from scipy.stats import t as student_t

#: Largest pool enumerated. Above it the allocator declines (never truncates).
POOL_CAP = 4096
#: Monte Carlo EHVI (K >= 3) draws and seed. Fixed constants, like
#: ``pareto.HV_MC_SEED``: the same inputs give the same ranking.
MC_SAMPLES = 512
MC_SEED = 20261017

DECLINE_REASONS = {
    "model_inadequate": "the epoch's model adequacy verdict is False: the "
                        "predictive distribution rests on a model the data rejected",
    "model_adequacy_unknown": "the epoch's model adequacy verdict is not True "
                              "(unknown or absent): allocation spends only on an "
                              "adequate model (WP-B)",
    "no_fit": "no fitted model for an objective",
    "no_pure_error": "an objective's fit has no pure-error variance, so no "
                     "predictive uncertainty exists",
    "predictive_df_too_small": "pure-error df < 2: the t predictive has no finite "
                               "mean, so expected improvement is undefined",
    "no_measured_incumbent": "single objective: no measured configuration is "
                             "predictable, so there is no incumbent to improve on",
    "empty_pool": "no candidate survived (every pool point was measured, "
                  "unpredictable, or the inputs named none)",
    "pool_too_large": f"the recombination product exceeds POOL_CAP={POOL_CAP}",
}


@dataclass
class Allocation:
    declined: str | None
    detail: str = ""
    method: dict = field(default_factory=dict)
    ranked: list = field(default_factory=list)
    unscored: list = field(default_factory=list)
    pool_size: int = 0

    def as_dict(self) -> dict:
        return {"declined": self.declined, "detail": self.detail,
                "method": self.method, "ranked": self.ranked,
                "unscored": self.unscored, "pool_size": self.pool_size}


def _decline(reason: str, detail: str = "", **kw) -> Allocation:
    return Allocation(declined=reason, detail=detail or DECLINE_REASONS[reason], **kw)


def _key(levels: dict) -> tuple:
    return tuple(sorted((k, repr(v)) for k, v in levels.items()))


# ── the pool ─────────────────────────────────────────────────────────────────


def disagreeing_knobs(points: list[dict]) -> dict:
    """``{knob: [values...]}`` for the knobs the points take more than one value
    on, the values in first-seen order (deterministic)."""
    knobs = sorted({k for p in points for k in p})
    out = {}
    for k in knobs:
        vals = []
        for p in points:
            if k in p and all(p[k] != v for v in vals):
                vals.append(p[k])
        if len(vals) > 1:
            out[k] = vals
    return out


def pool_size(points: list[dict]) -> int:
    """The recombination product's size, computed without enumerating it."""
    d = disagreeing_knobs(points)
    return math.prod(len(v) for v in d.values()) if d else (1 if points else 0)


def recombination_pool(points: list[dict], preferred: dict, *,
                       measured: list[dict] = (), include_measured: bool = False,
                       cap: int = POOL_CAP) -> tuple[list[dict], dict]:
    """``(pool, record)``. Each pool entry is ``{levels, source}``.

    ``record`` names the disagreeing knobs and the product size. If the size
    exceeds ``cap``, ``pool`` is empty and ``record["declined"]`` is
    ``pool_too_large``. The size is computed before anything is enumerated.
    """
    d = disagreeing_knobs(points)
    size = math.prod(len(v) for v in d.values()) if d else 0
    record = {"disagreeing_knobs": {k: list(v) for k, v in d.items()},
              "product_size": size, "n_points": len(points)}
    if size > cap:
        record["declined"] = "pool_too_large"
        return [], record
    seen = {_key(m) for m in measured} if not include_measured else set()
    out, keys = [], set()
    names = list(d)
    for combo in itertools.product(*(d[k] for k in names)):
        lv = {**dict(preferred), **dict(zip(names, combo))}
        k = _key(lv)
        if k in keys or k in seen:
            continue
        keys.add(k)
        out.append({"levels": lv, "source": "front_recombination"})
    record["kept"] = len(out)
    return out, record


def merge_pool(*parts) -> list[dict]:
    """Union of pool parts in order, de-duplicated by levels. The first
    source wins, and later sources are recorded under ``also_from``."""
    out, at = [], {}
    for part in parts:
        for e in part or ():
            k = _key(e["levels"])
            if k in at:
                out[at[k]].setdefault("also_from", []).append(e.get("source"))
                continue
            at[k] = len(out)
            out.append(dict(e))
    return out


# ── prediction ───────────────────────────────────────────────────────────────


def coded_of(levels: dict, *, fitted_ids, factors, held_fixed: dict,
             max_coded: float = 1.0) -> dict:
    """The fit's coded coordinates of ``levels``. Raises ``ValueError`` when
    the model cannot predict them: a fitted knob is missing or off its coding,
    or a held knob is at a value other than the held one. A numeric value
    whose coded coordinate exceeds ``max_coded`` in magnitude is refused as
    an extrapolation. The default 1.0 is the fitted range; only the planner's
    widen move passes more, and it records that its score is extrapolated."""
    from orchestrator.optimize.factors import code_vector, model_columns

    by_id = {f.id: f for f in factors}
    for k, v in (held_fixed or {}).items():
        if k in levels and levels[k] != v:
            raise ValueError(f"varies held factor {k} ({levels[k]!r} != held {v!r})")
    coded = {}
    for fid in fitted_ids:
        if fid not in levels:
            raise ValueError(f"fitted factor {fid} missing")
        f = by_id[fid]
        v = levels[fid]
        if f.type == "choice":
            if v not in f.levels:
                raise ValueError(f"{fid}={v!r} is not a declared level")
        else:
            cv = code_vector(f, v)
            if any(abs(x) > float(max_coded) + 1e-9 for x in cv):
                raise ValueError(f"{fid}={v!r} lies outside the fitted range (coded "
                                 f"{cv[0]:+.3f}, bound {max_coded:g}): an extrapolation")
        coded.update(zip(model_columns(f), code_vector(f, levels[fid])))
    return coded


def _phi(fit, coded: dict) -> list[float]:
    """The model row in the order of ``fit.effects + fit.quadratic``, with the
    intercept first."""
    return [1.0] + [math.prod(float(coded[t]) for t in e.terms)
                    for e in list(fit.effects) + list(fit.quadratic)]


def _cov_row(fit, coded: dict):
    """A callable ``c -> Cov(yhat(x), yhat(c))`` for fixed ``x = coded``.

    Uses the exact ``s^2 (X'X)^-1`` when the fit keeps it, else the diagonal
    the orthogonal two-level fit implies (intercept ``s^2/n``, term ``se_j^2``).
    This is the same arithmetic ``predicted_with_se`` uses.
    """
    s2 = float(fit.pure_error_var or 0.0)
    if fit.covariance is not None:
        tt = fit.term_terms

        def row(c):
            return [1.0] + [math.prod(float(c[t]) for t in ts) for ts in tt[1:]]
        a = row(coded)
        C = fit.covariance
        ca = [sum(C[i][j] * a[j] for j in range(len(a))) for i in range(len(a))]
        return lambda c: s2 * sum(u * v for u, v in zip(row(c), ca))
    w = [s2 / max(int(fit.n_runs), 1)] + [(e.se or 0.0) ** 2
                                          for e in list(fit.effects) + list(fit.quadratic)]
    a = _phi(fit, coded)
    wa = [x * y for x, y in zip(w, a)]
    return lambda c: sum(u * v for u, v in zip(_phi(fit, c), wa))


def _t_partial(m: float, s: float, h: float, nu: float) -> float:
    """``E[(Y - h)^+]`` for ``Y = m + s T_nu`` (``s > 0``, ``nu > 1``); with
    ``nu = inf`` it is the Gaussian ``s (z Phi(z) + phi(z))``."""
    z = (m - h) / s
    if math.isinf(nu):
        return s * (z * norm.cdf(z) + norm.pdf(z))
    return s * (z * student_t.cdf(z, nu) + (nu + z * z) / (nu - 1.0) * student_t.pdf(z, nu))


def expected_improvement(m: float, s: float, tau: float, nu: float) -> float:
    """EI over ``tau`` under ``m + s T_nu`` (larger is better)."""
    if not s > 0.0:
        return max(m - tau, 0.0)
    return _t_partial(m, s, tau, nu)


def _kg_lines(a: list[float], b: list[float]) -> float:
    """``E[max_i (a_i + b_i Z)] - max_i a_i``, Z ~ N(0,1), computed exactly
    (Frazier, Powell & Dayanik 2009, Algorithm 1: the upper envelope)."""
    base = max(a)
    lines = sorted(zip(b, a))
    dedup = []
    for bi, ai in lines:
        if dedup and abs(dedup[-1][0] - bi) <= 1e-15:
            if ai > dedup[-1][1]:
                dedup[-1] = (bi, ai)
            continue
        dedup.append((bi, ai))
    hull: list[tuple[float, float]] = []
    cuts: list[float] = []

    def x_of(l1, l2):
        return (l1[1] - l2[1]) / (l2[0] - l1[0])

    for ln in dedup:
        while hull:
            c = x_of(hull[-1], ln)
            if cuts and c <= cuts[-1]:
                hull.pop()
                cuts.pop()
                continue
            break
        if hull:
            cuts.append(x_of(hull[-1], ln))
        hull.append(ln)
    if len(hull) == 1:
        return 0.0
    edges = [-math.inf] + cuts + [math.inf]
    e = 0.0
    for (bj, aj), lo, hi in zip(hull, edges[:-1], edges[1:]):
        e += aj * (norm.cdf(hi) - norm.cdf(lo)) + bj * (norm.pdf(lo) - norm.pdf(hi))
    return max(e - base, 0.0)


# ── the scorer ───────────────────────────────────────────────────────────────


def _sign(direction: str) -> float:
    return -1.0 if direction == "minimize" else 1.0


def _check_models(fits: dict, model_adequate) -> Allocation | None:
    if model_adequate is False:
        return _decline("model_inadequate")
    if model_adequate is not True:
        return _decline("model_adequacy_unknown",
                        f"{DECLINE_REASONS['model_adequacy_unknown']} (got {model_adequate!r})")
    for m, f in fits.items():
        if f is None:
            return _decline("no_fit", f"no fitted model for objective {m!r}")
        if not f.pure_error_var or f.pure_error_df < 1:
            return _decline("no_pure_error", f"objective {m!r}: {DECLINE_REASONS['no_pure_error']}")
        if f.pure_error_df < 2:
            return _decline("predictive_df_too_small",
                            f"objective {m!r}: pure-error df={f.pure_error_df} < 2")
    return None


def score(pool: list[dict], *, fits: dict, objectives: list[dict], factors,
          fitted_ids, held_fixed: dict, measured: list[dict], model_adequate,
          replicates: int = 3, eps: dict | None = None,
          max_coded: float = 1.0, frame=None) -> Allocation:
    """Rank ``pool`` (entries ``{levels, source}``) by the acquisition score.

    ``fits``: ``{metric: Fit}``. ``objectives``: ``[{metric, direction}]``,
    one entry for a single objective. ``measured``: the measured configurations
    as ``{levels, mean: {metric: value}}``. They are the incumbent set: EI's
    incumbent is the best posterior mean over them; KG's decision set adds them
    to the pool; for EHVI their predicted values form the current front.
    Using predicted rather than measured values keeps EHVI and the candidate
    on one scale. ``mean`` sets the frame only, and a caller comparing several
    pools passes one fixed ``frame`` (``pareto.Frame``) so that their EHVIs
    are in the same units. Returns an ``Allocation``.
    """
    bad = _check_models(fits, model_adequate)
    if bad is not None:
        return bad
    from orchestrator.optimize.constraint_models import predicted_with_se

    r = max(1, int(replicates))
    objs = list(objectives)
    unscored, cands = [], []
    for e in pool:
        try:
            c = coded_of(e["levels"], fitted_ids=fitted_ids, factors=factors,
                         held_fixed=held_fixed, max_coded=max_coded)
        except (ValueError, KeyError) as exc:
            unscored.append({"levels": e["levels"], "source": e.get("source"),
                             "reason": f"unpredictable: {exc}"})
            continue
        cands.append((e, c))
    inc = []
    for mpt in measured or ():
        try:
            inc.append((mpt, coded_of(mpt["levels"], fitted_ids=fitted_ids,
                                      factors=factors, held_fixed=held_fixed)))
        except (ValueError, KeyError):
            continue
    if not cands:
        return _decline("empty_pool", unscored=unscored, pool_size=len(pool))

    def pred(metric, coded):
        y, s = predicted_with_se(fits[metric], coded)
        return y, s

    assumptions = [
        "f(x) ~ yhat(x) + se(x) T_nu per objective, nu = pure-error df: the "
        "flat-prior posterior of the fitted linear model's mean response; valid "
        "only if the model class holds (hence the model_adequate gate)",
        "selection is on predictions; any claim about a seated candidate rests "
        "on its fresh replicates only",
    ]
    if len(objs) == 1:
        o = objs[0]
        sg = _sign(o["direction"])
        fit = fits[o["metric"]]
        nu = float(fit.pure_error_df)
        s2 = float(fit.pure_error_var)
        Dm = [c for _, c in inc]
        mu_m = [sg * pred(o["metric"], c)[0] for c in Dm]
        if not mu_m:
            return _decline("no_measured_incumbent", unscored=unscored, pool_size=len(pool))
        tau = max(mu_m)
        ranked = []
        for e, c in cands:
            y, s = pred(o["metric"], c)
            m = sg * y
            ei = expected_improvement(m, s, tau, nu)
            cov = _cov_row(fit, c)
            var_x = max(cov(c), 0.0)
            denom = math.sqrt(var_x + s2 / r)
            # The decision after measuring x is made among the MEASURED
            # configurations plus x: Nous claims only on measured points.
            a = mu_m + [m]
            b = ([sg * sg * cov(d) / denom for d in Dm] + [var_x / denom]
                 if denom > 0 else [0.0] * len(a))
            kg = _kg_lines(a, b) + max(a) - tau
            ranked.append({
                "levels": e["levels"], "source": e.get("source"),
                **({"also_from": e["also_from"]} if e.get("also_from") else {}),
                "predicted": {o["metric"]: y}, "se": {o["metric"]: s},
                "ei": ei, "kg": kg, "kg_per_run": kg / r, "score": kg / r,
                "rationale": (f"{e.get('source')}: predicted {o['metric']}={y:.6g} "
                              f"(se {s:.3g}); EI over incumbent "
                              f"{sg * tau:.6g} = {ei:.3g}; "
                              f"KG of {r} replicate(s) = {kg:.3g} ({kg / r:.3g}/run)"),
            })
        ranked.sort(key=lambda d: (-d["score"], -d["ei"], _key(d["levels"])))
        method = {
            "kind": "single_objective",
            "score": "knowledge_gradient_per_run",
            "also_reported": "expected_improvement",
            "utility": ("expected increase in the best posterior mean over the "
                        "configurations a claim may rest on (the measured ones, plus x "
                        f"once measured) from measuring x with r={r} replicates, per "
                        "run: the knowledge gradient (Frazier, Powell & Dayanik 2009) "
                        "with the decision restricted to measured configurations"),
            "decision_set": f"measured configurations ({len(inc)}) + the candidate itself",
            "incumbent": {"value": sg * tau,
                          "rule": "max posterior mean over measured configurations "
                                  "(plug-in, Picheny et al. 2013)"},
            "approximations": [
                "KG under a Gaussian belief with s^2 treated as known (EI uses the t)",
                "myopic (one-step) KG; a batch is ranked greedily, ignoring redundancy "
                "between seats",
            ],
            "replicates_per_seat": r,
            "nu": nu,
        }
        return Allocation(None, "", {**method, "assumptions": assumptions}, ranked,
                          unscored, len(pool))

    # ── multi-objective: EHVI in the normalised frame ────────────────────────
    from orchestrator.optimize import pareto

    pobjs = [pareto.Objective(o["metric"], o["direction"], {}) for o in objs]
    K = len(pobjs)
    P_pred = []
    for _, c in inc:
        P_pred.append({o.metric: pred(o.metric, c)[0] for o in pobjs})
    cand_pred = [({o.metric: pred(o.metric, c) for o in pobjs}) for _, c in cands]
    value_rows = ([dict(m.get("mean") or {}) for m, _ in inc] + P_pred
                  + [{k: v[0] for k, v in cp.items()} for cp in cand_pred])
    if frame is None:
        frame = pareto.make_frame(pobjs, value_rows, eps or {})
    Pz = [frame.z(v) for v in P_pred]
    Pz = [p for p in Pz if all(math.isfinite(x) for x in p)]
    front = [Pz[i] for i in pareto.nondominated_indices(Pz)] if Pz else []
    nus = [float(fits[o.metric].pure_error_df) for o in pobjs]
    if K == 2:
        meth = "exact_2d_strip_decomposition"
    else:
        meth = f"monte_carlo(n={MC_SAMPLES},seed={MC_SEED},common_random_numbers)"
        rng = random.Random(MC_SEED)
        draws = []
        for _ in range(MC_SAMPLES):
            row = []
            for nu in nus:
                zt = rng.gauss(0.0, 1.0)
                row.append(zt / math.sqrt(rng.gammavariate(nu / 2.0, 2.0) / nu))
            draws.append(row)
        hv0 = pareto.hypervolume(front, [0.0] * K)[0]
    ranked = []
    for (e, _c), cp in zip(cands, cand_pred):
        mz, sz = [], []
        for o in pobjs:
            y, s = cp[o.metric]
            mz.append(pareto.sign(o.direction) * (y - frame.worst[o.metric])
                      / frame.range[o.metric])
            sz.append(s / frame.range[o.metric])
        if K == 2:
            ehvi = ehvi_2d(mz, sz, nus, front)
        else:
            tot = 0.0
            for row in draws:
                y = [m + s * t for m, s, t in zip(mz, sz, row)]
                tot += pareto.hypervolume(front + [y], [0.0] * K)[0] - hv0
            ehvi = tot / MC_SAMPLES
        ranked.append({
            "levels": e["levels"], "source": e.get("source"),
            **({"also_from": e["also_from"]} if e.get("also_from") else {}),
            "predicted": {o.metric: cp[o.metric][0] for o in pobjs},
            "se": {o.metric: cp[o.metric][1] for o in pobjs},
            "ehvi": ehvi, "ehvi_per_run": ehvi / r, "score": ehvi / r,
            "rationale": (f"{e.get('source')}: predicted "
                          + ", ".join(f"{o.metric}={cp[o.metric][0]:.6g}" for o in pobjs)
                          + f"; EHVI over the {len(front)}-point predicted front = {ehvi:.3g} "
                            f"(normalised units, {meth})"),
        })
    ranked.sort(key=lambda d: (-d["score"], _key(d["levels"])))
    method = {
        "kind": "multi_objective",
        "score": "expected_hypervolume_improvement_per_run",
        "utility": ("expected hypervolume added to the predicted front of the "
                    "measured configurations, in pareto.make_frame's normalised "
                    "frame with the reference at its worst point, per run"),
        "ehvi_method": meth,
        "references": ["Emmerich, Giannakoglou & Naujoks 2006",
                       "Emmerich, Deutz & Klinkenberg 2011 (exact 2-D)",
                       "Daulton, Balandat & Bakshy 2020"],
        "frame": frame.as_dict(),
        "front_points": len(front),
        "approximations": [
            "objectives independent (correlated noise across objectives is ignored)",
            "the current front is the PREDICTED values at measured configurations",
        ] + (["Monte Carlo EHVI"] if K > 2 else []),
        "replicates_per_seat": r,
    }
    return Allocation(None, "", {**method, "assumptions": assumptions}, ranked,
                      unscored, len(pool))


def ehvi_2d(m: list[float], s: list[float], nu: list[float], front: list[list[float]]) -> float:
    """Exact 2-D EHVI (maximisation, reference at the origin) for independent
    location-scale t marginals ``Y_k = m_k + s_k T_{nu_k}``.

    With the front sorted by objective 1 ascending (so objective 2 descends),
    ``H(z) = max{p_2 : p_1 >= z}`` is a step function, and the added area is
    ``int_0^{Y_1} (Y_2 - H(z))^+ dz``. Over the strips ``(l_i, u_i]`` on which
    ``H = h_i`` this is ``sum_i (min(u_i, Y_1) - l_i)^+ (Y_2 - h_i)^+``, and
    under independence each term's expectation factorises.
    """
    pts = sorted((max(p[0], 0.0), max(p[1], 0.0)) for p in front)
    nd = []
    for p in sorted(pts, key=lambda q: (-q[0], -q[1])):
        if not nd or p[1] > nd[-1][1]:
            nd.append(p)
    nd.sort()
    strips = []
    lo = 0.0
    for a1, b2 in nd:
        if a1 > lo:
            strips.append((lo, a1, b2))
        lo = max(lo, a1)
    strips.append((lo, math.inf, 0.0))

    def part(k, h):
        if not s[k] > 0.0:
            return max(m[k] - h, 0.0)
        return _t_partial(m[k], s[k], h, nu[k])

    tot = 0.0
    for l, u, h in strips:
        e1 = part(0, l) - (0.0 if math.isinf(u) else part(0, u))
        tot += max(e1, 0.0) * part(1, h)
    return tot


def allocate(*, front_points: list[dict], preferred: dict, fits: dict,
             objectives: list[dict], factors, fitted_ids, held_fixed: dict,
             measured: list[dict], model_adequate, replicates: int = 3,
             predicted_front: list[dict] = (), proposals: list[dict] = (),
             eps: dict | None = None, cap: int = POOL_CAP) -> Allocation:
    """Build the pool and score it. The model gate is checked FIRST, so an
    inadequate model never even enumerates."""
    bad = _check_models(fits, model_adequate)
    if bad is not None:
        return bad
    rec_pool, rec = recombination_pool(front_points, preferred,
                                       measured=[m["levels"] for m in measured], cap=cap)
    if rec.get("declined"):
        return _decline("pool_too_large",
                        f"{DECLINE_REASONS['pool_too_large']} (product {rec['product_size']})",
                        method={"pool": rec})
    seen = {_key(m["levels"]) for m in measured}
    extra = [{"levels": dict(p["levels"]), "source": p.get("source") or "predicted_front"}
             for p in predicted_front or () if _key(p["levels"]) not in seen]
    bo = [{"levels": dict(p["levels"]), "source": p.get("source") or "bo_proposal",
           **({"provenance": p["provenance"]} if p.get("provenance") else {})}
          for p in proposals or () if _key(p["levels"]) not in seen]
    pool = merge_pool(rec_pool, extra, bo)
    out = score(pool, fits=fits, objectives=objectives, factors=factors,
                fitted_ids=fitted_ids, held_fixed=held_fixed, measured=measured,
                model_adequate=model_adequate, replicates=replicates, eps=eps)
    out.method = {**out.method, "pool": rec,
                  "pool_sources": {"front_recombination": len(rec_pool),
                                   "predicted_front": len(extra), "bo_proposal": len(bo)}}
    return out
