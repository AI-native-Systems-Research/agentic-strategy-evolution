# AIOpsLab results (Opus 4.6, kind local)

All configs on `claude-opus-4-6` via the litellm proxy. Metrics are AIOpsLab's own objective
evaluator. `steps`/`tokens` for Nous are AIOpsLab-side (it sees one `get_action→submit`); the real
investigation is inside Nous (see each run's `meta.json` `nous_seconds` and `nous_runs/` artifacts).

## Detection — `misconfig_app_hotel_res-detection-1`
| Config | Detection Accuracy | TTD (s) | steps | tokens in/out | Notes |
|:--|:--|--:|--:|:--|:--|
| **Nous** (adapter) | **Correct** | 267.8 | 1 | (internal) | 1 iteration, observe-only |
| AIOpsLab-agent (Opus) | **Correct** | 9.0 | 4 | 1547 / 149 | AIOpsLab GenericOpenAI agent |

**Takeaway:** detection is a binary Yes/No task — both configs solve it and plain-Claude is ~30x
faster, so Nous's campaign overhead is not justified here. Detection is a poor discriminator of
methodology. The informative tasks are **localization** (which component) and **analysis** (root
cause), where investigation depth matters. Comparison focus moves there.

## Localization — `misconfig_app_hotel_res-localization-1`
| Config | Localization Acc | TTL (s) | steps | tokens in/out | Notes |
|:--|:--|--:|--:|:--|:--|
| **Nous** (adapter) | **100%** (`["geo"]`) | 241.6 | 1 | (internal) | 1 iteration, observe-only |
| AIOpsLab-agent (Opus) | **100%** (`["geo"]`) | 25.9 | 6 | 3860 / 248 | AIOpsLab GenericOpenAI agent |

## NoOp (no fault) — `noop_detection_hotel_reservation-1`  (false-positive test)
| Config | Detection | TTD (s) | Notes |
|:--|:--|--:|:--|
| **Nous** | **Correct ("No")** | 315.6 | no false positive |
| AIOpsLab-agent (Opus) | **Correct ("No")** | ~fast | no false positive either |

## HARD — `astronomy_shop_ad_service_high_cpu-localization-1` (subtle perf fault, ~20 services)
| Config | Localization Acc | TTL (s) | Notes |
|:--|:--|--:|:--|
| **Nous** (adapter) | **100%** (`["ad"]`) | 527.8 | Claude Code + methodology |
| plain Claude Code (L0) | **100%** (`["ad"]`) | 92.0 | Claude Code, no methodology — also correct, ~6x faster |
| AIOpsLab-agent (Opus) | **0%** (failed) | 131.9 | GenericOpenAI scaffold; 30 steps, 28.7k tok, wrong/no answer |

**Hard-task takeaway (careful):** the split is Nous ≈ plain-Claude-Code (both 100%) vs the AIOpsLab
GenericOpenAI scaffold (0%). That is a **base-agent/harness effect** (Claude Code >> AIOpsLab's
OpenAI-compat ReAct loop), **not a Nous-methodology effect** — Nous shows no gain over plain Claude
Code, at ~6x the time. Reporting "Nous beats AIOpsLab's agent 100 vs 0" would be misleading as
methodology evidence, since plain Claude Code also beats it 100 vs 0, and would invite the
"model not methodology" critique.

## FINAL VERDICT — AIOpsLab (Opus 4.6, kind local)

Full scoreboard (✓ = correct/success):

| Task | Type | Nous | plain Claude Code (L0) | AIOpsLab-agent |
|:--|:--|:--|:--|:--|
| misconfig hotel-res | detection | ✓ 268s | — | ✓ 9s |
| misconfig hotel-res | localization | ✓ 242s | — | ✓ 26s |
| NoOp hotel-res (no fault) | detection | ✓ "No" 316s | — | ✓ "No" |
| astronomy ad high-cpu | localization | ✓ 528s | ✓ 92s | ✗ 0% (fail) |
| misconfig hotel-res | mitigation | ✓ 285s | ✓ 57s | — |
| astronomy kafka-queue | mitigation | ✓ 417s | ✓ 209s | — |

**Nous never beats plain Claude Code on AIOpsLab.** On every head-to-head with the true L0 (same base
agent, no methodology) — including the two hardest tasks (astronomy high-cpu localization, kafka
mitigation) — both succeed and Nous is 2-6x slower. The only non-parity anywhere is AIOpsLab's *own*
GenericOpenAI agent failing hard localization (0%), which plain Claude Code also beats — a
**base-agent effect (Claude Code >> GenericOpenAI loop), not a Nous-methodology effect.**

**Why:** AIOpsLab tasks have a **definite answer** (which service is faulty / apply the known fix) that a
strong base model finds in a few kubectl commands. They do not exercise Nous's value (controlled
multi-arm experiments, prediction-error taxonomy, compounding principles), which is for **open-ended
problems with a continuous quality gradient**.

**Decision:** AIOpsLab = a **feasibility/breadth** demonstration ("Nous runs as an investigator on a
standard ops benchmark and matches strong agents"), **not** a discriminator for methodology. Do NOT
build the MLSys "Nous wins" claim on it. Move the discriminating comparison to **SWE-fficiency**
(perf optimization: continuous speedup metric, hard correctness gate, baseline ~0.04 of expert
parity → real headroom).

### Coverage / honesty note
- The methodology-isolation comparison is **Nous vs plain Claude Code** (3 tasks incl. the 2 hardest).
  Easy detection/localization/NoOp used the AIOpsLab-agent as the comparator (all solved); plain
  Claude Code was not separately run on those (base agent strictly stronger, would also solve them).
- Single run per (config, task); AIOpsLab metrics are objective (no LLM judge). Adapter dry-runs
  validated; all runs reproducible via `runners/` + `results/`.
- Infra caveat: astronomy first-deploy needs image pre-caching (300s readiness window); documented in `ai_ops_setup.md`.

## MITIGATION (multi-step: apply a real fix + verify recovery) — `misconfig_app_hotel_res-mitigation-1`
| Config | Success | TTM (s) | Notes |
|:--|:--|--:|:--|
| **Nous** (adapter) | **True** | 285.4 | applied fix, verified recovery |
| plain Claude Code (L0) | **True** | 56.8 | also fixed it, ~5x faster |

### HARD mitigation — `astronomy_shop_kafka_queue_problems-mitigation-1` (~20 services)
| Config | Success | TTM (s) | Notes |
|:--|:--|--:|:--|
| **Nous** (adapter) | **True** | 417.3 | fixed the kafka-queue perf fault + verified |
| plain Claude Code (L0) | **True** | 208.6 | also fixed it, ~2x faster |

## Config note
"AIOpsLab-agent (Opus)" = AIOpsLab's *own* GenericOpenAI shell agent on claude-opus-4-6 (their
scaffolding, OpenAI-compatible API). It is NOT "plain Claude Code". A separate **plain Claude Code**
L0 (the same base agent Nous wraps, no methodology; `run_claude.py`) is pending — it isolates the
*methodology* contribution with the base agent held constant.

## Pilot conclusion (honest)
The adapter works and is scored fairly by AIOpsLab. But across detection, localization, AND the NoOp
false-positive test on hotel-reservation, **Nous and the AIOpsLab agent both score perfectly**, and the
baseline is ~10-30x faster. Easy single-fault tasks (and even the NoOp negative) do not discriminate
methodology; the AIOpsLab GenericOpenAI agent on Opus is already a strong baseline. Discrimination, if
any, must come from the **hard `astronomy_shop` perf-localization tasks** (subtle degradation across ~20
services). If Nous does not separate there either, AIOpsLab is not the right benchmark to showcase Nous.

## To actually discriminate Nous (next)
- **Negative / NoOp tasks** (`noop_detection_*`): correct answer is "No fault". Raw agents tend to
  false-positive; Nous's negative-control discipline should avoid it. Strong candidate discriminator.
- **Analysis (root-cause) tasks**: require naming the fault *type/mechanism*, more room to be wrong.
- **Harder fault types**: network delay/loss, kafka queue, high-CPU, disk — subtler than a misconfig.
- Possibly **social-network** app (more services) and multi-symptom faults.
- Also: surface Nous internal step/token counts (`nous_runs/.../llm_metrics_summary.json`).

_Runs persisted under `results/<config>/<problem_id>/<timestamp>/` (results.json, meta.json)._
