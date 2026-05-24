---
name: nous-find-principle
description: Search Nous principles across one or more campaigns by substring. Use when the user wants to find prior learnings ("what have we learned about ordinal scheduling"), see if a principle exists already before adding a new one, or trace a principle back to the campaign that produced it.
---

# `nous-find-principle`

Search principles across all campaigns under a search root.

## When to use

- The user asks "what principles do we have about saturation", "have we already concluded X", "where was this principle first proposed".
- The user is authoring a new campaign and wants to check existing principles for overlap.

## Inputs

- `search-root` (required): directory to walk for campaign roots.
- `text` (required): case-insensitive substring to match against principle statements / descriptions / categories / IDs.
- `include-retired` (optional, default false): also search principles with `status: retired`.

## Run

```bash
python -c "
import json
from pathlib import Path
from orchestrator.campaign_index import search_principles

out = search_principles(
    Path('$SEARCH_ROOT'), '$TEXT',
    only_active=$([ "$INCLUDE_RETIRED" = "true" ] && echo False || echo True),
)
print(json.dumps(out, indent=2))
"
```

## Notes

- Phase A is plain substring matching. Embedding-based semantic search is gated on `OPENAI_API_KEY` and lands in #126 Phase B.
- Hits include both the principle and its source campaign (`run_id`, `path`) so you can jump to the originating findings.
- Sorted by `(run_id, principle.id)` for stable output.
