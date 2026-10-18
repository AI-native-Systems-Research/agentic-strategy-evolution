# Matched-budget benchmark: Nous vs random search, Latin hypercube, GP-BO

Every number below was regenerated under the current code: Nous source digest
`44d94bc5ee2a41b2` and benchmark digest `ac16583f62b3b384`, at checkout
`3abcb38` (nousko 4ccc6b3 plus the benchmark changes). The full run was done
twice: once at `bd97bf6`, and again after the last benchmark-code change. The
second run reproduced every row exactly, apart from timing and one added field
(`withheld`). That code includes
WP-A, WP-B, P2, P3, P4 and P6b. Each generated block names the digests its
rows were produced under, and every number in the prose traces to a row in
one of the four JSON files beside this one.


> **Pre-declared analysis (written and committed before the regenerated
> results existed; #321 H2 / #320 D4).**
>
> - **Primary metric.** For each surface family (shipped, non-quadratic,
>   many-knob sparse), the mean difference in NORMALIZED true regret at the
>   matched budget N, Nous minus GP-BO under `PRIMARY_RULE` (GP-BO's GP-mean
>   pick). Normalized regret is `regret / (f_best - f_worst_admissible)`, so
>   every surface counts on [0, 1]. The 95% interval is a percentile bootstrap
>   over SEEDS (the seed is the resampling unit; each seed's value is the mean
>   over the family's cells), 10,000 resamples, seeded, seed recorded in the
>   JSON. Negative favours Nous.
> - **Secondary.** Head-to-head counts (better / tie / worse, exact and within
>   Nous's ε) under `PRIMARY_RULE`, with Wilson 95% intervals on the win and
>   loss proportions; per-cell mean regret with the same bootstrap; anytime
>   regret curves at six budget fractions of N; certificate counts with their
>   false-certificate counts, per arm. A false certificate in any arm is a
>   core-claim failure and is reported as such, not averaged away.
> - **Multi-objective primary.** Mean hypervolume regret at the matched
>   budget N, `(HV(true front) - HV(reported, truly valid)) / HV(true front)`
>   in the oracle's normalised frame. Nous's reported front is every point its
>   report lists (both statuses); a baseline's is its measured non-dominated
>   set. Same seeded bootstrap over seeds. Lower is better.
> - **Ablations.** Each switch is compared with the default arm on the same
>   seeds: mean paired difference in normalised regret (or HV regret), with
>   the same bootstrap, and the certificate / false-certificate counts. The
>   drift attribution is tested by switching run-order randomization off
>   (every design and confirm block executed in design order).
> - **Nothing is tuned on these surfaces.** Ablation settings (allocate
>   `seats: 2`, the BO proposer's defaults) are the guide's documented
>   example and the module defaults, fixed before any run.

>
> The declaration was committed in `dc489e0` (2026-10-18 06:02), before the
> first regenerated row existed (the run started at 07:24). `PRIMARY_RULE` is
> unchanged.

Zero LLM tokens: every campaign is the in-process synthetic harness
(`orchestrator.optimize.harness`). Reproduce through the machine's heavy
wrapper, with at most 3 workers:

| invocation | what | JSON |
|---|---|---|
| `python -m benchmarks.optimization.run` | the suite | `optimization-benchmark.json` |
| `... --audit-repro` | the stage-0 audit's setup | `optimization-benchmark-audit-repro.json` |
| `... --ablations` | D4 ablations (the default arm is reused from the suite cache) | `optimization-benchmark-ablations.json` |
| `... --mo` | multi-objective arm | `optimization-benchmark-mo.json` |

- **Caching.** Every invocation accepts `--cache-dir`, so a killed run resumes.
  `--plan` prints the job counts before anything runs. `--render-only`
  re-aggregates a section from its JSON.
- **Digests.** The code digest is part of every cache key, so no row produced
  by other code is reused.
- **Previous run.** `optimization-benchmark-previous.json` keeps the previous
  run's per-cell budgets, certificate counts, regrets and CPU times (Nous digest
  `10d74ceaa7add3b7`, checkout `fd2e722`). The cost comparison below reads from
  it.

**What "matched budget" means here.** The budget N is the number of runs Nous's
own stopping rule chose. Every baseline is given exactly that N on the same
(surface, noise, seed), so every head-to-head is a comparison at **Nous's
chosen budget**. A method that would do better with fewer or more runs is not
credited for it. The anytime curves show what happens BEFORE N:

- Nous's curve is where its run sequence stands after n runs. The campaign was
  not stopped there, and it would not have certified there.
- A baseline's curve is its pick from the prefix of a run planned for N.

**Run size and cost of this regeneration** (64 GB machine, `--workers 3`,
under `nous-e2e/bin/heavy`):

| section | Nous campaigns | baseline runs | wall time | peak RSS (largest process) |
|---|---|---|---|---|
| suite | 336 | 1344 | 21.1 min | 0.93 GB |
| audit repro | 360 | 1440 | 48 s | 0.14 GB |
| ablations | 272 (+128 default arm, reused from the suite) | – | 25 s | 0.15 GB |
| multi-objective | 216 | 648 | 64 s | 0.14 GB |

## Protocol

- **Budget.** For each (surface, noise multiplier, seed), Nous runs first.
  - N is its count of FRESH measurements, from
    `benchmarks/optimization/measured.py`. That is the one counter every arm
    and the crash path use. Failed, infeasible and rejected rows count.
  - Copies do not count. Two kinds of row carry `reused_from` and are
    excluded: a refine row filled from the screen (`reused_from.stage`), and
    a row a resumed iteration carried forward (`reused_from.iteration`).
  - Every baseline gets exactly N measurements of the same surface, under the
    same noise model, over the SAME candidate domain Nous can recommend from
    (next bullet). A failed measurement still costs a run.
  - A Nous campaign that crashes is charged the worst admissible regret, and
    its baselines get the runs it spent.
  - Each ablation arm and each multi-objective arm is compared at its OWN N.
- **Candidate domain and truth (one for every method).**
  - **The rule.** The domain is the DECLARED candidate space plus the centre
    configurations the campaign's designs actually run:
    - the declared lattice (`surfaces.lattice_axis`):
      - every level of a choice or `levels_only` numeric;
      - the declared pair of a two-level numeric;
      - every multiple of g in [min, max] for a refinable numeric with
        `grid: g` (plus the declared levels). `decode_coded` snaps any fitted
        or design value onto that lattice;
      - a dense 201-point grid for a refinable numeric with no grid
        (tolerance: half the spacing). No suite surface has one.
    - the centre configurations (`surfaces.centre_configs`). These are read
      off Nous's own design code (`stage_runner._build_design`, then
      `matrix.expand`, which applies `matrix.centre_configurations` and the
      diagonal cyclic choice assignment), never hand-coded. Examples:
      - `fails_at_one_level` runs CPU = 24 with its two diagonal choice
        configurations;
      - `infeasible_corner_interior` runs the one joint centre {BS: 20,
        CMP: 1, PF: 5}.
  - **Why.** A certificate is a claim about the candidate space Nous ranks and
    the configurations it actually measured. A truth outside that space is a
    value Nous could never be asked to beat.
  - **Same domain for every method.** Every baseline samples this domain:
    - uniform over the lattice product plus the centres;
    - LHS swaps a sample for a centre at the centres' share;
    - GP-BO's pool always contains the centres.

    The truth (the optimum, its value and the worst admissible value) is
    enumerated over it. It is sized before enumeration and capped at 2,000,000
    points; the largest are the geometric knobs, at 1,032,256.
    Tests check that:
    - the truth lies in the domain on every surface;
    - every committed Nous recommendation lies in it;
    - `infeasible_corner_interior`'s truth is 14.4 at {BS: 32, CMP: 0, PF: 8}.
  - **Change from the previous version (P7 review H3).** The truth and the
    baselines used nine snapped points per gridded axis
    (`synthetic.candidate_grid`), while Nous could recommend any lattice point.
    An audit of every surface found:

    | surface | old grid optimum | domain optimum | effect |
    |---|---|---|---|
    | `two_peaks` | 14.754 | (14, 3) = 15.653 | Nous's (15, 3) was scored 0.364 against the grid; its real regret is 1.263 |
    | `sparse_knobs` 6/8/12 | X00 = 12, 25.07 | X00 = 13, 25.08 | +0.01 |
    | `geometric_knob(_log)` | (8, 2048) = 100.0 | (8, 2048) = 100.0 | none. Nous's off-grid recommendations (for example INT 7, BUF 1869) were already scored by their own value: off-grid but correct |
    | `fails_at_one_level` | 13.8 | 13.8 | none to the truth, but the baselines could not sample Nous's CPU = 24 |
    | every other single-objective surface | | identical | none |
    | the multi-objective surfaces except `pareto_three_discrete` | | | the lattice front has more points, so the true HV is higher (for example `pareto_convex` 0.745 → 0.763) |

  - **One false start, recorded.** An intermediate version of this fix gave
    each two-level numeric its centre independently. That over-stated the
    domain: it made {BS: 20, CMP: 2, PF: 8} = 14.7 reachable on
    `infeasible_corner_interior`, a point no design runs and no ranking scores.
    It produced 6 spurious "false" certificates there, all of which certify
    the declared-space optimum {32, 0, 8} = 14.4. Deriving the centres from
    `matrix.expand` removed them.
  - **CPU cost.** GP-BO on the 1,032,256-point geometric-knob lattice takes
    about 216 s per campaign, against 0.1 s on the old 100-point grid.
- **Metric.** TRUE regret of the recommendation on the NOISELESS surface,
  `f(true optimum) - f(recommendation)`. An infeasible recommendation (outside
  `X_valid`), or no recommendation at all, is charged the regret of the worst
  admissible configuration. Normalised regret divides by
  `f_best - f_worst_admissible`.
- **Recommendation rules, both reported.**
  - `obs`: the measured configuration with the best mean over its replicates.
    It is feasible only if every replicate passed every constraint, which is
    the rule Nous uses.
  - `GP mean`: the measured feasible configuration with the best posterior mean
    of the GP below, fitted to the method's own data. Measured points only,
    never an unmeasured argmax.
  - The PRIMARY rule (`PRIMARY_RULE`, unchanged) is `obs` for RS and LHS and
    `GP mean` for GP-BO, the standard noisy-BO recommendation.
  - Exception: `GP-BO-crude`'s GP-mean pick is the audit's, and it is NOT
    restricted to feasible points. That is why it scores 8.2 on `sla`.
- **Anytime curves.** Regret is recorded at 10, 20, 40, 60, 80 and 100% of N
  (`run.FRACTIONS`).
  - Nous: the best-so-far always-admissible measured configuration after its
    first n fresh measurements, in execution order.
  - Baselines: their primary-rule pick on the first n of their own
    measurements. A baseline's prefix GP is fitted with the same seed as its
    final GP-mean pick.
  - A configuration with any row the runner marked `infeasible` or `rejected`
    is struck for good, in Nous's curve and the baselines' alike. A `failed`
    row (no measurement) just contributes nothing.
  - A baseline's 100% point is its recorded answer. Nous's 100% point is its
    best measured configuration, which is not always its recommendation.
- **Intervals.** Every interval on a mean is a percentile bootstrap over SEEDS:
  10,000 resamples, seed 20261018 (`stats.BOOT_SEED`, recorded in each JSON's
  `meta.boot`). The primary also prints the t interval.
  - With 8 seeds a percentile bootstrap is coarse. It collapses to a point when
    every seed agrees, which happens often here. A zero-width interval means
    "identical on every seed", not "certain".
  - Head-to-head proportions get Wilson score intervals. These are conditional
    on THESE surfaces and noise levels: each campaign is one trial, and the
    surfaces are a fixed, non-random selection. The interval says nothing about
    other surfaces.
- **Ties.** "Exact" ties need identical regret. The "within ε" columns treat a
  difference of at most Nous's own resolved ε (a percentage of Nous's best value
  in that campaign) as a tie. That is Nous's indifference width, not a neutral
  one.
- **False certificate.**
  - Single-objective: a certified campaign whose recommendation is infeasible,
    or whose true regret exceeds its ε.
  - Multi-objective: certified while the recommendation is not within ε of the
    true front (`harness.evaluate_pareto_campaign`).
- **Surfaces.**
  - Single-objective: every surface in `synthetic.SURFACES` except
    `bowl_out_of_hull` (its optimum lies outside the hull by construction).
    Each constrained surface carries the constraints it was built for.
  - The audit's non-quadratic `step_cliff`, `ridge_cubic` and `two_peaks`.
  - `sparse_knobs(6/8/12)`, with 3 active knobs.
  - Multi-objective: all of `synthetic.PARETO_SURFACES`, plus
    `ALLOCATE_SURFACES["pareto_three_discrete"]`.
- **Size.**
  - Suite: seeds 1-8, noise ×1 and ×4 of each surface's `noise_sd`.
  - Audit repro: the audit's 9 surfaces, seeds 1-20, noise ×1 and ×8.
  - Ablations: seeds 1-8, ×1 and ×4.
  - Multi-objective: seeds 1-8, at the declared noise.
  - CPU seconds are the comparable cost figure. Wall time is inflated on a
    shared machine.

## The baselines

**GP-BO** (`benchmarks/optimization/gp.py`, `baselines.py`). Configured to
resemble a standard default rather than tuned to this suite:

- **Kernel.** Matern-5/2 with one lengthscale per input (ARD), times an
  outputscale, plus homoscedastic Gaussian noise. Inputs are coded to [0,1]:
  log coding for `scale: log` factors, one-hot for choices with more than two
  levels (a plain one-hot, not BoTorch's `MixedSingleTaskGP` categorical
  kernel). Outputs are standardized.
- **Hyperparameters, by MAP.** Gamma priors in (shape, rate) form, after
  BoTorch's legacy `SingleTaskGP` defaults (pre-0.12; BoTorch >= 0.12 uses
  dimension-scaled LogNormal lengthscale priors instead):
  - each lengthscale ~ Gamma(3, 6);
  - the outputscale ~ Gamma(2, 0.15);
  - the noise VARIANCE (on standardized outputs) ~ Gamma(1.1, 0.05).
- **Fitting.** The priors are applied to log-parameters with the log-Jacobian
  term, so the MAP point differs slightly from BoTorch's. The fit runs inside box
  bounds (lengthscale [0.01, 20], outputscale [0.01, 50], noise variance
  [1e-6, 4]) by L-BFGS-B with analytic gradients, which
  `tests/test_optimization_benchmark_smoke.py` checks against finite differences.
  Hyperparameters are refitted after every measurement while n <= 100 (warm
  start), and every 10th measurement beyond that, with two random restarts every
  10th step.
- **Initial design.** A Latin hypercube of `max(2, min(max(6, 2(d+1)), floor(N/3)))`
  points, where d is the coded input dimension.
- **Acquisition.** Expected improvement (Jones, Schonlau & Welch 1998) on the
  latent posterior. The incumbent is the best posterior mean among measured
  feasible points.
- **Constraints.** EI times each constraint GP's probability of satisfaction
  (Gardner et al. 2014; Gelbart, Snoek & Adams 2014). When nothing measured is
  feasible yet, the acquisition is the probability of feasibility alone.
- **Search.** EI is maximized over the whole grid when it has at most 4096
  points. Otherwise it searches 4096 random grid points plus every one-factor
  neighbour of the incumbent.
- **Failures.** A configuration that has only ever failed to measure is removed
  from the pool. Without that rule, GP-BO spent 31 of 40 runs re-measuring one
  failing configuration on `fails_at_one_level`.

**GP-BO-crude** is the audit's probe, kept for reproduction:

- a fixed isotropic RBF kernel (lengthscale 0.3, nugget 0.01);
- 6 uniform random starts;
- EI over the grid, or over 20,000 random grid points when the grid is larger;
- no constraint handling, and the same never-re-pick-a-failure rule.

**RS** samples each factor's axis uniformly. **LHS** stratifies each axis into
N strata and permutes them independently.

**Multi-objective baselines** (`benchmarks/optimization/mo.py`):

- **What each one reports.** Each baseline reports the non-dominated set, by
  mean observed objective values, of its always-feasible measured
  configurations.
- **Nous's reported front.** Every point in `report.json`'s `pareto.front`,
  with both statuses. Points that are truly invalid contribute nothing.
- **RS and LHS.** As in the single-objective arm.
- **ParEGO** (Knowles 2006).
  - Each step draws a weight vector uniformly from the simplex.
  - It scalarises every measured row by the augmented Chebyshev function
    (rho = 0.05, as in the paper). The objectives are normalised to [0, 1]
    over the observed rows.
  - It fits the GP above to the scalarised values and measures the pool point
    of maximal EI, times each constraint GP's probability of satisfaction.
  - The initial design, the pool and the refit schedule are GP-BO's.
  - EHVI was not implemented. ParEGO reuses the existing GP machinery at the
    same memory cost as GP-BO: peak RSS of the multi-objective section is
    0.14 GB.

## Comparison with the audit's 144 / 174 / 42

The audit reported Nous against its crude GP-BO over 360 head-to-heads as
**better 42, tie 174, worse 144**. With the audit's setup (`--audit-repro`):

| baseline | rule | now: better / tie / worse (exact) | now: within Nous's ε | previous run (`fd2e722`), exact | previous, within ε |
|---|---|---|---|---|---|
| GP-BO-crude (the audit's) | GP mean | **125 / 151 / 84** | 78 / 266 / 16 | 53 / 171 / 136 | 12 / 236 / 112 |
| GP-BO (fitted) | GP mean | **83 / 166 / 111** | 56 / 264 / 40 | 21 / 186 / 153 | 4 / 235 / 121 |
| GP-BO (fitted) | obs | 100 / 150 / 110 | 66 / 257 / 37 | 42 / 174 / 144 | 12 / 231 / 117 |

Most of the shift comes from Nous. GP-BO's rows moved too, because it also
gets the larger N (for example geometric_knob ×8: 4.45 → 2.71; step_cliff ×8:
0.29 → 0.215), but by less. Nous's regret fell on the surfaces where it used to
lose:

| surface | noise | previous | now |
|---|---|---|---|
| geometric_knob | ×1 / ×8 | 26.25 / 23.65 | 0.188 / 0.188 |
| step_cliff | ×1 / ×8 | 0.90 / 0.94 | 0.40 / 0.555 |
| ridge_cubic | ×1 / ×8 | 0.50 / 0.54 | 0.22 / 0.30 |
| two_peaks | ×1 / ×8 | 1.75 / 1.78 | 0.364 / 0.364 |

Every certificate on those four surfaces is gone: 0 of 160, against 54 of
160 before, of which 53 were false. Against the fitted GP-BO Nous still loses
more often than it wins: 111 losses against 83 wins (exact), and 40 against 56
within ε. The audit-reproduction observation from the previous version still
stands. The audit's exact triple 42/174/144 was what the fitted GP-BO scored
under `obs` in the previous run, which may be chance or a label mix-up in the
audit's table. That is noted, not resolved.

## Interpretation

The **pre-declared primary** is the per-family mean normalised regret
difference, Nous minus GP-BO (GP mean), with a bootstrap over 8 seeds. In the
suite:

| family | Nous minus GP-BO [95%] | read |
|---|---|---|
| shipped (21 surfaces x 2 noise) | **-0.055 [-0.066, -0.037]** | favours Nous, but see below |
| non-quadratic (3 x 2) | **-0.059 [-0.082, -0.021]** | favours Nous, but see below |
| many-knob sparse (3 x 2) | +0.0002 [-0.0002, +0.0008] | a tie |

**Both "favours Nous" results rest on one surface each.** A family mean of a
bounded metric is dominated by any cell with a large normalised gap. The
breakdown below is a POST-HOC reading, not part of the declared analysis:

- **Shipped.** The shipped family's mean rests on `stochastic_constraint_boundary`:
  Nous 0.875, every baseline 7.0, a normalised gap of -0.875 per cell. Without
  that surface, Nous minus GP-BO on the shipped family is **+0.004 [+0.0004,
  +0.007]**, a small loss for Nous. Part of that gap is a design asymmetry, not
  a better optimizer. Nous replicates its finalists. A baseline mostly measures
  a configuration once, so its "feasible" pick is feasible by one lucky draw. A
  baseline with replicated confirmation would narrow the gap.
- **Non-quadratic.** The non-quadratic mean rests on `two_peaks`: Nous 0.364,
  GP-BO 1.53. On `step_cliff` (0.40-0.46 against 0.225) and `ridge_cubic`
  (0.22-0.23 against 0.003-0.017) GP-BO is clearly better. Without `two_peaks`
  the family difference is **+0.043 [+0.032, +0.052]**.

**Where Nous wins or ties.**

- **Smooth, low-order surfaces.** These are additive, interaction_only, bowl,
  bowl_centred, saddle, choice_x_numeric, drift and geometric_knob_log: 128
  campaigns.
  - Against GP-BO the exact counts are 21 better / 102 tied / 5 worse. Within
    ε the result is 1 / 127 / 0.
  - Nous is within ε of the best baseline in 128 of 128.
  - So this is parity with GP-BO, not a win. Against RS and LHS Nous wins
    clearly.
- **Many knobs with effect sparsity** (`sparse_knobs` 6/8/12, 108-568 runs).
  - Mean regret is at most 0.014 in every cell. Within ε Nous ties GP-BO in 48
    of 48 and never loses to RS or LHS.
  - It certified NONE of the 48; see the cost section.
- **Drift** (`drift`, a trend of 0.05 per run). Nous scores 0 regret, RS
  0.34-0.38, LHS 0.21-0.22 and GP-BO 0.013-0.05.
  - The previous version attributed this to Nous's blocked, randomized run
    order. **The ablation refutes that attribution for regret.** With run-order
    randomization off (every block in design order), Nous's regret on `drift`
    is still 0 on all 16 campaigns.
  - What randomization does buy there is CERTIFICATES: 10 of 16 with it, 4 of
    16 without, 0 false either way.
  - Plausibly, the regret gap comes from the baselines' `obs` pick, which
    favours whichever configuration happened to be measured late in a rising
    trend, while Nous compares replicated finalists. That is not tested here.
- **Geometric knob coded linearly** (`geometric_knob`, no `scale: log`). Nous
  improved from 26.25 to 0.188. GP-BO scores 2.6-3.2 and RS 0.061, the best
  method here. No certificate was issued, against 4 false ones before.
- **Multi-objective, against RS and LHS.** Pooled HV regret, Nous minus RS, is
  -0.022 [-0.027, -0.017]; minus LHS, -0.015 [-0.020, -0.009].
- **What no baseline offers:**
  - a certificate with stated deltas, with **0 false certificates in every arm
    of every section** (table below);
  - a pre-registered policy and an audit trail;
  - provenance, `nous reanalyze`, and a cross-epoch error budget.

**Where Nous loses.**

- **Non-quadratic surfaces other than two_peaks.** GP-BO's regret is 10-70
  times lower on `ridge_cubic` and about half of Nous's on `step_cliff`. Nous no
  longer certifies there (0 of 48, against 22 of 48 before, all of which were
  false). Its answer is still the second-order model's, so it is still wrong in
  the same way.
- **Deterministic constraint at the boundary** (`sla`). Nous 0.40 at ×1 and
  0.275 at ×4; GP-BO 0.000.
- **A level that fails to measure** (`fails_at_one_level`). Nous 0.32-0.36
  (0.64 before); GP-BO 0.08.
- **Multi-objective, against ParEGO.** Pooled HV regret, Nous minus ParEGO at
  Nous's budget, is **+0.038 [+0.035, +0.040]**. ParEGO wins the majority of
  seeds on all 9 surfaces.
  - It wins 8 of 8 on `pareto_concave`, `pareto_three`, `pareto_choice_split`
    and `pareto_three_noisy`.
  - On `pareto_choice_split` and `pareto_three_noisy` Nous also loses to RS
    and LHS.
- **Anytime.** On the shipped family Nous's curve sits below every baseline's
  from 10% of N onward: 0.194 at 10% against GP-BO's 0.293, and 0.018 at N
  against GP-BO's 0.072.
  - On non-quadratic surfaces it is flat at 0.25 until 40% of N, because the
    screen's corners are all it has measured. It ends at 0.066, where RS
    (0.099) and LHS (0.070) end too. GP-BO ends at 0.126, which is pulled up by
    `two_peaks`.
  - On many-knob surfaces Nous's best-so-far sits at 0.065 until the final
    confirm. GP-BO reaches 0.004 by 20% of N, so GP-BO gets there with a fifth
    of the runs.
  - Stopped early, GP-BO is the better tool there. Nous's N is the price of
    the certificate it then declines to issue (below).

**The cost of the P3/P4 conservatism, measured against the previous run.**

| | previous (`fd2e722`, digest `10d74cea…`) | now (`44d94bc5…`) |
|---|---|---|
| suite: runs (sum of N) | 21,056 | 26,208 (+24%) |
| suite: certified / false | 162 / **26** (136 sound) | 50 / **0** |
| suite, smooth family (128 campaigns): certified / false | 89 / 0 | 44 / 0 |
| suite, many-knob sparse (48): certified / false | 47 / 0 | 0 / 0 |
| audit repro: runs | 10,460 | 16,080 (+54%) |
| audit repro: certified / false | 170 / **53** (117 sound) | 60 / **0** |

- **Runs.** The replicate floor (P3: 6 or 7 confirm replicates, against 3)
  and the outer validation ring (P4) cost runs. Some examples, previous N
  against current N:

  | surface | previous N | current N |
  |---|---|---|
  | bowl | 29 | 44 |
  | choice_x_numeric | 17 | 38 |
  | sla | 38 | 68 |
  | sparse_knobs_12 | 553 | 568 |

  Every baseline gets the larger N too, so the regret comparisons stay
  matched.
- **Certification power.** On the smooth family the code withheld 45 of the
  89 previous certificates, and none of the 89 had been false. On the
  many-knob family it withheld all 47, none of which had been false. That is
  the price of the soundness fix: 26 + 53 false certificates removed, against
  45 + 47 sound ones lost in those two families. On the many-knob family the
  dominant reason is `model_bound_above_epsilon`, recorded in 42 of 48
  campaigns: the Scheffé-band model bound (P2) over a 9^k searched space is
  wider than ε at these designs. That is the H3 caveat, now measured. The reasons are tabulated per
  family under the suite results (`Why uncertified campaigns were withheld`).
- **CPU.** On `sparse_knobs_12` Nous's median analysis CPU rose from 2.8 s to
  37.5 s per campaign. GP-BO takes 79.6 s, so Nous is still about half. On
  `sparse_knobs_8` Nous now takes 10.4-13.0 s against GP-BO's 5.6 s. A cProfile
  of one `sparse_knobs_12` campaign (seed 1; 98 s under the profiler) gives the
  top cumulative functions below `run_stage`:

  | function | cumulative s | origin |
  |---|---|---|
  | `certificate.region_bound` (115,130 calls of the inner `upper`) | 47.7 | P2 branch-and-bound (`6093737`) |
  | `stage_runner._validation_plan` → `adequacy._greedy_maximin` | 26.0 | P4 outer validation ring (`456494e`) |
  | `stage_runner._build_design` | 13.0 | |
  | `stage_runner._adequacy_record` (`design_efficiency` 8.1 s) | 9.8 | P4 G/I efficiency |
  | `certificate.model_regret_bound` | 8.5 | |

  This is measured, not optimised here. On a real target the runs, not the
  analysis, dominate the cost.

**Ablations (D4).** Each arm is compared on the same seeds against the
default; tables are under the results.

- **Allocate** (`design.confirm.allocate: {seats: 2}`). On the
  single-objective surfaces:
  - Paired Δ normalised regret is -0.0012 [-0.0032, 0.0000] on the smooth
    surfaces and +0.0001 [0.0000, +0.0004] on the non-quadratic ones.
  - Mean runs rise 45.1 → 52.3 (+16%), and certificates fall 20 → 12.
  - The cause is the extra registered look, which raises the replicate floor
    from 6 to 7 and splits delta_terminal three ways, whether or not the
    round fires.
  - It fired in 22 of 112 campaigns: additive ×4, saddle ×1/×4 and
    ridge_cubic ×4. It never fired on step_cliff or two_peaks, where the model
    gate declines.
  - On these surfaces allocate is a small regret gain at a real cost in runs
    and certification power.
- **Allocate, multi-objective.**
  - Paired Δ HV regret is **-0.0063 [-0.0100, -0.0029]** at 68.4 → 72.2 mean
    runs. On `pareto_with_constraint` it is -0.029 [-0.053, -0.006], and on
    `pareto_noisy` -0.014 [-0.024, -0.005].
  - Front certificates are 36 → 37 of 72, with 0 false.
  - On `pareto_three_discrete`, the recombination oracle's surface, HV regret
    is 0.006 → 0.003 (-0.0024 [-0.0048, -0.0005]). But the allocate TRANSITION
    fired in 0 of 8 there. Allocator seats also enter the gap-fill rounds, and
    this benchmark does not separate the two.
- **BO proposer** (`planner.bo`, TPE, module defaults; proposals reach only
  the allocate pool).
  - Single-objective: identical to allocate alone on every cell, except bowl
    ×4, where the proposals changed the seats in one campaign.
  - Multi-objective: -0.0039 [-0.0080, +0.0002] against the default, which is
    no better than allocate alone. On `pareto_with_constraint` it cost
    certificates (2 → 0 of 8).
  - There is no measurable benefit here.
- **Run order** (randomization off; `drift`, `bowl`, `additive`).
  - Regret is unchanged everywhere except additive ×4 (+0.0045 [0, +0.011])
    and bowl ×4 (-0.0038 [-0.0125, +0.0019]).
  - Certificates on drift fall 10 → 4 of 16. On bowl and additive they RISE
    (8 and 3 → 14 and 6 of 16).
  - With zero drift a different order only reassigns noise draws, so those
    rises show how variable a certificate count of 8 seeds is.

**Practical guidance.**

| Situation | Use |
|---|---|
| Few knobs, smooth monotone or single-bump response, expensive runs, and an auditable answer is needed (a deploy decision, a paper) | **Nous**, declaring `scale: log` for geometric knobs. Expect parity with GP-BO on regret. The certificate, when issued, has been sound in every campaign here, but it is withheld far more often than before |
| Many knobs, few of which matter | Nous and GP-BO tie on regret at Nous's budget. GP-BO gets there with a fifth of the runs. Nous did not certify any of these campaigns at the current code |
| A drifting environment | Either. Randomized order buys certificates, not regret, on the one drift surface here |
| Noisy constraints | Nous, or any method that replicates its finalists |
| Response suspected multimodal, cliff-like or strongly non-polynomial | **GP-BO.** Nous now declines to certify there instead of certifying a wrong answer, but its answer is still the quadratic model's |
| Multiple objectives, front quality is what matters | **ParEGO** (or another model-based MO method). Nous's front is better than RS/LHS but worse than ParEGO at Nous's budget; Nous's advantage is the front certificate (0 false in 216) |
| Pure exploration of an unknown surface, no certificate needed | GP-BO, or LHS as a cheap space-filling first pass |

## Results: suite (seeds 1-8, noise ×1/×4)

<!-- BEGIN GENERATED suite -->
_Tables aggregated by `python -m benchmarks.optimization.run --workers 3 --cache-dir <cache-dir>` at checkout dc2d9de7e2ed3c076b1d90fe0f55123e573bd1cd (Nous 0.5.0); seeds [1, 2, 3, 4, 5, 6, 7, 8], noise multipliers [1.0, 4.0]. Rows come from the resume cache and record the code they were produced under: Nous source digest(s) ff14a3afe6e0fdb1; benchmark code digest(s) 47bc42e50f66cb60. Wall 60.3 min; peak RSS: largest worker 0.894 GB, parent 0.111 GB._

### PRIMARY (pre-declared): mean normalised regret difference, Nous minus baseline, per family

Normalised regret = regret / (f_best - f_worst admissible). Per seed: the mean over the family's cells; then the mean over seeds with a seeded percentile bootstrap (10000 resamples, seed 20261018) and the t interval. Negative favours Nous.

| family | baseline | seeds | mean [bootstrap 95%] | t 95% |
|---|---|---|---|---|
| shipped | RS | 8 | -0.1219 [-0.1522, -0.0849] | [-0.1652, -0.0786] |
| shipped | LHS | 8 | -0.0905 [-0.1012, -0.0734] | [-0.1096, -0.0714] |
| shipped | GP-BO | 8 | -0.0628 [-0.0723, -0.0453] | [-0.0831, -0.0426] |
| shipped | GP-BO-crude | 8 | -0.2661 [-0.2760, -0.2480] | [-0.2867, -0.2454] |
| non-quadratic | RS | 8 | 0.0071 [-0.0154, 0.0288] | [-0.0217, 0.0360] |
| non-quadratic | LHS | 8 | 0.0434 [0.0334, 0.0563] | [0.0286, 0.0581] |
| non-quadratic | GP-BO | 8 | -0.0196 [-0.0625, 0.0366] | [-0.0825, 0.0434] |
| non-quadratic | GP-BO-crude | 8 | -0.0335 [-0.0753, 0.0157] | [-0.0920, 0.0251] |
| many-knob sparse | RS | 8 | -0.0324 [-0.0417, -0.0232] | [-0.0441, -0.0206] |
| many-knob sparse | LHS | 8 | -0.0284 [-0.0387, -0.0192] | [-0.0410, -0.0157] |
| many-knob sparse | GP-BO | 8 | 0.0012 [0.0008, 0.0017] | [0.0007, 0.0017] |
| many-knob sparse | GP-BO-crude | 8 | -0.0035 [-0.0070, -0.0002] | [-0.0078, 0.0009] |

**Certification soundness:** nous: 50 certified of 336, **0 false**.

### Mean true regret per cell (lower is better)

| surface | noise | N | Nous | cert/false | RS (obs) | LHS (obs) | GP-BO (GP mean) | GP-BO-crude (GP mean) | RS (GP mean) | LHS (GP mean) | GP-BO (obs) | GP-BO-crude (obs) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 48 | 0.000 | 3/0 of 8 | 0.263 | 0.281 | 0.000 | 0.000 | 0.263 | 0.281 | 0.000 | 0.000 |
| additive | ×4 | 48 | 0.013 | 0/0 of 8 | 0.275 | 0.313 | 0.000 | 0.038 | 0.269 | 0.281 | 0.000 | 0.106 |
| interaction_only | ×1 | 38 | 0.000 | 0/0 of 8 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| interaction_only | ×4 | 38 | 0.000 | 0/0 of 8 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| bowl | ×1 | 44 | 0.000 | 4/0 of 8 | 0.075 | 0.075 | 0.000 | 0.000 | 0.069 | 0.075 | 0.006 | 0.000 |
| bowl | ×4 | 44 | 0.031 | 4/0 of 8 | 0.150 | 0.119 | 0.019 | 0.050 | 0.069 | 0.075 | 0.113 | 0.050 |
| bowl_centred | ×1 | 48 | 0.000 | 3/0 of 8 | 0.250 | 0.119 | 0.006 | 0.000 | 0.250 | 0.119 | 0.006 | 0.006 |
| bowl_centred | ×4 | 48 | 0.000 | 3/0 of 8 | 0.312 | 0.188 | 0.019 | 0.056 | 0.275 | 0.119 | 0.044 | 0.088 |
| saddle | ×1 | 44 | 0.000 | 1/0 of 8 | 0.119 | 0.113 | 0.000 | 0.000 | 0.119 | 0.113 | 0.006 | 0.000 |
| saddle | ×4 | 44 | 0.031 | 0/0 of 8 | 0.137 | 0.156 | 0.013 | 0.013 | 0.119 | 0.113 | 0.050 | 0.013 |
| choice_x_numeric | ×1 | 38 | 0.000 | 4/0 of 8 | 0.438 | 0.062 | 0.000 | 0.000 | 0.438 | 0.062 | 0.000 | 0.000 |
| choice_x_numeric | ×4 | 38 | 0.000 | 4/0 of 8 | 0.438 | 0.062 | 0.000 | 0.000 | 0.438 | 0.062 | 0.000 | 0.000 |
| drift | ×1 | 26 | 0.000 | 5/0 of 8 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| drift | ×4 | 26 | 0.000 | 5/0 of 8 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| sla | ×1 | 68 | 0.400 | 0/0 of 8 | 0.238 | 0.125 | 0.000 | 8.200 | 0.238 | 0.113 | 0.000 | 0.338 |
| sla | ×4 | 68 | 0.275 | 0/0 of 8 | 0.300 | 0.150 | 0.000 | 8.200 | 0.238 | 0.113 | 0.000 | 0.363 |
| infeasible_corner_interior | ×1 | 45 | 0.000 | 5/0 of 8 | 0.000 | 0.019 | 0.000 | 3.300 | 0.000 | 0.019 | 0.000 | 0.019 |
| infeasible_corner_interior | ×4 | 45 | 0.000 | 1/0 of 8 | 0.000 | 0.056 | 0.000 | 3.300 | 0.000 | 0.019 | 0.000 | 0.075 |
| nan_at_corner | ×1 | 8 | 0.000 | 0/0 of 8 | 1.400 | 0.000 | 0.000 | 0.000 | 1.400 | 0.000 | 0.000 | 0.000 |
| nan_at_corner | ×4 | 8 | 0.000 | 0/0 of 8 | 1.400 | 0.000 | 0.000 | 0.000 | 1.400 | 0.000 | 0.000 | 0.000 |
| fails_at_one_level | ×1 | 30 | 0.320 | 0/0 of 8 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 |
| fails_at_one_level | ×4 | 30 | 0.360 | 0/0 of 8 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 | 0.640 |
| stochastic_constraint_boundary | ×1 | 68 | 0.875 | 0/0 of 8 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 |
| stochastic_constraint_boundary | ×4 | 68 | 0.875 | 0/0 of 8 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 6.162 |
| geometric_knob | ×1 | 44 | 0.188 | 0/0 of 8 | 1.447 | 2.036 | 0.782 | 4.412 | 1.410 | 2.269 | 0.815 | 2.700 |
| geometric_knob | ×4 | 44 | 0.188 | 0/0 of 8 | 1.456 | 2.645 | 3.127 | 4.890 | 1.600 | 2.812 | 3.197 | 3.861 |
| geometric_knob_log | ×1 | 44 | 0.000 | 4/0 of 8 | 2.086 | 2.094 | 0.040 | 0.022 | 2.086 | 2.094 | 0.046 | 0.053 |
| geometric_knob_log | ×4 | 44 | 0.000 | 4/0 of 8 | 2.498 | 2.094 | 0.151 | 0.161 | 2.232 | 2.094 | 0.209 | 0.485 |
| deterministic_constraint_axis | ×1 | 57 | 0.000 | 0/0 of 8 | 2.156 | 1.918 | 0.000 | 8.100 | 2.156 | 1.918 | 0.000 | 0.355 |
| deterministic_constraint_axis | ×4 | 57 | 0.000 | 0/0 of 8 | 2.244 | 1.918 | 0.000 | 8.100 | 2.244 | 1.918 | 0.000 | 1.021 |
| step_cliff | ×1 | 44 | 0.400 | 0/0 of 8 | 0.400 | 0.212 | 0.112 | 0.587 | 0.400 | 0.212 | 0.112 | 0.350 |
| step_cliff | ×4 | 44 | 0.462 | 0/0 of 8 | 0.437 | 0.212 | 0.225 | 0.550 | 0.425 | 0.212 | 0.225 | 0.312 |
| ridge_cubic | ×1 | 48 | 0.220 | 0/0 of 8 | 0.117 | 0.076 | 0.000 | 0.014 | 0.092 | 0.076 | 0.000 | 0.014 |
| ridge_cubic | ×4 | 48 | 0.228 | 0/0 of 8 | 0.297 | 0.148 | 0.014 | 0.040 | 0.210 | 0.128 | 0.114 | 0.146 |
| two_peaks | ×1 | 44 | 1.263 | 0/0 of 8 | 1.161 | 0.883 | 1.990 | 1.776 | 1.197 | 0.932 | 1.990 | 1.785 |
| two_peaks | ×4 | 44 | 1.263 | 0/0 of 8 | 1.201 | 0.883 | 2.169 | 2.169 | 1.238 | 1.027 | 2.188 | 2.197 |
| sparse_knobs_6 | ×1 | 108 | 0.010 | 0/0 of 8 | 0.402 | 0.276 | 0.002 | 0.006 | 0.402 | 0.276 | 0.002 | 0.006 |
| sparse_knobs_6 | ×4 | 108 | 0.020 | 0/0 of 8 | 0.480 | 0.339 | 0.004 | 0.084 | 0.425 | 0.315 | 0.020 | 0.119 |
| sparse_knobs_8 | ×1 | 176 | 0.010 | 0/0 of 8 | 0.286 | 0.305 | 0.005 | 0.004 | 0.286 | 0.305 | 0.005 | 0.004 |
| sparse_knobs_8 | ×4 | 176 | 0.024 | 0/0 of 8 | 0.330 | 0.400 | 0.006 | 0.111 | 0.314 | 0.400 | 0.006 | 0.111 |
| sparse_knobs_12 | ×1 | 568 | 0.010 | 0/0 of 8 | 0.124 | 0.096 | 0.000 | 0.004 | 0.124 | 0.096 | 0.005 | 0.004 |
| sparse_knobs_12 | ×4 | 568 | 0.010 | 0/0 of 8 | 0.149 | 0.146 | 0.004 | 0.055 | 0.160 | 0.170 | 0.027 | 0.055 |

### 95% bootstrap intervals of the per-cell means (over seeds; primary rule for baselines)

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | [0.000, 0.000] | [0.125, 0.406] | [0.219, 0.350] | [0.000, 0.000] | [0.000, 0.000] |
| additive | ×4 | [0.000, 0.038] | [0.125, 0.431] | [0.250, 0.381] | [0.000, 0.000] | [0.013, 0.069] |
| interaction_only | ×1 | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| interaction_only | ×4 | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| bowl | ×1 | [0.000, 0.000] | [0.031, 0.131] | [0.038, 0.119] | [0.000, 0.000] | [0.000, 0.000] |
| bowl | ×4 | [0.000, 0.081] | [0.038, 0.306] | [0.081, 0.169] | [0.000, 0.044] | [0.013, 0.100] |
| bowl_centred | ×1 | [0.000, 0.000] | [0.069, 0.500] | [0.063, 0.181] | [0.000, 0.019] | [0.000, 0.000] |
| bowl_centred | ×4 | [0.000, 0.000] | [0.119, 0.562] | [0.113, 0.269] | [0.006, 0.038] | [0.038, 0.075] |
| saddle | ×1 | [0.000, 0.000] | [0.063, 0.181] | [0.038, 0.219] | [0.000, 0.000] | [0.000, 0.000] |
| saddle | ×4 | [0.000, 0.081] | [0.075, 0.181] | [0.069, 0.256] | [0.000, 0.031] | [0.000, 0.031] |
| choice_x_numeric | ×1 | [0.000, 0.000] | [0.125, 0.875] | [0.000, 0.188] | [0.000, 0.000] | [0.000, 0.000] |
| choice_x_numeric | ×4 | [0.000, 0.000] | [0.125, 0.875] | [0.000, 0.188] | [0.000, 0.000] | [0.000, 0.000] |
| drift | ×1 | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| drift | ×4 | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| sla | ×1 | [0.400, 0.400] | [0.150, 0.350] | [0.050, 0.200] | [0.000, 0.000] | [8.200, 8.200] |
| sla | ×4 | [0.225, 0.350] | [0.188, 0.463] | [0.063, 0.238] | [0.000, 0.000] | [8.200, 8.200] |
| infeasible_corner_interior | ×1 | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.056] | [0.000, 0.000] | [3.300, 3.300] |
| infeasible_corner_interior | ×4 | [0.000, 0.000] | [0.000, 0.000] | [0.019, 0.112] | [0.000, 0.000] | [3.300, 3.300] |
| nan_at_corner | ×1 | [0.000, 0.000] | [0.350, 2.450] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| nan_at_corner | ×4 | [0.000, 0.000] | [0.350, 2.450] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| fails_at_one_level | ×1 | [0.320, 0.320] | [0.640, 0.640] | [0.640, 0.640] | [0.640, 0.640] | [0.640, 0.640] |
| fails_at_one_level | ×4 | [0.320, 0.440] | [0.640, 0.640] | [0.640, 0.640] | [0.640, 0.640] | [0.640, 0.640] |
| stochastic_constraint_boundary | ×1 | [0.000, 2.625] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] |
| stochastic_constraint_boundary | ×4 | [0.000, 2.625] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] |
| geometric_knob | ×1 | [0.188, 0.188] | [0.887, 2.018] | [1.043, 3.273] | [0.393, 1.225] | [3.098, 5.969] |
| geometric_knob | ×4 | [0.188, 0.188] | [0.891, 2.036] | [1.408, 3.973] | [1.865, 4.615] | [3.645, 6.277] |
| geometric_knob_log | ×1 | [0.000, 0.000] | [0.789, 3.580] | [1.037, 3.366] | [0.014, 0.072] | [0.006, 0.041] |
| geometric_knob_log | ×4 | [0.000, 0.000] | [1.312, 3.771] | [1.037, 3.366] | [0.080, 0.240] | [0.061, 0.285] |
| deterministic_constraint_axis | ×1 | [0.000, 0.000] | [1.462, 2.831] | [1.516, 2.305] | [0.000, 0.000] | [8.100, 8.100] |
| deterministic_constraint_axis | ×4 | [0.000, 0.000] | [1.525, 2.912] | [1.516, 2.305] | [0.000, 0.000] | [8.100, 8.100] |
| step_cliff | ×1 | [0.400, 0.400] | [0.250, 0.562] | [0.125, 0.300] | [0.000, 0.262] | [0.437, 0.737] |
| step_cliff | ×4 | [0.400, 0.587] | [0.312, 0.575] | [0.125, 0.300] | [0.075, 0.412] | [0.425, 0.687] |
| ridge_cubic | ×1 | [0.220, 0.220] | [0.065, 0.175] | [0.034, 0.110] | [0.000, 0.000] | [0.003, 0.024] |
| ridge_cubic | ×4 | [0.138, 0.327] | [0.247, 0.364] | [0.076, 0.225] | [0.003, 0.024] | [0.007, 0.085] |
| two_peaks | ×1 | [1.263, 1.263] | [0.746, 1.545] | [0.608, 1.092] | [0.995, 2.653] | [0.899, 2.439] |
| two_peaks | ×4 | [1.263, 1.263] | [0.786, 1.575] | [0.608, 1.092] | [1.478, 2.690] | [1.487, 2.690] |
| sparse_knobs_6 | ×1 | [0.010, 0.010] | [0.275, 0.495] | [0.144, 0.430] | [0.000, 0.006] | [0.002, 0.010] |
| sparse_knobs_6 | ×4 | [0.010, 0.040] | [0.315, 0.625] | [0.185, 0.502] | [0.001, 0.007] | [0.024, 0.154] |
| sparse_knobs_8 | ×1 | [0.010, 0.010] | [0.152, 0.424] | [0.126, 0.489] | [0.001, 0.009] | [0.001, 0.007] |
| sparse_knobs_8 | ×4 | [0.010, 0.051] | [0.181, 0.476] | [0.205, 0.589] | [0.002, 0.010] | [0.024, 0.221] |
| sparse_knobs_12 | ×1 | [0.010, 0.010] | [0.044, 0.222] | [0.050, 0.140] | [0.000, 0.000] | [0.001, 0.007] |
| sparse_knobs_12 | ×4 | [0.010, 0.010] | [0.044, 0.275] | [0.091, 0.200] | [0.001, 0.007] | [0.009, 0.107] |

### Head-to-head (Nous better / tie / worse), every cell pooled

| baseline | rule | exact tie | tie = within Nous's ε |
|---|---|---|---|
| RS | best_observed | 200 / 93 / 43 | 101 / 226 / 9 |
| RS | gp_mean | 199 / 93 / 44 | 97 / 229 / 10 |
| LHS | best_observed | 183 / 92 / 61 | 79 / 233 / 24 |
| LHS | gp_mean | 179 / 95 / 62 | 79 / 235 / 22 |
| GP-BO | best_observed | 98 / 164 / 74 | 47 / 263 / 26 |
| GP-BO | gp_mean | 83 / 166 / 87 | 46 / 264 / 26 |
| GP-BO-crude | best_observed | 130 / 147 / 59 | 66 / 255 / 15 |
| GP-BO-crude | gp_mean | 157 / 132 / 47 | 107 / 223 / 6 |

### Head-to-head by surface family (primary rule)

| family | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|
| shipped (exact) | 144 / 80 / 16 | 141 / 85 / 14 | 66 / 151 / 23 | 125 / 112 / 3 |
| shipped (within ε) | 84 / 156 / 0 | 69 / 167 / 4 | 34 / 195 / 11 | 91 / 149 / 0 |
| non-quadratic (exact) | 18 / 9 / 21 | 2 / 6 / 40 | 17 / 0 / 31 | 21 / 3 / 24 |
| non-quadratic (within ε) | 7 / 32 / 9 | 1 / 27 / 20 | 12 / 21 / 15 | 16 / 26 / 6 |
| many-knob sparse (exact) | 38 / 4 / 6 | 40 / 1 / 7 | 0 / 15 / 33 | 11 / 17 / 20 |
| many-knob sparse (within ε) | 10 / 38 / 0 | 9 / 39 / 0 | 0 / 48 / 0 | 0 / 48 / 0 |

### Wilson 95% intervals on the pooled head-to-head proportions (primary rule)

Conditional on THESE surfaces and noise levels: each campaign is one trial, the surfaces are a fixed, non-random selection, and campaigns of one cell are not independent of each other's surface. The interval says nothing about other surfaces.

| baseline | n | P(Nous better), exact | P(Nous worse), exact | P(better), within ε | P(worse), within ε |
|---|---|---|---|---|---|
| RS | 336 | 0.60 [0.54, 0.65] | 0.13 [0.10, 0.17] | 0.30 [0.25, 0.35] | 0.03 [0.01, 0.05] |
| LHS | 336 | 0.54 [0.49, 0.60] | 0.18 [0.14, 0.23] | 0.24 [0.19, 0.28] | 0.07 [0.05, 0.10] |
| GP-BO | 336 | 0.25 [0.20, 0.30] | 0.26 [0.22, 0.31] | 0.14 [0.10, 0.18] | 0.08 [0.05, 0.11] |
| GP-BO-crude | 336 | 0.47 [0.41, 0.52] | 0.14 [0.11, 0.18] | 0.32 [0.27, 0.37] | 0.02 [0.01, 0.04] |

### Anytime regret (mean normalised regret at fractions of N, bootstrap 95% over seeds)

Nous: the best-so-far always-admissible measured configuration after its first n runs (its campaign is NOT stopped there: this is where its run sequence stands). Baselines: their primary-rule pick on the prefix of their own measurements. N is Nous's own stopping budget.

| family | method | 10% N | 20% N | 40% N | 60% N | 80% N | 100% N |
|---|---|---|---|---|---|---|---|
| shipped | Nous | 0.194 [0.178, 0.219] | 0.130 [0.113, 0.155] | 0.144 [0.119, 0.162] | 0.040 [0.031, 0.058] | 0.034 [0.017, 0.059] | 0.018 [0.009, 0.035] |
| shipped | RS | 0.300 [0.271, 0.331] | 0.204 [0.172, 0.231] | 0.174 [0.150, 0.199] | 0.152 [0.132, 0.172] | 0.144 [0.121, 0.167] | 0.140 [0.117, 0.162] |
| shipped | LHS | 0.288 [0.247, 0.331] | 0.234 [0.204, 0.264] | 0.171 [0.150, 0.193] | 0.128 [0.102, 0.149] | 0.123 [0.113, 0.136] | 0.108 [0.105, 0.112] |
| shipped | GP-BO | 0.284 [0.261, 0.308] | 0.150 [0.129, 0.169] | 0.116 [0.095, 0.136] | 0.083 [0.082, 0.084] | 0.081 [0.081, 0.082] | 0.081 [0.080, 0.081] |
| shipped | GP-BO-crude | 0.390 [0.335, 0.444] | 0.337 [0.311, 0.365] | 0.300 [0.284, 0.320] | 0.291 [0.283, 0.304] | 0.291 [0.283, 0.304] | 0.284 [0.283, 0.285] |
| non-quadratic | Nous | 0.282 [0.282, 0.282] | 0.282 [0.282, 0.282] | 0.249 [0.249, 0.249] | 0.120 [0.117, 0.125] | 0.116 [0.112, 0.120] | 0.116 [0.112, 0.120] |
| non-quadratic | RS | 0.278 [0.223, 0.329] | 0.210 [0.168, 0.259] | 0.166 [0.128, 0.201] | 0.147 [0.114, 0.182] | 0.106 [0.077, 0.131] | 0.110 [0.085, 0.134] |
| non-quadratic | LHS | 0.273 [0.210, 0.319] | 0.200 [0.152, 0.249] | 0.144 [0.108, 0.178] | 0.101 [0.083, 0.122] | 0.090 [0.080, 0.100] | 0.074 [0.060, 0.087] |
| non-quadratic | GP-BO | 0.298 [0.242, 0.339] | 0.254 [0.217, 0.279] | 0.157 [0.113, 0.188] | 0.144 [0.098, 0.178] | 0.137 [0.084, 0.178] | 0.137 [0.084, 0.178] |
| non-quadratic | GP-BO-crude | 0.281 [0.211, 0.346] | 0.192 [0.152, 0.229] | 0.163 [0.123, 0.197] | 0.152 [0.108, 0.191] | 0.153 [0.106, 0.193] | 0.151 [0.104, 0.191] |
| many-knob sparse | Nous | 0.066 [0.066, 0.066] | 0.066 [0.066, 0.066] | 0.066 [0.066, 0.066] | 0.066 [0.066, 0.066] | 0.066 [0.066, 0.066] | 0.002 [0.001, 0.002] |
| many-knob sparse | RS | 0.123 [0.097, 0.147] | 0.089 [0.066, 0.110] | 0.050 [0.034, 0.067] | 0.044 [0.031, 0.060] | 0.041 [0.029, 0.054] | 0.034 [0.025, 0.044] |
| many-knob sparse | LHS | 0.121 [0.109, 0.132] | 0.087 [0.067, 0.107] | 0.059 [0.046, 0.073] | 0.040 [0.033, 0.049] | 0.034 [0.026, 0.042] | 0.030 [0.021, 0.040] |
| many-knob sparse | GP-BO | 0.073 [0.057, 0.089] | 0.004 [0.003, 0.005] | 0.001 [0.000, 0.002] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.000 [0.000, 0.001] |
| many-knob sparse | GP-BO-crude | 0.053 [0.039, 0.067] | 0.013 [0.010, 0.017] | 0.007 [0.005, 0.010] | 0.004 [0.003, 0.006] | 0.006 [0.003, 0.008] | 0.005 [0.002, 0.008] |

### Median CPU seconds per campaign

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | 0.21 | 0.01 | 0.01 | 0.13 | 0.02 |
| additive | ×4 | 0.21 | 0.01 | 0.01 | 0.13 | 0.02 |
| interaction_only | ×1 | 0.15 | 0.01 | 0.01 | 0.06 | 0.00 |
| interaction_only | ×4 | 0.15 | 0.01 | 0.01 | 0.05 | 0.00 |
| bowl | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| bowl | ×4 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| bowl_centred | ×1 | 0.20 | 0.01 | 0.01 | 0.15 | 0.02 |
| bowl_centred | ×4 | 0.21 | 0.01 | 0.01 | 0.14 | 0.02 |
| saddle | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| saddle | ×4 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| choice_x_numeric | ×1 | 0.19 | 0.01 | 0.01 | 0.06 | 0.01 |
| choice_x_numeric | ×4 | 0.19 | 0.01 | 0.01 | 0.06 | 0.01 |
| drift | ×1 | 0.14 | 0.00 | 0.00 | 0.03 | 0.00 |
| drift | ×4 | 0.14 | 0.00 | 0.00 | 0.03 | 0.00 |
| sla | ×1 | 0.27 | 0.01 | 0.02 | 0.30 | 0.02 |
| sla | ×4 | 0.27 | 0.02 | 0.02 | 0.30 | 0.02 |
| infeasible_corner_interior | ×1 | 0.21 | 0.01 | 0.01 | 0.13 | 0.01 |
| infeasible_corner_interior | ×4 | 0.21 | 0.01 | 0.01 | 0.13 | 0.01 |
| nan_at_corner | ×1 | 0.06 | 0.00 | 0.00 | 0.01 | 0.00 |
| nan_at_corner | ×4 | 0.06 | 0.00 | 0.00 | 0.01 | 0.00 |
| fails_at_one_level | ×1 | 0.14 | 0.01 | 0.01 | 0.04 | 0.00 |
| fails_at_one_level | ×4 | 0.14 | 0.01 | 0.01 | 0.04 | 0.00 |
| stochastic_constraint_boundary | ×1 | 0.28 | 0.02 | 0.01 | 0.29 | 0.02 |
| stochastic_constraint_boundary | ×4 | 0.28 | 0.01 | 0.02 | 0.30 | 0.02 |
| geometric_knob | ×1 | 0.21 | 0.04 | 0.04 | 216.79 | 5.93 |
| geometric_knob | ×4 | 0.21 | 0.04 | 0.04 | 215.93 | 5.94 |
| geometric_knob_log | ×1 | 0.20 | 0.04 | 0.04 | 216.50 | 5.95 |
| geometric_knob_log | ×4 | 0.20 | 0.04 | 0.04 | 216.57 | 5.95 |
| deterministic_constraint_axis | ×1 | 0.27 | 0.01 | 0.01 | 1.08 | 0.41 |
| deterministic_constraint_axis | ×4 | 0.27 | 0.02 | 0.01 | 1.07 | 0.41 |
| step_cliff | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| step_cliff | ×4 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| ridge_cubic | ×1 | 0.21 | 0.01 | 0.01 | 0.14 | 0.02 |
| ridge_cubic | ×4 | 0.21 | 0.01 | 0.01 | 0.14 | 0.02 |
| two_peaks | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| two_peaks | ×4 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| sparse_knobs_6 | ×1 | 1.31 | 0.06 | 0.06 | 2.62 | 1.84 |
| sparse_knobs_6 | ×4 | 1.56 | 0.06 | 0.05 | 2.58 | 1.83 |
| sparse_knobs_8 | ×1 | 10.35 | 0.16 | 0.15 | 5.95 | 5.06 |
| sparse_knobs_8 | ×4 | 12.96 | 0.15 | 0.14 | 5.89 | 5.10 |
| sparse_knobs_12 | ×1 | 37.48 | 2.89 | 3.24 | 80.60 | 80.31 |
| sparse_knobs_12 | ×4 | 37.98 | 3.05 | 3.05 | 82.04 | 80.12 |

### Why uncertified campaigns were withheld (reasons per campaign; one campaign can carry several)

| family | reason | campaigns |
|---|---|---|
| shipped | `noise_skewed` | 62 |
| shipped | `model_inadequate` | 48 |
| shipped | `model_recommendation_infeasible` | 44 |
| shipped | `model_bound_above_epsilon` | 36 |
| shipped | `shortlist_refilled` | 32 |
| shipped | `finalist_measured_infeasible` | 32 |
| shipped | `no_terminal_discrimination` | 16 |
| shipped | `bound_not_computable` | 16 |
| shipped | `finalist_unmeasured` | 16 |
| shipped | `fit_exclusions_level_correlated` | 16 |
| shipped | `model_recommendation_not_compared` | 14 |
| shipped | `no_feasible_rival` | 13 |
| shipped | `bound_above_epsilon` | 9 |
| shipped | `heteroscedastic_pure_error` | 4 |
| shipped | `no_admissible_finalist` | 3 |
| non-quadratic | `model_inadequate` | 44 |
| non-quadratic | `noise_skewed` | 14 |
| non-quadratic | `model_bound_above_epsilon` | 4 |
| non-quadratic | `bound_above_epsilon` | 1 |
| many-knob sparse | `model_bound_above_epsilon` | 42 |
| many-knob sparse | `noise_skewed` | 12 |
| many-knob sparse | `model_inadequate` | 6 |
| many-knob sparse | `heteroscedastic_pure_error` | 2 |

_GP-BO had to re-pick an only-failed configuration 0 time(s) (every candidate had failed)._
<!-- END GENERATED suite -->


## Results: audit reproduction (the audit's 9 surfaces, seeds 1-20, noise ×1/×8)

<!-- BEGIN GENERATED audit-repro -->
_Tables aggregated by `python -m benchmarks.optimization.run --audit-repro --workers 3 --cache-dir <cache-dir>` at checkout bf5a282dcc5fdee6432500207ff832059a42daaf (Nous 0.5.0); seeds [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], noise multipliers [1.0, 8.0]. Rows come from the resume cache and record the code they were produced under: Nous source digest(s) ff14a3afe6e0fdb1; benchmark code digest(s) 47bc42e50f66cb60. Wall 50.3 min; peak RSS: largest worker 0.141 GB, parent 0.112 GB._

### PRIMARY (pre-declared): mean normalised regret difference, Nous minus baseline, per family

Normalised regret = regret / (f_best - f_worst admissible). Per seed: the mean over the family's cells; then the mean over seeds with a seeded percentile bootstrap (10000 resamples, seed 20261018) and the t interval. Negative favours Nous.

| family | baseline | seeds | mean [bootstrap 95%] | t 95% |
|---|---|---|---|---|
| shipped | RS | 20 | -0.0316 [-0.0385, -0.0253] | [-0.0389, -0.0243] |
| shipped | LHS | 20 | -0.0290 [-0.0326, -0.0251] | [-0.0330, -0.0249] |
| shipped | GP-BO | 20 | -0.0058 [-0.0079, -0.0036] | [-0.0081, -0.0034] |
| shipped | GP-BO-crude | 20 | -0.0165 [-0.0211, -0.0125] | [-0.0214, -0.0117] |
| non-quadratic | RS | 20 | 0.0015 [-0.0206, 0.0236] | [-0.0231, 0.0261] |
| non-quadratic | LHS | 20 | 0.0287 [0.0052, 0.0510] | [0.0037, 0.0537] |
| non-quadratic | GP-BO | 20 | -0.0242 [-0.0471, 0.0024] | [-0.0518, 0.0033] |
| non-quadratic | GP-BO-crude | 20 | -0.0445 [-0.0685, -0.0171] | [-0.0732, -0.0159] |

**Certification soundness:** nous: 60 certified of 360, **0 false**.

### Mean true regret per cell (lower is better)

| surface | noise | N | Nous | cert/false | RS (obs) | LHS (obs) | GP-BO (GP mean) | GP-BO-crude (GP mean) | RS (GP mean) | LHS (GP mean) | GP-BO (obs) | GP-BO-crude (obs) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 48 | 0.000 | 8/0 of 20 | 0.255 | 0.205 | 0.000 | 0.000 | 0.255 | 0.205 | 0.000 | 0.000 |
| additive | ×8 | 48 | 0.063 | 0/0 of 20 | 0.368 | 0.373 | 0.030 | 0.120 | 0.295 | 0.233 | 0.113 | 0.170 |
| bowl | ×1 | 44 | 0.000 | 11/0 of 20 | 0.070 | 0.078 | 0.003 | 0.000 | 0.065 | 0.078 | 0.008 | 0.003 |
| bowl | ×8 | 44 | 0.010 | 2/0 of 20 | 0.178 | 0.353 | 0.068 | 0.085 | 0.068 | 0.095 | 0.135 | 0.135 |
| bowl_centred | ×1 | 48 | 0.000 | 8/0 of 20 | 0.180 | 0.113 | 0.005 | 0.000 | 0.178 | 0.113 | 0.010 | 0.003 |
| bowl_centred | ×8 | 48 | 0.040 | 3/0 of 20 | 0.327 | 0.275 | 0.058 | 0.138 | 0.210 | 0.143 | 0.123 | 0.218 |
| saddle | ×1 | 44 | 0.000 | 3/0 of 20 | 0.172 | 0.103 | 0.000 | 0.000 | 0.172 | 0.103 | 0.003 | 0.000 |
| saddle | ×8 | 44 | 0.045 | 0/0 of 20 | 0.292 | 0.222 | 0.035 | 0.048 | 0.197 | 0.148 | 0.065 | 0.105 |
| choice_x_numeric | ×1 | 38 | 0.000 | 13/0 of 20 | 0.250 | 0.100 | 0.000 | 0.000 | 0.250 | 0.100 | 0.000 | 0.000 |
| choice_x_numeric | ×8 | 38 | 0.025 | 12/0 of 20 | 0.325 | 0.150 | 0.000 | 0.000 | 0.250 | 0.100 | 0.000 | 0.025 |
| geometric_knob | ×1 | 44 | 0.188 | 0/0 of 20 | 1.824 | 2.221 | 0.709 | 5.767 | 1.882 | 2.513 | 0.743 | 4.046 |
| geometric_knob | ×8 | 44 | 0.188 | 0/0 of 20 | 2.765 | 3.099 | 4.059 | 5.478 | 3.122 | 2.956 | 4.135 | 4.915 |
| step_cliff | ×1 | 44 | 0.400 | 0/0 of 20 | 0.330 | 0.235 | 0.105 | 0.570 | 0.325 | 0.235 | 0.105 | 0.350 |
| step_cliff | ×8 | 44 | 0.555 | 0/0 of 20 | 0.435 | 0.420 | 0.290 | 0.695 | 0.475 | 0.370 | 0.305 | 0.695 |
| ridge_cubic | ×1 | 48 | 0.220 | 0/0 of 20 | 0.116 | 0.091 | 0.000 | 0.017 | 0.095 | 0.088 | 0.000 | 0.011 |
| ridge_cubic | ×8 | 48 | 0.300 | 0/0 of 20 | 0.377 | 0.325 | 0.058 | 0.148 | 0.242 | 0.233 | 0.199 | 0.287 |
| two_peaks | ×1 | 44 | 1.263 | 0/0 of 20 | 1.297 | 0.947 | 2.122 | 2.146 | 1.313 | 0.966 | 2.122 | 2.108 |
| two_peaks | ×8 | 44 | 1.263 | 0/0 of 20 | 1.362 | 1.023 | 2.252 | 2.077 | 1.566 | 1.227 | 2.249 | 2.166 |

### 95% bootstrap intervals of the per-cell means (over seeds; primary rule for baselines)

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | [0.000, 0.000] | [0.168, 0.345] | [0.153, 0.258] | [0.000, 0.000] | [0.000, 0.000] |
| additive | ×8 | [0.030, 0.105] | [0.250, 0.495] | [0.280, 0.475] | [0.000, 0.060] | [0.068, 0.180] |
| bowl | ×1 | [0.000, 0.000] | [0.050, 0.095] | [0.055, 0.105] | [0.000, 0.008] | [0.000, 0.000] |
| bowl | ×8 | [0.000, 0.030] | [0.105, 0.260] | [0.243, 0.470] | [0.030, 0.115] | [0.063, 0.110] |
| bowl_centred | ×1 | [0.000, 0.000] | [0.090, 0.295] | [0.078, 0.150] | [0.000, 0.013] | [0.000, 0.000] |
| bowl_centred | ×8 | [0.010, 0.080] | [0.200, 0.470] | [0.185, 0.382] | [0.043, 0.073] | [0.095, 0.183] |
| saddle | ×1 | [0.000, 0.000] | [0.090, 0.272] | [0.053, 0.165] | [0.000, 0.000] | [0.000, 0.000] |
| saddle | ×8 | [0.015, 0.082] | [0.163, 0.450] | [0.125, 0.335] | [0.018, 0.058] | [0.020, 0.080] |
| choice_x_numeric | ×1 | [0.000, 0.000] | [0.075, 0.450] | [0.025, 0.200] | [0.000, 0.000] | [0.000, 0.000] |
| choice_x_numeric | ×8 | [0.000, 0.075] | [0.125, 0.550] | [0.050, 0.275] | [0.000, 0.000] | [0.000, 0.000] |
| geometric_knob | ×1 | [0.188, 0.188] | [1.306, 2.362] | [1.370, 3.214] | [0.522, 0.905] | [4.437, 7.480] |
| geometric_knob | ×8 | [0.188, 0.188] | [1.856, 3.729] | [2.015, 4.306] | [2.868, 5.299] | [3.882, 7.399] |
| step_cliff | ×1 | [0.400, 0.400] | [0.220, 0.440] | [0.160, 0.315] | [0.030, 0.195] | [0.475, 0.665] |
| step_cliff | ×8 | [0.450, 0.665] | [0.280, 0.595] | [0.280, 0.570] | [0.185, 0.395] | [0.480, 0.930] |
| ridge_cubic | ×1 | [0.220, 0.220] | [0.083, 0.151] | [0.063, 0.121] | [0.000, 0.000] | [0.011, 0.022] |
| ridge_cubic | ×8 | [0.214, 0.385] | [0.313, 0.444] | [0.249, 0.417] | [0.026, 0.096] | [0.090, 0.213] |
| two_peaks | ×1 | [1.263, 1.263] | [0.993, 1.613] | [0.643, 1.289] | [1.592, 2.520] | [1.723, 2.520] |
| two_peaks | ×8 | [1.263, 1.263] | [1.032, 1.706] | [0.674, 1.410] | [1.861, 2.574] | [1.546, 2.554] |

### Head-to-head (Nous better / tie / worse), every cell pooled

| baseline | rule | exact tie | tie = within Nous's ε |
|---|---|---|---|
| RS | best_observed | 229 / 58 / 73 | 91 / 234 / 35 |
| RS | gp_mean | 223 / 57 / 80 | 85 / 238 / 37 |
| LHS | best_observed | 213 / 56 / 91 | 75 / 236 / 49 |
| LHS | gp_mean | 207 / 59 / 94 | 53 / 266 / 41 |
| GP-BO | best_observed | 133 / 136 / 91 | 50 / 271 / 39 |
| GP-BO | gp_mean | 112 / 149 / 99 | 43 / 275 / 42 |
| GP-BO-crude | best_observed | 157 / 131 / 72 | 77 / 260 / 23 |
| GP-BO-crude | gp_mean | 154 / 136 / 70 | 79 / 258 / 23 |

### Head-to-head by surface family (primary rule)

| family | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|
| shipped (exact) | 185 / 45 / 10 | 186 / 47 / 7 | 71 / 146 / 23 | 94 / 134 / 12 |
| shipped (within ε) | 70 / 169 / 1 | 60 / 179 / 1 | 12 / 227 / 1 | 37 / 201 / 2 |
| non-quadratic (exact) | 44 / 13 / 63 | 27 / 9 / 84 | 41 / 3 / 76 | 60 / 2 / 58 |
| non-quadratic (within ε) | 21 / 65 / 34 | 15 / 57 / 48 | 31 / 48 / 41 | 42 / 57 / 21 |
| many-knob sparse (exact) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| many-knob sparse (within ε) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

### Wilson 95% intervals on the pooled head-to-head proportions (primary rule)

Conditional on THESE surfaces and noise levels: each campaign is one trial, the surfaces are a fixed, non-random selection, and campaigns of one cell are not independent of each other's surface. The interval says nothing about other surfaces.

| baseline | n | P(Nous better), exact | P(Nous worse), exact | P(better), within ε | P(worse), within ε |
|---|---|---|---|---|---|
| RS | 360 | 0.64 [0.59, 0.68] | 0.20 [0.16, 0.25] | 0.25 [0.21, 0.30] | 0.10 [0.07, 0.13] |
| LHS | 360 | 0.59 [0.54, 0.64] | 0.25 [0.21, 0.30] | 0.21 [0.17, 0.25] | 0.14 [0.10, 0.18] |
| GP-BO | 360 | 0.31 [0.27, 0.36] | 0.28 [0.23, 0.32] | 0.12 [0.09, 0.16] | 0.12 [0.09, 0.15] |
| GP-BO-crude | 360 | 0.43 [0.38, 0.48] | 0.19 [0.16, 0.24] | 0.22 [0.18, 0.27] | 0.06 [0.04, 0.09] |

### Anytime regret (mean normalised regret at fractions of N, bootstrap 95% over seeds)

Nous: the best-so-far always-admissible measured configuration after its first n runs (its campaign is NOT stopped there: this is where its run sequence stands). Baselines: their primary-rule pick on the prefix of their own measurements. N is Nous's own stopping budget.

| family | method | 10% N | 20% N | 40% N | 60% N | 80% N | 100% N |
|---|---|---|---|---|---|---|---|
| shipped | Nous | 0.103 [0.102, 0.104] | 0.103 [0.102, 0.104] | 0.077 [0.076, 0.078] | 0.015 [0.013, 0.016] | 0.004 [0.002, 0.005] | 0.002 [0.002, 0.003] |
| shipped | RS | 0.177 [0.155, 0.203] | 0.100 [0.087, 0.114] | 0.061 [0.053, 0.070] | 0.046 [0.039, 0.053] | 0.039 [0.032, 0.047] | 0.034 [0.028, 0.041] |
| shipped | LHS | 0.178 [0.153, 0.205] | 0.101 [0.087, 0.116] | 0.058 [0.049, 0.068] | 0.046 [0.040, 0.052] | 0.038 [0.034, 0.043] | 0.032 [0.028, 0.035] |
| shipped | GP-BO | 0.167 [0.151, 0.184] | 0.057 [0.049, 0.064] | 0.026 [0.022, 0.031] | 0.014 [0.011, 0.016] | 0.010 [0.008, 0.012] | 0.009 [0.007, 0.010] |
| shipped | GP-BO-crude | 0.156 [0.135, 0.177] | 0.045 [0.037, 0.053] | 0.024 [0.019, 0.029] | 0.021 [0.017, 0.025] | 0.020 [0.016, 0.024] | 0.019 [0.016, 0.024] |
| non-quadratic | Nous | 0.282 [0.282, 0.282] | 0.285 [0.282, 0.288] | 0.250 [0.249, 0.252] | 0.126 [0.122, 0.131] | 0.121 [0.116, 0.126] | 0.120 [0.116, 0.124] |
| non-quadratic | RS | 0.290 [0.261, 0.318] | 0.226 [0.200, 0.255] | 0.188 [0.168, 0.208] | 0.161 [0.139, 0.182] | 0.130 [0.107, 0.154] | 0.121 [0.098, 0.145] |
| non-quadratic | LHS | 0.282 [0.244, 0.317] | 0.216 [0.189, 0.242] | 0.160 [0.133, 0.187] | 0.125 [0.100, 0.153] | 0.111 [0.088, 0.136] | 0.094 [0.074, 0.116] |
| non-quadratic | GP-BO | 0.306 [0.279, 0.331] | 0.262 [0.240, 0.280] | 0.180 [0.161, 0.195] | 0.157 [0.133, 0.178] | 0.150 [0.123, 0.173] | 0.147 [0.120, 0.170] |
| non-quadratic | GP-BO-crude | 0.288 [0.251, 0.323] | 0.225 [0.203, 0.246] | 0.186 [0.161, 0.209] | 0.178 [0.153, 0.200] | 0.169 [0.142, 0.193] | 0.167 [0.140, 0.191] |

### Median CPU seconds per campaign

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | 0.21 | 0.01 | 0.01 | 0.13 | 0.02 |
| additive | ×8 | 0.21 | 0.01 | 0.01 | 0.13 | 0.02 |
| bowl | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| bowl | ×8 | 0.21 | 0.01 | 0.01 | 0.09 | 0.01 |
| bowl_centred | ×1 | 0.21 | 0.01 | 0.01 | 0.15 | 0.02 |
| bowl_centred | ×8 | 0.21 | 0.01 | 0.01 | 0.14 | 0.02 |
| saddle | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| saddle | ×8 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| choice_x_numeric | ×1 | 0.20 | 0.01 | 0.01 | 0.06 | 0.00 |
| choice_x_numeric | ×8 | 0.20 | 0.01 | 0.01 | 0.06 | 0.00 |
| geometric_knob | ×1 | 0.20 | 0.04 | 0.04 | 216.19 | 5.78 |
| geometric_knob | ×8 | 0.20 | 0.04 | 0.04 | 210.95 | 5.78 |
| step_cliff | ×1 | 0.21 | 0.01 | 0.01 | 0.10 | 0.01 |
| step_cliff | ×8 | 0.21 | 0.01 | 0.01 | 0.09 | 0.01 |
| ridge_cubic | ×1 | 0.21 | 0.01 | 0.01 | 0.15 | 0.01 |
| ridge_cubic | ×8 | 0.21 | 0.01 | 0.01 | 0.13 | 0.02 |
| two_peaks | ×1 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| two_peaks | ×8 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |

### Why uncertified campaigns were withheld (reasons per campaign; one campaign can carry several)

| family | reason | campaigns |
|---|---|---|
| shipped | `model_inadequate` | 86 |
| shipped | `model_bound_above_epsilon` | 65 |
| shipped | `noise_skewed` | 64 |
| shipped | `bound_above_epsilon` | 45 |
| non-quadratic | `model_inadequate` | 85 |
| non-quadratic | `model_bound_above_epsilon` | 35 |
| non-quadratic | `noise_skewed` | 32 |
| non-quadratic | `bound_above_epsilon` | 18 |

_GP-BO had to re-pick an only-failed configuration 0 time(s) (every candidate had failed)._
<!-- END GENERATED audit-repro -->


## Results: ablations (D4; seeds 1-8, noise ×1/×4)

<!-- BEGIN GENERATED ablations -->
_Generated by `python -m benchmarks.optimization.run --ablations --workers 3 --cache-dir <cache-dir>` at checkout bf5a282dcc5fdee6432500207ff832059a42daaf; seeds [1, 2, 3, 4, 5, 6, 7, 8], noise [1.0, 4.0]; Nous digest(s) ff14a3afe6e0fdb1, benchmark digest 47bc42e50f66cb60. Wall 0.4 min; peak RSS: largest worker 0.145 GB, parent 0.105 GB._

### Ablations: each arm against the default on the same seeds

Δ = mean paired normalised regret, arm minus default, bootstrap 95% over seeds; negative favours the arm. N = mean runs. cert/false per arm.

**nous+alloc** — design.confirm.allocate: {seats: 2} (WP-D D1), confirm replicates at the raised floor.

Over its 112 campaigns: mean runs 45.1 (default) → 52.3 (arm); certified 20 → 12; false certificates 0 → 0. Pooled Δ by family: shipped -0.0012 [-0.0032, 0.0000]; non-quadratic 0.0001 [0.0000, 0.0004].

| surface | noise | n | regret default → arm | Δ [95%] | N default → arm | cert/false default | cert/false arm | allocate fired |
|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 48.0 → 51.0 | 3/0 | 4/0 | 0 |
| additive | ×4 | 8 | 0.013 → 0.000 | -0.0023 [-0.0068, 0.0000] | 48.0 → 66.8 | 0/0 | 0/0 | 6 |
| bowl | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 4/0 | 2/0 | 0 |
| bowl | ×4 | 8 | 0.031 → 0.006 | -0.0038 [-0.0115, 0.0000] | 44.0 → 47.0 | 4/0 | 2/0 | 0 |
| saddle | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 62.8 | 1/0 | 0/0 | 6 |
| saddle | ×4 | 8 | 0.031 → 0.006 | -0.0038 [-0.0115, 0.0000] | 44.0 → 62.8 | 0/0 | 0/0 | 6 |
| geometric_knob_log | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 4/0 | 2/0 | 0 |
| geometric_knob_log | ×4 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 4/0 | 2/0 | 0 |
| step_cliff | ×1 | 8 | 0.400 → 0.400 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| step_cliff | ×4 | 8 | 0.462 → 0.462 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| ridge_cubic | ×1 | 8 | 0.220 → 0.220 | 0.0000 [0.0000, 0.0000] | 48.0 → 51.0 | 0/0 | 0/0 | 0 |
| ridge_cubic | ×4 | 8 | 0.228 → 0.232 | 0.0009 [0.0000, 0.0027] | 48.0 → 61.5 | 0/0 | 0/0 | 4 |
| two_peaks | ×1 | 8 | 1.263 → 1.263 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| two_peaks | ×4 | 8 | 1.263 → 1.263 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |

**nous+alloc+bo** — as nous+alloc, plus planner.bo (the optional TPE proposer, module defaults); BO proposals reach only the allocate pool.

Over its 112 campaigns: mean runs 45.1 (default) → 52.5 (arm); certified 20 → 13; false certificates 0 → 0. Pooled Δ by family: shipped -0.0012 [-0.0032, 0.0000]; non-quadratic 0.0001 [0.0000, 0.0004].

| surface | noise | n | regret default → arm | Δ [95%] | N default → arm | cert/false default | cert/false arm | allocate fired |
|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 48.0 → 51.0 | 3/0 | 4/0 | 0 |
| additive | ×4 | 8 | 0.013 → 0.000 | -0.0023 [-0.0068, 0.0000] | 48.0 → 66.8 | 0/0 | 0/0 | 6 |
| bowl | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 4/0 | 2/0 | 0 |
| bowl | ×4 | 8 | 0.031 → 0.006 | -0.0038 [-0.0115, 0.0000] | 44.0 → 49.6 | 4/0 | 2/0 | 1 |
| saddle | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 62.8 | 1/0 | 1/0 | 6 |
| saddle | ×4 | 8 | 0.031 → 0.006 | -0.0038 [-0.0115, 0.0000] | 44.0 → 62.8 | 0/0 | 0/0 | 6 |
| geometric_knob_log | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 4/0 | 2/0 | 0 |
| geometric_knob_log | ×4 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 4/0 | 2/0 | 0 |
| step_cliff | ×1 | 8 | 0.400 → 0.400 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| step_cliff | ×4 | 8 | 0.462 → 0.462 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| ridge_cubic | ×1 | 8 | 0.220 → 0.220 | 0.0000 [0.0000, 0.0000] | 48.0 → 51.0 | 0/0 | 0/0 | 0 |
| ridge_cubic | ×4 | 8 | 0.228 → 0.232 | 0.0009 [0.0000, 0.0027] | 48.0 → 61.5 | 0/0 | 0/0 | 4 |
| two_peaks | ×1 | 8 | 1.263 → 1.263 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| two_peaks | ×4 | 8 | 1.263 → 1.263 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |

**nous-order** — run-order randomization OFF: every design and confirm block executes in design order (the drift ablation).

Over its 48 campaigns: mean runs 39.3 (default) → 39.3 (arm); certified 21 → 24; false certificates 0 → 0. Pooled Δ by family: shipped 0.0001 [-0.0018, 0.0018].

| surface | noise | n | regret default → arm | Δ [95%] | N default → arm | cert/false default | cert/false arm | allocate fired |
|---|---|---|---|---|---|---|---|---|
| drift | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 26.0 → 26.0 | 5/0 | 0/0 | 0 |
| drift | ×4 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 26.0 → 26.0 | 5/0 | 4/0 | 0 |
| bowl | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 44.0 → 44.0 | 4/0 | 7/0 | 0 |
| bowl | ×4 | 8 | 0.031 → 0.006 | -0.0038 [-0.0125, 0.0019] | 44.0 → 44.0 | 4/0 | 7/0 | 0 |
| additive | ×1 | 8 | 0.000 → 0.000 | 0.0000 [0.0000, 0.0000] | 48.0 → 48.0 | 3/0 | 6/0 | 0 |
| additive | ×4 | 8 | 0.013 → 0.038 | 0.0045 [0.0000, 0.0114] | 48.0 → 48.0 | 0/0 | 0/0 | 0 |


**Certification soundness:** nous: 30 certified of 128, **0 false**; nous+alloc: 12 certified of 112, **0 false**; nous+alloc+bo: 13 certified of 112, **0 false**; nous-order: 24 certified of 48, **0 false**.
<!-- END GENERATED ablations -->


## Results: multi-objective (seeds 1-8)

<!-- BEGIN GENERATED mo -->
_Generated by `python -m benchmarks.optimization.run --mo --workers 3 --cache-dir <cache-dir>` at checkout bf5a282dcc5fdee6432500207ff832059a42daaf; seeds [1, 2, 3, 4, 5, 6, 7, 8]; Nous digest(s) ff14a3afe6e0fdb1, benchmark digest(s) 47bc42e50f66cb60. Wall 1.1 min; peak RSS: largest worker 0.145 GB, parent 0.105 GB._

### Hypervolume regret at the matched budget (mean [bootstrap 95%]; lower is better)

Each baseline row is at the SAME arm's per-seed budget. h2h = arm better / tie / worse than the baseline.

| surface | arm | N | Nous | cert/false | RS | LHS | ParEGO | h2h RS | h2h LHS | h2h ParEGO |
|---|---|---|---|---|---|---|---|---|---|---|
| pareto_convex | nous | 56-62 | 0.028 [0.028, 0.028] | 8/0 of 8 | 0.072 [0.059, 0.086] | 0.059 [0.055, 0.065] | 0.021 [0.012, 0.032] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_concave | nous | 56-62 | 0.033 [0.033, 0.033] | 8/0 of 8 | 0.100 [0.087, 0.116] | 0.098 [0.084, 0.112] | 0.008 [0.003, 0.017] | 8 / 0 / 0 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_with_constraint | nous | 62 | 0.090 [0.066, 0.115] | 1/0 of 8 | 0.087 [0.078, 0.096] | 0.074 [0.058, 0.093] | 0.054 [0.035, 0.075] | 3 / 0 / 5 | 4 / 0 / 4 | 2 / 0 / 6 |
| pareto_three | nous | 84 | 0.181 [0.175, 0.186] | 5/0 of 8 | 0.167 [0.158, 0.176] | 0.160 [0.151, 0.170] | 0.070 [0.066, 0.074] | 3 / 0 / 5 | 2 / 0 / 6 | 0 / 0 / 8 |
| pareto_choice_split | nous | 56 | 0.066 [0.063, 0.069] | 0/0 of 8 | 0.013 [0.008, 0.019] | 0.007 [0.004, 0.011] | 0.020 [0.012, 0.028] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_noisy | nous | 62 | 0.050 [0.038, 0.063] | 0/0 of 8 | 0.095 [0.075, 0.116] | 0.092 [0.082, 0.100] | 0.027 [0.019, 0.036] | 7 / 0 / 1 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_convex_min | nous | 56-62 | 0.028 [0.028, 0.028] | 8/0 of 8 | 0.063 [0.052, 0.072] | 0.066 [0.056, 0.078] | 0.011 [0.001, 0.025] | 8 / 0 / 0 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_three_noisy | nous | 84 | 0.258 [0.251, 0.265] | 0/0 of 8 | 0.195 [0.181, 0.210] | 0.200 [0.187, 0.215] | 0.117 [0.106, 0.127] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_three_discrete | nous | 84 | 0.006 [0.003, 0.008] | 6/0 of 8 | 0.058 [0.030, 0.085] | 0.058 [0.046, 0.072] | 0.003 [0.001, 0.005] | 7 / 0 / 1 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_convex | nous+alloc | 56-62 | 0.028 [0.028, 0.028] | 8/0 of 8 | 0.072 [0.059, 0.086] | 0.059 [0.055, 0.065] | 0.021 [0.012, 0.032] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_concave | nous+alloc | 56-62 | 0.033 [0.033, 0.033] | 8/0 of 8 | 0.100 [0.087, 0.116] | 0.098 [0.084, 0.112] | 0.008 [0.003, 0.017] | 8 / 0 / 0 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_with_constraint | nous+alloc | 62-80 | 0.061 [0.052, 0.075] | 2/0 of 8 | 0.078 [0.068, 0.090] | 0.058 [0.043, 0.078] | 0.051 [0.032, 0.072] | 7 / 0 / 1 | 5 / 0 / 3 | 3 / 0 / 5 |
| pareto_three | nous+alloc | 84-108 | 0.174 [0.159, 0.186] | 5/0 of 8 | 0.164 [0.154, 0.175] | 0.154 [0.145, 0.165] | 0.067 [0.061, 0.073] | 3 / 0 / 5 | 3 / 0 / 5 | 0 / 0 / 8 |
| pareto_choice_split | nous+alloc | 56-74 | 0.062 [0.053, 0.069] | 0/0 of 8 | 0.013 [0.008, 0.019] | 0.007 [0.004, 0.011] | 0.016 [0.011, 0.021] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_noisy | nous+alloc | 62-80 | 0.036 [0.030, 0.043] | 0/0 of 8 | 0.086 [0.066, 0.110] | 0.083 [0.074, 0.092] | 0.021 [0.013, 0.029] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_convex_min | nous+alloc | 56-62 | 0.028 [0.028, 0.028] | 8/0 of 8 | 0.063 [0.052, 0.072] | 0.066 [0.056, 0.078] | 0.011 [0.001, 0.025] | 8 / 0 / 0 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_three_noisy | nous+alloc | 84 | 0.258 [0.251, 0.265] | 0/0 of 8 | 0.195 [0.181, 0.210] | 0.200 [0.187, 0.215] | 0.117 [0.106, 0.127] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_three_discrete | nous+alloc | 84 | 0.003 [0.002, 0.005] | 6/0 of 8 | 0.058 [0.030, 0.085] | 0.058 [0.046, 0.072] | 0.003 [0.001, 0.005] | 7 / 0 / 1 | 8 / 0 / 0 | 3 / 0 / 5 |
| pareto_convex | nous+alloc+bo | 56-62 | 0.027 [0.026, 0.028] | 8/0 of 8 | 0.072 [0.059, 0.086] | 0.059 [0.055, 0.065] | 0.021 [0.012, 0.032] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_concave | nous+alloc+bo | 59-62 | 0.028 [0.027, 0.030] | 8/0 of 8 | 0.099 [0.085, 0.116] | 0.098 [0.085, 0.112] | 0.008 [0.003, 0.017] | 8 / 0 / 0 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_with_constraint | nous+alloc+bo | 62-80 | 0.088 [0.076, 0.098] | 0/0 of 8 | 0.078 [0.068, 0.090] | 0.058 [0.043, 0.078] | 0.051 [0.032, 0.072] | 1 / 0 / 7 | 2 / 0 / 6 | 1 / 0 / 7 |
| pareto_three | nous+alloc+bo | 84-108 | 0.174 [0.159, 0.186] | 5/0 of 8 | 0.164 [0.154, 0.175] | 0.154 [0.145, 0.165] | 0.067 [0.061, 0.073] | 3 / 0 / 5 | 3 / 0 / 5 | 0 / 0 / 8 |
| pareto_choice_split | nous+alloc+bo | 56-74 | 0.062 [0.053, 0.069] | 0/0 of 8 | 0.013 [0.008, 0.019] | 0.007 [0.004, 0.011] | 0.016 [0.011, 0.021] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_noisy | nous+alloc+bo | 62-80 | 0.035 [0.029, 0.042] | 0/0 of 8 | 0.086 [0.066, 0.110] | 0.083 [0.074, 0.092] | 0.021 [0.013, 0.029] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_convex_min | nous+alloc+bo | 59-62 | 0.028 [0.028, 0.028] | 8/0 of 8 | 0.063 [0.052, 0.072] | 0.067 [0.056, 0.078] | 0.011 [0.001, 0.025] | 8 / 0 / 0 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_three_noisy | nous+alloc+bo | 84 | 0.258 [0.251, 0.265] | 0/0 of 8 | 0.195 [0.181, 0.210] | 0.200 [0.187, 0.215] | 0.117 [0.106, 0.127] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_three_discrete | nous+alloc+bo | 84 | 0.003 [0.002, 0.005] | 6/0 of 8 | 0.058 [0.030, 0.085] | 0.058 [0.046, 0.072] | 0.003 [0.001, 0.005] | 7 / 0 / 1 | 8 / 0 / 0 | 3 / 0 / 5 |

### Anytime HV regret, pooled over surfaces (bootstrap 95% over seeds)

Baselines at the default arm's N.

| method | 10% N | 20% N | 40% N | 60% N | 80% N | 100% N |
|---|---|---|---|---|---|---|
| nous | 0.393 [0.393, 0.393] | 0.304 [0.304, 0.304] | 0.175 [0.172, 0.178] | 0.102 [0.100, 0.104] | 0.075 [0.073, 0.077] | 0.072 [0.070, 0.074] |
| nous+alloc | 0.392 [0.390, 0.393] | 0.304 [0.304, 0.304] | 0.163 [0.159, 0.167] | 0.098 [0.093, 0.101] | 0.073 [0.070, 0.077] | 0.068 [0.067, 0.070] |
| nous+alloc+bo | 0.392 [0.390, 0.393] | 0.304 [0.304, 0.304] | 0.163 [0.159, 0.167] | 0.099 [0.095, 0.102] | 0.073 [0.070, 0.076] | 0.068 [0.066, 0.069] |
| RS | 0.384 [0.374, 0.394] | 0.264 [0.255, 0.275] | 0.178 [0.168, 0.190] | 0.136 [0.128, 0.144] | 0.113 [0.106, 0.121] | 0.094 [0.091, 0.098] |
| LHS | 0.356 [0.343, 0.369] | 0.249 [0.237, 0.262] | 0.166 [0.157, 0.176] | 0.127 [0.122, 0.132] | 0.105 [0.103, 0.107] | 0.090 [0.088, 0.093] |
| ParEGO | 0.337 [0.327, 0.348] | 0.147 [0.138, 0.154] | 0.073 [0.070, 0.075] | 0.052 [0.050, 0.054] | 0.044 [0.043, 0.046] | 0.037 [0.036, 0.038] |

### Pooled over surfaces (per seed, then bootstrap 95% over seeds)

| quantity | mean [95%] |
|---|---|
| HV regret, nous (mean runs 68.4) | 0.0820 [0.0799, 0.0840] |
| HV regret, nous+alloc (mean runs 72.2) | 0.0758 [0.0739, 0.0777] |
| HV regret, nous+alloc+bo (mean runs 72.3) | 0.0781 [0.0756, 0.0806] |
| nous+alloc minus nous (paired; negative favours the arm) | -0.0062 [-0.0098, -0.0029] |
| nous+alloc+bo minus nous (paired; negative favours the arm) | -0.0039 [-0.0078, 0.0002] |
| nous minus RS at nous's N (paired; negative favours Nous) | -0.0124 [-0.0177, -0.0073] |
| nous minus LHS at nous's N (paired; negative favours Nous) | -0.0085 [-0.0107, -0.0063] |
| nous minus ParEGO at nous's N (paired; negative favours Nous) | 0.0452 [0.0428, 0.0475] |

**Certification soundness (front certificates):** nous: 36 certified of 72, **0 false**; nous+alloc: 37 certified of 72, **0 false**; nous+alloc+bo: 35 certified of 72, **0 false**.
<!-- END GENERATED mo -->
