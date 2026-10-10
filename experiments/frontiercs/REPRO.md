# Reproducing any datapoint in the Frontier-CS table

Everything needed to reproduce a cell of `RESULTS.md` is in this repo. Setup: follow
`SETUP_NOTES.md` (VM/judge) or `RUN_ON_MAC.md` (local). Model = `claude-opus-4-6` via litellm
(`ANTHROPIC_BASE_URL`/`OPENAI_BASE_URL` + token). All runners live in `gen/`.

## 0. Environment
- Install Frontier-CS + build the judge (`SETUP_NOTES.md`).
- `cd ~/frontier/Frontier-CS`; export litellm creds; Nous installed at `~/nous_repo` (its own venv),
  `claude` CLI + Node on PATH.
- Runners: `gen/frontier_gen.py` (claude/nous/engram), `gen/frontier_gen_costbudget.py`
  (adds `--cost-budget` + early-stop + 429 retry). Harvesters: `gen/harvest/harvest<pid>.sh`.
  Batch drivers (exact commands we ran): `gen/drivers/*.sh`.

## 1. Which tasks (reproducible draw)
```
python3 gen/select_tasks.py --seed 42 --n 3 --exclude 0 1 5 15   # -> 211, 44, 9
python3 gen/select_tasks.py --seed 43 --n 1 --exclude 0 1 5 9 15 44 47 147 185 192 211  # -> 22
```
First-4 tasks (0,1,5,15) were hand-seeded (0=hard packing, 1=easy knapsack, 5=Hamiltonian,
15=perm gate). Mac batch (47,147,185,192) in `artifacts/mac/RESULTS_newtasks.md`.

## 2. Reproduce a single cell  (`<p>` = problem id)

**Nous** (iters: 5 for p0/1/5/15, 3 for p211/44/9):
```
python3 gen/frontier_gen.py <p> --agent nous --nous-iters <N> --out preds/p<p>.nous.json
bash gen/harvest/harvest<p>.sh      # re-evals every persisted arm, writes best to preds/p<p>.nous.json
```
(Nous deliverable = best *correct* arm, harvested from `nous_runs/frontier-<p>*/runs/iter-*/inputs/*solution*.cpp`.)

**plain Claude** (driver loop, plateau early-stop):
```
python3 gen/frontier_gen.py <p> --agent claude --rounds 6    --out preds/p<p>.claude.json   # first batch
python3 gen/frontier_gen_costbudget.py <p> --agent claude --rounds 30 --out preds/p<p>.claude.json  # plateau-stop
```

**Claude cost-matched** (to Nous's per-task $):
```
python3 gen/frontier_gen_costbudget.py <p> --agent claude --rounds 200 --cost-budget <NOUS_$> --out preds/p<p>.claude_cm.json
```

**Engram-style** (fixed 3 agents × 3 rounds):
```
python3 gen/frontier_gen.py <p> --agent engram --out preds/p<p>.engram.json
```

**Engram cost-matched** (to Nous's per-task $, cap 40 agents, early-stop):
```
python3 gen/frontier_gen_costbudget.py <p> --agent engram --agents 40 --cost-budget <NOUS_$> --out preds/p<p>.engram.json
```

**Score / re-eval any solution (×3 for the ±5 judge noise):**
```
./.venv/bin/frontier eval algorithmic <p> <solution.cpp> --json   # read "score"
```

## 3. Per-task Nous cost (budgets used for cost-matching)
p0 $27 · p1 $46 · p5 $46 · p15 $32 · p211 $36 · p44 $29 · p9 $38
(derived via `~/nous_repo/.venv/bin/nous cost nous_runs/frontier-<p>*`).

## 4. Exact batch commands we ran
See `gen/drivers/`: `base3_seq.sh` (Claude+Engram on 211/44/9), `cm_engram_seq.sh` /
`cm_claude_seq.sh` (cost-matched converge pass), `cmfull_seq.sh` (full Nous-equal-budget pass).

## 5. Artifacts (every run's raw data)
`artifacts/preds/p<p>.<agent>.json` (score, cost, tokens, solution path, per-round history),
`artifacts/gen_logs/` (agent logs, Nous `nous_runs/` campaigns incl. per-arm solutions,
`llm_metrics.jsonl` with real $/tokens, Engram journals/knowledgebase, per-round histories).
So any table cell = re-run the command above, or re-score the persisted `solution.cpp`.

## New tasks (2026-10-01): p22 (algorithmic) + cloudcast (research)

Draw: `python3 gen/select_tasks.py --seed 43 --n 1 --exclude 0 1 5 9 15 44 47 147 185 192 211` -> 22.
cloudcast = the first research-track problem (Engram's own benchmark).

**p22** (algorithmic, same runners as above; Nous $4.85 -> Engram cost-budget 4.85):
```
python3 gen/frontier_gen.py 22 --agent nous --nous-iters 3 --out preds/p22.nous.json           # -> 100
python3 gen/frontier_gen.py 22 --agent claude --rounds 6 --out preds/p22.claude.json            # -> 0
python3 gen/frontier_gen_costbudget.py 22 --agent engram --agents 40 --cost-budget 4.85 --out preds/p22.engram.json  # -> 0
./.venv/bin/frontier eval algorithmic 22 <sol.cpp> --json    # re-eval best 3x
```

**cloudcast** (research track; metric = total_cost $, lower is better; score = 100/(1+cost)).
Local eval, no Docker/GPU: build the per-problem venv once, then use `gen/frontier_research_gen.py`:
```
python3 -m venv research/problems/cloudcast/.evalvenv
research/problems/cloudcast/.evalvenv/bin/pip install 'networkx>=3.0' 'numpy>=1.24' colorama 'pandas>=1.5' graphviz
python3 gen/frontier_research_gen.py cloudcast --agent nous   --nous-iters 3 --out preds/cloudcast.nous.json          # -> cost $626
python3 gen/frontier_research_gen.py cloudcast --agent claude --rounds 6 --out preds/cloudcast.claude.json            # -> cost $1107
python3 gen/frontier_research_gen.py cloudcast --agent engram --agents 40 --cost-budget 9.89 --out preds/cloudcast.engram.json  # -> cost $1077
# re-score any solution.py (deterministic): research/problems/cloudcast/.evalvenv/bin/python3 \
#   research/problems/cloudcast/evaluator.py --solution <sol.py> --spec research/problems/cloudcast/resources/submission_spec.json --out /tmp/r.json
```
Nous per-task $ (budgets used for cost-matching): p22 $4.85 · cloudcast $9.89 (via `nous cost nous_runs/<run_id>`).
Artifacts for both under `artifacts/{preds,nous_runs,gen_logs/newtasks}/`.

## Caveat
Scores have ~±5 run-to-run judge noise, and agent generations are stochastic (no fixed LLM seed), so
exact numbers vary run-to-run; the *regime* (headroom → Nous wins; saturated → tie) reproduces.
Nous persists all arms, so re-scoring the saved winning solution reproduces a cell deterministically.
