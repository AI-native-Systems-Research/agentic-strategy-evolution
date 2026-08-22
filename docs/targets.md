# The target adapter contract (`kind: optimization`)

A `kind: optimization` campaign spends **zero** model calls inside its epoch
(one, for `build`, if the mechanism does not exist yet). Everything the
campaign learns, it learns from two commands your repo supplies:

| Campaign field | Your script | What Nous does with it |
|---|---|---|
| `optimization.run_command` | `bench/nous_bench.py` | Runs it once per design-matrix row and reads one JSON object off stdout. |
| `optimization.test_command` | `bench/test_nous_props.py` | Runs it once at `verify` and maps each declared `native_test` to pass/fail. |

If those two contracts hold, the campaign runs. If either is subtly wrong, the
campaign runs anyway and produces numbers that mean something other than what
you read — which is why this document is a contract and not a tutorial.

Worked, schema-valid examples live in `examples/optimization/` — including
[`vllm-batching.yaml`](../examples/optimization/vllm-batching.yaml),
[`qdrant-hnsw.yaml`](../examples/optimization/qdrant-hnsw.yaml),
[`knative-autoscale.yaml`](../examples/optimization/knative-autoscale.yaml), and
[`finetune-hyperparams.yaml`](../examples/optimization/finetune-hyperparams.yaml).
Copy the closest one.

The serving and datastore ones are online systems measured on throughput or latency;
`finetune-hyperparams.yaml` is deliberately not — an **offline batch
computation** whose objective is an accuracy under a wall-clock and memory
budget, with a real held-out test split, a censorable objective guarded by
`response.self_check`, and no `refine` stage. **Nothing in this contract is
specific to serving.** A target satisfies it if one invocation of one command
prints one JSON object of metrics for one configuration — whether that
configuration is a scheduler policy, a solver tolerance, a compiler flag set, or
a training hyperparameter. The
[optimization campaign guide](optimization-campaign-guide.md) §3 opens with a
domain-to-machinery mapping table and carries worked examples in four different
fields, including a PDE solver (§3.5) and a compiler flag set (§3.6).

---

## 1. `run_command`: one JSON object, or a loud failure

Nous invokes your command as

```
shlex.split(run_command) + [each factor's rendered `apply` argument]
```

with `cwd = target_system.repo_path`, a 600-second timeout, and the parent
environment plus any `env_var`-kind factor and the workload seed (§3).

**Your script must:**

1. **Exit 0** on a successful measurement, and non-zero on anything else.
2. **Print exactly one JSON object last on stdout.** Nous takes the *last*
   complete JSON object anywhere in stdout, so progress logs above it are fine;
   two result objects are not (the second wins silently).
3. Include, in that object, **every** of:
   - the primary metric (`response.primary.metric`);
   - every `response.constraints[].metric`;
   - every `response.held_out[]` metric, if declared;
   - every factor's `manipulation.observable` — conventionally under a `cfg.*`
     prefix, echoing back what the flags actually did;
   - every `design_space.invariants[].observable`.

Dotted names resolve into nested objects, so `cfg.max_num_seqs` may be
`{"cfg": {"max_num_seqs": 256}}` or a literal `"cfg.max_num_seqs"` key.

**There is no silent zero.** A non-zero exit, a timeout, an unparseable stdout,
or a missing metric all mark the row `failed` and preserve its full
stdout/stderr under `runs/iter-N/failed_runs/`. Never emit `0` or `null` for a
measurement you did not take — a zero is data, and it will bend the fitted
surface. Fail instead.

### The type trap that has killed real campaigns

`manipulation: {observable: cfg.m, op: "==", value: "{level}"}` compares the
observable against the **factor level object**, not its string rendering. So:

- a `numeric` factor's observable must be emitted as a **number** — `256`, not
  `"256"`;
- a `choice` factor's observable must be emitted as the **exact level string** —
  `"on"`, not `true`, and not `1`;
- if your flag template decorates the level (`--grace={level}s`), the observable
  must still be the bare level (`30`), not the decorated form (`"30s"`).

A predicate that can never match fails every row, and the CLI looks correct
while it happens. `nous validate campaign FILE --smoke` catches this in seconds.

### Your output contract is frozen for the epoch's duration

At the **first successful row** of an epoch, Nous fingerprints your adapter's
output contract — every top-level key and its value's **type**, never the values
themselves — and records it at the work-dir root as `adapter_contract.json` +
`adapter_contract.sha256`. Every later row is checked against it, and any of
these **hard-aborts the campaign**:

- a key that **disappeared**;
- a key that **appeared**;
- a key whose value **changed type**, including a real value becoming `null`.

This is the same discipline `policy.json` is under, applied to the other half of
the apparatus: a pre-registered design assumes the measurement instrument is
fixed, and an adapter edited mid-epoch means the rows already on disk were
measured by a different instrument from the ones that follow.

The defect it closes: an adapter's output schema was edited three times during
one epoch. Rows measured before each edit carried `null` for the new keys, the
response-reading path coerces with `float()`, and a `None` reached a `>=` against
a float — killing an entire iteration at fit time, after ~2 hours of measurement.
An added key is treated as strictly as a removed one for exactly this reason: the
addition is the *carrier* of the damage, and the rows it damaged were measured
before it appeared.

**If you need to change what your adapter emits, that is an epoch boundary, not
an edit.** Finish or end the epoch and let the next one capture the new contract.
Never edit `adapter_contract.json` — its hash sidecar is checked.

Practical consequences for how you write the adapter:

- **Emit every key on every row, always.** A diagnostic you can only sometimes
  compute must be present with a stable type; if it is genuinely unavailable,
  fail the row (exit non-zero) rather than emitting the key as `null`.
- **Do not switch a count between `3` and `3.0`, or a level between `4` and
  `"4"`.** Both read as drift, and both are real changes in what your instrument
  reports.
- **Settle the output shape before the first row.** `nous validate campaign FILE
  --smoke` runs one configuration; the shape it emits is the shape the epoch will
  hold you to.

### An invocation must produce output on *that* call

Nous also fails any row whose response object is **byte-identical** to the
immediately preceding row's while the factor levels differ. That is the signature
of a cached or stale read — the defect being an adapter that re-read a stale
metrics file whenever the target exited non-zero, so a factor level that
**panicked** was recorded as "no effect, identical to baseline".

Two different configurations *can* legitimately tie on the objective (two cache
policies both measured exactly 1.3125 on a live campaign), which is why the
comparison is over the whole object and only against the one preceding row. If
your response carries fields that legitimately never vary — a schema version, a
host name, a build tag — declare them in `response.constant_fields` and they are
excluded, which makes the check stricter on the fields that should have moved.

So: **delete or truncate any intermediate file before you write it**, and never
read a metrics file you did not just produce.

```python
if os.path.exists(metrics_path):
    os.unlink(metrics_path)         # never read a stale result
p = subprocess.run(cmd, capture_output=True, text=True)
if p.returncode != 0:
    raise ProbeError(f"exit {p.returncode}: {p.stderr[-400:]}")
if not os.path.exists(metrics_path):
    raise ProbeError("no metrics written")
```

### Assert that your reported answer satisfies its own predicate

When the objective is defined by a **predicate over a diagnostic** — "the largest
rate that was sustained", "the smallest setting that still converges", "the
highest load meeting a bound" — re-check the returned extremum against that
predicate before reporting it, and fail loudly if it does not hold. A search that
returns a point violating its own acceptance test has a bug in the search, not a
number worth recording, and as data it is indistinguishable from a good result.

Then **declare the same predicate** as `response.self_check` so Nous enforces it
against what your adapter actually returned:

```yaml
response:
  primary: {metric: max_sustained_rate, direction: maximize}
  self_check:
    - {metric: backlog_slope, op: "<=", value: 0.060}
```

A violation fails only that row (excluded from the fit, reason and verdicts
recorded in `runs.jsonl`); the sound rows are untouched. `--smoke` and
`--liveness` evaluate it on the configurations they run, so a violated invariant
surfaces before the policy hash is written.

The defect: two growth criteria combined with `and` instead of `or` meant **8 of
12 rows** reported a `max_sustained_rate` whose own recorded `backlog_slope` said
that rate was growing — every one biased in the flattering direction. Exit codes
were clean, the file was present and parseable, the manipulation predicates
passed, and the schema validated. The adapter was loud about *failures* and
silent about a *self-contradiction*.

---

## 2. `test_command`: per-test results, and every id must resolve

`verify` is the gate. It maps each factor's declared `native_test` locator onto
a verdict from your test command's output, and a declared test that did not
**run** counts as a **failed correctness relation** — fail-closed, deliberately.

**Your command must emit machine-readable per-test results.** Nous reads:

- pytest with `--json-report` (or any JSON-lines with `nodeid`/`outcome`);
- `go test -json` (`Test`/`Action`);
- as a fallback, per-test `--- PASS:` / `--- FAIL:` lines from `go test -v` or
  pytest's verbose output.

A package-level `ok` is **not** evidence that a specific relation's test ran,
and Nous will not treat it as such.

Locators are matched on the trailing identifier after `::`, so
`bench/test_nous_props.py::test_greedy_outputs_invariant` matches a reported
node id ending in `test_greedy_outputs_invariant`. Write the path so a human can
open it; the match only needs the tail.

**Every factor needs at least one `kind: correctness` relation.** Behavioral
relations are recorded as findings and never fail a campaign, so a factor with
only behavioral relations has nothing guarding its lever. The validator refuses
that shape.

If the mechanism and its tests do not exist yet, put `build` first in
`optimization.stages` — one agent call authors them, and `verify` still gates
them. The stage that writes the code is never the stage that certifies it.

---

## 3. `NOUS_WORKLOAD_SEED` must fully determine the trace

Declare `optimization.workload: {seed_env: NOUS_WORKLOAD_SEED}` whenever your
target is stochastic — a queue, a cache, an autoscaler, a sampler, a query
stream. Nous then exports a deterministic seed into every run's environment,
records it in that iteration's `design_matrix.json` as `workload_seeds`, and at
`confirm` gives replicate *i* of **every** finalist the same seed (common random
numbers), so the workload's contribution cancels out of the
finalist-to-finalist difference and the residual-regret bound is computed on
paired differences.

**Nous exports the variable. It cannot make your benchmark read it.** Your
workload generator must seed *all* of its randomness from it: request arrival
times, prompt/query selection, key distributions, think times, tie-breaking.
Anything left on a fresh entropy source stays uncancelled.

### What goes wrong if you declare it and do not read it

The paired bound is **still a valid bound at nominal coverage** — its variance
is estimated from the differences you actually observed, so a cancellation that
never happened simply never narrows them. This is not an overconfidence bug.

What you lose is:

- **efficiency** — the paired *t* spends fewer degrees of freedom in exchange
  for a common term that was not common, so it is typically *wider* than the
  unpaired form would have been, not tighter; and
- **provenance** — the certificate on disk records
  `method: bonferroni_one_sided_t_paired` for an experiment that paired
  nothing. The number is defensible; its stated derivation is not. A reader
  auditing the campaign cannot tell the difference from the artifact alone.

So this is a *honesty and cost* problem rather than a soundness one — and it is
invisible unless you go looking.

### Verify it yourself, before you trust any paired bound

Two runs, four commands. Do this once per target, and again whenever the
workload generator changes:

```bash
# (a) Same seed twice → the stochastic behaviour must reproduce.
NOUS_WORKLOAD_SEED=12345 python bench/nous_bench.py --emit-trace > /tmp/a.json
NOUS_WORKLOAD_SEED=12345 python bench/nous_bench.py --emit-trace > /tmp/b.json
diff <(jq -S .trace /tmp/a.json) <(jq -S .trace /tmp/b.json) && echo "SEED HONOURED"

# (b) Different seeds → the behaviour must measurably differ.
NOUS_WORKLOAD_SEED=99999 python bench/nous_bench.py --emit-trace > /tmp/c.json
diff <(jq -S .trace /tmp/a.json) <(jq -S .trace /tmp/c.json) || echo "SEED IS LIVE"
```

Read both halves as a pair, because each catches a different lie:

- **(a) fails** → the seed does not control the generator at all (or something
  else in the harness is unseeded). Pairing buys nothing.
- **(a) passes but (b) also shows no difference** → the seed is being read and
  then ignored, or the "trace" you are diffing is a constant. Equally useless,
  and much easier to mistake for success.

The cleanest way to make (a) checkable is a `--emit-trace` (or
`--dump-workload`) flag on your adapter that prints the *generated plan* —
arrival timestamps, request ids, chosen keys — without running the benchmark.
Then the check is exact and costs milliseconds.

**On genuinely non-deterministic infrastructure** — a real cluster, a real GPU,
anything where kernel scheduling or network jitter is in the measurement path —
(a) will not be bit-identical, and should not be. Diff the *generated workload
plan*, not the measured latencies: the plan is what the seed owns, and it should
be bit-identical even when the outcome is not. If your adapter cannot separate
the two, compare distribution summaries instead and treat "same seed → same
plan-level summary" as the bar.

> **Known gap.** `nous validate campaign FILE --smoke` today checks that the
> test identifiers resolve, that `run_command` execs and emits parseable JSON,
> that the objective metric is present, and that the manipulation predicates
> hold — but it does **not** run the same configuration twice at two seeds to
> check that `seed_env` is live. That automation is the natural next step and is
> a known future improvement; until it lands, the two-run check above is manual
> and it is on the target owner to run it.

An explicit `workload.seeds: [11, 22, ...]` list pins the seed set (taken modulo
the row/replicate index) when you want the same draws across epochs. Omit it and
Nous derives seeds from the run-order seed.

---

## 4. SLA constraints define validity, not a penalty

Nous has four distinct verdicts for a row, and they are not interchangeable:

| Verdict | Cause | What happens to the data |
|---|---|---|
| `complete` | everything held | fitted, and eligible to be recommended |
| `infeasible` | a `response.constraints` predicate failed | **retained** as real data about the space, excluded from fitting |
| `rejected` | a `design_space.invariants` predicate failed, or the response exceeded `response.ceiling` | **discarded** — the campaign left its declared space, or the instrumentation is lying |
| `failed` | non-zero exit, timeout, unparseable output, or a manipulation predicate that failed twice | excluded; the row's full output is preserved |

So: put a **real SLA** in `response.constraints` and let violating
configurations be *inadmissible*. Do not fold the SLA into the objective as a
penalty term — that lets the optimizer trade a latency violation for throughput
at an exchange rate you invented, and the recommendation will exploit it.

Put in `design_space.invariants` only the things whose violation means the
*measurement is untrustworthy* (memory cap exceeded, compaction still running,
activator in the request path) — those rows are thrown away, not learned from.

---

## 4a. Write under `NOUS_RUN_DIR` — never a shared path

Nous exports three variables into **every** run's environment, at every
concurrency width **including 1**:

| Variable | Meaning |
|---|---|
| `NOUS_RUN_DIR` | a private, already-created, writable directory for this row |
| `NOUS_ROW_INDEX` | the row's index in the design matrix |
| `NOUS_RUN_SLOT` | which concurrency slot the row occupies, or `0` |

**Put every file your adapter writes under `NOUS_RUN_DIR`** — build output,
metrics files, temp data, logs, downloaded fixtures:

```bash
# Wrong: two concurrent rows race on one path, and the loser's binary
# silently measures the winner's build.
go build -o /tmp/bench ./cmd/bench

# Right: private per row, and identical code serially or concurrently.
go build -o "$NOUS_RUN_DIR/bench" ./cmd/bench
"$NOUS_RUN_DIR/bench" --metrics-out "$NOUS_RUN_DIR/metrics.json"
```

This is not hypothetical. On a real campaign two rows shared a single
`go build -o` output path, so one row measured a binary built for the *other*
row's configuration — plausible numbers, attributed to the wrong levels, with
nothing in any artifact to show it. The variables are exported at width 1 as well
precisely so that the same adapter code path runs in both regimes: one that only
appeared above width 1 would make concurrency the first thing to exercise it.

Two related notes:

* Factors using `apply.kind: config_patch` are **already** isolated on the input
  side — each run reads its own patched copy of your config file — so this closes
  the *output* side of the same problem.
* A harness that reuses a stale metrics file when a run exits non-zero is the
  companion defect (§1): it reports a crashed configuration as a clean result
  identical to baseline. Write to `$NOUS_RUN_DIR` **and** fail loudly.

Nous cannot enforce this — an adapter that hardcodes `/tmp/bench` still collides.
It is a facility plus a contract, and honouring it is what makes
`optimization.concurrency` safe to declare. See the guide's
`optimization.concurrency` subsection.

---

## 5. Long benchmarks: keep the numbers honest

- **`design.max_runs`** is a real budget. Multiply your per-run wall time by it
  before you commit: a 90-run campaign over a 4-minute benchmark is six hours,
  and `confirm` replicates come out of the same budget.
- **`response.noise_estimate_pct`** should come from a **5-replicate pilot at
  the baseline configuration**, not from intuition. It is what the screen stage
  compares effects against; too low and every effect looks real, too high and
  nothing does.
- **`optimization.policy.epsilon`** is your indifference width — the
  improvement below which you would not bother changing production. Declare
  exactly one of `abs` / `pct`. **What it has to clear is the terminal bound
  at your planned replicate count, not "the noise floor"** — see the
  arithmetic below, which is the difference between an epsilon that can
  certify and one that cannot.
- **`known_valid_baseline`** must be your **production configuration** — a
  setting known to work today, with the mechanism under study at its
  OFF/control level. It is the report's last-resort answer when nothing
  measured survives, and it is the control that oracle 2(c) measures before and
  after a `build`. Every level it names must be a declared level of that factor.
- **`locked_parameters`** pins everything you are *not* varying (model,
  corpus, node count, thread pool). A campaign that silently re-picks these is
  not the experiment you designed.

### Picking an epsilon that can actually certify

Certification is `R_δ^term ≤ ε`, where `R_δ^term` is a **simultaneous**
one-sided upper bound over the `M = shortlist_size − 1` challengers,
Bonferroni-corrected. Under common random numbers with `n` paired replicates
per finalist, its scale is roughly

    R_δ^term  ≈  t_{1−δ/M, n−1} · σ · √( 2(1−ρ) / n )

with `σ` your per-run standard deviation (`noise_estimate_pct` × the metric)
and `ρ` the seed-induced correlation between finalists that pairing removes.
Three things follow, and they are not the same as "set epsilon above the
noise floor":

1. **Replicates buy you `√n`, not `n`.** Halving the bound costs four times
   the runs. Widening epsilon is usually cheaper than buying the bound down,
   and it is honest as long as the width is one you would genuinely be
   indifferent across.
2. **Pairing is what makes a noisy target affordable.** The `(1−ρ)` factor is
   the whole benefit of `workload.seed_env`. At `ρ = 0.9` the bound is about
   a third of its unpaired size — which is why §3's seed check matters before
   you trust any budget arithmetic.
3. **An epsilon below your noise floor is not automatically wrong.** What
   matters is the bound at your `n`, and the bound *floors at zero* once the
   winner's observed margin exceeds it. A campaign whose winner is genuinely
   several times `σ` better certifies comfortably at an epsilon under
   `noise_estimate_pct`; a campaign whose finalists are near-tied will not
   certify at any epsilon you would be willing to defend — and **that is the
   instrument working.** `terminal_best` on a near-tie is the correct answer:
   three configurations you cannot distinguish is real information, and
   certifying one of them would be the failure.

So the shipped examples are not misconfigured when they pair a 2% epsilon
with a 4% `noise_estimate_pct`: at 4 paired replicates with `ρ ≈ 0.9`, a
winner ~5% clear of the field certifies, and a winner inside a percent of the
field comes back `terminal_best`. Write the arithmetic for *your* target into
`guidance.interpretation`, so the reader of the report knows in advance which
outcome would have been the null result. If you would rather certify a
narrower margin, raise `design.confirm.replicates` — and multiply the extra
runs by your per-run wall time before you commit to it.

---

## 6. Per-target notes

**vLLM / Triton (inference serving).** Seed the *request trace*: arrival times,
prompt lengths, sampled prompts. Constrain p99 TTFT and OOM; put GPU memory
utilisation in `design_space.invariants` (a run that spilled is not a
measurement). Lock the model, quantization, and tensor-parallel size — they
change the whole surface. Greedy decoding makes token-identity a testable
correctness relation, which is the strongest oracle available here; use it.

**Milvus / Qdrant (vector search).** Two budgets, not one: build-time knobs
(`m`, `ef_construct`, quantization) spend index build time and memory,
search-time knobs (`ef_search`, nprobe) spend per-query latency. Seed the query
stream. Constrain recall at a fixed floor — recall is what makes throughput
meaningful, and an unconstrained campaign will happily recommend a fast index
that returns the wrong answers. Invariant: fully compacted/optimized before
queries start.

**ClickHouse (analytical queries).** Seed the query mix and any generated data.
Drop the page cache between runs, or lock it warm and say so in
`locked_parameters` — a half-warm cache is the single largest source of
irreproducible numbers here. Constrain peak memory per query; put "no
background merge in flight" in the invariants. Beware `apply` knobs that are
per-session vs. per-server: the manipulation observable must read back the one
that actually applied.

**Knative / KEDA (autoscaling).** Seed the load profile — burst timing is the
whole experiment. Constrain max pods (cluster cost) and error rate. Invariant:
the activator stays out of the steady-state request path. Autoscaler campaigns
have large run-to-run variance from cluster scheduling and image cache state:
expect a high `noise_estimate_pct`, more `confirm.replicates` than you would
use elsewhere, and a wider `epsilon`. Scale-to-zero grace periods make runs
long; count them into `max_runs`.

**Cilium / eBPF datapath.** Most interesting knobs here are compile-time or
require a datapath change, so this is the family that usually needs a `build`
stage. Seed the traffic generator. Constrain packet loss and connection error
rate; put "no verifier rejection, no map-full events" in the invariants.
Correctness relations should assert connectivity and policy semantics, not
throughput — a datapath that is fast and drops a policy decision is a
regression, and only a correctness relation will say so.

---

## 7. Before you launch

```bash
nous validate campaign examples/optimization/vllm-batching.yaml --smoke
```

Static validation passes campaigns that cannot execute a single configuration.
`--smoke` runs your test command and one configuration at the first design
corner, and reports: an unresolvable `native_test`, a `run_command` that cannot
exec, a missing objective metric, a manipulation predicate whose type can never
match, a declared `response.self_check` the probe row violates, and a
`build_checks.mechanism_paths` entry that resolves to nothing. Each of those
otherwise costs a full campaign to discover.

`--liveness` adds one run per declared level, so a level whose row violates a
`self_check` is caught even when the probe corner is honest.

Then run the seed check in §3 by hand. `--smoke` does not do it for you yet.

## See also

- `docs/optimization-campaign-guide.md` — authoring the `optimization` block
  field by field, with worked examples and anti-patterns.
- `docs/campaign-authoring-guide.md` — `locked_parameters` and the "what to
  lock" inventory.
- `orchestrator/schemas/campaign.schema.yaml` — the normative field reference.
- `orchestrator/validate.py` (`validate_optimization_campaign`) — the
  cross-field rules, each with its actionable repair.
