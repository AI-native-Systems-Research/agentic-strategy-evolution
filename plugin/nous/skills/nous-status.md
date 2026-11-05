---
name: nous-status
description: Show the current status of a Nous campaign: phase, session id and ledger row. Use when the user asks "where is the campaign", "is it stuck", or "report progress".
---

# `nous-status`

Read-only campaign status.

## When to use

- The user asks where a campaign is, whether it finished, or what it cost.

## Inputs

- `target` (required): a campaign yaml, run_id, or work-dir path.

## Run

```bash
nous status "$TARGET"
nous cost "$TARGET"   # cost meter totals from ledger.json
```

## Notes

- Pure read; no LLM calls.
