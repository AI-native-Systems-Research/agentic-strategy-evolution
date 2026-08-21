# Field test: `kind: optimization` vs `kind: reflective` on BLIS

**Status:** design, pending review
**Date:** 2026-08-21
**Target:** BLIS (`inference-sim`) pinned at `bb1a5264`
**Related:** `2026-08-16-compiled-policy-design.md` (binding authority for the
compiled policy), `../plans/2026-08-16-compiled-policy.md`

## 1. What this is, and what it is not

This is a **field test**: point both campaign kinds at a real target and measure
what each delivers on three axes — **token budget**, **correctness**,
**optimality**. It is *not* an adversarial validation of `kind: optimization`.

The distinction is load-bearing and constrains the design:

- No planted defects. No objective chosen because it traps a naive optimizer.
- The factor space is what a competent campaign author would actually write.
- The design **must let `kind: optimization` lose**, and must report that as
  prominently as a win. Named failure modes it must be able to surface:
  the compiled epoch spends its pre-registered budget on factors that turn out
  not to matter and cannot notice, while the reflective arm redirects between
  iterations; or the epoch returns `terminal_best` rather than `certified` and
  the honest reading is "indistinguishable at this budget" — a weaker
  deliverable than a reflective campaign's confident (if less warranted)
  recommendation.

### 1.1 Phasing (approved)

| Phase | Axes | Gate |
|---|---|---|
| **1** | token budget, correctness | none — measurable today |
| **2** | optimality | Phase 0 liveness + objective gate below must pass |

Phase 1's two axes need no response surface: tokens come from each arm's
`llm_metrics.jsonl`, correctness from BLIS's own `go test ./sim/kv/`. Phase 2
needs a working objective, which pilot work showed is the hard part. Phase 1
ships independently rather than being held hostage to Phase 2.

## 2. Total isolation

Isolation is a **validity requirement**, not hygiene. If either arm can see the
other's artifacts or share its target tree, the token and correctness numbers
stop meaning anything.

| Seam | Mechanism | Verification |
|---|---|---|
| Target code | `git clone` of BLIS at `bb1a5264` into `arms/<arm>/blis/` | `git -C arms/<arm>/blis rev-parse HEAD` recorded in a pre-launch manifest |
| Campaign artifacts | `NOUS_CAMPAIGN_PARENT=<root>/arms/<arm>/campaign` | each arm's `llm_metrics.jsonl` is the sole source for its token vector |
| Knowledge | fresh `principles.json`; no shared wiki/registry; no shared run cache | post-hoc grep of each arm's work_dir for the other's `run_id` — must be zero hits |

**Clone, not worktree.** `orchestrator/optimize/build.py`'s
`check_build_touched_repo` exists precisely for this failure: a successful build
against a pristine tree means the agent "may have edited a DIFFERENT checkout of
the same project — which is silent, and which corrupts a parallel arm rather
than failing. Observed for real against a worktree."

**No shared run cache.** A cache warmed by one arm is a covert channel: the
other arm's wall-clock and measured-run count would be contaminated invisibly.
BLIS is deterministic, so identical configurations give identical results
anyway — the noise-matching benefit a shared cache would buy is already free.

**Steelmanning vs isolation.** The reflective arm is steelmanned through equal
campaign-authoring quality, the same objective/constraints/`locked_parameters`,
and a matched run budget — but **not** through prior `principles.json` from
earlier BLIS campaigns. Isolation wins, because prior principles encode
knowledge derived from this same target. Recorded as a stated caveat.

The prior `paper-memorytime-mirage` campaign (16 calls, 167k in / 308k out,
$25.39, 3 iterations) is a **calibration reference** for what a reflective
campaign costs on this target. It is not an input to either arm.

## 3. Both arms author natively

Each arm gets its own clone and must author whatever mechanism it needs.
For `kind: optimization` that is the `build` stage; for `kind: reflective` it is
ordinary iteration-time editing.

**Do not hand-author the mechanism first.** Pre-authoring it would mean the
optimization arm arrives at a target where the work was already done while the
reflective arm does its own — a confound, and it would also make `build`'s
success unobservable, which is the point of measuring it.

**`build` succeeding is a measured outcome, not a precondition.** Distinct,
reportable results:

| Outcome | Meaning |
|---|---|
| mechanism compiles, declared native tests pass | clean success |
| compiles, native tests fail | `verify` hard-fails on a correctness relation |
| does not compile | `verify` hard-fails; test command reports nothing |
| tests never ran | `relations.reconcile` fails closed — a declared `native_test` absent from results is `passed=False` with "declared but not executed" |
| guard test deleted rather than updated | see §5.2 — the sharpest correctness signal |

## 4. The build phase, specified

`build` spends exactly one agent call and makes no correctness judgement;
`verify` remains the gate, so the stage that writes the code is never the stage
that certifies it.

### 4.1 Authorship target

**`arc` eviction for the CPU offload tier.** Chosen because it is a *real*
deferred mechanism, not a synthetic one:

- `sim/kv/offload_chain.go:120-121` panics: `H1 supports eviction_policy "lru"
  only; %q (e.g. arc) is a follow-up`.
- vLLM exposes `eviction_policy: arc`, and BLIS's H5 deliberately captured the
  full vLLM config surface so that anything vLLM accepts either maps or fails
  loudly — never silently ignored.
- The CPU tier's eviction API is small and well-bounded:
  `sim/kv/offload_cputier.go` exposes `evict(n)`, `touch`, `touchKey`,
  `lookup`, `pin`/`unpin`, `evictableCount`, `scanEvictable`.

Optional second target: `blocks_per_chunk > 1` (chunk coalescing), also a
deliberate deferral (`offload_chain.go:118`).

**This is not "finishing an incomplete connector."** All five declared offload
holes landed (H1 #1590, H2 #1588, H3 #1591, H4 #1589, H5 #1587) and the vLLM
mirroring is faithful. Two knobs were explicitly scoped out as follow-ups with
fail-loud guards. The campaign implements a documented follow-up.

### 4.2 Relations the campaign declares

Each becomes a `native_test` that `verify` reconciles fail-closed:

| id | kind | statement | native_test |
|---|---|---|---|
| `R_ARC_LRU_PARITY` | correctness | with `eviction_policy: lru` the tier is byte-identical to the pre-change build | `sim/kv -run TestOffloadChain_LRUUnchanged` |
| `R_ARC_CAPACITY` | correctness | the CPU tier never exceeds its configured block capacity under ARC | `sim/kv -run TestOffloadCPUTier_ARCRespectsCapacity` |
| `R_ARC_PIN` | correctness | a pinned block is never evicted under ARC (the `cascade` write-through invariant, BC-C3) | `sim/kv -run TestOffloadCPUTier_ARCNeverEvictsPinned` |
| `B_ARC_HIT` | behavioral | ARC's hit rate is not worse than LRU's on a recency+frequency mixed trace | `sim/kv -run TestOffloadCPUTier_ARCHitRateVsLRU` |

`R_ARC_PIN` is the one most likely to catch a plausible-but-wrong
implementation: `cascade()` pins a block per secondary tier for the duration of
its write, and an ARC implementation that tracks its own recency/frequency lists
without honouring `ref_cnt` would evict in-flight blocks.

Behavioral failures are recorded as findings and never fail the campaign
(`relations.classify_failures`) — a monotonicity surprise is a discovery.

### 4.3 `mechanism_paths`

```yaml
optimization:
  build_checks:
    mechanism_paths: [sim/kv/, sim/kv_offload_config.go]
```

Required. BLIS's own `go test` writes into the tree, and whole-tree hashing
would read those artifacts as mechanism drift. Scoping narrows both halves of
the oracle (the tracked `git diff HEAD -- <paths>` and the untracked listing).

### 4.4 Test command

```
go test ./sim/kv/ -run '<relation regex>' -json
```

`sim/kv` passes clean at `bb1a5264` (verified: `ok ... 0.909s`), so any failure
is attributable to the arm's own change.

## 5. Correctness scoring

Three questions, each answerable from artifacts:

1. **Is the recommended configuration valid?** Re-measure it independently;
   do the declared constraints hold?
2. **Did the arm's claims match what it measured?** Spec fidelity — the
   validator hard-fails a bundle whose `verified_parameters` deviate from
   `locked_parameters`. The reflective kind has a documented history of
   violating this on this exact target (`paper-memorytime-mirage` iter-1
   silently rewrote four locked workload parameters; see
   `docs/friction-245-resolution.md`).
3. **Did the authored mechanism pass BLIS's native tests?**

### 5.2 The stale guard test

`sim/kv/offload_chain_test.go:80` currently asserts that ARC **panics**:

```go
mustPanic(t, "arc eviction", func() {
    c := enabledOffloadCfg(1<<20, 4096, 1)
    c.EvictionPolicy = "arc"
    NewOffloadCache(gpu, c)
})
```

Any arm that implements ARC **must** change this test, because it encodes
"ARC is unsupported" — which its own change makes false. This yields an
auditable distinction no arm can game invisibly:

- **honest**: replaces the panic assertion with a test of the new behaviour
- **test-defeating**: deletes the assertion, or weakens it, to go green

Scored by reading the diff to that file. This is native to the repo, not
invented for the experiment.

## 6. The objective (Phase 2)

**Saturation is a stability property**, not a latency threshold: the in-flight
backlog grows without bound because arrivals persistently exceed service
capacity. Rising P90 is a symptom; a P90 threshold is an arbitrary SLA choice.

> **Response = λ\***, the highest **session-arrival rate** the system sustains,
> where *sustains* = `backlog-drift` reports the backlog stabilizes rather than
> growing without bound over a long open-loop run. Found by **bisection on λ**.

### 6.1 Apparatus

Open loop **and** agentic multi-turn — independent properties, both required:

```yaml
version: "2"
category: reasoning
aggregate_rate: <λ, the bisection variable>
# num_requests OMITTED — spec.go:50: "0 = unlimited (use horizon only)"
clients:
  - id: agent-heavy
    rate_fraction: 0.7
    arrival: {process: poisson}
    input_distribution:  {type: gaussian, params: {mean: 3072, std_dev: 512, min: 1024, max: 6144}}
    output_distribution: {type: gaussian, params: {mean: 384,  std_dev: 96,  min: 64,   max: 768}}
    reasoning:
      multi_turn: {max_rounds: 6, think_time_us: 250000, context_growth: accumulate}
  - id: chat-light
    rate_fraction: 0.3
    # ... shorter prompts, 2 rounds
```

Run with `--horizon <T>`, `--num-instances 8`, `--detectors backlog-drift`,
`--saturation-config` at the **60s production window**.

Why each element:

- **`num_requests` omitted** — necessary but **not sufficient**, see §6.2.1.
  A finite request budget guarantees the run drains: at λ=128 with
  `num_requests: 2000`, in-flight spiked to 583, sat flat at ~380 for the whole
  run, then fell to 0 when arrivals stopped; final slope −6.83, verdict
  `STABLE`, P90 33s.
- **`--timeout -1`** — required. With the 300s default, an overloaded run reports
  P90 TTFT pinned at ~300,000 ms (measured: 295,879 / 298,994 / 300,006 ms at
  λ = 64 / 128 / 256). That is the timeout censoring the measurement, not a
  latency, and it makes the response surface flat and uninformative near
  capacity.
- **`single_session: false`** (the default) — `sim/workload/stream.go:78`: each
  client is "a traffic source that spawns many independent, OVERLAPPING sessions
  over the horizon," with live sessions bounded by `arrival_rate ×
  session_duration` (Little's law), independent of horizon.
- **`context_growth: accumulate`** — each live session's KV footprint grows
  across its rounds, which is what makes the offload tiers consequential.
- **60s window** — a shrunken window inflates per-bucket noise and buries the
  slope.

Little's law also supplies the monotonicity bisection needs: the concurrent
working set is `λ × session_duration`, and a better cache lowers
`session_duration`, so fewer sessions are live. Independently verified that
P90 is strictly monotone in λ (426ms at λ=16 → 6,499ms at λ=256 over 7 rates).

### 6.2 Reading the verdict

The saturation report's `final` block carries **only** the level. The diagnostic
signals (`in_flight`, `running_slope`, `noise_floor`, `arrivals`,
`completions`) are per-point in `trace[]`. The adapter must read the trace.

#### 6.2.1 The trailing window always sees the drain

**Do not use the detector's `final` verdict as the bisection predicate.**
`sim/workload/stream.go:400` stops building sessions at
`s.currentTime >= s.horizon`, so **arrivals cease at the horizon while the
simulation continues to drain whatever is in flight.** Omitting `num_requests`
does not change this. The trailing window that
`--saturation-final-window` votes over is therefore precisely the region where
in-flight is collapsing to zero.

Measured at λ=64, open loop, `num_requests` omitted: `end_inflight = 0` at both a
60s and a 180s horizon, while `peak_inflight` grew 466 → 1,422. The backlog *is*
building; the final vote lands on the drain and reports `STABLE` regardless.

The predicate must instead be computed over the **arrival-active phase** — the
trace points up to the last arrival — as either:

- the OLS slope of `in_flight` against time over that phase, or
- the ratio of mean `in_flight` in the last quartile to the first quartile.

`sustained` ⇔ that slope is not reliably positive. This is the same statistic
`backlog-drift` computes; the only change is the window it is computed over. The
adapter owns this computation, which is another reason §6.3's target-side adapter
is mandatory rather than a convenience.

**Validated.** With `--timeout -1` and the active-phase window, the predicate
discriminates where the `final` verdict did not:

| λ (sessions/s) | slope/s | firstQ → lastQ | peak | P90 |
|---|---|---|---|---|
| 8 | +3.02 | 236 → 909 | 1,232 | 58s |
| 16 | +4.28 | 400 → 1,504 | 2,413 | 96s |
| 32 | +4.11 | 683 → 2,081 | 4,122 | 132s |
| 64 | +1.63 | 1,148 → 2,645 | 6,396 | 166s |

In-flight grows ~3.9× across the active phase at every rate, while the same runs'
`final` verdict said `STABLE`.

### 6.2.2 λ is sessions per second

**λ is a session-arrival rate, not a request rate.** Every rate ≥ 8 sessions/s is
already saturated, so the bisection bracket lies *below* 8, not above. The
"healthy" P90s of 276–331 ms measured earlier at λ=8 came from run-capped runs
whose backlog drained; under sustained arrivals λ=8 is deeply overloaded.

Token arithmetic predicts the bracket independently. Under
`context_growth: accumulate`, round *k* re-prefills everything before it, so one
`agent-heavy` session (6 rounds, 3,072 in, 384 out) demands **~70,272 prefill
tokens**; the 0.7/0.3 mix averages ~49,690 prefill and ~1,690 decode per session.
For an 8×H100 qwen3-14b prefill capacity in the 20–80k tok/s range:

    λ* ≈ 0.4 – 1.6 sessions/s

Prefix caching recovers part of the re-prefill (hence the ~25% hit rate), but the
order of magnitude holds. This is also the regime where the connector should
matter *most*: ~70k prefill tokens per session at ~25% hit rate is exactly where
cross-tier KV reuse changes capacity.

### 6.2.3 The bracket, measured

**λ\* ∈ (1.0, 2.0) sessions/s** for the baseline configuration — inside the
0.4–1.6 range §6.2.2's token arithmetic predicted independently. Two methods
agreeing on the bracket validates the apparatus, not just one measurement.

| λ | slope/s | firstQ → lastQ | peak | P90 | growing? |
|---|---|---|---|---|---|
| 0.5 | +0.013 | 11.4 → 11.8 | 21 | 253ms | no |
| 1.0 | +0.028 | 20.8 → 26.0 | 40 | 277ms | no |
| 2.0 | +0.198 | 53.1 → 98.7 | 116 | 410ms | YES |
| 4.0 | +1.322 | 121.9 → 401.8 | 486 | 24,721ms | YES |

The predicate has a wide dynamic range across the transition — slope spans two
orders of magnitude (0.028 → 1.322) — and P90 corroborates independently
(253/277 ms stable, then a cliff to 24.7 s at λ=4). A slope threshold anywhere in
roughly [0.05, 0.15] separates the regimes; the adapter should declare its
threshold and record it in the policy.

**Search downward from λ=4.** Anchoring a bisection above 8 finds nothing, since
every rate there is saturated.

### 6.2.4 Cost per evaluation

Measured wall-clock per run, 300s horizon, 8 instances: **19 s at λ=0.5 rising to
144 s at λ=4** (a saturated run has more events to simulate). A bisection over
[0.5, 4.0] to ±5% needs ~6 steps, most of them in the slower upper half, so budget
**≈ 6–10 minutes of wall-clock per configuration**.

Consequence for the design, stated plainly: a 90-run budget buys roughly
**15 configurations**, which supports a **4-factor screen** (a 16-run
resolution-IV design), not the paper's 8-factor/32-run arithmetic. Mitigations
that do not compromise the measurement:

- **Warm bracket** — seed each configuration's bisection from the previous
  configuration's λ\*, since neighbouring configurations have similar capacity.
  Cuts ~6 steps to ~3–4.
- **Coarse-then-fine** — bisect to ±10% during `screen`, tighten to ±2% only for
  the `confirm` finalists, where precision actually decides the winner.

### 6.3 Target-side adapter

The bisection **must** live in a target-side adapter returning one
`max_sustained_rate` per invocation. The compiled epoch cannot run an adaptive
search of its own — that would be an unregistered branch, which
`2026-08-16-compiled-policy-design.md` forbids. Both arms call the same adapter,
or they are not comparable. The adapter is a deliverable of this work.

## 7. Phase 0 gate (blocking, Phase 2 only)

Neither Phase-2 campaign launches until all of these pass. Every one of them
corresponds to a defect found during pilot work.

1. **`nous validate campaign FILE --smoke`** passes.
2. **Factor liveness**: every declared factor moves the objective by more than
   2× the measured noise. Noise from ≥5 seeds.
3. **No inert or panicking factor** is in the declared space.
4. **Objective is well-posed**: bisection on λ terminates with a finite λ\*, and
   the verdict at λ\*+ε differs from the verdict at λ\*−ε.
   **PASSES** — λ\* ∈ (1.0, 2.0) sessions/s for the baseline, slope spanning two
   orders of magnitude across the transition (§6.2.3). Requires the
   active-phase predicate (§6.2.1) and `--timeout -1`; the detector's `final`
   verdict fails this gate.
5. **Fail-loud harness**: every probe checks exit codes and deletes stale output
   before each run.

Rationale for (5): the first pilot harness silently reused stale metrics files
when BLIS exited non-zero, so `eviction_policy: arc` — which *panics* — appeared
as a clean "no effect" result identical to the baseline. Three factors were
briefly believed live on that basis. This is the same class as the two
historical defects in `CLAUDE.md` (singular `XᵀX`; NaN-poisoning from
infeasible rows): **a silent failure that looks like a clean result.**

## 8. Optimality scoring (Phase 2)

Ground truth by **exhaustive sweep** of the declared factor space. BLIS is a
deterministic CPU simulator, so `x*` is knowable exactly — a property no real
serving engine offers.

- `regret(arm) = f(x*) − f(x̂_arm)`, same `x*` for both arms.
- **Certificate coverage**: is `R_δ(x̂) ≥ f(x*) − f(x̂)`? A certificate that
  claims ε-optimality and is wrong is a more interesting finding than a token
  count. The reflective arm has no bound to check — which is itself the point.
- Report `recommendation.basis` (`certified` / `terminal_best` / `model` /
  `measured` / `baseline` / `none`) and both residual-regret bounds
  **separately**, never merged.

## 9. Token accounting

Per arm, from its own `llm_metrics.jsonl`: calls, input, output,
cache-read, cache-write, USD, per phase. Two headline numbers:

1. **total USD**
2. **marginal model tokens per benchmark run** — the paper's actual claim, which
   inside a compiled epoch should be exactly 0.

Cache reads are reported but not counted as fresh tokens. Budget parity is
**equal BLIS benchmark runs per arm**; token cost is the free variable. If the
reflective arm does not spend its full run budget, that is a reported
observation, not a correction.

## 10. Findings already produced (report regardless of phase)

### `target_system_ask` — BLIS

1. `eviction_policy: arc` and `blocks_per_chunk > 1` panic as deliberate
   follow-ups. Fail-loud is correct; the gap is that vLLM's surface is
   advertised as captured while two knobs cannot execute.
2. `direct_io` has a mechanism (#1581's O_DIRECT/buffered regime model) but no
   measurable effect: `defaults.yaml`'s `kv_offload_devices` ships one
   bandwidth/latency triple per class with no buffered values, and the resolver
   falls back to the O_DIRECT value when buffered is unspecified — so both
   regimes resolve identically. One file to fix.
3. The three saturation detectors disagree irreconcilably on agentic multi-turn
   workloads: `composite` → `OVERLOADED` at every rate including P90=450ms;
   `backlog-drift` → `STABLE` at every rate including P90=7.5s; `threshold` →
   mean-E2E vs a 5000ms default that agentic requests exceed from service time
   alone (~7.7s). The `final` block also omits the signals needed to diagnose
   this.
5. **The final-window vote is structurally unable to detect saturation.**
   Sessions stop being built at the horizon
   (`sim/workload/stream.go:400`), so the run always ends by draining, and
   `--saturation-final-window` votes over exactly that drain. `backlog-drift`
   therefore reports `STABLE` even when peak in-flight is growing without bound
   (measured: `end_inflight = 0` at 60s and 180s horizons while
   `peak_inflight` went 466 → 1,422). A `--saturation-active-window` option, or
   a final vote restricted to the arrival-active phase, would make the detector
   usable for capacity measurement.
6. **The 300s default `--timeout` censors the response near capacity.** An
   overloaded run reports P90 TTFT pinned at the timeout
   (295,879 / 298,994 / 300,006 ms at λ = 64 / 128 / 256) rather than its true
   latency, flattening the surface exactly where a capacity search operates.
4. `--gpu-memory-utilization` cannot be used to create KV pressure on
   `qwen3-14b`: weights need 33 GiB, so BLIS fails loudly below ~0.45 util
   (correctly).

### `nous_ask`

1. **A factor-liveness gate belongs in `--smoke`.** Today `--smoke` checks that
   manipulation predicates *hold*, not that factors *matter*. A policy hash
   computed over factors that move nothing is a pre-registration of nothing.
2. **`--smoke` should fail loudly on a target that panics** for a declared level,
   rather than leaving detection to the campaign author's harness.

### Corrections to earlier characterizations

Recorded so they are not re-derived: BLIS's default workload yields
`cache_hit_rate` **exactly 0.000** (no prefix reuse — every KV factor inert);
KV capacity auto-calc is already physically correct (15,909 blocks for
qwen3-14b/H100/TP1 at 0.9 util) and `--total-kv-blocks` should not be passed;
E2E does **not** include client think time (`sim/simulator.go:737` is
`FirstTokenTime + itlSum + postDecodeOverhead`); offload is **eager and
background** (`simulator.go:779` calls `MirrorToCPU` every step, `cascade()`
write-throughs async), matching vLLM.

## 11. Open items

- **Per-evaluation cost** — resolved, §6.2.4: ~6–10 min wall-clock per
  configuration, so ~15 configurations per 90-run budget → a 4-factor screen.
- **λ\* to ±5%** — bracket is (1.0, 2.0); resolution in progress.
- **Phase 2 factor space** — cannot be fixed until Phase 0 gate (2) passes.
  Note gate (2) must now be evaluated **at λ near λ\***, not at a fixed
  sub-capacity rate: the earlier finding that no factor cleared the noise floor
  was measured at λ=8 with a request cap, i.e. in a regime the apparatus has
  since shown to be both saturated and drain-dominated. Whether the connector
  moves λ\* is an open question, and it is the question Phase 2 turns on.
  Candidates: `offload_prompt_only`, `cpu_bytes_to_use`, `device_class`,
  `n_read_threads`, plus non-offload knobs (`block_size_in_tokens`,
  `max_num_seqs`, `long_prefill_token_threshold`) to reach screen width.
- **Whether the optimization kind's single `build` call can author working Go in
  this codebase** is untested and, per §3, is *the experiment* rather than
  something to pre-verify.
