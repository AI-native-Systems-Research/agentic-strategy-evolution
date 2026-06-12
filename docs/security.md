# Security model

Nous campaigns invoke an LLM agent (Claude Code) with shell-tool access against your target repository. The orchestrator's job is to make sure that access is *bounded* — agents can only see and modify what the campaign legitimately needs.

This document describes how that boundary is enforced.

## Per-campaign permission policy

When you run `nous run`, the orchestrator writes `<work_dir>/.claude/settings.json` (issue #135). The dispatcher then invokes the agent with `--settings <path>`, replacing the legacy `--dangerously-skip-permissions`.

The settings file declares:

| Key | Meaning |
|---|---|
| `permissions.allowOnly` | Absolute paths the agent may read or write. Always includes the campaign work-dir; includes the target repo when `repo_path` is set. |
| `permissions.allow` | Bash command allowlist. Built from a conservative default set (`git`, `python`, `pytest`, `grep`, …) plus any binaries referenced in `experiment_plan.yaml` arms, plus campaign-specific entries you pass via `extra_bin_allowlist`. |
| `permissions.deny` | Hard blocks. Ships with `Bash(curl https://*)`, `Bash(wget https://*)`, and `Bash(rm -rf /*)` to prevent the agent from exfiltrating data or destroying its host. |
| `hooks.Stop` | (When `bin/nous-execute-stop` exists) deterministic completion check — see #129. |
| `hooks.PreToolUse` | (When configured) plan-enforcer hook — see #128. |

### Why `--dangerously-skip-permissions` is no longer the default

`--dangerously-skip-permissions` auto-approves *every* tool call. That's appropriate for a sandboxed CI runner and a one-off experiment, but Nous campaigns run for hours against real repositories — we need writes to be bounded to the worktree by default.

The flag is still available behind explicit opt-in for emergency cases (e.g. recovering a stuck campaign), but no campaign in `examples/` uses it after #135 lands.

### Idempotency

`setup_work_dir` only writes `settings.json` if it doesn't already exist. That means you can hand-edit the file (add a custom `extra_bin_allowlist`, tweak deny rules, point `hooks.Stop` at a custom script) and a `nous resume` won't clobber your changes.

### What's NOT enforced by this layer

- **Network egress beyond the deny list.** The deny rules block the obvious cases; for hardened environments, run Nous inside a network-namespaced container.
- **Privilege escalation.** The agent runs as your shell user. Claude Code's permission system gates *which* commands run, not *what privileges* they run with.
- **Adversarial inputs from your target repo.** If the repo's source code contains prompt-injection payloads, the agent may follow them. Treat campaigns the way you'd treat any other code review of an untrusted repo.

## Hook registration

The settings file's `hooks` section wires up:

- **Stop hook** (`bin/nous-execute-stop`, #129): allows the executor to terminate only when `principle_updates.json` exists and `nous validate execution` returns pass. Cheaper and more reliable than a Haiku evaluator for schema-driven success criteria.
- **PreToolUse hook** (`bin/nous-plan-enforcer`, #128): rejects (or logs) Bash calls that aren't derivable from `experiment_plan.yaml`. Defense-in-depth on top of the allow/deny lists.

Both hooks are optional; their absence falls back to settings-only enforcement.
