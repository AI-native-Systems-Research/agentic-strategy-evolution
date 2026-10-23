# Campaign authoring guide

Practices that keep a Nous campaign faithful to its intent and easy to defend. Most come from the paper-memorytime-mirage friction report (#245).

## Lock what must not change

`locked_parameters` and `locked_workload` are maps of key to value. The plan validator fails any `plan.json` run whose `parameters` contain a locked key with a different value, unless that run lists the key in `workload_changes`. The Stop hook blocks the end of DESIGN on a failing plan, and the post-phase repair pass re-checks it. Locks are the cheapest defence against the agent quietly rewriting the experiment.

Enumerate every parameter that could affect the result before the campaign starts and decide, for each, whether deviation is acceptable. Adding locks one review round at a time is far slower. A sample inventory for an LLM-serving target:

| Category | Parameter | Lock? | Reason |
|---|---|---|---|
| Workload | `model` | yes | Different model, different latency physics. |
| Workload | `concurrency_per_tenant` | yes | Directly drives the metric. |
| Workload | `duration_seconds` | yes | Short runs lose statistical power. |
| Workload | `warmup_seconds` | yes | Short warmup admits transients. |
| KV / batching | `total_kv_blocks` | if testing contention | 1M blocks means no contention. |
| KV / batching | `max_num_seqs`, `max_batched_tokens` | usually | Throttle batching and prefill. |
| Latency model | TP factor | if testing distribution | Changes per-token cost. |
| Network | `rtt_ms`, `bandwidth` | if testing | Change timing. |

Only keys that appear in a run's `parameters` are checked, so ask in `target_system.description` that plans spell out locked keys.

## Check the prediction by hand before locking

Before locking values, compute the closed-form prediction at those values. In paper-memorytime-mirage, locking `D=8` output tokens and `K=1M` KV blocks put the system in a regime where the campaign's own theory predicted a ratio of about 1.06, a null result. A few minutes of arithmetic would have caught it before iteration 1. Closed-form math is cheap; a campaign iteration is not.

## Declare the claims you need

`problem.json.claims_needed` is where the agent states what must be measured. Each entry may set `min_seeds`, `needs_ci` and `conditions`. The stop rule only accepts `answered` once every declared claim meets them, and the final check reports `claims_matched_fraction`. Put the bar in the research question (for example "with 5 seeds and a 95% CI") so the agent declares it.

## Measure noise

Run the baseline with several seeds when the system is not deterministic, so `baseline.json.noise` holds a measured `sd`. Findings then need an effect larger than twice that sd to be `CONFIRMED` or `REFUTED`.

## Validate invariants on attribution, not totals

If the bug or effect involves how work is attributed among items, the check must distinguish per item, not only the sum. A total that balances can hide a misattribution.

## Keep secrets out of the file

List env var names under `secrets` and export the values. Nous masks them in its logs and fails validation if they appear in the answer.
