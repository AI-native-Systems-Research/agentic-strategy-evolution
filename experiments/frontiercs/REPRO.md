> **Superseded 2026-10-13:** the current results, rules, and run commands are in `README.md`. This file is kept for history only.

# Reproducing a Frontier-CS datapoint

`README.md` is the source of truth (golden rules §0, exact env §5/§5.1). This file is the short recipe.
Setup: `SETUP_NOTES.md` (judge + Frontier-CS). Keys/URLs come from `~/.zshrc`, never from the repo.

Golden rules: every agent as-is (Nous, real Engram, real AIDE, Claude Code agent); $50 cap
(tokens × $15/$75, cache-aware); sandboxed, no web, judge daemon, exploit audit + re-judge.

## Algorithmic (`<p>` = problem id; judge daemon `gen/judge_server.py --root /tmp/fcs_judge` running)

```bash
# Nous (as-is, sandboxed, token-capped)
python3 -u gen/nous_cap_launch.py <p> ...                     # see README §5
# Claude Code agent
python3 -u gen/claude_code_runner.py <p> --budget 50 --max-score 100 --out-dir runs/p<p>/claude
# Engram (real mit-nms/Engram, cost-capped)
bash gen/monitoring/engram_cost_cap.sh <alg_id> 50
# AIDE (real Weco aideml + adapter)
python3 gen/aide_frontier.py <p> --budget 50 --ceiling 99.5 --steps 80
```

## Research (score-metric: grammar_fuzzing, llm_router)

```bash
# Nous on vpc
env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL=$FCS_VPC_URL ANTHROPIC_API_KEY=$FCS_VPC_KEY \
  OPENAI_BASE_URL=$FCS_VPC_URL OPENAI_API_KEY=$FCS_VPC_KEY \
  python3 -u gen/nous_research_cap.py <task> --slug <slug> --model <model> --budget 50 --niters 30 \
  --out artifacts/preds/<name>.nous.<tag>.json --logdir ~/frontier/gen_logs
# Claude Code agent on vpc-int
env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY=$OPENAI_API_KEY \
  python3 -u gen/claude_code_research_runner.py <task> --slug <slug> --model <model> --budget 50 \
  --out-dir runs/<dir>/claude_<tag> --out artifacts/preds/<name>.claude.<tag>.json
```

cloudcast: Claude via `gen/claude_research_runner.py`; Engram via `engram_cost_cap.sh`.

## Re-judge a persisted solution

```bash
cd ~/frontier/Frontier-CS/research/problems/<task> && .evalvenv/bin/python3 evaluator.py --solution <sol.py> --out /tmp/x.json
```

Nous research solutions: `~/frontier/gen_logs/research_<slug>_measured_<ts>/` (every measured file,
named with its in-loop score) and `nous_runs/research-<slug>/runs/iter-*/inputs/*.py`.
