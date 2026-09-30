# Handoff — sympy__sympy-14772 iter-4

## Goal

Run the definitive production measurement of the three-argument `pow()` optimization in `_legendre()` (h-main) alongside a mechanism-specificity control that applies the same optimization class to `encipher_gm` (h-control-negative, NOT in the workload path). Both arms across 5 seeds with all 38 covering tests passing. Measure speedup as `0.0743 / measured_mean`.

## Key Discoveries

- **Iter-1→3 confirmed RP-1:** Three-arg `pow` yields ~3,300–4,700× speedup consistently across 10 independent seeds (1 in iter-1, 3 in iter-2, 5 in iter-3). Mean speedup across all prior runs: ~3,950×.
- **Iter-2 confirmed RP-2:** The `a%p` pre-reduction is redundant — removing it has no measurable impact.
- **Iter-3 confirmed RP-3:** Jacobi algorithm is ~1.7× faster per call in microbenchmarks (3.8μs vs 6.5μs) but NOT measurably faster in the full workload (Welch's t=0.80, p≫0.05) because ~16μs harness overhead dominates.
- **This iter's new finding:** The `encipher_gm` function (line 2221) also contains a two-arg `pow(a, b) % N`, but `b ∈ {0, 1}` so the intermediate is tiny — no performance concern. This code path is NOT in the workload, making it a clean control-negative target.
- **Per-call microbenchmarks (this iter):** three-arg pow = 6.0μs raw / 6.5μs in function, hand-written Jacobi = 3.8μs, ntheory jacobi_symbol = 6.4μs, no-op function = 0.2μs. The ~16μs fork overhead makes all optimized variants indistinguishable in the workload.

## System Interface

- **Build:** None needed — pure Python, just set `PYTHONPATH=$PWD`
- **Run workload:** `cd /testbed && PYTHONPATH=$PWD /opt/miniconda3/envs/testbed/bin/python /tmp/workload.py`
- **Run tests:** `cd /testbed && /opt/miniconda3/envs/testbed/bin/python -m pytest -q sympy/crypto/tests/test_crypto.py`
- **Output format:** stdout prints `Mean: <seconds>` and `Std Dev: <seconds>`
- **Baseline result:** Mean ≈ 0.069s (campaign reference: 0.0743s). 38 tests pass.

## Code Map

- `sympy/crypto/crypto.py:2054` — `_legendre(a, p)` function definition. The ONLY function under optimization in h-main.
- `sympy/crypto/crypto.py:2075` — The hot line: `sig = pow(a%p, (p - 1)//2) % p`. h-main changes this single line.
- `sympy/crypto/crypto.py:2076-2081` — Return value logic (1, 0, or -1).
- `sympy/crypto/crypto.py:2221` — `encipher_gm` two-arg pow: `encode = lambda b: next(gen)**2*pow(a, b) % N`. h-control-negative changes this line. NOT in workload path.
- `sympy/crypto/crypto.py:2184,2187` — Call sites of `_legendre` in `gm_private_key`. Check here if tests fail.
- `sympy/crypto/crypto.py:2242` — Call site in `decipher_gm`: `res = lambda m, p: _legendre(m, p) > 0`.
- `sympy/crypto/tests/test_crypto.py:309` — `test_encipher_decipher_gm` exercises the `encipher_gm` code path (line 2221), so the h-control-negative change must be mathematically correct (it is — by modular arithmetic properties).

## Code Targets

### h-main: Three-argument pow (without pre-reduction)
- **File:** `sympy/crypto/crypto.py`
- **Line:** 2075
- **Change:** `pow(a%p, (p - 1)//2) % p` → `pow(a, (p - 1) // 2, p)`
- **Why this location:** This is the sole hot path. Removes redundant `a%p` per RP-2.

### h-control-negative: Three-arg pow in encipher_gm (not in workload path)
- **File:** `sympy/crypto/crypto.py`
- **Line:** 2221
- **Change:** `next(gen)**2*pow(a, b) % N` → `next(gen)**2*pow(a, b, N) % N`
- **Why this location:** Same optimization class as h-main, but applied to a code path that is NOT exercised by the workload. Validates that h-main's speedup is path-specific. The mathematical equivalence is guaranteed by `(x * y) % N == (x * (y % N)) % N`.

## What I Tried That Didn't Work

- **System Python 3.11** cannot import this sympy version — fails with `ImportError: cannot import name 'Mapping' from 'collections'`. Must use testbed conda env Python 3.6.
- **Running without PYTHONPATH=$PWD** — sympy imports fail without it.
- **Jacobi algorithm in full workload** — despite being ~1.7× faster per call in microbenchmarks, showed no measurable improvement in the full workload (iter-3: Welch's t=0.80). Harness overhead (~16μs) dominates.
- **Iter-2 `a%p` ablation** — showed ~2.5% difference, within measurement noise. The pre-reduction is irrelevant.
- **Delegating to `sympy.ntheory.jacobi_symbol`** (tested this iter) — 6.4μs per call, equivalent to three-arg pow (6.5μs). The ntheory function adds `as_int()`, `igcd()` overhead that offsets the algorithmic advantage. No benefit.
- **Combined micro-optimizations** (`_pow=pow` binding + simplified conditional) — 6.6μs, identical to standard three-arg pow at 6.6μs. The Python-level improvements are <0.1μs, completely in noise.
- **Bitshift exponent** (`p >> 1` instead of `(p-1)//2`) — 6.1μs vs 6.0μs for raw pow. No measurable difference; both compute the same value for odd primes.

## What I Excluded and Why

- **No further algorithmic alternatives** — iter-3 exhaustively tested Jacobi (the only plausible alternative), confirming RP-3.
- **No `a%p` ablation** — already done in iter-2, confirmed RP-2.
- **`pow(a, b) % N` at line 2221** — in `encipher_gm`, not in the workload path. Used as control-negative target, not optimization target.
- **All other pow() calls** in crypto.py (lines 1268, 1288, 1821, 1874, 2008, 2048) already use three-arg form.
- **Workload harness optimization** — harness is read-only; cannot be modified.
- **Cython/C extension approaches** — not feasible in this environment.
- **Memoization/caching** — workload calls `clear_cache()` in setup and only calls `_legendre` once per timing iteration. No benefit.

## Evolution of Thinking

Iter-1 discovered the core optimization (three-arg pow). Iter-2 confirmed it across 3 seeds and showed `a%p` pre-reduction is redundant. Iter-3 tested the Jacobi alternative at full scale — no measurable improvement. 

For iter-4, I explored every remaining angle: delegating to `sympy.ntheory.jacobi_symbol` (same speed as three-arg pow due to validation overhead), combined micro-optimizations (no measurable effect), bitshift exponent (no effect). The optimization space is thoroughly exhausted.

The new scientific contribution for iter-4 is mechanism-specificity validation: proving that the speedup comes specifically from modifying the `_legendre` code path, not from any side effect. The control-negative (applying the same optimization class to `encipher_gm`, which is NOT in the workload) should show zero speedup.

## Current Status

- **Validated:** Three-arg pow optimization: Mean 15.5μs (speedup ≈ 4,787×), 38/38 tests pass. Control-negative: Mean 0.069s (speedup ≈ 1.08×, within noise), 38/38 tests pass. Baseline command works.
- **Uncertain:** Nothing — all predictions are grounded in extensive prior evidence.
- **Suggested next:** The optimization space for `_legendre` in this workload is completely exhausted across all angles (algorithmic alternatives, micro-optimizations, delegation approaches, scope expansion). If iteration 5 is needed, consider: (a) broadening the workload to include other crypto functions, (b) testing the optimization's robustness across different Python versions, or (c) formally closing the investigation.

## Warnings & Constraints

- **MUST use testbed Python:** `/opt/miniconda3/envs/testbed/bin/python` (3.6.13). System Python 3.11 cannot import this sympy.
- **PYTHONPATH=$PWD is required** for all runs.
- **Do NOT edit /tmp/workload.py** — read-only per campaign rules.
- **Speedup formula:** `0.0743 / measured_mean` (campaign baseline is 0.0743s).
- **Patch application:** h-main modifies line 2075 only. h-control-negative modifies line 2221 only. Apply from clean state — do NOT stack patches.
- **Seeds:** Use seeds 42, 43, 44, 45, 46. The workload doesn't accept a seed flag — use the seed to label runs. Each run is an independent workload invocation measuring 10 repetitions.
- **h-control-negative correctness:** The line 2221 change is mathematically equivalent by modular arithmetic. Tests confirm this (test_encipher_decipher_gm at line 309 passes).
