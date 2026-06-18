# Component 1 ablation — experiments to run

What to run for the Section 5.1 ablation across the 5 systems. Reference. Living doc — update as runs land.

---

## Status

| System | Use case | nous iters (existing) | Baselines to run | Status |
|---|---|---|---|---|
| flink-torchserve | investigation | (have) | claude_plain, claude_loop, claude_methodology, claude_methodology_loop | not yet started |
| flow-control-reflective-v2 | evolution | 5 | claude_plain, claude_loop, claude_methodology, claude_methodology_loop | not yet started |
| pd-disagg-validation | verification | 4 | claude_plain, claude_loop, claude_methodology, claude_methodology_loop | not yet started |
| blis-search-algo2 | config search | 9 | claude_plain, claude_loop, claude_methodology, claude_methodology_loop | not yet started |
| Graph-Coloring | discovery | 5 | claude_plain, claude_loop, claude_methodology, claude_methodology_loop | not yet started |

For each system: nous results already exist in `~/Downloads/succesful_campaigns/<campaign>/`. We are NOT re-running nous. We are running the 4 baseline variants on the same research question, with the same iter budget, then re-judging the existing nous output alongside via the bench framework.

---

## Pre-flight (do these once before any campaign runs)

### 1. Push the judge code

The 11-metric selectable judge (#295) and the new methodology.md are uncommitted. Commit + push to `origin/bench-framework` first — the campaign-yamls and experiment-yamls below will reference these.

```bash
cd /Users/naimaabrar/Desktop/nous/agentic-strategy-evolution
git add bench/judge.py bench/judge_prompt.md bench/__main__.py \
        bench/runner.py bench/report.py bench/methodology/methodology.md \
        tests/test_bench_judge.py tests/test_bench_main.py \
        tests/test_bench_report.py tests/test_bench_runner.py
git commit -m "feat(bench): 11-metric selectable judge rubric + bench rejudge subcommand (#295)

- judge_prompt.md is now a frame template; per-metric rubric language
  lives in METRIC_RUBRICS in judge.py.
- 11 metrics: correctness, completeness, novelty, coverage,
  diagnostic_value, reproducibility, iter_coherence, principle_yield,
  causal_explanation_depth, transferability, structured_artifact_production.
- 6 named presets: default, ablation-single-iter, ablation-multi-iter,
  case-study, transferability, minimal.
- Selectable via --judge-metrics (csv) and/or --judge-preset.
- iter_coherence auto-dropped on single-iter runs.
- New 'bench rejudge' subcommand for re-judging existing results.json
  without re-running variants.
- JudgeScore.scores is now dict[str, int|None] for variable metrics.
- Validation: rejudged phase4_iter3 under all 11 metrics across Sonnet (3x)
  and Opus (1x). Rubric directionally captures structural-enforcement wins
  for nous (reproducibility +3, structured_artifact +3, iter_coherence +2,
  causal_depth +2) vs methodology's coverage win (-2 completeness, -1 coverage).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push origin bench-framework
```

### 2. Verify target repos exist locally

The 4 campaigns reference paths from their original authors' machines (`/Users/toslali/...`, `/Users/jchen/...`, etc.). For our reruns, we need accessible target repos.

| Campaign | Target | What we need |
|---|---|---|
| flow-control-reflective-v2 | BLIS / inference-sim | Use a known checkout. We've been using `~/Desktop/nous/inference-sim` for blis_prefix. Reuse if same commit, otherwise pin to a specific SHA. |
| pd-disagg-validation | BLIS / inference-sim | Same as above |
| blis-search-algo2 | BLIS / inference-sim | Same as above |
| Graph-Coloring | github.com/...graph-coloring | Need to clone. Check the existing nous run's `inputs/` dir for a snapshot. |

```bash
# Verify BLIS checkout (reuse if exists)
ls ~/Desktop/nous/inference-sim/ 2>/dev/null && echo "exists" || echo "missing — clone first"

# For Graph-Coloring, check if there's a snapshot in the existing campaign
ls ~/Downloads/succesful_campaigns/Graph-Coloring/graph-coloring-v1/inputs/ 2>/dev/null
```

If the BLIS commit needs to be pinned: each existing nous campaign records a `repo_sha` somewhere in its `state.json` or `runs/iter-1/` dir. Match that for fair comparison.

### 3. Confirm the methodology.md change is intentional

Current `bench/methodology/methodology.md` is the *short* version (~570 bytes, no required `## Principles` format).

**Implication for `claude_methodology_loop`:** that variant's regex extracts a `## Principles` section from each iter's text answer to feed into the next iter's prompt. With the new methodology, the agent isn't required to emit that section, so the regex will likely return empty bullets across iters. **The variant degenerates to `claude_loop` with a methodology system prompt** — no principle compounding.

This is a real design choice, not a bug. If intended (more realistic / less coupled to a strict format), keep it. If unintended, restore the strict-format requirement to methodology.md before running.

For the paper's L2-vs-L3 claim, this change *strengthens* the result — methodology becomes a softer baseline, structural enforcement matters more.

---

## Per-campaign experiment plan

### Authoring pattern

For each of the 4 systems below, you author 2 small files, then 1 CLI invocation runs all 4 baselines in parallel.

**File 1: `bench/campaigns/<campaign_id>.yaml`** — campaign definition (research question + target).
**File 2: `bench/experiments/<experiment_id>.yaml`** — points at the campaign + lists variants + budget.

Then run:
```bash
python3 -m bench run bench/experiments/<experiment_id>.yaml \
  --variants claude_plain,claude_loop,claude_methodology,claude_methodology_loop \
  --max-iterations <N> \
  --judge-preset ablation-multi-iter \
  --run-id ablation_<campaign>_baselines
```

`--max-iterations N` matches nous's actual iter count for that campaign (see Status table above).

`--judge-preset ablation-multi-iter` selects the 8-metric subset (correctness, completeness, novelty, coverage, diagnostic_value, iter_coherence, principle_yield, structured_artifact_production) — the metrics that defend the paper's structural-enforcement claim.

`--variants ...` lists all 4 baselines (omits nous — its results live separately in `~/Downloads/succesful_campaigns/`).

### Campaign 1 — flow-control-reflective-v2

**Use case:** evolution (policy search).

**Source nous run:** `~/Downloads/succesful_campaigns/flow-control-reflective-v2/`. 5 iters completed.

**Research question (verbatim from campaign.yaml):**
> "Can we discover a per-band dispatch ceiling policy that is parameter-free (no user-tuned thresholds) and automatically prioritizes high-priority requests as load increases — reducing critical-band tail latency with at most 10% overall throughput reduction (≤10% is acceptable)? The policy must be simple enough to migrate into llm-d as a drop-in UsageLimitPolicy plugin..."
> [full text — copy from `~/Downloads/succesful_campaigns/flow-control-reflective-v2/campaign.yaml`]

**Setup files to author:**

`bench/campaigns/flow_control_v2.yaml`:
```yaml
id: flow_control_v2
research_question: |
  [paste full RQ from source campaign.yaml]
target_repo: ~/Desktop/nous/inference-sim
target_ref: <same commit nous used — check source state.json>
```

`bench/experiments/ablation_flow_control_v2.yaml`:
```yaml
id: ablation_flow_control_v2
campaign: flow_control_v2
variants:
  - claude_plain
  - claude_loop
  - claude_methodology
  - claude_methodology_loop
budget:
  max_tokens: 1000000
  max_iterations: 5    # match nous's actual iter count
  max_wall_seconds: 7200
```

**Run:**
```bash
python3 -m bench run bench/experiments/ablation_flow_control_v2.yaml \
  --judge-preset ablation-multi-iter \
  --run-id ablation_flow_control_v2_baselines
```

**Expected cost:** ~$30-60 across the 4 baselines at iter=5. Rough breakdown: claude_plain ~$3, claude_loop ~$15 (5 iters), claude_methodology ~$5, claude_methodology_loop ~$25.

**Wall:** ~60-90 min in parallel.

**After running, where to look:**
- `runs/ablation_flow_control_v2_baselines/results.json` — per-variant judge scores
- `runs/ablation_flow_control_v2_baselines/report.md` — rendered table
- For nous comparison: rejudge the existing nous output under the same metric set:
  ```bash
  # First, build a synthetic results.json from the existing nous artifacts
  # (manual — there's no auto-import yet; copy nous's report.md as final_answer)
  python3 -m bench rejudge runs/ablation_flow_control_v2_nous/results.json \
    --judge-preset ablation-multi-iter --multi-iter
  ```

---

### Campaign 2 — pd-disagg-validation

**Use case:** verification of human-designed algorithm.

**Source nous run:** `~/Downloads/succesful_campaigns/pd-disagg-validation/output_dir/`. 4 iters completed.

**Research question:** validates "When to Disaggregate" paper predictions on BLIS — closed-form ITL/TTFT for Always-Local, Always-Disaggregate, Stationary-Randomized, and Drift-Plus-Penalty policies. Full text in source `pd-disagg-campaign.yaml`.

**Setup files:**

`bench/campaigns/pd_disagg.yaml`:
```yaml
id: pd_disagg
research_question: |
  [paste full RQ from source campaign yaml — large, multi-paragraph]
target_repo: ~/Desktop/nous/inference-sim
target_ref: <commit nous used>
```

`bench/experiments/ablation_pd_disagg.yaml`:
```yaml
id: ablation_pd_disagg
campaign: pd_disagg
variants:
  - claude_plain
  - claude_loop
  - claude_methodology
  - claude_methodology_loop
budget:
  max_tokens: 1000000
  max_iterations: 4
  max_wall_seconds: 7200
```

**Run:**
```bash
python3 -m bench run bench/experiments/ablation_pd_disagg.yaml \
  --judge-preset ablation-multi-iter \
  --run-id ablation_pd_disagg_baselines
```

**Expected cost:** ~$25-50 at iter=4. **Wall:** ~50-75 min.

**Where to look after:** `runs/ablation_pd_disagg_baselines/results.json` + `report.md`.

---

### Campaign 3 — blis-search-algo2

**Use case:** multi-objective configuration search.

**Source nous run:** `~/Downloads/succesful_campaigns/blis-search-algo2/`. 9 iters completed (campaign.yaml says max=10 but state.json shows iter=9 was the terminal).

**Research question:** design a generic multi-objective configuration search algorithm for BLIS that discovers Pareto-optimal configs efficiently, with hypervolume ratio ≥95% of exhaustive search within 3 minutes wall time. Iteration strategy specified per-iter (iter 1: random search baseline; later: refinement + portability).

**Setup files:**

`bench/campaigns/blis_search.yaml`:
```yaml
id: blis_search
research_question: |
  [paste from source campaign-3.yaml]
target_repo: ~/Desktop/nous/inference-sim
target_ref: <commit nous used>
```

`bench/experiments/ablation_blis_search.yaml`:
```yaml
id: ablation_blis_search
campaign: blis_search
variants:
  - claude_plain
  - claude_loop
  - claude_methodology
  - claude_methodology_loop
budget:
  max_tokens: 2000000   # higher because of 9 iters
  max_iterations: 9
  max_wall_seconds: 14400
```

**Run:**
```bash
python3 -m bench run bench/experiments/ablation_blis_search.yaml \
  --judge-preset ablation-multi-iter \
  --run-id ablation_blis_search_baselines
```

**Expected cost:** ~$60-100 at iter=9. This is the most expensive of the four. **Wall:** ~3-5 hrs.

**Note:** at 9 iters, claude_methodology_loop is the variant most likely to challenge nous (per-paper-claim test). Watch its iter logs for evidence of cross-iter contradiction or principle drift.

**Where to look after:** `runs/ablation_blis_search_baselines/`.

---

### Campaign 4 — Graph-Coloring

**Use case:** algorithm discovery (non-systems domain — important for breadth claim).

**Source nous run:** `~/Downloads/succesful_campaigns/Graph-Coloring/graph-coloring-v1/`. 5 iters completed (yaml says max=8).

**Note: this campaign used Opus for design, Sonnet for execute** in the original nous run. Our baselines use Sonnet only. This is intentional — the ablation tests prompt-vs-orchestrator at fixed model, not model variation. But flag this in the paper write-up so reviewers know.

**Research question:** vertex ordering and color-selection heuristics for greedy graph coloring on the DIMACS benchmark suite — and whether gains compound super-additively when combined.

**Target repo:** the original `repo_path` was `/Users/tamareilam2022/workprojects/graph-coloring`. We need a working checkout. Check the existing nous campaign's `inputs/` dir for a snapshot, or clone from upstream if known.

**Setup files:**

`bench/campaigns/graph_coloring.yaml`:
```yaml
id: graph_coloring
research_question: |
  Which vertex ordering and color-selection heuristics most reduce the number
  of colors used by the greedy graph coloring algorithm across the DIMACS
  benchmark suite, and do the gains compound (super-additively) when
  combined — without exceeding the per-graph time budget?
target_repo: <path to graph-coloring checkout>
target_ref: <commit>
```

`bench/experiments/ablation_graph_coloring.yaml`:
```yaml
id: ablation_graph_coloring
campaign: graph_coloring
variants:
  - claude_plain
  - claude_loop
  - claude_methodology
  - claude_methodology_loop
budget:
  max_tokens: 1000000
  max_iterations: 5
  max_wall_seconds: 7200
```

**Run:**
```bash
python3 -m bench run bench/experiments/ablation_graph_coloring.yaml \
  --judge-preset ablation-multi-iter \
  --run-id ablation_graph_coloring_baselines
```

**Expected cost:** ~$25-50 at iter=5. **Wall:** ~50-75 min.

**Where to look after:** `runs/ablation_graph_coloring_baselines/`.

---

## Total budget estimate

| Campaign | iters | est. cost | est. wall |
|---|---|---|---|
| flow-control-reflective-v2 | 5 | $30-60 | ~75 min |
| pd-disagg-validation | 4 | $25-50 | ~60 min |
| blis-search-algo2 | 9 | $60-100 | ~4 hrs |
| Graph-Coloring | 5 | $25-50 | ~75 min |
| **Total (sequential)** | | **$140-260** | **~7 hrs** |
| **Total (parallel by campaign)** | | same $ | ~4 hrs (slowest = blis-search) |

Run all four campaigns in parallel using separate `bench run` invocations in different terminals or via background tasks.

---

## After-run analysis

Once all 4 baseline runs complete:

### 1. Rejudge each nous campaign under the same 8-metric rubric

For each existing nous campaign in `~/Downloads/succesful_campaigns/`, build a synthetic `results.json` matching the bench schema (manually copy nous's `report.md` text into a `final_answer` field for the nous variant), then rejudge:

```bash
python3 -m bench rejudge runs/ablation_<campaign>_nous_synthetic/results.json \
  --judge-preset ablation-multi-iter --multi-iter
```

This gives a directly-comparable nous score on the same metrics as the baselines.

### 2. Build the Section 5.1 ablation table

For each system, one row × 4 levels × 8 metrics. Pull from each `runs/ablation_<campaign>_baselines/results.json`:

```bash
python3 -c "
import json, glob
metrics = ['correctness','completeness','novelty','coverage','diagnostic_value',
           'iter_coherence','principle_yield','structured_artifact_production']
print('| System | Variant | ' + ' | '.join(metrics) + ' | Sum |')
for f in sorted(glob.glob('runs/ablation_*_baselines/results.json')):
    r = json.load(open(f))
    system = r['run_id'].replace('ablation_','').replace('_baselines','')
    for v in r['variants']:
        scores = v.get('judge_scores', {})
        row = [str(scores.get(m,'?')) for m in metrics]
        s = sum(x for x in scores.values() if isinstance(x,int))
        print(f'| {system} | {v[\"variant\"]} | ' + ' | '.join(row) + f' | {s} |')
"
```

### 3. Pull qualitative L0 failure modes

For each `runs/ablation_<campaign>_baselines/`, read `claude_plain/workspace/.bench-claude_plain.log` to see what L0 actually claimed. Categorize the failure mode per the paper's table:

| System | L0 failure mode |
|---|---|
| flow-control | doesn't generalize |
| pd-disagg | premature confirmation |
| blis-search | self-contradicting |
| Graph-Coloring | textbook default |
| flink | confidently wrong |

That qualitative column belongs in the Section 5.1 table alongside the score columns.

### 4. Compare iter-by-iter coherence (L1/L2/L3)

For multi-iter variants (claude_loop, claude_methodology_loop, nous), pull each iter's claims from the iter logs / findings.json and check for contradictions across iters. This backs the intro's "L1/L2 contradict by iter 4" claim. The new judge's `iter_coherence` axis will already score this — the manual check is for the qualitative paper write-up.

---

## Open questions

1. **methodology.md scope.** The new short methodology (570 bytes) breaks claude_methodology_loop's principle-extraction regex. Should we keep it short (and let meth_loop degenerate to "loop with methodology system prompt") or restore the strict `## Principles` requirement?

2. **target_repo paths.** Each source campaign uses a path from the original author's machine. Need to either (a) reuse a single canonical checkout for all 3 BLIS campaigns, or (b) match each campaign's exact commit. Recommendation: (a) for simplicity, (b) only if a campaign's RQ depends on a specific commit's behavior.

3. **Graph-Coloring repo.** Need to locate or clone the graph-coloring repo. Existing nous campaign's `inputs/` dir might have a snapshot.

4. **Synthetic nous result.json for rejudging.** Right now `bench rejudge` works on a `results.json` produced by `bench run`. The existing nous campaigns have a different artifact layout. We need a small import script that reads `~/Downloads/succesful_campaigns/<campaign>/` and produces a bench-compatible `results.json` so the rejudge command lines up. ~1 hr of work; should add as a tiny sub-issue or do inline before running.
