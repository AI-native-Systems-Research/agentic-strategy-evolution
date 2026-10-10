# Nous ↔ AIOpsLab adapter — design

## Goal
Let Nous investigate a live AIOpsLab Kubernetes fault and be scored by AIOpsLab's
objective evaluator (Detection Accuracy, TTL/localization, TTD, steps, tokens) — on
**Opus 4.6**, head-to-head with plain-Claude and AIOpsLab's own baseline agent.

## The mismatch (why this needs thought)
Both systems are *outer-loop orchestrators*:
- **AIOpsLab** drives the agent: `init_context(problem, instructions, apis)` once, then loops
  `action = agent.get_action(obs)` → parser → `perform_action` → repeat until `submit(...)`
  yields `VALID_SUBMISSION`, then `eval()`  (`orchestrator/orchestrator.py:145` `start_problem`).
- **Nous** also owns a loop (DESIGN → EXECUTE_ANALYZE → principle extraction) and dispatches
  Claude via the Agent SDK (`orchestrator/sdk_dispatch.py:487`). It has **no stepwise action API**.

Two outer loops can't both be outer. Resolution: **AIOpsLab stays the driver; one Nous campaign
runs inside a single `get_action` call**, and its diagnosis is returned as one `submit(...)`.

## Design
`NousAgent` (AIOpsLab-side, implements the agent contract):
- `init_context(problem_desc, instructions, apis)`: store context; render a campaign spec from
  `adapter/campaign_template.yaml` with the problem injected into `research_question` +
  `target_system.description`; `live_target: true`; all phase `models: claude-opus-4-6`;
  `repo_path` = per-run scratch dir; embed the **answer contract**: "write ONLY the submission
  argument to `$NOUS_ANSWER_FILE` as your terminal step."
- `get_action(_)`: on first call, run `nous run <campaign.yaml> --auto-approve --max-iterations 1`
  (blocking; inherits `KUBECONFIG`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`). Then read the
  answer file and return exactly one code block: ```\nsubmit(<literal>)\n```. Cache it; any later
  call re-emits the same submit.

Nous's executor investigates the live cluster directly (Bash/kubectl, `bypassPermissions`, same
kind-kind kubeconfig) and writes the submission literal to the answer file as its last step.
AIOpsLab parses `submit(...)`, evaluates, and records results — identically to every other agent.

## Fairness
- Same weights (`claude-opus-4-6`) for all configs via the one litellm proxy. Nous uses the
  Anthropic Messages path (`ANTHROPIC_BASE_URL`); baselines use the OpenAI-compatible path
  (`OPENAI_COMPATIBLE_*`). Same model, different API surface — noted.
- AIOpsLab computes all metrics; TTD/TTL includes the full Nous campaign time (honest agent time).
  We *additionally* record Nous-internal iteration/step/token counts for transparency.

## Task-type submission mapping (read from `apis` submit signature)
- detection → `submit("Yes"|"No")`
- localization → `submit(["<component>"])` (or the exact shape the problem's submit API declares)
- analysis / mitigation → later.
NousAgent passes the exact submit signature to Nous so it emits the right literal; NousAgent
`ast`-validates the literal before returning.

## Layout (reproducible; results persisted)
```
experiments/aiopslab/
  DESIGN.md  README.md  ai_ops_setup.md
  adapter/    nous_agent.py, campaign_template.yaml, submit contract
  runners/    run_nous.py, run_baseline.py, run_matrix.sh
  campaigns/  generated specs (kept for repro)
  results/    <config>/<problem_id>/<timestamp>/{session.json, results.json, nous_runs/, meta.json}
```

## Self-review (risks → mitigations)
- **R4 (critical): don't let Nous fix the fault during detection/localization.** Those tasks are
  scored with the fault still present; a mutation would corrupt the score. → Instruct Nous to
  **observe-only** (no cluster mutation) for detection/localization; allow mutation only for
  mitigation tasks. Enforce via the campaign prompt + (optionally) a read-only kubeconfig context.
- R1: `get_action` blocks for the whole campaign → AIOpsLab sees "one step," TTD large. Acceptable
  (real thinking time); we log Nous's internal steps separately.
- R2: answer file missing (Nous ended without emitting) → fallback to `runs/iter-1/findings.json`
  + `report.md`; if still nothing, emit a safe default and mark the run INVALID in meta.
- R3: submit-format mismatch per task → derive literal shape from `apis`; `ast.literal_eval` before returning.
- R5: namespace/kubeconfig — Nous must target the problem's namespace; inherit `KUBECONFIG`,
  pass the namespace from `problem_desc` into the prompt.
- R6: `max_iterations=1` underuses Nous's cross-iteration compounding (a live fault can't be
  re-injected identically per iteration). Accept; lean on within-iteration multi-arm rigor; note in write-up.

## Non-goals (v1)
No Nous core changes. No MCP tool registry. Mitigation tasks and multi-iteration deferred.
