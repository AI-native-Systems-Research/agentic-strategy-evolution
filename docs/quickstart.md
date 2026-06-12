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

When `repo_path` is set in `campaign.yaml`, the campaign directory is created at `$NOUS_CAMPAIGN_PARENT/<run_id>/` if you've exported that env var (recommended — see [Environment setup](../README.md#environment-setup)), otherwise at the legacy `<repo_path>/.nous/<run_id>/`. Issue #239 gives the rationale.

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

## Live-target campaigns (`live_target: true`)

By default Nous treats `repo_path` as a git repo and creates a fresh `git worktree` per iteration so that any source-code patches are isolated. For some campaigns there is no codebase to evolve — the thing you want to study is a *running* system: a Kubernetes cluster, a deployed service, a dataset on disk, a non-git scratch directory. Setting `live_target: true` tells Nous to skip worktree creation and run the executor directly inside `repo_path`.

Use it when:

- The target is a live system you are probing, not a codebase you are mutating (e.g. a GPU cluster, a production-like service, a workload generator).
- `repo_path` points at a directory that is not a git repo, or is a git repo whose working tree must not be branched.
- The bundle should only contain probe-style arms (config tweaks, command-line invocations, observation runs) — never `code_changes`.

Example:

```yaml
research_question: >
  Why does p99 latency spike when the cluster autoscaler kicks in?

target_system:
  name: "Staging GPU cluster"
  description: >
    Live Kubernetes cluster running our inference workload.
    The agent probes the cluster via kubectl and Prometheus; it does
    not modify source code.
  repo_path: /scratch/cluster-probe   # any working directory; need not be a git repo
  live_target: true

prompts:
  methodology_layer: "prompts/methodology"
  domain_adapter_layer: null
```

How `live_target` differs from regular observe-mode arms:

- **Observe mode** is a *bundle-level* property — an individual arm has no `code_changes`, so the executor skips patching and just runs commands. The campaign can still mix observe arms and evolve arms in the same bundle, and a worktree is still created.
- **`live_target: true`** is a *campaign-level* property — it controls the *executor environment* (no worktree, run in `repo_path` directly) and tells the planner up front that the target is a shared running system, so every arm must be a probe. Bundles with `code_changes` arms are incoherent in this mode.

Pick `live_target: true` when there is nothing meaningful to branch from; pick observe-mode arms when you have a real codebase but a particular iteration only needs to measure, not patch.

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
