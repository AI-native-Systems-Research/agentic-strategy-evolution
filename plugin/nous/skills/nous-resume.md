---
name: nous-resume
description: Resume a Nous campaign that was interrupted (timeout, crash, ctrl-c, STOP). Use when the user says "resume", "continue", or references a campaign that already has a state.json.
---

# `nous-resume`

Resume an interrupted Nous campaign from its work dir.

## When to use

- The user says "resume the saturation campaign" or "pick up where it left off".
- A previous run was killed and the campaign's `state.json` exists.

## Inputs

- `target` (required): work dir, run_id, or campaign.yaml.
- `note` (optional): a human note added to the next phase message and the ledger.
- `max-iterations` (optional): override the campaign's cap.

## Run

```bash
nous resume "$TARGET" ${NOTE:+--note "$NOTE"} ${MAX:+--max-iterations "$MAX"}
```

## Notes

- Resume reconnects to the saved session id. If that fails, it starts a fresh session primed from `state/digest.json`.
