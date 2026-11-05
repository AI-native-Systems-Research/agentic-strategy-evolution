# Security model

A Nous campaign runs a Claude Code session with shell access in your target repository. Read this before pointing it at anything you care about.

## What the session can do

- The session runs with `permission_mode="bypassPermissions"`. When `repo_path` is a git repo, `cwd` is a separate worktree (`<repo>/.nous-experiments/<run_id>/`); otherwise it is `repo_path` itself. Every tool call is auto-approved. There is no command allowlist and no write boundary: the worktree only keeps honest work off your checkout, it does not stop the agent from writing elsewhere.
- The agent runs as your shell user, with your network access and credentials.
- Nous commits the worktree once at the end (`git add -A`, `git commit`) on branch `nous/<run_id>`. Use a dedicated clone.

For anything beyond a disposable checkout, run Nous inside a container or VM with limited network and file-system access (see `s390x/` for a Podman setup).

## What Nous enforces

- **Recording.** In-process PostToolUse hooks record every Bash command, its exit code and output size in `runs.jsonl`.
- **Answer gating.** The Stop hook blocks the end of the session while `answer.json` or the notebook fails its checks. This checks the method, not safety.
- **Challenger.** The reviewer session cannot run Bash, write or edit files, or use the web.
- **Secrets.** Values of the env vars named in `campaign.secrets` are masked in `runs.jsonl` and `state/digest.json`. The answer check fails if a value appears in `answer.json`. Pass secrets as env vars; never put them in `campaign.yaml`.

## Not covered

- Network egress and data exfiltration.
- Privilege escalation beyond your user.
- Prompt injection from the target repo's contents. Treat a campaign on an untrusted repo like running untrusted code.
