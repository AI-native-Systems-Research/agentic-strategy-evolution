# Nous: scientific investigation method

You are running a structured scientific investigation. Follow this loop exactly.

## Phases

**BASELINE** — Observe the current system before changing anything.
- Run the simplest command that produces a real measurement.
- Write `baseline.json`: observation (the measured value), command, git_sha.
- If task_type is not set, determine it (debug/verify/optimize/policy/explain/other) and include task_type_reason.
- Aim for about 5 turns. Do not design hypotheses yet.

**DESIGN** — Frame testable hypotheses relative to the baseline.
- Read `state/digest.json` and `baseline.json`.
- Write `problem.json`: research sub-question, claims_needed (what must be true to answer the campaign question).
- Write `bundle.json`: a list of hypotheses, each with:
  - `family`: the mechanism family (e.g. "algorithm", "configuration"). Use at least 2 families when the problem allows, or give `single_family_reason`.
  - `prediction`: a concrete numeric or boolean prediction relative to baseline.
  - `control`: what stays unchanged to isolate the variable.
  - `falsified_if`: the observation that would refute this hypothesis.
  - Parameters and workload must match locked values exactly.
- Write `plan.json`: the runs to execute, with commands and expected outputs. Set a run's `wait_for` (a file path, or `cmd:<command>` that exits 0 when done) only for runs started in the background that outlast the turn.
- Predictions are locked after DESIGN. Do not change them during EXECUTE.

**EXECUTE** — Run the plan and record what happened.
- Execute each run in plan.json. Fix anything that does not run.
- For each hypothesis, write its `status`: CONFIRMED, REFUTED, PARTIALLY_CONFIRMED, or INCONCLUSIVE.
- Write `findings.json`: per-hypothesis results with:
  - `status`, `error_type` (prediction/measurement/design/scope), `evidence` (list of {path, key, value} pointing to real files).
  - per claim: `claim_id` (from claims_needed), `metric`, `condition`, `value`, plus `seeds` (list) and `ci` when claims_needed declares min_seeds / needs_ci.
  - `question_answered`: true/false — did the findings resolve the campaign question?
  - `finding_ref`: identifier linking back to the hypothesis.
  - If noise was measured, include `noise_sd`. A finding resting on unmeasured noise must set `noise_unmeasured: true`.
- Write `principle_updates.json`: lessons learned (add/revise/remove), each with an id and evidence.

**REPORT** — Summarize the investigation.
- Write `answer.json`: the answer to the research question, with claims_matched_fraction and evidence.
- Write `report.md`: a human-readable summary.

## Rules

1. **Baseline first.** Always measure before changing. Every prediction is a delta from baseline.
2. **Lock predictions.** After DESIGN, predictions in bundle.json are frozen. If EXECUTE changes them, the bundle hash check will flag it.
3. **One variable per experiment.** Each hypothesis isolates one mechanism. Include a control.
4. **Noise-aware claims.** If the effect is within 2x the noise sd, it is not a real effect. Measure noise on the baseline when the system is non-deterministic.
5. **Evidence must be checkable.** Every claim must cite a file path, JSON key, and value that a validator can verify. Use JSON, JSONL, CSV, or TSV files.
6. **Secrets.** Use environment variables for secrets, never literal values. The system masks secrets in logs.
7. **Long output.** Redirect long command output to a file and read only what you need. Do not paste large logs.
8. **Principles compound.** Read active principles before each DESIGN. Add new principles only with evidence; revise or remove when evidence changes.
