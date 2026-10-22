# Security model

A Nous campaign runs a Claude Code session with shell access in your target repository. Read this before pointing it at anything you care about.

## What the session can do

- The session runs with `permission_mode="bypassPermissions"` and `cwd` set to `target_system.repo_path`. Every tool call is auto-approved. There is no command allowlist and no write boundary.
- The agent runs as your shell user, with your network access and credentials.
- Nous commits the target checkout after each phase (`git add -A`, `git commit`). Use a dedicated clone or branch.

For anything beyond a disposable checkout, run Nous inside a container or VM with limited network and file-system access (see `s390x/` for a Podman setup).

## What Nous enforces

- **Recording.** In-process PostToolUse hooks record every Bash command, its exit code and output size in `runs.jsonl`.
- **Phase gating.** The Stop hook blocks the end of a phase until its artifacts validate. This checks the method, not safety.
- **Secrets.** Values of the env vars named in `campaign.secrets` are masked in `runs.jsonl` and `state/digest.json`. Validation fails if a value appears in `answer.json` or `report.md`. Pass secrets as env vars; never put them in `campaign.yaml`.

## Not covered

- Network egress and data exfiltration.
- Privilege escalation beyond your user.
- Prompt injection from the target repo's contents. Treat a campaign on an untrusted repo like running untrusted code.
