# Quickstart

Run Nous iterations on any target system — single or multi-iteration campaigns.

## Prerequisites

- **Python 3.11+**
- **An LLM API key** — `export OPENAI_API_KEY=...` (and `OPENAI_BASE_URL` if using a proxy). Works with any OpenAI-compatible endpoint.
- **A target system** — something you can describe in terms of observable metrics and controllable knobs.

## Install

```bash
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

## Create a campaign configuration

Create a `campaign.yaml` that describes your target system. See [campaign.schema.yaml](../schemas/campaign.schema.yaml) for the full schema, or use the [BLIS example](../examples/blis/campaign.yaml) as a starting point.

```yaml
research_question: >
  What mechanism drives the primary performance bottleneck in your system?

target_system:
  name: "Your System Name"
  description: >
    What the system does, its architecture, and what you want to investigate.
  observable_metrics:
    - latency_p99_ms
    - throughput_rps
    - error_rate_pct
  controllable_knobs:
    - algorithm
    - cache_size
    - concurrency_limit

review:
  design_perspectives:
    - statistical-rigor
    - causal-sufficiency
    - confound-risk
  findings_perspectives:
    - statistical-rigor
    - causal-sufficiency
    - confound-risk
    - reproducibility
  max_review_rounds: 3

prompts:
  methodology_layer: "prompts/methodology"
  domain_adapter_layer: null
```

### Key fields

| Field | Description |
|-------|-------------|
| `research_question` | The guiding question for the campaign — what mechanism are you investigating? |
| `target_system.observable_metrics` | What agents can measure — these appear in predictions and findings |
| `target_system.controllable_knobs` | What agents can change — these define the experimental design space |
| `review.design_perspectives` | How many reviewers check the hypothesis bundle (one per perspective) |
| `review.findings_perspectives` | How many reviewers check the findings (typically more than design) |

## Run a single iteration

```bash
python run_iteration.py campaign.yaml
```

The script handles setup, runs all phases, and pauses at human gates for your approval. Options:

```bash
python run_iteration.py campaign.yaml --model gpt-4o    # different model
python run_iteration.py campaign.yaml --run-id my-run    # custom work dir
python run_iteration.py campaign.yaml -v                 # verbose logging
```

Or try the BLIS example directly:

```bash
python run_iteration.py examples/blis/campaign.yaml
```

## Review output

After completion, check:

- **`runs/iter-1/problem.md`** — How the problem was framed
- **`runs/iter-1/bundle.yaml`** — The hypothesis bundle
- **`runs/iter-1/experiment_plan.json`** — Executor commands (real execution only)
- **`runs/iter-1/experiment_results.json`** — Collected metrics (real execution only)
- **`runs/iter-1/findings.json`** — Prediction vs. outcome analysis
- **`runs/iter-1/reviews/`** — All reviewer perspectives
- **`principles.json`** — Extracted principles that guide future iterations

## Choosing a model

By default, `run_iteration.py` uses `aws/claude-opus-4-6`. Pass any model name via `--model`:

```bash
python run_iteration.py campaign.yaml --model gpt-4o
```

## Real experiment execution

If your target system can be invoked from the command line and produces JSON metrics, add an `execution` section to your campaign:

```yaml
target_system:
  # ... name, description, metrics, knobs ...
  execution:
    run_command: "./your-tool --metrics-path {metrics_path}"
    timeout: 300
```

With this config, the executor will:

1. Design shell commands for the baseline and each hypothesis arm
2. Run each command and collect metrics from the JSON files
3. Analyze the real metrics against predictions

The `{metrics_path}` placeholder is replaced with the actual output path at runtime. Your tool must write a JSON file to that path.

Optional execution fields:

| Field | Default | Description |
|-------|---------|-------------|
| `repo_path` | null | Git repo for worktree isolation |
| `setup_commands` | [] | Commands to run before experiments |
| `cleanup_commands` | [] | Commands to run after experiments |
| `timeout` | 300 | Max seconds per command |

Without an `execution` section, the executor operates in **analysis mode** — reasoning about the system without running experiments.

## Run a multi-iteration campaign

For investigations that require more than one iteration, use `run_campaign.py`:

```bash
python run_campaign.py campaign.yaml --max-iterations 5
```

This loops through iterations automatically. After each non-final iteration:

1. A **ledger row** is appended with prediction accuracy and principle changes
2. An **investigation summary** is generated — a bounded JSON capturing what was tested, key findings, and suggested next direction
3. A **continue gate** pauses for your approval before starting the next iteration

The investigation summary feeds into the next iteration's design prompt, so each hypothesis bundle is informed by all prior learning. The summary is bounded — agent context stays at O(summary) regardless of campaign depth.

Options:

```bash
python run_campaign.py campaign.yaml --max-iterations 10   # default: 10
python run_campaign.py campaign.yaml --model gpt-4o        # different model
python run_campaign.py campaign.yaml --run-id my-campaign   # custom work dir
python run_campaign.py campaign.yaml -v                     # verbose logging
```

You can also set `max_iterations` in `campaign.yaml`:

```yaml
max_iterations: 10  # CLI --max-iterations overrides this
```

### Campaign output

After a multi-iteration campaign, your working directory contains:

- **`runs/iter-N/`** — artifacts for each iteration (bundle, findings, reviews, etc.)
- **`runs/iter-N/investigation_summary.json`** — bounded summary for each non-final iteration
- **`ledger.json`** — append-only log with one row per completed iteration
- **`principles.json`** — accumulated principles across all iterations

### Three human gates

Each iteration has two gates (design and findings approval). Between iterations, a third **continue gate** asks whether to proceed:

| Gate | When | Question |
|------|------|----------|
| Design gate | After design review | Approve the hypothesis bundle? |
| Findings gate | After findings review | Approve the results? |
| Continue gate | After extraction | Continue to the next iteration? |

Type `approve` to continue, `abort` to stop the campaign.

## Next steps

- See [examples/blis/](../examples/blis/) for a complete BLIS campaign configuration
- See [docs/architecture.md](architecture.md) for how the orchestrator, dispatcher, and agents fit together
- See [docs/data-model.md](data-model.md) for schema documentation
