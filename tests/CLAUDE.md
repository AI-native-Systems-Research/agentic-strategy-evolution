# Tests — local conventions

This file is auto-loaded whenever Claude Code is operating inside `tests/`.
It restates the non-negotiable rules from the root `CLAUDE.md` so they're
in scope even when the repo root isn't.

## 🚫 NEVER make live LLM calls in tests

This applies to **unit, integration, and end-to-end tests alike**. There
is no test category in this repo that's allowed to spend tokens against
a real provider.

**Active enforcement** (see `tests/conftest.py`):
- `block_live_llm_calls` autouse fixture strips `OPENAI_API_KEY`,
  `OPENAI_BASE_URL`, `ANTHROPIC_API_KEY` and `NOUS_CAMPAIGN_PARENT`, and
  patches `urllib.request.urlopen` (LLM hosts), `claude_agent_sdk.query`
  and `ClaudeSDKClient.connect` to hard-fail. If a new test trips this
  guard, inject a fake at the seam; don't disable the guard.

**Standard injection seams**:
- `Session(client_factory=...)` / `Campaign(cfg, work_dir, client_factory=...)`
  with `tests/fakes/sdk_client.FakeClient` (scripted messages, simulated
  file writes, `PostToolUse` hooks for scripted tool calls).
- CLI: `monkeypatch.setattr(cli, "_sdk_client", factory)`; see
  `tests/v2/test_cli_v2.py`.

## Behavioral testing only

- ✓ Assert what's on disk: file existence, JSON Schema validation, contents
  of `ledger.json`, `runs.jsonl`, `state.json`.
- ✓ Assert hook return values (e.g. a Stop `decision: block` and its reason).
- ✗ Don't assert "function X was called with Y"; that's structural.
- ✗ Don't assert argv shape or internal control flow.

## Determinism

- Inject `now=`, `monkeypatch.time.sleep`, `os.utime` for time-dependent
  behavior. Tests must not depend on real wall-clock.
- Inject `sleep=` into `Session` and `now=` into `HookState` instead of
  waiting on real time.
