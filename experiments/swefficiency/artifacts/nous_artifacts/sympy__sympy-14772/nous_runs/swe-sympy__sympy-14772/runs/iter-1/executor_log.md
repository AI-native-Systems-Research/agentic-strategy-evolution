I'll execute this experiment systematically. Let me start with Phase 1: Prepare.Good. I can see the target line. Let me now run the baseline and validate it works, then create the patch.

## Step 1-2: Validate Baseline & Run TestsBaseline works (Mean: 0.0713s). The test runner has a conflict. Let me check a different way to run tests:The issue is a conflicting conftest. Let me try running just the crypto test file directly:The conftest.py has a conflict with the installed pytest version. Let me check if there's a conftest plugin also installed:The conftest.py is being picked up regardless. It seems like there's a pytest plugin that also adds `--quickcheck`. Let me check if there's a conftest issue from the pytest 7.0 upgrade and just fix it:The issue is that the conftest.py is adding `--quickcheck` but something else already added it. Let me check if the main repo's conftest has the same conflict:It works from /testbed but not from the worktree! The conftest.py seems to interact differently. Let me check if there's a duplicate conftest or a symlinking issue:The issue is with the conftest in the worktree being loaded twice. Let me try a workaround — running tests directly with Python's test framework, or from within the crypto tests directory:All 38 tests pass at baseline. Now let me try to fix the pytest issue for convenience, or just use this direct approach. Let me check if the issue is the worktree path causing conftest to load twice:`--noconftest` works. I'll use that flag for pytest runs. Now let me proceed.

## Step 3: Create Patch for h-mainNow smoke-test the treatment:Mean ~0.000021s — that's a massive speedup (~3500x). Let me verify tests pass:All 38 tests pass with the treatment. Now save the patch:Now reset and verify patch applies:## Step 4: Write experiment_plan.yaml## Phase 2: Execute the plan

Now I'll run all conditions. Let me execute them:Baseline runs: 0.0706, 0.0707, 0.0711 — very consistent. Now the treatment runs:Treatment runs: 0.0000191, 0.0000186, 0.0000194 — all ~19 microseconds. Speedup is enormous. 

Now run the covering tests with treatment:All 38 tests pass. Let me verify baseline vs treatment aren't byte-identical (they clearly aren't — orders of magnitude difference):

Baseline means: 0.0706, 0.0707, 0.0711 (avg ~0.0708s)
Treatment means: 0.0000191, 0.0000186, 0.0000194 (avg ~0.0000190s)

Speedup (campaign baseline 0.0743 / treatment mean): 0.0743 / 0.0000190 ≈ **3,910x**

## Phase 3: Analyze and Write Findings## Phase 4: Extract Principles## Phase 5: ValidateTwo schema issues — let me fix them:Now fix findings.json — remove the top-level `mode` field:Validation passes.

## Summary

**Experiment: legendre-modpow-optimization, iteration 1**

**h-main: CONFIRMED** — Replacing two-argument `pow(a%p, (p-1)//2) % p` with three-argument `pow(a%p, (p-1)//2, p)` in `sympy/crypto/crypto.py:2075` produces a decisive speedup:

| Metric | Baseline | Treatment | 
|---|---|---|
| Mean runtime (3 runs × 10 reps) | 0.0708s | 0.0000190s |
| Speedup vs campaign baseline (0.0743s) | 1.0x | **3,906x** |
| Tests passing | 38/38 ✅ | 38/38 ✅ |

**Mechanism confirmed:** Python's two-argument `pow(87389, 65535)` constructs a ~1.1 million-bit intermediate integer before the final `% 131071`. Three-argument `pow(87389, 65535, 131071)` uses CPython's C-level modular exponentiation, keeping all intermediates bounded to ~17 bits. This is an algorithmic complexity class change.

**Artifacts produced:**
- `patches/h-main.patch` — one-line change
- `results/h-main/` — 6 measurement files + 1 test result
- `findings.json` — CONFIRMED status with metadata
- `principle_updates.json` — extracted principle about three-arg pow
- `experiment_plan.yaml` — fully reproducible plan