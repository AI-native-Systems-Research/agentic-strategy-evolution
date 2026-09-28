# AIOpsLab local setup (repro) — M1 / 64GB

Goal: kind cluster (ARM) + one light app + run a shipped baseline agent via litellm on one task.
Repo: https://github.com/microsoft/AIOpsLab (MIT). Requirements: python3.11, kind, kubectl, helm, poetry, a container runtime (Docker/colima).

## Step 0 — toolchain check
- docker 27.3.1 (colima 0.8.0), kind v0.20.0 (arm64), kubectl v1.31.3, helm v3.18.6, python 3.11.7 — OK
- poetry: MISSING → install via `curl -sSL https://install.python-poetry.org | python3.11 -` (pip `-e .` fallback)
- litellm: `OPENAI_BASE_URL=https://ete-litellm.ai-models.vpc-int.res.ibm.com`, `OPENAI_API_KEY` set → map to AIOpsLab `OPENAI_COMPATIBLE_BASE_URL/_API_KEY/_MODEL`
- CRITICAL (M1): colima VM must be sized up (~8 CPU / 24-32GB / 100GB disk) or the cluster+microservices won't fit despite 64GB host.

## Step 1 — clone + backend check (DONE)
- `git clone --recurse-submodules https://github.com/microsoft/AIOpsLab ~/aiopslab` (submodules incl. `hotelReservation` — mandatory).
- litellm proxy verified: `POST $OPENAI_BASE_URL/v1/chat/completions` with `Azure/gpt-4o` returns OK. Use this as `OPENAI_COMPATIBLE_*` for the pilot; fix ONE model across configs for real runs.
- Available models incl. `Azure/gpt-4o`, `claude-sonnet-4-6`, `aws/claude-sonnet-5`, gpt-5.x, gemini-3.x.

## Step 2 — colima resize + deps
- Resize: `colima stop && colima start --cpu 8 --memory 32` (disk persists at 100GB). Safe (0 running containers).
- Poetry: `curl -sSL https://install.python-poetry.org | python3.11 -`; `export PATH="$HOME/.local/bin:$PATH"`.
- GOTCHA: default `poetry install` tries to build **vllm 0.7.3** from source → fails on macOS ARM. vllm is in the optional `clients` group. Fix: `cd ~/aiopslab && poetry install --without clients` then `poetry run pip install groq` (top-level import in `clients/utils/llm.py`). All other client deps (openai, tiktoken, azure-identity, wandb, python-dotenv) are in main deps.

## Step 3 — kind cluster (DONE)
- `kind create cluster --config kind/kind-config-arm.yaml` (2 nodes: control-plane + worker, k8s v1.32). `kubectl wait --for=condition=Ready nodes --all` → Ready.
- `/run/udev` extraMount in the arm config resolves inside the colima Linux VM; no issue for misconfig/detection tasks.

## Step 4 — config + env (DONE)
- `aiopslab/config.yml`: `k8s_host: kind`, `qualitative_eval: false`, `print_session: true` (rest defaults).
- `.env` (write key from env, don't echo): `OPENAI_COMPATIBLE_BASE_URL=https://ete-litellm.ai-models.vpc-int.res.ibm.com/v1`, `OPENAI_COMPATIBLE_API_KEY=$OPENAI_API_KEY`, `OPENAI_COMPATIBLE_MODEL=Azure/gpt-4o`, `USE_WANDB=false`.
- Verify: `poetry run python -c "import aiopslab; from clients.generic_openai import GenericOpenAIAgent; from aiopslab.orchestrator import Orchestrator; print('IMPORT OK')"`.

## Step 5 — run one task (IN PROGRESS)
- Runner `~/aiopslab/run_one.py` (single pid) mirrors shipped `clients/generic_openai.py __main__`.
- `poetry run python run_one.py misconfig_app_hotel_res-detection-1`.
- First `init_problem` auto-installs OpenEBS + Prometheus (ns `observe`/`openebs`) then deploys hotel-reservation (ns `test-hotel-reservation`), injects fault, runs workload, then agent loop (max_steps=30). Slow on first image pulls.

### RESULT — end-to-end PASS (Azure/gpt-4o via litellm)
- Objective score (no LLM judge): `Detection Accuracy: Correct, TTD: 55.4s, steps: 8, in_tokens: 7882, out_tokens: 192`.
- Agent submitted `submit("Yes")` → `VALID_SUBMISSION`; auto fault-recovery + teardown ran; `[run_one] DONE`.
- Wall-clock note: first run includes OpenEBS/Prometheus install + image pulls (~several min); framework overhead ~265s. Subsequent runs faster (images cached).

## CONFIRMED for the plan
1. AIOpsLab runs locally on M1 (kind, CPU-only) — feasible.
2. Shipped baseline agents run via litellm (`OPENAI_COMPATIBLE_*`) → baselines free + same-model fairness + open-weight (RQ4) path all viable.
3. Objective, judge-free metrics available (Detection Accuracy, TTD, steps, tokens).

## NEXT
- Write the **Nous↔AIOpsLab adapter** (`init_context(problem_desc, instructions, apis)` + `async get_action(input)` → shell cmd or `submit(...)`) so Nous is scored by the same evaluator.
- Then run the ladder (vanilla / Science-superpowers / Engram / Curie / nous_prompt / nous_full) on a small set of hotel-res/social-net detection+localization tasks, fixed model + budget, 3 seeds on 1-2 for variance.
