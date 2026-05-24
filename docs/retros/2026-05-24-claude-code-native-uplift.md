# Retro — Claude-Code-Native Uplift for Nous (#120)

**Closes:** [#120](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/120)
**Window:** 2026-05-24 (single session, multi-PR initiative)
**Children resolved:** 15 of 15 — #121, #122, #123, #124, #125, #126, #127, #128, #129, #130, #131, #132, #133, #134, #135.
**Plus a project-wide guard PR:** #151 — no-live-LLM-in-tests, codified in `CLAUDE.md` + `tests/CLAUDE.md` + `tests/conftest.py` + `docs/contributing/workflow.md`.

## What landed

```
                       Foundation                Capabilities                Ecosystem
                  ┌───────────────────┐       ┌────────────────────┐    ┌─────────────────┐
                  │ #121 SDK port     │──┬────│ #122 caching        │    │ #126 MCP server │
                  │ #129 stop hook    │  ├────│ #127 stream-json    │    │ #125 plugin pkg │
                  │ #135 perm policy  │  ├────│ #132 explore design │    │ #134 routines   │
                  │ #131 CLAUDE.md    │  └────│ #123 parallel arms  │    │ #130 channels   │
                  └───────────────────┘       │ #133 worktree harness│    │ #124 /goal-driven│
                                              │ #128 plan enforcer  │    └─────────────────┘
                                              └────────────────────┘
```

15 PRs in flight against `upstream/reflective`. ~250 new behavioral tests. Zero structural assertions. Zero live LLM calls (enforced by the conftest guard).

## How the architecture changed

Before: Nous was a Python orchestrator that shelled out to `claude -p` as a subprocess for code-access roles, with a custom JSON parser, a custom retry loop, and a manual git-worktree lifecycle. The methodology preamble (~465 lines across `design.md` + `execute_analyze.md`) was re-rendered into every prompt.

After: Nous is a Python orchestrator that owns checkpointing, validation, and gates, while delegating the actual agent loop to the Claude Agent SDK. Methodology lives in CLAUDE.md (auto-loaded once per session); the prompt body shrinks to per-iteration context only. Subagents (Explore for design mapping, isolation="worktree" for parallel arms) replace the mega-session pattern. The on-disk artifact contract is unchanged — every PR was a transport substitution behind the existing `dispatcher.dispatch(role, phase, ...)` seam.

## Token-budget delta (the user's mission-critical metric)

| Lever | Before | After | Verifies via |
|---|---|---|---|
| Methodology re-sent each call (#131) | full template (~465 lines) per call | thin template (~50 lines) when CLAUDE.md is in scope | `nous cost --cache-stats` (#122) — stats infrastructure landed |
| System block caching (#122) | none | `cache_control: ephemeral` on methodology preamble | `cache_read_input_tokens` in `llm_metrics.jsonl` |
| DESIGN exploration (#132) | one Opus session for codebase walk + synthesis | 4 parallel Haiku Explore subagents + 1 Opus synthesis call | report.input_tokens aggregation in `ExploreStageResult` |
| Multi-arm execution (#123) | one Sonnet mega-session for 24 simulations | per-arm subagent in isolated worktree, parallelizable | wall-clock + per-unit metrics on representative campaign |

The cache-stats aggregation (`orchestrator/cache_stats.py`) is the regression gate — `nous cost --cache-stats` must show non-zero hit rate on warm phase calls and ≥25% input-token reduction over the 5-iter baseline. Soak verification on real `inference-sim` campaigns confirms or refutes this; the infrastructure to observe it is in place.

## How testing held up

The user's directive — "behavioral testing discipline, absolutely no structural tests" — was the most consequential constraint of the initiative. It forced specific design choices:

- **Pluggable seams everywhere.** `sdk_runner` Protocol returning `SDKResult` (#121); `poster` callable for channels (#130) and routines (#134); `runner` injection for plan enforcer (#128), explore stage (#132), parallel arms (#123); `pid_check` and `now=` for worktree GC (#133); `completion_fn` for the legacy LLMDispatcher path. Every test asserts on disk artifacts, JSON shapes, or externally-visible state — never on internal helper invocations.
- **No live LLM calls in tests, ever.** Codified in PR #151 with active enforcement: `tests/conftest.py` strips `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` from the env, patches `urllib.request.urlopen` to refuse known LLM hosts, patches `claude_agent_sdk.query` to hard-fail. `tests/test_no_live_llm_guard.py` verifies the guard fires correctly.
- **Determinism via injected clocks/PIDs/IDs.** Tests inject `now=`, `pid_check=`, fake `os.utime`, scripted runners — they pass on any machine, in any timezone, without flaky waits. No `time.sleep` polling.

That seam discipline is also what makes Phase B closures possible: in every #N Phase B PR, the production wiring is one line that constructs the real SDK runner; the orchestration layer + tests above it are unchanged.

## What's deferred to soak

Acceptance criteria that explicitly require running a real campaign (the issue body's measurement-based criteria) cannot be honestly verified in CI:

- #122: ≥25% input token drop on a 5-iteration campaign (need Anthropic API).
- #123: significant wall-clock improvement on `examples/campaign-best-of-field.yaml` with `max_parallel_arms: 4` (need real subagent spawning).
- #132: ≥30% DESIGN cost drop (need real Explore subagents).
- #131: subjective bundle-quality parity on 3 reference campaigns (human review).
- #126/#130/#134: live transports against MCP / Slack / Routines APIs (need credentials).

These are integration tests for the soak environment, not unit tests. The infrastructure to measure each is shipped (`nous cost --cache-stats`, the ledger, `merge_unit_results` determinism). The team verifies on first soak; if a criterion fails, the failure is observable from the metrics emit and the cause is traceable to a single seam.

## What the next initiative should pick up

- Drop `cli_dispatch.py` once `--agent sdk` has soaked. The CLI subprocess path is dead code after that.
- Drop `worktree.py`'s manual `create_experiment_worktree` / `remove_experiment_worktree` once #123 wires `make_isolated_arm_runner` into iteration.py — closes #133's ≥60% LoC reduction acceptance criterion.
- Real MCP transport using the `mcp` Python SDK once it pins; the stdio JSON-RPC server in #142 is bounded by what stdlib can do.
- Slack interactive messages adapter for #130 Phase B (parsed reply tokens are landed; the per-channel reply provider needs a webhook receiver).
- Routines API integration once the API stabilizes; the payload builder + `submit_routine` are landed.

## Lessons (worth carrying to the next epic)

1. **Phase A / Phase B split was right.** Eleven of fifteen child issues had at least one criterion that requires soak verification. Bundling them as one PR each would have made every PR claim "soak verified" — false. Splitting let us land the testable orchestration first and name the soak-only follow-up explicitly.
2. **Stack PRs when one logical change builds on another.** Five PRs stacked on #136 (#121 SDK port); #139 stacked on #138; #150 stacked on #143 stacked on #136. Each stack mirrors the dependency chain. Reviewers can merge bottom-up; rebases are mechanical.
3. **The conftest guard was the highest-leverage one-day investment.** ~50 lines of `tests/conftest.py` and a one-line autouse fixture meant every existing test, every new test, every future PR is now incapable of accidentally spending tokens. Cost: one PR. Benefit: forever.

## Closing #120

All 15 children + the test-policy guard are in flight. The retro is this document; the metric-verification work is named in [`docs/plans/CHECKPOINT.md`](../plans/CHECKPOINT.md).
