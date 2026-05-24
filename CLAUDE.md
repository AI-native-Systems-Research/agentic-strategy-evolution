# Nous — project conventions

This file is auto-loaded by Claude Code on every session in this repo. The
rules below are non-negotiable; when they conflict with general AI/coding
defaults, **the rules here win**.

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

## PR workflow (project owner: @sriumcp)

1. Branch off `upstream/reflective` (NOT `main`).
2. Push to `origin` (the fork at `sriumcp/agentic-strategy-evolution`).
3. Open PR with base `upstream/reflective`, head `sriumcp:<branch>`.
4. PR body links the issue with `Closes #N` (or `Refs #N` for partials).
5. Stack PRs when one logical change builds on another rather than waiting
   for merge — see `docs/plans/CHECKPOINT.md` for the pattern.

## See also

- `docs/contributing/workflow.md` — full workflow doc.
- `docs/security.md` — permission policy (#135).
- `docs/architecture.md` — internals.
- `docs/plans/CHECKPOINT.md` — current state of the #120 epic.
