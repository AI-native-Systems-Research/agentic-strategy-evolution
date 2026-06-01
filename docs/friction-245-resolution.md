# Friction report #245 resolution map

This document maps each F-entry from tracking issue [#245](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/245)
(21 sub-issues #246..#266) to the concrete code, schema, and docs
changes that resolved it. Newcomers — and AI assistants picking up
this PR cold — should be able to navigate from any F-entry to its
implementation in one hop.

| F | Issue | Severity | Resolution | Tests |
|---|---|---|---|---|
| F1 | [#246](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/246) | HIGH | `campaign.locked_parameters` schema field + `_validate_locked_parameters` in `validate.py` (hard-fails regardless of `--auto-approve`) | `tests/test_friction_245.py::test_f1_*` |
| F2 | [#247](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/247) | MED-HIGH | "Source-of-truth hierarchy" section added to `prompts/methodology/design.md` with worked example | (prompt-text — no behavioral test) |
| F3 | [#248](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/248) | MED | `rehearsal_subset.depth_overrides` + `invalidates_checks` schema; `_validate_depth_overrides` enforces non-empty `invalidates_checks` whenever any depth payload is set; methodology prompt explains the breadth-vs-depth distinction | `tests/test_friction_245.py::test_f3_*` |
| F4 | [#249](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/249) | HIGH | `compute_campaign_spec_diff` in `validate.py` + `_augment_summary_with_spec_diff` in `iteration.py` writes `campaign_spec_diff` block into every `gate_summary_design.json`, regardless of `--auto-approve`. `nous status` surfaces it | `tests/test_friction_245.py::test_f4_*` |
| F5 | [#250](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/250) | LOW-MED | `nous stop --immediate` writes a `STOP_IMMEDIATE` sentinel; the SDK turn loop checks for it at each event boundary in `sdk_dispatch.py` | (CLI smoke; runtime side-effect) |
| F6 | [#251](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/251) | LOW | `_warn_tracked_worktree_extras` runs at `nous run` campaign load time; checks each entry against `git ls-files --error-unmatch` | (CLI runtime side-effect) |
| F7 | [#252](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/252) | HIGH | "Apparatus discipline" section added to `prompts/methodology/execute_analyze.md` with the BLIS `runningBatch` vs `RequestMap` worked example and per-invariant bug-class checklist | (prompt-text — no behavioral test) |
| F8 | [#253](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/253) | LOW | `_cmd_resume` in `cli.py` detects directory-typed argument and emits a structured diagnostic before falling through to the legacy "Work directory not found" path | (CLI smoke) |
| F9 | [#254](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/254) | LOW | `nous clean --orphaned` subcommand in `cli.py` (`_cmd_clean`); supports `--target-repo`, `--campaign`, `--dry-run` | (CLI smoke; mirrors `gc_orphan_worktrees`) |
| F10 | [#255](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/255) | MED | New section "`--auto-approve` safety preconditions" in `README.md`; `--auto-approve` help text references it | (docs only) |
| F11 | [#256](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/256) | MED | `_emit_high_build_warning` in `iteration.py` runs after DESIGN; emits a sized recommendation to raise `max_turns.execute_analyze` | `tests/test_friction_245.py::test_f11_*` |
| F12 | [#257](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/257) | LOW | `aiter_with_silence_watchdog`'s `aclose` path now wraps in `asyncio.wait_for(timeout=5)` and explicitly catches `(TimeoutError, CancelledError, RuntimeError, GeneratorExit)` | (covered by existing watchdog tests; race is non-deterministic) |
| F13 | [#258](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/258) | HIGH | `nous create-campaign` scaffold gains a commented `locked_parameters` block + `locked_workload`, `derived_from`, `sdk_timeouts.turn_silence_threshold_seconds` (per-phase), `plot_specs`. New `docs/campaign-authoring-guide.md` includes the "what to lock" inventory | (existing scaffold tests cover schema-validity) |
| F14 | [#259](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/259) | N/A | `docs/campaign-authoring-guide.md` includes "Rehearsal as scientific instrument" section + "Pre-lock unit check" | (docs only) |
| F15 | [#260](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/260) | HIGH | `bundle.experiment_spec.physical_realism_check` schema + `_validate_physical_realism` soft-warn when `k_realism_ratio < 0.5` and justification is empty/perfunctory | `tests/test_friction_245.py::test_f15_*` |
| F16 | [#261](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/261) | HIGH | `bundle.experiment_spec.unlocked_parameters_audit` schema; methodology prompt requires the audit when leaving parameters at default | (schema validation; prompt-text) |
| F17 | [#262](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/262) | HIGH | New module `orchestrator/reproducibility.py`; `setup_work_dir` calls `capture_reproducibility_metadata` at INIT; iter-N start calls `snapshot_iter_files`. Block recorded in `state.json` (schema extended). Surfaced via `nous status` | `tests/test_friction_245.py::test_f17_*` |
| F18 | [#263](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/263) | MED | `campaign.plot_specs` schema; new module `orchestrator/plot_specs.py` invokes scripts after findings.json. `nous package` subcommand tarballs work_dir + reproduce.sh + Dockerfile + README | `tests/test_friction_245.py::test_f18_*` |
| F19 | [#264](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/264) | HIGH | `sdk_timeouts.turn_silence_threshold_seconds` accepts per-phase map; `_resolve_turn_silence_threshold(phase)` selects the right value at dispatch time. Defaults: design=600, execute_analyze=120, report=240. Scalar form preserved | `tests/test_friction_245.py::test_f19_*` |
| F20 | [#265](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/265) | MED | `campaign.locked_workload` + `bundle.workload_changes_from_canonical` schemas; `_validate_locked_workload` walks the workload yaml and diffs against the canonical (declared deviations are allowed) | `tests/test_friction_245.py::test_f20_*` |
| F21 | [#266](https://github.com/AI-native-Systems-Research/agentic-strategy-evolution/issues/266) | HIGH | New module `orchestrator/lineage.py`. Each iteration emits `patches/cumulative.patch` (`emit_cumulative_patch`). `campaign.derived_from` resolves a prior campaign's cumulative patch and applies it as a worktree preflight (`apply_derived_from_patch`). `nous lineage` subcommand surfaces the chain | `tests/test_friction_245.py::test_f21_*` |

## Why this PR is correct (for newcomers)

The 21 entries cluster around five themes (per #245). Each cluster
has a single architectural primitive that closes the structural
gap, plus secondary entries that adopt the primitive elsewhere:

1. **Spec-fidelity (F1, F2, F3, F4, F10, F13, F20).** The headline
   issue: nous validated *self-consistency* (executor matches bundle)
   but not *spec-fidelity* (bundle matches campaign) under
   `--auto-approve`. **Primitive**: `campaign.locked_parameters`
   (#246) — hard-fail on deviation, regardless of `--auto-approve`.
   Adoption: `locked_workload` (#265) for workload yamls,
   `unlocked_parameters_audit` (#261) for the agent's side, the
   methodology hierarchy clause (#247) at the prompt layer, and
   `campaign_spec_diff` (#249) for the soft-record auditor channel.
2. **Apparatus discipline (F7, F14, F16).** Invariants must validate
   ATTRIBUTION, not upstream totals. Primitive: methodology prompt
   sections covering the bug-class question and the "rehearsal as
   scientific instrument" pattern.
3. **Lifecycle / portability (F5, F11, F12, F19, F21).**
   Primitive: per-phase silence threshold (#264) closes the active-
   stall failure mode where DESIGN's heavy reasoning trips an
   EXECUTE_ANALYZE-tuned watchdog. F21 lands cross-campaign code
   reuse via `cumulative.patch` + `derived_from`.
4. **Reproducibility (F17, F18).** Primitive: `reproducibility_metadata`
   (#262) auto-captured at INIT, plus per-iter snapshots of latency
   config files. F18 builds on that to ship paper artifact tarballs.
5. **Hygiene (F6, F8, F9, F15).** Individually low-severity; each
   lands a small, focused fix.

## How to verify (paste-ready)

```bash
# Unit tests covering F1, F3, F4, F11, F15, F17, F18, F19, F20, F21:
pytest tests/test_friction_245.py -v

# Schema smoke (F1/F3/F15/F19/F20 schema additions parse):
python -c "import yaml, jsonschema; \
  s = yaml.safe_load(open('orchestrator/schemas/campaign.schema.yaml').read()); \
  print('campaign schema valid')"

# Full suite (regression check):
pytest tests/ -q
```

Every change is tagged in code with `(#NNN / F<n>)` so `git blame` +
the issue tracker form a complete audit trail.
