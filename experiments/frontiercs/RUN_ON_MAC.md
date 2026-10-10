# Frontier-CS on a local Mac (parallel to the VM runs)

Goal: run additional Frontier-CS tasks + baselines locally without disturbing the VM's in-flight
Nous runs. The two environments are independent except for the shared litellm gateway.

## 0. Guardrails (read first)
- **Do NOT kill the reverse-tunnel processes** on this Mac (`ssh -R …:8443 …` + its keeper loop) and
  **do not let the Mac sleep** while the VM runs are going. The VM has no VPN; its LLM calls route
  through this Mac's tunnel. Killing it or sleeping stalls the VM runs. `caffeinate` is holding it awake.
- Local runs here use litellm **directly via VPN** (a separate path), so they won't touch the tunnel.
  The only shared resource is the litellm gateway itself — if you launch many concurrent agents,
  watch for HTTP 429 rate-limits (they'd slow both Mac and VM).
- Work on your **own git branch** (`frontier-mac`) or write results under
  `experiments/frontiercs/artifacts/mac/` so you don't collide with the VM-side commits on `aiopslab`.
- Do not edit `gen/frontier_gen.py` here while it may be edited VM-side; branch first.

## 1. Get the code
```bash
cd .../_nous_paper/agentic-strategy-evolution
git pull origin aiopslab
git checkout -b frontier-mac aiopslab
```

## 2. Install Frontier-CS locally (Docker Desktop required)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH"
mkdir -p ~/frontier && cd ~/frontier && git clone https://github.com/FrontierCS/Frontier-CS
cd Frontier-CS && uv sync
# judge image (verify it builds on arm64/M1 — it's Go+Node, should be fine):
#   the upstream Dockerfile has a broken `npm install -g npm@latest` line; no-op it if build fails:
#   sed -i '' 's/^RUN npm install -g npm@latest/RUN true/' algorithmic/Dockerfile
cd algorithmic && docker compose build   # ~1-2 min, ~1.8GB
```

## 3. litellm creds — DIRECT (no tunnel)
```bash
export ANTHROPIC_BASE_URL="https://ete-litellm.ai-models.vpc-int.res.ibm.com"   # :443 direct via VPN
export ANTHROPIC_AUTH_TOKEN="<token>"
export OPENAI_BASE_URL="https://ete-litellm.ai-models.vpc-int.res.ibm.com"
export OPENAI_API_KEY="<token>"
# sanity: curl -sS "$OPENAI_BASE_URL/v1/models" -H "Authorization: Bearer $OPENAI_API_KEY" | head -c 200
```

## 4. Run a task (same runner as the VM)
```bash
cd ~/frontier/Frontier-CS
FG=.../agentic-strategy-evolution/experiments/frontiercs/gen/frontier_gen.py
# plain-Claude baseline (driver-controlled loop, logs tokens+cost):
python3 "$FG" <problem_id> --agent claude  --rounds 6   --out ~/frontier/preds/p<pid>.claude.json
# Nous (5 iterations, native campaign):
python3 "$FG" <problem_id> --agent nous    --nous-iters 5 --out ~/frontier/preds/p<pid>.nous.json
```
Nous needs `nous` installed locally (its own venv) and the `claude` CLI on PATH; see the repo's
main setup. The runner writes per-round history + token/cost to `~/frontier/gen_logs/`.

## 5. Scoring / comparison
`frontier_gen.py` already re-evaluates and records `final_score` (+ Nous harvests best correct arm
from persisted `nous_runs/frontier-<pid>/runs/iter-*/inputs/*-solution.cpp`). The judge has ±~5
run-to-run variance, so **re-eval each final solution 2-3×** for a stable number:
```bash
./.venv/bin/frontier eval algorithmic <pid> <solution.cpp> --json   # read "score"
```

## Notes on task choice (from what we've seen)
- Prefer problems with **headroom** (p0 packing: ref ~76; p15 hard permutation gate) — they
  discriminate methodologies. **Avoid ceiling-saturating clamp problems** (p1: both agents hit ~97).
- 188 algorithmic problems total (`frontier list algorithmic`), plus `research` and `2.0` tracks.
