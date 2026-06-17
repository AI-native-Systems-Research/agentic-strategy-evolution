# nous-bench: how `final_answer` is rendered for the `nous` variant

This document describes what the bench framework shows the Claude-as-judge when grading the `nous` variant — and why. Audience: anyone reading or extending `bench/variants/nous.py`, or interpreting a bench `report.md`.

## What gets rendered

`bench/variants/nous.py:_read_final_answer(artifacts_dir)` returns a single multi-section string composed of (in order, separated by `\n\n---\n\n`):

1. **All iterations' findings** — every `<artifacts_dir>/runs/iter-N/findings.json` in ascending iteration order. Each rendered with a `## Iteration N findings` header. Per-arm structure preserved: `predicted` / `observed` / `status` / `diagnostic_note`, plus the cross-arm `discrepancy_analysis` summary. Multi-iteration runs show the full trajectory, not just the endpoint.

2. **Cumulative principles** — `<artifacts_dir>/principles.json`. Every active principle rendered with id, statement, regime, mechanism, applicability_bounds, confidence. Inactive principles (status `"superseded"`, `"retired"`, etc.) are filtered out. Missing or null `status` is treated as **active** (lenient default — older nous versions sometimes omit the field).

3. **Iteration ledger** — `<artifacts_dir>/ledger.json` as a markdown table: `iteration / family / h_main_result / control_result / robustness_result / prediction_accuracy`. Seed iteration (iter=0, always null fields) is skipped.

4. **Campaign report** — `<artifacts_dir>/report.md` verbatim, if present. Gracefully omitted otherwise (common — short runs or runs without an API key for the report-generator skip this).

Sources that are missing or empty produce no output; the `\n\n---\n\n` separator appears only between non-empty sources.

## Why all four

Sub-issue #292 closed the third instance of an "extraction-too-narrow" pattern that had bitten the bench twice already. Each time, nous produced structured output, the bench rendered only a slice, and the judge graded nous on what it saw rather than on what nous actually delivered.

| Phase | What was hidden from the judge | Effect |
|---|---|---|
| 1.7.1 (`bb0797d`) | Cache token fields rolled into `tokens_in` | False `hit_cap` alarm; misleading cost comparison |
| 2.7 (`8318054`) | Per-arm `predicted` / `observed` / `status` — only `discrepancy_analysis` shown | Judge scored nous 3/2 vs claude_plain 8/8 — **backwards from reality** |
| 2.8 (`220ad73`, #292) | Principles, ledger, report, all-iters findings | Judge would see only one iter's summary, missing nous's full structured deliverable |

The bench tests the paper claim that nous's structural output is its differentiator vs prompt-based baselines. Hiding that output makes the test invalid. The decision to widen all four sources at once (rather than chase each in a separate PR) is intentional — it closes the loophole shape, not just one instance.

## Where this fits in the pipeline

```
NousVariant.run()
  │
  ├── translates bench Campaign → nous-compatible yaml
  ├── invokes `nous run --auto-approve --run-id <id> ...` as subprocess
  ├── on exit, reads metrics from .nous/<id>/llm_metrics.jsonl
  ├── calls _read_final_answer(artifacts_dir)
  │     └── _render_all_findings(artifacts_dir / "runs")
  │     └── _render_principles(artifacts_dir)
  │     └── _render_ledger(artifacts_dir)
  │     └── _render_report(artifacts_dir)
  └── returns VariantResult{final_answer=<rendered string>, ...}

bench/runner.py
  └── after all variants complete, passes each variant's final_answer to
      bench/judge.py:run_judge(...) which scores correctness + completeness
```

The judge sees `final_answer` (and only `final_answer`) for every variant. For `nous`, that's the full structured output — findings + principles + ledger + report. For `claude_plain`, `claude_methodology`, and the loop variants, it's whatever the agent produced as its last reply, which is what each variant naturally generates. (Note: `claude_methodology` does NOT produce structured artifacts like nous — it gets the methodology as a system prompt, but its `final_answer` is still just the agent's prose reply.)

## How to read a bench `report.md`

When you open `runs/<run_id>/report.md`, the `### nous` section's "Final answer" subsection shows the full rendered output described above. Look for:

- `## Iteration N findings` headers — one per iteration nous completed
- `## Principles extracted` — the cumulative knowledge store
- `## Iteration ledger` — the per-iteration outcome table with prediction accuracy
- `## Campaign report` — the formal write-up (if present)

The judge's rationale (in the same section) cites these explicitly when scoring — e.g. "actual measurements across four prefix fractions" refers to the iter-N findings; "mechanistically validated negative control" refers to a per-arm observation.

## How to extend for future variants

If a future variant produces structured artifacts (the way `nous` produces `findings.json`, `principles.json`, etc.), it should implement its own renderer modeled on the `_render_*` pattern in `bench/variants/nous.py` and compose the result into its `VariantResult.final_answer`. The judge sees only the rendered string; the variant decides what goes into it.

Currently, only `nous` produces structured artifacts. The other 4 variants (`claude_plain`, `claude_loop`, `claude_methodology`, `claude_methodology_loop`) just return the agent's last reply as `final_answer` — that's the right thing for them, since they're prompt-based variants without nous's artifact pipeline.

The design intent is: each variant's `final_answer` is **what an honest reviewer would say that variant produced**. For nous that's the full structured output. For prompt-based variants without structured output, it's the agent's response.

## Source

- `bench/variants/nous.py` — `_read_final_answer` and the four `_render_*` helpers
- `tests/test_bench_variants_nous.py` — 35 tests covering each helper, composition, missing-source paths, and edge cases
- Closed by commit `220ad73` (sub-issue #292)
