# Quickstart

Run Nous campaigns on any target system with a git repository.

## Prerequisites

- **Python 3.11+**
- **Claude Code CLI** (`claude`) — installed and authenticated
- **A target system** — a git repo the planner can explore

## Install

```bash
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

## Environment setup

Nous uses two LLM paths:

1. **`claude -p` (DESIGN, EXECUTE_ANALYZE)** — authenticates via Claude CLI config. Just ensure `claude` works in your terminal.
2. **OpenAI-compatible API (gate summaries, reports)** — needs env vars:

```bash
export OPENAI_API_KEY=your-api-key
export OPENAI_BASE_URL=https://your-proxy.example.com  # LiteLLM, vLLM, or any OpenAI-compatible endpoint
```

If these aren't set, gate summaries and report generation are skipped (non-fatal). The campaign still runs — you just won't get LLM-generated summaries at the gates or a final report.

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
nous run campaign.yaml --max-iterations 3
```

When `repo_path` is set in `campaign.yaml`, the campaign directory is created inside the target repo at `.nous/<run_id>/`.

Each iteration runs the full Nous loop (design → execute+analyze → validate) and pauses at two human gates. Both agents write artifacts directly to disk and run `nous validate` before claiming done — if validation fails, the agent fixes and retries.

Options:

```bash
nous run campaign.yaml --max-iterations 5 -v   # verbose
nous run campaign.yaml --model gpt-4o          # different model
nous run campaign.yaml --run-id my-campaign     # custom work dir
nous run campaign.yaml --auto-approve           # skip gates
```

Or try the BLIS example directly:

```bash
nous run examples/campaign.yaml --max-iterations 3
```

You can also set `max_iterations` in `campaign.yaml` (CLI `--max-iterations` overrides it).

## Human gates

Two gates per iteration:

| Gate | When | Question |
|------|------|----------|
| Design gate | After DESIGN | Approve the hypothesis bundle? |
| Findings gate | After EXECUTE_ANALYZE | Approve the results and principle updates? |

Each gate shows a formatted summary before asking for your decision. Type `approve` to continue, `reject` to loop back, `abort` to stop.

## Review output

After a campaign, your working directory contains:

- **`handoff.md`** — Living exploration context (updated each iteration)
- **`principles.json`** — Accumulated principles across all iterations
- **`ledger.json`** — One row per completed iteration
- **`runs/iter-N/problem.md`** — How the problem was framed
- **`runs/iter-N/bundle.yaml`** — The hypothesis bundle
- **`runs/iter-N/handoff_snapshot.md`** — Iteration snapshot of handoff for audit
- **`runs/iter-N/experiment_plan.yaml`** — Exact commands per arm
- **`runs/iter-N/findings.json`** — Prediction vs. outcome analysis
- **`runs/iter-N/principle_updates.json`** — Proposed principle changes
- **`runs/iter-N/patches/`** — Code diffs (evolve mode only)
- **`runs/iter-N/inputs/`** — Agent-created input files (configs, workloads)
- **`runs/iter-N/results/`** — Experiment output files

## Choosing a model

Defaults (from `defaults.yaml`):
- DESIGN: `claude-opus-4-6` (80 max turns)
- EXECUTE_ANALYZE: `claude-sonnet-4-6` (120 max turns)

Override via `--model` (applies to all phases) or per-phase in `campaign.yaml` under `models:`:

```bash
nous run campaign.yaml --model gpt-4o
```

## Single iteration (advanced)

For running just one iteration (useful for debugging):

```bash
nous run campaign.yaml --run-id test-run --max-iterations 1 -v
```

## Next steps

- See [examples/campaign.yaml](../examples/campaign.yaml) for a complete example
- See [docs/architecture.md](architecture.md) for architecture details
- See [docs/data-model.md](data-model.md) for schema documentation
