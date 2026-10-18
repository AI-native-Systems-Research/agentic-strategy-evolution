# Matched-budget benchmark: Nous vs random search, Latin hypercube, GP-BO

> **Read this first: the certification figures below predate model adequacy
> (WP-B) and certification soundness (WP-A).** The REGRET comparisons stand
> (they do not depend on certification). The CERTIFICATE counts do not: after
> WP-B and WP-A, false certificates on the non-quadratic family went from
> 21/48 to **0/48** (WP-B oracle, seeds 1-8; 0/40 at 40 seeds), and on the
> stage-0 noise sweep from 17/621 to **0/425** (WP-A, every noise cell). The
> cost is certification POWER on near-tied surfaces with few pure-error df.
> Sources: `docs/superpowers/specs/2026-10-17-model-adequacy-design.md` and
> `2026-10-17-certification-soundness.md`; independently re-run in
> `docs/optimization-expert-audit.md`. Regenerating this benchmark under the
> final code is a tracked follow-up.

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

Zero LLM tokens: every campaign is the in-process synthetic harness
(`orchestrator.optimize.harness`). Reproduce with
`python -m benchmarks.optimization.run` (the suite) and
`python -m benchmarks.optimization.run --audit-repro` (the stage-0 audit's
setup). Run through the machine's heavy wrapper with at most 3 workers. Both
accept `--cache-dir`, so a killed run resumes. Every row is in
`optimization-benchmark.json` / `optimization-benchmark-audit-repro.json`, and
records the code digest it was produced under (`code`). The digests are listed
in each table's header. The code digest is part of the cache key, so no row
produced by other code is reused. Every row in both tables was regenerated under a
single Nous digest and a single benchmark digest. The numbers are unchanged from
the previous run, including the GP-BO rows on surfaces without failing
configurations, so the never-re-pick-a-failure rule is a no-op there.

**This is a descriptive comparison, not a statistical one.** The budget N comes
from Nous's own stopping rule, so every baseline is compared at the one budget
Nous chose. There are no anytime (regret-vs-budget) curves and no confidence
intervals on the means: with 8 (suite) or 20 (audit) seeds per cell, a
difference of a few hundredths is noise. Read the head-to-head counts, not
small differences in the means.

## Protocol

- **Budget.** For each (surface, noise multiplier, seed), Nous runs first. The
  budget N is its total measured rows (every `runs/iter-*/runs.jsonl` row,
  failed ones included). Every baseline gets exactly N measurements of the same
  surface, under the same noise model, over the same candidate axes the oracle's
  truth is enumerated on (declared levels plus nine snapped points per gridded
  numeric). A failed measurement still costs a run. A Nous campaign that
  crashes is charged the worst admissible regret, and its baselines get the runs
  it spent; none crashed in these runs.
- **Metric.** TRUE regret of the recommendation on the NOISELESS surface,
  `f(true optimum) - f(recommendation)`. An infeasible recommendation (outside
  `X_valid`) or no recommendation is charged the regret of the worst admissible
  configuration.
- **Recommendation rules, both reported.**
  - `obs`: the measured configuration with the best mean over its replicates.
    It is feasible only if every replicate passed every constraint, the rule
    Nous uses.
  - `GP mean`: the measured feasible configuration with the best posterior mean
    of the GP below, fitted to the method's own data. Measured points only,
    never an unmeasured argmax.
  - The PRIMARY rule, used in the head-to-heads, is `obs` for RS and LHS and
    `GP mean` for GP-BO, the standard noisy-BO recommendation.
  - Exception: `GP-BO-crude`'s GP-mean pick is the audit's, and it is NOT
    restricted to feasible points. That is why it scores 8.2 on `sla`.
- **Ties.** "Exact" ties need identical regret. The "within ε" columns treat a
  difference of at most Nous's own resolved ε (a percentage of Nous's best value
  in that campaign) as a tie. That is Nous's indifference width, not a neutral
  one.
- **Surfaces.**
  - Every single-objective surface in `synthetic.SURFACES` except
    `bowl_out_of_hull` (its optimum lies outside the hull by construction), with
    the constraints each constrained surface was built for.
  - The audit's non-quadratic `step_cliff`, `ridge_cubic` and `two_peaks`.
  - `sparse_knobs(6/8/12)`, with 3 active knobs.
  - Pareto surfaces are out of scope: no baseline here is multi-objective.
- **Size.**
  - Suite: seeds 1-8, noise ×1 and ×4 of each surface's `noise_sd`, giving 336
    Nous campaigns and 1344 baseline runs.
  - Audit repro: the audit's 9 surfaces, seeds 1-20, noise ×1 and ×8, giving
    360 + 1440.
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

## Comparison with the audit's 144 / 174 / 42

The audit reported Nous against its crude GP-BO over 360 head-to-heads as
**better 42, tie 174, worse 144**. With the audit's setup (`--audit-repro`):

| baseline | rule | Nous better / tie / worse (exact) | within Nous's ε |
|---|---|---|---|
| GP-BO-crude (the audit's) | GP mean | **53 / 171 / 136** | 12 / 236 / 112 |
| GP-BO (fitted) | GP mean | **21 / 186 / 153** | 4 / 235 / 121 |
| GP-BO (fitted) | obs | 42 / 174 / 144 | 12 / 231 / 117 |

- **Nous's regrets match the audit's at the audit's precision** on every cell
  checked: additive ×8 0.078, bowl ×8 0.037, bowl_centred ×8 0.090,
  geometric_knob 26.25 / 23.65, step_cliff 0.90 / 0.94, ridge_cubic 0.50 /
  0.54, two_peaks 1.75 / 1.78.
- **The crude GP-BO reproduces only approximately.** The head-to-head is
  53/171/136 against the audit's 42/174/144, and per-cell means differ by up to
  0.7 (geometric_knob ×8: 5.64 against the audit's 6.35; two_peaks ×8: 1.60
  against 1.18). It has its own seed stream and initial points, and this
  harness's constrained and failing-measurement handling is not exercised on
  these 9 surfaces.
- **A coincidence worth checking.** The audit's exact triple, 42/174/144, is
  what the FITTED GP-BO scores here under the `obs` rule. That may be chance, or
  a label mix-up in the audit's table. It is noted, not resolved.
- **Either way, a properly fitted GP-BO is a stronger opponent than the
  audit's.** Under its standard GP-mean rule Nous loses 153 of 360 and wins 21.

## Interpretation

**Where Nous wins or ties.**

- **Smooth, low-order surfaces.** These are additive, interaction_only, bowl,
  bowl_centred, saddle, choice_x_numeric, drift and geometric_knob_log: 128
  campaigns.
  - Against the fitted GP-BO, exact counts are 25 better / 100 tied / 3 worse;
    within ε the result is 0 / 128 / 0.
  - Nous is within ε of the BEST baseline in 128 of 128.
  - Against RS and LHS it wins clearly.
  - So against GP-BO this is a tie, not a win.
- **Many knobs with effect sparsity** (`sparse_knobs` 6/8/12, 93-553 runs):
  - Nous's mean regret is 0.002, against GP-BO 0.003, RS 0.32 and LHS 0.48.
  - Within ε it ties GP-BO in 48 of 48 campaigns and never loses to RS or LHS.
  - It does this at about 1/30 of GP-BO's analysis CPU: 2.6 s against 88 s per
    campaign at 12 knobs and 553 runs. On a real target the runs, not the
    analysis, dominate the cost.
- **Drift** (`drift`, a trend of 0.05 per run). Nous scores 0 regret; the
  sequential baselines score 0.38-0.46 (RS, LHS) and 0.03-0.07 (GP-BOs). This is
  plausibly the blocked, randomized run order. No ablation here tests that
  attribution.
- **Noisy constraints** (`stochastic_constraint_boundary`). Nous scores 0.875;
  every baseline 6-7. Part of this gap is a design asymmetry, not a better
  optimizer: Nous replicates its finalists, while each baseline mostly measures a
  configuration once, so its "feasible" pick is feasible by one lucky draw. A
  baseline with replicated confirmation would narrow it.
- **What no baseline offers:**
  - a certificate with stated deltas (162 of 336 suite campaigns certified, of
    which **26 are false** at the code this table was generated with; **0 false** after WP-B/WP-A, see the note at the top);
  - a pre-registered policy and an audit trail;
  - provenance, `nous reanalyze`, and a cross-epoch error budget.

**Where Nous loses, and it is not close.**

- **Non-quadratic surfaces, at both noise levels.**
  - Regret on step_cliff: Nous 0.90 against RS 0.20 and GP-BO 0.23-0.30.
  - On ridge_cubic: 0.50 against 0.003-0.03.
  - On two_peaks: 1.75 against RS 1.02-1.06.
  - Against GP-BO in this family Nous is better in 0, tied in 17 and worse in 31
    of 48 (within ε).
  - Nous's regret here is identical on every seed (standard deviation 0). It
    converges to the same wrong answer because the second-order model cannot
    represent a cliff, a cubic or two peaks.
  - **At the code this table was generated with, it certified those answers.** The lack-of-fit test, at three levels per
    axis, had too little power to withhold certification in 22 of these 48
    campaigns, and all 22 certificates were false. WP-B's off-lattice validation
    check now withholds them: **0 of 48** false after WP-B/WP-A (note at the top).
  - The certificate is conditional on the response class (audit Q3; WP-A's
    scope).
- **Geometric knobs coded linearly** (`geometric_knob` without `scale: log`).
  - Nous's regret is 26.2 at ×1 and ×4, against GP-BO 2.6-4.1 and LHS 0.5.
  - 4 of 8 certificates at ×4 are false, and 6 of 20 at ×8 in the audit repro.
  - With `scale: log` (validation rule 25 warns when it is missing), Nous is the
    best method: 0 against GP-BO's 0.06-0.13.
- **Deterministic constraint at the boundary** (`sla`). Nous 0.40 (×1) and
  0.46 (×4); GP-BO 0.00 and 0.00.
- **A level that fails to measure** (`fails_at_one_level`). Nous 0.64 at both
  noise levels; GP-BO 0.08 and 0.08-0.13.

**Practical guidance.**

| Situation | Use |
|---|---|
| Few knobs, smooth monotone or single-bump response, expensive runs, and an auditable answer is needed (a deploy decision, a paper) | **Nous**, declaring `scale: log` for geometric knobs. Expect parity with GP-BO on regret; the certificate and the audit trail are the difference |
| Many knobs, few of which matter | **Nous** ties GP-BO at a fraction of the analysis compute, and certifies |
| A drifting environment | **Nous** (blocked, randomized order), although the attribution is untested |
| Noisy constraints | Nous, or any method that replicates its finalists |
| Response suspected multimodal, cliff-like or strongly non-polynomial | **GP-BO.** Treat a Nous certificate there as void without an independent check |
| Pure exploration of an unknown surface, no certificate needed | GP-BO, or LHS as a cheap space-filling first pass |

A sensible hybrid, not implemented here: explore with GP-BO or LHS first. Use
Nous when the explored region looks smooth, and distrust a certificate on a
surface the exploration showed to be non-smooth.

## Results: suite (seeds 1-8, noise ×1/×4)

<!-- BEGIN GENERATED suite -->
_Tables aggregated by `python -m benchmarks.optimization.run --workers 3 --cache-dir <cache-dir>` at checkout bd97bf6977f25aac4f1fa1df85167f0747e76aff (Nous 0.5.0); seeds [1, 2, 3, 4, 5, 6, 7, 8], noise multipliers [1.0, 4.0]. Rows come from the resume cache and record the code they were produced under: Nous source digest(s) 44d94bc5ee2a41b2; benchmark code digest(s) 2a042c84120bb891._

### PRIMARY (pre-declared): mean normalised regret difference, Nous minus baseline, per family

Normalised regret = regret / (f_best - f_worst admissible). Per seed: the mean over the family's cells; then the mean over seeds with a seeded percentile bootstrap (10000 resamples, seed 20261018) and the t interval. Negative favours Nous.

| family | baseline | seeds | mean [bootstrap 95%] | t 95% |
|---|---|---|---|---|
| shipped | RS | 8 | -0.0979 [-0.1124, -0.0751] | [-0.1236, -0.0722] |
| shipped | LHS | 8 | -0.0848 [-0.1010, -0.0643] | [-0.1078, -0.0617] |
| shipped | GP-BO | 8 | -0.0546 [-0.0655, -0.0367] | [-0.0747, -0.0344] |
| shipped | GP-BO-crude | 8 | -0.2672 [-0.2806, -0.2457] | [-0.2911, -0.2432] |
| non-quadratic | RS | 8 | -0.0318 [-0.0775, 0.0151] | [-0.0913, 0.0276] |
| non-quadratic | LHS | 8 | -0.0023 [-0.0520, 0.0371] | [-0.0611, 0.0564] |
| non-quadratic | GP-BO | 8 | -0.0588 [-0.0821, -0.0209] | [-0.1016, -0.0160] |
| non-quadratic | GP-BO-crude | 8 | -0.0749 [-0.0947, -0.0508] | [-0.1039, -0.0459] |
| many-knob sparse | RS | 8 | -0.0312 [-0.0416, -0.0216] | [-0.0440, -0.0184] |
| many-knob sparse | LHS | 8 | -0.0278 [-0.0379, -0.0199] | [-0.0395, -0.0162] |
| many-knob sparse | GP-BO | 8 | 0.0002 [-0.0002, 0.0008] | [-0.0005, 0.0009] |
| many-knob sparse | GP-BO-crude | 8 | -0.0020 [-0.0030, -0.0010] | [-0.0034, -0.0007] |

**Certification soundness:** nous: 50 certified of 336, **0 false**.

### Mean true regret per cell (lower is better)

| surface | noise | N | Nous | cert/false | RS (obs) | LHS (obs) | GP-BO (GP mean) | GP-BO-crude (GP mean) | RS (GP mean) | LHS (GP mean) | GP-BO (obs) | GP-BO-crude (obs) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 48 | 0.000 | 3/0 of 8 | 0.106 | 0.313 | 0.000 | 0.000 | 0.100 | 0.313 | 0.000 | 0.000 |
| additive | ×4 | 48 | 0.013 | 0/0 of 8 | 0.119 | 0.313 | 0.000 | 0.025 | 0.113 | 0.313 | 0.031 | 0.025 |
| interaction_only | ×1 | 38 | 0.000 | 0/0 of 8 | 0.140 | 0.035 | 0.000 | 0.000 | 0.140 | 0.035 | 0.000 | 0.000 |
| interaction_only | ×4 | 38 | 0.000 | 0/0 of 8 | 0.235 | 0.070 | 0.000 | 0.000 | 0.200 | 0.070 | 0.000 | 0.000 |
| bowl | ×1 | 44 | 0.000 | 4/0 of 8 | 0.063 | 0.038 | 0.000 | 0.000 | 0.063 | 0.031 | 0.000 | 0.000 |
| bowl | ×4 | 44 | 0.031 | 4/0 of 8 | 0.119 | 0.138 | 0.006 | 0.013 | 0.069 | 0.038 | 0.062 | 0.050 |
| bowl_centred | ×1 | 48 | 0.000 | 3/0 of 8 | 0.125 | 0.113 | 0.000 | 0.000 | 0.125 | 0.113 | 0.000 | 0.000 |
| bowl_centred | ×4 | 48 | 0.000 | 3/0 of 8 | 0.194 | 0.169 | 0.019 | 0.025 | 0.125 | 0.131 | 0.050 | 0.025 |
| saddle | ×1 | 44 | 0.000 | 1/0 of 8 | 0.056 | 0.106 | 0.000 | 0.000 | 0.050 | 0.094 | 0.000 | 0.006 |
| saddle | ×4 | 44 | 0.031 | 0/0 of 8 | 0.056 | 0.106 | 0.019 | 0.019 | 0.081 | 0.100 | 0.031 | 0.013 |
| choice_x_numeric | ×1 | 38 | 0.000 | 4/0 of 8 | 0.125 | 0.000 | 0.000 | 0.000 | 0.125 | 0.000 | 0.000 | 0.000 |
| choice_x_numeric | ×4 | 38 | 0.000 | 4/0 of 8 | 0.125 | 0.000 | 0.000 | 0.000 | 0.125 | 0.000 | 0.000 | 0.000 |
| drift | ×1 | 26 | 0.000 | 5/0 of 8 | 0.381 | 0.213 | 0.050 | 0.038 | 0.294 | 0.113 | 0.050 | 0.038 |
| drift | ×4 | 26 | 0.000 | 5/0 of 8 | 0.344 | 0.219 | 0.013 | 0.069 | 0.294 | 0.200 | 0.013 | 0.069 |
| sla | ×1 | 68 | 0.400 | 0/0 of 8 | 0.200 | 0.075 | 0.000 | 8.200 | 0.200 | 0.075 | 0.000 | 0.200 |
| sla | ×4 | 68 | 0.275 | 0/0 of 8 | 0.200 | 0.150 | 0.000 | 8.200 | 0.200 | 0.075 | 0.025 | 0.350 |
| infeasible_corner_interior | ×1 | 45 | 0.000 | 5/0 of 8 | 0.000 | 0.019 | 0.000 | 3.300 | 0.000 | 0.019 | 0.000 | 0.019 |
| infeasible_corner_interior | ×4 | 45 | 0.000 | 1/0 of 8 | 0.000 | 0.056 | 0.000 | 3.300 | 0.000 | 0.019 | 0.000 | 0.075 |
| nan_at_corner | ×1 | 8 | 0.000 | 0/0 of 8 | 0.744 | 0.181 | 0.000 | 0.506 | 0.744 | 0.181 | 0.000 | 0.506 |
| nan_at_corner | ×4 | 8 | 0.000 | 0/0 of 8 | 0.744 | 0.181 | 0.056 | 0.594 | 0.744 | 0.181 | 0.100 | 0.613 |
| fails_at_one_level | ×1 | 30 | 0.320 | 0/0 of 8 | 0.200 | 0.140 | 0.080 | 0.080 | 0.200 | 0.140 | 0.080 | 0.080 |
| fails_at_one_level | ×4 | 30 | 0.360 | 0/0 of 8 | 0.260 | 0.170 | 0.080 | 0.080 | 0.220 | 0.150 | 0.090 | 0.090 |
| stochastic_constraint_boundary | ×1 | 68 | 0.875 | 0/0 of 8 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 6.125 |
| stochastic_constraint_boundary | ×4 | 68 | 0.875 | 0/0 of 8 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 7.000 | 6.125 |
| geometric_knob | ×1 | 44 | 0.188 | 0/0 of 8 | 0.061 | 0.505 | 2.614 | 5.089 | 0.087 | 0.552 | 2.614 | 3.304 |
| geometric_knob | ×4 | 44 | 0.188 | 0/0 of 8 | 0.061 | 0.505 | 3.207 | 4.734 | 0.516 | 1.521 | 3.208 | 2.961 |
| geometric_knob_log | ×1 | 44 | 0.000 | 4/0 of 8 | 0.500 | 0.103 | 0.076 | 0.144 | 0.492 | 0.081 | 0.068 | 0.109 |
| geometric_knob_log | ×4 | 44 | 0.000 | 4/0 of 8 | 0.500 | 0.115 | 0.110 | 0.150 | 0.522 | 0.137 | 0.116 | 0.108 |
| deterministic_constraint_axis | ×1 | 57 | 0.000 | 0/0 of 8 | 1.225 | 1.712 | 0.000 | 8.100 | 1.225 | 1.712 | 0.000 | 0.000 |
| deterministic_constraint_axis | ×4 | 57 | 0.000 | 0/0 of 8 | 1.225 | 1.725 | 0.000 | 8.100 | 1.225 | 1.712 | 0.000 | 0.256 |
| step_cliff | ×1 | 44 | 0.400 | 0/0 of 8 | 0.200 | 0.150 | 0.225 | 0.500 | 0.200 | 0.150 | 0.225 | 0.337 |
| step_cliff | ×4 | 44 | 0.462 | 0/0 of 8 | 0.200 | 0.162 | 0.225 | 0.575 | 0.225 | 0.175 | 0.225 | 0.487 |
| ridge_cubic | ×1 | 48 | 0.220 | 0/0 of 8 | 0.081 | 0.066 | 0.003 | 0.010 | 0.081 | 0.052 | 0.003 | 0.007 |
| ridge_cubic | ×4 | 48 | 0.228 | 0/0 of 8 | 0.232 | 0.132 | 0.017 | 0.079 | 0.147 | 0.096 | 0.045 | 0.159 |
| two_peaks | ×1 | 44 | 0.364 | 0/0 of 8 | 1.011 | 0.721 | 1.534 | 1.412 | 1.011 | 0.712 | 1.534 | 1.412 |
| two_peaks | ×4 | 44 | 0.364 | 0/0 of 8 | 1.037 | 0.721 | 1.544 | 1.607 | 1.011 | 0.720 | 1.534 | 1.607 |
| sparse_knobs_6 | ×1 | 108 | 0.000 | 0/0 of 8 | 0.350 | 0.260 | 0.000 | 0.000 | 0.350 | 0.260 | 0.000 | 0.000 |
| sparse_knobs_6 | ×4 | 108 | 0.010 | 0/0 of 8 | 0.427 | 0.270 | 0.014 | 0.044 | 0.350 | 0.270 | 0.044 | 0.054 |
| sparse_knobs_8 | ×1 | 176 | 0.000 | 0/0 of 8 | 0.250 | 0.282 | 0.000 | 0.000 | 0.250 | 0.282 | 0.000 | 0.000 |
| sparse_knobs_8 | ×4 | 176 | 0.014 | 0/0 of 8 | 0.335 | 0.370 | 0.000 | 0.057 | 0.270 | 0.400 | 0.010 | 0.057 |
| sparse_knobs_12 | ×1 | 568 | 0.000 | 0/0 of 8 | 0.106 | 0.064 | 0.000 | 0.000 | 0.106 | 0.064 | 0.000 | 0.000 |
| sparse_knobs_12 | ×4 | 568 | 0.000 | 0/0 of 8 | 0.180 | 0.226 | 0.000 | 0.027 | 0.135 | 0.150 | 0.024 | 0.027 |

### 95% bootstrap intervals of the per-cell means (over seeds; primary rule for baselines)

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | [0.000, 0.000] | [0.038, 0.181] | [0.219, 0.419] | [0.000, 0.000] | [0.000, 0.000] |
| additive | ×4 | [0.000, 0.038] | [0.050, 0.188] | [0.219, 0.419] | [0.000, 0.000] | [0.000, 0.063] |
| interaction_only | ×1 | [0.000, 0.000] | [0.035, 0.245] | [0.000, 0.105] | [0.000, 0.000] | [0.000, 0.000] |
| interaction_only | ×4 | [0.000, 0.000] | [0.105, 0.375] | [0.000, 0.175] | [0.000, 0.000] | [0.000, 0.000] |
| bowl | ×1 | [0.000, 0.000] | [0.019, 0.125] | [0.013, 0.069] | [0.000, 0.000] | [0.000, 0.000] |
| bowl | ×4 | [0.000, 0.081] | [0.031, 0.244] | [0.056, 0.231] | [0.000, 0.019] | [0.000, 0.031] |
| bowl_centred | ×1 | [0.000, 0.000] | [0.056, 0.194] | [0.050, 0.181] | [0.000, 0.000] | [0.000, 0.000] |
| bowl_centred | ×4 | [0.000, 0.000] | [0.106, 0.287] | [0.069, 0.281] | [0.006, 0.038] | [0.006, 0.050] |
| saddle | ×1 | [0.000, 0.000] | [0.025, 0.100] | [0.025, 0.212] | [0.000, 0.000] | [0.000, 0.000] |
| saddle | ×4 | [0.000, 0.081] | [0.025, 0.100] | [0.025, 0.212] | [0.000, 0.038] | [0.006, 0.038] |
| choice_x_numeric | ×1 | [0.000, 0.000] | [0.000, 0.375] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| choice_x_numeric | ×4 | [0.000, 0.000] | [0.000, 0.375] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| drift | ×1 | [0.000, 0.000] | [0.206, 0.575] | [0.050, 0.394] | [0.000, 0.150] | [0.000, 0.088] |
| drift | ×4 | [0.000, 0.000] | [0.163, 0.550] | [0.050, 0.406] | [0.000, 0.038] | [0.013, 0.156] |
| sla | ×1 | [0.400, 0.400] | [0.075, 0.325] | [0.025, 0.150] | [0.000, 0.000] | [8.200, 8.200] |
| sla | ×4 | [0.225, 0.350] | [0.075, 0.325] | [0.050, 0.250] | [0.000, 0.000] | [8.200, 8.200] |
| infeasible_corner_interior | ×1 | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.056] | [0.000, 0.000] | [3.300, 3.300] |
| infeasible_corner_interior | ×4 | [0.000, 0.000] | [0.000, 0.000] | [0.019, 0.112] | [0.000, 0.000] | [3.300, 3.300] |
| nan_at_corner | ×1 | [0.000, 0.000] | [0.375, 1.100] | [0.081, 0.281] | [0.000, 0.000] | [0.244, 0.806] |
| nan_at_corner | ×4 | [0.000, 0.000] | [0.375, 1.100] | [0.081, 0.281] | [0.000, 0.169] | [0.225, 1.025] |
| fails_at_one_level | ×1 | [0.320, 0.320] | [0.100, 0.340] | [0.090, 0.210] | [0.080, 0.080] | [0.080, 0.080] |
| fails_at_one_level | ×4 | [0.320, 0.440] | [0.130, 0.400] | [0.100, 0.260] | [0.080, 0.080] | [0.080, 0.080] |
| stochastic_constraint_boundary | ×1 | [0.000, 2.625] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] |
| stochastic_constraint_boundary | ×4 | [0.000, 2.625] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] | [7.000, 7.000] |
| geometric_knob | ×1 | [0.188, 0.188] | [0.025, 0.103] | [0.059, 1.353] | [0.713, 4.542] | [3.242, 7.045] |
| geometric_knob | ×4 | [0.188, 0.188] | [0.025, 0.103] | [0.059, 1.353] | [1.394, 5.054] | [2.994, 6.529] |
| geometric_knob_log | ×1 | [0.000, 0.000] | [0.050, 1.350] | [0.066, 0.137] | [0.034, 0.119] | [0.106, 0.170] |
| geometric_knob_log | ×4 | [0.000, 0.000] | [0.050, 1.350] | [0.074, 0.150] | [0.068, 0.157] | [0.124, 0.170] |
| deterministic_constraint_axis | ×1 | [0.000, 0.000] | [0.894, 1.531] | [1.037, 2.400] | [0.000, 0.000] | [8.100, 8.100] |
| deterministic_constraint_axis | ×4 | [0.000, 0.000] | [0.894, 1.531] | [1.050, 2.437] | [0.000, 0.000] | [8.100, 8.100] |
| step_cliff | ×1 | [0.400, 0.400] | [0.050, 0.400] | [0.062, 0.237] | [0.037, 0.450] | [0.362, 0.700] |
| step_cliff | ×4 | [0.400, 0.587] | [0.050, 0.400] | [0.062, 0.250] | [0.037, 0.450] | [0.375, 0.775] |
| ridge_cubic | ×1 | [0.220, 0.220] | [0.036, 0.129] | [0.023, 0.110] | [0.000, 0.010] | [0.003, 0.021] |
| ridge_cubic | ×4 | [0.138, 0.327] | [0.132, 0.333] | [0.071, 0.193] | [0.007, 0.028] | [0.025, 0.137] |
| two_peaks | ×1 | [0.364, 0.364] | [0.422, 1.599] | [0.228, 1.433] | [1.096, 1.754] | [0.900, 1.754] |
| two_peaks | ×4 | [0.364, 0.364] | [0.422, 1.652] | [0.228, 1.433] | [1.096, 1.781] | [1.124, 1.889] |
| sparse_knobs_6 | ×1 | [0.000, 0.000] | [0.135, 0.591] | [0.100, 0.454] | [0.000, 0.000] | [0.000, 0.000] |
| sparse_knobs_6 | ×4 | [0.000, 0.030] | [0.194, 0.666] | [0.112, 0.455] | [0.000, 0.041] | [0.000, 0.104] |
| sparse_knobs_8 | ×1 | [0.000, 0.000] | [0.120, 0.375] | [0.129, 0.435] | [0.000, 0.000] | [0.000, 0.000] |
| sparse_knobs_8 | ×4 | [0.000, 0.041] | [0.176, 0.505] | [0.205, 0.530] | [0.000, 0.000] | [0.024, 0.087] |
| sparse_knobs_12 | ×1 | [0.000, 0.000] | [0.020, 0.214] | [0.014, 0.124] | [0.000, 0.000] | [0.000, 0.000] |
| sparse_knobs_12 | ×4 | [0.000, 0.000] | [0.060, 0.320] | [0.126, 0.326] | [0.000, 0.000] | [0.000, 0.069] |

### Head-to-head (Nous better / tie / worse), every cell pooled

| baseline | rule | exact tie | tie = within Nous's ε |
|---|---|---|---|
| RS | best_observed | 188 / 84 / 64 | 87 / 229 / 20 |
| RS | gp_mean | 183 / 88 / 65 | 82 / 233 / 21 |
| LHS | best_observed | 171 / 84 / 81 | 78 / 232 / 26 |
| LHS | gp_mean | 162 / 90 / 84 | 78 / 231 / 27 |
| GP-BO | best_observed | 72 / 188 / 76 | 42 / 272 / 22 |
| GP-BO | gp_mean | 62 / 198 / 76 | 40 / 273 / 23 |
| GP-BO-crude | best_observed | 108 / 167 / 61 | 62 / 262 / 12 |
| GP-BO-crude | gp_mean | 153 / 134 / 49 | 112 / 220 / 4 |

### Head-to-head by surface family (primary rule)

| family | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|
| shipped (exact) | 132 / 70 / 38 | 126 / 72 / 42 | 45 / 151 / 44 | 122 / 95 / 23 |
| shipped (within ε) | 68 / 167 / 5 | 63 / 169 / 8 | 25 / 203 / 12 | 92 / 147 / 1 |
| non-quadratic (exact) | 20 / 2 / 26 | 8 / 1 / 39 | 16 / 1 / 31 | 23 / 1 / 24 |
| non-quadratic (within ε) | 12 / 21 / 15 | 6 / 24 / 18 | 15 / 22 / 11 | 20 / 25 / 3 |
| many-knob sparse (exact) | 36 / 12 / 0 | 37 / 11 / 0 | 1 / 46 / 1 | 8 / 38 / 2 |
| many-knob sparse (within ε) | 7 / 41 / 0 | 9 / 39 / 0 | 0 / 48 / 0 | 0 / 48 / 0 |

### Wilson 95% intervals on the pooled head-to-head proportions (primary rule)

| baseline | n | P(Nous better), exact | P(Nous worse), exact | P(better), within ε | P(worse), within ε |
|---|---|---|---|---|---|
| RS | 336 | 0.56 [0.51, 0.61] | 0.19 [0.15, 0.24] | 0.26 [0.22, 0.31] | 0.06 [0.04, 0.09] |
| LHS | 336 | 0.51 [0.46, 0.56] | 0.24 [0.20, 0.29] | 0.23 [0.19, 0.28] | 0.08 [0.05, 0.11] |
| GP-BO | 336 | 0.18 [0.15, 0.23] | 0.23 [0.18, 0.27] | 0.12 [0.09, 0.16] | 0.07 [0.05, 0.10] |
| GP-BO-crude | 336 | 0.46 [0.40, 0.51] | 0.15 [0.11, 0.19] | 0.33 [0.29, 0.39] | 0.01 [0.00, 0.03] |

### Anytime regret (mean normalised regret at fractions of N, bootstrap 95% over seeds)

Nous: the best-so-far always-admissible measured configuration after its first n runs (its campaign is NOT stopped there: this is where its run sequence stands). Baselines: their primary-rule pick on the prefix of their own measurements. N is Nous's own stopping budget.

| family | method | 10% N | 20% N | 40% N | 60% N | 80% N | 100% N |
|---|---|---|---|---|---|---|---|
| shipped | Nous | 0.194 [0.178, 0.219] | 0.130 [0.113, 0.155] | 0.144 [0.119, 0.162] | 0.040 [0.031, 0.058] | 0.034 [0.017, 0.059] | 0.018 [0.009, 0.035] |
| shipped | RS | 0.316 [0.293, 0.348] | 0.213 [0.183, 0.244] | 0.160 [0.149, 0.169] | 0.132 [0.128, 0.137] | 0.121 [0.117, 0.125] | 0.116 [0.110, 0.122] |
| shipped | LHS | 0.298 [0.250, 0.352] | 0.227 [0.206, 0.249] | 0.156 [0.140, 0.178] | 0.118 [0.100, 0.135] | 0.102 [0.087, 0.118] | 0.103 [0.095, 0.112] |
| shipped | GP-BO | 0.293 [0.265, 0.320] | 0.141 [0.128, 0.154] | 0.092 [0.074, 0.108] | 0.076 [0.072, 0.080] | 0.072 [0.070, 0.074] | 0.072 [0.070, 0.075] |
| shipped | GP-BO-crude | 0.422 [0.381, 0.472] | 0.350 [0.328, 0.369] | 0.309 [0.298, 0.321] | 0.295 [0.289, 0.302] | 0.293 [0.285, 0.302] | 0.285 [0.280, 0.291] |
| non-quadratic | Nous | 0.251 [0.251, 0.251] | 0.251 [0.251, 0.251] | 0.217 [0.217, 0.217] | 0.070 [0.067, 0.075] | 0.066 [0.062, 0.070] | 0.066 [0.062, 0.070] |
| non-quadratic | RS | 0.237 [0.165, 0.310] | 0.170 [0.115, 0.219] | 0.131 [0.074, 0.181] | 0.098 [0.049, 0.145] | 0.102 [0.056, 0.148] | 0.099 [0.053, 0.144] |
| non-quadratic | LHS | 0.238 [0.168, 0.286] | 0.157 [0.102, 0.208] | 0.142 [0.087, 0.191] | 0.099 [0.042, 0.157] | 0.087 [0.036, 0.139] | 0.070 [0.029, 0.122] |
| non-quadratic | GP-BO | 0.284 [0.215, 0.335] | 0.224 [0.182, 0.256] | 0.140 [0.106, 0.165] | 0.133 [0.091, 0.161] | 0.128 [0.088, 0.155] | 0.126 [0.087, 0.151] |
| non-quadratic | GP-BO-crude | 0.267 [0.209, 0.315] | 0.173 [0.139, 0.200] | 0.154 [0.127, 0.176] | 0.147 [0.118, 0.170] | 0.143 [0.116, 0.165] | 0.142 [0.115, 0.164] |
| many-knob sparse | Nous | 0.065 [0.065, 0.065] | 0.065 [0.065, 0.065] | 0.065 [0.065, 0.065] | 0.065 [0.065, 0.065] | 0.065 [0.065, 0.065] | 0.000 [0.000, 0.001] |
| many-knob sparse | RS | 0.114 [0.092, 0.134] | 0.078 [0.059, 0.097] | 0.061 [0.044, 0.079] | 0.045 [0.031, 0.058] | 0.039 [0.027, 0.049] | 0.032 [0.022, 0.042] |
| many-knob sparse | LHS | 0.129 [0.118, 0.141] | 0.095 [0.073, 0.117] | 0.058 [0.043, 0.076] | 0.035 [0.026, 0.045] | 0.028 [0.021, 0.037] | 0.028 [0.020, 0.038] |
| many-knob sparse | GP-BO | 0.074 [0.053, 0.092] | 0.004 [0.002, 0.006] | 0.002 [0.000, 0.003] | 0.001 [0.000, 0.001] | 0.001 [0.000, 0.001] | 0.000 [0.000, 0.001] |
| many-knob sparse | GP-BO-crude | 0.064 [0.046, 0.081] | 0.007 [0.003, 0.011] | 0.003 [0.001, 0.004] | 0.003 [0.003, 0.004] | 0.002 [0.001, 0.003] | 0.002 [0.002, 0.003] |

### Median CPU seconds per campaign

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| additive | ×4 | 0.21 | 0.01 | 0.01 | 0.10 | 0.01 |
| interaction_only | ×1 | 0.15 | 0.01 | 0.01 | 0.45 | 0.12 |
| interaction_only | ×4 | 0.15 | 0.01 | 0.01 | 0.45 | 0.12 |
| bowl | ×1 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| bowl | ×4 | 0.20 | 0.01 | 0.01 | 0.08 | 0.01 |
| bowl_centred | ×1 | 0.21 | 0.01 | 0.01 | 0.12 | 0.01 |
| bowl_centred | ×4 | 0.21 | 0.01 | 0.01 | 0.11 | 0.01 |
| saddle | ×1 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| saddle | ×4 | 0.20 | 0.01 | 0.01 | 0.08 | 0.01 |
| choice_x_numeric | ×1 | 0.20 | 0.01 | 0.01 | 0.06 | 0.00 |
| choice_x_numeric | ×4 | 0.20 | 0.01 | 0.01 | 0.06 | 0.01 |
| drift | ×1 | 0.14 | 0.01 | 0.01 | 0.04 | 0.00 |
| drift | ×4 | 0.14 | 0.01 | 0.01 | 0.04 | 0.00 |
| sla | ×1 | 0.26 | 0.02 | 0.02 | 0.30 | 0.01 |
| sla | ×4 | 0.26 | 0.02 | 0.02 | 0.30 | 0.01 |
| infeasible_corner_interior | ×1 | 0.21 | 0.01 | 0.01 | 0.13 | 0.01 |
| infeasible_corner_interior | ×4 | 0.21 | 0.01 | 0.01 | 0.13 | 0.01 |
| nan_at_corner | ×1 | 0.06 | 0.00 | 0.00 | 0.01 | 0.00 |
| nan_at_corner | ×4 | 0.06 | 0.00 | 0.00 | 0.01 | 0.00 |
| fails_at_one_level | ×1 | 0.14 | 0.01 | 0.01 | 0.04 | 0.00 |
| fails_at_one_level | ×4 | 0.14 | 0.01 | 0.01 | 0.04 | 0.00 |
| stochastic_constraint_boundary | ×1 | 0.28 | 0.02 | 0.02 | 0.29 | 0.01 |
| stochastic_constraint_boundary | ×4 | 0.28 | 0.02 | 0.02 | 0.29 | 0.01 |
| geometric_knob | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| geometric_knob | ×4 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| geometric_knob_log | ×1 | 0.20 | 0.01 | 0.01 | 0.08 | 0.01 |
| geometric_knob_log | ×4 | 0.20 | 0.01 | 0.01 | 0.08 | 0.01 |
| deterministic_constraint_axis | ×1 | 0.27 | 0.01 | 0.01 | 0.36 | 0.03 |
| deterministic_constraint_axis | ×4 | 0.27 | 0.01 | 0.02 | 0.35 | 0.03 |
| step_cliff | ×1 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| step_cliff | ×4 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| ridge_cubic | ×1 | 0.21 | 0.01 | 0.01 | 0.11 | 0.01 |
| ridge_cubic | ×4 | 0.21 | 0.01 | 0.01 | 0.11 | 0.01 |
| two_peaks | ×1 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| two_peaks | ×4 | 0.20 | 0.01 | 0.01 | 0.08 | 0.01 |
| sparse_knobs_6 | ×1 | 1.31 | 0.06 | 0.06 | 2.51 | 1.96 |
| sparse_knobs_6 | ×4 | 1.58 | 0.05 | 0.05 | 2.47 | 1.95 |
| sparse_knobs_8 | ×1 | 10.39 | 0.15 | 0.15 | 5.60 | 5.80 |
| sparse_knobs_8 | ×4 | 12.98 | 0.14 | 0.14 | 5.60 | 5.49 |
| sparse_knobs_12 | ×1 | 37.51 | 3.24 | 2.97 | 78.99 | 80.48 |
| sparse_knobs_12 | ×4 | 38.01 | 3.00 | 3.26 | 79.62 | 80.03 |

_GP-BO had to re-pick an only-failed configuration 0 time(s) (every candidate had failed)._
<!-- END GENERATED suite -->


## Results: audit reproduction (the audit's 9 surfaces, seeds 1-20, noise ×1/×8)

<!-- BEGIN GENERATED audit-repro -->
_Tables aggregated by `python -m benchmarks.optimization.run --audit-repro --workers 3 --cache-dir <cache-dir>` at checkout bd97bf6977f25aac4f1fa1df85167f0747e76aff (Nous 0.5.0); seeds [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], noise multipliers [1.0, 8.0]. Rows come from the resume cache and record the code they were produced under: Nous source digest(s) 44d94bc5ee2a41b2; benchmark code digest(s) 2a042c84120bb891._

### PRIMARY (pre-declared): mean normalised regret difference, Nous minus baseline, per family

Normalised regret = regret / (f_best - f_worst admissible). Per seed: the mean over the family's cells; then the mean over seeds with a seeded percentile bootstrap (10000 resamples, seed 20261018) and the t interval. Negative favours Nous.

| family | baseline | seeds | mean [bootstrap 95%] | t 95% |
|---|---|---|---|---|
| shipped | RS | 20 | -0.0216 [-0.0284, -0.0161] | [-0.0284, -0.0148] |
| shipped | LHS | 20 | -0.0187 [-0.0226, -0.0147] | [-0.0230, -0.0143] |
| shipped | GP-BO | 20 | -0.0049 [-0.0077, -0.0023] | [-0.0079, -0.0020] |
| shipped | GP-BO-crude | 20 | -0.0149 [-0.0190, -0.0109] | [-0.0194, -0.0104] |
| non-quadratic | RS | 20 | -0.0401 [-0.0686, -0.0107] | [-0.0718, -0.0084] |
| non-quadratic | LHS | 20 | 0.0058 [-0.0232, 0.0311] | [-0.0241, 0.0356] |
| non-quadratic | GP-BO | 20 | -0.0519 [-0.0710, -0.0296] | [-0.0746, -0.0292] |
| non-quadratic | GP-BO-crude | 20 | -0.0710 [-0.0852, -0.0541] | [-0.0882, -0.0538] |

**Certification soundness:** nous: 60 certified of 360, **0 false**.

### Mean true regret per cell (lower is better)

| surface | noise | N | Nous | cert/false | RS (obs) | LHS (obs) | GP-BO (GP mean) | GP-BO-crude (GP mean) | RS (GP mean) | LHS (GP mean) | GP-BO (obs) | GP-BO-crude (obs) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 48 | 0.000 | 8/0 of 20 | 0.228 | 0.225 | 0.000 | 0.000 | 0.225 | 0.223 | 0.000 | 0.000 |
| additive | ×8 | 48 | 0.063 | 0/0 of 20 | 0.333 | 0.320 | 0.048 | 0.093 | 0.273 | 0.243 | 0.123 | 0.213 |
| bowl | ×1 | 44 | 0.000 | 11/0 of 20 | 0.050 | 0.068 | 0.000 | 0.003 | 0.050 | 0.060 | 0.000 | 0.003 |
| bowl | ×8 | 44 | 0.010 | 2/0 of 20 | 0.192 | 0.255 | 0.038 | 0.085 | 0.058 | 0.075 | 0.113 | 0.150 |
| bowl_centred | ×1 | 48 | 0.000 | 8/0 of 20 | 0.120 | 0.093 | 0.000 | 0.000 | 0.110 | 0.093 | 0.000 | 0.000 |
| bowl_centred | ×8 | 48 | 0.040 | 3/0 of 20 | 0.205 | 0.280 | 0.050 | 0.108 | 0.128 | 0.133 | 0.068 | 0.155 |
| saddle | ×1 | 44 | 0.000 | 3/0 of 20 | 0.048 | 0.078 | 0.000 | 0.000 | 0.045 | 0.072 | 0.003 | 0.008 |
| saddle | ×8 | 44 | 0.045 | 0/0 of 20 | 0.178 | 0.127 | 0.003 | 0.065 | 0.127 | 0.087 | 0.018 | 0.097 |
| choice_x_numeric | ×1 | 38 | 0.000 | 13/0 of 20 | 0.325 | 0.000 | 0.000 | 0.000 | 0.325 | 0.000 | 0.000 | 0.000 |
| choice_x_numeric | ×8 | 38 | 0.025 | 12/0 of 20 | 0.325 | 0.050 | 0.000 | 0.000 | 0.325 | 0.000 | 0.000 | 0.000 |
| geometric_knob | ×1 | 44 | 0.188 | 0/0 of 20 | 0.651 | 0.263 | 1.991 | 4.748 | 0.664 | 0.293 | 1.985 | 3.239 |
| geometric_knob | ×8 | 44 | 0.188 | 0/0 of 20 | 0.949 | 0.496 | 2.713 | 5.664 | 1.439 | 2.485 | 2.766 | 4.281 |
| step_cliff | ×1 | 44 | 0.400 | 0/0 of 20 | 0.230 | 0.205 | 0.105 | 0.480 | 0.230 | 0.205 | 0.105 | 0.335 |
| step_cliff | ×8 | 44 | 0.555 | 0/0 of 20 | 0.425 | 0.410 | 0.215 | 0.545 | 0.435 | 0.310 | 0.300 | 0.420 |
| ridge_cubic | ×1 | 48 | 0.220 | 0/0 of 20 | 0.076 | 0.077 | 0.003 | 0.015 | 0.078 | 0.065 | 0.003 | 0.007 |
| ridge_cubic | ×8 | 48 | 0.300 | 0/0 of 20 | 0.359 | 0.341 | 0.112 | 0.047 | 0.245 | 0.220 | 0.201 | 0.146 |
| two_peaks | ×1 | 44 | 0.364 | 0/0 of 20 | 1.007 | 0.457 | 1.510 | 1.549 | 1.007 | 0.454 | 1.510 | 1.529 |
| two_peaks | ×8 | 44 | 0.364 | 0/0 of 20 | 1.099 | 0.457 | 1.503 | 1.575 | 1.037 | 0.696 | 1.528 | 1.627 |

### 95% bootstrap intervals of the per-cell means (over seeds; primary rule for baselines)

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | [0.000, 0.000] | [0.145, 0.320] | [0.163, 0.290] | [0.000, 0.000] | [0.000, 0.000] |
| additive | ×8 | [0.030, 0.105] | [0.200, 0.495] | [0.233, 0.410] | [0.010, 0.095] | [0.038, 0.155] |
| bowl | ×1 | [0.000, 0.000] | [0.028, 0.078] | [0.040, 0.098] | [0.000, 0.000] | [0.000, 0.008] |
| bowl | ×8 | [0.000, 0.030] | [0.113, 0.280] | [0.168, 0.345] | [0.015, 0.068] | [0.038, 0.145] |
| bowl_centred | ×1 | [0.000, 0.000] | [0.083, 0.158] | [0.055, 0.130] | [0.000, 0.000] | [0.000, 0.000] |
| bowl_centred | ×8 | [0.010, 0.080] | [0.155, 0.257] | [0.187, 0.377] | [0.020, 0.085] | [0.063, 0.160] |
| saddle | ×1 | [0.000, 0.000] | [0.020, 0.080] | [0.033, 0.132] | [0.000, 0.000] | [0.000, 0.000] |
| saddle | ×8 | [0.015, 0.082] | [0.078, 0.317] | [0.062, 0.200] | [0.000, 0.008] | [0.023, 0.117] |
| choice_x_numeric | ×1 | [0.000, 0.000] | [0.100, 0.625] | [0.000, 0.000] | [0.000, 0.000] | [0.000, 0.000] |
| choice_x_numeric | ×8 | [0.000, 0.075] | [0.100, 0.625] | [0.000, 0.150] | [0.000, 0.000] | [0.000, 0.000] |
| geometric_knob | ×1 | [0.188, 0.188] | [0.089, 1.295] | [0.074, 0.610] | [0.976, 3.140] | [3.270, 6.208] |
| geometric_knob | ×8 | [0.188, 0.188] | [0.292, 1.752] | [0.085, 1.104] | [1.583, 3.920] | [3.905, 7.464] |
| step_cliff | ×1 | [0.400, 0.400] | [0.140, 0.325] | [0.125, 0.295] | [0.030, 0.210] | [0.380, 0.590] |
| step_cliff | ×8 | [0.450, 0.665] | [0.255, 0.615] | [0.260, 0.575] | [0.110, 0.335] | [0.405, 0.705] |
| ridge_cubic | ×1 | [0.220, 0.220] | [0.045, 0.110] | [0.047, 0.109] | [0.000, 0.007] | [0.010, 0.021] |
| ridge_cubic | ×8 | [0.214, 0.385] | [0.274, 0.441] | [0.253, 0.441] | [0.052, 0.186] | [0.016, 0.085] |
| two_peaks | ×1 | [0.364, 0.364] | [0.645, 1.357] | [0.153, 0.795] | [1.247, 1.754] | [1.344, 1.754] |
| two_peaks | ×8 | [0.364, 0.364] | [0.714, 1.485] | [0.153, 0.795] | [1.180, 1.766] | [1.220, 1.886] |

### Head-to-head (Nous better / tie / worse), every cell pooled

| baseline | rule | exact tie | tie = within Nous's ε |
|---|---|---|---|
| RS | best_observed | 178 / 80 / 102 | 72 / 255 / 33 |
| RS | gp_mean | 175 / 85 / 100 | 62 / 263 / 35 |
| LHS | best_observed | 160 / 76 / 124 | 52 / 264 / 44 |
| LHS | gp_mean | 155 / 86 / 119 | 42 / 274 / 44 |
| GP-BO | best_observed | 100 / 150 / 110 | 66 / 257 / 37 |
| GP-BO | gp_mean | 83 / 166 / 111 | 56 / 264 / 40 |
| GP-BO-crude | best_observed | 122 / 146 / 92 | 75 / 260 / 25 |
| GP-BO-crude | gp_mean | 125 / 151 / 84 | 78 / 266 / 16 |

### Head-to-head by surface family (primary rule)

| family | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|
| shipped (exact) | 126 / 74 / 40 | 124 / 71 / 45 | 38 / 163 / 39 | 70 / 149 / 21 |
| shipped (within ε) | 37 / 201 / 2 | 34 / 205 / 1 | 20 / 219 / 1 | 34 / 205 / 1 |
| non-quadratic (exact) | 52 / 6 / 62 | 36 / 5 / 79 | 45 / 3 / 72 | 55 / 2 / 63 |
| non-quadratic (within ε) | 35 / 54 / 31 | 18 / 59 / 43 | 36 / 45 / 39 | 44 / 61 / 15 |
| many-knob sparse (exact) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| many-knob sparse (within ε) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

### Wilson 95% intervals on the pooled head-to-head proportions (primary rule)

| baseline | n | P(Nous better), exact | P(Nous worse), exact | P(better), within ε | P(worse), within ε |
|---|---|---|---|---|---|
| RS | 360 | 0.49 [0.44, 0.55] | 0.28 [0.24, 0.33] | 0.20 [0.16, 0.24] | 0.09 [0.07, 0.13] |
| LHS | 360 | 0.44 [0.39, 0.50] | 0.34 [0.30, 0.39] | 0.14 [0.11, 0.18] | 0.12 [0.09, 0.16] |
| GP-BO | 360 | 0.23 [0.19, 0.28] | 0.31 [0.26, 0.36] | 0.16 [0.12, 0.20] | 0.11 [0.08, 0.15] |
| GP-BO-crude | 360 | 0.35 [0.30, 0.40] | 0.23 [0.19, 0.28] | 0.22 [0.18, 0.26] | 0.04 [0.03, 0.07] |

### Anytime regret (mean normalised regret at fractions of N, bootstrap 95% over seeds)

Nous: the best-so-far always-admissible measured configuration after its first n runs (its campaign is NOT stopped there: this is where its run sequence stands). Baselines: their primary-rule pick on the prefix of their own measurements. N is Nous's own stopping budget.

| family | method | 10% N | 20% N | 40% N | 60% N | 80% N | 100% N |
|---|---|---|---|---|---|---|---|
| shipped | Nous | 0.103 [0.102, 0.104] | 0.103 [0.102, 0.104] | 0.077 [0.076, 0.078] | 0.015 [0.013, 0.016] | 0.004 [0.002, 0.005] | 0.002 [0.002, 0.003] |
| shipped | RS | 0.177 [0.160, 0.195] | 0.104 [0.091, 0.119] | 0.053 [0.042, 0.064] | 0.039 [0.030, 0.049] | 0.030 [0.023, 0.038] | 0.024 [0.019, 0.032] |
| shipped | LHS | 0.178 [0.150, 0.210] | 0.097 [0.083, 0.111] | 0.048 [0.038, 0.060] | 0.035 [0.028, 0.043] | 0.030 [0.023, 0.037] | 0.021 [0.018, 0.025] |
| shipped | GP-BO | 0.161 [0.140, 0.184] | 0.062 [0.052, 0.071] | 0.023 [0.018, 0.028] | 0.013 [0.010, 0.017] | 0.009 [0.006, 0.011] | 0.008 [0.005, 0.010] |
| shipped | GP-BO-crude | 0.183 [0.162, 0.205] | 0.048 [0.037, 0.061] | 0.024 [0.020, 0.027] | 0.019 [0.015, 0.023] | 0.018 [0.014, 0.022] | 0.018 [0.014, 0.021] |
| non-quadratic | Nous | 0.251 [0.251, 0.251] | 0.254 [0.251, 0.258] | 0.218 [0.217, 0.220] | 0.076 [0.072, 0.081] | 0.071 [0.066, 0.076] | 0.070 [0.066, 0.074] |
| non-quadratic | RS | 0.239 [0.202, 0.277] | 0.168 [0.137, 0.198] | 0.147 [0.113, 0.180] | 0.124 [0.094, 0.153] | 0.119 [0.090, 0.148] | 0.113 [0.083, 0.142] |
| non-quadratic | LHS | 0.244 [0.205, 0.279] | 0.184 [0.156, 0.212] | 0.151 [0.123, 0.178] | 0.099 [0.067, 0.134] | 0.087 [0.057, 0.119] | 0.067 [0.042, 0.095] |
| non-quadratic | GP-BO | 0.282 [0.254, 0.306] | 0.224 [0.199, 0.246] | 0.141 [0.120, 0.160] | 0.129 [0.107, 0.148] | 0.124 [0.103, 0.143] | 0.124 [0.103, 0.143] |
| non-quadratic | GP-BO-crude | 0.267 [0.234, 0.296] | 0.193 [0.171, 0.214] | 0.157 [0.137, 0.175] | 0.148 [0.127, 0.166] | 0.144 [0.125, 0.161] | 0.144 [0.124, 0.160] |

### Median CPU seconds per campaign

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | 0.21 | 0.01 | 0.01 | 0.11 | 0.01 |
| additive | ×8 | 0.21 | 0.01 | 0.01 | 0.11 | 0.01 |
| bowl | ×1 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| bowl | ×8 | 0.21 | 0.01 | 0.01 | 0.08 | 0.01 |
| bowl_centred | ×1 | 0.21 | 0.02 | 0.01 | 0.12 | 0.01 |
| bowl_centred | ×8 | 0.22 | 0.01 | 0.01 | 0.11 | 0.01 |
| saddle | ×1 | 0.21 | 0.01 | 0.01 | 0.10 | 0.01 |
| saddle | ×8 | 0.21 | 0.01 | 0.01 | 0.08 | 0.01 |
| choice_x_numeric | ×1 | 0.20 | 0.01 | 0.01 | 0.06 | 0.00 |
| choice_x_numeric | ×8 | 0.20 | 0.01 | 0.01 | 0.06 | 0.00 |
| geometric_knob | ×1 | 0.20 | 0.01 | 0.01 | 0.10 | 0.01 |
| geometric_knob | ×8 | 0.21 | 0.01 | 0.01 | 0.09 | 0.01 |
| step_cliff | ×1 | 0.22 | 0.01 | 0.01 | 0.09 | 0.01 |
| step_cliff | ×8 | 0.21 | 0.01 | 0.01 | 0.08 | 0.01 |
| ridge_cubic | ×1 | 0.22 | 0.01 | 0.02 | 0.12 | 0.01 |
| ridge_cubic | ×8 | 0.21 | 0.01 | 0.01 | 0.11 | 0.01 |
| two_peaks | ×1 | 0.20 | 0.01 | 0.01 | 0.09 | 0.01 |
| two_peaks | ×8 | 0.21 | 0.01 | 0.01 | 0.08 | 0.01 |

_GP-BO had to re-pick an only-failed configuration 0 time(s) (every candidate had failed)._
<!-- END GENERATED audit-repro -->


## Results: ablations (D4; seeds 1-8, noise ×1/×4)

<!-- BEGIN GENERATED ablations -->
_Generated by `python -m benchmarks.optimization.run --ablations --workers 3 --cache-dir <cache-dir>` at checkout bd97bf6977f25aac4f1fa1df85167f0747e76aff; seeds [1, 2, 3, 4, 5, 6, 7, 8], noise [1.0, 4.0]; Nous digest(s) 44d94bc5ee2a41b2, benchmark digest 2a042c84120bb891._

### Ablations: each arm against the default on the same seeds

Δ = mean paired normalised regret, arm minus default, bootstrap 95% over seeds; negative favours the arm. N = mean runs. cert/false per arm.

**nous+alloc** — design.confirm.allocate: {seats: 2} (WP-D D1), confirm replicates at the raised floor.

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
| two_peaks | ×1 | 8 | 0.364 → 0.364 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| two_peaks | ×4 | 8 | 0.364 → 0.364 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |

**nous+alloc+bo** — as nous+alloc, plus planner.bo (the optional TPE proposer, module defaults); BO proposals reach only the allocate pool.

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
| two_peaks | ×1 | 8 | 0.364 → 0.364 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |
| two_peaks | ×4 | 8 | 0.364 → 0.364 | 0.0000 [0.0000, 0.0000] | 44.0 → 47.0 | 0/0 | 0/0 | 0 |

**nous-order** — run-order randomization OFF: every design and confirm block executes in design order (the drift ablation).

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
_Generated by `python -m benchmarks.optimization.run --mo --workers 3 --cache-dir <cache-dir>` at checkout bd97bf6977f25aac4f1fa1df85167f0747e76aff; seeds [1, 2, 3, 4, 5, 6, 7, 8]; Nous digest(s) 44d94bc5ee2a41b2, benchmark digest(s) 2a042c84120bb891._

### Hypervolume regret at the matched budget (mean [bootstrap 95%]; lower is better)

Each baseline row is at the SAME arm's per-seed budget. h2h = arm better / tie / worse than the baseline.

| surface | arm | N | Nous | cert/false | RS | LHS | ParEGO | h2h RS | h2h LHS | h2h ParEGO |
|---|---|---|---|---|---|---|---|---|---|---|
| pareto_convex | nous | 56-62 | 0.004 [0.004, 0.004] | 8/0 of 8 | 0.068 [0.047, 0.091] | 0.045 [0.041, 0.049] | 0.008 [0.001, 0.017] | 8 / 0 / 0 | 8 / 0 / 0 | 3 / 0 / 5 |
| pareto_concave | nous | 56-62 | 0.007 [0.007, 0.007] | 8/0 of 8 | 0.097 [0.076, 0.116] | 0.075 [0.059, 0.094] | 0.002 [0.000, 0.003] | 8 / 0 / 0 | 8 / 0 / 0 | 0 / 0 / 8 |
| pareto_with_constraint | nous | 62 | 0.068 [0.044, 0.094] | 1/0 of 8 | 0.068 [0.060, 0.075] | 0.059 [0.044, 0.076] | 0.045 [0.039, 0.051] | 3 / 0 / 5 | 4 / 0 / 4 | 2 / 0 / 6 |
| pareto_three | nous | 84 | 0.155 [0.149, 0.161] | 5/0 of 8 | 0.153 [0.137, 0.170] | 0.140 [0.131, 0.151] | 0.042 [0.037, 0.048] | 3 / 0 / 5 | 2 / 0 / 6 | 0 / 0 / 8 |
| pareto_choice_split | nous | 56 | 0.045 [0.043, 0.049] | 0/0 of 8 | 0.008 [0.003, 0.014] | 0.003 [0.001, 0.007] | 0.009 [0.001, 0.019] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_noisy | nous | 62 | 0.027 [0.015, 0.040] | 0/0 of 8 | 0.086 [0.075, 0.099] | 0.072 [0.058, 0.085] | 0.015 [0.007, 0.024] | 8 / 0 / 0 | 7 / 0 / 1 | 3 / 0 / 5 |
| pareto_convex_min | nous | 56-62 | 0.004 [0.004, 0.004] | 8/0 of 8 | 0.054 [0.040, 0.070] | 0.056 [0.042, 0.071] | 0.004 [0.000, 0.010] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_three_noisy | nous | 84 | 0.236 [0.228, 0.243] | 0/0 of 8 | 0.160 [0.150, 0.169] | 0.173 [0.160, 0.187] | 0.084 [0.074, 0.093] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_three_discrete | nous | 84 | 0.006 [0.003, 0.008] | 6/0 of 8 | 0.058 [0.030, 0.085] | 0.058 [0.046, 0.072] | 0.003 [0.001, 0.005] | 7 / 0 / 1 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_convex | nous+alloc | 56-62 | 0.004 [0.004, 0.004] | 8/0 of 8 | 0.068 [0.047, 0.091] | 0.045 [0.041, 0.049] | 0.008 [0.001, 0.017] | 8 / 0 / 0 | 8 / 0 / 0 | 3 / 0 / 5 |
| pareto_concave | nous+alloc | 56-62 | 0.007 [0.007, 0.007] | 8/0 of 8 | 0.097 [0.076, 0.116] | 0.075 [0.059, 0.094] | 0.002 [0.000, 0.003] | 8 / 0 / 0 | 8 / 0 / 0 | 0 / 0 / 8 |
| pareto_with_constraint | nous+alloc | 62-80 | 0.039 [0.030, 0.053] | 2/0 of 8 | 0.055 [0.042, 0.067] | 0.034 [0.028, 0.041] | 0.039 [0.031, 0.047] | 5 / 0 / 3 | 4 / 0 / 4 | 5 / 0 / 3 |
| pareto_three | nous+alloc | 84-108 | 0.148 [0.133, 0.161] | 5/0 of 8 | 0.149 [0.130, 0.169] | 0.135 [0.127, 0.145] | 0.041 [0.036, 0.047] | 4 / 0 / 4 | 2 / 0 / 6 | 0 / 0 / 8 |
| pareto_choice_split | nous+alloc | 56-74 | 0.041 [0.032, 0.048] | 0/0 of 8 | 0.005 [0.002, 0.010] | 0.003 [0.001, 0.007] | 0.008 [0.001, 0.016] | 0 / 0 / 8 | 0 / 0 / 8 | 1 / 0 / 7 |
| pareto_noisy | nous+alloc | 62-80 | 0.013 [0.007, 0.020] | 0/0 of 8 | 0.071 [0.056, 0.086] | 0.067 [0.054, 0.080] | 0.015 [0.007, 0.023] | 8 / 0 / 0 | 8 / 0 / 0 | 4 / 0 / 4 |
| pareto_convex_min | nous+alloc | 56-62 | 0.004 [0.004, 0.004] | 8/0 of 8 | 0.054 [0.040, 0.070] | 0.056 [0.042, 0.071] | 0.004 [0.000, 0.010] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_three_noisy | nous+alloc | 84 | 0.236 [0.228, 0.243] | 0/0 of 8 | 0.160 [0.150, 0.169] | 0.173 [0.160, 0.187] | 0.084 [0.074, 0.093] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_three_discrete | nous+alloc | 84 | 0.003 [0.002, 0.005] | 6/0 of 8 | 0.058 [0.030, 0.085] | 0.058 [0.046, 0.072] | 0.003 [0.001, 0.005] | 7 / 0 / 1 | 8 / 0 / 0 | 3 / 0 / 5 |
| pareto_convex | nous+alloc+bo | 56-62 | 0.004 [0.003, 0.004] | 8/0 of 8 | 0.068 [0.047, 0.091] | 0.045 [0.041, 0.049] | 0.008 [0.001, 0.017] | 8 / 0 / 0 | 8 / 0 / 0 | 3 / 0 / 5 |
| pareto_concave | nous+alloc+bo | 59-62 | 0.002 [0.001, 0.003] | 8/0 of 8 | 0.096 [0.076, 0.115] | 0.072 [0.056, 0.091] | 0.001 [0.000, 0.002] | 8 / 0 / 0 | 8 / 0 / 0 | 1 / 0 / 7 |
| pareto_with_constraint | nous+alloc+bo | 62-80 | 0.067 [0.054, 0.077] | 0/0 of 8 | 0.055 [0.042, 0.067] | 0.034 [0.028, 0.041] | 0.039 [0.031, 0.047] | 1 / 0 / 7 | 0 / 0 / 8 | 2 / 0 / 6 |
| pareto_three | nous+alloc+bo | 84-108 | 0.148 [0.133, 0.161] | 5/0 of 8 | 0.149 [0.130, 0.169] | 0.135 [0.127, 0.145] | 0.041 [0.036, 0.047] | 4 / 0 / 4 | 2 / 0 / 6 | 0 / 0 / 8 |
| pareto_choice_split | nous+alloc+bo | 56-74 | 0.041 [0.032, 0.048] | 0/0 of 8 | 0.005 [0.002, 0.010] | 0.003 [0.001, 0.007] | 0.008 [0.001, 0.016] | 0 / 0 / 8 | 0 / 0 / 8 | 1 / 0 / 7 |
| pareto_noisy | nous+alloc+bo | 62-80 | 0.012 [0.005, 0.019] | 0/0 of 8 | 0.071 [0.056, 0.086] | 0.067 [0.054, 0.080] | 0.015 [0.007, 0.023] | 8 / 0 / 0 | 8 / 0 / 0 | 4 / 0 / 4 |
| pareto_convex_min | nous+alloc+bo | 59-62 | 0.004 [0.004, 0.005] | 8/0 of 8 | 0.054 [0.040, 0.070] | 0.058 [0.043, 0.073] | 0.002 [0.000, 0.005] | 8 / 0 / 0 | 8 / 0 / 0 | 2 / 0 / 6 |
| pareto_three_noisy | nous+alloc+bo | 84 | 0.236 [0.228, 0.243] | 0/0 of 8 | 0.160 [0.150, 0.169] | 0.173 [0.160, 0.187] | 0.084 [0.074, 0.093] | 0 / 0 / 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| pareto_three_discrete | nous+alloc+bo | 84 | 0.003 [0.002, 0.005] | 6/0 of 8 | 0.058 [0.030, 0.085] | 0.058 [0.046, 0.072] | 0.003 [0.001, 0.005] | 7 / 0 / 1 | 8 / 0 / 0 | 3 / 0 / 5 |

### Anytime HV regret, pooled over surfaces (bootstrap 95% over seeds)

Baselines at the default arm's N.

| method | 10% N | 20% N | 40% N | 60% N | 80% N | 100% N |
|---|---|---|---|---|---|---|
| nous | 0.379 [0.379, 0.379] | 0.288 [0.288, 0.288] | 0.156 [0.153, 0.160] | 0.082 [0.080, 0.084] | 0.054 [0.052, 0.056] | 0.051 [0.049, 0.053] |
| nous+alloc | 0.378 [0.376, 0.379] | 0.288 [0.288, 0.288] | 0.144 [0.140, 0.148] | 0.077 [0.073, 0.081] | 0.052 [0.049, 0.056] | 0.047 [0.046, 0.049] |
| nous+alloc+bo | 0.378 [0.376, 0.379] | 0.288 [0.288, 0.288] | 0.144 [0.140, 0.148] | 0.078 [0.074, 0.082] | 0.052 [0.049, 0.055] | 0.047 [0.045, 0.048] |
| RS | 0.384 [0.374, 0.393] | 0.261 [0.244, 0.279] | 0.166 [0.151, 0.181] | 0.125 [0.116, 0.133] | 0.101 [0.096, 0.106] | 0.084 [0.079, 0.088] |
| LHS | 0.348 [0.334, 0.363] | 0.238 [0.228, 0.251] | 0.155 [0.145, 0.165] | 0.115 [0.109, 0.121] | 0.091 [0.087, 0.094] | 0.076 [0.071, 0.080] |
| ParEGO | 0.327 [0.317, 0.338] | 0.129 [0.120, 0.140] | 0.065 [0.061, 0.069] | 0.042 [0.038, 0.045] | 0.029 [0.027, 0.031] | 0.024 [0.021, 0.026] |

**Certification soundness (front certificates):** nous: 36 certified of 72, **0 false**; nous+alloc: 37 certified of 72, **0 false**; nous+alloc+bo: 35 certified of 72, **0 false**.
<!-- END GENERATED mo -->
