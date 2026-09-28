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
| Config | Correct? | TTL (s) | Notes |
|:--|:--|--:|:--|
| **Nous** (adapter) | _running_ | — | 1 iteration, observe-only |
| plain-Claude | _pending_ | — | same model |

## TODO
- Surface Nous internal step/token counts from `nous_runs/.../llm_metrics_summary.json` for fair token accounting.
- Consider analysis/mitigation tasks (harder) once localization is in.

_Runs persisted under `results/<config>/<problem_id>/<timestamp>/` (results.json, meta.json)._
