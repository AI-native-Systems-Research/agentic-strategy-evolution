# Running Nous on BLIS

This example shows how to run a single Nous iteration on [BLIS](https://github.com/inference-sim/inference-sim), a discrete-event simulator for LLM inference serving systems.

## Prerequisites

- Python 3.11+
- An LLM API key set as an environment variable (e.g., `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or any [LiteLLM-supported provider](https://docs.litellm.ai/docs/providers))
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
blis-run-001/
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

## Phase 2 limitation

In Phase 2, the executor operates in **analysis mode** — it reasons about the BLIS codebase and mechanisms but does not run actual benchmarks. The executor produces findings based on its understanding of how scheduling policies, batching, and cache management affect performance.

Phase 3 will add real experiment execution via shell access.

## Customizing

To adapt this for a different LLM inference system:

1. Copy `campaign.yaml` to a new directory
2. Update `target_system` fields (name, description, metrics, knobs)
3. Optionally adjust reviewer perspectives in `review`
4. Run the same Python script with the new campaign config
