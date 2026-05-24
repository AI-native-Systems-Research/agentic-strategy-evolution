---
name: nous-resume
description: Resume a Nous campaign that was interrupted mid-flight (timeout, crash, ctrl-c). Picks up at the last checkpointed phase. Use when the user says "resume", "continue", or references a campaign that already has a state.json.
---

# `nous-resume`

Resume an interrupted Nous campaign from the latest checkpoint (#91).

## When to use

- The user says "resume the saturation campaign" or "pick up where it left off".
- A previous run was killed and the campaign's `state.json` is mid-flight (phase != INIT, != DONE).

## Inputs

- `target` (required): campaign.yaml path. The orchestrator reads the matching `<repo>/.nous/<run-id>/state.json` to find the resume point.
- `max-iterations` (optional): override the campaign's cap.
- `agent` (optional): backend to use on resume — usually matches the original.

## Run

```bash
nous resume "$TARGET" --max-iterations "${MAX:-$(yq '.max_iterations' "$TARGET")}" --agent "${AGENT:-api}"
```

## Notes

- Resume is idempotent — running it on a DONE campaign starts the next iteration if `max_iterations` allows.
- If the campaign was killed mid-EXECUTE_ANALYZE, the agent receives a continuation hint and picks up from existing artifacts in the iter dir (no full re-run).
