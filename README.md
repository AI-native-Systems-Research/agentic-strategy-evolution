# Nous — Hypothesis-Driven Experimentation for Software Systems

Nous is a framework that runs the scientific method on software systems. An AI agent forms a falsifiable hypothesis about system behavior, designs a controlled experiment, executes it, and extracts reusable principles from the outcome — whether the hypothesis was confirmed or refuted.

A deterministic Python orchestrator (not an LLM) drives four AI agent roles through a structured loop, producing schema-governed artifacts at every step. Knowledge compounds: principles from iteration N constrain the design space of iteration N+1.

## Why Nous?

Traditional performance tuning is ad-hoc: try something, measure, repeat. Nous adds structure:

- **Hypothesis bundles** decompose each experiment into multiple falsifiable arms (main hypothesis, ablations, controls, robustness checks) so you learn *why* something works, not just *that* it works.
- **Prediction error taxonomy** classifies wrong predictions by type (direction, magnitude, regime), turning failures into precise knowledge about where your mental model was wrong.
- **Fast-fail rules** cut wasted compute — if the main hypothesis is refuted, skip the remaining arms and go straight to learning.
- **Principle extraction** builds a living knowledge base that prevents the system from repeating mistakes or contradicting established findings.

## When to Use Nous

Nous works on any software system that meets four preconditions:

| Precondition | Example |
|---|---|
| **Observable metrics** | Latency, throughput, error rate, utilization |
| **Controllable policy space** | Algorithms, configurations, scheduling policies, routing rules |
| **Reproducible execution** | Simulator, testbed, or staging environment with controlled conditions |
| **Decomposable mechanisms** | System behavior arises from interacting components you can reason about individually |

**Good fits:** LLM serving systems, database query optimizers, network routing, resource schedulers, caching strategies, load balancers, batch processing pipelines.

**Not a fit:** Systems where you cannot reproduce conditions or measure outcomes quantitatively.

## How It Works

Each iteration follows five phases:

```
1. FRAMING          Planner defines research question, baseline, success criteria
2. DESIGN           Planner creates hypothesis bundle with multiple arms
   DESIGN_REVIEW    AI multi-perspective review (blocks on CRITICAL findings)
   HUMAN_GATE       Human approves, rejects, or aborts
3. PLAN_EXECUTION   Executor designs exact shell commands per arm
   EXECUTING        Orchestrator runs commands deterministically
   ANALYSIS         LLM compares observed metrics to predictions
   FINDINGS_REVIEW  AI review of prediction-vs-outcome results
   HUMAN_GATE       Human approves findings
4. EXTRACTION       Extractor updates principle store (insert/update/prune)
   → next iteration or DONE
```

See [docs/protocol.md](docs/protocol.md) for the full methodology, [docs/data-model.md](docs/data-model.md) for a plain-English guide to every data structure, and [docs/architecture.md](docs/architecture.md) for system internals.

## Hypothesis Bundle Arms

Every experiment is structured as a bundle of falsifiable predictions:

| Arm | Question | Purpose |
|---|---|---|
| **H-main** | Does the mechanism work? | Primary hypothesis with causal explanation |
| **H-ablation** | Which components matter? | Tests individual contribution of each component |
| **H-super-additivity** | Do components interact? | Tests whether compound effect exceeds sum of parts |
| **H-control-negative** | Where should it NOT work? | Confirms mechanism specificity |
| **H-robustness** | Does it generalize? | Tests across workloads, resources, scale |

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Claude Code CLI** (`claude`) — installed and authenticated
- **An LLM API key** — `export OPENAI_API_KEY=...` (any OpenAI-compatible endpoint). Required for reviewer, extractor, and summarizer agents.

### 1. Install Nous

```bash
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

### 2. Set up credentials

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://your-endpoint.example.com  # if using a proxy
```

### 3. Create a campaign

Create a `campaign.yaml` pointing to your target repo:

```yaml
research_question: >
  What mechanism drives the primary performance bottleneck?

max_iterations: 5

target_system:
  name: "Your System"
  description: >
    What the system does and its architecture.
  repo_path: /path/to/your/repo
```

The planner explores the codebase to discover metrics, knobs, and execution methods. You can optionally provide `observable_metrics` and `controllable_knobs` as hints — see [examples/campaign.yaml](examples/campaign.yaml) for all options.

### 4. Run a campaign

```bash
python run_campaign.py campaign.yaml --max-iterations 3
```

Each iteration runs the full loop (framing → design → review → execution → extraction), pausing at three human gates:

| Gate | When | You decide |
|------|------|------------|
| **Design gate** | After design review | Approve the hypothesis bundle? |
| **Findings gate** | After findings review | Approve the results? |
| **Continue gate** | After extraction | Continue to next iteration? |

Each gate shows a formatted summary. Type `approve`, `reject`, or `abort`.

Options:

```bash
python run_campaign.py campaign.yaml --max-iterations 5 -v   # verbose
python run_campaign.py campaign.yaml --model gpt-4o          # different model
python run_campaign.py campaign.yaml --auto-approve           # skip gates
```

### 5. Try the BLIS example

```bash
git clone https://github.com/inference-sim/inference-sim.git blis
cd blis && go build -o blis . && cd ..
# Edit examples/campaign.yaml: set repo_path to your blis/ path
python run_campaign.py examples/campaign.yaml --max-iterations 3
```

### Output

```
blis-run/
  state.json              # orchestrator checkpoint
  principles.json         # accumulated principles
  ledger.json             # one row per iteration
  runs/iter-N/
    problem.md            # problem framing
    bundle.yaml           # hypothesis bundle
    findings.json         # prediction vs outcome
    gate_summary_*.json   # human-readable summaries
    investigation_summary.json  # iteration summary (non-final)
    reviews/              # reviewer perspectives
```

### Run tests

```bash
pytest -v
```

## Project Structure

```
schemas/                 JSON Schema definitions (Draft 2020-12)
templates/               Starter files for new campaigns
orchestrator/            Python orchestrator (deterministic, not an LLM)
  engine.py                State machine with atomic checkpoint/resume
  dispatch.py              Stub agent dispatch (for testing without LLM)
  llm_dispatch.py          LLM-based agent dispatch via OpenAI SDK
  cli_dispatch.py          Code-access agent dispatch via claude -p
  prompt_loader.py         Template loading with {{placeholder}} rendering
  gates.py                 Human approval gates with summaries
  fastfail.py              Fast-fail rule evaluation
  ledger.py                Deterministic ledger append (no LLM)
  worktree.py              Git worktree isolation for experiments
  protocols.py             Dispatcher and Gate interface contracts
  util.py                  Shared utilities (atomic_write)
prompts/methodology/     Methodology prompt templates
examples/                Example campaigns
docs/                    Quickstart, protocol, data model, architecture
tests/                   Comprehensive test suite
```

## Case Study: LLM Inference Serving

Nous was developed and validated through 30 iterations on [BLIS](https://github.com/inference-sim/inference-sim), an LLM inference simulator. The campaign extracted 30 principles across scheduling and routing, achieving a 73.7% reduction in critical TTFT P99 latency.

Key insight: the breakthrough mechanism (SLO-gated admission control) was discovered through *refuted* predictions, not confirmed ones. A direction error in iteration 1 — where priority scheduling caused 62.4% cluster degradation instead of the predicted <10% — redirected the entire investigation toward admission control.

See [docs/case-studies/blis.md](docs/case-studies/blis.md) for the full case study with all 30 extracted principles.

## Contributing

See [docs/contributing/workflow.md](docs/contributing/workflow.md) for the Claude-based PR creation workflow.

## Current Status

**Phase 1 (complete):** Schemas, templates, orchestrator skeleton, and protocol documentation.

**Phase 2 (complete):** Agent prompts and real LLM dispatch via OpenAI SDK.

**Phase 3 (complete):** Real experiment execution with git worktree isolation.

**Phase 4 (complete):** Multi-iteration campaigns with compounding knowledge.

**Phase 4.5 (complete):** Code-access agents via CLIDispatcher (`claude -p`), simplified campaigns, and gate summaries for human UX.

**Phase 5 (next):** Plugin UX — `/nous:init`, `/nous:investigate`, `/nous:status`.

## License

Apache 2.0
