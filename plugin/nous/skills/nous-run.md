---
name: nous-run
description: Start a Nous campaign from a campaign.yaml. Use when the user wants to run a hypothesis-driven experiment, kick off a new investigation, or has just authored a campaign.yaml. Accepts the campaign path and an optional max-iterations override.
---

# `nous-run`

Start (or resume) a Nous campaign from a `campaign.yaml`.

## When to use

- The user wants to run a new experiment described in a campaign file.
- The user says "kick off the saturation campaign", "start a Nous run", or refers to a specific campaign yaml.

## What this does

Shells out to the `nous run` CLI with the campaign path. The orchestrator drives the standard 6-phase loop (DESIGN → HUMAN_DESIGN_GATE → EXECUTE_ANALYZE → HUMAN_FINDINGS_GATE → DONE → next iteration) until `max_iterations` is reached or the user aborts at a gate.

## Inputs

- `campaign` (required): path to a `campaign.yaml`. May be relative or absolute.
- `max-iterations` (optional): override the iteration cap declared in the campaign.
- `auto-approve` (optional, default false): skip human gates for unattended runs. Sets `NOUS_ALLOW_AUTO_APPROVE=1`.
- `agent` (optional, default `api`): one of `inline`, `api`, `sdk`.

## Run

```bash
nous run "$CAMPAIGN" --max-iterations "$MAX" --agent "$AGENT" $([ "$AUTO_APPROVE" = "true" ] && echo --auto-approve)
```

## Notes

- For unattended overnight runs, prefer `--agent sdk --auto-approve` and configure `channels:` in the campaign so gate approvals can come from Slack (#130).
- If the campaign already has a state.json mid-flight, use `nous-resume` instead.
