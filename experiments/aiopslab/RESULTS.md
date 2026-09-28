# AIOpsLab results (Opus 4.6, kind local)

All configs on `claude-opus-4-6` via the litellm proxy. Metrics are AIOpsLab's own objective
evaluator. `steps`/`tokens` for Nous are AIOpsLab-side (it sees one `get_action→submit`); the real
investigation is inside Nous (see each run's `meta.json` `nous_seconds` and `nous_runs/` artifacts).

## Detection — `misconfig_app_hotel_res-detection-1`
| Config | Detection Accuracy | TTD (s) | Notes |
|:--|:--|--:|:--|
| **Nous** (adapter) | **Correct** | 267.8 | 1 iteration, observe-only, `answer_valid=true` |
| plain-Claude (GenericOpenAI) | _running_ | — | AIOpsLab shipped shell agent, same model |

## Pending
- Localization task (Nous vs plain-Claude).
- Surface Nous internal step/token counts from `nous_runs/.../llm_metrics_summary.json` for fair token comparison.

_Runs persisted under `results/<config>/<problem_id>/<timestamp>/` (results.json, meta.json)._
