# Running Nous on BLIS

This example shows how to run a single Nous iteration on [BLIS](https://github.com/inference-sim/inference-sim), a discrete-event simulator for LLM inference serving systems.

## Prerequisites

- Python 3.11+
- An LLM API key: `export OPENAI_API_KEY=...` (and `OPENAI_BASE_URL` if using a proxy)
- Nous installed: `pip install -e ".[dev]"`

## Campaign configuration

The `campaign.yaml` in this directory configures Nous for BLIS:

| Section | What it controls |
|---------|-----------------|
| `target_system.name` | Human-readable name shown in prompts |
| `target_system.description` | System description given to all agents |
| `target_system.observable_metrics` | What agents can measure (TTFT, TPOT, throughput, etc.) |
| `target_system.controllable_knobs` | What agents can change (scheduler_policy, max_batch_size, etc.) |
| `review.design_perspectives` | Reviewer perspectives for hypothesis bundle review (5 perspectives) |
| `review.findings_perspectives` | Reviewer perspectives for findings review (10 perspectives) |
| `review.max_review_rounds` | Maximum convergence rounds per review gate |

## Running a single iteration

```bash
python run_iteration.py examples/blis/campaign.yaml
```

That's it. The script will:

1. Create a working directory (`blis-run/`)
2. Walk through all phases: framing, design, review, execution, extraction
3. Pause at two human gates for your approval
4. Print progress as it goes

Options:

```bash
# Use a different model
python run_iteration.py examples/blis/campaign.yaml --model gpt-4o

# Custom working directory name
python run_iteration.py examples/blis/campaign.yaml --run-id my-experiment

# Verbose logging
python run_iteration.py examples/blis/campaign.yaml -v
```

## Expected output

After running, your working directory will contain:

```
blis-run/
  state.json              # phase: DONE
  principles.json         # extracted principles
  ledger.json
  runs/
    iter-1/
      problem.md          # problem framing
      bundle.yaml         # hypothesis bundle
      findings.json       # executor findings
      reviews/
        review-*.md       # design reviews
        review-findings-*.md  # findings reviews
```

## Real experiment execution

The campaign includes an `execution` block that enables real experiment execution. To use it:

1. Clone the [BLIS repository](https://github.com/inference-sim/inference-sim) locally
2. Build it (follow BLIS docs)
3. Set `repo_path` in `campaign.yaml` to your local BLIS checkout:
   ```yaml
   execution:
     repo_path: "/path/to/your/blis"
   ```
4. Run: `python run_iteration.py examples/blis/campaign.yaml`

When `repo_path` is set, Nous creates an isolated git worktree in the BLIS repo, runs the simulator commands, collects real metrics, and compares them against hypothesis predictions.

When `repo_path` is null (or the `execution` block is removed), the executor falls back to **analysis mode** — reasoning about the system without running real experiments.

## Customizing

To adapt this for a different LLM inference system:

1. Copy `campaign.yaml` to a new directory
2. Update `target_system` fields (name, description, metrics, knobs)
3. Optionally adjust reviewer perspectives in `review`
4. Run: `python run_iteration.py path/to/your/campaign.yaml`
