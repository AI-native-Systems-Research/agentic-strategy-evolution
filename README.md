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
- **Claude Code CLI** (`claude`) — installed and authenticated. The Claude
  Agent SDK (the default code-access backend, `--agent sdk`) reuses your
  CLI authentication.

### Environment setup

The Claude Agent SDK handles its own authentication via Claude CLI config. However, gate summaries and report generation use the OpenAI-compatible LLM API, which needs:

```bash
export OPENAI_API_KEY=your-api-key
export OPENAI_BASE_URL=https://your-litellm-proxy.example.com  # or any OpenAI-compatible endpoint
```

If you're using Anthropic directly via a LiteLLM proxy, point both vars at the proxy. If these aren't set, gate summaries and report generation are skipped (non-fatal). The campaign still runs — you just won't get LLM-generated summaries at the gates or a final report.

### 1. Install Nous

```bash
pip install "git+https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git@reflective"
```

`reflective` is the active integration branch — that's where new work lands first. `main` lags slightly behind. To pin to a release, replace `@reflective` with a tag (`@v0.2.0`).

For development (editable install with test dependencies):

```bash
git clone -b reflective https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

The Claude Agent SDK (`claude-agent-sdk`) is a required dependency and
lands automatically — no separate install step. The legacy `--agent api`
(claude -p subprocess) backend was removed in #183; `--agent sdk` is the
default and only user-facing code-access path.

### 2. Configure models

Two LLM calls per iteration, both via the Claude Agent SDK:

| Phase | Default model | Role |
|-------|---------------|------|
| DESIGN | Opus | Planner — explores, frames, designs |
| EXECUTE_ANALYZE | Sonnet | Executor — builds, patches, runs, analyzes |

Both agents write their artifacts directly to disk and run `nous validate` before claiming done. If validation fails, the agent reads the errors, fixes the artifacts, and retries. Principle merge is Python-only (no LLM).

### 4. Create a campaign

The fastest path is the scaffolder, which writes a heavily-commented
campaign.yaml with the right defaults (including `repo_path` set to
your CWD so `nous run` doesn't silently wedge — see #184):

```bash
cd /path/to/your/repo
nous create-campaign --to ./campaign.yaml \
  --target-name "Your System" \
  --research-question "What mechanism drives the primary bottleneck?"
```

If you prefer to author by hand, use this minimum:

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

To discover the full schema (required vs optional fields, descriptions
verbatim from the schema source), run:

```bash
nous schema                      # campaign schema, Markdown (default)
nous schema bundle --format yaml # bundle schema, raw YAML for tooling
nous schema findings             # findings schema
```

Optional blocks worth knowing about:

- **`max_turns`** (#186) — per-phase tool-use budget override. Default
  is 80 design / 120 execute_analyze. A 50-arm fanout may need 200+
  design turns; a probe-only campaign fits in 30.
- **`ground_truth`** (#185) — pre-register the immutable direction
  claim and pass condition before any iteration runs. Surfaces in the
  agent's prompt verbatim alongside `target_system.description`.
- **`models`** — pin per-phase models. Defaults: Opus for DESIGN,
  Sonnet for EXECUTE_ANALYZE.
- **`theory_references`** — declare external theory anchors (Little's
  Law, M/G/K stability bound, etc.). Items can be plain strings or
  full `{name, statement, ...}` objects.

The planner explores the codebase to discover metrics, knobs, and execution methods. You can optionally provide `observable_metrics` and `controllable_knobs` as hints — see [examples/campaign.yaml](examples/campaign.yaml) for all options.

### 5. Run a campaign

```bash
nous run campaign.yaml --max-iterations 3
```

Each iteration runs the full loop (design → execute+analyze → validate), pausing at two human gates:

| Gate | When | You decide |
|------|------|------------|
| **Design gate** | After DESIGN | Approve the hypothesis bundle? |
| **Findings gate** | After EXECUTE_ANALYZE | Approve the results and principles? |

Each gate shows a formatted summary. Type `approve`, `reject`, or `abort`.

Options:

```bash
nous run campaign.yaml --max-iterations 5 -v   # verbose
nous run campaign.yaml --auto-approve           # skip gates (for CI/non-interactive)
nous run campaign.yaml --auto-approve --max-iterations 1  # quick unattended run

# Skip DESIGN entirely with a pre-authored bundle (#188 — paper repro).
# Bundle is schema-validated, hashed, and recorded in
# iter-1/bundle_manifest.json for reviewer-defensible provenance.
nous run campaign.yaml --bundle ./fig7_bundle.yaml --auto-approve
```

### Overnight / long-running campaigns

For unattended runs, increase retries and timeout so transient failures don't kill the campaign:

```bash
# High-resilience overnight run: 60-min timeout, 50 retries, 10 iterations
nous run campaign.yaml \
  --auto-approve \
  --max-iterations 10 \
  --timeout 3600 \
  --max-cli-retries 50

# Unlimited retries (never give up on transient failures)
nous run campaign.yaml \
  --auto-approve \
  --max-cli-retries -1
```

| Flag | Default | Description |
|------|---------|-------------|
| `--timeout` | 1800 (30 min) | Per-phase time limit for the Agent SDK call |
| `--max-cli-retries` | 10 | Retries per phase before giving up |
| `--max-iterations` | 10 | Total experiment iterations |

Nous retries all failures with exponential backoff (5s → 600s). A pre-flight check at campaign start validates that the CLI is installed and credentials work — if your key is wrong, you'll know in seconds, not hours.

After a run, check `retry_log.jsonl` in the campaign directory to see what failed and when.

### 6. Try the BLIS example

```bash
git clone https://github.com/inference-sim/inference-sim.git blis
# Edit examples/campaign.yaml: set repo_path to your blis/ path
nous run examples/campaign.yaml --max-iterations 3
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

### Other CLI commands

```bash
nous status campaign.yaml             # one-shot campaign phase, iteration, principles
nous status campaign.yaml --watch     # live redraw; STUCK marker after 5 min of silence
nous status campaign.yaml --line      # one-line summary (shell prompt / parent agent)
nous cost campaign.yaml               # token/cost summary from llm_metrics.jsonl
nous cost campaign.yaml --cache-stats # include prompt-cache hit-rate stats (#122)
nous report campaign.yaml             # generate report.md (uses LLM)
nous resume campaign.yaml             # resume a paused/interrupted campaign
nous replay campaign.yaml --iter 1    # re-run iteration 1 commands in fresh worktree (no LLM)
nous validate design --dir .nous/run/runs/iter-1/   # validate artifacts (agent-facing)
nous schema [campaign|bundle|findings] [--format md|json|yaml]  # print artifact schema
nous stop campaign.yaml --reason "out of budget"  # halt at next iteration boundary
```

### Quick reference: how to run nous correctly

| You want to... | Command |
|---|---|
| Discover the campaign.yaml shape | `nous schema` |
| Scaffold a starter campaign | `nous create-campaign --to ./campaign.yaml` |
| Run a campaign end-to-end | `nous run campaign.yaml` (uses `--agent sdk` by default) |
| Skip DESIGN with a pre-authored bundle | `nous run campaign.yaml --bundle path/to/bundle.yaml` |
| Watch progress live | `nous status campaign.yaml --watch` |
| Cleanly halt a running campaign | `nous stop campaign.yaml` |
| Resume after halt or interruption | `nous resume campaign.yaml` |
| Diagnose a failed iteration | `cat .nous/<run>/runs/iter-N/inputs/executor_log.jsonl` (#190) and `cat .nous/<run>/retry_log.jsonl` |
| Audit token spend | `nous cost campaign.yaml --cache-stats` |

### Observability (when nous looks stuck or wrong)

When a campaign is mid-iteration and you can't tell what's happening:

1. **`nous status --watch`** — live redraw of phase / iteration / last
   tool call. Prints `STUCK` after 5 min of dispatcher silence.
2. **`runs/iter-N/inputs/executor_log.jsonl`** (#190) — every SDK
   streaming event with timestamps. Tail it: `tail -f .nous/<run>/runs/iter-N/inputs/executor_log.jsonl`.
3. **`retry_log.jsonl`** at the campaign root — every transient failure
   with attempt count, backoff, error string. The DESIGN-incomplete
   case (#187) writes a `failure_type: "design_incomplete"` entry with
   the missing-files list and the active `max_turns`.
4. **`llm_metrics.jsonl`** at the campaign root — per-call tokens,
   cost, cache hits. `nous cost --cache-stats` aggregates this.
5. **`state.json`** — the engine's atomic phase + iteration. Safe to
   `cat` mid-run. Resume picks up from here.

When DESIGN exits without producing `bundle.yaml` / `problem.md` /
`handoff_snapshot.md`, the orchestrator raises a structured
`DesignIncompleteError` (#187) naming the missing files and listing
the four common causes — `max_turns` exhaustion, agent ran the
experiment in DESIGN, API stall, transport failure — each with a
concrete file to inspect.

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
  sdk_dispatch.py          Code-access agent dispatch via Claude Agent SDK (default)
  cli_dispatch.py          Private base class for sdk_dispatch (legacy claude -p path retired in #183)
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
