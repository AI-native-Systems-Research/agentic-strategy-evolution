"""Pre-launch DESIGN PREVIEW for ``nous validate campaign --liveness``.

Zero tokens, zero extra runs: everything here is arithmetic over the campaign
and what ``--liveness`` just MEASURED (the baseline's noise sd and mean, and each
run's wall clock). It answers the questions an author otherwise learns only by
launching:

  (a) how many runs each stage will register — from the SAME design builders
      the stages use (``stage_runner._build_design``, ``compile_policy``), never
      re-derived, so the preview cannot disagree with the epoch;
  (b) the wall clock that implies, against ``max_wall_clock_hours``;
  (c) the screen's minimum detectable effect from the measured noise, against
      ``epsilon`` resolved exactly as the certificate resolves it (guide §7.9
      check 14);
  (d) whether each numeric factor's levels bracket the base point the
      liveness sweep varied around.

A PREVIEW, not a verdict: nothing here fails validation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageRuns:
    stage: str
    runs: int            # runs if the stage executes (one round for confirm)
    max_runs: int        # upper bound (all confirm rounds)
    conditional: bool    # True when a registered branch decides whether it runs
    note: str = ""


@dataclass(frozen=True)
class ObjectiveMDE:
    """One objective's screen MDE against its own indifference width."""
    metric: str
    direction: str
    noise_sd: float
    mean: float
    mde: float
    epsilon: float | None
    epsilon_spec: dict


@dataclass
class DesignPreview:
    stages: list[StageRuns] = field(default_factory=list)
    guaranteed_runs: int = 0
    max_runs: int = 0
    budget_max_runs: int | None = None
    per_run_sec: float | None = None
    slowest_run_sec: float | None = None
    spending_width: int = 1
    confirm_width: int = 1
    expected_hours: float | None = None
    worst_hours: float | None = None
    wall_clock_cap_hours: float | None = None
    screen_corners: int = 0
    pure_error_df: int = 0
    t_crit: float | None = None
    noise_sd: float | None = None
    mde: float | None = None
    epsilon: float | None = None
    epsilon_spec: dict = field(default_factory=dict)
    brackets: list[tuple[str, str]] = field(default_factory=list)
    #: Multi-objective only: one entry per ``response.objectives`` metric.
    per_objective: list[ObjectiveMDE] = field(default_factory=list)
    #: Metrics ``response.constraints`` bounds (not objectives): named so the
    #: preview can say they need no MDE.
    constraint_metrics: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def screen_mde(n_corners: int, df: int, sd: float) -> tuple[float, float | None]:
    """``(MDE, t)``: ``t(0.975, df) * 2 * sd / sqrt(n_corners)``.

    The screen estimates a main effect as mean(+) - mean(-) over its corners,
    SE = 2 sd / sqrt(c), tested with pure-error df from its centre points.
    ``df < 1`` means no pure-error estimate exists: the MDE is infinite.
    """
    if df < 1 or n_corners < 1:
        return math.inf, None
    from scipy.stats import t as student_t

    t = float(student_t.ppf(0.975, df))
    return t * 2.0 * float(sd) / math.sqrt(n_corners), t


def _ceil_div(a: int, b: int) -> int:
    return -(-int(a) // max(1, int(b)))


def build_preview(
    campaign: dict, *, noise_sd: float | None, mean: float | None,
    run_secs: list[float] | None, baseline: dict | None = None,
    objectives: dict | None = None,
) -> DesignPreview:
    """``objectives``: ``{metric: {"noise_sd", "mean"}}`` measured per objective
    (multi-objective campaigns); each gets its own MDE vs its own epsilon."""
    from orchestrator.optimize import certificate
    from orchestrator.optimize.design import alias_pairs
    from orchestrator.optimize.factors import parse_factors
    from orchestrator.optimize.policy import compile_policy, pre_epoch_stages
    from orchestrator.optimize.stage import Stage
    from orchestrator.optimize.stage_runner import (
        _baseline_replicates,
        _build_design,
        resolve_max_parallel,
    )

    opt = campaign.get("optimization") or {}
    factors = parse_factors(opt["factors"])
    design_cfg = opt.get("design") or {}
    pol = compile_policy(campaign)
    states = pol.get("states") or {}
    pv = DesignPreview()

    if "build" in pre_epoch_stages(campaign):
        n = _baseline_replicates(campaign)
        pv.stages.append(StageRuns(
            "build oracle", 2 * n, 2 * n, False,
            f"{n} baseline run(s) before and after build",
        ))

    screen = _build_design(factors, design_cfg, Stage.SCREEN.value)
    n_centre = sum(1 for p in screen.points if p.role == "center")
    pv.screen_corners = len(screen.corners)
    pv.pure_error_df = max(0, n_centre - 1)
    from orchestrator.optimize.design import (
        _counting_bound_runs,
        _smallest_known_runs,
        min_runs_for,
    )

    k = len(screen.factor_ids)
    if screen.kind == "fractional":
        res = int(screen.resolution or 0)
        known = _smallest_known_runs(k, res)
        floor = _counting_bound_runs(k, res)
        roman = {3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}.get(res, str(res))
        # Two different numbers, named as such: the smallest design KNOWN to
        # exist (a catalogue / a construction that attains it), and the
        # counting bound (a theoretical floor no design need attain).
        if known is None:
            versus = ("no catalogue bound for resolution VI+"
                      if res >= 6 else "past the resolution-V catalogue (65 factors)")
            versus += f"; the counting bound (a theoretical floor) is {floor}"
        elif pv.screen_corners <= known:
            versus = ("the smallest regular design (it meets the counting bound)"
                      if res <= 4 else "the smallest known")
        else:
            versus = (f"smallest known is {known} (the best known construction; "
                      f"counting bound {floor})")
        shape = (f"resolution-{roman} "
                 f"fraction 2^({k}-{len(screen.generators)}) of {2 ** k} -- " + versus)
        # The cost of the neighbouring resolutions, so the author can trade
        # aliasing against runs knowingly: a higher resolution at the SAME
        # cost is free, and a screen-first IV is usually far cheaper than V.
        if res < 5 and min_runs_for(k, res + 1) == pv.screen_corners:
            shape += f"; resolution {({3: 'IV', 4: 'V'})[res]} costs the same here -- use it"
        elif res >= 5 and min_runs_for(k, 4) < pv.screen_corners:
            shape += (f"; a resolution-IV screen would take {min_runs_for(k, 4)} "
                      f"(main effects clear, 2fi aliased in chains)")
    else:
        shape = "the full factorial, already the smallest design of this resolution"
    pv.stages.append(StageRuns(
        "screen", len(screen.points), len(screen.points), False,
        f"{pv.screen_corners} corners ({shape}) + {n_centre} centre point(s)",
    ))

    if "foldover" in states:
        if alias_pairs(screen):
            fold = len(_build_design(
                factors, design_cfg, Stage.FOLDOVER.value, fold_on=None,
            ).points)
            pv.stages.append(StageRuns(
                "foldover", fold, fold, True,
                "only if an aliased pair is consequential",
            ))
        else:
            pv.stages.append(StageRuns(
                "foldover", 0, 0, True,
                "cannot fire: the screen aliases no two-factor interaction",
            ))

    if "refine" in states:
        ccd = len(_build_design(factors, design_cfg, Stage.REFINE.value).points)
        pv.stages.append(StageRuns(
            "refine", ccd, ccd, True,
            "central composite over refinable factors; runs if one survives "
            "the screen OR the screen's centre points show curvature",
        ))

    if "confirm" in states:
        d = states["confirm"]["design"]
        per_round = int(d["shortlist_size"]) * int(d["replicates"])
        rounds = int(d["max_rounds"])
        pv.stages.append(StageRuns(
            "confirm", per_round, per_round * rounds, False,
            f"{d['shortlist_size']} finalist(s) x {d['replicates']} "
            f"replicate(s) per round, up to {rounds} round(s)",
        ))

    pv.guaranteed_runs = sum(s.runs for s in pv.stages if not s.conditional)
    pv.max_runs = sum(s.max_runs for s in pv.stages)
    budget = design_cfg.get("max_runs")
    pv.budget_max_runs = int(budget) if isinstance(budget, int) else None
    if pv.budget_max_runs is not None and pv.guaranteed_runs > pv.budget_max_runs:
        pv.warnings.append(
            f"design.max_runs={pv.budget_max_runs} is below the "
            f"{pv.guaranteed_runs} run(s) the screen + first confirm round "
            f"register: the epoch will run out of budget mid-design.",
        )

    # (b) wall clock.
    pv.spending_width = resolve_max_parallel(opt, stage_name=Stage.SCREEN.value)
    pv.confirm_width = resolve_max_parallel(opt, stage_name=Stage.CONFIRM.value)
    secs = [float(s) for s in (run_secs or []) if s is not None]
    if secs:
        pv.per_run_sec = sum(secs) / len(secs)
        pv.slowest_run_sec = max(secs)

        def _hours(per: float, use_max: bool) -> float:
            total = 0.0
            for s in pv.stages:
                n = s.max_runs if use_max else (0 if s.conditional else s.runs)
                if s.stage == "confirm" and n:
                    d = states["confirm"]["design"]
                    blocks = n // max(1, int(d["shortlist_size"]))
                    total += blocks * _ceil_div(
                        int(d["shortlist_size"]), pv.confirm_width) * per
                else:
                    total += _ceil_div(n, pv.spending_width) * per
            return total / 3600.0

        pv.expected_hours = _hours(pv.per_run_sec, False)
        pv.worst_hours = _hours(pv.slowest_run_sec, True)
        cap = opt.get("max_wall_clock_hours")
        if isinstance(cap, (int, float)) and not isinstance(cap, bool):
            pv.wall_clock_cap_hours = float(cap)
            if pv.worst_hours > pv.wall_clock_cap_hours:
                pv.warnings.append(
                    f"the worst case ({pv.worst_hours:.2f} h: every conditional "
                    f"stage and confirm round at the slowest measured run) "
                    f"exceeds max_wall_clock_hours={cap}; the campaign may halt "
                    f"between iterations and report on a partial design.",
                )

    # (c) MDE vs epsilon -- per objective when the campaign declares several.
    from orchestrator.optimize import objectives as _obj

    resp = opt.get("response") or {}
    obj_metrics = set(_obj.objective_metrics(opt))
    for c in resp.get("constraints") or []:
        cm = (c.get("metric") or c.get("observable")) if isinstance(c, dict) else None
        if cm and cm not in obj_metrics and cm not in pv.constraint_metrics:
            pv.constraint_metrics.append(str(cm))
    if _obj.is_multi_objective(opt):
        n_df = pv.pure_error_df
        seeded = bool((opt.get("workload") or {}).get("seed_env"))
        for o in _obj.declared_objectives(opt):
            m = o["metric"]
            got = (objectives or {}).get(m) or {}
            if got.get("noise_sd") is None or got.get("mean") is None:
                continue
            sd, mu = float(got["noise_sd"]), float(got["mean"])
            spec = _obj.epsilon_spec_for(opt, m)
            eps = certificate.resolve_epsilon(spec, mu)
            mde, t = screen_mde(pv.screen_corners, n_df, sd)
            pv.t_crit = t
            pv.per_objective.append(ObjectiveMDE(
                m, o["direction"], sd, mu, mde, eps, spec))
            if eps < mde:
                remedies = ["add confirm replicates"]
                if not seeded:
                    remedies.append("declare workload.seed_env (pairs confirm)")
                remedies.append("add centre points (raises the screen's df)")
                remedies.append(f"widen policy.epsilon.{m}")
                pv.warnings.append(
                    f"objective {m}: epsilon ({eps:.6g}) is below the screen's "
                    f"minimum detectable effect ({_fmt(mde)}): dominance on {m} "
                    f"is unresolvable from the screen; the front's statuses on "
                    f"it will rest on confirm's replicates — "
                    + " / ".join(remedies) + ".",
                )
    pv.epsilon_spec = dict((pol.get("objective") or {}).get("epsilon") or {})
    if mean is not None and not pv.per_objective:
        pv.epsilon = certificate.resolve_epsilon(pv.epsilon_spec, mean)
    if noise_sd is not None and not pv.per_objective:
        pv.noise_sd = float(noise_sd)
        pv.mde, pv.t_crit = screen_mde(
            pv.screen_corners, pv.pure_error_df, pv.noise_sd,
        )
        if pv.epsilon is not None and pv.epsilon < pv.mde:
            seeded = bool((opt.get("workload") or {}).get("seed_env"))
            remedies = ["add confirm replicates"]
            if not seeded:
                remedies.append("declare workload.seed_env (pairs confirm)")
            remedies.append("add centre points (raises the screen's df)")
            pv.warnings.append(
                f"epsilon ({pv.epsilon:.6g}) is below the screen's minimum "
                f"detectable effect ({_fmt(pv.mde)}): epsilon is unreachable "
                f"from the screen; certification will rest on confirm's paired "
                f"replicates — " + " / ".join(remedies) + ".",
            )

    # (d) do numeric levels bracket the base point?
    base = baseline if baseline is not None else (opt.get("known_valid_baseline") or {})
    for f in factors:
        if getattr(f, "type", None) != "numeric" or f.id not in base:
            continue
        try:
            lv = sorted(float(x) for x in f.levels)
            b = float(base[f.id])
        except (TypeError, ValueError):
            continue
        if lv[0] < b < lv[-1]:
            verdict = f"brackets base {base[f.id]} ({lv[0]:g} < base < {lv[-1]:g})"
        elif b in (lv[0], lv[-1]):
            verdict = (f"base {base[f.id]} sits AT the edge of [{lv[0]:g}, "
                       f"{lv[-1]:g}]: effects are probed on one side only")
        else:
            verdict = (f"base {base[f.id]} is OUTSIDE [{lv[0]:g}, {lv[-1]:g}]")
            pv.warnings.append(
                f"factor {f.id}: known_valid_baseline {base[f.id]} lies outside "
                f"its declared levels.",
            )
        pv.brackets.append((f.id, verdict))
    return pv


def _fmt(x: float | None) -> str:
    if x is None:
        return "n/a"
    if math.isinf(x):
        return "inf (no pure-error df)"
    return f"{x:.6g}"


def _dur(hours: float) -> str:
    return f"{hours:.2f} h" if hours >= 1 else f"{hours * 60:.1f} min"


def format_preview(pv: DesignPreview) -> list[str]:
    out = ["  DESIGN PREVIEW (computed from what --liveness just measured; zero "
           "tokens, nothing is run — a preview, not a verdict)"]
    out.append("    pre-registered runs per stage:")
    for s in pv.stages:
        cond = " (conditional)" if s.conditional else ""
        n = f"{s.runs}" if s.runs == s.max_runs else f"{s.runs}..{s.max_runs}"
        out.append(f"      {s.stage:<13} {n:>8}{cond}  — {s.note}")
    budget = (f"; design.max_runs={pv.budget_max_runs}"
              if pv.budget_max_runs is not None else "")
    out.append(f"      total: {pv.guaranteed_runs} guaranteed, up to "
               f"{pv.max_runs}{budget}")
    if pv.per_run_sec is not None:
        cap = (f" vs max_wall_clock_hours={pv.wall_clock_cap_hours:g}"
               if pv.wall_clock_cap_hours is not None else
               " (no max_wall_clock_hours declared)")
        out.append(
            f"    wall clock: ~{_dur(pv.expected_hours)} expected "
            f"(guaranteed runs x {pv.per_run_sec:.1f}s mean), "
            f"{_dur(pv.worst_hours)} worst case (all runs x "
            f"{pv.slowest_run_sec:.1f}s slowest){cap}; width "
            f"{pv.spending_width} at spending stages, {pv.confirm_width} at "
            f"confirm",
        )
    if pv.per_objective:
        t = f"{pv.t_crit:.3f}" if pv.t_crit is not None else "n/a"
        out.append(
            f"    screen MDE per objective: t(0.975, df={pv.pure_error_df})={t} "
            f"x 2 x sd / sqrt({pv.screen_corners} corners), against each "
            f"objective's epsilon:")
        for o in pv.per_objective:
            mark = ("   <-- epsilon below MDE"
                    if o.epsilon is not None and o.epsilon < o.mde else "")
            out.append(
                f"      {o.metric:<24} ({o.direction}) sd {o.noise_sd:.6g} -> "
                f"MDE {_fmt(o.mde)}; epsilon {o.epsilon_spec} -> "
                f"{_fmt(o.epsilon)}{mark}")
    if pv.noise_sd is not None and not pv.per_objective:
        t = f"{pv.t_crit:.3f}" if pv.t_crit is not None else "n/a"
        out.append(
            f"    screen MDE: t(0.975, df={pv.pure_error_df})={t} x 2 x "
            f"sd {pv.noise_sd:.6g} / sqrt({pv.screen_corners} corners) = "
            f"{_fmt(pv.mde)}; epsilon {pv.epsilon_spec} -> "
            f"{_fmt(pv.epsilon)}",
        )
    if pv.constraint_metrics and (pv.noise_sd is not None or pv.per_objective):
        out.append(
            f"    constraint metric(s) {', '.join(pv.constraint_metrics)}: no "
            f"MDE needed — a constraint is admissibility, checked per row, "
            f"not optimized or compared against epsilon")
    for fid, verdict in pv.brackets:
        out.append(f"    levels of {fid}: {verdict}")
    for w in pv.warnings:
        out.append(f"    WARNING: {w}")
    return out
