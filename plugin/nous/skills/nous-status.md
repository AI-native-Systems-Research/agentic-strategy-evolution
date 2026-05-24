---
name: nous-status
description: Show the current status of a Nous campaign — phase, iteration, completed runs, active principles, last tool call. Use when the user asks "where is the campaign", "is it stuck", "report progress", or wants a live watch view.
---

# `nous-status`

Read-only campaign status. Supports one-shot, single-line, and live `--watch` views (#127).

## When to use

- The user asks where a campaign is, what phase it's in, whether it's stuck.
- The user wants a live view to monitor an in-flight EXECUTE_ANALYZE.
- The user wants a single-line summary suitable for a shell prompt or CI log.

## Inputs

- `target` (required): a campaign yaml, run_id, or work-dir path. The CLI auto-resolves.
- `watch` (optional): loop and redraw every 2 seconds until interrupted.
- `line` (optional): print a single-line summary instead of the multi-line panel.
- `interval` (optional, default 2.0): seconds between redraws when `watch` is set.

## Run

```bash
if [ "$WATCH" = "true" ]; then
  nous status "$TARGET" --watch --interval "${INTERVAL:-2}"
elif [ "$LINE" = "true" ]; then
  nous status "$TARGET" --line
else
  nous status "$TARGET"
fi
```

## Notes

- A `STUCK` marker fires when the most recent `executor_log.jsonl` event is more than 5 minutes old.
- This skill is a pure read — no LLM calls — so it's free to call repeatedly.
