# Frontier-CS Setup Notes (algorithmic track)

VM: ubuntu@169.63.182.123 (x86_64 Ubuntu 24.04, 8 vCPU / 31GB RAM).
All work lives under `~/frontier/`. Repo: github.com/FrontierCS/Frontier-CS (arXiv 2512.15699, ICML26).
Everything below is verified on the box unless marked otherwise.

## TL;DR
- The generate -> evaluate -> score loop WORKS. Problem 0 (`reference.cpp`) scored **81.18**.
- Eval is Docker-based (a Node/go-judge sidecar). NO GPU needed for algorithmic.
- Two repo bugs to know about (fixed / worked around below):
  1. README shows `frontier eval algorithmic <id> sol.cpp --unbounded`. That flag does
     NOT exist on `frontier eval` (it is a research/README artifact). Eval ALWAYS prints
     both bounded score and `score_unbounded` automatically; use `--json` to capture both.
  2. The judge Docker image failed to build out of the box: `RUN npm install -g npm@latest`
     pulls npm@12 which needs Node 22+, but the Dockerfile installs Node 20. Patched (see below).

## 1. Install (exact commands that worked)
```bash
# uv (repo recommends it)
curl -LsSf https://astral.sh/uv/install.sh | sh          # -> ~/.local/bin/uv (0.12.20)
export PATH="$HOME/.local/bin:$PATH"

# clone + sync (creates .venv, installs 153 pkgs, incl anthropic/openai/datasets)
cd ~/frontier && git clone https://github.com/FrontierCS/Frontier-CS
cd ~/frontier/Frontier-CS && uv sync
# CLI is then at ~/frontier/Frontier-CS/.venv/bin/frontier  (or: uv run frontier ...)
```
System python3 is 3.12 (>=3.11 required, fine). `pip install -e .` also listed as alt.

### Docker compose plugin was MISSING (blocker, fixed)
`docker compose` was not installed (only the `trust` cli-plugin was present), and the runner
shells out to `docker compose up -d`. Installed the v2 plugin into the user dir (no system change):
```bash
mkdir -p ~/.docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.39.1/docker-compose-linux-x86_64 \
     -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
docker compose version   # -> v2.39.1
```

### Judge image build fix (Dockerfile patch)
File: `~/frontier/Frontier-CS/algorithmic/Dockerfile` (original backed up at `~/frontier/Dockerfile.orig.bak`).
Changed line 30 from `RUN npm install -g npm@latest` to a no-op echo. The bundled package.json
runs fine on the npm 10 that ships with Node 20. After the patch the image builds cleanly:
```bash
cd ~/frontier/Frontier-CS/algorithmic && docker compose build   # ~1-2 min, image = 1.81 GB
```

## 2. Real CLI surface (verified)
```
frontier {eval,batch,list,show,harbor}
frontier list algorithmic            # 188 problems (ids like 0,1,5,...); list 2.0 ; list research
frontier show algorithmic <id>       # prints statement.txt
frontier eval algorithmic <id> <sol.cpp> [--backend docker|skypilot] [--json] [-q] [--judge-url URL] [--timeout N]
frontier eval research <name> <sol.py> [--backend docker]
frontier harbor trial <track> <id> -a <agent> -m <model> [--json]   # agent runs (do NOT use yet)
```
- Algorithmic defaults to `--backend docker`; research defaults to skypilot.
- NO `--unbounded` flag on eval. Bounded + unbounded both emitted; grab via `--json`
  (fields `score` and `score_unbounded`).

## 3. Mechanics
### Scoring
- Judge (go-judge behind a Node/Express orchestrator, port 8081) returns `score` (0-100,
  clipped) and `scoreUnbounded` (uncapped, for OpenEvolve-style evolution). **Higher is better.**
- If bounded == unbounded, the solution is below the 100 cap (normal). Unbounded can exceed 100.
- Score is subtask/case based. Most algorithmic problems have a custom `chk.cc` checker that
  gives PARTIAL credit (continuous), e.g.:
  - Problem 0: per-test `score = 1e5 * (sum k_i)/(W*H)` (packing density), averaged over 70 cases.
  - Problems 1/15: `100 * clamp((you - baseline)/(best - baseline), 0, 1)`, averaged.
  - Problem 5: `Ratio = points/10` per case.
- A score of 0 can still be `status=success` (means it ran but earned no credit, e.g. invalid
  output on this test). Failures surface via `status`/`message`, not the score.
- Public test cases per problem vary: the README says 1-3 for most, but problem 0 ships all 70 (140 .in/.ans files); the 81.18 score is over all 70. Full private suite runs on maintainers servers.
  `.in/.ans` pair is used locally... actually prob 0 ships 140 files = 70 cases). Full/private
  test suite runs on maintainers servers.

### Task layout (what a solver gets)
`algorithmic/problems/{id}/`:
- `statement.txt` (Markdown problem statement; input/output format, limits, scoring rule)
- `config.yaml` (`type: default|interactive`, `time:` e.g. 2s, `memory:` e.g. 256m, subtasks/n_cases)
- `testdata/{1..N}.in` + `{1..N}.ans` (public cases)
- `chk.cc` (testlib checker) or `interactor.cc` (interactive)
- `examples/reference.cpp` + `examples/gpt5.cpp` -- ONLY problem 0 ships these.
- Language: C++17 only, single .cpp file. `tag.txt` exists but is empty for these.

### submit.sh iterative-feedback (Harbor agent path, for LATER)
Lives in the Harbor task template, not the plain eval path:
`adapters/frontier-cs-algorithm/src/frontier_cs_algorithm/task-template/environment/`
- `submit.sh` -> `exec python3 /app/submit.py "$@"` (thin wrapper; optional arg = alt solution path,
  default `/app/solution.cpp`).
- During a trial the agent runs `bash /app/submit.sh` as many times as it wants. Each call POSTs the
  code to a judge sidecar `POST $JUDGE_URL/evaluate` with `submission_role="agent"`, logs a record to
  `/logs/agent/submissions.jsonl`, and prints `status / score (raw/100) / detail / metrics` to stdout
  so the agent gets feedback. Exit 0 even on low score; 2=missing/empty file, 3=judge fail.
- Final scoring (`tests/evaluate.py`, the Harbor verifier): submits the final `/app/solution.cpp`
  with `submission_role="final"`, then takes **the HIGHER of the final score and the best successful
  iterative "agent" submission**. Reward = score/100 (0..1). Written to
  `/logs/verifier/reward.txt`, `reward.json`, `judge_result.json`. So an agent that regresses at the
  end is not penalized; its best mid-run submission still counts.

### Docker / GPU
- Docker REQUIRED for algorithmic (privileged go-judge container, `shm_size 4g`). Auto-started by
  `frontier eval` via `docker compose up -d` in `algorithmic/`. Container name `Competitive-Programming`.
- Image `algorithmic-lightcpverifier:latest` = **1.81 GB**, build ~1-2 min after fix.
- NO GPU for algorithmic. (Research track may need GPU + SkyPilot; not set up here.)
- DISK IS TIGHT: ~5 GB free after the judge image. There are ~28 GB of unrelated
  `swefficiency`/`swenous` images from another project on the box; do not touch without asking, but
  they are the main disk pressure.

## 4. Proof the loop works (exact commands + observed scores)
```bash
cd ~/frontier/Frontier-CS
export PATH="$HOME/.local/bin:$PATH"

# THE single-task eval command:
./.venv/bin/frontier eval algorithmic 0 algorithmic/problems/0/examples/reference.cpp --json
```
Observed (JSON):
- reference.cpp (human best):  score = **81.18**, score_unbounded = 81.18, status=success, ~30s
- gpt5.cpp (bundled):          score = **0.0**  (invalid/low on this case), status=success
- naive0.cpp (I wrote it, stack-in-bands, no transforms): score = **25.12**, status=success

`~/frontier/naive0.cpp` is my trivial correct baseline (valid packing, low density) used to
confirm partial credit + headroom. reference beats naive by ~56 points.

## 5. Candidate problems for an agent bake-off (naive-low, headroom-high)
All are `type: default`, C++17, partial-credit optimization checkers -> ideal for iterative climbing.
| id | title | time | cases | scoring rule | why good |
|----|-------|------|-------|--------------|----------|
| 0  | Pack the Polyominoes (reflections) | 2s | 70 | 1e5*(sum k)/(W*H) density | proven: naive 25.1, human 81.2, gpt5 0 -> huge headroom, has reference to compare |
| 1  | Treasure Packing (bounded knapsack, JSON) | 1s | 20 | 100*clamp((you-baseline)/(best-baseline)) | must beat NSA baseline to score; smooth partial credit |
| 15 | Lexicographically-smallest permutation via 3-cut swaps | 1s | 10 | 100*clamp((4n-ops)/(4n-best)) | minimize op count; clear improvement gradient |
| 5  | Hamiltonian / longest simple path (directed) | 4s | 10 | Ratio = points/10 (longer path = more) | NP-hard, naive short path scores low, lots of room |
| 8  | The Empress | 2s | 100 | ratio-based (chk.cc has Ratio) | 100 cases, fine-grained partial credit |

Recommended proof/primary target: **problem 0** (only one with bundled reference + gpt5 to
benchmark against, and the naive-vs-human gap is already measured).

## Blockers hit (all resolved)
1. `docker compose` plugin missing -> installed v2 plugin in ~/.docker/cli-plugins.
2. Judge Dockerfile npm@latest vs Node20 -> patched line 30 (backup at ~/frontier/Dockerfile.orig.bak).
3. README `--unbounded` flag on eval does not exist -> use `--json` (both scores always emitted).

## LLM gateway (verified reachable, NOT used yet)
`source ~/.nous_env` then `curl "$OPENAI_BASE_URL/v1/models" -H "Authorization: Bearer $OPENAI_API_KEY"`
returns JSON. Note: model list advertises `claude-opus-4-8` (task said 4-6); confirm the exact id later.
