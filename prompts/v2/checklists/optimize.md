## Optimize checklist

- Baseline: the simplest valid solution, scored, with its noise.
- Climb one change per measurement; revert when the score drops. After ~3 flat measurements, design competing solution families.
- Respect the task's evaluation limits (time, cost, submissions).
- Score with the task's stated success criterion, written in BASELINE, checked independently of your search. A count your search produced is not a score.
- Before dropping a variable from the search, test it in at least two contrasting settings; the deliverable must not hard-code a fact measured in one setting only.
- Score the deliverable under each condition the task names (other inputs, held-out settings), not only the one you tuned on.
