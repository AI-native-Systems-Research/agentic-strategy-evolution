# Quickstart

## Prerequisites

- Python 3.11+
- Claude Code CLI (`claude`), installed and logged in
- A target system in a git repo

## Install

```bash
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

Optionally keep campaign output outside the target repo:

```bash
export NOUS_CAMPAIGN_PARENT=~/nous-campaigns
```

## Write a campaign

```yaml
research_question: >
  What mechanism drives the main latency bottleneck in this system?
run_id: my-first-campaign
max_iterations: 3
target_system:
  name: My system
  description: What the system does and what to investigate.
  repo_path: /path/to/your/repo
locked_parameters:          # optional: values every planned run must use
  duration_seconds: 600
```

See the README for every key. [examples/campaign.yaml](../examples/campaign.yaml) is a working example (set its `repo_path`).

## Run

```bash
nous run campaign.yaml
```

Nous prints the work dir, then runs BASELINE, DESIGN and EXECUTE per iteration, and REPORT in one Claude session. It prints a JSON summary with `stop_reason` and `iterations` at the end.

While it runs, from another terminal:

```bash
nous status <work_dir>      # phase, iteration, ledger rows
nous stop <work_dir>        # halt after the current iteration, then REPORT
```

If the process dies or you press Ctrl+C:

```bash
nous resume <work_dir> --note "use 5 seeds per arm"
```

## Read the results

- `answer.json`, `report.md`: the answer and its evidence.
- `final_check.json`: whether the answer's evidence resolves and the repro command was actually run.
- `ledger.json`: one row per iteration (stop reason, cost, prereg violations). `nous cost <work_dir>` sums the cost.
- `runs/iter-N/`: problem, bundle, plan, findings and principle updates for each iteration.
- `runs.jsonl`: every Bash command the agent ran.

See [data-model.md](data-model.md) for each file and [architecture.md](architecture.md) for how the loop works.
