---
name: nous-resume
description: Resume a Nous campaign that was interrupted (timeout, crash, ctrl-c). Use when the user says "resume", "continue", or references a campaign that already has a state.json.
---

# `nous-resume`

Resume an interrupted Nous campaign from its work dir.

## When to use

- The user says "resume the saturation campaign" or "pick up where it left off".
- A previous run was killed and the campaign's `state.json` exists.

## Inputs

- `target` (required): work dir, run_id, or campaign.yaml.
- `note` (optional): a human note added to the first message after the resume.
- `max-iterations` (optional): override the continue-message cap.

## Run

```bash
nous resume "$TARGET" ${NOTE:+--note "$NOTE"} ${MAX:+--max-iterations "$MAX"}
```

## Notes

- Resume reconnects to the saved session id. If that fails before any turn succeeds, it starts a fresh session with the task and a pointer to the existing notebook. A finished campaign is not run again.
