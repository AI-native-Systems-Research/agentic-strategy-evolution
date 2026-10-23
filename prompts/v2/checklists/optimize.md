## Optimize checklist

- Baseline: the simplest valid solution, scored. Measure noise on it.
- Climb with one change per measurement. Revert when the score drops.
- When the score is flat for about 3 measurements, design competing solution families.
- Keep the best solution so far and build on it.
- Respect the task's evaluation limits (time, cost, number of submissions).
- Score with the task's own stated success criterion, written down in BASELINE; check it independently of your own search (e.g. a held-out setting or a reference the task gives). A count your own search produced is not a score.
