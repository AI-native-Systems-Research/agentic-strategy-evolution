# sdk_options Per-Phase Effort Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `sdk_options` stanza to `campaign.yaml` that sets the SDK `effort` level per phase (design, execute_analyze), defaulting to today's behaviour (SDK default "high") when omitted.

**Architecture:** Thread an `effort: str | None` value from `campaign["sdk_options"][phase]["effort"]` through `iteration.py`'s phase orchestration → `SDKDispatcher` → the SDK runner protocol → both `ClaudeAgentOptions(...)` construction sites. `None` is a no-op (SDK default), preserving existing behaviour. A schema enum on `effort` catches typos at campaign-load time.

**Tech Stack:** Python, `claude-agent-sdk` 0.2.87 (`ClaudeAgentOptions.effort`), jsonschema, pytest. No live LLM calls — tests inject a fake `sdk_runner` (`_ScriptedRunner`).

---

## File Structure

- `orchestrator/sdk_dispatch.py` — add `effort` to `SDKDispatcher.__init__`, store as `self._effort`, pass through `_call_claude` → runner; add `effort` param to the `SDKRunner` protocol and the default `_runner`; pass `effort=effort` into both `ClaudeAgentOptions(...)` calls.
- `orchestrator/iteration.py` — add `_effort_for(phase_key)` helper; pass `effort=_effort_for("design")` at construction; set `cli_dispatcher._effort = _effort_for("execute_analyze")` at the phase swap.
- `orchestrator/schemas/campaign.schema.yaml` — add `sdk_options` object with per-phase `effort` enum.
- `orchestrator/defaults.yaml` — add documented, effort-unset `sdk_options` stanza.
- `orchestrator/create_campaign.py` — add commented `sdk_options` example block.
- `tests/test_sdk_dispatch.py` — effort-threading tests (configured value + None default).
- `tests/test_sdk_effort.py` (new) — `_effort_for`-equivalent resolution + schema enum tests.

---

## Task 1: Thread `effort` through the SDK runner protocol and dispatcher

**Files:**
- Modify: `orchestrator/sdk_dispatch.py` (runner protocol `__call__` ~line 338; default `_runner` ~line 378; both `ClaudeAgentOptions(...)` ~lines 414 & 423; `SDKDispatcher.__init__` ~line 550; `_call_claude` runner call ~line 931)
- Test: `tests/test_sdk_dispatch.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sdk_dispatch.py` (the `_ScriptedRunner` class and `_make_campaign` helper already exist; `_ScriptedRunner` records every call's kwargs in `.calls`):

```python
class TestSDKDispatchEffort:
    """effort threads from SDKDispatcher into the runner call (#282)."""

    def test_effort_passed_to_runner(self, tmp_path):
        runner = _ScriptedRunner([SDKResult(text="ok")])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
            effort="medium",
        )
        out = tmp_path / "runs" / "iter-1" / "design_log.md"
        dispatcher.dispatch("planner", "design", output_path=out, iteration=1)

        assert runner.calls[0]["effort"] == "medium"

    def test_effort_defaults_to_none(self, tmp_path):
        # Behaviour-unchanged guarantee: no effort kwarg -> runner sees None,
        # which the SDK treats as its default ("high").
        runner = _ScriptedRunner([SDKResult(text="ok")])
        dispatcher = SDKDispatcher(
            work_dir=tmp_path,
            campaign=_make_campaign(tmp_path),
            sdk_runner=runner,
        )
        out = tmp_path / "runs" / "iter-1" / "design_log.md"
        dispatcher.dispatch("planner", "design", output_path=out, iteration=1)

        assert runner.calls[0]["effort"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sdk_dispatch.py::TestSDKDispatchEffort -v`
Expected: FAIL — `SDKDispatcher.__init__` has no `effort` kwarg (TypeError) and/or `runner.calls[0]` has no `"effort"` key (KeyError).

- [ ] **Step 3: Add `effort` to the runner protocol and default runner**

In `orchestrator/sdk_dispatch.py`, the `SDKRunner.__call__` protocol signature (~line 338) — add `effort` after `turn_silence_threshold`:

```python
    def __call__(
        self,
        *,
        prompt: str,
        model: str,
        cwd: Path | None,
        max_turns: int,
        system_prompt: str | None = None,
        settings_path: Path | None = None,
        event_log_path: Path | None = None,
        permission_mode: Literal["bypassPermissions"] | None = None,
        turn_silence_threshold: float | None = None,
        effort: str | None = None,
    ) -> SDKResult:
```

In the default `_runner` signature (~line 378) — add the same param:

```python
    def _runner(
        *,
        prompt: str,
        model: str,
        cwd: Path | None,
        max_turns: int,
        system_prompt: str | None = None,
        settings_path: Path | None = None,
        event_log_path: Path | None = None,
        permission_mode: Literal["bypassPermissions"] | None = "bypassPermissions",
        turn_silence_threshold: float | None = None,
        effort: str | None = None,
    ) -> SDKResult:
```

- [ ] **Step 4: Pass `effort` into both `ClaudeAgentOptions(...)` calls**

In `_run()` inside `_runner` (~lines 414 and 423), add `effort=effort` to each `ClaudeAgentOptions(...)`. The `if permission_mode:` branch:

```python
            if permission_mode:
                options = ClaudeAgentOptions(
                    model=model,
                    cwd=str(cwd) if cwd else None,
                    max_turns=max_turns,
                    system_prompt=system_prompt,
                    settings=str(settings_path) if settings_path else None,
                    permission_mode=permission_mode,  # type: ignore[arg-type]
                    effort=effort,
                )
            else:
                options = ClaudeAgentOptions(
                    model=model,
                    cwd=str(cwd) if cwd else None,
                    max_turns=max_turns,
                    system_prompt=system_prompt,
                    settings=str(settings_path) if settings_path else None,
                    effort=effort,
                )
```

- [ ] **Step 5: Add `effort` to `SDKDispatcher.__init__` and store it**

In `SDKDispatcher.__init__` (~line 550), add the kwarg after `sandbox` (keyword-only callers — keep it last to avoid positional breakage):

```python
    def __init__(
        self,
        work_dir: Path,
        campaign: dict,
        model: str = "claude-sonnet-4-6",
        prompts_dir: Path | None = None,
        timeout: int = 1800,
        max_turns: int = 25,
        max_retries: int | None = 10,
        sdk_runner: Callable | None = None,
        system_prompt: str | None = None,
        settings_path: Path | None = None,
        sandbox: str | None = None,
        effort: str | None = None,
    ) -> None:
```

Then store it. Add this line in the body after `self._settings_path = settings_path` (~line 577):

```python
        # #282: per-phase SDK effort. None means "don't pass effort" — the
        # SDK applies its own default ("high"), so behaviour is unchanged.
        self._effort = effort
```

- [ ] **Step 6: Pass `self._effort` into the runner call in `_call_claude`**

In `_call_claude` (~line 931), add `effort=self._effort` to the `self._sdk_runner(...)` call:

```python
                result = self._sdk_runner(
                    prompt=prompt,
                    model=self.model,
                    cwd=cwd,
                    max_turns=turns,
                    system_prompt=self._system_prompt,
                    settings_path=self._settings_path,
                    event_log_path=self._event_log_path,
                    permission_mode=self._permission_mode,
                    turn_silence_threshold=self._turn_silence_threshold,
                    effort=self._effort,
                )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_sdk_dispatch.py::TestSDKDispatchEffort -v`
Expected: PASS (both tests).

- [ ] **Step 8: Run the full sdk_dispatch suite for regressions**

Run: `python -m pytest tests/test_sdk_dispatch.py tests/test_sdk_sandbox.py -q`
Expected: all PASS (the existing `_ScriptedRunner(**kwargs)` calls absorb the new kwarg; the real-runner tests are unaffected since `effort=None` is a no-op).

- [ ] **Step 9: Commit**

```bash
git add orchestrator/sdk_dispatch.py tests/test_sdk_dispatch.py
git commit -m "feat(sdk): thread effort through SDKDispatcher and runner (#282)"
```

---

## Task 2: Resolve `effort` per phase in `iteration.py`

**Files:**
- Modify: `orchestrator/iteration.py` (helper block ~line 1143; `SDKDispatcher(...)` construction ~line 1167; phase swap ~line 1342)
- Test: `tests/test_sdk_effort.py` (new)

- [ ] **Step 1: Write the failing test for `_effort_for` resolution**

The `_effort_for` helper is a closure inside `run_iteration` and not directly importable. Test the resolution logic that the closure implements, as a standalone equivalent, so the test pins the contract the closure must satisfy. Create `tests/test_sdk_effort.py`:

```python
"""Tests for per-phase SDK effort resolution + schema (#282)."""
from __future__ import annotations

from pathlib import Path

import pytest


def _effort_for(campaign: dict, phase_key: str) -> str | None:
    """Standalone equivalent of the iteration.py closure — pins the contract."""
    phase = (campaign.get("sdk_options", {}) or {}).get(phase_key) or {}
    return phase.get("effort")


class TestEffortResolution:
    def test_returns_configured_effort(self):
        campaign = {"sdk_options": {"execute_analyze": {"effort": "medium"}}}
        assert _effort_for(campaign, "execute_analyze") == "medium"

    def test_none_when_stanza_absent(self):
        assert _effort_for({}, "design") is None

    def test_none_when_phase_absent(self):
        campaign = {"sdk_options": {"design": {"effort": "high"}}}
        assert _effort_for(campaign, "execute_analyze") is None

    def test_none_when_effort_key_absent(self):
        campaign = {"sdk_options": {"design": {}}}
        assert _effort_for(campaign, "design") is None

    def test_handles_null_sdk_options(self):
        # YAML "sdk_options:" with no body parses to None.
        assert _effort_for({"sdk_options": None}, "design") is None
```

- [ ] **Step 2: Run the test to verify it passes against the standalone helper**

Run: `python -m pytest tests/test_sdk_effort.py::TestEffortResolution -v`
Expected: PASS — this pins the exact resolution semantics the closure must implement (including the `or {}` guards for null/missing).

- [ ] **Step 3: Add the `_effort_for` closure in `iteration.py`**

In `orchestrator/iteration.py`, just after the `_max_turns_for` helper (~line 1154), add the campaign lookup and helper. First add the lookup next to `campaign_max_turns` (~line 1141):

```python
    campaign_max_turns = campaign.get("max_turns", {}) or {}
    # #282: per-phase SDK effort. Same key shape as models/max_turns.
    campaign_sdk_options = campaign.get("sdk_options", {}) or {}
```

Then add the helper after `_max_turns_for`:

```python
    def _effort_for(phase_key: str) -> str | None:
        # #282: campaign.sdk_options[phase].effort, or None (SDK default).
        phase = campaign_sdk_options.get(phase_key) or {}
        return phase.get("effort")
```

- [ ] **Step 4: Pass `effort` at `SDKDispatcher` construction**

In the `SDKDispatcher(...)` construction (~line 1167), add `effort=_effort_for("design")`:

```python
        cli_dispatcher = (
            SDKDispatcher(
                work_dir=work_dir, campaign=campaign,
                model=_model_for("design"), timeout=timeout,
                max_turns=_max_turns_for("design"),
                max_retries=max_cli_retries,
                effort=_effort_for("design"),
            ) if repo_path else None
        )
```

- [ ] **Step 5: Set `effort` at the execute_analyze phase swap**

At the phase swap (~line 1342), add the `_effort` line next to the existing `.model` / `.max_turns` swaps:

```python
        if cli_dispatcher:
            cli_dispatcher.model = _model_for("execute_analyze")
            cli_dispatcher.max_turns = _max_turns_for("execute_analyze")
            cli_dispatcher._effort = _effort_for("execute_analyze")
```

- [ ] **Step 6: Verify import sanity**

Run: `python -c "import orchestrator.iteration; print('ok')"`
Expected: prints `ok` (no syntax/NameError).

- [ ] **Step 7: Commit**

```bash
git add orchestrator/iteration.py tests/test_sdk_effort.py
git commit -m "feat(iteration): resolve per-phase effort from sdk_options (#282)"
```

---

## Task 3: Add `sdk_options` to the campaign schema (enum validation)

**Files:**
- Modify: `orchestrator/schemas/campaign.schema.yaml` (add a top-level property next to `max_turns`, ~after line 236)
- Test: `tests/test_sdk_effort.py`

- [ ] **Step 1: Write the failing schema tests**

Append to `tests/test_sdk_effort.py`:

```python
class TestSdkOptionsSchema:
    def _schema(self):
        import yaml
        schemas_dir = Path(__file__).resolve().parent.parent / "orchestrator" / "schemas"
        return yaml.safe_load((schemas_dir / "campaign.schema.yaml").read_text())

    def _base_campaign(self):
        return {
            "research_question": "q",
            "target_system": {"name": "x", "description": "d"},
            "prompts": {"methodology_layer": "p"},
        }

    def test_accepts_valid_effort(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"execute_analyze": {"effort": "medium"}}
        jsonschema.validate(campaign, self._schema())

    def test_accepts_absent_stanza(self):
        import jsonschema
        jsonschema.validate(self._base_campaign(), self._schema())

    def test_accepts_empty_phase(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"design": {}}
        jsonschema.validate(campaign, self._schema())

    def test_rejects_unknown_effort(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"execute_analyze": {"effort": "medum"}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, self._schema())

    def test_rejects_unknown_phase_key(self):
        import jsonschema
        campaign = self._base_campaign()
        campaign["sdk_options"] = {"reporting": {"effort": "high"}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(campaign, self._schema())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_sdk_effort.py::TestSdkOptionsSchema -v`
Expected: `test_rejects_unknown_effort` and `test_rejects_unknown_phase_key` FAIL (no `sdk_options` constraint yet, so unknown values validate). The accept-tests pass vacuously.

- [ ] **Step 3: Add the `sdk_options` block to the schema**

In `orchestrator/schemas/campaign.schema.yaml`, after the `max_turns` block (which ends at line 236, before `prompts:` at line 238), add:

```yaml
  sdk_options:
    type: object
    additionalProperties: false
    description: >
      Per-phase SDK effort level (#282). Controls how hard the model thinks
      each turn. design defaults to deep reasoning; execute_analyze (coding,
      running simulations, parsing JSON) is often adequate at lower effort.
      Omit the stanza, a phase, or the effort key to use the SDK default
      ("high") — behaviour is then unchanged.
    properties:
      design:
        type: object
        additionalProperties: false
        properties:
          effort:
            type: string
            enum: [low, medium, high, xhigh, max]
            description: "Effort for the DESIGN phase. Omit for SDK default (high)."
      execute_analyze:
        type: object
        additionalProperties: false
        properties:
          effort:
            type: string
            enum: [low, medium, high, xhigh, max]
            description: "Effort for EXECUTE_ANALYZE. Omit for SDK default (high)."
```

- [ ] **Step 4: Run the schema tests to verify they pass**

Run: `python -m pytest tests/test_sdk_effort.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/schemas/campaign.schema.yaml tests/test_sdk_effort.py
git commit -m "feat(schema): add sdk_options with effort enum (#282)"
```

---

## Task 4: Document the stanza in `defaults.yaml` and the campaign template

**Files:**
- Modify: `orchestrator/defaults.yaml` (append after the `max_turns` block, line 27)
- Modify: `orchestrator/create_campaign.py` (add a commented block near the `sdk_timeouts` block, ~line 217)

- [ ] **Step 1: Append the documented stanza to `defaults.yaml`**

Append to the end of `orchestrator/defaults.yaml` (after line 27):

```yaml

# Per-phase SDK effort (#282). Controls how hard the model thinks each turn.
# Valid: low | medium | high (SDK default) | xhigh | max
# Omit a phase or the effort key to use the SDK default (high) — behaviour
# is then unchanged. design benefits from high; execute_analyze (coding,
# simulations, JSON parsing) is often adequate at medium and much cheaper.
sdk_options:
  design: {}           # effort unset -> SDK default (high)
  execute_analyze: {}  # effort unset -> SDK default (high)
```

- [ ] **Step 2: Verify defaults.yaml still parses**

Run: `python -c "import yaml; yaml.safe_load(open('orchestrator/defaults.yaml')); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Add the commented example to the campaign template**

In `orchestrator/create_campaign.py`, after the `sdk_timeouts` commented block (ends ~line 217, before the `plot_specs` block at line 219), add:

```python
# Per-phase SDK effort (#282). design benefits from deep reasoning (high);
# execute_analyze (coding, simulations, JSON parsing) is often adequate at
# medium and much cheaper. Omit to use the SDK default (high) everywhere.
# Valid: low | medium | high | xhigh | max
# sdk_options:
#   design:
#     effort: high
#   execute_analyze:
#     effort: medium
```

(Match the exact string-literal/quoting style of the surrounding commented blocks in that file — they are lines inside a multi-line template string; replicate the leading `# ` comment style used by the neighbouring `sdk_timeouts` block.)

- [ ] **Step 4: Verify create_campaign imports and the template still renders**

Run: `python -c "import orchestrator.create_campaign; print('ok')"`
Expected: prints `ok`. If `create_campaign.py` has a render/generate function exercised by tests, run `python -m pytest tests/test_templates.py -q` and expect PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/defaults.yaml orchestrator/create_campaign.py
git commit -m "docs(campaign): document sdk_options in defaults + template (#282)"
```

---

## Task 5: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: all PASS (baseline before this work was 1309 passed; expect 1309 + the new effort/schema tests). No live LLM calls (conftest guards enforce this).

- [ ] **Step 2: Confirm the behaviour-unchanged guarantee end-to-end**

Confirm `test_effort_defaults_to_none` (Task 1) passed in the full run — that is the guarantee that campaigns omitting `sdk_options` send `effort=None`, identical to today.

- [ ] **Step 3: Final commit (if any stragglers) / no-op**

```bash
git status --short
# Expect clean tree; nothing to commit if Tasks 1-4 committed cleanly.
```

---

## Self-Review notes

- **Spec coverage:** all 5 files from the spec's "Architecture / threading path" are covered (Task 1: sdk_dispatch.py; Task 2: iteration.py; Task 3: schema; Task 4: defaults.yaml + create_campaign.py). Testing section of the spec maps to Task 1 (threading + None default), Task 2 (resolution), Task 3 (schema accept/reject).
- **Type consistency:** the kwarg is named `effort` everywhere; stored as `self._effort`; helper is `_effort_for`. The runner records kwargs in `.calls` (verified in `_ScriptedRunner`), so `runner.calls[0]["effort"]` is valid.
- **Out of scope honoured:** no `report`-phase effort, no mid-turn changes, no InlineDispatcher effort.
- **Behaviour-unchanged:** `effort=None` flows end-to-end when the stanza is omitted; `_ScriptedRunner(**kwargs)` absorbs the new kwarg so existing sdk_dispatch tests don't break.
