# Nous: hypothesis-driven experimentation for software systems

Nous gives Claude Code a research question about a software system and lets it investigate the way it normally would, in one session (through the Claude Agent SDK). Nous adds a light scientific discipline around that session. Nous Lightweight replaces the earlier phase-based Nous.


1. **Notebook.** The agent writes each hypothesis, with a prediction, before testing it, and each result afterwards, with the file that holds the measured number (`notebook.jsonl`).
2. **Checked answer.** The agent finishes with `answer.json`: the answer, the deliverable, one `repro` command and quantitative claims. Each claim cites a file, and Nous checks that the value is really there.
3. **Record.** Every Bash command is recorded in `runs.jsonl`. Nous looks there for a successful run of the `repro` command. If there is none, Nous asks the agent once to run it. Nous never runs it itself.
4. **Challenger.** One fresh, read-only reviewer session (`claude-sonnet-5-5`, 15 minute timeout) reads the answer and the notebook and names the strongest untested reason the conclusion could be wrong. The agent runs that check and updates the answer. If the reviewer fails or times out, the campaign goes on without it.

At the end Nous copies the cited evidence into the target repo and writes `final_check.json`. Cost is measured and reported only; it never drives a decision.

Start with [docs/quickstart.md](docs/quickstart.md) and read [docs/security.md](docs/security.md) before pointing Nous at a real repo (the session runs with all tool calls auto-approved). [docs/example-campaign/](docs/example-campaign/README.md) is a complete worked example. [docs/architecture.md](docs/architecture.md) describes the internals and [docs/data-model.md](docs/data-model.md) every file.

## Install

Requires Python 3.11+ and the Claude Code CLI, installed and logged in. The SDK reuses the CLI's authentication.

```bash
pip install "git+https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git"

# Development install
git clone https://github.com/AI-native-Systems-Research/agentic-strategy-evolution.git
cd agentic-strategy-evolution
pip install -e ".[dev]"
```

## Campaign file

A minimal `campaign.yaml` ([examples/campaign.yaml](examples/campaign.yaml) adds `task_type` and `experiment_commands`):

```yaml
research_question: >
  Does raising the cache size from 64 to 256 entries lower p99 latency,
  with the workload held fixed?
run_id: cache-p99
target_system:
  name: My service
  description: What the system does and how to run its benchmark.
  repo_path: /path/to/repo          # required: the target git checkout
```

Required keys are `research_question` and `target_system.repo_path`. The task message holds only the research question. Nous does not send `target_system.name` or `target_system.description` to the agent, so put anything the agent must know (benchmark command, fixed parameters) in the question. Optional keys:

| Key | Meaning |
|---|---|
| `run_id` | Work dir name. `--run-id` overrides it; if both are absent, `<campaign file's dir name>-run`. Passing the yaml to `resume` or `status` needs `run_id` in the file (or use the work dir path). |
| `max_iterations` | How many "continue" messages Nous sends when the agent stops without writing `answer.json` (default 5). |
| `models.session` (or `models.design`, or `model`) | Session model (default `claude-opus-5-5`). `--model` overrides it. The challenger always uses `claude-sonnet-5-5`. |
| `effort` | SDK effort level for the session: `low`, `medium`, `high`, `xhigh` or `max`. Unset means the model default. Nous steps it down when a reply is cut at the output limit. |
| `task_type` | Optional hint: `debug`, `verify`, `optimize`, `policy` or `explain` adds a short checklist to the method note. `other` (or any other value) adds none. |
| `experiment_commands` | Regexes that mark a Bash command as an experiment in `runs.jsonl`. The defaults match `python <...search|bench|run|sweep...>.py` and `make bench`. |
| `secrets` | Env var names whose values are masked in `runs.jsonl` and the digest, and must not appear in `answer.json`. |

Keys from the earlier Nous (`locked_parameters`, `locked_workload`, `objective`, `min_improvement`, `stall_iterations`, `session_scope`, `task_limits`, `human_gates`, `rerun_repro`, `nous_version`) are accepted and ignored. Any other key logs a warning and is ignored.

## Commands

```bash
nous run campaign.yaml [--max-iterations N] [--model M] [--run-id ID]
nous resume <work_dir|run_id|campaign.yaml> [--note "text"] [--max-iterations N] [--model M]
nous status <target>
nous cost <target>
```

- `run` refuses to start if the work dir already has `state.json`; use `resume`.
- `resume` reconnects to the saved session id and asks the agent to continue. If that fails before any turn succeeds, it starts a fresh session with the task again and a pointer to the existing notebook. `--note` is appended to that first message. A finished campaign (`phase: DONE`) is not run again.
- `status` prints phase, session id and the ledger row. `cost` sums the cost meter from `ledger.json`.

## Work dir

By default the work dir is `<repo_path>/.nous/<run_id>/`. To keep campaign output out of the target's working tree, set:

```bash
export NOUS_CAMPAIGN_PARENT=~/nous-campaigns   # work dirs go to $NOUS_CAMPAIGN_PARENT/<run_id>/
```

`resume` and `status` accept a work-dir path or a campaign.yaml. A bare run_id is looked up under `$NOUS_CAMPAIGN_PARENT` when it is set, else under the current repo's `.nous/`.

```
<work_dir>/
  campaign.yaml          config with CLI overrides applied (used by resume)
  notebook.jsonl         the agent's hypotheses and results
  answer.json            the agent's answer (rewritten by the evidence export)
  runs.jsonl             one row per Bash command
  nous_evidence/         copies of the files answer.json cites
  final_check.json       answer and notebook checks, and the challenger's reply
  ledger.json            one row: status, stop reason, cost, tokens
  state.json             phase, session id, SDK/CLI versions, session costs
  state/digest.json      written before each context compaction
```

When `repo_path` is a git repo, the agent works in a separate worktree, `<repo_path>/.nous-experiments/<run_id>/` on branch `nous/<run_id>`, so your checkout is never changed. Nous lists `.nous-experiments/` in the clone's `info/exclude` and commits the worktree once at the end (`nous: iter-1 ANSWER`). The work dir is never committed.

## Tests

```bash
pytest -q
```

Tests never call a live LLM; see [CLAUDE.md](CLAUDE.md).

## Layout

```
orchestrator/cli.py           `nous` CLI
orchestrator/lightweight/     campaign loop, session, hooks, notebook and answer checks, cost, resume
orchestrator/lightweight/schemas/answer.schema.json
prompts/lightweight/          method note and task-type checklists
examples/                     example campaign.yaml
docs/example-campaign/        worked example: every file of a finished campaign
tests/                        test suite (tests/lightweight/ for the runtime)
```

## Contributing

See [docs/contributing/workflow.md](docs/contributing/workflow.md).

## License

Apache 2.0
