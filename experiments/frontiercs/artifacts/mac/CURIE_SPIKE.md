# Curie spike result — BLOCKED, not wired

Date: 2026-09-30. Machine: Mac (arm64, Docker via Colima). Repo: github.com/Just-Curieous/Curie
(cloned to `~/frontier/Curie`), paper arXiv:2502.16069.

Per the plan we spiked before wiring `--agent curie`. Verdict: **(a) works, (b) is prose-only, and
running Curie end-to-end on this Mac is blocked by hardcoded Azure/DinD assumptions.** We document
and stop, per instructions ("if not, document the blocker and stop").

## (a) LLM via our litellm proxy with opus — WORKS
`litellm.completion(model="openai/claude-opus-4-6", api_base="https://ete-litellm.ai-models.vpc-int.res.ibm.com/v1", api_key=<token>)`
returned a valid completion ("PONG"). Curie's model seam is `ChatLiteLLM(model=os.environ["MODEL"])`
(`curie/model.py:128`), so `MODEL="openai/claude-opus-4-6"` + `OPENAI_BASE_URL`/`OPENAI_API_KEY`
routes through the same litellm path. The model layer is fine.

## (b) Inject external scorer (frontier eval) as objective — only prose-level
Curie has **no programmatic scorer hook** (no `objective_fn` / `score_command` config field). The
objective is a natural-language question (`-q` / `--question_file`); an external scorer is injected by
*describing in prose* how the agent should run it and self-report the number (see shipped
`benchmark/.../q1_simple_relation.txt`). So our `frontier eval` could be wired only as an untrusted,
LLM-mediated contract, not a guaranteed metric call. That is materially weaker than how claude/engram/
nous get a hard, driver-measured judge score, and would be hard to defend as an apples-to-apples baseline.

## Why it can't run end-to-end here (the real blocker)
Even setting (b) aside, launching Curie on this Mac requires forking it to undo several hardcoded
assumptions:

1. **Hardcoded docker socket mount.** `curie/main.py:154` mounts `-v /var/run/docker.sock:/var/run/docker.sock`.
   That path does not exist under Colima (socket is `~/.colima/default/docker.sock`). Curie spawns a
   per-iteration container that itself needs Docker (runs OpenHands + nested exec) — DinD via socket
   mount under Colima is fragile and not what the code assumes.
2. **Azure hardwiring.** `curie/main.py:198-201` and `curie/experiment.py:118-121` `sed`-inject an
   `organization` id into `litellm/llms/azure/azure.py` *inside the container*, at fixed line numbers.
   On a non-Azure OpenAI-compatible proxy this is at best dead code and at worst corrupts litellm if
   the pinned line numbers drift.
3. **Context-length default.** `curie/utils.py:31` returns 30000 for any model not in a 3-entry dict
   (gpt-4o, gpt-4o-mini, one Bedrock Claude). opus would be treated as 30k context → prompt truncation.
   Needs a source patch.
4. **Two LLM layers + big image.** Both the orchestrator (`env.sh`) and the in-container OpenHands
   coding agent (`workspace/config.toml`, generated *with* the Azure patch applied) must be pointed at
   our proxy, and the `exp-agent-image` (OpenHands) must be built. `pip install curie-ai` alone is
   insufficient — the runnable workflow needs the git checkout (prompts/configs/Dockerfiles).

## Decision
Do **not** wire `--agent curie`. It would require a substantial fork (≥4 hardcoded Azure/Linux/DinD
fixes) plus a degraded prose-only scorer contract, which the plan explicitly said to avoid ("if not,
document the blocker and stop"). The controlled comparison proceeds with the three agents that share
the identical driver + judge seam: **vanilla claude, engram-style, nous.**

If a Curie baseline is later required, the honest options are (1) fork Curie to fix 1–4 above and run
it on a native-Linux Docker host (not Colima), or (2) build a faithful Curie-style *reimplementation*
on the same driver loop (as we did for Engram) — but that is a different deliverable and was not what
the spike authorized.
