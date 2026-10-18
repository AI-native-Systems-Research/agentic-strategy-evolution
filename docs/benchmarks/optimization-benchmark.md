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
_Tables aggregated by `python -m benchmarks.optimization.run --workers 3 --cache-dir <cache-dir>` at checkout fd2e7227ca60ed93d2e058ad7ab0bedc4e7d08fc (Nous 0.5.0); seeds [1, 2, 3, 4, 5, 6, 7, 8], noise multipliers [1.0, 4.0]. Rows come from the resume cache and record the code they were produced under: Nous source digest(s) 10d74ceaa7add3b7; benchmark code digest(s) b6427c581ddb8006._

### Mean true regret per cell (lower is better)

| surface | noise | N | Nous | cert/false | RS (obs) | LHS (obs) | GP-BO (GP mean) | GP-BO-crude (GP mean) | RS (GP mean) | LHS (GP mean) | GP-BO (obs) | GP-BO-crude (obs) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 33 | 0.000 | 7/0 of 8 | 0.156 | 0.250 | 0.000 | 0.000 | 0.150 | 0.250 | 0.000 | 0.000 |
| additive | ×4 | 33 | 0.025 | 1/0 of 8 | 0.156 | 0.281 | 0.000 | 0.050 | 0.150 | 0.269 | 0.044 | 0.050 |
| interaction_only | ×1 | 29 | 0.000 | 7/0 of 8 | 0.165 | 0.105 | 0.000 | 0.000 | 0.165 | 0.105 | 0.000 | 0.000 |
| interaction_only | ×4 | 29 | 0.000 | 3/0 of 8 | 0.285 | 0.140 | 0.000 | 0.035 | 0.250 | 0.140 | 0.000 | 0.000 |
| bowl | ×1 | 29 | 0.000 | 6/0 of 8 | 0.138 | 0.056 | 0.000 | 0.000 | 0.138 | 0.056 | 0.000 | 0.000 |
| bowl | ×4 | 29 | 0.006 | 4/0 of 8 | 0.194 | 0.094 | 0.031 | 0.025 | 0.163 | 0.069 | 0.062 | 0.050 |
| bowl_centred | ×1 | 33 | 0.000 | 7/0 of 8 | 0.144 | 0.206 | 0.000 | 0.000 | 0.144 | 0.206 | 0.000 | 0.006 |
| bowl_centred | ×4 | 33 | 0.025 | 4/0 of 8 | 0.212 | 0.262 | 0.019 | 0.038 | 0.144 | 0.212 | 0.075 | 0.050 |
| saddle | ×1 | 29 | 0.000 | 6/0 of 8 | 0.113 | 0.044 | 0.000 | 0.000 | 0.106 | 0.044 | 0.000 | 0.006 |
| saddle | ×4 | 29 | 0.006 | 3/0 of 8 | 0.113 | 0.138 | 0.025 | 0.019 | 0.113 | 0.081 | 0.038 | 0.013 |
| choice_x_numeric | ×1 | 17 | 0.000 | 8/0 of 8 | 0.250 | 0.000 | 0.000 | 0.000 | 0.250 | 0.000 | 0.000 | 0.000 |
| choice_x_numeric | ×4 | 17 | 0.000 | 8/0 of 8 | 0.250 | 0.000 | 0.000 | 0.000 | 0.250 | 0.000 | 0.000 | 0.000 |
| drift | ×1 | 17 | 0.000 | 8/0 of 8 | 0.375 | 0.356 | 0.038 | 0.025 | 0.344 | 0.369 | 0.038 | 0.025 |
| drift | ×4 | 17 | 0.000 | 7/0 of 8 | 0.456 | 0.538 | 0.038 | 0.069 | 0.369 | 0.350 | 0.038 | 0.069 |
| sla | ×1 | 38 | 0.400 | 0/0 of 8 | 0.200 | 0.313 | 0.000 | 8.200 | 0.200 | 0.313 | 0.000 | 0.200 |
| sla | ×4 | 38 | 0.463 | 0/0 of 8 | 0.200 | 0.400 | 0.000 | 8.200 | 0.200 | 0.338 | 0.025 | 0.350 |
| infeasible_corner_interior | ×1 | 29 | 0.000 | 8/0 of 8 | 0.019 | 0.037 | 0.000 | 3.300 | 0.019 | 0.037 | 0.000 | 0.019 |
| infeasible_corner_interior | ×4 | 29 | 0.019 | 2/0 of 8 | 0.056 | 0.075 | 0.000 | 3.300 | 0.019 | 0.037 | 0.000 | 0.075 |
| nan_at_corner | ×1 | 8 | 0.000 | 0/0 of 8 | 0.744 | 0.181 | 0.000 | 0.506 | 0.744 | 0.181 | 0.000 | 0.506 |
| nan_at_corner | ×4 | 8 | 0.000 | 0/0 of 8 | 0.744 | 0.181 | 0.056 | 0.594 | 0.744 | 0.181 | 0.100 | 0.613 |
| fails_at_one_level | ×1 | 21 | 0.640 | 0/0 of 8 | 0.200 | 0.170 | 0.080 | 0.080 | 0.200 | 0.170 | 0.080 | 0.080 |
| fails_at_one_level | ×4 | 21 | 0.640 | 0/0 of 8 | 0.220 | 0.240 | 0.080 | 0.120 | 0.220 | 0.230 | 0.130 | 0.160 |
| stochastic_constraint_boundary | ×1 | 38 | 0.875 | 0/0 of 8 | 7.000 | 6.312 | 7.000 | 7.000 | 7.000 | 6.312 | 7.000 | 6.125 |
| stochastic_constraint_boundary | ×4 | 38 | 0.875 | 0/0 of 8 | 7.000 | 6.312 | 7.000 | 7.000 | 7.000 | 6.312 | 7.000 | 6.125 |
| geometric_knob | ×1 | 29 | 26.248 | 0/0 of 8 | 1.073 | 0.507 | 2.640 | 5.089 | 1.494 | 3.204 | 2.627 | 3.304 |
| geometric_knob | ×4 | 29 | 26.248 | 4/4 of 8 | 1.073 | 0.507 | 4.085 | 5.250 | 1.502 | 4.304 | 4.087 | 2.961 |
| geometric_knob_log | ×1 | 29 | 0.000 | 6/0 of 8 | 1.968 | 2.237 | 0.056 | 0.144 | 1.946 | 2.237 | 0.056 | 0.115 |
| geometric_knob_log | ×4 | 29 | 0.000 | 4/0 of 8 | 2.027 | 2.237 | 0.125 | 0.142 | 1.959 | 2.243 | 0.125 | 0.101 |
| deterministic_constraint_axis | ×1 | 39 | 0.000 | 0/0 of 8 | 1.562 | 1.938 | 0.000 | 8.100 | 1.562 | 1.938 | 0.000 | 0.100 |
| deterministic_constraint_axis | ×4 | 39 | 0.000 | 0/0 of 8 | 1.562 | 1.944 | 0.000 | 8.100 | 1.562 | 1.944 | 0.000 | 0.325 |
| step_cliff | ×1 | 29 | 0.900 | 6/6 of 8 | 0.200 | 0.425 | 0.225 | 0.500 | 0.200 | 0.425 | 0.225 | 0.337 |
| step_cliff | ×4 | 29 | 0.900 | 5/5 of 8 | 0.200 | 0.525 | 0.300 | 0.600 | 0.200 | 0.550 | 0.300 | 0.487 |
| ridge_cubic | ×1 | 33 | 0.504 | 7/7 of 8 | 0.081 | 0.079 | 0.003 | 0.014 | 0.085 | 0.079 | 0.003 | 0.010 |
| ridge_cubic | ×4 | 33 | 0.504 | 4/4 of 8 | 0.270 | 0.165 | 0.030 | 0.130 | 0.169 | 0.165 | 0.063 | 0.190 |
| two_peaks | ×1 | 29 | 1.754 | 0/0 of 8 | 1.020 | 1.199 | 1.534 | 1.412 | 1.020 | 1.199 | 1.534 | 1.412 |
| two_peaks | ×4 | 29 | 1.754 | 0/0 of 8 | 1.055 | 1.225 | 1.553 | 1.607 | 1.020 | 1.199 | 1.578 | 1.607 |
| sparse_knobs_6 | ×1 | 93 | 0.000 | 6/0 of 8 | 0.478 | 0.680 | 0.000 | 0.000 | 0.478 | 0.680 | 0.000 | 0.000 |
| sparse_knobs_6 | ×4 | 93 | 0.010 | 5/0 of 8 | 0.573 | 0.715 | 0.010 | 0.054 | 0.478 | 0.715 | 0.044 | 0.054 |
| sparse_knobs_8 | ×1 | 161 | 0.000 | 8/0 of 8 | 0.250 | 0.485 | 0.000 | 0.000 | 0.250 | 0.485 | 0.000 | 0.000 |
| sparse_knobs_8 | ×4 | 161 | 0.000 | 4/0 of 8 | 0.335 | 0.527 | 0.000 | 0.057 | 0.300 | 0.527 | 0.010 | 0.067 |
| sparse_knobs_12 | ×1 | 553 | 0.000 | 8/0 of 8 | 0.106 | 0.195 | 0.000 | 0.000 | 0.106 | 0.184 | 0.000 | 0.000 |
| sparse_knobs_12 | ×4 | 553 | 0.000 | 6/0 of 8 | 0.180 | 0.249 | 0.010 | 0.027 | 0.116 | 0.226 | 0.024 | 0.027 |

### Head-to-head (Nous better / tie / worse), every cell pooled

| baseline | rule | exact tie | tie = within Nous's ε |
|---|---|---|---|
| RS | best_observed | 181 / 73 / 82 | 87 / 177 / 72 |
| RS | gp_mean | 173 / 79 / 84 | 81 / 182 / 73 |
| LHS | best_observed | 182 / 77 / 77 | 106 / 166 / 64 |
| LHS | gp_mean | 179 / 80 / 77 | 102 / 171 / 63 |
| GP-BO | best_observed | 54 / 199 / 83 | 18 / 241 / 77 |
| GP-BO | gp_mean | 43 / 209 / 84 | 15 / 242 / 79 |
| GP-BO-crude | best_observed | 81 / 179 / 76 | 35 / 239 / 62 |
| GP-BO-crude | gp_mean | 125 / 142 / 69 | 80 / 197 / 59 |

### Head-to-head by surface family (primary rule)

| family | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|
| shipped (exact) | 135 / 62 / 43 | 130 / 68 / 42 | 40 / 148 / 52 | 110 / 94 / 36 |
| shipped (within ε) | 77 / 126 / 37 | 79 / 129 / 32 | 15 / 177 / 48 | 79 / 129 / 32 |
| non-quadratic (exact) | 9 / 0 / 39 | 7 / 6 / 35 | 1 / 16 / 31 | 5 / 11 / 32 |
| non-quadratic (within ε) | 1 / 12 / 35 | 4 / 12 / 32 | 0 / 17 / 31 | 1 / 20 / 27 |
| many-knob sparse (exact) | 37 / 11 / 0 | 45 / 3 / 0 | 2 / 45 / 1 | 10 / 37 / 1 |
| many-knob sparse (within ε) | 9 / 39 / 0 | 23 / 25 / 0 | 0 / 48 / 0 | 0 / 48 / 0 |

### Median CPU seconds per campaign

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | 0.16 | 0.01 | 0.01 | 0.07 | 0.01 |
| additive | ×4 | 0.15 | 0.01 | 0.01 | 0.07 | 0.01 |
| interaction_only | ×1 | 0.11 | 0.01 | 0.01 | 0.34 | 0.10 |
| interaction_only | ×4 | 0.11 | 0.01 | 0.01 | 0.34 | 0.09 |
| bowl | ×1 | 0.14 | 0.01 | 0.01 | 0.06 | 0.01 |
| bowl | ×4 | 0.15 | 0.01 | 0.01 | 0.05 | 0.01 |
| bowl_centred | ×1 | 0.15 | 0.01 | 0.01 | 0.08 | 0.01 |
| bowl_centred | ×4 | 0.14 | 0.01 | 0.01 | 0.07 | 0.01 |
| saddle | ×1 | 0.14 | 0.01 | 0.01 | 0.06 | 0.01 |
| saddle | ×4 | 0.14 | 0.01 | 0.01 | 0.06 | 0.01 |
| choice_x_numeric | ×1 | 0.10 | 0.01 | 0.00 | 0.02 | 0.00 |
| choice_x_numeric | ×4 | 0.10 | 0.01 | 0.00 | 0.02 | 0.00 |
| drift | ×1 | 0.10 | 0.01 | 0.00 | 0.03 | 0.00 |
| drift | ×4 | 0.10 | 0.01 | 0.00 | 0.03 | 0.00 |
| sla | ×1 | 0.19 | 0.01 | 0.01 | 0.13 | 0.01 |
| sla | ×4 | 0.19 | 0.01 | 0.01 | 0.13 | 0.01 |
| infeasible_corner_interior | ×1 | 0.15 | 0.01 | 0.01 | 0.08 | 0.00 |
| infeasible_corner_interior | ×4 | 0.14 | 0.01 | 0.01 | 0.07 | 0.00 |
| nan_at_corner | ×1 | 0.05 | 0.00 | 0.00 | 0.01 | 0.00 |
| nan_at_corner | ×4 | 0.05 | 0.00 | 0.00 | 0.01 | 0.00 |
| fails_at_one_level | ×1 | 0.11 | 0.01 | 0.01 | 0.03 | 0.00 |
| fails_at_one_level | ×4 | 0.11 | 0.01 | 0.00 | 0.03 | 0.00 |
| stochastic_constraint_boundary | ×1 | 0.21 | 0.01 | 0.01 | 0.12 | 0.01 |
| stochastic_constraint_boundary | ×4 | 0.20 | 0.01 | 0.01 | 0.12 | 0.01 |
| geometric_knob | ×1 | 0.14 | 0.01 | 0.01 | 0.06 | 0.01 |
| geometric_knob | ×4 | 0.14 | 0.01 | 0.01 | 0.06 | 0.01 |
| geometric_knob_log | ×1 | 0.15 | 0.01 | 0.01 | 0.06 | 0.01 |
| geometric_knob_log | ×4 | 0.14 | 0.01 | 0.01 | 0.05 | 0.01 |
| deterministic_constraint_axis | ×1 | 0.22 | 0.01 | 0.01 | 0.23 | 0.02 |
| deterministic_constraint_axis | ×4 | 0.23 | 0.01 | 0.01 | 0.23 | 0.02 |
| step_cliff | ×1 | 0.14 | 0.01 | 0.01 | 0.06 | 0.01 |
| step_cliff | ×4 | 0.14 | 0.01 | 0.01 | 0.05 | 0.01 |
| ridge_cubic | ×1 | 0.14 | 0.01 | 0.01 | 0.07 | 0.01 |
| ridge_cubic | ×4 | 0.15 | 0.01 | 0.01 | 0.07 | 0.01 |
| two_peaks | ×1 | 0.14 | 0.01 | 0.01 | 0.05 | 0.01 |
| two_peaks | ×4 | 0.15 | 0.01 | 0.01 | 0.05 | 0.01 |
| sparse_knobs_6 | ×1 | 0.90 | 0.05 | 0.05 | 2.21 | 1.48 |
| sparse_knobs_6 | ×4 | 0.90 | 0.05 | 0.05 | 2.16 | 1.48 |
| sparse_knobs_8 | ×1 | 1.25 | 0.14 | 0.15 | 5.58 | 4.98 |
| sparse_knobs_8 | ×4 | 1.27 | 0.12 | 0.14 | 5.52 | 4.78 |
| sparse_knobs_12 | ×1 | 2.79 | 3.49 | 3.91 | 85.05 | 81.52 |
| sparse_knobs_12 | ×4 | 2.76 | 3.91 | 3.96 | 83.96 | 79.82 |
<!-- END GENERATED suite -->


## Results: audit reproduction (the audit's 9 surfaces, seeds 1-20, noise ×1/×8)

<!-- BEGIN GENERATED audit-repro -->
_Tables aggregated by `python -m benchmarks.optimization.run --audit-repro --workers 3 --cache-dir <cache-dir>` at checkout fd2e7227ca60ed93d2e058ad7ab0bedc4e7d08fc (Nous 0.5.0); seeds [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], noise multipliers [1.0, 8.0]. Rows come from the resume cache and record the code they were produced under: Nous source digest(s) 10d74ceaa7add3b7; benchmark code digest(s) b6427c581ddb8006._

### Mean true regret per cell (lower is better)

| surface | noise | N | Nous | cert/false | RS (obs) | LHS (obs) | GP-BO (GP mean) | GP-BO-crude (GP mean) | RS (GP mean) | LHS (GP mean) | GP-BO (obs) | GP-BO-crude (obs) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| additive | ×1 | 33 | 0.000 | 17/0 of 20 | 0.268 | 0.370 | 0.000 | 0.000 | 0.265 | 0.370 | 0.000 | 0.000 |
| additive | ×8 | 33 | 0.078 | 2/0 of 20 | 0.425 | 0.488 | 0.048 | 0.108 | 0.295 | 0.400 | 0.135 | 0.265 |
| bowl | ×1 | 29 | 0.000 | 18/0 of 20 | 0.103 | 0.083 | 0.000 | 0.003 | 0.103 | 0.080 | 0.000 | 0.003 |
| bowl | ×8 | 29 | 0.037 | 2/0 of 20 | 0.212 | 0.235 | 0.038 | 0.120 | 0.135 | 0.165 | 0.113 | 0.185 |
| bowl_centred | ×1 | 33 | 0.000 | 17/0 of 20 | 0.138 | 0.165 | 0.000 | 0.005 | 0.138 | 0.165 | 0.000 | 0.005 |
| bowl_centred | ×8 | 33 | 0.090 | 3/0 of 20 | 0.302 | 0.302 | 0.028 | 0.150 | 0.153 | 0.190 | 0.058 | 0.210 |
| saddle | ×1 | 29 | 0.000 | 18/0 of 20 | 0.135 | 0.122 | 0.000 | 0.000 | 0.132 | 0.122 | 0.000 | 0.008 |
| saddle | ×8 | 29 | 0.040 | 2/0 of 20 | 0.285 | 0.270 | 0.003 | 0.053 | 0.230 | 0.180 | 0.020 | 0.097 |
| choice_x_numeric | ×1 | 17-25 | 0.000 | 20/0 of 20 | 0.550 | 0.150 | 0.000 | 0.000 | 0.550 | 0.150 | 0.000 | 0.000 |
| choice_x_numeric | ×8 | 17-25 | 0.000 | 17/0 of 20 | 0.550 | 0.150 | 0.000 | 0.000 | 0.550 | 0.150 | 0.000 | 0.000 |
| geometric_knob | ×1 | 29 | 26.248 | 0/0 of 20 | 2.280 | 0.424 | 2.560 | 4.748 | 2.846 | 4.023 | 2.553 | 3.239 |
| geometric_knob | ×8 | 29 | 23.648 | 6/6 of 20 | 2.569 | 0.819 | 4.446 | 5.640 | 3.935 | 6.387 | 4.125 | 4.282 |
| step_cliff | ×1 | 29 | 0.900 | 18/18 of 20 | 0.285 | 0.295 | 0.105 | 0.480 | 0.285 | 0.295 | 0.105 | 0.335 |
| step_cliff | ×8 | 29 | 0.940 | 7/7 of 20 | 0.375 | 0.415 | 0.290 | 0.530 | 0.455 | 0.430 | 0.355 | 0.430 |
| ridge_cubic | ×1 | 33 | 0.504 | 17/17 of 20 | 0.082 | 0.070 | 0.007 | 0.017 | 0.083 | 0.070 | 0.007 | 0.013 |
| ridge_cubic | ×8 | 21-33 | 0.540 | 4/3 of 20 | 0.297 | 0.215 | 0.119 | 0.089 | 0.219 | 0.174 | 0.164 | 0.212 |
| two_peaks | ×1 | 29 | 1.754 | 0/0 of 20 | 1.116 | 1.274 | 1.510 | 1.549 | 1.113 | 1.270 | 1.510 | 1.529 |
| two_peaks | ×8 | 29 | 1.782 | 2/2 of 20 | 1.235 | 1.346 | 1.496 | 1.599 | 1.125 | 1.380 | 1.542 | 1.641 |

### Head-to-head (Nous better / tie / worse), every cell pooled

| baseline | rule | exact tie | tie = within Nous's ε |
|---|---|---|---|
| RS | best_observed | 160 / 62 / 138 | 56 / 184 / 120 |
| RS | gp_mean | 149 / 67 / 144 | 41 / 200 / 119 |
| LHS | best_observed | 151 / 75 / 134 | 62 / 180 / 118 |
| LHS | gp_mean | 144 / 77 / 139 | 52 / 192 / 116 |
| GP-BO | best_observed | 42 / 174 / 144 | 12 / 231 / 117 |
| GP-BO | gp_mean | 21 / 186 / 153 | 4 / 235 / 121 |
| GP-BO-crude | best_observed | 70 / 158 / 132 | 23 / 227 / 110 |
| GP-BO-crude | gp_mean | 53 / 171 / 136 | 12 / 236 / 112 |

### Head-to-head by surface family (primary rule)

| family | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|
| shipped (exact) | 135 / 59 / 46 | 126 / 64 / 50 | 13 / 157 / 70 | 35 / 150 / 55 |
| shipped (within ε) | 46 / 153 / 41 | 49 / 151 / 40 | 1 / 199 / 40 | 3 / 197 / 40 |
| non-quadratic (exact) | 25 / 3 / 92 | 25 / 11 / 84 | 8 / 29 / 83 | 18 / 21 / 81 |
| non-quadratic (within ε) | 10 / 31 / 79 | 13 / 29 / 78 | 3 / 36 / 81 | 9 / 39 / 72 |
| many-knob sparse (exact) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| many-knob sparse (within ε) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

### Median CPU seconds per campaign

| surface | noise | Nous | RS | LHS | GP-BO | GP-BO-crude |
|---|---|---|---|---|---|---|
| additive | ×1 | 0.14 | 0.01 | 0.01 | 0.07 | 0.01 |
| additive | ×8 | 0.14 | 0.01 | 0.01 | 0.07 | 0.01 |
| bowl | ×1 | 0.13 | 0.01 | 0.01 | 0.05 | 0.01 |
| bowl | ×8 | 0.13 | 0.01 | 0.01 | 0.05 | 0.01 |
| bowl_centred | ×1 | 0.14 | 0.01 | 0.01 | 0.08 | 0.01 |
| bowl_centred | ×8 | 0.14 | 0.01 | 0.01 | 0.07 | 0.01 |
| saddle | ×1 | 0.13 | 0.01 | 0.01 | 0.06 | 0.01 |
| saddle | ×8 | 0.13 | 0.01 | 0.01 | 0.05 | 0.01 |
| choice_x_numeric | ×1 | 0.10 | 0.01 | 0.01 | 0.02 | 0.00 |
| choice_x_numeric | ×8 | 0.10 | 0.01 | 0.01 | 0.02 | 0.00 |
| geometric_knob | ×1 | 0.13 | 0.01 | 0.01 | 0.06 | 0.01 |
| geometric_knob | ×8 | 0.13 | 0.01 | 0.01 | 0.06 | 0.01 |
| step_cliff | ×1 | 0.13 | 0.01 | 0.01 | 0.06 | 0.01 |
| step_cliff | ×8 | 0.13 | 0.01 | 0.01 | 0.05 | 0.01 |
| ridge_cubic | ×1 | 0.14 | 0.01 | 0.01 | 0.07 | 0.01 |
| ridge_cubic | ×8 | 0.14 | 0.01 | 0.01 | 0.07 | 0.01 |
| two_peaks | ×1 | 0.13 | 0.01 | 0.01 | 0.06 | 0.01 |
| two_peaks | ×8 | 0.14 | 0.01 | 0.01 | 0.05 | 0.01 |
<!-- END GENERATED audit-repro -->


## Results: ablations (D4; seeds 1-8, noise ×1/×4)

<!-- BEGIN GENERATED ablations -->
<!-- END GENERATED ablations -->


## Results: multi-objective (seeds 1-8)

<!-- BEGIN GENERATED mo -->
<!-- END GENERATED mo -->
