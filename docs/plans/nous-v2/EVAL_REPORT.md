# Nous v2 merge-bar evaluation (R13)

The merge bar does not pass after 3 improvement rounds. The spec now calls for this report and a human decision.

Scope: by reviewer decision of 2026-10-22, R13 ran on the 3 oracle tasks only (dbg, pd, search), because this Mac has no Docker for the Frontier-CS judge. p5 and the held-out p225 move to the follow-up experiments. All numbers come from `~/nous_v2_eval/eval.sh`, which prints bar fields only. The baseline (L2) is the recorded Claude + 4-line prompt, as printed by eval.sh.

## Final round (round 3, code 816d677)

| task | run | accuracy | cost $ | × L2 | C1 | R2 | lost rounds |
|---|---|---|---|---|---|---|---|
| dbg | 1 | correct | 4.84 | 1.42 | 1.0 | 1.0 | 0 |
| dbg | 2 | correct | 3.97 | 1.17 | 0.0 | 0.0 | 0 |
| pd | 1 | wrong | 10.30 | 0.99 | 1.0 | 1.0 | 0 |
| pd | 2 | correct | 8.58 | 0.82 | 1.0 | 1.0 | 0 |
| search | 1 | search-works no, structure facts 2 | 13.39 | 4.11 | 1.0 | 1.0 | 0 |
| search | 2 | search-works no, structure facts 3 | 13.48 | 4.13 | 1.0 | 1.0 | 0 |

L2: dbg 3/3 at $3.40, pd 2/3 at $10.43, search works 2/3 with a mean of 2.0 structure facts at $3.26.

## Bar rules

1. **Accuracy.**
   - Debugging passes: 2/2 in every round.
   - Formula fails. Round 3 got 1/2, and the extra round-2 runs reached 1/4, both below L2's 2/3.
   - Search fails. Search-works is 0/2 against L2's 2/3. Structure facts (mean 2.5) beat L2's mean of 2.0.
2. **Cost (≤ 1.25× L2).**
   - pd passes at 0.82–0.99×.
   - dbg is borderline: the mean is 1.30×. Round 2's mean was 2.3×.
   - search fails at 4.1×.
3. **Trail.** C1 and R2 reached 1.0 on 5 of 6 runs. dbg rep2 scored 0 because its claim values were numeric strings, fixed after the round in 33df08e. The regression test failed on the buggy code in every dbg run (D5 true).
4. **Hooks ran.** Every run had hook rows, 0 lost rounds, 0 crashes and 0 pre-registration violations.
5. **Method ran.** Baseline came before bundle, the lock came before EXECUTE, and every finding had evidence. The validators enforce all of this, and no run was flagged. eval.sh does not print a separate method-rule check, so these points come from the validators and the ledgers.

## Evidence and what was tried

All entries in `progress.txt` cite transcript evidence; the fixes are general.

- **Round 1 → 2:** the trail rose from 0–0.33 to 0.5–1.0, formula accuracy went from 0/2 to 1/2, and dbg cost went down. The changes:
  - REPORT repair;
  - claim values checked against their evidence;
  - repro run from the repo root;
  - a method prompt that matches the schemas exactly;
  - absolute artifact paths;
  - task-criterion lines in the optimize and verify checklists.
- **Round 2 → 3:** dbg cost dropped from 2.3× to 1.3×, the C1/R2 trail reached 1.0 on 5 of 6 runs, and search structure facts went from 1.5 to 2.5. The changes:
  - evidence paths resolve across the iter dir, the work dir and the repo;
  - numeric strings match numbers;
  - `claims_needed` is append-only;
  - the repro must have run exactly as written;
  - an evidence-export path fix;
  - optimize lines on testing a knob in two regimes and scoring under each condition the task names.
- **Bugs found and fixed along the way:**
  - the cost meter was 3× too high and missed streamed usage;
  - list-valued claims crashed the stop rule;
  - a bare-word `wait_for` caused a 4-hour poll;
  - the evidence shape broke the output contract;
  - mixed evidence forms crashed REPORT;
  - B12 (output cut-off) was not wired in.

## Why search and formula still fail (transcript evidence)

- **Search, accuracy and cost.**
  - Both runs used all 10 iterations. Each iteration pays for DESIGN, EXECUTE and repairs, which drives the 4× cost.
  - The agents climbed one search family, judged themselves against references they built from their own pruned assumptions, and dropped knobs after testing them at one operating point.
  - The round-3 checklist lines lifted structure facts to 2.5 but did not make the deliverable work under the task's other conditions.
- **Formula.**
  - Runs differ in process. The correct runs answered every sub-question inside the task's fixed ranges, with the size and sign of each error.
  - The wrong runs used a summary fit statistic, or ran outside the stated range and built the headline on those points.
  - `locked_parameters` is never filled in from the task text, so the range rule is only advice.

## What to try next

1. **Fill `locked_parameters` and allowed ranges from the research question in BASELINE,** and enforce them on experiment commands, for example with a PreToolUse check on the 3.9 experiment commands. This makes "stay inside the task's setup" a hard rule, which targets the formula failures.
2. **Lower the per-iteration overhead on long tasks.** For example, merge DESIGN and EXECUTE into one turn from iteration 2 on, while keeping the lock by hashing the bundle at the first experiment command. Or raise the default `stall_iterations` sensitivity for optimize tasks. This targets search cost.
3. **Require a competing solution family by iteration 3 for optimize tasks,** with the deliverable scored under each named condition before REPORT. Today the checklist only advises this.
4. **Run p5 and the held-out p225** once the Frontier-CS judge is available, before any merge decision.
