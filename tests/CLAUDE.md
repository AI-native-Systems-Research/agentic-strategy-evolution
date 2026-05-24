# Tests — local conventions

This file is auto-loaded whenever Claude Code is operating inside `tests/`.
It restates the non-negotiable rules from the root `CLAUDE.md` so they're
in scope even when the repo root isn't.

## 🚫 NEVER make live LLM calls in tests

This applies to **unit, integration, and end-to-end tests alike**. There
is no test category in this repo that's allowed to spend tokens against
a real provider.

**Active enforcement** (see `tests/conftest.py`):
- `block_live_llm_calls` autouse fixture strips `OPENAI_API_KEY` /
  `ANTHROPIC_API_KEY` and patches `urllib.request.urlopen` + `claude_agent_sdk.query`
  to hard-fail on real network calls. If a new test trips this guard,
  inject a fake at the dispatcher seam — don't disable the guard.

**Standard injection seams**:
- `LLMDispatcher(..., completion_fn=fake)` — see `_make_fake_completion`.
- `CLIDispatcher` — `monkeypatch.setattr("orchestrator.cli_dispatch.subprocess.run", fake)`.
- `SDKDispatcher(..., sdk_runner=fake)` — see `_ScriptedRunner`.
- `StubDispatcher` for end-to-end orchestrator flows that don't care
  about any specific LLM behavior.

## Behavioral testing only

- ✓ Assert what's on disk: file existence, JSON Schema validation, contents.
- ✓ Assert metrics-row contents in `llm_metrics.jsonl`.
- ✓ Assert exit codes and stderr substrings for hooks.
- ✗ Don't assert "function X was called with Y" — that's structural.
- ✗ Don't assert argv shape or internal control flow.

The dispatcher seams (Protocol + dataclass result) are the contract;
the implementation is free to evolve under them.

## Determinism

- Inject `now=`, `monkeypatch.time.sleep`, `os.utime` for time-dependent
  behavior. Tests must not depend on real wall-clock.
- Inject `pid_check=` for `gc_orphan_worktrees` — never assert on real PIDs.
- Use `_RecordingPoster` / `_ScriptedRunner` patterns to capture arguments
  for assertion without coupling to internal call shapes.
