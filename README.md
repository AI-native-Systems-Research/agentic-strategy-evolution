# Nous — Hypothesis-Driven Experimentation for Software Systems

Nous is a framework that runs the scientific method on software systems. An AI agent forms a falsifiable hypothesis about system behavior, designs a controlled experiment, executes it, and extracts reusable principles from the outcome — whether the hypothesis was confirmed or refuted.

A deterministic Python orchestrator (not an LLM) drives two AI agent roles through a structured loop, producing schema-governed artifacts at every step. Knowledge compounds: principles from iteration N constrain the design space of iteration N+1.

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

**Interventions can include source-code patches.** When the research question implies an algorithmic change (not just flag tuning), add a `code_changes` entry on the arm — Nous implements the change, captures it as a `git` patch, applies it during the treatment run, and resets the worktree between conditions.

## How It Works

Each iteration follows a 6-phase loop with 2 LLM calls and 2 human gates:

```
INIT → DESIGN → HUMAN_DESIGN_GATE → EXECUTE_ANALYZE → HUMAN_FINDINGS_GATE → DONE

1. DESIGN              Planner (Opus) explores system, frames problem, designs hypothesis bundle
   HUMAN_DESIGN_GATE   Human approves, rejects (→ DESIGN), or aborts
2. EXECUTE_ANALYZE     Executor (Sonnet) builds, patches, runs experiments, analyzes results,
                       extracts principles — all in one session
   HUMAN_FINDINGS_GATE Human approves findings, rejects (→ EXECUTE_ANALYZE), or aborts
   DONE → DESIGN       Next iteration (increments counter, merges principles)
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

### Environment setup

The `claude -p` subprocess handles its own authentication via Claude CLI config. However, gate summaries and report generation use the OpenAI-compatible LLM API, which needs:

```bash
export OPENAI_API_KEY=your-api-key
export OPENAI_BASE_URL=https://your-litellm-proxy.example.com  # or any OpenAI-compatible endpoint
```

If you're using Anthropic directly via a LiteLLM proxy, point both vars at the proxy. If these aren't set, gate summaries and report generation are skipped (non-fatal). The campaign still runs — you just won't get LLM-generated summaries at the gates or a final report.

### 1. Install Nous

```bash
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

### 2. Configure models

Two LLM calls per iteration, both via `claude -p`:

| Phase | Default model | Role |
|-------|---------------|------|
| DESIGN | Opus | Planner — explores, frames, designs |
| EXECUTE_ANALYZE | Sonnet | Executor — builds, patches, runs, analyzes |

Both agents write their artifacts directly to disk and run `nous validate` before claiming done. If validation fails, the agent reads the errors, fixes the artifacts, and retries. Principle merge is Python-only (no LLM).

### 4. Create a campaign

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

When `repo_path` is set, the campaign directory is created inside the target repo at `.nous/<run_id>/`. All artifacts live there.

The planner explores the codebase to discover metrics, knobs, and execution methods. You can optionally provide `observable_metrics` and `controllable_knobs` as hints — see [examples/campaign.yaml](examples/campaign.yaml) for all options.

### 5. Run a campaign

```bash
python run_campaign.py campaign.yaml --max-iterations 3
```

Each iteration runs the full loop (design → execute+analyze → validate), pausing at two human gates:

| Gate | When | You decide |
|------|------|------------|
| **Design gate** | After DESIGN | Approve the hypothesis bundle? |
| **Findings gate** | After EXECUTE_ANALYZE | Approve the results and principles? |

Each gate shows a formatted summary. Type `approve`, `reject`, or `abort`.

Options:

```bash
python run_campaign.py campaign.yaml --max-iterations 5 -v   # verbose
python run_campaign.py campaign.yaml --auto-approve           # skip gates (for CI/non-interactive)
python run_campaign.py campaign.yaml --auto-approve --max-iterations 1  # quick unattended run
```

### 6. Try the BLIS example

```bash
git clone https://github.com/inference-sim/inference-sim.git blis
# Edit examples/campaign.yaml: set repo_path to your blis/ path
python run_campaign.py examples/campaign.yaml --max-iterations 3
```

Campaign artifacts will be created at `blis/.nous/<run_id>/`.

### Output

```
your-repo/.nous/<run_id>/
  state.json              # orchestrator checkpoint
  principles.json         # accumulated principles
  ledger.json             # one row per iteration
  handoff.md              # living exploration context (updated each iteration)
  runs/iter-N/
    problem.md            # problem framing
    bundle.yaml           # hypothesis bundle
    handoff_snapshot.md   # iteration snapshot of handoff
    experiment_plan.yaml  # exact commands per arm
    findings.json         # prediction vs outcome
    principle_updates.json # proposed principle changes
    patches/              # code diffs (evolve mode only)
    inputs/               # agent-created input files (configs, workloads)
    results/              # experiment output files
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
  validate.py              Artifact validation CLI (nous validate design/execution)
  dispatch.py              Stub agent dispatch (for testing without LLM)
  cli_dispatch.py          Code-access agent dispatch via claude -p
  prompt_loader.py         Template loading with {{placeholder}} rendering
  gates.py                 Human approval gates with summaries
  ledger.py                Deterministic ledger append (no LLM)
  worktree.py              Git worktree isolation for experiments
  util.py                  Shared utilities (atomic_write)
prompts/methodology/     Methodology prompt templates
examples/                Example campaigns
docs/                    Quickstart, protocol, data model, architecture
tests/                   Comprehensive test suite
```

## Contributing

See [docs/contributing/workflow.md](docs/contributing/workflow.md) for the Claude-based PR creation workflow.

## License

Apache 2.0
