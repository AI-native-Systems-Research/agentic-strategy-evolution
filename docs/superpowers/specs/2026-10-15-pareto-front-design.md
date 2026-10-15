# Multi-objective `kind: optimization`: discovering the Pareto front

Status: design, 2026-10-15. Extends `2026-08-16-compiled-policy-design.md`
(binding); everything not stated here keeps that spec's semantics.

## Why

Users routinely tune knobs across several repos and want the **trade-off
frontier** — throughput vs memory, compression ratio vs speed, latency vs
cost — not one scalar. Today the kind accepts one `response.primary`; anything
else is a constraint. A constraint answers "is this admissible?"; a frontier
answers "what can I buy with what?". Scalarizing up front hides the frontier
and makes the author pick weights before seeing what is possible.

## Principles kept

- The epoch stays **pre-registered and tokenless**; the design matrices do not
  depend on the number of objectives (a factorial design measures every
  response it is given).
- **Honest uncertainty**: dominance is a claim with a bound, never a
  point-estimate comparison dressed as one; an unknown is never a zero.
- **Always act**: a single recommended configuration is still produced, on a
  named basis, through the fallback ladder.
- Adaptivity only as **registered branches with an accounting rule**.

## Contract (fixed — both implementation tracks code to this)

### Campaign schema (`optimization.response`)

```yaml
response:
  # EITHER primary (single objective, unchanged) OR objectives (>= 2). Not both.
  objectives:
    - {metric: ops_per_cpu_s, direction: maximize}
    - {metric: peak_rss_mib, direction: minimize}
  # Optional. How ONE configuration is chosen from the front for the
  # recommendation. Default: knee.
  preference:
    method: knee            # knee | weights | lexicographic
    weights: {ops_per_cpu_s: 1.0, peak_rss_mib: 0.5}   # method: weights only
    order: [ops_per_cpu_s, peak_rss_mib]               # method: lexicographic only
  constraints: [...]        # unchanged: admissibility
  held_out: [...]           # unchanged; may not name an objective
  self_check: [...]         # unchanged
  noise_estimate_pct: 2.0   # applies per objective (or a map metric -> pct)
```

`policy.epsilon` may be a map keyed by objective metric
(`{ops_per_cpu_s: {pct: 2}, peak_rss_mib: {abs: 5}}`) or a single spec applied
to every objective. It is each objective's indifference width.

### Validator rules (new)

- `objectives` and `primary` are mutually exclusive; `objectives` needs ≥ 2
  distinct metrics; directions in {maximize, minimize}.
- No objective may appear in `constraints`, `held_out`, or `self_check`.
- `preference.weights` keys ⊆ objective metrics, all > 0;
  `preference.order` is a permutation of the objective metrics.
- Warn when two objectives are the same metric under different names (can't
  be detected) — skip; but warn when an objective is constant across the
  liveness sweep (no trade-off to discover).

### Artifacts

`recommendation.json` (every fitting stage) gains, when multi-objective:

```json
"objectives": ["ops_per_cpu_s", "peak_rss_mib"],
"objective_models": {"<metric>": {"modelled": true, "reason": "...", "lack_of_fit_p": 0.4}},
"predicted_front": [ {"levels": {...}, "predicted": {"<metric>": v}, "se": {"<metric>": s},
                      "status": "nondominated|possibly_nondominated"} ],
"front_size_predicted": 7
```

`levels`/`predicted` at the top level remain: the PREFERRED point of the
predicted front (so every single-objective consumer keeps working).

`confirmation.json` gains `pareto` (measured): see report.

`report.json` gains (multi-objective only):

```json
"pareto": {
  "objectives": [{"metric": "...", "direction": "maximize"}],
  "front": [
    {"levels": {...}, "n": 6, "mean": {"<m>": v}, "ci": {"<m>": [lo, hi]},
     "status": "confidently_nondominated|possibly_dominated",
     "dominated_by": [], "source": "confirm|screen|refine"}
  ],
  "hypervolume": {"value": v, "reference": {"<m>": baseline_value}, "normalized": true},
  "preference": {"method": "knee", "chosen": {...levels...}},
  "rounds": 2,
  "gaps_remaining": [ {"between": [i, j], "size": g} ]
}
```

`report.md` renders the front as a table sorted by the first objective, marks
the preferred point, states statuses, hypervolume and remaining gaps, and the
What-to-do-next section names how to widen or refine the front.

## Algorithm

1. **Fit**: every objective on the same complete+infeasible rows
   (coded-as-run, `fit_effects`), exactly like constraint models.
   `model_adequate` = every objective's model adequate; a rejected objective
   model is recorded and its predictions used only as ranking hints.
2. **Policy observations** (closed vocabulary; reuse existing keys):
   `refinable_survivors` = factors significant for ANY objective;
   `lack_of_fit` = ANY objective rejects; `nan_response` = any objective NaN on
   a complete row. Certification-related observations become front-level
   (below).
3. **Predicted front**: enumerate `decide.candidates` (constraint models
   applied); compute each objective's prediction ± one-sided bound at
   `delta_screen / (K objectives)`. Candidate `c` is CONFIDENTLY DOMINATED if
   some `d` has, for every objective, its pessimistic bound better than `c`'s
   optimistic bound, and strictly so in one. `possibly_nondominated` = not
   confidently dominated. `nondominated` = point-prediction non-dominated.
4. **Shortlist (confirm)**: seats, in order, until `shortlist_size` is filled:
   the best measured admissible configuration per objective (extremes), the
   predicted extremes, the knee of the predicted front, then points that
   maximize the minimum normalized distance to already-seated points along the
   front (spread). Plus the supported-feasible seat when constraints exist.
   Never duplicate; CRN-paired replicates as today.
5. **Measured front**: over finalists (fresh replicates) AND every measured
   admissible configuration of the epoch (means over its complete rows),
   compute dominance with paired one-sided bounds where pairing exists
   (finalists) and Welch otherwise; `confidently_nondominated` = no other
   measured point dominates it with confidence AND it is not dominated in
   point estimate. Per-objective ε (indifference) is honoured: a difference
   below ε is not dominance.
6. **Adaptivity — registered `confirm -> confirm` branch** with accounting
   "front gap fill, Bonferroni over rounds": if `round < confirm_max_rounds`
   and the largest normalized gap between adjacent measured-front points
   exceeds `2 x max_k(eps_k / range_k)`, the next round seats predicted-front
   candidates that fall inside the largest gaps. Observation key:
   `front_gap_large` (new, INV-VOC pattern).
7. **Recommendation (always act)**: the preferred point of the MEASURED front
   by `preference` (knee = maximum normalized distance from the line between
   the two extreme points for K = 2; for K > 2, the point maximizing the
   minimum normalized improvement over the baseline); basis ladder:
   `certified` iff the chosen point is `confidently_nondominated` AND every
   objective's terminal regret vs the shortlist within that objective's ε is
   satisfied by the preference's scalarization — simpler, stated rule:
   certified iff `confidently_nondominated` and the preference scalarization's
   terminal regret bound ≤ ε_scalar (weighted sum of ε_k for weights; for knee
   use the min-normalized ε). Otherwise `terminal_best`, then the existing
   rungs. `certification_withheld` reasons gain `front_point_possibly_dominated`.
8. **Hypervolume**: over the measured confidently-nondominated points,
   objectives normalized to [0,1] by the measured range, reference point =
   `known_valid_baseline`'s measured means (or the worst measured value per
   objective). K = 2 exact; K = 3 exact by slicing; K > 3 Monte Carlo with a
   fixed seed and stated sample count.

## Oracles (synthetic surfaces, zero tokens)

- `pareto_convex`: two objectives with a known analytic convex front.
- `pareto_concave`: concave front (knee preference must still pick a front
  point; weighted sums miss concave regions — test that knee/lexicographic
  reach them).
- `pareto_with_constraint`: front partly cut by a constraint.
- `pareto_three`: three objectives.
Properties: every reported `confidently_nondominated` point lies within ε of
the true front; the reported front's hypervolume ≥ X% of the true front's
(stated per surface); single-objective campaigns are byte-identical to before.

## Out of scope (stated)

Model-based acquisition beyond the registered gap-fill branch (expected
hypervolume improvement); interactive preference elicitation.

## Decisions (estimation core, recorded where the contract was ambiguous)

Implemented in `orchestrator/optimize/pareto.py` (pure arithmetic),
`orchestrator/optimize/pareto_stage.py` (artifact glue), and gated call sites
in `stage_runner.py` / `policy.py`. Every call site is gated on the compiled
policy registering `objective.objectives`, so a single-objective campaign takes
none of these paths.

1. **The primary role.** A multi-objective campaign has no `primary`; its FIRST
   objective plays that role wherever the single-objective machinery needs one
   metric (the stage rule's fit and `effects.json`, the NaN guard, the adapter's
   metric path, `top_candidates`, `residual_regret_model`). The policy records
   it as `objective.metric/direction`, with every objective (and its own
   epsilon spec, map-valued `policy.epsilon` resolved per metric) under
   `objective.objectives` and the preference under `objective.preference`.
2. **Objective models** reuse the constraint models' row selection and
   reduction (`constraint_models._fit_one`). A model is *rejected* for lack of
   fit (`lack_of_fit` observation, curvature branch) or when not estimable
   (`model_adequate: false` only); a model with no pure error is NOT rejected
   (no test to fail), but its bounds are infinite, so nothing is confidently
   dominated through it.
3. **`stationary_in_hull` is not observed** in a multi-objective epoch: the
   first objective's stationary point leaves the hull whenever that objective is
   monotone in a knob the other pays for, which is the normal shape of a
   trade-off, not a defect in the ranges. `report.md`'s What-to-do-next names a
   factor whose range edge an objective's extreme sits on instead.
4. **Refine carries the other branches.** Refine holds a choice factor at the
   preferred point's level, so its predicted front sees one branch; entries of
   the previous stage's predicted front at another level of a held factor are
   appended (with their `stage`). Oracle `pareto_choice_split`.
5. **"Within epsilon of the front"** is additive epsilon-approximate Pareto
   optimality: `c` is within epsilon iff no configuration beats it by at least
   `eps_k` on EVERY objective. Front membership (point estimates) honours
   epsilon: `d` removes `c` only if no worse anywhere and better by MORE than
   `eps_k` somewhere.
6. **Confident status.** `c` is `confidently_nondominated` iff for EVERY other
   measured admissible configuration `d` some objective's one-sided upper bound
   on `d - c` is below `eps_k` (Bonferroni over rivals x objectives), and no
   ADEQUATE-model prediction (other than at `c`'s own levels) beats `c`'s
   measured mean by `eps_k` on every objective.
7. **Variance: pooled pure error**, not per-pair Welch. The within-configuration
   mean square per objective over every configuration with >= 2 complete rows.
   With the default 3 replicates a per-pair Welch t has 2-4 df and a Bonferroni
   quantile above 10, so nothing could ever be claimed; the pooled estimate is
   the variance the fits and constraint models already rest on. Pairing is not
   used (valid, wider when seeds were shared).
8. **Fresh replicates only for finalists.** A configuration confirm measured is
   represented by its confirm rows only (its fitting rows are what nominated it,
   so pooling them carries the winner's curse); fitting-only configurations keep
   their fitting rows.
9. **Two levels, two looks.** Front statuses and the hypervolume are one claim at
   the end: `delta_terminal`. Certification is a stopping rule evaluated every
   round, so it pays for every registered look: the preferred point must be
   confident at `delta_terminal / max_rounds` ("Bonferroni over rounds") and the
   scalar regret is taken at that level. Charging rounds to the statuses made
   every extra registered round shrink the confident set.
10. **Scalar regret.** Rivals are EVERY measured admissible configuration, not
    only the front. Weights apply to objectives normalised by the measured range
    (`epsilon_scalar = sum_k w_k eps_k / range_k`); knee (K = 2) uses the unit
    normal of the line through the extremes (linear once they are fixed);
    lexicographic uses `order[0]`; knee (K > 2, `min_k` improvement over the
    baseline) bounds `max_r min_k U_k(r) - min_k L_k(c)` with simultaneous
    bounds on normalised means. `epsilon_scalar` for knee is `min_k eps_k /
    range_k` as stated above.
11. **Hypervolume** over the confident points in the measured-range frame;
    reference = `known_valid_baseline`'s measured means when it was measured,
    else the worst measured value per objective.
12. **Gaps.** K = 2: adjacency along the front sorted by the first objective;
    K > 2: the edges of the Euclidean minimum spanning tree. Size is L-infinity
    in normalised units. A gap is "large" above `max(2 x max_k eps_k / range_k,
    2 x max_k (t se_k - eps_k) / range_k)`: the second term is the separation a
    midpoint fill needs to be told apart from both neighbours at confirm's
    replicate count. A gap-fill candidate must itself be predicted resolvable
    from both endpoints; round r > 1 never re-seats an already-confirmed point
    except a `possibly_dominated` one (re-measuring a confident point on a noisy
    constraint boundary is how it gets struck off by one unlucky replicate).
13. **Defaults.** Multi-objective `shortlist_size` defaults to `2K + 2` and
    `confirm_max_rounds` to 2 (the gap-fill branch needs a second round to
    exist); explicit declarations win. The gap-fill rule is registered BEFORE
    `certified -> report`: the epoch's product is the front.
14. **Noise map.** `build_checks` baseline tolerance with a map-valued
    `noise_estimate_pct` uses the first objective's entry.

### Oracle results (seeds 1-8, default multi-objective campaign)

| surface | front coverage | hypervolume ratio (confident) | recommended on front | certified | false cert | runs |
|---|---|---|---|---|---|---|
| `pareto_convex` | 1.00 | 0.996 | 8/8 | 8/8 | 0 | 56 |
| `pareto_concave` | 1.00 | 0.993 | 8/8 | 8/8 | 0 | 56 |
| `pareto_with_constraint` | 0.70-1.00 | 0.859-0.974 | 8/8 | 1/8 | 0 | 56 |
| `pareto_three` | 0.42-0.59 | 0.836-0.860 | 8/8 | 7/8 | 0 | 78 |
| `pareto_choice_split` | 0.84-0.95 | 0.950-0.957 | 8/8 | 7/8 | 0 | 52 |
| `pareto_noisy` (noise ~ epsilon) | 0.40-1.00 | 0.781-0.967 | 8/8 | 1/8 | 0 | 56 |

Property 1 (every confident point within epsilon of the true front and truly
admissible): 0 violations everywhere. Property 5 (raising `confirm_max_rounds`
1 -> 2 -> 3 never lowers the true hypervolume): holds on every surface for the
whole reported front, and for the confident points on every surface except
`pareto_noisy`, where a fill closer than the replicates can resolve honestly
strips its neighbours' confidence. Coverage on `pareto_three` is low because
its true front is a 2-D surface of ~200 grid points measured with 78 runs.

### The infeasible-finalist rule (evaluated, kept)

Alternative (b): an infeasible finalist is a caveat (`certification_caveats`)
rather than a veto when >= 2 admissible finalists remain, their bound is within
epsilon and the model is adequate. Certified / false-certified (truly gap >
epsilon OR truly inadmissible), seeds 1-8:

| surface | rounds | (a) today | (b) caveat |
|---|---|---|---|
| `sla` (p99 <= 40) | 1 / 3 | 0/0, 0/0 | 0/0, 5/0 |
| `infeasible_corner_interior` | 1 / 3 | 3/0, 3/0 | 3/0, 3/0 |
| `stochastic_constraint_boundary` | 1 / 3 | 0/0, 0/0 | 0/0, **1/1** |
| `deterministic_constraint_axis` | 1 / 3 | 0/0, 0/0 | 8/0, 8/0 |
| `pareto_with_constraint` | 2 / 3 | 1/0, 7/0 | 7/0, 7/0 |

(b) raises certification sharply but adds a false certificate: on
`stochastic_constraint_boundary` it certified a truly inadmissible
configuration that passed its own replicates by luck while a sibling in the
same stochastic region did not -- exactly the evidence the veto reads. Today's
rule is kept (`stage_runner._INFEASIBLE_FINALIST_CAVEAT = False`, pinned by
`tests/test_optimize_pareto.py::test_an_infeasible_finalist_still_withholds_certification`).
