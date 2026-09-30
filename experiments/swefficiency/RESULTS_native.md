# SWE-fficiency: Nous vs plain Claude Code (native, in-container)

Model: `claude-opus-4-6` for both agents. 3 pure-Python sympy tasks. Objective = Speedup Ratio
(SR = model_speedup / gold_expert_speedup, correctness-gated on `PASS_TO_PASS`; an incorrect patch
is nullified to raw speedup 1.0x). Generation runs in the prebuilt task container; the authoritative
speedup comes from `swefficiency eval`.

## Setup that matters
- **Nous** runs natively inside the container in its git-worktree mode. The editable target package
  is uninstalled so a worktree's source is the code-under-test; `IS_SANDBOX=1` lets the Claude CLI
  run as root; the deliverable patch is chosen by independently replaying every candidate on a clean
  `/testbed` (not the agent's self-report).
- **Plain Claude** is the fair native peer: a single `claude -p` session edits `/testbed` in place
  (editable install intact), same workload/measurement/model/budget.
- **Isolated-workload fix (critical):** the official scorer rewrites the workload with
  `transform_to_isolated_workload(method="fork")` so each `timeit` repeat runs in a forked child.
  Our first Nous run measured the *raw* workload in one process, so sympy's `@cacheit` memoization
  faked huge speedups (sympy-10919 harvest 79x vs official 1.03x) and the loop optimized a caching
  artifact. Both runners now feed the agent the isolated (cold) workload, aligning self-measurement
  with the official metric.

## Results (official `swefficiency eval`)

| task  | gold    | NOUS raw        | NOUS isolated        | CLAUDE            |
|-------|---------|-----------------|----------------------|-------------------|
| 14772 | 4757x   | 2256x, SR 0.474 | 4095x, SR 0.861 ✓    | 4131x, SR 0.869 ✓ |
| 10919 | 18.8x   | 1.03x, SR 0.055 | 27.7x, FAILS tests   | 10.7x, SR 0.569 ✓ |
| 11675 | 172.7x  | fails tests     | fails tests          | 32995x, SR 191 ✓  |

✓ = passes PASS_TO_PASS. "fails tests" = fast but incorrect, speedup nullified.

## Verdict
Claude ≥ Nous on all three (wins 10919 and 11675, ties 14772). The isolated-workload fix rescued
14772 to parity (both agents converged on the canonical `pow(a, k, p)` modular-exponentiation
one-liner). But on 10919 and 11675, Nous's aggressive hypothesis search yields fast-but-incorrect
patches that fail `PASS_TO_PASS`, whereas plain Claude writes the correct fix directly.

**Interpretation.** These sympy tasks are "obvious-fix" performance bugs that a strong base agent
solves one-shot; Nous's scientific loop provides no edge here and can hurt (correctness breakage).
This mirrors the AIOpsLab finding (parity). Nous's value is not on tasks already within a base
agent's one-shot ability; it needs problems with genuine headroom where systematic experimentation
beats one-shot cleverness. Cherry-picking Nous-favorable SWE-fficiency tasks would be
reviewer-fragile, so we do not claim a SWE-fficiency win.

Artifacts: per-task campaigns persisted under `~/nous_swe/nous_artifacts/<iid>/` on the VM
(nous_runs, candidate patches, meta). Runners: `gen/swe_nous_native.py`, `gen/swe_claude_native.py`.
