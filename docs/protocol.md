# Nous protocol

Nous applies a light version of the scientific method to a software system. The text the agent sees is `prompts/lightweight/method.md`, plus a task-type checklist from `prompts/lightweight/checklists/`. This page summarises it; [architecture.md](architecture.md) describes how Nous enforces it.

## Preconditions

| Precondition | What it means |
|---|---|
| Observable metrics | The system produces measurable outputs (latency, throughput, error rate, a test result). |
| Controllable knobs | There is something to change: code, configuration, policy, workload. |
| Reproducible runs | A command, simulator or testbed that can be re-run, ideally with seeds. |

## The method

The agent works on the task the way it normally would. Nous asks for three things:

1. **Predict before testing.** Before each test, the agent writes a hypothesis and what it expects to measure to `notebook.jsonl`.
2. **Cite the number.** After each test, it writes the result (`confirmed`, `refuted` or `inconclusive`). A confirmed or refuted result cites the file, key and value that hold the measurement.
3. **Answer with checkable claims.** It finishes with `answer.json`: prose that answers every part of the question, the deliverable, one `repro` command that regenerates the headline numbers, and claims whose values are copied from files.

## What Nous adds

- **Checks.** Nous re-reads every cited value. A wrong value, a missing file, a result without an earlier hypothesis, or a `repro` that uses `cd` or an absolute path blocks the stop until it is fixed.
- **Repro.** The `repro` command must appear in the command record with exit code 0. If it does not, Nous asks the agent to run it as written.
- **One challenger.** A fresh, read-only reviewer reads the answer and notebook and names the strongest reason the conclusion could be wrong that the measurements do not already rule out: an untested regime, a confound, the wrong baseline, a sub-question left open. The agent runs that check, records it in the notebook and updates the answer.

## Stopping

The campaign ends when a valid answer has passed the repro check and the challenger step (`answered`), or when the answer still fails its checks after the repair messages (`partial`). Nous then exports the evidence and writes the final record.
