---
name: nous-create-campaign
description: Create a Nous campaign.yaml with all the right fields filled in. Use when the user wants to author a new campaign, "set up a new investigation", create a campaign config from scratch, or asks how to wire up domain context for a Nous run. Walks through the four-item authoring checklist and prevents the silent-failure trap where domain context goes into the unimplemented `domain_adapter_layer` field instead of the reachable `target_system.description`.
---

# `nous-create-campaign`

Author a new Nous `campaign.yaml` with all the domain context the LLM agents actually need to do their job — and avoid the silent-failure trap from issue #89.

## When to use

- The user wants to start a new investigation and asks for help writing the campaign config.
- The user has a `campaign.yaml` they suspect is misconfigured (agent seems to ignore important context).
- The user asks "where should I put X in the campaign?" and X is domain-specific context (data paths, schema notes, statistical guardrails, baselines, gotchas).

## Why this skill exists

`campaign.yaml` has a field called `prompts.domain_adapter_layer` that **looks** like the right place to put domain-specific overrides — and the schema description even calls it that. **It is not yet implemented.** When set, the orchestrator emits a warning and ignores it. Authors who don't read `orchestrator/llm_dispatch.py` walk into this trap silently: the LLM never sees their carefully-prepared domain notes.

The fix is mechanical: put domain context in `target_system.description`, which IS substituted into the agent's system prompt. This skill walks the user through that — and through the four-item authoring checklist that catches the other common mistakes.

## Fields that actually reach the LLM agents

These four are the only fields substituted into agent prompts via `{{template}}` placeholders today (see `orchestrator/llm_dispatch.py::_build_context`):

  * `research_question` — the guiding question, one falsifiable sentence.
  * `target_system.description` — free-form Markdown. **This is the channel** for everything else.
  * `target_system.observable_metrics` — list of measurable outputs.
  * `target_system.controllable_knobs` — list of things the agent can change.

Everything else in `campaign.yaml` configures the orchestrator's behavior (run_id, max_iterations, prompts.methodology_layer, optional warm_start / pre_work_script / objective / theory_references / etc.) but is NOT seen by the LLM as text. If you want the agent to know about it, write about it in `target_system.description`.

## The protocol

### Step 1 — start from the scaffolder

```bash
nous create-campaign --to ./examples/<run-id>.yaml
```

This writes a heavily-commented `campaign.yaml` at the target path with TODO markers and inline guidance about every field. The comments are kept in sync with this skill.

If the user provides specifics inline (target name, run id, research question), pass them as flags:

```bash
nous create-campaign --to ./examples/saturation-v3.yaml \
    --target-name "BLIS" \
    --run-id saturation-v3 \
    --research-question "Does Token-WFQ reduce TTFT P95 under bursty loads?"
```

### Step 2 — fill in `target_system.description` carefully

This is the highest-leverage field. Use AskUserQuestion to elicit the four pieces:

1. **Data schema gotchas** — what file formats does the system consume/produce? What columns are expected? What edge cases have caused silent failures in prior runs against this system?
2. **Statistical guardrails** — what's the minimum seed count per arm? Walk-forward / time-cut split rules? How should the agent handle multiple comparisons? (Pair with `seeds_rationale` on bundle arms — issue #163.)
3. **Exact paths and run commands** — virtualenv paths, the canonical run command, where outputs go. The agent will use these literally; ambiguity here costs turns.
4. **Pre-specified baseline** — what's the comparator the agent must beat? Pre-specifying prevents cherry-picking. (Pair with `objective.deploy_threshold` if using composite scoring — issue #168.)

Long is good — `target_system.description` is part of the cached system block, so it's paid once per session, not per turn. Verbosity here is free.

### Step 3 — fill in `observable_metrics` + `controllable_knobs`

Concrete names, not categories. `latency_p50_ms`, not "latency". `evictor_threshold`, not "cache settings". The agent uses these as the experimental vocabulary.

### Step 4 — pick the optional blocks

Walk through these and ask if any apply:

- `warm_start.prior_run_id` (issue #83) — inheriting principles + handoff from a completed prior campaign on the same target.
- `pre_work_script` (issue #167) — pointing to a deterministic exploration script that runs before iter-1 to inform the design.
- `objective` or `objective_preset` (issue #168) — declaring a composite-scoring objective if the user has multi-dimensional success criteria.
- `theory_references` (issue #88) — declaring external theorems (Little's Law, M/G/K bound, etc.) the campaign should derive ground truths from.

These are all opt-in; no harm in skipping any.

### Step 5 — validate before declaring done

```bash
nous validate design --dir <campaign-dir>/runs/iter-1
```

(Won't apply until iter-1 exists, but the same `jsonschema.validate` runs against `campaign.yaml` at orchestrator startup.)

### Step 6 — DO NOT set `domain_adapter_layer`

If the user asks "what about `domain_adapter_layer`? It's in the schema." — answer:

> That's a NOT-YET-IMPLEMENTED placeholder (issue #89). Setting it triggers a warning and the value is ignored. Put domain context in `target_system.description` — that's the field the LLM actually reads.

If their existing `campaign.yaml` has `domain_adapter_layer` populated, MIGRATE the content into `target_system.description` and set `domain_adapter_layer: null`.

## Authoring checklist (paste into the YAML or keep handy)

Before running:

- [ ] `target_system.description` includes critical data schema gotchas (file formats, expected columns, edge cases that have caused silent failures in prior runs)
- [ ] `target_system.description` states statistical guardrails (minimum seeds per arm, walk-forward / time-cut splits, multiple-comparisons handling)
- [ ] `target_system.description` includes EXACT file paths, virtualenv paths, and run commands
- [ ] `target_system.description` specifies the pre-specified BASELINE the agent must beat (no cherry-picking)
- [ ] `research_question` is one falsifiable sentence with a clear directional claim
- [ ] `observable_metrics` and `controllable_knobs` are concrete (no placeholders)
- [ ] `prompts.domain_adapter_layer` is `null` (or unset) — never populated

## Notes

- Scaffolder source: `orchestrator/create_campaign.py`. The `REACHABLE_FIELDS` constant there is the source of truth and is regression-tested against the actual `_build_context` substitutions.
- Pairs with `nous-run` (kicks off a campaign once authored), `nous-status` (watches it), `nous-list` (finds prior runs to warm-start from).
- The schema `orchestrator/schemas/campaign.schema.yaml` has the canonical field list; this skill should not drift from it.
