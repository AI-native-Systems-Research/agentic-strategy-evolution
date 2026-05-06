# Quickstart

Run Nous campaigns on any target system with a git repository.

## Prerequisites

- **Python 3.11+**
- **Claude Code CLI** (`claude`) — installed and authenticated
- **An LLM API key** — `export OPENAI_API_KEY=...` (and `OPENAI_BASE_URL` if using a proxy). Required for reviewer, extractor, and summarizer agents.
- **A target system** — a git repo the planner can explore

## Install

```bash
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

## Create a campaign configuration

Create a `campaign.yaml` with your research question and target repo. See [examples/campaign.yaml](../examples/campaign.yaml) as a starting point.

```yaml
research_question: >
  What mechanism drives the primary performance bottleneck in your system?

max_iterations: 5

target_system:
  name: "Your System Name"
  description: >
    What the system does, its architecture, and what you want to investigate.
  repo_path: /path/to/your/repo

  # Optional — planner discovers these from code when repo_path is set.
  # Provide as hints to constrain the design space.
  # observable_metrics:
  #   - latency_p99_ms
  #   - throughput_rps
  # controllable_knobs:
  #   - algorithm
  #   - cache_size

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
| `research_question` | The guiding question — what mechanism are you investigating? |
| `target_system.repo_path` | Path to git repo — planner explores code to discover metrics and knobs |
| `target_system.observable_metrics` | Optional hints — what agents can measure (discovered from code if omitted) |
| `target_system.controllable_knobs` | Optional hints — what agents can change (discovered from code if omitted) |
| `max_iterations` | Max iterations (default: 10, CLI flag overrides) |

## Run a campaign

```bash
python run_campaign.py campaign.yaml --max-iterations 3
```

This loops through iterations. Each iteration runs the full Nous loop (design, review, execution, extraction) and pauses at human gates for your approval. After each iteration, a continue gate asks whether to proceed.

Options:

```bash
python run_campaign.py campaign.yaml --max-iterations 5 -v   # verbose
python run_campaign.py campaign.yaml --model gpt-4o          # different model
python run_campaign.py campaign.yaml --run-id my-campaign     # custom work dir
python run_campaign.py campaign.yaml --auto-approve           # skip gates
```

Or try the BLIS example directly:

```bash
python run_campaign.py examples/campaign.yaml --max-iterations 3
```

You can also set `max_iterations` in `campaign.yaml` (CLI `--max-iterations` overrides it).

## Human gates

Three gates per iteration cycle:

| Gate | When | Question |
|------|------|----------|
| Design gate | After design review | Approve the hypothesis bundle? |
| Findings gate | After findings review | Approve the results? |
| Continue gate | After extraction | Continue to the next iteration? |

Each gate shows a formatted summary before asking for your decision. Type `approve` to continue, `reject` to loop back, `abort` to stop.

## Review output

After a campaign, your working directory contains:

- **`runs/iter-N/problem.md`** — How the problem was framed
- **`runs/iter-N/bundle.yaml`** — The hypothesis bundle
- **`runs/iter-N/findings.json`** — Prediction vs. outcome analysis
- **`runs/iter-N/gate_summary_*.json`** — Human-readable gate summaries
- **`runs/iter-N/investigation_summary.json`** — Iteration summary (non-final)
- **`runs/iter-N/reviews/`** — All reviewer perspectives
- **`ledger.json`** — One row per completed iteration
- **`principles.json`** — Accumulated principles across all iterations

## Choosing a model

Default is `aws/claude-sonnet-4-5` (from `defaults.yaml`). Pass any model name via `--model`:

```bash
python run_campaign.py campaign.yaml --model gpt-4o
```

## Single iteration (advanced)

For running just one iteration (useful for debugging):

```bash
python run_iteration.py campaign.yaml --run-id test-run -v
```

## Next steps

- See [examples/campaign.yaml](../examples/campaign.yaml) for a complete example
- See [docs/architecture.md](architecture.md) for architecture details
- See [docs/data-model.md](data-model.md) for schema documentation
