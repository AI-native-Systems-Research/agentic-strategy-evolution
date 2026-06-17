# Bench variants

A *variant* is one configuration of an agent answering a research question. The bench runs multiple variants on the same campaign with the same budget, scores each via Claude-as-judge, and produces a side-by-side comparison.

## The variant contract

Every variant is a Python class that implements one method, `run(...)`, and returns one dataclass, `VariantResult`. The runner doesn't look inside the variant — it only knows that calling `variant.run(campaign, workspace, budget)` will eventually return a `VariantResult` (or raise, in which case the runner records `crashed=True`).

```python
class Variant(Protocol):
    name: str

    def run(
        self,
        campaign: Campaign,        # parsed campaign yaml: question, target
        workspace: Path,           # this variant's private clone of the target repo
        budget: Budget,            # max tokens, max iterations, max wall seconds
    ) -> VariantResult: ...

@dataclass
class VariantResult:
    variant: str                   # variant name (matches the file in variants/)
    campaign_id: str               # which campaign this came from
    tokens_in: int                 # cumulative input tokens (billable only)
    tokens_out: int                # cumulative output tokens
    dollars: float                 # tokens × per-model price
    wall_seconds: float            # variant.run() wall-clock
    final_answer: str              # the variant's stated conclusion (verbatim)
    artifacts_dir: Path            # where the variant wrote its outputs
    raw_log_path: Path             # full transcript of every LLM call (for audit)
    crashed: bool                  # True if variant.run() raised
    hit_cap: bool                  # True if the budget cap terminated the variant early
    error: str | None              # exception message if crashed
```

`Variant` is the protocol — what an implementation has to look like from outside. `VariantResult` is the output shape every variant fills in before returning. The runner only ever sees `VariantResult`; everything else (which model the variant called, how it spawned subprocesses, how it parsed output) is the variant's private business.

## The 5 variants currently registered

The "Level" column refers to the L0/L1/L2/L3 ladder used in the paper's
graduated ablation: **L0** = ad-hoc agent (no structure), **L1** =
methodology-as-prompt (single session), **L2** = methodology + multi-session
memory (without nous's structural enforcement), **L3** = full nous
orchestrator. `claude_loop` sits between L0 and L1 — adds the iteration axis
to L0 without methodology.

| Variant | Level | What it is | What this isolates |
|---|---|---|---|
| `claude_plain` | **L0** | Single headless Claude Code session, no methodology, no loop | The floor — ad-hoc agent use with none of nous's structure |
| `claude_loop` | L0 + iter | N sequential `claude_plain` sessions; previous answer prepended to next session's question | The value of *iteration alone* — does running the agent more times help, or does it drift without methodology? |
| `claude_methodology` | **L1** | Single Claude session with `bench/methodology/methodology.md` injected as system prompt | The L1 baseline — methodology-as-prompt vs methodology-as-orchestration. Tests whether nous's structural enforcement (schema, deterministic phases, gates) does real work beyond what a system prompt can do |
| `claude_methodology_loop` | **L2** | N sequential `claude_methodology` sessions; principles extracted via regex and prepended to next session | Methodology + memory across sessions, *without* nous's deterministic principle merge, schema validation, or git isolation |
| `nous` | **L3** | The full orchestrator (`nous run` subprocess) | The reference — multi-iteration, schema-validated artifacts, git-isolated experiments, principle merging in Python (not by the LLM), checkpoint/resume |

The bench runs them in parallel on the same campaign and grades each on the same metric row. Differences in scores localize *which structural piece of nous* is doing the work.

## How to add a new variant

5-step recipe.

1. **Pick the file location**: `bench/variants/<your_variant>.py`. If your variant calls `claude --print`, lean on the shared helpers in `bench/variants/_claude_common.py` (`ClaudeInvocation`, `invoke_claude`, `variant_result_from`) — they handle subprocess + parsing + result aggregation.

2. **Implement the Variant Protocol**:
   ```python
   from bench.variants._claude_common import ClaudeInvocation, invoke_claude, variant_result_from
   from bench.variants.base import Budget, Campaign, VariantResult

   class YourVariant:
       name = "your_variant"

       def run(self, campaign: Campaign, workspace: Path, budget: Budget) -> VariantResult:
           inv = ClaudeInvocation(
               question=campaign.research_question,
               workspace=workspace,
               budget=budget,
               log_path=workspace / ".bench-your-variant.log",
               # set system_prompt= for methodology-style variants
           )
           result = invoke_claude(inv)
           return variant_result_from([result], variant_name=self.name, ...)
   ```

   For loop variants, build a list of `ClaudeRunResult`s across N invocations and pass them all to `variant_result_from`.

3. **Register in the runner**: add an import and an entry in `bench/runner.py:VARIANT_REGISTRY`.

4. **Add a description** in `bench/__main__.py:VARIANT_DESCRIPTIONS` so `python3 -m bench list` shows it.

5. **Test the variant**: create `tests/test_bench_variants_<your_variant>.py`. Patch `bench.variants._claude_common.subprocess.run` for low-level tests, or patch `bench.variants.<your_variant>.invoke_claude` for variant-level tests. **No live Claude calls in tests** — the autouse fixture in `tests/conftest.py` blocks them.

If your variant produces structured artifacts beyond a final answer (e.g. like nous's `findings.json`), implement a `_render_*` helper similar to `bench/variants/nous.py:_read_final_answer` so the judge sees your full output, not just one slice.

## Standards every variant must follow

- **Token accounting**: count only `usage.input_tokens` (billable) and `usage.output_tokens`. Do NOT count `cache_creation_input_tokens` or `cache_read_input_tokens` — they're billed at different rates and reflected in `cost_usd` already. Counting them inflates cache-heavy variants 1000× and breaks the comparison. (Phase 1.7.1 fix; same rule everywhere.)
- **`final_answer` must reflect what the variant actually produced**. If your variant writes structured artifacts, render them into `final_answer` so the judge sees what an honest reviewer would. (Phase 2.7 + 2.8 fixes.)
- **No live LLM calls in tests**. Patch at the subprocess seam (`bench.variants._claude_common.subprocess.run`) or at the variant level (`invoke_claude`). The `block_live_llm_calls` autouse fixture is the backstop.
- **Behavioral testing only**: assert what's in the rendered output, the result fields, the file system. Don't assert which method was called or argv shapes.
