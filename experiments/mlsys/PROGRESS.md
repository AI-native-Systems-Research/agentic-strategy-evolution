# MLSys controlled experiments: progress log

Times are local (EDT).

## 2026-10-19

- 18:40 Branch `mlsys-exp` from `main` (`decbde7`). Nous `main` installed in its own venv (`.venv-mlsys`,
  claude-agent-sdk 0.2.168). Mac kept awake with `caffeinate`.
- 18:55 pd-disagg answer key: our own BLIS sweep (BLIS `4e88b20`, 40 rate points x 5 seeds x AL/AD = 200 runs, plus
  600 held-out runs on 3 unseen workload/topology configs). Result: ITL = alpha/(1-lambda W), W fit on rates 2-60,
  max error 1.12% (AL) / 0.65% (AD) on 2-60; overpredicts at high rate: AL +14.3% at 100, +28.3% at 120, +65% at 150;
  AD first >10% at 110. AD TTFT > AL TTFT at every rate; AD ITL < AL ITL at every rate >= 2. Seed std ~0.001 ms.
  Independently reproduces the original campaign's "+29% at rate 120".
- 19:05 Debugging task: BLIS snapshot at `4d75db2` (parent of fix `d8271ee`), single-commit repo with no history
  (the fix cannot be found via git). Bug reproduces from the CLI: total_output_tokens 114630 with KV=600 vs 105082
  with a large KV, same 200 requests. Hidden checks (6 preemption cases + 2 no-pressure regression cases): buggy build
  fails 6/8, upstream fix passes 8/8. Upstream test fails on the buggy build (as it should). Self-review caught one
  invalid hidden case (PD cluster dropped 148 requests even on the fixed build); replaced.
- 19:15 blis-search answer key: our own exhaustive sweeps (1800 configs each) for the main config (qwen3-14b, rate 100)
  and two held-out configs (llama-3.1-8b rate 100, qwen3-14b rate 50). Exact 4-objective hypervolume (same objectives
  and reference point as the original campaign). Reference: random search with 200 evals reaches 0.944 mean HV
  ratio (min 0.855) on the main config. Trade-off facts T1-T4 locked in `keys/search/facts.json`.
- 19:20 Task prompts and shared output contract written (`tasks/`). Keys + prompts committed before any run.
