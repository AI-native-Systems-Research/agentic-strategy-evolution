# Design: `sdk_options` stanza for per-phase effort control (#282)

## Problem

Every SDK phase (design, execute_analyze) runs at `effort="high"` because
`ClaudeAgentOptions` defaults to that and nous never sets it. There is no
way to change it from `campaign.yaml`. High effort means the model thinks
deeply every turn — right for design, often wasteful for execute_analyze
(writing Go, running simulations, parsing JSON). Observed cost: execute_analyze
runs 5–6× more expensive than its raw token count suggests.

## Goal

A new optional `sdk_options` stanza in `campaign.yaml`, same per-phase key
shape as `models` and `max_turns`:

```yaml
sdk_options:
  design:
    effort: high        # unchanged from today's default
  execute_analyze:
    effort: medium      # cheaper; adequate for coding + analysis
```

Omitting the stanza (or a phase key, or the `effort` key) keeps today's
behaviour exactly: `effort=None` is passed, which the SDK treats as its
default (`high`).

## Verified facts (against the actual tree, not the issue's approximations)

- `claude-agent-sdk` is pinned at `0.2.87`; `ClaudeAgentOptions` has an
  `effort` field (confirmed via `dataclasses.fields`).
- The SDK runner is a **separate callable** with a fixed protocol signature
  (`SDKRunner.__call__`), not an inline `ClaudeAgentOptions` build inside
  the dispatcher. So `effort` must thread through the runner protocol —
  the issue's snippet (put `effort=` in `ClaudeAgentOptions`) is necessary
  but not sufficient.
- There are **two** `ClaudeAgentOptions(...)` construction sites in the
  runner (permission_mode set vs not); both need `effort=effort`.
- `iteration.py` constructs `SDKDispatcher` once for `design`, then mutates
  `.model` / `.max_turns` in place for the `execute_analyze` phase. `effort`
  follows the same in-place-swap pattern via `cli_dispatcher._effort`.

## Architecture / threading path

### 1. `orchestrator/sdk_dispatch.py` (4 touch points)

- `SDKDispatcher.__init__`: add `effort: str | None = None`; store
  `self._effort = effort`.
- `_call_claude`: pass `effort=self._effort` in the `self._sdk_runner(...)`
  call.
- `SDKRunner.__call__` protocol **and** `_runner` (the default factory):
  add `effort: str | None = None` parameter.
- Both `ClaudeAgentOptions(...)` calls: pass `effort=effort`. `None` is a
  no-op (SDK default), so the behaviour-unchanged guarantee holds.

### 2. `orchestrator/iteration.py` (3 touch points)

- Add helper `_effort_for(phase_key)` mirroring `_model_for` /
  `_max_turns_for`:

  ```python
  campaign_sdk_options = campaign.get("sdk_options", {}) or {}

  def _effort_for(phase_key: str) -> str | None:
      phase = campaign_sdk_options.get(phase_key) or {}
      return phase.get("effort")
  ```

- `SDKDispatcher(...)` construction: add `effort=_effort_for("design")`.
- Phase swap for execute_analyze: add
  `cli_dispatcher._effort = _effort_for("execute_analyze")` next to the
  existing `.model` / `.max_turns` swaps.

### 3. `orchestrator/defaults.yaml`

Add a documented, effort-unset stanza so the feature is discoverable while
behaviour stays unchanged:

```yaml
# Per-phase SDK effort. Controls how hard the model thinks each turn.
# Valid: low | medium | high (SDK default) | xhigh | max
# Omit a phase or the effort key to use the SDK default (high).
sdk_options:
  design: {}           # effort unset → SDK default (high)
  execute_analyze: {}  # effort unset → SDK default (high)
```

### 4. `orchestrator/schemas/campaign.schema.yaml`

Add `sdk_options` (mirroring the `max_turns` block) with per-phase `effort`
constrained by enum — catches typos (`medum`) at campaign-load time, before
any tokens are spent:

```yaml
sdk_options:
  type: object
  additionalProperties: false
  description: >
    Per-phase SDK effort level (#282). ...
  properties:
    design:
      type: object
      additionalProperties: false
      properties:
        effort: { type: string, enum: [low, medium, high, xhigh, max] }
    execute_analyze:
      type: object
      additionalProperties: false
      properties:
        effort: { type: string, enum: [low, medium, high, xhigh, max] }
```

### 5. `orchestrator/create_campaign.py`

Add a commented `sdk_options` example block next to the `sdk_timeouts`
block in the generated campaign template.

## Testing (no live LLM calls — inject a fake `sdk_runner`)

Following `tests/CLAUDE.md` and the `_ScriptedRunner` seam:

- `effort` threads: `SDKDispatcher(effort="medium")` → captured runner kwarg
  is `"medium"`.
- Default: `SDKDispatcher()` with no effort → captured kwarg is `None`
  (behaviour-unchanged guarantee).
- `_effort_for` resolution: returns the configured value, and `None` when
  the stanza / phase / `effort` key is absent.
- Schema: rejects an invalid effort enum value; accepts a valid value and
  an entirely absent stanza.

## Out of scope (YAGNI)

- `report`-phase effort (it is an LLM-API phase, not SDK-dispatched).
- Changing effort mid-turn.
- Effort for the `InlineDispatcher`.

## Behaviour-unchanged guarantee

Campaigns that omit `sdk_options` pass `effort=None` end-to-end, which is
identical to today's code path (the kwarg simply wasn't passed before). The
only new failure mode is a schema rejection for a malformed `sdk_options`
block, which surfaces at campaign load — strictly earlier and clearer than
the status quo.
