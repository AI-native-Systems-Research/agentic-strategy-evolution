---
name: nous-run
description: Start a Nous campaign from a campaign.yaml. Use when the user wants to run a hypothesis-driven experiment, kick off a new investigation, or has just authored a campaign.yaml. Accepts the campaign path and an optional max-iterations override.
---

# `nous-run`

Start a Nous campaign from a `campaign.yaml`.

## When to use

- The user wants to run a new experiment described in a campaign file.
- The user says "kick off the saturation campaign", "start a Nous run", or refers to a specific campaign yaml.

## What this does

Shells out to `nous run`. Nous v2 drives one Claude session through BASELINE (once), then DESIGN and EXECUTE per iteration, then REPORT. It stops when the question is answered, the campaign stalls, or `max_iterations` is reached.

## Inputs

- `campaign` (required): path to a `campaign.yaml`.
- `max-iterations` (optional): override the iteration cap declared in the campaign.

## Run

```bash
nous run "$CAMPAIGN" ${MAX:+--max-iterations "$MAX"}
```

## Notes

- If the campaign already has a `state.json`, use `nous-resume` instead.
