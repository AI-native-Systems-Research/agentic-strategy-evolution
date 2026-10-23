---
name: nous-status
description: Show the current status of a Nous campaign: phase, iteration, session id and ledger rows. Use when the user asks "where is the campaign", "is it stuck", or "report progress".
---

# `nous-status`

Read-only campaign status.

## When to use

- The user asks where a campaign is, what phase it is in, or how its iterations went.

## Inputs

- `target` (required): a campaign yaml, run_id, or work-dir path.

## Run

```bash
nous status "$TARGET"
nous cost "$TARGET"   # cost meter totals from ledger.json
```

## Notes

- Pure read; no LLM calls.
