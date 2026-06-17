# nous-bench walkthrough

A guide to the `bench/` framework: what it does, what the user sees, what happens in the background, every file involved, the parallel execution details, the design choices made, and the JSON / yaml shapes flowing through the pipeline.

## 1. What this thing is

The benchmark framework runs a single research question through several agent configurations ("variants") and produces a unified comparison report scoring each variant on:

- **Tokens** (billable input + output)
- **Dollars** (Anthropic's reported `cost_usd`)
- **Wall-clock**
- **Correctness** (Claude-as-judge, 0–10)
- **Completeness** (Claude-as-judge, 0–10)

The whole point: prove that the nous orchestrator's structural guarantees (multi-iteration with deterministic phase transitions, schema-validated artifacts, git-isolated experiments, principle merging) outperform ad-hoc Claude usage *and* Claude prompted with the same methodology. The first live comparison validated the claim — `nous` scored 9/10 on correctness vs `claude_plain`'s 7/7 on the same budget for the same question.

## 2. Where everything lives

```
agentic-strategy-evolution/
├── orchestrator/                  ← Nous itself (untouched by bench)
├── prompts/methodology/           ← Nous's phase prompts
├── docs/
│   ├── architecture.md
│   ├── contributing/workflow.md   ← Claude-based PR workflow
│   └── bench/                     ← bench docs (this file + variants.md)
└── bench/                         ← the framework
    ├── variants/
    │   ├── base.py                ← Variant Protocol + dataclasses
    │   ├── _claude_common.py      ← shared invoke_claude + variant_result_from
    │   ├── claude_plain.py        ← L0 baseline
    │   ├── claude_loop.py         ← N sequential plain sessions
    │   ├── claude_methodology.py  ← L1 baseline (methodology in prompt)
    │   ├── claude_methodology_loop.py  ← L2 (methodology + principle carry-forward)
    │   └── nous.py                ← reference (wraps `nous run`)
    ├── methodology/
    │   └── methodology.md         ← pinned system prompt for *_methodology variants
    ├── campaigns/
    │   └── blis_prefix.yaml
    ├── experiments/
    │   ├── phase1_smoke.yaml      ← nous-only
    │   ├── phase2_compare.yaml    ← claude_plain + nous
    │   └── phase4_full_sweep.yaml ← all 5 variants
    ├── isolation.py               ← `git clone`-per-variant
    ├── metrics.py                 ← parse_claude_json + LLMMeter
    ├── judge.py                   ← Claude-as-judge accuracy scoring
    ├── judge_prompt.md            ← committed-and-pinned judge instructions
    ├── report.py                  ← markdown renderer
    ├── runner.py                  ← orchestrates variants + judge + report
    └── __main__.py                ← `python3 -m bench {run, list}`
```

`bench/` imports nous as a library (e.g. to invoke `nous run` from the `nous` variant). Nothing inside `orchestrator/` or `prompts/` imports anything from `bench/`. One-way dependency: changes inside `bench/` cannot break nous; nous can keep evolving on `main` without coordinating with the bench code.

## 3. The three-layer mental model

Three concepts:

| Layer | Question | File | Reusable? |
|---|---|---|---|
| **Campaign** | What do we want to know? | `campaigns/<id>.yaml` | Yes — many experiments can reference one campaign |
| **Variant** | How does the agent try to find out? | `variants/<name>.py` | Yes — implements the `Variant` Protocol |
| **Experiment** | What are we actually running? | `experiments/<id>.yaml` | One-shot — picks campaign + variants + budget |

### Concrete example — `campaigns/blis_prefix.yaml`

```yaml
id: blis_prefix
research_question: "With total input length held fixed, does increasing the prefix portion (cached tokens) reduce TTFT under moderate load?"
target_repo: "/Users/naimaabrar/Desktop/nous/inference-sim"
target_ref: "main"
```

### Concrete example — `experiments/phase4_full_sweep.yaml`

```yaml
id: phase4_full_sweep
campaign: campaigns/blis_prefix.yaml
variants: [claude_plain, claude_loop, claude_methodology, claude_methodology_loop, nous]
budget:
  max_tokens: 200000
  max_iterations: 3
  max_wall_seconds: 1800
```

## 4. What the user sees

### List what's available
```
$ cd agentic-strategy-evolution
$ python3 -m bench list
Campaigns:
  blis_prefix              With total input length held fixed, does increasing the prefix portion (cached t...

Variants:
  claude_loop              N sequential plain sessions, summary carry-forward
  claude_methodology       single session w/ methodology.md as system prompt
  claude_methodology_loop  N methodology sessions w/ principle carry-forward
  claude_plain             single Claude Code session, no methodology
  nous                     full orchestrator (multi-iter, schema-validated, isolated)
```

### Run an experiment
```
$ python3 -m bench run bench/experiments/phase4_full_sweep.yaml
Run complete: /Users/.../runs/2026-06-16_phase4_full_sweep
Report:       /Users/.../runs/2026-06-16_phase4_full_sweep/report.md
```

Between those two print lines: ~30 minutes (parallelism keeps wall-clock to the slowest variant), ~$15-25 (5 variants × 3 iters × Sonnet), 5 git clones into `runs/<id>/`, one parallel `ThreadPoolExecutor` running all variants concurrently, and one Claude judge call at the end.

### CLI flags

```
python3 -m bench run experiments/<id>.yaml [flags]

  --variants a,b,c           override yaml's variant list
  --max-tokens N             override budget.max_tokens
  --max-iterations N         override budget.max_iterations
  --max-wall-seconds N       override budget.max_wall_seconds
  --max-parallel-variants N  cap concurrent variants
  --skip-judge               skip Claude-as-judge (saves $ during debugging)
  --run-id NAME              override generated run-id
```

## 5. What happens in the background

```
__main__.py: parse_args
        │
        ├── argparse builds args object
        ├── budget_overrides = {} unless flags passed
        └── runner.run_experiment(experiment_path, ..., skip_judge=False)
        │
        ▼
runner.run_experiment
        ├── Experiment.from_yaml → loads campaign too
        ├── validate_variants → reject duplicates / unknown names
        ├── apply budget_overrides
        ├── find_repo_root via pyproject.toml walkup
        ├── mkdir runs/<rid>/, snapshot campaign + experiment yamls
        ├── max_workers = min(len(variants), cpu_count)
        ├── ThreadPoolExecutor(max_workers).map(_run, variants)
        │     For each variant in PARALLEL:
        │       a) variant_dir = run_dir / variant_name
        │       b) workspace = variant_dir / "workspace"
        │       c) isolation.clone_target_repo(target_repo, target_ref, workspace)
        │       d) variant = VARIANT_REGISTRY[variant_name]()
        │       e) result = variant.run(campaign, workspace, budget)
        │     map() returns results in INPUT order
        │
        ├── judge.run_judge(research_question, results) (skipped if --skip-judge)
        ├── attach judge scores to each variant's dict
        ├── write per-variant result.json + combined results.json
        └── report.render(run_dir) → runs/<rid>/report.md
```

## 6. How each variant works

### nous (the reference)
Wraps `nous run <generated_yaml> --auto-approve --run-id <id> --max-iterations <N>`. Reads tokens from `<workspace>/.nous/<id>/llm_metrics.jsonl`, renders a multi-section `final_answer` from `findings.json` (per-arm `predicted`/`observed`/`status`), `principles.json` (cumulative knowledge), `ledger.json` (per-iter outcome rows), and `report.md` (verbatim if present). All artifacts come from nous itself — the bench just observes.

### claude_plain (L0)
Spawns `claude --print --output-format json --dangerously-skip-permissions --model claude-sonnet-4-6 "<question>"` in the workspace. Reads stdout JSON for the agent's reply and token usage. One subprocess call, one final answer.

### claude_loop
N sequential `claude_plain` calls. Each call after the first prepends the previous final answer to the next user message ("Previous session's answer: ... Continue refining"). No methodology, no principle extraction, no schema enforcement.

### claude_methodology (L1)
Same plumbing as `claude_plain` but invokes Claude with `--append-system-prompt <bench/methodology/methodology.md>`. The system prompt explains hypothesis bundles, controlled experiments, prediction error taxonomy, principle extraction, and the artifact schemas to produce. Same agent, same task — only the system prompt differs.

### claude_methodology_loop (L2)
Same loop pattern as `claude_loop` but on top of `claude_methodology`. Between sessions, `_extract_principles(text)` regex-scans the agent's reply for a `## Principles` section and pulls out the labeled principles. Principles **accumulate** across iterations and get prepended to the next session's user message — same shape as nous's `principles.json`, but without nous's structural enforcement (no schema validation, no dedup, no conflict detection). That absence is the experimental signal.

## 7. The judge (`bench/judge.py`)

Runs after all variants complete. Single Claude session with the pinned `bench/judge_prompt.md` as system prompt. Input: research question + each (non-crashed) variant's `final_answer`. Output: per-variant `(correctness 0-10, completeness 0-10, rationale)`. Crashed variants are skipped (scores `None`). Judge prompt is committed and pinned — drift between runs invalidates cross-run comparisons.

Token cost goes in a top-level `judge_usage` field in `results.json`, NOT mixed into per-variant rows.

## 8. Parallel execution

`ThreadPoolExecutor`, not `ProcessPoolExecutor` — each variant spawns its own subprocess (`nous run` or `claude --print`); the variant Python class is just an orchestrator. Threads avoid pickle issues and have no GIL contention since the heavy work is out-of-process.

`max_workers = min(len(variants), os.cpu_count() or 4)`. Order preservation: `map()` returns results in input order regardless of completion order.

## 9. The output structure

```
runs/2026-06-16_phase4_full_sweep/
├── report.md                    ← human-readable comparison
├── results.json                 ← machine-readable, all variants + judge_usage
├── experiment.snapshot.yaml     ← exact yaml used (for traceability)
├── campaign.snapshot.yaml       ← exact campaign yaml used
├── claude_plain/
│   ├── result.json              ← VariantResult
│   └── workspace/               ← cloned target repo (gitignored)
├── claude_loop/
├── claude_methodology/
├── claude_methodology_loop/
└── nous/
    ├── result.json
    └── workspace/
        └── .nous/<run_id>/      ← all of nous's own outputs
```

`runs/` is gitignored — workspaces are 50–500 MB each.

## 10. Token accounting

The bench counts only `usage.input_tokens` (billable fresh input) and `usage.output_tokens` for the comparison row. Cache fields (`cache_creation_input_tokens`, `cache_read_input_tokens`) are billed at 0.10×–1.25× full rate and are reflected in `cost_usd` already. Counting them in `tokens_in` would inflate cache-heavy variants like nous 1000× — making `hit_cap` a false alarm and the comparison unfair.

This rule is enforced at every harvest site (`bench/metrics.py:parse_claude_json`, `bench/variants/nous.py:_harvest_metrics`).

## 11. The Phase 1.7.1 / 2.7 / 2.8 pattern

Three bugs surfaced by live smoke runs followed the same shape: nous produces structured output, the bench renders too narrow a slice, the judge scores nous on what it sees rather than what nous delivered.

| Phase | What was hidden from the judge | Effect |
|---|---|---|
| 1.7.1 | Cache token fields rolled into `tokens_in` | False `hit_cap` alarm |
| 2.7 | Per-arm `predicted` / `observed` / `status` (only `discrepancy_analysis` shown) | Judge scored nous 3/2 vs claude_plain 8/8 — backwards from reality |
| 2.8 (#292) | Principles, ledger, report, all-iters findings | Judge would see only one iter's summary |

Sub-issue #292 closed all three by widening the rendering once across all four artifact types. Output grew from 375 chars (just `discrepancy_analysis`) to 6,869 chars (full structured set) on the existing smoke run. Documented in `docs/bench/final-answer-rendering.md`.

## 12. Test architecture

```
tests/test_bench_base.py               (4 tests)  — Campaign/Experiment yaml parsing
tests/test_bench_isolation.py          (3 tests)  — clone_target_repo
tests/test_bench_metrics.py           (12 tests)  — parse_claude_json + LLMMeter
tests/test_bench_variants_nous.py    (35 tests)  — yaml translation, all four artifact renderers
tests/test_bench_variants_claude_common.py (18 tests) — invoke_claude + variant_result_from
tests/test_bench_variants_claude_plain.py        (2 tests)
tests/test_bench_variants_claude_loop.py        (11 tests)
tests/test_bench_variants_claude_methodology.py  (6 tests)
tests/test_bench_variants_claude_methodology_loop.py (29 tests)
tests/test_bench_runner.py            (14 tests)  — find_repo_root, validation, parallel, judge wiring
tests/test_bench_judge.py             (12 tests)  — prompt assembly, JSON parsing, error paths
tests/test_bench_report.py             (9 tests)  — table rendering, judge columns, crashed variants
tests/test_bench_main.py               (6 tests)  — argparse, list command
                                     ─────────
                                      161 tests, ~1.4s, no live API calls
```

`tests/conftest.py` installs an autouse `block_live_llm_calls` fixture that strips API keys and refuses real network calls. Per-CLAUDE.md: tests must NEVER make live LLM calls.

## 13. Decisions that could have gone differently

| Choice | Alternative rejected | Why |
|---|---|---|
| Three-layer model (Campaign / Variant / Experiment) | Two-layer (budgets in campaign) | Reusability — same campaign re-runs with different budgets/variants without editing it |
| ThreadPoolExecutor | ProcessPoolExecutor | Variants spawn their own subprocesses; threads avoid pickle, no GIL issues |
| `tokens_in = input_tokens` only | Sum input + cache_creation + cache_read | Cache fields ~10× cheaper, reflected in cost_usd already; counting inflates cache-heavy variants 1000× |
| Render all nous artifacts in `final_answer` | Just findings or just principles | Hides nous's structural output, biases judge against nous (Phase 2.7 + 2.8 lesson) |
| Distill methodology.md from FAT prompts (`design.md`/`execute_analyze.md`) not THIN | Use `*_thin.md` versions | Thin assumes nous's CLAUDE.md is loaded; bench runs in target repo with target's CLAUDE.md, must be self-contained |
| `--auto-approve` mandatory for nous variant | Manual gates | Bench is unattended; without `--auto-approve` nous deadlocks on stdin |
| Headless Claude Code (`claude --print`) for L0/L1/L2 | Anthropic SDK with custom tool harness | "Same off-the-shelf agent" — using SDK with our harness invalidates the comparison |
| `git clone`-per-variant | `git worktree`-per-variant | Worktrees share `.git`; a baseline doing weird `git checkout` could corrupt others |
| Judge prompt + methodology.md committed once | Inline | Treats them as load-bearing infrastructure; prevents drift between runs |
| Skip crashed variants from judge (score = None) | Send empty answers, score = 0 | Empty answers → nonsense scores. None = honest "not judged" |

## 14. Status (sub-issue progression)

| Sub-issue | Status |
|---|---|
| Phase 1: nous variant + sequential runner + report + CLI | ✅ |
| Phase 2: claude_plain + ThreadPoolExecutor + judge | ✅ |
| Phase 1.7.1: token accounting + answer extraction fix | ✅ |
| Phase 2.7: per-arm rendering for nous | ✅ |
| Phase 2.8 (#292): all nous artifacts in final_answer | ✅ |
| Phase 3+4 (#293): claude_methodology, claude_loop, claude_methodology_loop, methodology.md, phase4_full_sweep, docs | ✅ |
| Sub-issue C: variant workspace isolation hardening | not started |
| Live phase4 smoke run (~$15–25, all 5 variants × 3 iters) | not run |
