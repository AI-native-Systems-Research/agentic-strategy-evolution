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
