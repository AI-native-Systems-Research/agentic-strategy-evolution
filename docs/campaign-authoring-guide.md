# Campaign authoring guide

Practices that keep a Nous campaign faithful to its intent and easy to defend. Most come from the paper-memorytime-mirage friction report (#245).

## Put the bar in the question

The research question is the only task the agent gets. State what an answer must contain: the metric, the conditions, how many seeds, whether a confidence interval is needed (for example "with 5 seeds and a 95% CI"). The challenger reads the same question, so a sub-question left unanswered is the first gap it names.

## State what must not change

Lightweight has no parameter locks. List every knob whose deviation would invalidate the result in `target_system.description` or the question itself ("keep `requests=10000` and `concurrency=8`"). Enumerate them before the campaign starts. A sample inventory for an LLM-serving target:

| Category | Parameter | Hold fixed? | Reason |
|---|---|---|---|
| Workload | `model` | yes | Different model, different latency physics. |
| Workload | `concurrency_per_tenant` | yes | Directly drives the metric. |
| Workload | `duration_seconds` | yes | Short runs lose statistical power. |
| Workload | `warmup_seconds` | yes | Short warmup admits transients. |
| KV / batching | `total_kv_blocks` | if testing contention | 1M blocks means no contention. |
| KV / batching | `max_num_seqs`, `max_batched_tokens` | usually | Throttle batching and prefill. |
| Latency model | TP factor | if testing distribution | Changes per-token cost. |
| Network | `rtt_ms`, `bandwidth` | if testing | Change timing. |

## Check the prediction by hand first

Before fixing values, compute the closed-form prediction at those values. In paper-memorytime-mirage, fixing `D=8` output tokens and `K=1M` KV blocks put the system in a regime where the campaign's own theory predicted a ratio of about 1.06, a null result. A few minutes of arithmetic would have caught it before the run. Closed-form math is cheap; a campaign is not.

## Say how to run the benchmark

Describe the build and benchmark commands in `target_system.description`, and add an `experiment_commands` regex for them so `runs.jsonl` marks experiment runs. The `repro` command must run from the repository root, so prefer commands that take relative paths.

## Validate invariants on attribution, not totals

If the bug or effect involves how work is attributed among items, the check must distinguish per item, not only the sum. A total that balances can hide a misattribution.

## Keep secrets out of the file

List env var names under `secrets` and export the values. Nous masks them in its logs and fails the answer check if they appear in the answer.
