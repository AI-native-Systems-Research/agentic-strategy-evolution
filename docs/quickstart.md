# Quickstart

Run a single Nous iteration on any target system via the Python API.

## Prerequisites

- **Python 3.11+**
- **An LLM API key** — any [LiteLLM-supported provider](https://docs.litellm.ai/docs/providers). Set the appropriate environment variable (e.g., `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`).
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

## Initialize working directory

```python
import json
import shutil
from pathlib import Path

work_dir = Path("my-experiment")
work_dir.mkdir(exist_ok=True)

# Copy template files
for template in ["state.json", "ledger.json", "principles.json"]:
    shutil.copy(f"templates/{template}", work_dir / template)

# Set a run ID
state = json.loads((work_dir / "state.json").read_text())
state["run_id"] = "my-experiment-001"
(work_dir / "state.json").write_text(json.dumps(state, indent=2))
```

## Run a single iteration

```python
import yaml
from orchestrator.engine import Engine
from orchestrator.llm_dispatch import LLMDispatcher
from orchestrator.gates import HumanGate

campaign = yaml.safe_load(Path("campaign.yaml").read_text())

engine = Engine(work_dir)
dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign)
gate = HumanGate()  # interactive approval prompts

iteration = 1
iter_dir = work_dir / "runs" / f"iter-{iteration}"

# Framing: define the problem
engine.transition("FRAMING")
dispatcher.dispatch("planner", "frame", output_path=iter_dir / "problem.md", iteration=iteration)

# Design: create hypothesis bundle
engine.transition("DESIGN")
dispatcher.dispatch("planner", "design", output_path=iter_dir / "bundle.yaml", iteration=iteration)

# Design review: multiple perspectives evaluate the bundle
engine.transition("DESIGN_REVIEW")
for p in campaign["review"]["design_perspectives"]:
    dispatcher.dispatch("reviewer", "review-design",
        output_path=iter_dir / "reviews" / f"review-{p}.md",
        iteration=iteration, perspective=p)

# Human gate: you review and approve
engine.transition("HUMAN_DESIGN_GATE")
gate.prompt("Approve the hypothesis bundle?",
    artifact_path=str(iter_dir / "bundle.yaml"))

# Execution: analyze the system
engine.transition("RUNNING")
dispatcher.dispatch("executor", "run",
    output_path=iter_dir / "findings.json", iteration=iteration)

# Findings review
engine.transition("FINDINGS_REVIEW")
for p in campaign["review"]["findings_perspectives"]:
    dispatcher.dispatch("reviewer", "review-findings",
        output_path=iter_dir / "reviews" / f"review-findings-{p}.md",
        iteration=iteration, perspective=p)

# Human gate: approve findings
engine.transition("HUMAN_FINDINGS_GATE")
gate.prompt("Approve the findings?")

# Extract principles
engine.transition("TUNING")
engine.transition("EXTRACTION")
dispatcher.dispatch("extractor", "extract",
    output_path=work_dir / "principles.json", iteration=iteration)

engine.transition("DONE")
print("Done! Principles:", work_dir / "principles.json")
```

## Review output

After completion, check:

- **`runs/iter-1/problem.md`** — How the problem was framed
- **`runs/iter-1/bundle.yaml`** — The hypothesis bundle (validate against `schemas/bundle.schema.yaml`)
- **`runs/iter-1/findings.json`** — Executor findings (validate against `schemas/findings.schema.json`)
- **`runs/iter-1/reviews/`** — All reviewer perspectives
- **`principles.json`** — Extracted principles that guide future iterations

## Choosing a model

By default, `LLMDispatcher` uses `aws/claude-opus-4-6`. Pass any [LiteLLM model string](https://docs.litellm.ai/docs/providers) to use a different model:

```python
dispatcher = LLMDispatcher(work_dir=work_dir, campaign=campaign, model="gpt-4o")
```

## Phase 2 limitation

The executor currently operates in **analysis mode** — it reasons about the system rather than running actual experiments. Real experiment execution is planned for Phase 3.

## Next steps

- See [examples/blis/](../examples/blis/) for a complete BLIS campaign configuration
- See [docs/architecture.md](architecture.md) for how the orchestrator, dispatcher, and agents fit together
- See [docs/data-model.md](data-model.md) for schema documentation
