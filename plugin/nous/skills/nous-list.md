---
name: nous-list
description: List all Nous campaigns under a search root (typically a target repo). Use when the user wants to see what campaigns exist, filter by status or substring, or get an overview of running vs completed work. Powered by the campaign_index module shipped in #126.
---

# `nous-list`

List Nous campaigns under a search root.

## When to use

- The user asks "what campaigns exist on this repo", "list all my Nous runs", "show me all DONE campaigns".
- The user wants to filter by run_id substring, phase, or repo.

## Inputs

- `search-root` (required): directory to walk. Typically the parent of one or more `<repo>/.nous/` directories.
- `query` (optional): case-insensitive substring filter against run_id.
- `status` (optional): filter to a specific phase (`DONE`, `EXECUTE_ANALYZE`, `INIT`, etc.).
- `repo` (optional): substring filter against the resolved repo path.

## Run

```bash
python -c "
import json, sys
from pathlib import Path
from orchestrator.campaign_index import list_campaigns

out = list_campaigns(
    Path('$SEARCH_ROOT'),
    query=$([ -n "$QUERY" ] && echo "'$QUERY'" || echo None),
    status=$([ -n "$STATUS" ] && echo "'$STATUS'" || echo None),
    repo=$([ -n "$REPO" ] && echo "'$REPO'" || echo None),
)
print(json.dumps(out, indent=2))
"
```

## Notes

- Uses the `campaign_index` foundation (#126) — pure Python, no MCP runtime needed.
- Output is JSON sorted by `run_id` for stable comparison across runs.
