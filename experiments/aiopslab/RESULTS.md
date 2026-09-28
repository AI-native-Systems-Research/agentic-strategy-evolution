# AIOpsLab results (Opus 4.6, kind local)

All configs on `claude-opus-4-6` via the litellm proxy. Metrics are AIOpsLab's own objective
evaluator. `steps`/`tokens` for Nous are AIOpsLab-side (it sees one `get_action→submit`); the real
investigation is inside Nous (see each run's `meta.json` `nous_seconds` and `nous_runs/` artifacts).

## Detection — `misconfig_app_hotel_res-detection-1`
| Config | Detection Accuracy | TTD (s) | steps | tokens in/out | Notes |
|:--|:--|--:|--:|:--|:--|
| **Nous** (adapter) | **Correct** | 267.8 | 1 | (internal) | 1 iteration, observe-only |
| plain-Claude (GenericOpenAI) | **Correct** | 9.0 | 4 | 1547 / 149 | same model |

**Takeaway:** detection is a binary Yes/No task — both configs solve it and plain-Claude is ~30x
faster, so Nous's campaign overhead is not justified here. Detection is a poor discriminator of
methodology. The informative tasks are **localization** (which component) and **analysis** (root
cause), where investigation depth matters. Comparison focus moves there.

## Localization — `misconfig_app_hotel_res-localization-1`
| Config | Localization Acc | TTL (s) | steps | tokens in/out | Notes |
|:--|:--|--:|--:|:--|:--|
| **Nous** (adapter) | **100%** (`["geo"]`) | 241.6 | 1 | (internal) | 1 iteration, observe-only |
| plain-Claude | **100%** (`["geo"]`) | 25.9 | 6 | 3860 / 248 | same model |

## Pilot conclusion (honest)
The adapter works and is scored fairly by AIOpsLab. But on these hotel-reservation **misconfig**
tasks, **both Nous and plain-Claude score perfectly** on detection and localization, and plain-Claude
is ~10-30x faster. Single-fault misconfig tasks are too easy to discriminate methodology on a binary
accuracy metric; Nous's campaign overhead is not justified here.

## To actually discriminate Nous (next)
- **Negative / NoOp tasks** (`noop_detection_*`): correct answer is "No fault". Raw agents tend to
  false-positive; Nous's negative-control discipline should avoid it. Strong candidate discriminator.
- **Analysis (root-cause) tasks**: require naming the fault *type/mechanism*, more room to be wrong.
- **Harder fault types**: network delay/loss, kafka queue, high-CPU, disk — subtler than a misconfig.
- Possibly **social-network** app (more services) and multi-symptom faults.
- Also: surface Nous internal step/token counts (`nous_runs/.../llm_metrics_summary.json`).

_Runs persisted under `results/<config>/<problem_id>/<timestamp>/` (results.json, meta.json)._
