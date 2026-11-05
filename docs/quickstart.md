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
target_system:
  name: My system
  description: Notes for people reading the file. Nous does not send this to the agent.
  repo_path: /path/to/your/repo
```

The research question is the only task text the agent gets, so name the benchmark command and anything that must stay fixed there. See the README for every key. [examples/campaign.yaml](../examples/campaign.yaml) is a working example (set its `repo_path`). [example-campaign/](example-campaign/README.md) shows every file a finished campaign leaves behind.

## Run

```bash
nous run campaign.yaml
```

Nous prints the work dir, then runs one Claude session on the question in a worktree of your repo. It prints a JSON summary with `stop_reason` at the end.

While it runs, from another terminal:

```bash
nous status <work_dir>      # phase and session id
```

If the process dies or you press Ctrl+C:

```bash
nous resume <work_dir> --note "use 5 seeds per arm"
```

## Read the results

- `answer.json`: the answer and its claims. The cited files are also copied to `<repo>/nous_evidence/`.
- `notebook.jsonl`: the hypotheses the agent tested and what it found.
- `final_check.json`: whether the answer's evidence resolves, whether the repro command was actually run, and what the challenger asked.
- `ledger.json`: status, cost and tokens. `nous cost <work_dir>` sums the cost.
- `runs.jsonl`: every Bash command the agent ran.
- The agent's code changes are on branch `nous/<run_id>` of your repo.

See [data-model.md](data-model.md) for each file and [architecture.md](architecture.md) for how Nous works.
