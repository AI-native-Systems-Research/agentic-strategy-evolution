# MLSys controlled experiments: design

Status: draft. Nothing has been run yet.

## Goal

The case studies stay as they are and show real-world impact. This study adds controlled evidence
for the questions ICSE reviewers raised:

- the same task, several agents, identical conditions;
- whether a strong prompt alone can reproduce Nous's benefit, without its orchestrator;
- repeated runs (variance);
- grading by a deterministic, objective oracle instead of an LLM judge.

Framing: investigation, not score maximization. Each task asks a question about a system's
behavior. The oracle grades whether the answer is correct, backed by evidence, generalizes, and is
reproducible. Where a task has a metric, it is one check, not the goal.

## Arms

| Arm | What it is | Models |
|---|---|---|
| `l2` | Claude Code with a short scientific-method prompt (4 bullets), N sequential sessions, prior sessions' final answers pasted into the next (Engram-style iterative prompting). From `bench-framework` (PR #291): `claude_methodology_loop`. | Opus 4.6, all sessions |
| `nous_prompt` | Nous's full methodology prompts (`prompts/methodology/design.md`, `execute_analyze.md`, `report.md`) injected each session, N sequential sessions, prior answers pasted forward. No orchestrator: no schema validation, gates, worktrees, ledger, or principle store. From `bench-framework`: `claude_arm_structured_loop`. | Opus 4.6, all sessions |
| `nous` | Nous `main` at `decbde7` (v0.5.0, Claude Agent SDK dispatcher), as shipped, re-run for every cell. | Opus 4.6 design, Sonnet 4.6 execute and report (`orchestrator/defaults.yaml`) |

What each pair tests:
- `l2` vs `nous_prompt`: does Nous's methodology help, beyond generic "be scientific" prompting?
- `nous_prompt` vs `nous`: does the orchestrator add value beyond the same methodology as a prompt?

Model asymmetry, on purpose: Nous runs as shipped, with Sonnet for execution, while both baselines
run entirely on Opus 4.6. This biases against Nous. Any Nous advantage holds despite the baselines
having the stronger model throughout. Reported in the paper. Model scaling (all arms on one
model) is a later step.

Same for every arm:
- same `claude` CLI version, no web tools;
- same target repo commit and locked parameters;
- same task prompt and the same output contract (below);
- full transcripts kept;
- cost from one token-based ruler over the Claude transcripts (not each tool's self-report);
  crashed sessions are still counted.

## Iterations, stopping, cost

- Upper bound: N iterations for Nous, N sessions for `l2` and `nous_prompt`. N fixed per task.
- Each arm decides when it is done. No arm sees the oracle.
  - Nous: the continue gate follows the agent's own continue/stop recommendation, instead of
    always approving. Small change: an "agent decides" gate mode next to `--auto-approve`.
  - `l2`, `nous_prompt`: each session ends by writing `{"done": true|false, "why": "..."}`; the loop
    stops on `done`.
- No dollar cap. A safety ceiling of 3x the original Nous campaign cost kills runaway runs; any run
  that hits it is reported.
- Cost is reported, not equalized: dollars, wall time, iterations used.
- Crashes are outcomes, not retried. (In the ICSE runs, every `nous_prompt` attempt on pd-disagg
  crashed; the pilot checks this first.)

## Tasks

| Use case | Task | Ground truth | N |
|---|---|---|---|
| Verification | `pd-disagg-validation`: does the ITL formula for prefill/decode disaggregation hold, and where does it break? | Our own BLIS sweep over rates 2 to 150, computed before any run | 5 |
| Debugging | BLIS bug `d8271ee` reverted at its parent: TotalOutputTokens double-counted after preemption. Agent gets only the symptom. The fix is removed from the repo's git history (no `git log --all` leak). | The merged upstream fix, its test, and our hidden regression tests | 3 |
| Optimization | `blis-search-algo2`: design a multi-objective config search for BLIS | Our own exhaustive sweep of the full config space | 10 |

All three are CPU-only on BLIS (inference-sim), seeded, and cheap to evaluate. Contamination is
low: niche repo, 2026 commits.

Runs: 3 per arm per task. 3 tasks x 3 arms x 3 runs = 27 runs, roughly $800 to $900 based on
earlier costs.

## Held-out conditions

Held out means conditions the agent never ran, not only new seeds. Fixed before any run and kept
out of the agent's workspace.
- pd-disagg: workload shapes (input/output length mixes) and instance counts not in the task prompt.
- Debugging: hidden regression tests on other preemption-related metrics (ITL, TTFT, request
  counts under preemption), plus tests on non-preemption paths, so a patch that only satisfies the
  upstream test is caught.
- blis-search: a different model config and a different hardware config, with their own exhaustive
  fronts.

## Output contract (same text appended to every arm's prompt)

At the end, write `final/answer.json`:

```json
{
  "answer": "short prose answer to the research question",
  "deliverable": "path to the delivered artifact (patch, search script, or none)",
  "repro": "one shell command that regenerates the headline numbers from a clean checkout",
  "claims": [
    {"id": "c1", "metric": "itl_ms", "value": 17.4,
     "condition": "rate=120, mode=AD, seeds=1-3", "evidence": "path/to/results.json"}
  ]
}
```

A missing or malformed contract is recorded, not repaired.

## Oracle

Rules:
- Every question is answered by a script or by an answer key committed before the first run.
  No LLM grades anything.
- Format-neutral: it only asks for what every arm was asked to produce through the contract.
  No credit for Nous's file layout.
- The oracle runs on a fresh copy of the final workspace.
- It also scores per-iteration snapshots, so it can tell when the task was first solved.

Each question is yes/no or a number.

### Primary outcome

**O1, correct answer** (task-specific definition below). Declared primary before any run. All
other questions are secondary and reported in full, never selected after the fact.

### Secondary questions (every task)

Generalization
- O2 The answer or deliverable holds on the held-out conditions?

Claim integrity
- C1 Fraction of claims whose evidence file exists and contains the value.
- C2 Fraction of claims the oracle re-measures within tolerance.
- C3 Number of claims the oracle contradicts (false claims).

Reproducibility
- R1 `repro` runs from a fresh checkout?
- R2 The re-run matches the headline claim within tolerance?

Validity (checked in files and transcripts)
- V1 Locked parameters respected in every measured run?
- V2 Each claimed effect compared against a baseline under the same conditions?
- V3 At least 2 seeds behind each claimed difference?
- V4 No access to forbidden material (answer key, oracle, upstream fix, held-out sets)?

Stopping and cost
- S1 Declared done while O1 was still false (stopped too early)?
- S2 Iterations and dollars spent after O1 first became true (stopped too late).
- S3 Crashed or hit the safety ceiling?
- E1 Dollars, wall time, iterations used.

### Task-specific questions

pd-disagg-validation (O1 = K1 and K2 and K3)
- K1 Formula fits within ~1.5% at moderate rates (claimed and re-measured)?
- K2 Regime boundary found at high rate, within +/-20% of our sweep's crossover, correct sign
  (overprediction)?
- K3 TTFT underestimate reported, magnitude within our measured band?
- K4 Mechanism names the constant service-cost assumption. Phrase list fixed in advance; the one
  soft check, reported separately.

Debugging, `d8271ee` (O1 = D1 and D2 and D3)
- D1 Root cause located in the right file and function?
- D2 The upstream fix's test passes on the agent's patch?
- D3 Full existing test suite passes?
- D4 Our hidden regression tests pass?
- D5 Agent added a test that fails before its fix and passes after?
- D6 Patch touches only related code (diff size, files outside the fix area)?

blis-search-algo2 (O1 = B1 and T-score >= 3 of 4)
- B1 Hypervolume ratio of the delivered search vs our exhaustive front >= 95% within 3 minutes,
  oracle-run on 3 fresh seeds?
- B2 Same on the held-out model and hardware configs?
- B3 Hypervolume ratio (number, heat-colored).
- Trade-off facts, each matched against the agent's claims, numbers checked against our sweep:
  - T1 Names the knobs that dominate the Pareto front, matching our sweep's top knobs?
  - T2 Identifies the knobs that barely matter (flat effect in our sweep)?
  - T3 States the main trade-off direction correctly (which objective rises as the other falls)?
  - T4 Reports the front's structure (its size and its shape, within tolerance of our sweep)?
  The exact facts and tolerances come from our sweep and are committed before any run.

## Analysis plan (fixed before any run)

- Report every run's O1 and secondary values individually, per task and arm.
- Per task: mean, min-max, and the difference in means between arms for each pair
  (`nous` - `nous_prompt`, `nous_prompt` - `l2`, `nous` - `l2`).
- Pooled across the 3 tasks (9 runs per arm): O1 success rate and paired task-level differences, as a
  secondary view.
- Uncertainty: bootstrap intervals over runs, labeled as descriptive.
- No significance claims. With 3 vs 3 runs, the smallest possible two-sided permutation p-value is
  0.1. No broad reliability claims from 3 runs.
- Cost always reported next to outcome.

## Results view

A grid: rows are questions grouped by category, columns are task x arm x run. Yes/no cells are
green or red, not-applicable cells grey, numeric cells heat-colored per row. A summary grid shows
the mean over the 3 runs with the min-max in the cell.

## Later

- L0/L1 arms (plain Claude, single session + prompt).
- Model scaling: all arms on one model (Sonnet 4.6, Opus 4.7), subset of tasks.
- A fourth task (investigation, e.g. `paper-memorytime-mirage`).
- Resume test.

## Next steps

1. Answer keys and held-out sets: pd-disagg BLIS sweep and held-out workloads; debugging task
   (revert `d8271ee`, scrub history, symptom text, hidden regression tests); blis-search exhaustive
   fronts (main + held-out configs) and trade-off facts.
2. Oracle scripts plus grid renderer. Commit before any run.
3. Dry run: score the existing pd-disagg and blis-search runs (L2, Nous) from
   `~/Downloads/Ablations/nous-experiment-artifact/`. No LLM spend; checks the oracle separates arms.
4. Harness: `l2` and `nous_prompt` runners with `done` flag and shared cost meter; Nous "agent
   decides" gate mode.
5. Pilot: debugging task, one run per arm, `nous_prompt` first.
6. Full 27 runs, oracle, grid.
