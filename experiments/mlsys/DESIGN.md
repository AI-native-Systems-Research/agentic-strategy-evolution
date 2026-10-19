# MLSys controlled experiments: design

Status: draft. Nothing has been run yet.

## Goal

The case studies stay as they are and show real-world impact. This study adds controlled evidence
for the questions ICSE reviewers raised:

- the same task, two agents, identical conditions;
- repeated runs (variance);
- grading by a deterministic, objective oracle instead of an LLM judge.

Framing: investigation, not score maximization. Each task asks a question about a system's
behavior. The oracle grades whether the answer is correct, backed by evidence, and reproducible.
Where a task has a metric, it is one check, not the goal.

## Comparison

| Arm | What it is |
|---|---|
| `l2` | Claude Code with a scientific-method prompt, run as N sequential sessions. Each session gets the prior sessions' final answers pasted in (Engram-style iterative prompting). Reuses `claude_methodology_loop` from the `bench-framework` branch (PR #291). |
| `nous` | Nous `main` at `decbde7` (v0.5.0, Claude Agent SDK dispatcher), re-run for every cell. |

L2 vs Nous is the matched pair: same model, same iteration count, both iterate. It isolates the
method. L0 (plain Claude) and L1 (single session + prompt) can be added later; they are cheap.

Same for both arms:
- model `claude-opus-4-6`, same `claude` CLI version, no web tools;
- same target repo commit and locked parameters;
- same task prompt and the same output contract (below);
- full transcripts kept;
- cost measured by one token-based ruler over the Claude transcripts (not each tool's self-report).
  Crashed sessions are still counted.

## Iterations, stopping, cost

- Upper bound: N iterations for Nous, N sessions for L2. N is fixed per task.
- Early stop: each arm decides when it is done. Neither arm sees the oracle.
  - Nous: the continue gate follows the agent's own continue/stop recommendation, instead of
    always approving. Small change: an "agent decides" gate mode next to `--auto-approve`.
  - L2: each session ends by writing `{"done": true|false, "why": "..."}`; the loop stops on `done`.
- No dollar cap. A safety ceiling of 3x the original Nous campaign cost kills runaway runs; any run
  that hits it is reported.
- Cost is reported, not equalized: dollars, wall time, iterations used.

## Tasks

| Use case | Task | Ground truth | N |
|---|---|---|---|
| Verification | `pd-disagg-validation`: does the ITL formula for prefill/decode disaggregation hold, and where does it break? | Answer key from our own BLIS sweep over rates 2 to 150, computed before any run | 5 |
| Debugging | BLIS bug `d8271ee` reverted at its parent commit: TotalOutputTokens double-counted after preemption. Agent gets only the symptom. | The merged upstream fix and its test | 3 |
| Optimization | `blis-search-algo2`: design a multi-objective config search for BLIS | Our own exhaustive sweep of the full config space | 10 |

All three are CPU-only on BLIS (inference-sim), seeded, and cheap to evaluate. Contamination is
low: niche repo, 2026 commits.

Repetition: 3 runs per arm per task. 3 tasks x 2 arms x 3 runs = 18 runs, roughly $550 based on the
earlier ablation costs.

## Output contract (same text appended to both arms' prompts)

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
- Format-neutral: it only asks for what both arms were asked to produce through the contract.
  No credit for Nous's file layout.
- The oracle runs on a fresh copy of the final workspace.
- It also scores per-iteration snapshots, so it can tell when the task was first solved.

Each question is yes/no or a number.

### Generic questions (every task)

Outcome
- O1 Correct answer? (task-specific, below)
- O2 Holds on held-out conditions the agent never saw?

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
- V4 No access to forbidden material (answer key, oracle, upstream fix)?

Stopping and cost
- S1 Declared done while O1 was still false (stopped too early)?
- S2 Iterations and dollars spent after O1 first became true (stopped too late).
- S3 Crashed or hit the safety ceiling?
- E1 Dollars, wall time, iterations used.

### Task-specific questions

pd-disagg-validation (O1 = all of K1 to K3 true)
- K1 Formula fits within ~1.5% at moderate rates (claimed and re-measured)?
- K2 A regime boundary is found at high rate, within +/-20% of our sweep's crossover, with the
  correct sign (overprediction)?
- K3 TTFT underestimate reported, magnitude within our measured band?
- K4 Mechanism names the constant service-cost assumption. Phrase list fixed in advance; the one
  soft check, reported separately.

Debugging, `d8271ee` (O1 = D1 and D2 and D3)
- D1 Root cause located in the right file and function?
- D2 The upstream fix's test passes on the agent's patch?
- D3 Full test suite passes?
- D4 Agent added a test that fails before its fix and passes after?
- D5 Patch touches only related code (diff size, files outside the fix area)?

blis-search-algo2 (O1 = B1)
- B1 Hypervolume ratio of the delivered search vs our exhaustive front >= 95% within 3 minutes,
  oracle-run on 3 fresh seeds?
- B2 Same on a held-out model or hardware config?
- B3 Hypervolume ratio (number, heat-colored).

## Results view

A grid: rows are questions grouped by category, columns are task x arm x run. Yes/no cells are
green or red, not-applicable cells grey, numeric cells heat-colored per row. A summary grid shows
the mean over the 3 runs with the min-max in the cell.

## Open (later)

- Add L0/L1 arms.
- Model scaling (second model, subset of tasks).
- `nous_prompt` ablation (methodology as a prompt, no orchestrator).
- A fourth task (investigation, e.g. `paper-memorytime-mirage`).
- Resume test.

## Next steps

1. Answer keys: pd-disagg BLIS sweep; debugging task (revert `d8271ee`, symptom text, hidden test);
   blis-search exhaustive front.
2. Oracle scripts plus grid renderer. Commit before any run.
3. Dry run: score the existing pd-disagg and blis-search L2 and Nous runs from
   `~/Downloads/Ablations/nous-experiment-artifact/`. No LLM spend; checks the oracle separates arms.
4. Harness: L2 runner with `done` flag and shared cost meter; Nous "agent decides" gate mode.
5. Pilot: debugging task, one run per arm.
6. Full 18 runs, oracle, grid.
