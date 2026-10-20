# Reproduce or extend the MLSys controlled study on a new machine

Start here: `REPORT.md` (results), `NOUS_LESSONS.md` (what it means for Nous), `PROGRESS.md` (every decision and fix,
in order), `runs/` (per-run artifacts). Nous issues found: #327, #328, #329.

## Layout

| Path | Purpose |
|---|---|
| `DESIGN.md` | Arms, tasks, oracle questions, analysis plan (written before any run) |
| `tasks/` | Exact task prompts + shared output contract given to every arm |
| `keys/` | Answer keys and held-out sets (pd sweep, dbg hidden checks + upstream patches, search exhaustive fronts) |
| `oracle/` | Scorers: `score_run.py` (driver), `pd.py`, `dbg.py`, `search.py`, `common.py`, `grid.py`, `report_figs.py` |
| `harness/` | `run_one.py` (one isolated run), `queue.py` (5 key slots), `loop_arm.py` (L2/Nous-prompt), `sandbox.py`, `proxy.py`, `cost_meter.py`, `status.py` |
| `runs/` | Compact per-run outputs (see `runs/README.md`) |
| `figures/` | Plots, grids, `results.json` |

## Setup (macOS; the harness uses `sandbox-exec`)

The harness assumes these absolute paths under `~/mlsys_runs`. Recreate them, or edit the constants in
`harness/*.py`, `oracle/pd.py` (`CLEAN_BLIS`) and `oracle/dbg.py` (`BASE`).

```bash
R=~/mlsys_runs; mkdir -p $R/{repos,keys,runs,launch,harness}
git clone https://github.com/inference-sim/inference-sim /tmp/isim

# task repos: single-commit snapshots (no history, so the dbg fix cannot be found via git)
for spec in "task-pd 4e88b20" "task-search 4e88b20" "task-dbg 4d75db2"; do set -- $spec
  mkdir -p $R/repos/$1 && git -C /tmp/isim archive $2 | tar -x -C $R/repos/$1
  (cd $R/repos/$1 && git init -q && git add -A && git -c user.name=b -c user.email=b@l commit -qm snapshot); done
cp <paper pdf "When to Disaggregate"> $R/repos/task-pd/docs/pd-disagg.pdf

# clean BLIS binary the oracle re-measures pd claims with (no .git, so no leak)
mkdir -p $R/repos/blis-pd-base && git -C /tmp/isim archive 4e88b20 | tar -x -C $R/repos/blis-pd-base
(cd $R/repos/blis-pd-base && go build -o blis main.go)

# keys + pinned Nous runtime (this branch), with the SDK-bundled Claude CLI
cp -r experiments/mlsys/keys/* $R/keys/
mkdir -p $R/nous && git archive HEAD | tar -x -C $R/nous
(cd $R/nous && uv venv -q .venv --python 3.11 && uv pip install -q --python .venv/bin/python -e .)
git rev-parse HEAD > $R/nous/NOUS_COMMIT
rm -rf /tmp/isim   # the full clone contains the dbg fix; never leave it readable
```

Go 1.24 must be at `/opt/homebrew/bin/go` (the oracle pins it; an old `/usr/local/go` broke the test suite once).

LLM gateway: `harness/run_one.py` reads five URL/key pairs from env (`SLOTS`: `NOUS_LITELLM_URL` + `KEY1..3`,
`NOUS_VPCINT_URL` + `KEY1..2`) via `zsh -ic`. Never inline keys.

## Run

```bash
cd experiments/mlsys/harness
python3 run_one.py dbg l2 9 0                  # one run: task arm rep slot
python3 queue.py ../main_cells.txt 0,1,2,3,4   # many runs, one per key slot; restart-safe
python3 status.py                              # live status + cost
```

Each run writes `~/mlsys_runs/runs/<task>/<arm>/rep<N>/`: `meta.json`, `oracle.json`, `ws/` (final repo),
`claude_cfg/` (all transcripts), `logs/`.

## Re-score / re-plot

```bash
cd experiments/mlsys/oracle
python3 score_run.py ~/mlsys_runs/runs/pd/nous/rep4   # one run
python3 report_figs.py ~/mlsys_runs/runs ../figures   # summary figures + results.json
python3 grid.py ~/mlsys_runs/runs ../figures          # per-task color grids
```

To audit the oracle edits, re-grade with the pre-run oracle: `git show f0481da:experiments/mlsys/oracle/<file>`.
Under it, all pd and search runs score O1 false.

## Rules we followed (keep them)

- **Every arm the same.** Same task text, sandbox, model family and CLI. No arm-specific prompts or fixes.
- **Fix only harness and oracle bugs.** Apply every oracle fix to all arms, rescore all runs, and log it in
  PROGRESS.md.
- **Verify by hand.** Read every score against the raw answer before trusting it.
- **Validate cost and isolation.** The meter must equal the CLI's `total_cost_usd`. Scan tool calls for access to
  keys, other runs or the network.
- **No live LLM calls in tests.** See the repo's `CLAUDE.md`.
