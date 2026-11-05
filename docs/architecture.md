# Architecture

Nous Lightweight wraps one Claude Code session. Python code (not an LLM) records commands, checks the answer and the notebook, runs one challenger and writes the final record. All runtime code lives in `orchestrator/lightweight/`; the CLI entry point is `orchestrator/cli.py`.

## The campaign (`loop.py`)

`Campaign.run()` does this, in order:

1. **Working copy.** When `repo_path` is a git repo, Nous creates (or reuses) the worktree `<repo>/.nous-experiments/<run_id>/` on branch `nous/<run_id>` and adds `.nous-experiments/` to the clone's `info/exclude`. A failure here raises `Preflight failed`. A non-git `repo_path` is used as is, with a warning, and Nous makes no commits.
2. **Task.** One session starts. `state.json` gets `phase: INVESTIGATE`. Nous sends one message: the research question, the absolute paths of `notebook.jsonl` and `answer.json`, and (with a worktree) the working-copy note "Build, run, edit and commit only in the working copy".
3. **Continue.** If the agent stops without writing `answer.json`, Nous sends "Continue the investigation..." up to `max_iterations` times.
4. **Repair.** If `answer.json` or the notebook fails its checks, Nous sends "Fix these before you stop:" with up to 10 errors, at most 2 times. Still failing means `status: partial`.
5. **Repro.** If `runs.jsonl` exists and holds no successful run of `answer.repro`, Nous sends one message asking the agent to run it exactly as written from the repository root, then repairs again.
6. **Challenger.** Only when the answer is valid. See below. If the challenger names a gap with a test, `state.json` gets `phase: CHALLENGE` (with the cost so far), Nous sends that test to the agent, and repairs again.
7. **Export, commit, record.** Nous exports the evidence, commits the worktree (`nous: iter-1 ANSWER`), writes `final_check.json` and `ledger.json`, and sets `phase: DONE`.

`run()` returns `{"stop_reason": "answered" | "partial", "iterations": 1}`.

## The session (`session.py`)

`Session.build_agent_options` sets:

- `system_prompt`: the `claude_code` preset with the method note appended (`prompts/lightweight/method.md`, plus `prompts/lightweight/checklists/<task_type>.md` when `task_type` is set). The note is static, so it caches.
- `model` (default `claude-opus-5-5`), optional `effort`, `cwd` (the working copy), `permission_mode="bypassPermissions"`.
- `env`: `CLAUDE_CODE_MAX_OUTPUT_TOKENS` at the model maximum and `NOUS_WORK_DIR`.
- `setting_sources=["project", "local"]`: the target repo's settings and `CLAUDE.md` load; the user's own `~/.claude` settings, plugins and global `CLAUDE.md` do not.
- `hooks` (below), and `resume=<session_id>` when resuming.

After each turn the session id is saved to `state.json` with the SDK and CLI versions. Transient errors (exit 143, "Fatal error in message reader", timeouts, API 5xx and 429, "overloaded") are retried twice, after 5 s and 30 s.

A full context ("prompt is too long") is handled once per turn: Nous starts a fresh session, sends a priming message built from `state/digest.json`, then sends the turn again.

The client comes from a `client_factory` argument. The CLI passes `cli._sdk_client`; tests pass `tests/fakes/sdk_client.FakeClient`.

## Hooks (`hooks.py`)

Hooks run in-process via `ClaudeAgentOptions.hooks`.

- **PostToolUse / PostToolUseFailure** (Bash only): append one row per command to `runs.jsonl` with `ts`, `phase`, `iter`, `tool_use_id`, `command` (secrets masked), `exit_code` (0 on success, parsed from the error on failure, `null` for background commands), `output_bytes`, `cwd`, `background`, `agent_id` and `experiment` (whether the command matches `experiment_commands`; the defaults match `python *search|bench|run|sweep*.py` and `make bench`).
- **Stop**: when `answer.json` exists and fails its checks, returns `decision: block` with the errors, so the agent keeps working. No answer yet means the agent paused; the stop is allowed and Nous sends a continue message instead. After 6 blocks in a row the stop is allowed and the repair messages take over.
- **PreCompact**: writes `state/digest.json` (phase, iteration, principles if any), secrets masked.

## Checks

**answer.json** (`validators.py`, schema `schemas/answer.schema.json`). Unknown top-level keys move into `extra` and never fail. All schema errors are reported at once (up to 10), each with its path. Then:

- `repro` must not `cd` anywhere and must not use the absolute path of the repo or the work dir, so it runs from the repository root in any copy.
- Each claim's evidence resolves and its `value` equals the evidence value. `evidence_detail` is checked when present; for a bare path string, the value text must appear in the file.
- No secret value appears in `answer.json` (or a `report.md`, if the agent wrote one).

**notebook.jsonl** (`notebook.py`). Each line is a JSON object with `kind` `hypothesis`, `result` or `note`. A hypothesis needs `id` and `predict`. A result needs an earlier hypothesis with the same `id`. Only the latest result per id is checked: its `status` is `confirmed`, `refuted` or `inconclusive`, and a confirmed or refuted result needs `evidence`, each item checked like a claim's. An empty notebook has no errors; it is reported, not required.

### Evidence

An evidence item is `{path, key, value}`. A relative `path` is looked up under the work dir, then the working copy; the first root that holds the file wins. A path written as `work/<file>` from the work dir's parent also resolves. An absolute path is accepted when it lies inside one of these roots.

| File | `key` | Example |
|---|---|---|
| `.json` | JSON Pointer (a missing leading `/` is added) | `/p99_ms`, `/runs/0/score` |
| `.jsonl` | `line@pointer`, line numbers from 0 | `1@/p99_ms` |
| `.csv`, `.tsv` | `column@row`, data rows from 0 | `lookup_us@0` |
| other text | regex, group 1 is the value | `p99_ms=([0-9.]+)` |

Numbers and numeric strings match within a relative tolerance of 1e-3 (`"105082"` equals `105082`). A `.json` file that is not JSON gets a direct message: save it as `.txt`/`.log` and use a regex key.

## The challenger

A fresh session with `model=claude-sonnet-5-5`, `cwd` = the work dir, the working copy as an extra dir, `setting_sources=["project", "local"]`, and `Bash`, `Write`, `Edit`, `NotebookEdit`, `WebFetch`, `WebSearch` disallowed. Its prompt gives the research question and asks it to read `answer.json`, `notebook.jsonl` and the files they cite, then reply with one JSON object: `{"gap": true, "test": ..., "why": ...}` or `{"gap": false, "why": ...}`. Nous takes the last such object in the reply.

The challenger is advice. A crash, a 15-minute timeout or a reply without a verdict is recorded in `final_check.json` (`gap: null` with an `error`) and the campaign goes on.

## Evidence export

Each claim's evidence file is copied to `<repo>/nous_evidence/<path relative to its root>` and to the same path under the work dir (mtimes kept). `evidence` becomes that repo-relative path string, and a `{path, key, value}` item moves to `evidence_detail` with the new path. A file already in the repo is cited in place. A numeric-string claim `value` becomes a number.

## Resume (`resume.py`)

`nous resume` reads `state.json`. A campaign at `phase: DONE` with a ledger row is not run again; its stop reason is returned. Otherwise Nous restores the per-session costs, reuses the worktree and resumes the saved session with "Continue the investigation..." (plus `--note`). If resuming fails before any turn succeeds, it starts a fresh session with the task message and a pointer to the existing notebook. Spend recorded before the resume (the ledger row, or the figure saved on entering `CHALLENGE`) is added to this run's cost.

## Final check (`final_check.py`)

`final_check.json` holds `answer_valid` and `evidence_errors`, `repro_recorded` (some `runs.jsonl` row with exit code 0 contains the `repro` command after normalising `export`/`cd` segments, `VAR=` prefixes, pipes and redirections), the notebook summary and errors, the challenger's reply and the final `status`. `claims_matched_fraction` and `unmeasured_noise_findings` are kept for a stable format and read 0.0 and `[]`.

## Cost meter (`cost.py`)

The authority is the CLI's own cost: each `ResultMessage.total_cost_usd` is cumulative for its session id (subagents included), so the meter adds its increase per session. Between results, or when the CLI reports no cost, it prices assistant usage from the `prices` table in `orchestrator/defaults.yaml`, counting each message once by id. The challenger's cost is included. `nous cost` sums the ledger.

## Effort (`effort.py`)

`campaign.effort` is passed to the SDK as is (unset means the model default). A turn is cut when the `ResultMessage` or the last main-agent `AssistantMessage` has `stop_reason: max_tokens`; subagent cut-offs do not count. On a cut, Nous steps one level down `max > xhigh > high > medium > low` (`low` only after 2 cuts in a row), saves `cut_offs` in `state.json`, reconnects the same session and sends "Your last reply was cut at the output limit. Write and run the simplest correct step first." This is bounded to one retry per ladder step.

## Secrets (`secrets.py`)

Values of the env vars named in `campaign.secrets` are replaced with `<secret:NAME>` in `runs.jsonl` and the digest. The answer check fails if any value appears in `answer.json`.
