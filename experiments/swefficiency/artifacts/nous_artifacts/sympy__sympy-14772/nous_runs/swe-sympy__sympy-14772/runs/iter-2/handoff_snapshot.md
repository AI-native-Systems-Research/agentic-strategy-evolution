# Handoff — sympy__sympy-14772 iter-2

## Goal

Apply the confirmed three-argument `pow()` optimization to `_legendre()` in `sympy/crypto/crypto.py`, plus an ablation removing the `a%p` pre-reduction. Measure speedup for both variants and verify all 38 covering tests pass.

## Key Discoveries

- **Iter-1 confirmed RP-1:** Replacing `pow(a%p, (p-1)//2) % p` with `pow(a%p, (p-1)//2, p)` at `crypto.py:2075` yields ~3,900x speedup. Treatment mean: ~19μs. All 38 tests pass.
- The `a%p` pre-reduction is functionally redundant: Python's three-arg `pow(a, exp, mod)` handles `a >= mod` internally. Verified for all edge cases: negative `a`, `a=0`, `a < p`, `a > p`.
- Microbenchmark shows `a%p` pre-reduction adds ~3% (~0.1μs), well within workload harness noise.
- In the workload, `a=87389 < p=131071`, so `a%p` is a no-op (just a comparison). The pre-reduction would only matter if `a > p`.
- The workload is entirely dominated by the single `pow()` call. After the fix, the remaining ~19μs is ~3μs for `pow` + ~16μs for workload harness overhead (process fork, timeit, etc.).

## System Interface

- **Build:** None needed — pure Python, just set `PYTHONPATH=$PWD`
- **Run baseline:** `cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Run tests:** `cd /testbed && /opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
- **Output format:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Mean: 0.0686s (campaign reference: 0.0743s)

## Code Map

- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition. The ONLY function under optimization.
- `sympy/crypto/crypto.py:2075` — The hot line: `sig = pow(a%p, (p - 1)//2) % p`. Change to three-arg pow here.
- `sympy/crypto/crypto.py:2076-2081` — Return value logic (1, 0, or -1). Unchanged.
- `sympy/crypto/crypto.py:2184,2187` — Call sites of `_legendre` in `gm_private_key`. Check here if tests fail.
- `sympy/crypto/crypto.py:2242` — Call site in `decipher_gm`: `res = lambda m, p: _legendre(m, p) > 0`.
- `sympy/crypto/tests/test_crypto.py` — 38 tests covering all crypto functions.

## Code Targets

### h-main: Three-argument pow (with pre-reduction)
- **File:** `sympy/crypto/crypto.py`
- **Line:** 2075
- **Change:** `pow(a%p, (p - 1)//2) % p` → `pow(a % p, (p - 1) // 2, p)`
- **Why this location:** This is the sole hot path. The function is called once per workload iteration.

### h-ablation: Three-argument pow (without pre-reduction)
- **File:** `sympy/crypto/crypto.py`
- **Line:** 2075
- **Change:** `pow(a%p, (p - 1)//2) % p` → `pow(a, (p - 1) // 2, p)`
- **Why this location:** Same line, but additionally removes the `a%p` to test if it's a measurable component.

## What I Tried That Didn't Work

- **System Python 3.11** cannot import this sympy version — fails with `ImportError: cannot import name 'Mapping' from 'collections'`. Must use the testbed conda env Python 3.6.
- **Running without PYTHONPATH=$PWD** — sympy imports fail without it since the repo isn't installed.
- **Microbenchmark of `a%p` removal** — showed ~3% difference at microbenchmark level but this is sub-noise for the full workload. Both variants produce ~19μs.

## What I Excluded and Why

- **No negative control arm** — The effect is ~3,900x (confirmed iter-1) and the mechanism is a complexity class change. A control regime adds no diagnostic value.
- **No dose-response arm** — The knob is binary (two-arg vs three-arg pow); no continuous parameter.
- **Other `pow()` calls in crypto.py** — All other pow calls (lines 1268, 1288, 1821, 1874, 2008, 2048) already use three-arg form. Only line 2075 has the anti-pattern. Line 2221 has `pow(a, b) % N` but it's in `encipher_gm`, not in the workload path.

## Evolution of Thinking

Iter-1 decisively confirmed the three-arg pow optimization. For iter-2, I explored whether additional micro-optimizations existed:
1. Checked all pow() calls in crypto.py — all others already use three-arg form.
2. Tested removing `a%p` pre-reduction — functionally safe but negligible performance impact.
3. Profiled the remaining ~19μs — ~3μs is pow itself, ~16μs is workload harness overhead (unfixable).
4. Concluded: the three-arg pow is THE optimization, and the ablation confirms the pre-reduction is irrelevant.

## Current Status

- **Validated:** Both variants (with/without `a%p`) produce ~3,900x speedup with all 38 tests green. Patches apply cleanly.
- **Uncertain:** Whether the `a%p` removal shows any statistically significant difference in the full workload — microbenchmarks suggest not, but the workload harness has ~1-2μs variance.
- **Suggested next:** The optimization is fully characterized. No further iterations needed for this workload. If the campaign expands scope, look at line 2221 (`pow(a, b) % N` in `encipher_gm`) — but it's not in the current workload.

## Warnings & Constraints

- **MUST use testbed Python:** `/opt/miniconda3/envs/testbed/bin/python` (3.6.13). System Python 3.11 cannot import this sympy version.
- **PYTHONPATH=$PWD is required** — the repo is not pip-installed.
- **Do NOT edit /tmp/workload.py** — the workload is read-only per campaign rules.
- **Speedup formula:** `0.0743 / measured_mean` (campaign baseline is 0.0743s, not the measured baseline).
- **Patch application:** Each arm modifies the same line (2075). Apply patches from clean state — do NOT stack them.
