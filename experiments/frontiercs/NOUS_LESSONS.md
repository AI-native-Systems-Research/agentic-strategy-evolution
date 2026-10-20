# What Frontier-CS taught us about Nous (2026-10-20)

A look back over the whole Frontier-CS effort (Nous v1 to v8 and the frozen `nous-algo-v1`), plus the MLSys
controlled study on the `mlsys-exp` branch. Evidence: `NOUS_IMPROVEMENT_LOG.md` (sections 1 to 14),
`NOUS_V7_RUN_NOTES.md`, `gen/why_lose_*.py`, `experiments/mlsys/REPORT.md` on `mlsys-exp`.

## 1. The record in one table

| stage | setup | result vs Claude Code |
|---|---|---|
| v1 to v3 | research tasks gf, llm_router at $50 | about even; v1 spent ~61% of budget on design |
| v4 to v6 | $25, gf, llm_router, p0, p5, p47 | v6 won 4 of 5 narrowly (p5 +7, others +0.3 to +1), tied gf |
| Opus-5 at $25 | p5 | Claude 96.0, Nous 90.0 (Nous lost with the stronger model) |
| v7 | $50, p0, p5, p26, p58, p181 | won p0, p58, p26, lost p5, tied p181; but Claude was cut at 64k output |
| v8 / nous-algo-v1 | $50, 6 tasks, both agents at 128k output | Nous 1 (p0), Claude 3 (p26 +49, p5 +14, p58 +62), ties 2 |
| MLSys study | 3 BLIS tasks x 3 arms x 3 runs, oracle-graded | no O1 difference; Nous cost 1.4x to 9.4x more |

The most important finding: almost every earlier Nous win was explained by something other than the method.
Claude losing replies at the CLI's 64k output default, contaminated baselines (shared judge folder, unsandboxed
Nous runs that read hidden tests), and single-run noise of +-10 points. Once these were removed, Nous did not
beat a well-configured Claude Code on these tasks.

## 2. Where Nous's score actually came from

In the v8 runs, the first session (the evaluator: build a local checker, write a simple valid solution, measure
it) produced nearly all of the final score. That session is plain Claude Code work.

| task | after first session | final | added by the hypothesis loop |
|---|---|---|---|
| p0 | 79.7 | 81.8 | +2.1 |
| p44 | 74.8 | 78.9 | +4.1 |
| p5 | 45 | 45 | 0 |
| p26 | 30 | 30 | 0 |
| p225 | 0 | 38.9 | +38.9 (at the very end, after $50) |

Spend split (v8): arms 25-60%, winner sessions 20-40%, evaluator 15-27%, design 1-33%. Every session hit its cap
(5-7 wrap-ups per run). Predictions were mostly refuted (0/1, 0/2) and runs extracted 0-1 principles.

## 3. What the methodology and machinery help with

Evidence-backed, even if small:

1. **Breaking early lock-in at small budgets.** v6 at $25: p5 57 vs Claude 50. Claude ran ~15 variants of one
   approach at 49-50; Nous's distinct arms and refine loop climbed 31, 41, 50, 54, 56, 57.
2. **Instrument first.** Building a local evaluator with per-instance score and CPU time exposed what an
   aggregate score hid (p0 timeouts looked like "judge noise" to every agent, including Claude).
3. **Robustness to harness failure.** Short sessions plus saved-reasoning resume survived the 64k cut where a
   single Claude session lost whole replies. This is real value under stock settings, but it is engineering,
   not the scientific method, and it disappears once the output limit is raised.
4. **Process quality.** MLSys debugging: Nous's own regression test caught the bug in 3/3 runs (baselines 2/3),
   and one run fixed two related metrics a later upstream commit also fixed. Hypotheses, refutations and
   handoffs make a run auditable.
5. **Integrity checks.** Official-first measurement, local vs official disagreement flags, and exploit audits
   caught real gaming (gf import hook, coverage tricks). These belong in any agent harness.

## 4. What Nous struggles with

1. **Session fragmentation.** The budget is cut into capped sessions. Each new session re-reads 70-120K tokens
   (~$0.17-0.30 per turn) and starts from a summary, not the reasoning. Tasks like p26, p58 and p5 reward one
   long uninterrupted line of thought; Claude's single session climbed steadily (p26: 39 at $12, 69 at $35).
2. **Too few iterations to compound.** $50 buys 2-3 iterations. The principle store and prediction-error
   taxonomy need many cheap iterations to pay off; they never got there.
3. **Incremental bias.** Falsifiable, single-mechanism hypotheses push arms toward tweaks of the incumbent.
   p5 iteration 2 tried six local variants (all <= 45) and concluded "hard ceiling of 45"; Claude reached 59 with
   a different construction. The tier rule (simple first) adds to this.
4. **Weak validity checks.** Checks on tiny inputs passed solutions that fail at scale (p58: 64-bit overflow,
   5/100 tests correct).
5. **Overhead on easy questions.** When one session can answer (MLSys debugging, 9/9 for every arm), Nous adds
   cost (2.5x) and sometimes keeps going after the answer is known (#329).
6. **Machinery fragility.** Each version exposed new bugs: budget undercount ~10x (v7), 600 s silence guard
   killing long thoughts, gateway hangs, gate summaries waiting 10 min, 1 MB SDK buffer (#327), strict findings
   schema dropping whole iterations (#328, also p0/p5 iter-1 here). Most of v2 to v8 was spent on these, not on
   the method.
7. **Design re-planning cost.** p225 spent 33% and p26 25% of budget in design sessions.

## 5. Which tasks fit Nous

| fits Nous | does not fit Nous |
|---|---|
| multi-factor systems behavior with noise and confounders, where controls and ablations change the conclusion | one scalar score with a fast judge (Frontier-CS) |
| questions whose answer is a mechanism or a causal claim, and wrong claims are costly | tasks a single session can finish (clear bug, small optimization) |
| long campaigns that exceed one context window, with cheap repeated experiments | problems that need one deep insight more than many experiments |
| work that must be audited or handed over (provenance, refuted hypotheses, principles) | small budgets (2-3 iterations) |

The case studies (cluster-debug, flink-torchserve, admission policy) are in the left column. They have not yet
been compared against a baseline under identical conditions; that is the open evidence gap.

## 6. How to improve Nous

Ordered by expected value.

1. **Escalate, do not default.** Start as one long agent session (what the evaluator already is). Invoke the
   hypothesis loop only when it plateaus, when results disagree with predictions, or when the question asks for
   attribution. Keeps Claude's depth and adds Nous only where it helps.
2. **Keep context across steps.** Continue the winning session (resume) instead of starting fresh sessions with
   summaries; hand over the reasoning, not just the conclusion. Fewer session boundaries.
3. **Force real diversity when stuck.** On a plateau, require an alternative from a different algorithm or
   mechanism family, checked against the incumbent's approach, instead of another refinement.
4. **Validity at scale.** The instrument must test the largest allowed inputs and edge cases before any arm is
   trusted.
5. **Fix the known robustness bugs.** #328 (tolerate or repair extra findings keys), #327 (raise
   `max_buffer_size`), #329 (stop when the summary says the question is answered), #300 (verify principles
   against raw measurements).
6. **Measure the loop itself.** Log "score after first session" vs "final" on every run, so the loop's
   contribution is visible and regressions are caught.
7. **Fewer moving parts.** v8 has many budget rules (floors, reserves, soft caps, wrap-ups, repair, effort
   ladder). Each one was a fix for a failure of the previous one. A simpler loop with fewer, longer sessions
   would remove most of them.

## 7. How to reduce cost

1. **Fewer sessions.** Each session boundary costs a full context re-read and a wrap-up. Resume the winner;
   skip design calls while exploiting (v8 does this partly).
2. **Cap design at ~10% of spend.** p225 and p26 spent a quarter to a third on design.
3. **Cheaper models where reasoning is not the bottleneck.** Sonnet for running and measuring (MLSys Nous
   already does this), Haiku or Explore subagents for summaries and read-only mapping. Opus only for design and
   the hard step.
4. **Stop on answered questions** (#329) and on plateaus with no new mechanism to try.
5. **Orchestrator writes artifacts, not the LLM.** v8 removed LLM wrap-ups ($17.5 across five v7 runs); extend
   this to findings repair and packaging.
6. **Thin prompts.** Methodology in the auto-loaded CLAUDE.md, cached system blocks, per-iteration context only.

## 8. Evaluation lessons (apply to any future comparison)

1. Match every harness setting that changes outcomes; the CLI's 64k output default alone moved Claude p0 from
   26 to 74.
2. Sandbox every agent and audit transcripts; two contamination cases changed headline numbers.
3. Judge any change with at least 2 runs per task; single runs swing by +-10.
4. Separate dev tasks from held-out tasks, and freeze before held-out runs.
5. Freeze oracle matchers before reading answers, or grade blind (the MLSys matchers were edited while arm
   labels were visible).
6. Report "score from the first session vs the loop" so the method's own contribution is explicit.

## 9. Bottom line

On tasks with one score, a fast judge and a small budget, Nous is Claude Code plus overhead. Its machinery
helps most as robustness and integrity scaffolding, and its methodology has not yet shown an outcome advantage
under fair, controlled conditions. The best next step for the project is an adaptive Nous (single long session
first, scientific loop on escalation), evaluated on investigation tasks where controls and causal claims
matter, against a baseline with identical settings.
