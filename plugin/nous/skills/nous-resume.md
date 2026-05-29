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

- `target` (required): campaign.yaml path. The orchestrator reads `state.json` from `$NOUS_CAMPAIGN_PARENT/<run-id>/` if that env var is set, else from `<repo>/.nous/<run-id>/` (legacy default; #239). `find_existing_work_dir` checks both candidates plus state.json's recorded `work_dir`, so campaigns created before/after env-var adoption are both resumable.
- `max-iterations` (optional): override the campaign's cap.
- `agent` (optional): backend to use on resume — usually matches the original.

## Run

```bash
nous resume "$TARGET" --max-iterations "${MAX:-$(yq '.max_iterations' "$TARGET")}" --agent "${AGENT:-api}"
```

## Notes

- Resume is idempotent — running it on a DONE campaign starts the next iteration if `max_iterations` allows.
- If the campaign was killed mid-EXECUTE_ANALYZE, the agent receives a continuation hint and picks up from existing artifacts in the iter dir (no full re-run).
