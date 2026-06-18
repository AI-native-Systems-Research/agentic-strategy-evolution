# Component 1 ablation — experiments to run

Living doc for the L0/L1/L2/Nous ablation. Reference; update as runs land.

---

## What this is

For each of 5 systems we already have a nous run. We're running 3 baselines per system to fill out the L0/L1/L2 columns of the ablation table. Nous is **not** re-run — its results are imported from the existing campaign directories.

| Level | Variant | What gets passed to Claude |
|---|---|---|
| **L0** | `claude_plain` | research question only — single session |
| **L1** | `claude_methodology` | research question + `bench/methodology/methodology.md` as system prompt — single session |
| **L2** | `claude_methodology_loop` | same as L1 but **N sessions**, with previous iters' "Key takeaways" pasted into each next prompt |
| **Nous** | `nous` | full orchestrator (existing campaign result, imported via `bench import-nous`) |

---

## Per-system parameters

These come from the original nous campaign — **match these exactly when running baselines** so the comparison is fair.

| System | Use case | Iters | Model | Target repo | Source nous campaign |
|---|---|---|---|---|---|
| flink-torchserve | investigation | (existing) | Sonnet | flink + TorchServe pipeline | `~/Downloads/succesful_campaigns/flink-torchserve/` |
| flow-control-reflective-v2 | evolution | **5** | Sonnet | inference-sim (BLIS) | `~/Downloads/succesful_campaigns/flow-control-reflective-v2/` |
| pd-disagg-validation | verification | **5** | Sonnet | inference-sim (BLIS) | `~/Downloads/succesful_campaigns/pd-disagg-validation/` |
| blis-search-algo2 | config search | **10** | Sonnet | inference-sim (BLIS) | `~/Downloads/succesful_campaigns/blis-search-algo2/` |
| Graph-Coloring | algorithm discovery | **4** | Opus design + Sonnet execute (nous); Sonnet only (baselines) | graph-coloring repo | `~/Downloads/succesful_campaigns/Graph-Coloring/graph-coloring-v1/` |

**Note on Graph-Coloring models:** the original nous run used Opus for design and Sonnet for execute. Baselines (L0/L1/L2) use Sonnet only — that's the bench's default. Flag this in the paper write-up: nous gets a slight model advantage on this one campaign during its design phase.

---

## Pre-flight (do once)

### Find the research question for each campaign

Each campaign's research_question lives in its source `*.yaml`:

```bash
ls ~/Downloads/succesful_campaigns/<campaign>/*.yaml
# Look at the `research_question:` field — copy it verbatim into your bench campaign yaml
```

The exact sources:
- `flow-control-reflective-v2/campaign.yaml`
- `pd-disagg-validation/pd-disagg-campaign.yaml`
- `blis-search-algo2/campaign-3.yaml`
- `Graph-Coloring/graph_coloring_campaign.yaml`

### Resolve the target repo path

The nous campaigns reference the original authors' machine paths (`/Users/toslali/...`, etc.). For the BLIS-based campaigns, point at one canonical local checkout (e.g. `~/Desktop/nous/inference-sim`). For Graph-Coloring, clone the graph-coloring repo or use the snapshot the original campaign captured under `inputs/`.

---

## How to run one campaign

For each system, you author 2 small files then run 1 CLI invocation.

### File 1 — `bench/campaigns/<campaign_id>.yaml`

```yaml
id: <campaign_id>           # e.g. flow_control_v2
research_question: |
  <paste verbatim from the source nous campaign yaml>
target_repo: <local path>
target_ref: <commit SHA — match nous's, or use main if not pinned>
```

### File 2 — `bench/experiments/ablation_<campaign_id>.yaml`

```yaml
id: ablation_<campaign_id>
campaign: <campaign_id>
variants:
  - claude_plain
  - claude_methodology
  - claude_methodology_loop
budget:
  max_tokens: 1000000
  max_iterations: <N>          # match the iter count from the table above
  max_wall_seconds: 14400
```

### Run

```bash
python3 -m bench run bench/experiments/ablation_<campaign_id>.yaml \
  --judge-preset ablation-multi-iter \
  --run-id ablation_<campaign_id>_baselines
```

The 3 baselines run in parallel. Variant scores under the 8-metric `ablation-multi-iter` preset land in `runs/ablation_<campaign_id>_baselines/results.json`.

---

## After the baseline run — bring nous in for comparison

The baselines `results.json` only has L0/L1/L2. Pull nous's existing campaign output into the same shape and merge:

```bash
python3 -m bench import-nous \
  ~/Downloads/succesful_campaigns/<source_campaign_dir> \
  --merge-baselines runs/ablation_<campaign_id>_baselines/results.json \
  --out runs/ablation_<campaign_id>_combined/results.json
```

Then rejudge the combined 4-variant set under the same rubric:

```bash
python3 -m bench rejudge runs/ablation_<campaign_id>_combined/results.json \
  --judge-preset ablation-multi-iter --multi-iter
```

The rejudged file (`results.rejudged.json` next to the input) has all 4 variants scored under the same 8-metric rubric — that's your ablation row for this system.

---

## Where to look after each run

| File | What's in it |
|---|---|
| `runs/ablation_<id>_baselines/results.json` | L0/L1/L2 raw scores |
| `runs/ablation_<id>_baselines/report.md` | rendered table for the 3 baselines |
| `runs/ablation_<id>_baselines/<variant>/workspace/.bench-*.log` | per-variant transcript (use to identify L0 failure modes) |
| `runs/ablation_<id>_combined/results.json` | merged set with nous |
| `runs/ablation_<id>_combined/results.rejudged.json` | final 4-variant scores, all under the same rubric |

---

## Building the Section 5.1 ablation table

After all 5 systems' rejudged results are in, pull the table:

```bash
python3 -c "
import json, glob
metrics = ['correctness','completeness','novelty','coverage','diagnostic_value',
           'iter_coherence','principle_yield','structured_artifact_production']
print('| System | Variant | ' + ' | '.join(metrics) + ' | Sum |')
print('|' + '---|' * (len(metrics) + 3))
for f in sorted(glob.glob('runs/ablation_*_combined/results.rejudged.json')):
    r = json.load(open(f))
    system = r['run_id'].replace('ablation_','').replace('_combined','')
    for v in r['variants']:
        scores = v.get('judge_scores', {})
        row = [str(scores.get(m,'?')) for m in metrics]
        s = sum(x for x in scores.values() if isinstance(x,int))
        print(f'| {system} | {v[\"variant\"]} | ' + ' | '.join(row) + f' | {s} |')
"
```

---

## L0 failure mode (qualitative column)

For each system, read `runs/ablation_<id>_baselines/claude_plain/workspace/.bench-claude_plain.log` and categorize what L0 actually got wrong. Per the paper outline, expected failure modes per system:

| System | L0 failure mode |
|---|---|
| flink-torchserve | confidently wrong |
| flow-control-reflective-v2 | doesn't generalize |
| pd-disagg-validation | premature confirmation |
| blis-search-algo2 | self-contradicting |
| Graph-Coloring | textbook default |

This goes in the table next to the score columns.
