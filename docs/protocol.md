# Nous protocol

Nous applies a light version of the scientific method to a software system. The method text the agent sees is `prompts/v2/method.md`, plus a task-type checklist from `prompts/v2/checklists/`. This page summarises it; [architecture.md](architecture.md) describes how Nous enforces it.

## Preconditions

| Precondition | What it means |
|---|---|
| Observable metrics | The system produces measurable outputs (latency, throughput, error rate, a test result). |
| Controllable knobs | There is something to change: code, configuration, policy, workload. |
| Reproducible runs | A command, simulator or testbed that can be re-run, ideally with seeds. |

## The loop

1. **BASELINE.** Measure the system before changing anything. Record the command, git sha, observation and noise (`baseline.json`). If `task_type` is unset, choose one.
2. **DESIGN.** Frame the sub-problem and the claims needed to answer the question (`problem.json`). Write a bundle of hypotheses (`bundle.json`), each with a mechanism, a prediction relative to the baseline, a control, and a `falsified_if` condition. Write the runs that test them (`plan.json`). Predictions are locked once DESIGN ends.
3. **EXECUTE.** Run the plan. Mark each hypothesis `CONFIRMED`, `PARTIALLY_CONFIRMED`, `REFUTED` or `INCONCLUSIVE`, with evidence that points at real files (`findings.json`). Propose principle changes (`principle_updates.json`).
4. Repeat DESIGN and EXECUTE until the stop rule fires.
5. **REPORT.** Write the answer, the deliverable, a repro command and evidence-backed claims (`answer.json`), plus `report.md`.

## Rules

1. **Baseline first.** Every prediction is a change relative to the baseline.
2. **Locked predictions.** Editing `bundle.json` after DESIGN is reverted and flagged as a `prereg_violation`.
3. **Controls.** Each hypothesis has a control, or says why it cannot. Treatment and control runs use the same seeds.
4. **Competing explanations.** A bundle covers at least 2 mechanism families, or gives a `single_family_reason`.
5. **Noise-aware claims.** A `CONFIRMED` or `REFUTED` status needs a noise estimate, and the effect must exceed twice the noise sd. Otherwise the agent must add seeds, mark the result `INCONCLUSIVE`, or declare the noise unmeasured with a reason.
6. **Checkable evidence.** Every claim cites a file, a key and a value that a validator re-reads.
7. **Compounding principles.** Principles are added, revised or removed only with a `finding_ref` to a tested hypothesis. Active principles are shown at each DESIGN.

## Prediction errors

When a prediction is wrong, `findings.json` records an `error_type`:

| Error type | Meaning |
|---|---|
| `direction` | The effect went the other way; the mechanism model is wrong. |
| `magnitude` | Right direction, wrong size. |
| `regime` | The effect holds under different conditions than predicted. |
| `shape` | The functional form (for example linear vs threshold) differs. |
| `none` | The prediction held. |

## Stopping

The campaign stops after an iteration when the question is answered with all declared claims measured, when `max_iterations` is reached, when `stall_iterations` quiet iterations occur in a row, when `nous stop` was called, or when the failure breaker trips. REPORT always runs. See [architecture.md](architecture.md#stop-rule-stop_rulepy) for the exact order.
