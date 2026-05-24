---
name: nous-bisect
description: Compare two iterations of the same Nous campaign — what changed in arm statuses, which principles were added between them. Use when the user wants to understand iteration deltas or debug regressions across a campaign's history.
---

# `nous-bisect`

Compare two iterations of one campaign. Powered by `compare_iterations` (#126).

## When to use

- The user asks "what changed between iter 2 and iter 3", "which principles got added in iter 4", "did h-main flip from CONFIRMED to REFUTED".
- The user is debugging a regression and wants to bisect across the campaign timeline.

## Inputs

- `campaign-root` (required): the campaign work-dir (e.g. `<repo>/.nous/<run-id>`).
- `iter-a` (required): first iteration number.
- `iter-b` (required): second iteration number.

## Run

```bash
python -c "
import json
from pathlib import Path
from orchestrator.campaign_index import compare_iterations

out = compare_iterations(Path('$CAMPAIGN_ROOT'), $ITER_A, $ITER_B)
print(json.dumps(out['delta'], indent=2))
"
```

## Notes

- Output is deterministic — calling it twice on unchanged data produces byte-equal output (no timestamps, no map-ordering leaks).
- The `delta.arm_status_changes` array names only arms whose status differs between the two iterations.
- The `delta.principles_added` array is the sorted set difference of principle IDs in `principle_updates.json` between the two iterations.
