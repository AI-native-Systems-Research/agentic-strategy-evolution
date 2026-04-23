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
1. FRAMING        Planner defines research question, baseline, success criteria
2. DESIGN         Planner creates hypothesis bundle with multiple arms
   DESIGN_REVIEW  AI multi-perspective review (blocks on CRITICAL findings)
   HUMAN_GATE     Human approves, rejects, or aborts
3. RUNNING        Executor implements, runs experiment across 3+ seeds
   FINDINGS_REVIEW AI review of prediction-vs-outcome results
   HUMAN_GATE     Human approves findings
4. TUNING         Bayesian parameter optimization (skipped if H-main refuted)
5. EXTRACTION     Extractor updates principle store (insert/update/prune)
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
- **Go** (to build the BLIS simulator) — or skip real execution and use analysis mode
- **An LLM API key** — any OpenAI-compatible endpoint works

### 1. Install Nous

```bash
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

### 2. Set up your LLM

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://your-endpoint.example.com  # if using a proxy
```

Works with OpenAI, Anthropic via proxy, or any OpenAI-compatible endpoint.

### 3. (Optional) Build the BLIS simulator for real execution

```bash
git clone https://github.com/mtoslalibu/inference-sim.git blis
cd blis && go build -o blis . && cd ..
```

Then set `repo_path` in `examples/blis/campaign.yaml` to your BLIS checkout path. Without this, the executor runs in analysis mode (LLM reasons about the system without executing experiments).

### 4. Run a single iteration

```bash
python run_iteration.py examples/blis/campaign.yaml
```

### 5. Run a multi-iteration campaign

```bash
python run_campaign.py examples/blis/campaign.yaml --max-iterations 5
```

The campaign loops through iterations, pausing at human gates (design, findings, and continue gates). After each non-final iteration, it generates an investigation summary that feeds into the next design prompt. See [docs/quickstart.md](docs/quickstart.md) for details.

### What to expect

The script walks through these phases, printing progress:

| Phase | What happens | Output |
|-------|-------------|--------|
| **FRAMING** | LLM defines the research problem | `runs/iter-1/problem.md` |
| **DESIGN** | LLM creates hypothesis bundle with arms | `runs/iter-1/bundle.yaml` |
| **DESIGN REVIEW** | Multiple reviewer perspectives check the bundle | `runs/iter-1/reviews/review-*.md` |
| **HUMAN GATE** | **Pauses for your approval** — read the bundle and reviews, then type `approve` | |
| **RUNNING** | LLM designs commands, orchestrator executes them, collects real metrics | `runs/iter-1/experiment_plan.json`, `experiment_results.json` |
| **FINDINGS REVIEW** | Reviewers check prediction vs. outcome | `runs/iter-1/reviews/review-findings-*.md` |
| **HUMAN GATE** | **Pauses again** for your approval | |
| **EXTRACTION** | LLM extracts reusable principles | `principles.json` |

Output goes to `blis-run/`. The two human gates are hard stops — the system waits for you.

### Run on your own system

1. Copy `templates/campaign.yaml` and fill in your system's name, description, metrics, and knobs
2. Optionally add an `execution` block with your system's run command
3. Run: `python run_iteration.py your-campaign.yaml`

See [docs/quickstart.md](docs/quickstart.md) for details, or [examples/blis/](examples/blis/) for a complete example.

### Run tests

```bash
pytest -v
```

Comprehensive test suite covering schemas, templates, engine, gates, dispatch, fast-fail, prompt loading, and end-to-end integration.

## Project Structure

```
schemas/                 JSON Schema definitions (Draft 2020-12)
  bundle.schema.yaml       Hypothesis bundle (arms + metadata)
  campaign.schema.yaml     Campaign configuration (target system, reviewers, prompts)
  experiment_plan.schema.json  Executor experiment commands (real execution)
  findings.schema.json     Prediction-vs-outcome results
  investigation_summary.schema.json  Bounded iteration summary for cross-iteration learning
  principles.schema.json   Living principle store
  state.schema.json        Orchestrator checkpoint
  ledger.schema.json       Append-only iteration log
  summary.schema.json      Campaign rollup
  trace.schema.json        Observability log (JSONL lines)

templates/               Starter files for new campaigns
  state.json               Initial state (INIT, iteration 0)
  campaign.yaml            Campaign config (target system, reviewer panel, prompts)
  ledger.json              Baseline ledger row
  principles.json          Empty principle store
  bundle.yaml              Hypothesis bundle with TODO markers
  problem.md               Problem framing template
  findings.json            Findings template (schema-conformant)

orchestrator/            Python orchestrator (deterministic, not an LLM)
  engine.py                State machine with atomic checkpoint/resume
  dispatch.py              Stub agent dispatch (for testing without LLM)
  llm_dispatch.py          LLM-based agent dispatch via OpenAI SDK
  prompt_loader.py         Template loading with {{placeholder}} rendering
  gates.py                 Human approval gates
  fastfail.py              Fast-fail rule evaluation
  ledger.py                Deterministic ledger append (no LLM)
  worktree.py              Git worktree isolation for experiments
  protocols.py             Dispatcher and Gate interface contracts
  util.py                  Shared utilities (atomic_write)

prompts/                 Methodology prompt templates
  methodology/
    frame.md               Problem framing (planner)
    design.md              Hypothesis bundle design (planner)
    run.md                 Analysis-mode execution (executor, no execution config)
    run_plan.md            Experiment command design (executor, real execution)
    run_analyze.md         Real metrics analysis (executor, real execution)
    review_design.md       Design review from a perspective (reviewer)
    review_findings.md     Findings review from a perspective (reviewer)
    extract.md             Principle extraction (extractor)
    summarize.md           Investigation summary (extractor)

examples/
  blis/                    Reference campaign for BLIS inference simulator
    campaign.yaml            Filled-in campaign config
    README.md                Step-by-step walkthrough

docs/
  quickstart.md            How to run Nous on any target system
  protocol.md              Full methodology specification
  data-model.md            Plain-English guide to every data structure
  architecture.md          System architecture and component design
  case-studies/
    blis.md                30-iteration validation on LLM inference serving

tests/                   Comprehensive test suite (schemas, templates, engine, gates, stub + LLM dispatch, prompt loader, fastfail, protocols, integration)
```

## Case Study: LLM Inference Serving

Nous was developed and validated through 30 iterations on [BLIS](https://github.com/inference-sim/inference-sim), an LLM inference simulator. The campaign extracted 30 principles across scheduling and routing, achieving a 73.7% reduction in critical TTFT P99 latency.

Key insight: the breakthrough mechanism (SLO-gated admission control) was discovered through *refuted* predictions, not confirmed ones. A direction error in iteration 1 — where priority scheduling caused 62.4% cluster degradation instead of the predicted <10% — redirected the entire investigation toward admission control.

See [docs/case-studies/blis.md](docs/case-studies/blis.md) for the full case study with all 30 extracted principles.

## Contributing

See [docs/contributing/workflow.md](docs/contributing/workflow.md) for the Claude-based PR creation workflow.

## Current Status

**Phase 1 (complete):** Schemas, templates, orchestrator skeleton, and protocol documentation. The orchestrator drives the full state machine with stub agent dispatch.

**Phase 2 (complete):** Agent prompts and real LLM dispatch. `LLMDispatcher` replaces stubs with LLM-driven agents via the OpenAI SDK (works with any OpenAI-compatible endpoint). Methodology prompt templates, schema validation with retry, and a BLIS example campaign.

**Phase 3 (complete):** Real experiment execution. The executor runs actual experiments via shell commands, collects real metrics, and analyzes results. Two-phase executor dispatch (plan commands → run → analyze), git worktree isolation for experiments, configurable timeouts, and backward-compatible `execution` config in `campaign.yaml`. Systems without execution config fall back to analysis mode.

**Phase 4 (complete):** Multi-iteration campaigns. `run_campaign.py` loops through iterations with human continue gates, deterministic ledger tracking, and bounded investigation summaries that feed into each subsequent iteration's design prompt. Knowledge compounds across iterations via principles and summaries.

**Phase 5 (next):** Domain adapter layer, cost tracking, and trace population.

## License

Apache 2.0
