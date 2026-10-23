# Nous v2 lean audit (R12b)

Every piece of the v2 runtime and the remaining CLI, mapped to the SPEC section it serves. Anything with no SPEC section was removed or merged (see Removals).

## v2 runtime modules (`orchestrator/v2/`)

| Module | Main functions / classes | SPEC section |
|---|---|---|
| `session.py` | `Session` (`build_agent_options`, `connect`, `turn`, `_retry`, `disconnect`), `MODEL_MAX_OUTPUT`, `SDK_VERSION`/`CLI_VERSION` | 3.1 (options, buffer, env, versions, session_id persisted) |
| `session.py` | `is_transient`, `APIServerError`, `RETRY_DELAYS_S` | 3.5 transient errors / B9 (merged from `errors.py`) |
| `loop.py` | `Campaign.run` / `_run_phases_from` / `_report` | 3.2 phases |
| `loop.py` | `_repair` | 3.5 repair |
| `loop.py` | `_lock_bundle`, `_check_bundle_hash` | 3.2 steps 3 and 6 (bundle lock, prereg_violation) |
| `loop.py` | `_merge_principles`, ledger row, `_save_ledger` | 3.2 step 6, 3.4 ledger |
| `loop.py` | `_commit_phase` | 3.1 one worktree, commit per phase (D5) |
| `loop.py` | `Campaign.resume`, `_reload_state` | 3.7 resume and fallback |
| `loop.py` | `_record_final_check` | 3.8 |
| `config.py` | `CampaignConfig`, `parse_campaign_config`, `validator_limits` | 4 (campaign.yaml), 3.4/3.14 limits |
| `hooks.py` | `HookState`, `build_hooks`, PostToolUse / PostToolUseFailure / Stop / PreCompact callbacks, `PHASE_ARTIFACTS` | 3.3 |
| `hooks.py` | `DEFAULT_EXPERIMENT_COMMANDS`, `is_experiment_command` | 3.9, B11 |
| `validators.py` | `validate_artifact`, `validate_phase_artifacts`, `iter_context`, `ValidatorContext`, `_move_extras` | 3.4 (B5, B6) |
| `validators.py` | `check_evidence_item`, `_resolve_json_pointer`, `_values_match` | 3.4 evidence rules |
| `validators.py` | bundle / plan / findings / principle_updates / answer semantic checks, `_check_noise_schema` | 3.4 (families, control, claims coverage, paired seeds, locks, noise honesty, finding_ref, secrets) |
| `validators.py` | `_check_task_limits` (`max_runs` only) | 3.3 B11 |
| `validators.py` | `bundle_hash`, `read_json` | 3.2 step 3; shared helper |
| `stop_rule.py` | `check_stop`, `claims_changed`, `best_changed`, `principles_changed`, `_claims_needed_met` | 3.6 |
| `robustness.py` | `FailureBreaker`, `failure_fingerprint`, `write_halt` | 3.5 failure breaker |
| `robustness.py` | `check_wait_condition`, `poll_and_resume` | 3.2 step 4 long runs |
| `resume.py` | `update_state` (atomic), `load_campaign_state`, `resume_phase`, `build_fallback_message` | 3.7 |
| `final_check.py` | `check_answer`, `_check_repro`, `_normalize`, `_claims_matched_fraction` | 3.8 |
| `cost.py` | `CostMeter` (`record`, `total`, `iter_delta`), `load_prices` | 3.10 cost, B10 |
| `effort.py` | `EffortManager`, `EFFORT_LADDER` | 3.10 effort ladder, B12. **Gap: not wired into the loop** (see Gaps) |
| `preflight.py` | `run_preflight`, fixtures | 3.5 preflight, B4 |
| `prompts.py` | `build_system_prompt`, `load_method_prompt`, `load_checklist` | 3.12 |
| `secrets.py` | `mask_secrets`, `check_secrets` | 3.14 |
| `schemas/*.schema.json` | answer, baseline, bundle, findings, plan, principle_updates, problem; `ledger_entry` (served by `nous schema`, tested; not loaded at runtime) | 3.4 |

## campaign.yaml keys (`config._KNOWN_KEYS`)

| Key | Runtime effect | SPEC section |
|---|---|---|
| `research_question` | required; parsed | 4 |
| `target_system` (`repo_path`) | session cwd, phase commits, wait_for cwd | 4, 3.1 |
| `run_id` | work dir name (CLI) | 4 (work dir) |
| `max_iterations` | loop bound, stop rule | 4, 3.6 |
| `models` (`session`, else `design`) | session model | 4, 3.1 |
| `locked_parameters`, `locked_workload` | plan validator | 4, 3.4 |
| `effort` | passed to SDK | 4, 3.1, 3.10 |
| `human_gates` | parsed, **not acted on** | 4 (listed; kept, see Gaps) |
| `secrets` | masking + REPORT check | 4, 3.14 |
| `min_improvement` | `best_changed` | 4, 3.6 |
| `stall_iterations` | stop rule | 4, 3.6 |
| `task_type` | method checklist; BASELINE hint | 4, 3.12 |
| `session_scope` | `iteration` forces fresh-session resume | 4, 3.1 |
| `experiment_commands` | hook experiment flag | 4, 3.9 |
| `task_limits` | `max_runs` checked on findings | 4, 3.3 B11 |
| `objective` (`direction`) | `best_changed` direction | 4, 3.6 |
| `rerun_repro` | parsed, **not acted on** | 4, 3.8 (listed; kept, see Gaps) |

Legacy keys (`critic`, `prompts`, `arm_sweep`, ...) are accepted with a warning and ignored (SPEC 4).

## Non-v2 code

| Item | Decision | Reason / SPEC section |
|---|---|---|
| `orchestrator/cli.py` | keep, trimmed to `run`, `resume`, `status`, `cost`, `validate`, `schema`, `stop` | 4 |
| `orchestrator/work_dir_resolver.py` | keep | 3.13 work dir location (used by `run`/`resume`/`status`/`cost`/`stop`) |
| `orchestrator/defaults.yaml` | keep (`prices` read by the cost meter; other keys are v1 leftovers, harmless) | 3.10 |
| `orchestrator/meta_findings.py`, `validate.py` | delete | read v1 `retry_log.jsonl`, `llm_metrics.jsonl`, dict-shaped ledger; v2 never writes them; command `reports` removed |
| `orchestrator/deployment_recommendation.py`, `composite_score.py` | delete | only used by meta_findings; read v1 `best_found.json`, `pre_work.json` |
| `orchestrator/create_campaign.py` | delete | wrote a v1 scaffold (`prompts.methodology_layer`); command `create-campaign` removed |
| `orchestrator/lineage.py` | delete | reads v1 `derived_from` / cumulative patches; command `lineage` removed (SPEC 4: not working on v2 artifacts) |
| `orchestrator/campaign_index.py`, `engine.py` | delete | read v1 shapes (`ledger.iterations`, `principles.principles`, `findings.arms`, `last_entered_phase`); v2 ledger/principles are lists |
| `orchestrator/util.py` | delete | `atomic_write` only used by deleted modules |
| `bin/nous-mcp` | delete | wrapped `campaign_index` (v1 only) |
| `nous replay`, `package`, `lineage`, `report`, `reports`, `create-campaign`, `clean` | delete | SPEC 4 allows deprecate-or-keep; they read only v1 artifacts and already exited 1 or ran v1 code, so removed outright |
| `plugin/nous/skills/nous-run.md`, `nous-status.md`, `nous-resume.md` | keep, rewritten for v2 | wrap kept CLI commands (4) |
| `plugin/nous/skills/nous-list.md`, `nous-bisect.md`, `nous-find-principle.md` | delete | used `campaign_index` |
| `plugin/nous/skills/nous-create-campaign.md` | delete | used `nous create-campaign` (removed) |
| `orchestrator/schemas/*` (v1 campaign/state/ledger/principles/findings/best_found/meta_findings) | delete | nothing loads them after this pass; `nous schema campaign` dropped |
| `orchestrator/templates/*` | delete | only v1 `Engine` and template tests used them |
| `scripts/visualize_campaign.py`, `visualize_registry.py`, `retrieve_wiki_context.py`, `validate_concepts.py` | keep (deprecated for v2 input) | wiki/registry tooling for `.claude/commands/*`; SPEC 6 puts the cross-campaign registry out of scope. They read v1 shapes; not touched |

## Removals

Modules: `orchestrator/v2/errors.py` (merged into `session.py`; `TransientError`, `ProcessError`, `TimeoutError_` dropped, the SDK's own `ProcessError` carries `exit_code`), `meta_findings.py`, `deployment_recommendation.py`, `composite_score.py`, `create_campaign.py`, `lineage.py`, `campaign_index.py`, `engine.py`, `validate.py`, `util.py`, `bin/nous-mcp`.

Functions / branches: `robustness.poll_wait_for` (unused; loop uses `poll_and_resume`), `CostMeter.set_phase` / `phase_summary` / per-phase totals (unused at runtime; ledger is per iteration), `task_limits.max_wall_seconds` branch (summed `wall_seconds`, which hooks never write; could never trigger), `final_check` scan of `runs/iter-*/runs.jsonl` (hooks only write `<work_dir>/runs.jsonl`), duplicate claim-evidence loop in `check_answer` (the answer validator already checks it), Stop hook's own file loop (now reuses `validate_phase_artifacts`), `_artifact_path`, `ledger_entry` in the validator map (no runtime caller), `cli._V2_PHASE_ARTIFACTS` (reuses `hooks.PHASE_ARTIFACTS`).

CLI commands: `report`, `replay`, `reports`, `create-campaign`, `lineage`, `clean`, `package`; `nous schema campaign` (printed the v1 schema) and the schema `See also` block.

Schemas / templates: all of `orchestrator/schemas/` and `orchestrator/templates/`.

Plugin skills: `nous-list`, `nous-bisect`, `nous-find-principle`, `nous-create-campaign`.

Tests (deleted with their modules or v1 schemas): `test_meta_findings`, `test_deployment_recommendation`, `test_composite_score`, `test_create_campaign`, `test_campaign_index`, `test_mcp_server`, `test_engine`, `test_engine_search_continuation`, `test_atomic_state_writes`, `test_friction_245`, `test_schemas`, `test_templates`, `test_empirical_content`, `test_campaign_ground_truth`, `test_max_turns_resolution`, `test_sdk_effort`, `test_sdk_sandbox`, `test_sdk_silence_detector`, `test_theory_references`; `TestCmdReports` in `test_cli`; the v1 schema render test in `test_nous_stop`; `poll_wait_for` and `phase_summary` unit tests. `test_nous_schema_command` rewritten for v2 artifacts.

Dependencies: `openai`, `scipy` (runtime) and `optuna`, `pymc` (dev) dropped from `pyproject.toml`; nothing imports them. `uv.lock` not regenerated (needs network); run `uv lock` later.

## Gaps (recorded, not fixed)

- `EffortManager` (3.10 / B12) is not wired into the loop: no `max_tokens` detection, interrupt, reconnect at a lower effort, or `cut_offs` in `state.json`. Wiring needs Session reconnect with a new effort plus a per-phase reset; more than a minimal change, so left as a gap.
- `human_gates` (3.2 step 3, 4) parsed but no gate exists.
- `rerun_repro` (3.8) parsed but the repro is never re-run.
- Ledger has no per-phase cost or `cost_sdk_usd` (3.4); the meter records per-iteration totals only.
- `scripts/visualize_*` and the wiki commands read v1 ledger/principles shapes.
