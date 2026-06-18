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
| flink-torchserve | investigation | (existing) | Sonnet | flink + TorchServe pipeline | `$BENCH_NOUS_CAMPAIGNS/flink-torchserve/` |
| flow-control-reflective-v2 | evolution | **5** | Sonnet | inference-sim (BLIS) | `$BENCH_NOUS_CAMPAIGNS/flow-control-reflective-v2/` |
| pd-disagg-validation | verification | **5** | Sonnet | inference-sim (BLIS) | `$BENCH_NOUS_CAMPAIGNS/pd-disagg-validation/` |
| blis-search-algo2 | config search | **10** | Sonnet | inference-sim (BLIS) | `$BENCH_NOUS_CAMPAIGNS/blis-search-algo2/` |
| Graph-Coloring | algorithm discovery | **4** | Opus design + Sonnet execute (nous); Sonnet only (baselines) | graph-coloring repo | `$BENCH_NOUS_CAMPAIGNS/Graph-Coloring/graph-coloring-v1/` |

**Note on Graph-Coloring models:** the original nous run used Opus for design and Sonnet for execute. Baselines (L0/L1/L2) use Sonnet only — that's the bench's default. Flag this in the paper write-up: nous gets a slight model advantage on this one campaign during its design phase.

---

## Pre-flight (do once)

You'll need three things on your machine before running:

1. **The 5 source nous campaign directories** (the existing nous results we're comparing against).
2. **Local clones of the target repos** the campaigns investigate.
3. **Two environment variables** pointing at #1 and the BLIS clone, so the commands below stay machine-agnostic.

### 1. Locate the source nous campaigns

The 5 source campaigns are the existing nous runs we're comparing baselines to. They are not regenerated. Get a copy of the directory structure and put it anywhere on your machine; export the parent path so the rest of this doc works without edits:

```bash
export BENCH_NOUS_CAMPAIGNS=/path/to/your/copy/of/succesful_campaigns
ls "$BENCH_NOUS_CAMPAIGNS"
# Should show: flow-control-reflective-v2  pd-disagg-validation  blis-search-algo2
#              Graph-Coloring  flink-torchserve  ...
```

The campaign yamls inside each directory carry the source research_question:

| Campaign | Source yaml inside `$BENCH_NOUS_CAMPAIGNS/<campaign>/` |
|---|---|
| flow-control-reflective-v2 | `campaign.yaml` |
| pd-disagg-validation | `pd-disagg-campaign.yaml` |
| blis-search-algo2 | `campaign-3.yaml` |
| Graph-Coloring | `graph_coloring_campaign.yaml` |
| flink-torchserve | (filename varies — `ls` to find the .yaml) |

### 2. Clone the target repos

Each campaign investigates a real codebase. Clone these once, anywhere on your machine — the bench reads the path you give it and clones a fresh worktree per variant.

```bash
# BLIS / inference-sim — used by 3 campaigns (flow-control-reflective-v2,
# pd-disagg-validation, blis-search-algo2)
git clone <inference-sim repo url> /your/local/path/inference-sim
export BENCH_BLIS_REPO=/your/local/path/inference-sim

# Graph-Coloring — Python greedy graph coloring on DIMACS
# If you don't have the repo url, the existing nous campaign captured
# a snapshot under "$BENCH_NOUS_CAMPAIGNS/Graph-Coloring/graph-coloring-v1/inputs/"
# — copy that to a writable directory.
git clone <graph-coloring repo url> /your/local/path/graph-coloring
export BENCH_GRAPH_COLORING_REPO=/your/local/path/graph-coloring

# flink-torchserve — pipeline used by the flink-torchserve campaign
git clone <flink-torchserve repo url> /your/local/path/flink-torchserve
export BENCH_FLINK_REPO=/your/local/path/flink-torchserve
```

In each `bench/campaigns/<id>.yaml`, set `target_repo:` to one of the env-var-resolved paths (or hardcode your local path — both work; the env var convention just keeps the doc reproducible across machines).

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
  "$BENCH_NOUS_CAMPAIGNS/<source_campaign_dir>" \
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
