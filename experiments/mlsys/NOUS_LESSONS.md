# What the controlled study means for Nous

Written 2026-10-20 after 27 isolated, oracle-graded runs. Nous was compared with L2 (Claude Code with a short scientific
prompt and N sessions) and Nous-prompt (the same loop plus Nous's full methodology prompts, no orchestrator). Tasks:
a real BLIS bug, a model-verification question, and a config-space search. Data and per-run evidence are in
`REPORT.md`, `PROGRESS.md` and `figures/`. This note is about the Nous project, not the paper.

## 1. What we learned, in one paragraph

On tasks with a definite answer that one strong Claude Code session can reach, Nous gives **no correctness gain**. Its
methodology does not lift Nous-prompt over L2. Its machinery adds cost (1.4-9x) and new ways to fail. The model was
already competent at the "science" part (forming hypotheses, running controls, reading results). Where all arms
failed, the cause was the same for all: framing and stating conclusions (a whole-range fit hides a breakdown; "block
size is secondary"). Nous did not fix that. What Nous did produce was more **process value**: regression tests that
caught the bug every time, a second related bug found, and stronger evidence trails. None of that was rewarded by
"is the answer right".

## 2. Where Nous helped

| Observation | Evidence |
|---|---|
| Better test discipline | Nous's own regression test caught the bug in 3/3 debugging runs; L2 2/3, Nous-prompt 2/3. In two baseline runs the "regression test" passed on the buggy code too. |
| Broader investigation | One Nous run also found and fixed the same root cause inflating `AllITLs` and `TTFTSum`; upstream fixed that later (`320aa47`). No baseline did. |
| Claims backed by files | High evidence-file coverage on verification (C1 0.92-1.0 vs L2 0.64-0.8). Results, bundles and findings persist per iteration. |
| Correct answer on the hardest task once | Verification rep 4 found the fit at low rate, over-prediction at high rate, and the correct AL/AD ordering. |

These help most where **being right is not visible from the final answer alone**: audits, root-causing, work that
others must trust and re-run. They help little where one good session already lands the answer.

## 3. Where Nous struggled

### 3.1 Cost: the designer does the work, on Opus

- Nous was the most expensive arm on every task: $8.39 vs $3.40 (debug), $14.66 vs $10.43 (verification), $30.69
  vs $3.26 (search).
- **About 65% of Nous spend is the design phase** (Opus): $35.69 of $45.53 in the worst run, and 13.6-16.0 of 22-24
  in the other search runs.
- The designer is meant to plan. In practice it **runs the experiments itself**. Across all Nous design sessions:
  1,463 Bash calls, of which **358 were BLIS runs or sweeps** and 66 were builds or tests. The Sonnet executor then
  repeats the work in a worktree. That is paying Opus prices for execution, then paying again.
- Design sessions average 52-65 turns, reading 3.7-5.0M cached tokens each. The methodology prompts (`design.md` 30
  KB + `execute_analyze.md` 14 KB) plus handoff/bundle/problem files add about 20 KB per iteration of artifacts that
  later sessions must read.
- More iterations without better answers: search used 4-5 iterations ($22-46) and ended at the same hypervolume as
  1-session baselines ($3).

### 3.2 Machinery failures (filed)

- **#327**: SDK 1 MB message buffer. One PDF read killed a whole iteration.
- **#328**: one extra key in `findings.json` makes the iteration fail permanently, and its results and principles
  are dropped. One campaign lost 3 of 4 iterations of finished work (~$15).
- **#329**: the continue gate said "fully fixed" and then "continue". That cost an extra iteration ($3.67, 57 min).
- The search script miscounted its budget: 4 "probe" runs were excluded from its own count. Nous's checks did not
  catch it; the oracle did.

These failures hit only Nous: the baselines have no schema or SDK layer to break.

### 3.3 The methodology does not fix framing errors

Every arm, Nous included, made the same verification mistake: it fitted the formula over all rates and concluded "fits
moderately". It should have calibrated at low load and tested where the formula breaks. Nous's hypothesis bundles (h-main,
h-control, h-robustness) did not prevent this. Its design read the paper and still fitted both parameters freely. The
methodology structures *how* to test, not *what claim matters*.

### 3.4 Stopping and handoff

- Baselines stopped after 1 session on 22 of 24 runs; Nous used 1-5 iterations. Later iterations rarely changed the
  final answer.
- Each iteration restarts a fresh Opus designer, which re-reads code, docs and prior artifacts. That gives no
  compounding benefit visible within a single campaign.

## 4. What kind of tasks Nous fits, and which it does not

| Fits poorly (this study) | Likely fits better (not tested here) |
|---|---|
| One clear answer, reachable in one long session (bug fix, fit a formula, map a 1800-config space) | Open questions that need many experiments over hours or days, beyond one context window |
| Cheap, fast evaluator (0.1 s BLIS runs) that the agent can iterate on directly | Expensive or slow experiments (GPU clusters, real deployments), where planning before running saves real money |
| Single campaign, no reuse | Many campaigns on the same system, where principles transfer (the cross-campaign registry) |
| Graded only on the final answer | Work judged on trust: reproducible evidence, audit trail, regression tests, negative results |

This matches the earlier Frontier-CS result: with a scorer and instant feedback, plain Claude Code was at least as
good. Nous's structure pays off only when experiments are costly enough that thinking before running matters, or when
the record itself is the product.

## 5. How to improve Nous

### 5.1 Fix the robustness bugs (cheap, high value)

1. Set `max_buffer_size` (e.g. 32 MB) in both SDK option sites (#327).
2. On a `findings.json` schema error, send the error back to the executor once, or strip unknown keys, instead of
   failing the iteration. Merge principles even from a partially valid iteration (#328).
3. Give the continue gate a stop rule tied to the research question's sub-parts (#329).
4. Make the executor check budgets against the real command count, not the agent's own counter.

### 5.2 Make the methodology target framing, not only rigor

- Add a design step: "List the exact claims the research question needs and how each is tested; for a model check,
  calibrate on a regime where the model should hold, then test the regime where it may fail." That alone would have
  fixed the common verification miss.
- Ask for a "claims vs evidence" table in findings: each claim, the condition it was measured under, and whether it
  was verified. Today the bundle structures arms, not claims.
- Keep a short "framing checklist" per task type (verification, debugging, search) rather than one 30 KB generic
  design prompt.

### 5.3 Cut cost

| Change | Expected effect |
|---|---|
| Designer must not run experiments: give it read-only tools (no `blis run`, no sweeps); executions go to the Sonnet executor | Design is about 65% of spend; most of its Bash calls are execution. Plausibly halves Nous cost. |
| Designer on Sonnet for iterations 2+, or for task types where design is routine | Opus is 1.7x Sonnet on input/output |
| One persistent design session per campaign (resume), not a fresh Opus session per iteration | Avoids re-reading code and docs each iteration (3.7-5M cached tokens/iteration) |
| Trim `design.md` (30 KB) to the parts used; move rare sections behind task type | Fewer tokens per turn in every session |
| Early stop: stop when the gate summary says the question is answered (#329) | Removes extra iterations (debug rep 3, search 4-5 iterations) |
| Budget-aware stopping: cap iterations by expected value (stop when an iteration did not change any claim) | Search spent 4-5 iterations with no gain |
| Drop the packaging session by having the report step write the output contract directly | $0.8-2.2 per run |

### 5.4 Measure what Nous is for

The oracle rewarded only the final answer. If Nous's value is process, measure it directly and cheaply:
- Does the regression test fail on the buggy code (D5)?
- Does every claim re-measure (C2)?
- Does `repro` regenerate the numbers (R2)?
- Are negative results recorded?

Then test Nous where those matter: long, costly investigations, and multi-campaign reuse.

## 6. Suggested next steps for the project

1. Fix #327, #328, #329 and the budget-count gap. Re-run only the verification task (3 reps), to see whether the
   machinery fixes change its 1/3.
2. Build "lean Nous": a read-only designer, a Sonnet designer after iteration 1, and a stop rule. Measure cost on the
   same 3 tasks. Target cost close to L2's.
3. Add the claims-and-framing design step, and re-run verification for all arms with it added to Nous only. This tests
   whether methodology can fix framing.
4. Find one task where structure should matter: slow or expensive evaluations (a minutes-long benchmark, a real
   cluster) or a multi-day investigation. Compare Nous with L2 there before investing more.
