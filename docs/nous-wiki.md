# Campaign Wiki

After a Nous campaign finishes, its knowledge lives in raw `ledger.json` and
`principles.json` files. The wiki skills extract that knowledge into structured,
self-contained files and render them as interactive visualizations.

## Quickstart

After a campaign completes, run these in order:

```bash
# 1. Extract knowledge, index into registry, generate per-campaign visualization
/post-campaign path/to/.nous/my-campaign

# 2. Re-render the campaign visualization (e.g., after script updates)
/visualize-campaign path/to/.nous/my-campaign

# 3. (Optional) Render the cross-campaign knowledge graph
/visualize-registry

# 4. Get recommendations for the next campaign
/suggest-next /path/to/repo "your research question"
```

`/post-campaign` already generates the campaign visualization and calls
`/index-wiki` internally, so step 2 is only needed to re-render after script
changes.

## Skills

### `/post-campaign`

Extracts structured knowledge from a completed campaign and produces a
visualization.

**Usage:**

```
/post-campaign path/to/.nous/my-campaign
```

If no path is given, the skill searches for campaign directories and asks you
to pick one.

**What it reads** (from the campaign directory):

| File | What it provides |
|------|------------------|
| `ledger.json` | Iteration outcomes (CONFIRMED/REFUTED), prediction accuracy |
| `principles.json` | Full principle definitions (statement, mechanism, bounds) |
| `campaign.yaml` | Research question, target system name, repo path |

**What it writes** (to `~/.nous/wiki/campaigns/<name>/`):

| File | Contents |
|------|----------|
| `dead-ends.json` | Approaches that were tried and conclusively failed |
| `frontiers.json` | Boundary conditions — where knowledge ends |
| `interactions.json` | Untested combinations of confirmed techniques |
| `concepts.json` | Knowledge graph: entities, concepts, parameters with linkage |
| `summaries.json` | Per-iteration narratives (what was tried, what was found) |
| `principles.json` | Copy of the campaign's principles (for downstream consumers) |
| `llm_metrics.jsonl` | Copy of per-call cost data (if it exists) |
| `summary.md` | Human-readable campaign summary |

It also generates `~/.nous/wiki/viz/<name>.html` — an interactive HTML page
with tabs for the knowledge graph, iteration timeline, insights, and summary.

**Idempotency:** If the campaign was already indexed (i.e., `concepts.json`
exists in the wiki), extraction is skipped and only the visualization is
regenerated.

**What doesn't happen:** This skill never modifies the campaign's own files.
It only reads from the campaign directory and writes to `~/.nous/wiki/`.

---

### `/visualize-campaign`

Re-renders a campaign's HTML visualization from existing wiki data. Does not
extract or modify any knowledge files.

**Usage:**

```
/visualize-campaign path/to/.nous/my-campaign
```

**Prerequisites:** The campaign must have already been indexed by
`/post-campaign`. If `concepts.json` or `summaries.json` don't exist in
`~/.nous/wiki/campaigns/<name>/`, the skill tells you to run `/post-campaign`
first.

**What it does:**
1. Finds the campaign name from `campaign.yaml` or the directory name
2. Runs the visualization script on the existing wiki data
3. Opens the generated HTML in the browser

Use this when you want to regenerate the HTML (e.g., after updating the
visualization script) without re-running the full extraction.

---

### `/index-wiki`

Merges a single campaign's extracted knowledge into the cross-campaign registry.

**Usage:**

```
/index-wiki my-campaign-name
```

**Prerequisites:** The campaign must have already been processed by
`/post-campaign`. It reads from `~/.nous/wiki/campaigns/<name>/`.

**What it reads:**

| File | What it uses |
|------|--------------|
| `concepts.json` | Entities, concepts, parameters, plus repo_path and system_name |
| `principles.json` | Principle IDs |
| `dead-ends.json` | Dead-end entries |
| `frontiers.json` | Frontier entries |
| `interactions.json` | Interaction entries |

**What it writes:**

`~/.nous/wiki/registry.json` — the cross-campaign routing index.

**What it does:**
1. Loads or initializes `registry.json`
2. Checks if campaign is already indexed (skips if yes)
3. Deduplicates entities by normalized name across campaigns
4. Assigns globally-unique IDs to all items (E-N, C-N, P-N, DE-N, F-N, I-N)
5. Appends the campaign's knowledge to the registry
6. Recomputes entity clusters (semantic grouping by functional role)

**Idempotency:** Running on an already-indexed campaign is a no-op.

**Key rule:** This is the only skill that writes to `registry.json`.

---

### `/suggest-next`

Retrieves prior knowledge from the cross-campaign registry and recommends how
to frame a new campaign. Optionally generates executable `campaign.yaml` files.

**Usage:**

```
/suggest-next /path/to/repo "research intent"
/suggest-next inference-sim "reduce tail latency under burst workloads"
/suggest-next                  # lists available projects and asks
```

**Prerequisites:** The project must have at least one campaign indexed via
`/index-wiki` (i.e., it must exist in `registry.json`).

**What it reads:**

| Source | What it uses |
|--------|--------------|
| `~/.nous/wiki/registry.json` | Project matching, campaign selection, entity selection |
| Campaign wiki files (via `retrieve_wiki_context.py`) | Principles, dead-ends, frontiers, interactions, concepts |

**What it writes:**

| File | Contents |
|------|----------|
| `~/.nous/wiki/suggestions/<date>-<slug>.md` | Scored recommendations with research questions, cost predictions, model configs |
| `~/.nous/wiki/suggestions/campaigns/<date>-<slug>-<N>.yaml` | Nous-compatible campaign configs (optional, user-selected) |

**Algorithm:**
1. **Phase A (Retrieval):** Matches project in registry, selects 3 campaigns and 6 entities, runs `retrieve_wiki_context.py` for subgraph extraction
2. **Phase B (Synthesis):** Scores 3 recommendations on Novelty, Foundation, Impact, Testability, Efficiency
3. **Phase C (Output):** Writes suggestion markdown
4. **Phase D (Format):** Structures the markdown with scoring tables and per-recommendation detail
5. **Phase E (Campaign Generation):** Asks which recommendations to turn into `campaign.yaml` files, writes schema-valid YAML to `suggestions/campaigns/`

**What doesn't happen:** This skill never modifies registry files, campaign
wiki data, or any other existing files.

---

### `/visualize-registry`

Renders the full cross-campaign knowledge graph with heuristic opportunity
scores. No LLM calls — runs in seconds.

**Usage:**

```
/visualize-registry
```

**Prerequisites:** At least one campaign must be indexed via `/index-wiki`
(i.e., `registry.json` must exist with at least one project).

**What it reads:**

| Source | What it uses |
|--------|--------------|
| `~/.nous/wiki/registry.json` | Projects, entities, entity clusters, campaigns |
| Per-campaign wiki files | concepts.json, dead-ends.json, frontiers.json, interactions.json, summary.md |

**What it writes:**

| File | Contents |
|------|----------|
| `~/.nous/wiki/viz/registry.html` | Interactive cross-campaign knowledge graph |

**Algorithm:**
1. Verify registry exists
2. Run `visualize_registry.py` (reads registry + campaign files, computes
   heuristic scores, writes HTML)
3. Open HTML in browser

The Opportunities tab shows per-cluster research potential scored by frontier
count, interaction count, and dead-end density. Each cluster card includes a
copyable `/suggest-next` command for users who want detailed LLM-powered
recommendations for that area.

**What doesn't happen:** This skill never modifies registry.json, campaign
data, or any other existing wiki files. No LLM calls are made.

---

## Output Data Model

All output lives under `~/.nous/wiki/` — a user-level directory outside any
repo. Each campaign gets its own subdirectory.

```
~/.nous/wiki/
├── registry.json                    # Cross-campaign index (written by /index-wiki)
├── campaigns/
│   └── <campaign-name>/
│       ├── concepts.json
│       ├── summaries.json
│       ├── principles.json
│       ├── dead-ends.json
│       ├── frontiers.json
│       ├── interactions.json
│       ├── llm_metrics.jsonl
│       └── summary.md
├── suggestions/                     # Written by /suggest-next
│   ├── <date>-<slug>.md            # Scored recommendation reports
│   └── campaigns/                   # Generated campaign configs
│       └── <date>-<slug>-<N>.yaml
└── viz/
    ├── <campaign-name>.html         # Per-campaign graphs
    └── registry.html                # Cross-campaign graph
```

### dead-ends.json

Approaches that were tested and conclusively don't work. Each entry is
self-contained — you can understand what failed without reading any other file.

```json
[
  {
    "id": "DE-1",
    "title": "Gradient-dampened saturation detection under sustained overload",
    "iteration": "iter-1",
    "what_was_tried": "A gradient-aware saturation detector with dampening factor 0.8...",
    "why_it_failed": "In-flight count grows monotonically during overload, making gradient always positive...",
    "avoid_when": "arrival_rate > drain_rate, any cluster size"
  }
]
```

### frontiers.json

Boundary conditions where knowledge runs out. Each frontier tells you what was
explored, what wasn't, and what to try next.

```json
[
  {
    "id": "F-1",
    "title": "Multi-instance scaling beyond 2 instances",
    "what_was_tried": "All experiments used 1-2 instances with rate 20-200...",
    "what_was_left_untried": "3+ instance clusters with rate > 200...",
    "what_to_try_next": "Run confirmed hybrid at threshold=0.7 with 4 instances, rate=400",
    "related_principles": ["RP-5", "RP-18"]
  }
]
```

### interactions.json

Untested combinations of independently-confirmed techniques that might produce
compound gains when used together.

```json
[
  {
    "id": "I-1",
    "title": "Confirmed hybrid detector + multi-instance priority dispatch",
    "approach_a": "Hybrid detector at threshold=0.7 provides 8.6% critical improvement (1-instance)...",
    "approach_b": "Priority dispatch reduces p99 latency by 12% under 2-instance mixed workloads...",
    "why_combine": "Both operate on orthogonal mechanisms — combining might provide gains across the full scale range...",
    "experiment_to_run": "Run hybrid threshold=0.7 + priority dispatch with 2 instances, rate=200, mixed-SLO",
    "related_principles": ["RP-8", "RP-17", "RP-18"]
  }
]
```

### concepts.json

The campaign's knowledge graph — entities (pre-existing code components),
concepts (techniques the campaign discovered), and parameters (tunable knobs).

The graph has directed ownership: `Entity ←(operates_on)← Concept →(owns)→ Parameter`.

Key rules:
- Entities existed in the codebase before the campaign ran
- Concepts are techniques the campaign discovered and validated
- Each parameter belongs to exactly one concept
- Every concept operates on at least one entity

### summaries.json

Per-iteration narratives used by the visualization's iteration timeline.

```json
{
  "iter-0": {
    "what_was_tried": "Baseline measurement with default configuration...",
    "what_was_found": "Established reference p99=230ms, throughput=142 req/s. BASELINE.",
    "why_it_matters": "Provides comparison point for all subsequent iterations."
  },
  "iter-1": {
    "what_was_tried": "Gradient-dampened saturation detector with dampening=0.8...",
    "what_was_found": "No improvement over baseline. REFUTED.",
    "why_it_matters": "Eliminated gradient approach under sustained overload (RP-1)."
  }
}
```

---

## Scripts

The skills call two Python scripts. You can also run them directly.

### `scripts/validate_concepts.py`

Checks a `concepts.json` file for graph integrity errors: orphaned parameters,
unreachable entities, parameters owned by multiple concepts, broken references.

```bash
python scripts/validate_concepts.py ~/.nous/wiki/campaigns/my-campaign/concepts.json
```

Exits 0 if valid, non-zero with error messages if not.

### `scripts/visualize_campaign.py`

Generates an interactive HTML page from campaign data.

```bash
python scripts/visualize_campaign.py path/to/.nous/my-campaign \
  --summaries ~/.nous/wiki/campaigns/my-campaign/summaries.json \
  --concepts ~/.nous/wiki/campaigns/my-campaign/concepts.json
```

Reads `dead-ends.json` from the wiki directory automatically. Produces
`~/.nous/wiki/viz/<campaign-name>.html` and opens it in the default browser.

The HTML includes:
- **Iterations tab** — timeline with clickable nodes showing per-iteration detail
- **Knowledge tab** — force-directed graph of entities, concepts, and parameters
- **Insights tab** — dead-ends, frontiers, and interactions as browsable cards
- **Summary tab** — the campaign's narrative summary with key principles

### `scripts/visualize_registry.py`

Generates an interactive cross-campaign HTML page from the registry and
per-campaign wiki files.

```bash
python scripts/visualize_registry.py
```

Reads `~/.nous/wiki/registry.json` plus per-campaign files (concepts.json,
dead-ends.json, frontiers.json, interactions.json, summary.md). Produces
`~/.nous/wiki/viz/registry.html` and opens it in the default browser.

The HTML includes:
- **Graph tab** — force-directed graph of entities, concepts, and parameters across all campaigns, colored by campaign
- **Opportunities tab** — per-cluster research potential scored by frontier count, interaction count, and dead-end density; each card includes a copyable `/suggest-next` command

---

## Concurrency

**Do not run `/post-campaign` in parallel for multiple campaigns targeting the
same project.** The skill writes to `~/.nous/wiki/campaigns/<name>/` and then
invokes `/index-wiki`, which performs a read-modify-write cycle on
`registry.json`. Running two `/post-campaign` invocations concurrently can
cause one to overwrite the other's registry changes (last-writer-wins race
condition).

Safe patterns:
- Run `/post-campaign` sequentially — finish one campaign before starting the next
- Running `/post-campaign` for campaigns in *different* projects is safe (they write to different registry keys), but still shares the same `registry.json` file — so even cross-project parallelism should be avoided
- `/visualize-campaign` and `/visualize-registry` are read-only and safe to run anytime
