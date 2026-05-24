# Design — iteration {{iteration}} for {{target_system}}

> **Methodology lives in `CLAUDE.md`** (auto-loaded by Claude Code from this campaign's
> `.nous/<run-id>/` directory). This prompt carries only the per-iteration context;
> consult CLAUDE.md for the hypothesis-bundle structure, prediction taxonomy,
> arm types, and writing standards.

## Research question
{{research_question}}

## Target system
**{{target_system}}** — {{system_description}}

- Observable metrics: {{observable_metrics}}
- Controllable knobs: {{controllable_knobs}}

## Active principles
{{active_principles}}

## Previous handoff
{{previous_handoff}}

## Iteration directory
`{{iter_dir}}` (work_dir-relative). Write `problem.md`, `bundle.yaml`, and a
`## Handoff` section so the executor and the next designer can pick up.

## Validation
Run `nous validate design --dir {{iter_dir}}` before claiming done. Fix any
errors the validator reports and rerun.
