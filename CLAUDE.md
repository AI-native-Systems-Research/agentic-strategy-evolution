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

**How to test correctly (the seams):**

| Code under test | How to fake it |
|---|---|
| `orchestrator.lightweight.session.Session` / `orchestrator.lightweight.loop.Campaign` | Pass `client_factory=` (and `challenger_factory=` for the reviewer) a callable that returns `tests/fakes/sdk_client.FakeClient`. `FakeClient` replays a script of `FakeAssistantMessage` / `FakeResultMessage`, writes `files_to_write` / `per_turn_files` to simulate the agent, and fires the registered hooks (`PostToolUse`, `PostToolUseFailure`, `Stop`, `PreCompact`) when built with `hooks=opts.hooks`. |
| `nous run` / `nous resume` (CLI) | `monkeypatch.setattr(cli, "_sdk_client", factory)` with a factory returning `FakeClient`. See `tests/lightweight/test_cli_run.py`. |
| Hooks, answer and notebook checks, final check, cost meter | Plain functions over files and dicts: build inputs in `tmp_path`, no client needed. |

**Active enforcement:** `tests/conftest.py` installs an autouse fixture
(`block_live_llm_calls`) that:
1. Strips `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `ANTHROPIC_API_KEY`
   (and `NOUS_CAMPAIGN_PARENT`) from the env.
2. Patches `urllib.request.urlopen` to refuse `api.anthropic.com`,
   `api.openai.com`, and `api.litellm.ai` hosts.
3. Patches `claude_agent_sdk.query` to a hard-fail.
4. Patches `ClaudeSDKClient.connect` to a hard-fail.

If a test triggers any of these guards, the fix is to inject a fake at
the seam, never to disable the guard. The guards are the backstop; the
seams are the contract.

## Behavioral testing only

When the fake is in place, write **behavioral** tests:
- ✓ Assert what's on disk after a campaign runs (`ledger.json`,
  `runs.jsonl`, `state.json`, `final_check.json`, `answer.json`).
- ✓ Assert `answer.json` passes `validate_answer` and the notebook `check_notebook`.
- ✗ Don't assert which method was called on the fake.
- ✗ Don't assert argv shape, internal helper invocation, or attribute access.

The seam is the contract; the implementation is free to evolve.

## Token-budget discipline (production code)

- **The method note is appended to the system prompt once per session**
  (`prompts/lightweight/method.md` plus an optional task-type checklist).
  User messages carry only the task and per-turn instructions. Keep it
  that way: the system prompt stays stable so it caches.
- **One agent session and one challenger per campaign.** Do not add other
  model calls (summaries, critics, judges); deterministic checks belong
  in Python.

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

The agent's code changes are made in a worktree of
``target_system.repo_path`` (``<repo>/.nous-experiments/<run_id>/``, branch
``nous/<run_id>``) and committed there once at the end; the user's checkout
and the work dir are never committed.

Path resolution lives in ``orchestrator/work_dir_resolver.py``, the
single source of truth (``RESOLUTION RULES`` marker). ``cli._cmd_run``
and ``cli.resolve_work_dir`` delegate there.

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
   for merge.

## See also

- `docs/architecture.md`: internals (campaign, session, hooks, checks, challenger, resume).
- `docs/data-model.md`: the notebook, the answer and every file Nous writes.
- `docs/security.md`: what the session can and cannot do.
- `docs/campaign-authoring-guide.md`: authoring practices.
- `docs/contributing/workflow.md`: full contribution workflow.
