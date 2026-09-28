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

## Overall conclusion
Across detection, localization, NoOp, and hard perf-localization, **Nous never exceeds plain Claude
Code on AIOpsLab** (parity on accuracy, slower). AIOpsLab tasks have definite lookup-style answers a
strong base model already finds, so they do not exercise Nous's methodology. **AIOpsLab is a
feasibility/breadth demonstration, not a discriminator for Nous.** The "Nous wins" story needs an
open-ended benchmark with continuous quality headroom (e.g., SWE-fficiency perf optimization), where
solution quality varies and methodology can plausibly separate.

## MITIGATION (multi-step: apply a real fix + verify recovery) — `misconfig_app_hotel_res-mitigation-1`
| Config | Success | TTM (s) | Notes |
|:--|:--|--:|:--|
| **Nous** (adapter) | **True** | 285.4 | applied fix, verified recovery |
| plain Claude Code (L0) | _running_ | — | same base agent, no methodology |

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
