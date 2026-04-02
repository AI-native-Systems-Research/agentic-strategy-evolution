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

### Install

```bash
pip install -e ".[dev]"
```

### Initialize a Campaign

Copy the templates to create a new campaign directory:

```bash
mkdir -p my-campaign/runs
cp templates/state.json my-campaign/
cp templates/ledger.json my-campaign/
cp templates/principles.json my-campaign/
```

Edit `my-campaign/state.json` to set your `run_id`, then use the orchestrator engine to drive the state machine:

```python
from orchestrator.engine import Engine

engine = Engine("my-campaign")
print(engine.state)  # {"phase": "INIT", "iteration": 0, ...}

engine.transition("FRAMING")
# ... dispatch agents, run reviews, advance through phases
```

### Run Tests

```bash
pytest -v
```

All 98 tests validate schemas, templates, state machine transitions, gates, dispatch, fast-fail rules, and end-to-end integration.

## Project Structure

```
schemas/                 JSON Schema definitions (Draft 2020-12)
  bundle.schema.yaml       Hypothesis bundle (arms + metadata)
  findings.schema.json     Prediction-vs-outcome results
  principles.schema.json   Living principle store
  state.schema.json        Orchestrator checkpoint
  ledger.schema.json       Append-only iteration log
  summary.schema.json      Campaign rollup
  trace.schema.json        Observability log (JSONL lines)

templates/               Starter files for new campaigns
  state.json               Initial state (INIT, iteration 0)
  ledger.json              Baseline ledger row
  principles.json          Empty principle store
  bundle.yaml              Hypothesis bundle with TODO markers
  problem.md               Problem framing template
  findings.json            Findings template (schema-conformant)

orchestrator/            Python orchestrator (deterministic, not an LLM)
  engine.py                State machine with atomic checkpoint/resume
  dispatch.py              Agent dispatch (stub dispatcher for Phase 1)
  gates.py                 Human approval gates
  fastfail.py              Fast-fail rule evaluation
  protocols.py             Dispatcher and Gate interface contracts

docs/
  protocol.md              Full methodology specification
  data-model.md            Plain-English guide to every data structure
  architecture.md          System architecture and component design
  case-studies/
    blis.md                30-iteration validation on LLM inference serving

tests/                   98 tests (schemas, templates, engine, gates, dispatch, fastfail, integration)
```

## Case Study: LLM Inference Serving

Nous was developed and validated through 30 iterations on [BLIS](https://github.com/inference-sim/inference-sim), an LLM inference simulator. The campaign extracted 30 principles across scheduling and routing, achieving a 73.7% reduction in critical TTFT P99 latency.

Key insight: the breakthrough mechanism (SLO-gated admission control) was discovered through *refuted* predictions, not confirmed ones. A direction error in iteration 1 — where priority scheduling caused 62.4% cluster degradation instead of the predicted <10% — redirected the entire investigation toward admission control.

See [docs/case-studies/blis.md](docs/case-studies/blis.md) for the full case study with all 30 extracted principles.

## Contributing

See [docs/contributing/workflow.md](docs/contributing/workflow.md) for the Claude-based PR creation workflow.

## Current Status

**Phase 1 (current):** Schemas, templates, orchestrator skeleton, and protocol documentation. The orchestrator drives the full state machine with stub agent dispatch, enabling end-to-end testing of the loop without LLM calls.

**Phase 2 (next):** Agent prompts and real LLM dispatch — replacing stubs with actual agent implementations that produce hypothesis bundles, execute experiments, run reviews, and extract principles.

## License

Apache 2.0
