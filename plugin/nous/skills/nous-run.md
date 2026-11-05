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

Shells out to `nous run`. Nous runs one Claude session on the question: the agent keeps a notebook of hypotheses and results and finishes with `answer.json`, which Nous checks against the evidence. One independent reviewer then asks for one more check before Nous writes `final_check.json`.

## Inputs

- `campaign` (required): path to a `campaign.yaml`.
- `max-iterations` (optional): how many continue messages Nous sends if the agent stops without an answer.

## Run

```bash
nous run "$CAMPAIGN" ${MAX:+--max-iterations "$MAX"}
```

## Notes

- If the campaign already has a `state.json`, use `nous-resume` instead.
