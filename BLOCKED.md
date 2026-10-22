# BLOCKED on R4c: Human smoke checkpoint 1

## What to do

1. Run the smoke test:
   ```bash
   cd ~/nous_v2_smoke
   bash smoke.sh
   ```
2. Copy the output to `docs/plans/nous-v2/smoke/1.json`.
3. Force-add and commit:
   ```bash
   git add -f docs/plans/nous-v2/smoke/1.json
   git commit -m "R4c: smoke test 1 result"
   git push origin nous-v2-wip
   ```
4. Delete this BLOCKED.md and re-run the build agent.

## Context

R4b is complete (27bd3ae). 1712 tests pass, 2086 runtime lines.
The smoke test validates the v2 runtime end-to-end on a real target.
If `smoke/1.json` has `exit_code: 0`, R4c passes. If it has failures,
they become new plan items.
