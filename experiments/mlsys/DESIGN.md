# MLSys controlled experiments: design

Status: draft for discussion. Nothing here has been run yet.

## Goal

The case studies (self-tuning-admission, cluster-debug, flink-torchserve, ...) stay as they are and
show real-world impact. This study adds the controlled evidence that ICSE reviewers asked for:

- the same task given to several agents under identical conditions,
- repeated runs (variance),
- more than one model (does the gain come from the model or from Nous),
- grading by an objective oracle instead of an LLM judge.

## Nous version

`main` at `decbde7` (v0.5.0, Claude Agent SDK dispatcher). This is the reflective release
(`3659548`, v0.4.0) plus five small fixes. It is the version people install.
Every run records the Nous commit in its result file. Nous is re-run for every cell; no imported
campaigns.

## Arms

| Arm | What it is |
|---|---|
| `claude` | Plain Claude Code (`claude -p`), research question + output contract, resumed with "Continue." until budget or it stops. |
| `engram` | Engram-style iterative hypothesis prompting. Open: real Engram (mit-nms `agentic_handoff`, already wired for Frontier-CS in `aiopslab:experiments/frontiercs/gen/engram_research_cap.py`) vs the L2 loop from `bench-framework` (`claude_methodology_loop`). |
| `nous` | Nous `main` as-is. |

Ablation arm (open question): `nous_prompt`, the Nous methodology delivered as a prompt without the
orchestrator (`bench-framework:bench/variants/claude_arm_structured_loop.py`), on a subset.

Fairness rules, identical across arms:
- same model, same Claude Code version, same tools, no web tools;
- same target repo commit and the same locked parameters;
- same dollar budget per run, measured by one token-based ruler from the CLI/SDK transcripts
  (not each tool's self-report);
- same output contract appended to every arm's prompt (see Oracle section);
- full stream-json transcripts kept for every arm (needed for the ordering checks).

## Campaign selection

Criteria: runs on a CPU laptop, deterministic or seeded, cheap per evaluation, an oracle a script
can compute, ground truth that does not come from Nous's own run, low contamination, and a spread
of use cases.

Survey of `succesful_campaigns_jun16/` (fit = how well it suits a controlled, oracle-graded rerun):

| Campaign | Use case | Infra | Oracle | Fit |
|---|---|---|---|---|
| blis-search-algo2 | config search | CPU, BLIS (~100 ms/eval) | HV ratio vs exhaustive front (1800 configs) | good |
| flow-control-reflective-v2 | policy evolution | CPU, BLIS | critical P99 TTFT reduction under throughput-loss cap | good |
| pd-disagg-validation | model verification | CPU, BLIS | answer key, computed by our own BLIS sweep | good |
| Graph-Coloring | algorithm discovery, non-systems | CPU, Python | `evaluator.py` combined_score, known chromatic numbers | good, but contaminated (DSatur/TabuCol public) |
| scaling-with-optimal-concurrency | sample-efficient search | CPU, Go + Python | calls, gap_M, gap_f vs exhaustive truth | good, repo is on another machine |
| paper-memorytime-vector | methodology validation | CPU, BLIS fork, 75 runs | rho_dom + pre-registered pass conditions | ok, heavy |
| self-tuning-admission | policy evolution | CPU, BLIS | E2E/TTFT vs GAIE baseline | ok, no metrics archived |
| cluster-debug | infra debugging | k8s, H100, RoCE | answer key | poor to rerun (hardware) |
| flink-torchserve, iter5_streaming_gnn, gnn-streaming | pipeline analysis | Flink/JVM/TorchServe, GPU-free but noisy, 2.6 GB data | answer key | poor (noise, setup) |
| certus SSD-to-GPU, debug-flow-control | datapath / live router | NVMe+GPU / live cluster | scalar, noisy | poor |
| adaptive-*, absorption-test, epp-* | smoke / null results | BLIS | none or circular | poor |

Proposed set (4, optional 5th):

1. **blis-search-algo2**: search.
2. **flow-control-reflective-v2**: evolution.
3. **pd-disagg-validation**: verification (closest CPU-only stand-in for an investigation task).
4. **Graph-Coloring**: algorithm discovery outside systems. Kept on purpose: the earlier L2 baseline
   reached 0.9874 here vs Nous 0.969, so it guards against a cherry-picked set.
5. Optional: **scaling-with-optimal-concurrency** if the repo can be recovered.

Gap: no CPU-only debugging/investigation campaign with an independent ground truth. Options:
answer-key-only use of cluster-debug (no rerun), or a new seeded-bug task in BLIS. Open question.

Prior controlled data on these tasks (Opus 4.6, LLM judge, `~/Downloads/Ablations/nous-experiment-artifact/`)
can be re-scored by the oracle as a free dry run.

## Repetition and model scaling

- Repetition: 3 runs per arm on every selected campaign, main model claude-opus-4-6.
  4 campaigns x 3 arms x 3 runs = 36 runs.
- Model scaling: 2 campaigns (blis-search-algo2, pd-disagg-validation), all 3 arms re-run on a
  second and third model (proposal: claude-sonnet-4-6 weaker, claude-opus-4-7 stronger), 1 run each
  = 12 runs. Nous is re-run on each model (the ICSE version only re-ran the baselines).
- Report mean, min-max, and per-run values; no claim from a single run.
- Rough cost at ~$25/run: ~$900 + ~$300.

## Oracle judge

Principles:
- Every question is answered by a script, or by comparison with an answer key written before any
  arm runs. No LLM grades quality.
- Format-neutral: no credit for Nous's file layout (bundles, principles.json). A question can only
  ask for things every arm was asked to produce through the shared output contract.
- The oracle, the answer keys, and the tolerances are committed before the first run.
- The oracle runs on a fresh copy of the final workspace, so it cannot be gamed by editing results.

### Output contract (appended verbatim to every arm's prompt)

At the end, write `final/answer.json`:

```json
{
  "answer": "short prose answer to the research question",
  "deliverable": "path to the delivered artifact (policy file, search script, solver, or none)",
  "repro": "one shell command that regenerates the headline numbers from a clean checkout",
  "claims": [
    {"id": "c1", "metric": "critical_p99_ttft_ms", "value": 412.0,
     "condition": "workload=balanced_mid, policy=X, seeds=1-5", "evidence": "path/to/results.json"}
  ]
}
```

A missing or malformed contract is recorded, not repaired. The answers to Q-O* still use the
deliverable if it exists.

### Generic poll (asked for every campaign)

Outcome
- **O1** Oracle-measured headline metric of the deliverable, on the campaign's fixed evaluation
  (oracle runs it; the agent's own number is ignored).
- **O2** Same metric on held-out conditions the agent never saw (other seeds, workloads, models, or
  instances). Detects overfitting.
- **O3** Pass/fail against the campaign's stated target (e.g. HV >= 95% within 3 min).
- **O4** Answer-key facts recovered: k of n (verification tasks).

Claim integrity
- **C1** Fraction of claims whose `evidence` file exists and contains the claimed value (tolerance per metric).
- **C2** Fraction of claims the oracle re-measures within tolerance.
- **C3** Count of claims contradicted by the oracle's measurement (false claims).

Reproducibility
- **R1** Does `repro` run to completion from a fresh checkout (yes/no, wall time)?
- **R2** Does the re-run reproduce the headline claim within tolerance?

Experimental validity (objective, checked in files and transcripts)
- **V1** Locked parameters respected in every measured run (workload, model, hardware config).
- **V2** Each claimed improvement compared against a baseline measured under the same conditions.
- **V3** Number of seeds behind each claimed difference (>= 2 required to count).
- **V4** No access to forbidden material (held-out data, answer files, the oracle itself), from the transcript.
- **V5** Prediction-before-result: for claims the arm framed as predicted, the transcript shows the
  prediction before the run that tested it. Reported, not scored, since only some arms predict.

Cost and operability
- **E1** Dollars (shared ruler), wall time, number of target-system evaluations.
- **E2** Dollars to reach 90% of the best O1 seen across all arms on that campaign.
- **P1** Crashed, hung, or stopped early (and why).
- **P2** Resume: kill each arm once at ~50% budget and restart. Report whether it continues, and how
  much completed work it repeats. Run on a subset; open question.

### Campaign-specific questions

**blis-search-algo2** (search)
- O1: HV ratio of the delivered search algorithm vs the precomputed exhaustive Pareto front,
  oracle-run with fixed budget (200 evals), 3 fresh seeds, Qwen config.
- O2: same on the Llama config and a second hardware config.
- O3: HV >= 95% within 3 min wall.
- Ground truth: our exhaustive 1800-config sweep (recomputed, not taken from the Nous run).

**flow-control-reflective-v2** (evolution)
- O1: critical-priority P99 TTFT reduction vs default policy on balanced_mid, 5 fresh seeds,
  subject to throughput loss <= 10% (fails O1 if the cap is broken).
- O2: same on the code-completion workload and a 3-band priority setup.
- O3: no regression under low load (critical P99 TTFT and throughput within 1% of default).

**pd-disagg-validation** (verification)
- Answer key computed by our own BLIS sweep over rates 2 to 150 before any arm runs.
- O4 facts: K1 formula fits within ~1.5% for moderate rates; K2 a regime boundary exists at high
  rate, location within +/-20% of our sweep's crossover, error sign correct (overprediction);
  K3 TTFT is underestimated, magnitude within our measured band; K4 the stated mechanism names the
  constant-service-cost assumption. K1-K3 are numeric checks on claims; K4 is a keyword/phrase
  match list fixed in advance (the one soft check, reported separately).
- C2: every claimed ITL/TTFT number re-measured in BLIS.

**Graph-Coloring** (algorithm discovery)
- O1: `combined_score` of the delivered solver on the 22 DIMACS graphs via `evaluator.py`.
- O2: same solver on held-out DIMACS instances not in the 22.
- O3: count of graphs at the known chromatic number; any invalid coloring scores 0.
- Contamination note reported with results.

## Open questions

1. Engram arm: real Engram vs L2 iterative prompting.
2. `nous_prompt` ablation: which subset, if any.
3. Fifth campaign and the investigation/debugging gap.
4. Models for scaling; main model Opus 4.6 vs a newer one.
5. Budget per campaign (equal dollars per run; proposal: the Nous case-study cost rounded up).
6. Resume test (P2): all arms or a subset.

## Next steps

1. Agree on the open questions.
2. Write the oracle and answer keys; commit before any run.
3. Dry run: score the existing ablation workspaces with the oracle (no LLM spend).
4. Pilot: one campaign, all arms, one run each.
5. Full runs.
