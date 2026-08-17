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

Three worked, schema-valid examples live in `examples/optimization/`:
[`vllm-batching.yaml`](../examples/optimization/vllm-batching.yaml),
[`qdrant-hnsw.yaml`](../examples/optimization/qdrant-hnsw.yaml),
[`knative-autoscale.yaml`](../examples/optimization/knative-autoscale.yaml).
Copy the closest one.

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
match, and a `build_checks.mechanism_paths` entry that resolves to nothing.
Each of those otherwise costs a full campaign to discover.

Then run the seed check in §3 by hand. `--smoke` does not do it for you yet.

## See also

- `docs/optimization-campaign-guide.md` — authoring the `optimization` block
  field by field, with worked examples and anti-patterns.
- `docs/campaign-authoring-guide.md` — `locked_parameters` and the "what to
  lock" inventory.
- `orchestrator/schemas/campaign.schema.yaml` — the normative field reference.
- `orchestrator/validate.py` (`validate_optimization_campaign`) — the
  cross-field rules, each with its actionable repair.
