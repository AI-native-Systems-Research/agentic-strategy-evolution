# Nous on AIOpsLab

Run Nous as an investigator on Microsoft [AIOpsLab](https://github.com/microsoft/AIOpsLab)
live-Kubernetes fault problems, scored by AIOpsLab's objective evaluator (Detection Accuracy,
localization, TTD, steps, tokens), head-to-head with plain-Claude and AIOpsLab's baseline agent —
all on **Opus 4.6**.

## Contents
- `ai_ops_setup.md` — reproducible AIOpsLab local setup (kind on M1, litellm backend). **Start here.**
- `DESIGN.md` — adapter design + self-review (AIOpsLab is the outer driver; one Nous campaign per `get_action`).
- `adapter/` — `NousAgent` (AIOpsLab-side) + campaign template.
- `runners/` — scripts to run each config (Nous / plain-Claude / AIOpsLab baseline).
- `campaigns/` — generated Nous campaign specs (kept for repro).
- `results/<config>/<problem_id>/<timestamp>/` — persisted session + results + Nous run artifacts.

## Prereqs
1. AIOpsLab installed + kind cluster up (see `ai_ops_setup.md`).
2. Nous installed (`nous` CLI on PATH).
3. litellm env: `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` (Nous), `OPENAI_COMPATIBLE_*` (baselines).
4. Model fixed to `claude-opus-4-6` for all configs.

## Status
Design complete; adapter implementation in progress. See `DESIGN.md`.
