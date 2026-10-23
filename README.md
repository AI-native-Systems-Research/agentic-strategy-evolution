# Nous: hypothesis-driven experimentation for software systems

Nous runs the scientific method on a software system. It drives one Claude Code session (through the Claude Agent SDK) through a fixed loop:

1. **BASELINE**: measure the system once before changing anything.
2. **DESIGN**: write falsifiable hypotheses with predictions relative to the baseline. Nous locks the bundle after this phase.
3. **EXECUTE**: run the planned treatment and control runs, then write findings and principle updates.
4. **REPORT**: answer the research question with evidence that Nous checks against files on disk.

DESIGN and EXECUTE repeat per iteration until the question is answered, the campaign stalls, or `max_iterations` is reached. Principles from one iteration feed the next DESIGN.

Nous enforces the method with in-process hooks and validators. Every Bash command is recorded in `runs.jsonl`. The Stop hook blocks the end of a phase until its artifacts validate (up to 6 blocks in a row; any Bash command resets the count); after each phase Nous re-validates and sends up to 2 repair messages, then records the iteration as `partial` and keeps the valid content. Start with [docs/quickstart.md](docs/quickstart.md) and read [docs/security.md](docs/security.md) before pointing Nous at a real repo (the session runs with all tool calls auto-approved). [docs/example-campaign/](docs/example-campaign/README.md) is a complete worked example. See [docs/architecture.md](docs/architecture.md) for internals, [docs/data-model.md](docs/data-model.md) for artifact shapes, and [docs/protocol.md](docs/protocol.md) for the method.

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

A minimal `campaign.yaml` ([examples/campaign.yaml](examples/campaign.yaml) adds `task_type`, `objective` and `locked_parameters`):

```yaml
research_question: >
  Does raising the cache size from 64 to 256 entries lower p99 latency,
  with the workload held fixed?
run_id: cache-p99
max_iterations: 3
target_system:
  name: My service
  description: What the system does and how to run its benchmark.
  repo_path: /path/to/repo          # required: the target git checkout
```

Required keys are `research_question` and `target_system.repo_path`. Optional keys:

| Key | Meaning |
|---|---|
| `run_id` | Work dir name. `--run-id` overrides it; if both are absent, `<campaign file's dir name>-run`. Passing the yaml to `resume`, `stop` or `status` needs `run_id` in the file (or use the work dir path). |
| `max_iterations` | Iteration cap (default 5). |
| `models.session` | Session model (default `claude-opus-4-6`). |
| `effort` | SDK effort level passed to the session. |
| `locked_parameters`, `locked_workload` | Values every `plan.json` run must use, unless the run lists the key in `workload_changes`. |
| `objective` | `{metric, direction}`; `direction` (`increase`/`decrease`) decides whether `findings.best` improved. |
| `min_improvement` | Minimum change in `best` that counts as progress (default 0). |
| `stall_iterations` | Quiet iterations in a row before stopping (default 2). |
| `task_type` | `debug`, `verify`, `optimize`, `policy`, `explain` or `other`. Adds a checklist to the method prompt. If unset, the agent picks one in BASELINE. |
| `experiment_commands` | Regexes that mark a Bash command as an experiment in `runs.jsonl`. |
| `task_limits` | `max_runs`: cap on experiment commands in `runs.jsonl`, checked when validating findings. |
| `secrets` | Env var names whose values are masked in `runs.jsonl` and the digest, and must not appear in `answer.json` or `report.md`. |
| `session_scope` | `campaign` (default) resumes the same session; `iteration` always resumes into a fresh session primed from the digest. |
| `human_gates`, `rerun_repro` | Accepted, not yet acted on. |

Any other key (for example v1 keys such as `prompts`, `critic`, `arm_sweep`) logs a warning and is ignored. `nous schema <artifact>` prints a v2 artifact schema; this table is the reference for `campaign.yaml` keys.

## Commands

```bash
nous run campaign.yaml [--max-iterations N] [--model M] [--run-id ID]
nous resume <work_dir|run_id|campaign.yaml> [--note "text"] [--max-iterations N] [--model M]
nous stop <target> [--reason "text"]
nous status <target>
nous cost <target>
nous validate {baseline,design,execute,report} --dir <dir>
nous schema {answer|baseline|bundle|findings|ledger_entry|plan|principle_updates|problem} [--format md|json|yaml]
```

- `run` refuses to start if the work dir already has `state.json`; use `resume`.
- `resume` reconnects to the saved session id. If that fails before any turn succeeds, it starts a fresh session primed from `state/digest.json`. `--note` is appended to the next phase message (the first EXECUTE after the resume, or REPORT when resuming there) and stored as `note` in that iteration's ledger row.
- `stop` writes a `STOP` sentinel. The loop checks it after each EXECUTE phase, then writes the REPORT and exits.
- `status` prints phase, iteration, session id and ledger rows. `cost` sums the cost meter from `ledger.json`.
- `validate` runs the same validators as the loop. `--dir` is `runs/iter-N` for `design`/`execute`, the work dir for `baseline`/`report`.

`--agent`, `--auto-approve`, `--timeout`, `--max-cli-retries` and `--sandbox` are accepted for v1 compatibility, print a warning and do nothing. The v1-only commands `report`, `replay`, `reports`, `create-campaign`, `lineage`, `clean` and `package` were removed; they only read v1 artifacts.

## Work dir

By default the work dir is `<repo_path>/.nous/<run_id>/`. To keep campaign output out of the target's working tree, set:

```bash
export NOUS_CAMPAIGN_PARENT=~/nous-campaigns   # work dirs go to $NOUS_CAMPAIGN_PARENT/<run_id>/
```

`resume`, `status` and `stop` accept a work-dir path or a campaign.yaml. A bare run_id is looked up under `$NOUS_CAMPAIGN_PARENT` when it is set, else under the current repo's `.nous/`.

```
<work_dir>/
  campaign.yaml          config with CLI overrides applied (used by resume)
  state.json             phase, iteration, session_id, SDK/CLI versions
  ledger.json            one row per iteration
  principles.json        merged principles
  runs.jsonl             one row per Bash command
  baseline.json          BASELINE observation and noise
  answer.json, report.md REPORT output
  nous_evidence/         copies of the files answer.json cites
  final_check.json       answer check against the record
  halt.json              written only when the failure breaker trips
  STOP                   written by `nous stop`
  state/digest.json      written before each context compaction
  runs/iter-N/
    problem.json  bundle.json  .bundle.locked.json  plan.json
    findings.json  principle_updates.json
```

Nous writes `state.json`, `ledger.json`, `principles.json`, `runs.jsonl`, `.bundle.locked.json`, `final_check.json`, `halt.json`, `state/digest.json` and `nous_evidence/`. The agent writes every other JSON file, and Nous validates it. After REPORT, Nous copies each claim's evidence file to `<repo_path>/nous_evidence/` (and the same path in the work dir) and rewrites `answer.json` to cite those repo-relative paths, so the answer is self-contained in the target repo. Nous also commits the target checkout after each phase (`nous: iter-N DESIGN`, ...), never the work dir.

## Tests

```bash
pytest -q
```

Tests never call a live LLM; see [CLAUDE.md](CLAUDE.md).

## Layout

```
orchestrator/cli.py      `nous` CLI
orchestrator/v2/         loop, session, hooks, validators, resume, cost, final check
orchestrator/v2/schemas/ JSON Schemas for v2 artifacts
prompts/v2/              method prompt and task-type checklists
examples/                example campaign.yaml
docs/example-campaign/   worked example: every artifact of a one-iteration campaign
tests/                   test suite (tests/v2/ for the v2 runtime)
s390x/                   running Nous on IBM Z via Podman (see s390x/README.md)
```

## Contributing

See [docs/contributing/workflow.md](docs/contributing/workflow.md).

## License

Apache 2.0
