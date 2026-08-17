# Nous — project conventions

This file is auto-loaded by Claude Code on every session in this repo. The
rules below are non-negotiable; when they conflict with general AI/coding
defaults, **the rules here win**.

## 🚧 Pre-GA: achieving goals outranks preserving behaviour

**`nous` has not reached GA.** Until the project owner explicitly says
otherwise, this applies repo-wide, not to any one branch or kind:
achieving the stated goal of a piece of work outranks preserving `nous`'s
existing observable behaviour. Semantic versioning is what covers the
change for consumers — it is not a reason to avoid making it.

This is **not** a license to regress silently. An unexplained behaviour
change is still a defect. What changes is the *default when a legacy code
path and the correct one disagree*: fix it and name the change, rather than
contorting new work to reproduce an old defect or an incidental artifact of
how something used to be implemented. Every task/PR that changes observable
behaviour should still say so and say why the new behaviour is correct — a
reviewer still checks that reasoning; they just no longer weigh it against
a preservation requirement that does not apply pre-GA.

This reverses only on explicit word from the project owner that `nous` has
reached GA.

## 🚫 Tests must NEVER make live LLM calls

**No unit, integration, or end-to-end test in this repo may make a real
API call to Anthropic, OpenAI, or any other LLM provider. Period.**

Why this is a hard rule:
- Tests run on every CI build, every contributor's laptop, and every PR
  rebase. Live LLM calls would burn tokens for no signal — the test
  result depends on what the model said today, not on the code under test.
- Token budget for `nous` is mission-critical. We refuse to spend it on
  CI churn.
- Live calls are non-deterministic. A flaky test from a model rephrasing
  itself is worse than no test.

**How to test correctly:**

| Code under test | How to mock |
|---|---|
| `LLMDispatcher` | Pass `completion_fn=` in the constructor — a callable that returns canned `chat.completions`-shaped objects. See `tests/test_llm_dispatch.py`'s `_make_fake_completion` for the pattern. |
| `CLIDispatcher` (claude -p subprocess) | Patch `orchestrator.cli_dispatch.subprocess.run` — return a `subprocess.CompletedProcess` with the JSON the test wants. See `tests/test_cli_dispatch.py`. |
| `SDKDispatcher` (Claude Agent SDK) | Pass `sdk_runner=` in the constructor — a callable returning `SDKResult`. See `tests/test_sdk_dispatch.py`'s `_ScriptedRunner`. |
| `InlineDispatcher` | Set up the `.nous_response_*` signal file in tmp_path before calling dispatch. |
| Stub-driven flows | Use `StubDispatcher` from `orchestrator.dispatch` — it produces valid schema-conformant artifacts with no LLM at all. |

**Active enforcement:** `tests/conftest.py` installs an autouse fixture
(`block_live_llm_calls`) that:
1. Strips `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the env so any
   accidental real-client construction fails loudly instead of silently
   billing.
2. Patches `urllib.request.urlopen` to refuse `api.anthropic.com`,
   `api.openai.com`, and `api.litellm.ai` hosts.
3. Patches `claude_agent_sdk.query` (when installed) to a hard-fail.

If a test triggers any of these guards, the fix is to inject a fake at
the dispatcher's seam — never to disable the guard. The guards are the
backstop; the seams are the contract.

## Behavioral testing only

When the test mock is in place, write **behavioral** tests:
- ✓ Assert what's on disk after `dispatcher.dispatch(...)`.
- ✓ Assert metrics rows in `llm_metrics.jsonl`.
- ✓ Assert artifacts match a JSON Schema.
- ✗ Don't assert which method was called on the mock.
- ✗ Don't assert argv shape, internal helper invocation, or attribute access.

The seam is the contract; the implementation is free to evolve.

## Token-budget discipline (production code)

Beyond tests, Nous itself must be frugal with tokens:
- **Methodology stays in `CLAUDE.md`** (auto-loaded by Claude Code), not
  in per-call prompts. The thin templates in `prompts/methodology/*_thin.md`
  carry only per-iteration context.
- **System blocks are cached** (`cache_control: ephemeral`). Any code
  that constructs an SDK call with a static system_prompt should rely
  on this, and any change that breaks within-iteration cache locality
  must be measured (`nous cost --cache-stats`) and justified.
- **Read-only mapping uses Explore subagents**, not Opus. See
  `orchestrator/explore_design.py`.

## Campaign-artifact location (issue #239)

Campaign work_dirs default to ``<target_repo>/.nous/<run_id>/`` for
backward compat, but the recommended setup is to export
``NOUS_CAMPAIGN_PARENT`` so artifacts live OUTSIDE the target:

```bash
# Add to your shell rc:
export NOUS_CAMPAIGN_PARENT=~/Documents/Projects/nous-campaigns
```

When set, work_dirs land at ``$NOUS_CAMPAIGN_PARENT/<run_id>/``.
The target repo's working tree stays clean — ``git stash -u`` won't
capture campaign output, ``git status`` stays uncluttered, ``git add .``
won't accidentally stage campaign content.

**The split that matters:**

| Artifact type | Lives at | Why |
|---|---|---|
| Code worktrees per arm (#133) | ``<target>/.nous-experiments/<run>/<arm>/`` | They ARE code FOR the target repo; share its git history. Unaffected by the env var. |
| Campaign artifacts (state, ledger, principles, findings, JSON results) | ``$NOUS_CAMPAIGN_PARENT/<run_id>/`` if env var set, else ``<target>/.nous/<run_id>/`` | About *experiment results*, not target's code. Env-var location avoids working-tree pollution. |

Path resolution lives in ``orchestrator/work_dir_resolver.py`` —
single source of truth (``RESOLUTION RULES`` marker). Three call
sites (``setup_work_dir``, ``cli.resolve_work_dir``, ``cli._cmd_run``)
delegate there. State.json records the resolved ``work_dir`` and
``repo_path`` for collision detection and per-campaign provenance.

``find_existing_work_dir`` provides migration grace: pre-#239
campaigns at the legacy path are still findable when the user later
sets the env var, so existing campaigns don't break on env-var
adoption.

## PR workflow (project owner: @sriumcp)

1. Branch off `upstream/main`.
2. Push to `origin` (the fork at `sriumcp/agentic-strategy-evolution`).
3. Open PR with base `upstream/main`, head `sriumcp:<branch>`.
4. PR body links the issue with `Closes #N` (or `Refs #N` for partials).
5. Stack PRs when one logical change builds on another rather than waiting
   for merge — see `docs/plans/CHECKPOINT.md` for the pattern.

`main` is the integration branch. `reflective` was the target during the
#120 epic and is no longer it — do not branch from it or open PRs against
it. If you find a branch that forked from `reflective`, rebase onto
`upstream/main` before opening the PR rather than retargeting a diverged
history.

## Graded-complexity tier discipline (issue #159)

Each iteration's bundle declares an optional ``complexity_tier`` (1..4):

| Tier | Description |
|---|---|
| 1 | single mechanism, single knob, treatment vs control |
| 2 | single mechanism + multi-knob OR ablation OR dose-response on one knob |
| 3 | multi-mechanism interactions, super-additivity, dose-response across knobs |
| 4 | cross-system / cross-workload generalization, robustness across regimes |

**Rule: iteration N may use any tier ≤ N.** Iter 1 → tier 1 only. Iter 2
→ tier 1 or 2. Etc. Sophisticated hypotheses are allowed, just *deferred
until simpler ones are ruled out*. The bundle's ``tier_justification``
explains the chosen tier given the iteration index and prior refutations.

The discipline is enforced through visibility, not refusal. The design
gate (``orchestrator.complexity_tier.format_tier_summary``) prints the
tier and prior-iteration tiers, and prominently flags jumps of more than
one tier across iterations. Humans can override; agents cannot
silently leap from tier 1 to tier 3.

## Optimization campaigns (kind: optimization)

`kind: optimization` is a second campaign type alongside the default
`reflective` one: a factorial/response-surface flow where the campaign
author (human or an AI writing the YAML) declares factors; `verify`
certifies them and compiles the policy; Python drives the epoch; `report`
writes the recommendation and its residual-regret certificate.
**Substantive model calls per campaign: 0 without `build`, 1 with it —
the only substantive model call in the kind is `build`.** Gate summaries and
the end-of-campaign report use the existing shared machinery and are not part
of the epoch. Compilation of the experimental policy is deterministic Python;
every state inside the compiled epoch is tokenless.

### 🔒 The compiled experimental policy — read this before touching `orchestrator/optimize/`

**Binding design authority:** `docs/superpowers/specs/2026-08-16-compiled-policy-design.md`.
**Implementation plan (16 tasks, TDD, phase-by-phase):**
`docs/superpowers/plans/2026-08-16-compiled-policy.md`.
Every claim below is an assertion the spec makes and the plan builds toward —
if this section and the spec ever disagree, the spec wins; fix this section.

The epoch (`screen`/`foldover`/`refine`/`confirm`/`report`/`exception`) is not
Python control flow branching on `if`/`elif`. It is an **interpreted state
machine**:

1. At the end of `verify`, `orchestrator.optimize.policy.compile_policy(campaign)`
   is a **pure function** (zero model tokens, no measurement read) that
   compiles the campaign's `optimization` block into `policy.json` — a
   schema-validated (`orchestrator/schemas/policy.schema.json`), content-hashed
   (`policy.sha256`) document. This IS the pre-registration: a policy hash
   written before the first benchmark run means every subsequent branch was
   fixed before any result was seen.
2. `check_policy(policy)` structurally validates it — every non-terminal state
   has a default transition, every conditional transition names its
   `accounting` rule, every `when` clause's observation key is in the closed
   `OBSERVATION_KEYS` vocabulary and its comparison operator is in the closed
   `COMPARISON_OPS` vocabulary (`>`, `>=`, `<`, `<=` only — **no** `==`/`!=`,
   deliberately narrower than the general-purpose `predicates.OPS` used
   elsewhere for manipulation checks; see the design spec §3.2 on why the
   compiled policy's grammar must stay closed).
3. `step(policy, state, observations) -> (next_state, rule)` is the *only*
   thing that decides what happens next inside an epoch. It is pure, total
   (defined for every observation, including an empty dict), and
   deterministic. A measurement outside the declared vocabulary is a
   **semantic exception that ends the epoch** — it is never a new branch
   invented on the fly. Every `step()` call is logged to
   `transitions.jsonl`, which is the audit trail `enumerate_paths`/
   `current_state` read back.
4. **Never add an `if`/`elif` branch to `stage_runner.py` that decides what
   the NEXT stage is.** That decision belongs in the compiled policy. If a
   new adaptive branch is needed, it is a new transition in
   `compile_policy`'s output, gated behind its own named `accounting` rule
   — not a new code path in the interpreter. An adaptive branch with no
   named inferential accounting rule (POSI, data splitting, confidence
   sequences) is explicitly a **non-goal**; it does not ship.
5. **No model call is ever made inside a compiled epoch state**, for any
   reason, including "just to interpret a result". A semantic exception ends
   the epoch instead of improvising. This is the single most important
   invariant in the kind — it is what makes the token-call table above true.

**Oracle-first discipline (spec §2.1):** no paper-aligned mechanism is
implemented before a synthetic surface exists (`orchestrator/optimize/synthetic.py`,
nine closed-form response surfaces with known optima, each named for a past
real bug) that *fails* without the mechanism and *passes* with it. If you are
adding a capability to this module and cannot point to which synthetic
surface would catch its absence, you have not finished specifying it.
`orchestrator/optimize/harness.py` drives these surfaces through the real
`stage_runner.run_stage` in-process, with no dispatcher and no LLM.

**Two verified historical defects, fixed in this line of work** (do not
reintroduce): a tabulated resolution-IV screen crashed at fit because one
column per two-factor-interaction made `XᵀX` singular under aliasing (fixed
by fitting one coefficient per **alias class**, spec §4 D1); one infeasible
row silently NaN-poisoned every fitted coefficient because the abort guard
excluded infeasible rows from its check but nothing downstream excluded them
from the fit (fixed by fitting on the complete-row subset and recording
exclusions, spec §4 D2).

When the mechanism under study does not exist in the target yet, add the
opt-in `build` stage first (`stages: [build, verify, screen, confirm]`).
It spends **one** agent call authoring the mechanism plus the native tests
its `relations` declare — the campaign's only substantive model call. `build`
makes no
correctness judgement — `verify` remains the gate, so the stage that writes
the code is never the stage that certifies it. The validator rejects `build`
anywhere but position 1 and warns when declared `native_test` files are
absent with no `build` stage to author them. Omit `build` whenever every
factor maps to a knob the target already exposes.

**Model:** every phase of a `kind: optimization` campaign resolves to
`claude-opus-5` (`orchestrator.campaign.OPTIMIZATION_MODEL`) rather than the
per-phase `defaults.yaml` models the reflective kind uses — few calls, and the
`build` call determines the quality of every downstream number. An explicit
`campaign.models.<phase>` still overrides it.

**The graded-complexity tier ladder above is scoped to `kind: reflective`
only and does not apply here.** `complexity_tier` / `tier_justification`
are rejected under `kind: optimization` wherever they appear — top level,
under `metadata`, or under the `optimization` block — because a
pre-registered design matrix already gives a *stronger* anti-p-hacking
guarantee than the tier ladder protects (every configuration is fixed
before any result is seen), so the two disciplines must not be
half-adopted together.

Before launching any optimization campaign, run
`nous validate campaign FILE --smoke`. Static validation passes campaigns that
cannot execute a single configuration; `--smoke` runs the test command and one
config to check that declared `native_test` identifiers actually resolve, that
`run_command` execs and emits parseable JSON, that the objective metric is
present, and that the manipulation predicates hold. Each of those otherwise
costs a full campaign to discover.

These campaigns are authored by AI: see
`docs/optimization-campaign-guide.md` for the mental model, the
field-by-field walkthrough of the `optimization` block, four worked
end-to-end examples, and the anti-patterns to avoid. Cross-field rules
live in `orchestrator.validate.validate_optimization_campaign`.

## Meta-findings emit at campaign end (issue #155)

Every campaign's terminal transition writes `meta_findings.json` at the
campaign work-dir. Three streams:

1. `campaign_design_lessons` — how to structure future campaigns better.
2. `target_system_asks` — what the target repo could improve.
3. `nous_asks` — what Nous itself could improve.

The emitter (`orchestrator.meta_findings.emit_meta_findings`) is **pure
Python** — zero LLM tokens. Heuristics over `ledger.json`,
`principles.json`, per-iteration `findings.json`, `retry_log.jsonl`,
and `llm_metrics.jsonl` produce structured entries with concrete
citations (iter-N, file path, tool name, error string, numeric
measurement). The validator floor (`validate_evidence`) rejects
aspirational platitudes regardless of source. See `docs/data-model.md`
for the schema.

## Spec fidelity (issue #246 / F1, friction-report #245)

Every campaign should declare ``locked_parameters`` (and, when
applicable, ``locked_workload``) for every knob whose deviation
would invalidate the experiment. The validator hard-fails any
bundle whose ``experiment_spec.verified_parameters`` deviates from
``locked_parameters`` — regardless of ``--auto-approve``. This
closes the spec-fidelity gap that allowed paper-memorytime-mirage
iter-1 to silently rewrite four locked workload parameters.

Authoring discipline lives in ``docs/campaign-authoring-guide.md``
(the "what to lock" inventory + the rehearsal-as-instrument
worked example). The full friction-report resolution map is in
``docs/friction-245-resolution.md``.

## See also

- `docs/contributing/workflow.md` — full workflow doc.
- `docs/security.md` — permission policy (#135).
- `docs/architecture.md` — internals.
- `docs/campaign-authoring-guide.md` — locked_parameters, the
  "what to lock" inventory, rehearsal-as-instrument (#245
  resolution).
- `docs/optimization-campaign-guide.md` — authoring guide for
  `kind: optimization` factorial/response-surface campaigns.
- `docs/superpowers/specs/2026-08-16-compiled-policy-design.md` — binding
  design authority for the compiled experimental policy (`policy.json`,
  `step()`, the closed observation/operator vocabularies, the residual-regret
  certificate, the fallback ladder).
- `docs/superpowers/plans/2026-08-16-compiled-policy.md` — the 16-task
  implementation plan for the compiled policy, executed via
  `superpowers:subagent-driven-development`.
- `docs/friction-245-resolution.md` — F1..F21 → file map for
  paper-memorytime-mirage friction report.
- `docs/plans/CHECKPOINT.md` — current state of the #120 epic.
